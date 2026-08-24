import os
import tempfile

os.environ["REGISTRY_OFFLINE"] = "1"  # deterministic snapshot mode in tests
os.environ["MODELECT_DATA_DIR"] = tempfile.mkdtemp()  # fresh DB per run

from fastapi.testclient import TestClient

from app.main import app

# admin session for the whole suite (cookies persist on the client)
client = TestClient(app)
assert client.post("/api/auth/login", json={
    "username": "admin", "password": "modelect-admin"}).status_code == 200


def _user_client(team: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": team, "password": "modelect-user"})
    assert r.status_code == 200
    return c


def test_auth_sessions_and_roles():
    # no session -> 401 on portal APIs; gateway + health stay open
    anon = TestClient(app)
    assert anon.get("/api/models").status_code == 401
    assert anon.get("/healthz").status_code == 200
    assert anon.post("/v1/chat/completions", json={
        "model": "auto", "messages": [{"role": "user", "content": "hi"}]}).status_code == 200
    # bad password rejected
    assert anon.post("/api/auth/login", json={
        "username": "admin", "password": "wrong"}).status_code == 401
    # team user: can decide/deploy surfaces, cannot admin surfaces
    u = _user_client("support-bot")
    assert u.get("/api/models").status_code == 200
    assert u.get("/api/tokenomics").status_code == 403
    assert u.put("/api/config", json={"values": {"default_quality_floor": 80}}).status_code == 403
    assert u.put("/api/teams/support-bot", json={"enabled": True}).status_code == 403
    # own-team view works and exposes only their team
    mine = u.get("/api/me/team").json()
    assert mine["id"] == "support-bot" and mine["api_key"].startswith("tk-")
    # admin retains full access
    assert client.get("/api/tokenomics").status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["role"] == "admin"


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


def test_tokenomics_overview():
    r = client.get("/api/tokenomics").json()
    assert len(r["teams"]) == 4
    states = {t["id"]: t["state"] for t in r["teams"]}
    assert states["research-agents"] == "degraded"   # over budget, policy degrade
    assert states["support-bot"] == "warn"           # ~80% used
    assert states["intern-sandbox"] == "ok"          # no history
    assert r["kpis"]["blended_per_1m"] > 0
    assert r["kpis"]["budget_health"]["degraded"] >= 1
    assert any(s["private"] for s in r["statement"]), "private GPU rows in statement"
    assert any(not s["private"] for s in r["statement"]), "API rows in statement"
    # seeded burst shows up as an anomaly and in the enforcement log
    assert any(a["team_id"] == "research-agents" for a in r["anomalies"])
    assert any(l["action"] == "DEGRADE" for l in r["enforcement_log"])


def test_budget_enforcement_at_gateway():
    teams = {t["id"]: t for t in client.get("/api/tokenomics").json()["teams"]}

    # over-budget team requesting an expensive model gets degraded to an SLM
    r = client.post("/v1/chat/completions",
                    headers={"Authorization": f"Bearer {teams['research-agents']['api_key']}"},
                    json={"model": "claude-opus-4.5",
                          "messages": [{"role": "user", "content": "hi"}]}).json()
    enf = r["modelect"]["receipt"]["enforcement"]
    assert enf["policy"] == "degrade" and enf["requested_model"] == "claude-opus-4.5"
    assert r["model"] != "claude-opus-4.5"

    # healthy, unrestricted team is served exactly what it asked for
    r2 = client.post("/v1/chat/completions",
                     headers={"Authorization": f"Bearer {teams['doc-pipeline']['api_key']}"},
                     json={"model": "claude-opus-4.5",
                           "messages": [{"role": "user", "content": "hi"}]}).json()
    assert r2["model"] == "claude-opus-4.5"
    assert "enforcement" not in r2["modelect"]["receipt"]
    after = {t["id"]: t for t in client.get("/api/tokenomics").json()["teams"]}
    assert after["doc-pipeline"]["spend"] > teams["doc-pipeline"]["spend"]


def test_guardrails_tier_shape_rate_killswitch():
    teams = {t["id"]: t for t in client.get("/api/tokenomics").json()["teams"]}
    hdr = lambda tid: {"Authorization": f"Bearer {teams[tid]['api_key']}"}
    msg = lambda content: {"messages": [{"role": "user", "content": content}]}

    # tier allowlist: intern-sandbox (slm,mid) may not call a large model
    r = client.post("/v1/chat/completions", headers=hdr("intern-sandbox"),
                    json={"model": "claude-opus-4.5", **msg("hi")})
    assert r.status_code == 403 and "tier" in r.json()["detail"]

    # input-shape limit: intern's max_input_tokens=8000
    r = client.post("/v1/chat/completions", headers=hdr("intern-sandbox"),
                    json={"model": "phi-4", **msg("word " * 7000)})
    assert r.status_code == 400 and "max_input_tokens" in r.json()["detail"]

    # token-rate limit: with a 100 tpm cap, doc-pipeline gets throttled
    # within the 60s window (first call may pass if the window is empty)
    client.put("/api/teams/doc-pipeline", json={"rate_limit_tpm": 100})
    first = client.post("/v1/chat/completions", headers=hdr("doc-pipeline"),
                        json={"model": "gemini-2.5-flash", **msg("hello there")})
    if first.status_code == 200:
        second = client.post("/v1/chat/completions", headers=hdr("doc-pipeline"),
                             json={"model": "gemini-2.5-flash", **msg("hello again")})
        assert second.status_code == 429
    else:
        assert first.status_code == 429
    client.put("/api/teams/doc-pipeline", json={"rate_limit_tpm": 10_000_000})

    # kill switch: pause -> 403, resume -> 200
    client.put("/api/teams/support-bot", json={"enabled": False})
    r = client.post("/v1/chat/completions", headers=hdr("support-bot"),
                    json={"model": "claude-haiku-4.5", **msg("hi")})
    assert r.status_code == 403 and "paused" in r.json()["detail"]
    client.put("/api/teams/support-bot", json={"enabled": True})
    r = client.post("/v1/chat/completions", headers=hdr("support-bot"),
                    json={"model": "claude-haiku-4.5", **msg("hi")})
    assert r.status_code == 200
    # enforcement log captured the blocks and the kill switch
    log = client.get("/api/tokenomics").json()["enforcement_log"]
    assert any(l["action"] == "BLOCK" for l in log)
    assert any(l["action"] == "KILLSWITCH" for l in log)


def test_cascade_routing():
    # simple prompt: stays on the tier-1 SLM and reports the saving
    r = client.post("/v1/chat/completions", json={
        "model": "cascade", "messages": [{"role": "user", "content": "hi there"}],
    }).json()
    cascade = r["modelect"]["receipt"]["cascade"]
    assert cascade["escalated"] is False
    assert r["model"] == cascade["tier1"]
    assert cascade["saved_usd"] > 0 and cascade["vs_model"]

    # complex prompt: escalates to a strong model
    hard = ("Analyze the architecture of our payment platform step by step, "
            "design a migration plan and prove the rollback strategy is safe.")
    r2 = client.post("/v1/chat/completions", json={
        "model": "cascade", "messages": [{"role": "user", "content": hard}],
    }).json()
    c2 = r2["modelect"]["receipt"]["cascade"]
    assert c2["escalated"] is True
    assert r2["model"] == c2["served_by"] != c2["tier1"]


def test_telemetry_provenance_and_sync():
    models = client.get("/api/models").json()["models"]
    # seeded traffic gives measured telemetry to traffic-bearing models
    mini = next(m for m in models if m["id"] == "gpt-5-mini")
    assert mini["telemetry"]["samples"] >= 20
    assert mini["provenance"]["latency"]["source"] == "measured"
    # a model with no traffic stays an estimate
    grok = next(m for m in models if m["id"] == "grok-4")
    assert grok["telemetry"] is None
    assert grok["provenance"]["latency"]["source"] == "estimated"
    # recommendations surface the measured basis
    rec = client.post("/api/recommend", json={"use_case": "chatbot"}).json()
    assert any(r["latency_measured"] for r in rec["results"]), \
        "seeded models should be speed-scored from measured latency"
    assert any("measured on your gateway" in reason
               for r in rec["results"] for reason in r["reasons"])
    # force re-sync endpoint returns fresh sync metadata
    s = client.post("/api/registry/sync").json()
    assert {x["registry"] for x in s["sync"]} == {"huggingface", "openrouter"}


def test_config_service_and_persistence():
    entries = client.get("/api/config").json()["entries"]
    keys = {e["key"] for e in entries}
    assert {"gpu_utilization_target", "assumed_monthly_m_tokens",
            "default_quality_floor", "cache_ttl_hours"} <= keys

    # update flows through to the engines that read it
    r = client.put("/api/config", json={
        "values": {"assumed_monthly_m_tokens": 120}}).json()
    assert r["updated"] == [{"key": "assumed_monthly_m_tokens", "value": 120}]
    rec = client.post("/api/recommend", json={
        "use_case": "coding", "chosen_id": "gpt-5.1",
        "constraints": {"open_source_only": True}}).json()
    assert any("120M tokens" in d for d in rec["chosen_vs_suggested"]["deltas"])

    # validation: out-of-range and unknown keys rejected
    assert client.put("/api/config", json={
        "values": {"gpu_utilization_target": 5}}).status_code == 400
    assert client.put("/api/config", json={
        "values": {"nope": 1}}).status_code == 400

    # system endpoint reports the persistent store
    sysinfo = client.get("/api/system").json()
    assert sysinfo["db_backend"] == "sqlite"
    assert sysinfo["analytics_events"] > 0

    # restore default for other tests
    client.put("/api/config", json={"values": {"assumed_monthly_m_tokens": 50}})


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
    assert len(a["series"]) >= 13  # complete days only, today excluded
    assert a["granularity"] == "day" and a["window_days"] == 14
    # industry-standard KPIs: percentiles, success rate, deltas, throughput
    k = a["kpis"]
    assert k["p95_ms"] >= k["p50_ms"] > 0
    assert 0 <= k["success_rate"] <= 100
    assert k["tokens_in"] > 0 and k["tokens_out"] > 0
    assert set(k["deltas"]) == {"requests_pct", "spend_pct", "p95_pct"}
    # provider + hybrid estate splits
    assert a["by_provider"] and a["by_provider"][0]["cost"] >= a["by_provider"][-1]["cost"]
    assert a["hybrid"]["api"]["tokens"] > 0
    assert a["model_count"] == len(a["by_model"])
    # narrower window really narrows, hourly on the 24h view
    d7 = client.get("/api/analytics/summary?days=7").json()
    assert d7["kpis"]["requests"] <= a["kpis"]["requests"]
    h = client.get("/api/analytics/summary?days=1").json()
    assert h["granularity"] == "hour"
    # recent rows carry routing provenance fields
    assert {"policy", "backend"} <= set(a["recent"][0].keys())


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


def test_agent_reporting_and_real_cluster_lifecycle():
    token = client.get("/api/agents/token").json()["token"]
    assert token.startswith("ma-")
    # bad/missing token rejected
    assert client.post("/api/agent/report", json={"cluster_id": "x"}).status_code == 401
    # a real GPU cluster reports in (with a time-sliced vGPU pool)
    report = {
        "cluster_id": "caaslab", "name": "CaaS Lab", "platform": "openshift",
        "version": "v1.29.6", "region": "lab", "residency": "us",
        "cost_factor": 1.0, "nodes": 5,
        "gpus": [
            {"family": "L40S", "type": "NVIDIA L40S 48GB · time-sliced x4",
             "count": 8, "virtual": True, "mode": "time-slice"},
        ],
    }
    r = client.post("/api/agent/report", json=report,
                    headers={"X-Agent-Token": token})
    assert r.status_code == 200
    fleet = client.get("/api/clusters").json()["clusters"]
    lab = next(c for c in fleet if c["id"] == "caaslab")
    assert lab["source"] == "agent" and lab["agent_status"] == "connected"
    assert lab["gpus"][0]["virtual"] is True and lab["gpus"][0]["free"] == 8
    assert lab["gpu_class"] == "gpu-ready"  # inferred from reported pools

    # a CPU-only cluster registers, is classified, and is never a
    # placement target for GPU profiles
    client.post("/api/agent/report", json={
        "cluster_id": "edge-cpu", "name": "Edge CPU", "nodes": 3,
        "gpus": [], "gpu_class": "cpu-only", "operator_detected": False,
    }, headers={"X-Agent-Token": token})
    fleet = client.get("/api/clusters").json()["clusters"]
    edge = next(c for c in fleet if c["id"] == "edge-cpu")
    assert edge["gpu_class"] == "cpu-only"
    p = client.post("/api/placement", json={
        "model_id": "mistral-small-3.2", "profile_id": "balanced"}).json()
    edge_entry = next(c for c in p["clusters"] if c["cluster_id"] == "edge-cpu")
    assert edge_entry["eligible"] is False
    assert "not GPU-schedulable" in edge_entry["reasons"][0]
    # placement can target the real cluster explicitly, deploy consumes vGPUs
    dep = client.post("/api/deployments", json={
        "model_id": "mistral-small-3.2", "profile_id": "balanced",
        "cluster_id": "caaslab", "name": "lab-mistral"}).json()
    assert dep["cluster_name"] == "CaaS Lab"
    fleet = client.get("/api/clusters").json()["clusters"]
    lab = next(c for c in fleet if c["id"] == "caaslab")
    assert lab["gpus"][0]["used"] == 1 and lab["gpus"][0]["free"] == 7
    client.delete(f"/api/deployments/{dep['id']}")
    fleet = client.get("/api/clusters").json()["clusters"]
    lab = next(c for c in fleet if c["id"] == "caaslab")
    assert lab["gpus"][0]["free"] == 8


def test_work_orders_and_real_backend_fallback():
    token = client.get("/api/agents/token").json()["token"]
    # deploying onto an agent cluster queues a work order for its agent
    dep = client.post("/api/deployments", json={
        "model_id": "phi-4", "profile_id": "balanced",
        "cluster_id": "caaslab", "name": "lab-phi"}).json()
    assert dep["backend"] == "agent" and dep["status"] == "scheduling"

    assert client.get("/api/agent/work?cluster_id=caaslab").status_code == 401
    orders = client.get("/api/agent/work?cluster_id=caaslab",
                        headers={"X-Agent-Token": token}).json()["orders"]
    order = next(o for o in orders if o["id"] == dep["id"])
    assert order["action"] == "deploy" and order["state"] == "pending"
    assert order["hf_repo"] == "microsoft/phi-4" and order["gpu_count"] == 1

    # agent lifecycle: starting -> ready (endpoint reported)
    client.post(f"/api/agent/work/{dep['id']}", json={"state": "starting"},
                headers={"X-Agent-Token": token})
    d = next(x for x in client.get("/api/deployments").json()["deployments"]
             if x["id"] == dep["id"])
    assert d["status"] == "warming_up"
    client.post(f"/api/agent/work/{dep['id']}",
                json={"state": "ready", "endpoint": "http://127.0.0.1:9"},
                headers={"X-Agent-Token": token})
    d = next(x for x in client.get("/api/deployments").json()["deployments"]
             if x["id"] == dep["id"])
    assert d["status"] == "ready" and d["real_endpoint"] == "http://127.0.0.1:9"

    # gateway tries the real endpoint, falls back honestly when unreachable
    r = client.post("/v1/chat/completions", json={
        "model": "phi-4", "messages": [{"role": "user", "content": "hi"}]}).json()
    backend = r["modelect"]["receipt"]["backend"]
    assert backend["type"] == "simulated-fallback"
    assert backend["endpoint"] == "http://127.0.0.1:9"

    # delete flows to the agent as a teardown order, confirmed -> gone
    client.delete(f"/api/deployments/{dep['id']}")
    orders = client.get("/api/agent/work?cluster_id=caaslab",
                        headers={"X-Agent-Token": token}).json()["orders"]
    tear = next(o for o in orders if o["id"] == dep["id"])
    assert tear["action"] == "delete"
    client.post(f"/api/agent/work/{dep['id']}", json={"state": "deleted"},
                headers={"X-Agent-Token": token})
    orders = client.get("/api/agent/work?cluster_id=caaslab",
                        headers={"X-Agent-Token": token}).json()["orders"]
    assert all(o["id"] != dep["id"] for o in orders)


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


def test_smart_router_simple_prompt_goes_small():
    r = client.post("/v1/chat/completions", json={
        "model": "route",
        "messages": [{"role": "user", "content": "What is the capital of France?"}],
    })
    assert r.status_code == 200
    body = r.json()
    router = body["modelect"]["receipt"]["router"]
    assert router["policy"] == "smart-router"
    assert router["verdict"] == "simple"
    assert body["model"] == router["served_by"] == router["small"]
    # decision is auditable: every signal listed, fired or not
    ids = {s["signal"] for s in router["signals"]}
    assert {"long_prompt", "reasoning_keywords", "short_question"} <= ids
    fired = [s for s in router["signals"] if s["fired"]]
    assert all(s["detail"] for s in fired)
    assert router["score"] < router["threshold"]
    # exactly one call, savings measured against the strong model
    assert router["saved_usd"] >= 0
    assert router["vs_model"] == router["strong"]


def test_smart_router_complex_prompt_escalates_upfront():
    prompt = ("Analyze the architecture trade-offs of this design and prove, "
              "step by step, that the failover plan holds. " + "context " * 150)
    r = client.post("/v1/chat/completions", json={
        "model": "route",
        "messages": [{"role": "user", "content": prompt}],
    })
    assert r.status_code == 200
    router = r.json()["modelect"]["receipt"]["router"]
    assert router["verdict"] == "complex"
    assert router["served_by"] == router["strong"]
    assert router["score"] >= router["threshold"]
    assert "saved_usd" not in router  # no counterfactual claim on escalations


def test_router_preview_and_measured_summary():
    p = client.post("/api/router/preview", json={
        "messages": [{"role": "user", "content": "Translate 'hello' to French?"}],
    }).json()
    assert p["verdict"] == "simple" and p["served_by"] == p["small"]

    s = client.get("/api/router/summary").json()
    assert s["provenance"] == "measured"
    route_stats = s["policies"]["route"]  # the two gateway tests above recorded traffic
    assert route_stats["requests"] >= 2
    assert 0 <= route_stats["small_share_pct"] <= 100
    assert route_stats["saved_usd"] >= 0
    assert route_stats["strong_usd"] >= route_stats["actual_usd"]


def test_admin_dashboard_insights():
    r = client.get("/api/dashboard/admin")
    assert r.status_code == 200
    d = r.json()
    # attention queue is ranked crit -> warn -> info
    sev = [i["severity"] for i in d["attention"]]
    order = {"crit": 0, "warn": 1, "info": 2}
    assert sev == sorted(sev, key=lambda s: order[s])
    # seeded estate: research-agents is degraded and anomalous -> crit items exist
    assert any(i["kind"] == "budget" for i in d["attention"])
    assert all({"severity", "kind", "title", "detail", "link"} <= set(i) for i in d["attention"])
    # runway from real burn
    assert d["runway_days"] is None or d["runway_days"] >= 0
    # router health trend rows are day-bucketed percentages
    for t in d["router_health"]["trend"]:
        assert 0 <= t["escalation_pct"] <= 100
    assert d["prompt_bloat"]["trend"]
    conc = d["concentration"]
    assert conc and 0 < conc["share_pct"] <= 100 and conc["providers_used"] >= 1
    # admin-only
    user = _user_client("doc-pipeline")
    assert user.get("/api/dashboard/admin").status_code == 403


def test_counterfactual_uses_measured_mix():
    # generate a measured routed mix (>=5 routed requests)
    for _ in range(5):
        client.post("/v1/chat/completions", json={
            "model": "route",
            "messages": [{"role": "user", "content": "Translate hello to French?"}]})
    d = client.get("/api/dashboard/admin").json()
    cf = d["counterfactual"]
    assert cf is not None
    assert cf["direct_requests"] > 0
    assert cf["est_routed_cost"] >= 0
    assert "measured mix" in cf["basis"]
    # savings claim is consistent with its own numbers
    assert abs((cf["direct_cost"] - cf["est_routed_cost"]) - cf["est_savings"]) < 0.02
