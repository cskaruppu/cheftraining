import os

os.environ["REGISTRY_OFFLINE"] = "1"  # deterministic snapshot mode in tests

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


def test_registry_connectors():
    r = client.get("/api/registry/models").json()
    registries = {e["registry"] for e in r["entries"]}
    assert registries == {"huggingface", "openrouter"}
    assert all(s["mode"] == "snapshot" for s in r["sync"])
    # channel dedupe: known models match curated ids
    hf_phi = next(e for e in r["entries"] if e["id"] == "hf/microsoft/phi-4")
    assert hf_phi["matches_curated"] == "phi-4"
    assert hf_phi["source"] == "open" and hf_phi["license"] == "mit"
    or_sonnet = next(e for e in r["entries"] if "claude-sonnet" in e["id"])
    assert or_sonnet["matches_curated"] == "claude-sonnet-4.5"
    assert or_sonnet["input_price"] == 3.0  # per-1M normalization
    # genuinely new models stay unmatched (registry-only cards)
    kimi = next(e for e in r["entries"] if "kimi" in e["id"])
    assert kimi["matches_curated"] is None and kimi["rated"] is False
    # source filtering
    only_hf = client.get("/api/registry/models?sources=huggingface").json()
    assert {e["registry"] for e in only_hf["entries"]} == {"huggingface"}


def test_smallest_capable_mode():
    # low floor: Phi-4 (14B SLM, chat 79) is the smallest capable model
    r = client.post("/api/recommend", json={
        "use_case": "chatbot", "mode": "smallest_capable", "quality_floor": 78,
    }).json()
    assert r["mode"] == "smallest_capable" and r["quality_floor"] == 78
    assert r["results"][0]["model"]["id"] == "phi-4"
    assert "Smallest capable" in r["results"][0]["reasons"][0]
    # raise the floor: SLMs drop out and land in excluded with the reason
    r2 = client.post("/api/recommend", json={
        "use_case": "chatbot", "mode": "smallest_capable", "quality_floor": 85,
    }).json()
    assert all(res["model"]["quality"]["chat"] >= 85 for res in r2["results"])
    assert any("below the 85 floor" in e["reason"] for e in r2["excluded"])
    # catalog carries size metadata
    models = client.get("/api/models").json()["models"]
    phi = next(m for m in models if m["id"] == "phi-4")
    assert phi["size_class"] == "slm" and phi["params_b"] == 14


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


def test_serving_profiles():
    r = client.get("/api/models/llama-4-maverick/profiles").json()
    assert r["self_hostable"] is True
    assert len(r["profiles"]) >= 2
    assert any(p["recommended"] for p in r["profiles"])
    closed = client.get("/api/models/gpt-5.1/profiles").json()
    assert closed["profiles"] == []


def test_deployment_lifecycle():
    r = client.post("/api/deployments", json={
        "model_id": "phi-4", "profile_id": "balanced", "name": "phi4-prod"}).json()
    assert r["api_key"].startswith("mk-")
    assert r["status"] in {"scheduling", "pulling_weights", "warming_up", "ready"}
    assert r["cluster_id"], "auto-placement should assign a cluster"
    listed = client.get("/api/deployments").json()["deployments"]
    assert any(d["id"] == r["id"] for d in listed)
    assert client.post("/api/deployments", json={
        "model_id": "gpt-5.1", "profile_id": "balanced", "name": "x"}).status_code == 400
    assert client.delete(f"/api/deployments/{r['id']}").json()["deleted"] == r["id"]


def test_fleet_and_placement():
    fleet = client.get("/api/clusters").json()["clusters"]
    assert len(fleet) == 3
    assert all(c["agent_status"] == "connected" for c in fleet)
    assert all(g["free"] == g["count"] - g["used"] for c in fleet for g in c["gpus"])

    # H100 profile: cloud-burst has 4 free H100s at spot pricing -> recommended
    p = client.post("/api/placement", json={
        "model_id": "llama-4-scout", "profile_id": "balanced"}).json()
    assert p["recommended"]["cluster_id"] == "cloud-burst"
    assert any("free" in r for r in p["recommended"]["reasons"])

    # EU residency: only the EU cluster qualifies; it has 1 free L40S
    p_eu = client.post("/api/placement", json={
        "model_id": "mistral-small-3.2", "profile_id": "balanced",
        "residency": "eu"}).json()
    assert p_eu["recommended"]["cluster_id"] == "eu-west-osh"
    excluded = [c for c in p_eu["clusters"] if not c["eligible"]]
    assert any("residency" in r for c in excluded for r in c["reasons"])


def test_deployment_consumes_and_releases_gpu_capacity():
    def free_h100(cluster_id):
        fleet = client.get("/api/clusters").json()["clusters"]
        c = next(x for x in fleet if x["id"] == cluster_id)
        return next(g for g in c["gpus"] if g["family"] == "H100")["free"]

    before = free_h100("cloud-burst")
    r = client.post("/api/deployments", json={
        "model_id": "llama-4-scout", "profile_id": "balanced",
        "cluster_id": "cloud-burst", "name": "scout-burst"}).json()
    assert free_h100("cloud-burst") == before - 1
    client.delete(f"/api/deployments/{r['id']}")
    assert free_h100("cloud-burst") == before


def test_openai_compatible_gateway_auto_routing():
    r = client.post("/v1/chat/completions", json={
        "model": "auto",
        "messages": [{"role": "user", "content": "hello"}],
    }).json()
    assert r["object"] == "chat.completion"
    assert r["modelect"]["routed"] is True
    assert r["usage"]["total_tokens"] > 0
    assert r["modelect"]["receipt"]["cost_usd"] >= 0
    assert "auto-routed" in r["modelect"]["receipt"]["reason"]


def test_routing_receipt_on_expensive_model():
    r = client.post("/v1/chat/completions", json={
        "model": "claude-opus-4.5",
        "messages": [{"role": "user", "content": "hello"}],
    }).json()
    receipt = r["modelect"]["receipt"]
    assert receipt["reason"] == "explicitly requested by caller"
    alt = receipt.get("cheapest_comparable")
    assert alt and alt["savings_pct"] > 0


def test_migrate_plan_high_volume_saves():
    r = client.post("/api/migrate", json={
        "cloud_model_id": "claude-opus-4.5",
        "monthly_m_tokens": 500,
        "use_case": "chatbot",
    }).json()
    assert r["cloud"]["monthly_cost"] > 0
    assert len(r["alternatives"]) >= 1
    best = r["alternatives"][0]
    assert best["savings_monthly"] > 0 and best["savings_pct"] > 0
    assert best["quality_delta"] >= -12
    assert len(r["projection"]) == 12
    assert r["projection"][11]["cloud"] > r["projection"][0]["cloud"]
    assert "saves" in (r["verdict"] or "")


def test_migrate_plan_low_volume_is_honest():
    # at low volume dedicated GPUs cost more than the API — the verdict
    # must say so instead of overselling migration
    r = client.post("/api/migrate", json={
        "cloud_model_id": "gemini-2.5-flash",
        "monthly_m_tokens": 5,
        "use_case": "chatbot",
    }).json()
    assert "cost-competitive" in (r["verdict"] or "")
    # migrating away from a self-hostable model is rejected
    assert client.post("/api/migrate", json={
        "cloud_model_id": "phi-4"}).status_code == 400


def test_integration_test_suite():
    r = client.post("/api/integration-test", json={"model_id": "claude-sonnet-4.5"}).json()
    assert r["overall"] in {"pass", "warn"}
    ids = [c["id"] for c in r["checks"]]
    assert ids == ["connectivity", "auth", "streaming", "json_schema", "groundedness"]
    assert all(c["status"] in {"pass", "warn"} for c in r["checks"])
    grounded = next(c for c in r["checks"] if c["id"] == "groundedness")
    assert "measured, not promised" in grounded["detail"]
    # deterministic per model
    r2 = client.post("/api/integration-test", json={"model_id": "claude-sonnet-4.5"}).json()
    assert r2["checks"] == r["checks"]
    schema_check = next(c for c in r["checks"] if c["id"] == "json_schema")
    assert "/20 responses validated" in schema_check["detail"]
    assert client.post("/api/integration-test", json={"model_id": "nope"}).status_code == 400


def test_evals_run():
    r = client.post("/api/evals", json={
        "prompts": ["Summarize this contract", "Draft an escalation email"],
        "model_ids": ["claude-sonnet-4.5", "gpt-5-mini", "llama-4-maverick"],
        "use_case": "chatbot",
    }).json()
    assert r["mode"] == "simulated"
    assert len(r["results"]) == 3
    assert r["results"][0]["avg_judge_score"] >= r["results"][-1]["avg_judge_score"]
    assert r["winner_id"] and r["value_pick_id"] and r["verdict"]
    assert len(r["results"][0]["per_prompt"]) == 2
    # deterministic: same request, same scores
    r2 = client.post("/api/evals", json={
        "prompts": ["Summarize this contract", "Draft an escalation email"],
        "model_ids": ["claude-sonnet-4.5", "gpt-5-mini", "llama-4-maverick"],
        "use_case": "chatbot",
    }).json()
    assert r2["results"][0]["avg_judge_score"] == r["results"][0]["avg_judge_score"]
    assert client.post("/api/evals", json={
        "prompts": [], "model_ids": ["gpt-5-mini", "phi-4"]}).status_code == 400
