from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_models_catalog():
    data = client.get("/api/models").json()
    assert len(data["models"]) >= 15
    assert "OpenAI" in data["providers"]


def test_recommend_with_constraints():
    r = client.post("/api/recommend", json={
        "use_case": "coding",
        "weights": {"quality": 60, "cost": 30, "speed": 10},
        "constraints": {"open_source_only": True},
        "chosen_id": "gpt-5.1",
    }).json()
    assert r["results"], "expected at least one open-source recommendation"
    assert all(res["model"]["source"] == "open" for res in r["results"])
    assert r["chosen_vs_suggested"]["deltas"]
    for res in r["results"]:
        assert res["reasons"] and 0 <= res["score"] <= 100


def test_compare_and_similar():
    r = client.post("/api/compare", json={"model_ids": ["gpt-5.1", "claude-opus-4.5"]}).json()
    assert len(r["radar"]) == 7
    s = client.get("/api/models/gpt-5.1/similar").json()
    assert len(s["similar"]) == 3


def test_playground_and_analytics():
    r = client.post("/api/playground", json={
        "model_ids": ["claude-haiku-4.5"], "prompt": "Summarize our Q3 report"}).json()
    assert r["results"][0]["cost"] > 0
    a = client.get("/api/analytics/summary").json()
    assert a["kpis"]["requests_total"] > 0
    assert len(a["daily"]) >= 14


def test_openai_compatible_gateway_auto_routing():
    r = client.post("/v1/chat/completions", json={
        "model": "auto",
        "messages": [{"role": "user", "content": "hello"}],
    }).json()
    assert r["object"] == "chat.completion"
    assert r["modelect"]["routed"] is True
    assert r["usage"]["total_tokens"] > 0
