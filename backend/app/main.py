"""Modelect — Multi-LLM Orchestrator (demo build).

Single FastAPI service combining the control plane (catalog,
recommendations, analytics) and a demo gateway (OpenAI-compatible
/v1/chat/completions). In the production architecture the gateway
hot path moves to the Go data plane; the API contracts stay the same.
"""
import asyncio
import json
import os
import random
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import httpx

from . import (agentic, agents, analytics, auth, clusters, config, deployments,
               evals, insights, integration, ledger, migrate, registry, replay,
               resilience, serving, tokenomics, work)
from . import router as smart_router
from .db import DATA_DIR, backend_name
from .catalog import MODELS, MODELS_BY_ID, USE_CASES, QUALITY_DIMS
from .recommender import recommend, routing_receipt, similar_models

app = FastAPI(title="Modelect — Multi-LLM Orchestrator", version="0.2.0-demo")

# Split-topology role (combined | gateway | control): gateway pods serve
# only /healthz + /v1/* and skip seeding and the portal session gate —
# the surfaces they'd guard don't exist there.
_ROLE = os.environ.get("MODELECT_ROLE", "combined").lower()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


analytics.seed()

from . import demofill  # noqa: E402  (needs every engine imported first)
demofill.seed()

# Paths that never require a portal session: health, the OpenAI-compatible
# gateway (team API keys are its auth), login, agent reports (enrollment
# token is their auth), and the static UI.
_SESSION_EXEMPT = ("/healthz", "/v1/", "/api/auth/", "/api/agent/")


from . import metrics  # noqa: E402


@app.middleware("http")
async def _session_gate(request: Request, call_next):
    path = request.url.path
    if _ROLE != "gateway" and path.startswith("/api/") \
            and not any(path.startswith(p) for p in _SESSION_EXEMPT):
        try:
            request.state.user = auth.authorize(request)
        except HTTPException as e:
            metrics.inc("modelect_http_requests_total",
                        {"surface": "portal", "method": request.method,
                         "status": str(e.status_code)})
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)
    started = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - started
    surface = ("gateway" if path.startswith("/v1") else
               "portal" if path.startswith("/api") else "other")
    metrics.inc("modelect_http_requests_total",
                {"surface": surface, "method": request.method,
                 "status": str(response.status_code)})
    if surface == "gateway":
        metrics.observe_gateway_seconds(elapsed)
    return response


@app.get("/metrics")
def prometheus_metrics():
    """Prometheus exposition — request/token/cost/enforcement counters
    and the gateway latency histogram. Per-replica, as Prometheus expects."""
    return Response(metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# ----------------------------- auth ------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def auth_login(req: LoginRequest, response: Response):
    user = auth.login(req.username, req.password)
    if user is None:
        raise HTTPException(401, "invalid username or password")
    response.set_cookie(auth.COOKIE_NAME, auth.issue_token(user),
                        max_age=auth.SESSION_TTL, httponly=True,
                        samesite="lax", path="/")
    return user


@app.post("/api/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request):
    user = auth.session_user(request)
    if user is None:
        raise HTTPException(401, "not authenticated")
    return {**user, "demo_seed": analytics.demo_seed_enabled()}


@app.get("/api/me/team")
def my_team(request: Request):
    user = request.state.user
    team_id = user["team_id"]
    if user["role"] == "admin" or not team_id:
        raise HTTPException(400, "admin accounts are not bound to a team — see Tokenomics")
    team = next((t for t in tokenomics.overview()["teams"] if t["id"] == team_id), None)
    if team is None:
        raise HTTPException(404, "team not found")
    return team


# --------------------------- catalog ---------------------------------

@app.get("/api/models")
def list_models(q: str = "", provider: str = "", open_source: bool | None = None):
    items = MODELS
    if q:
        needle = q.lower()
        items = [m for m in items if needle in m["name"].lower() or needle in m["provider"].lower()]
    if provider:
        items = [m for m in items if m["provider"] == provider]
    if open_source is not None:
        items = [m for m in items if (m["source"] == "open") == open_source]

    # Phase 2/3 enrichment: every value carries provenance; telemetry
    # (measured on this install's gateway) overrides spec estimates.
    stats = analytics.model_stats()
    or_prices = registry.price_provenance()
    enriched = []
    for m in items:
        t = stats.get(m["id"])
        enriched.append({
            **m,
            "telemetry": t,
            "provenance": {
                "latency": ({"source": "measured", "samples": t["samples"]}
                            if t else {"source": "estimated"}),
                "price": or_prices.get(m["id"], {"source": "curated-seed"}),
                "quality": {"source": "benchmark-seed"},
            },
        })
    return {"models": enriched, "providers": sorted({m["provider"] for m in MODELS}),
            "quality_dims": QUALITY_DIMS}


@app.get("/api/models/{model_id}/similar")
def get_similar(model_id: str):
    if model_id not in MODELS_BY_ID:
        raise HTTPException(404, "unknown model")
    return {"similar": similar_models(model_id)}


@app.get("/api/use-cases")
def use_cases():
    return {"use_cases": USE_CASES}


@app.get("/api/registry/models")
def registry_models(sources: str = "huggingface,openrouter"):
    wanted = [s.strip() for s in sources.split(",") if s.strip()]
    return registry.get_entries(wanted)


@app.post("/api/registry/sync")
def registry_sync(sources: str = "huggingface,openrouter"):
    wanted = [s.strip() for s in sources.split(",") if s.strip()]
    return registry.force_sync(wanted)


# ------------------------ recommendation ------------------------------

class RecommendRequest(BaseModel):
    use_case: str = "chatbot"
    weights: dict = Field(default_factory=lambda: {"quality": 50, "cost": 30, "speed": 20})
    constraints: dict = Field(default_factory=dict)
    chosen_id: str | None = None
    mode: str = "best"  # "best" | "smallest_capable" (SLM-first)
    quality_floor: int = 80


@app.post("/api/recommend")
def post_recommend(req: RecommendRequest):
    return recommend(req.use_case, req.weights, req.constraints, req.chosen_id,
                     mode=req.mode, quality_floor=req.quality_floor)


class CompareRequest(BaseModel):
    model_ids: list[str]


@app.post("/api/compare")
def post_compare(req: CompareRequest):
    missing = [i for i in req.model_ids if i not in MODELS_BY_ID]
    if missing:
        raise HTTPException(404, f"unknown model(s): {missing}")
    models = [MODELS_BY_ID[i] for i in req.model_ids[:3]]
    radar = [{"dimension": d, **{m["id"]: m["quality"][d] for m in models}} for d in QUALITY_DIMS]
    return {"models": models, "radar": radar}


# --------------------------- playground -------------------------------

class PlaygroundRequest(BaseModel):
    model_ids: list[str]
    prompt: str


def _simulate_completion(model: dict, prompt: str,
                         team_id: str | None = None,
                         max_output_tokens: int | None = None,
                         policy: str | None = None,
                         agent_id: str | None = None,
                         task_id: str | None = None) -> dict:
    """Demo mode: synthesizes a response instead of calling the provider.

    Production wiring point — replace with the provider adapter call
    (or route through the Go gateway) once API keys are configured.
    """
    rng = random.Random(hash((model["id"], prompt)) & 0xFFFF)
    tokens_in = max(8, len(prompt.split()) * 4 // 3)
    tokens_out = rng.randint(90, 220)
    if max_output_tokens:
        tokens_out = min(tokens_out, max_output_tokens)
    latency = int(rng.gauss(model["latency_ms"], model["latency_ms"] * 0.15))
    text = (
        f"[demo response — provider call not wired in this build]\n\n"
        f"{model['name']} ({model['provider']}) would answer your prompt here. "
        f"In this simulation it processed ~{tokens_in} input tokens and produced "
        f"~{tokens_out} output tokens at ~{model['throughput_tps']} tok/s. "
        f"Strengths for this kind of request: "
        + ", ".join(sorted(model["quality"], key=model["quality"].get, reverse=True)[:3])
        + f". Context window {model['context_window']:,} tokens."
    )
    cost = (tokens_in * model["input_price"] + tokens_out * model["output_price"]) / 1_000_000
    analytics.record(model["id"], tokens_in, tokens_out, latency,
                     team_id=team_id, policy=policy, backend="simulated",
                     agent_id=agent_id, task_id=task_id)
    metrics.inc("modelect_gateway_tokens_total", {"direction": "in"}, tokens_in)
    metrics.inc("modelect_gateway_tokens_total", {"direction": "out"}, tokens_out)
    metrics.inc("modelect_gateway_cost_usd_total", value=cost)
    return {
        "model_id": model["id"], "model_name": model["name"], "provider": model["provider"],
        "text": text, "tokens_in": tokens_in, "tokens_out": tokens_out,
        "latency_ms": latency, "cost": round(cost, 6),
    }


@app.post("/api/playground")
def playground(req: PlaygroundRequest):
    if not req.model_ids:
        raise HTTPException(400, "select at least one model")
    missing = [i for i in req.model_ids if i not in MODELS_BY_ID]
    if missing:
        raise HTTPException(404, f"unknown model(s): {missing}")
    results = []
    for i in req.model_ids[:3]:
        model = MODELS_BY_ID[i]
        sim = _simulate_completion(model, req.prompt)
        sim["receipt"] = routing_receipt(model, sim["tokens_in"], sim["tokens_out"])
        results.append(sim)
    return {"results": results}


# ------------------------ integration test ----------------------------

class IntegrationTestRequest(BaseModel):
    model_id: str


@app.post("/api/integration-test")
def post_integration_test(req: IntegrationTestRequest):
    try:
        return integration.run_integration_test(req.model_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------- migrate ---------------------------------

class MigrateRequest(BaseModel):
    cloud_model_id: str
    monthly_m_tokens: float = 50
    use_case: str = "chatbot"


@app.post("/api/migrate")
def post_migrate(req: MigrateRequest):
    try:
        return migrate.migrate_plan(req.cloud_model_id, req.monthly_m_tokens, req.use_case)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ----------------------------- evals ----------------------------------

class EvalRequest(BaseModel):
    prompts: list[str]
    model_ids: list[str]
    use_case: str = "chatbot"


@app.post("/api/evals")
def post_eval(req: EvalRequest):
    try:
        return evals.run_eval(req.prompts, req.model_ids, req.use_case)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ----------------------------- clusters -------------------------------

@app.get("/api/clusters")
def list_clusters():
    snap = clusters.snapshot()
    for c in snap:
        c["fits"] = deployments.fits_preview(c)
    return {"clusters": snap}


class CordonRequest(BaseModel):
    cordoned: bool


@app.put("/api/clusters/{cluster_id}/cordon")
def cordon_cluster(cluster_id: str, req: CordonRequest):
    """Maintenance mode: a cordoned cluster stays visible but the
    placement engine skips it (reason appears in placement receipts)."""
    if cluster_id not in {c["id"] for c in clusters.snapshot()}:
        raise HTTPException(404, f"unknown cluster '{cluster_id}'")
    clusters.set_cordon(cluster_id, req.cordoned)
    ledger.record("placement", "-",
                  summary=f"cluster '{cluster_id}' "
                          f"{'cordoned for maintenance' if req.cordoned else 'uncordoned'}",
                  receipt={"cluster_id": cluster_id, "cordoned": req.cordoned})
    return {"cluster_id": cluster_id, "cordoned": req.cordoned}


class AgentReport(BaseModel):
    cluster_id: str
    name: str = ""
    platform: str = "kubernetes"
    version: str = ""
    region: str = ""
    residency: str = ""
    cost_factor: float = 1.0
    nodes: int = 0
    gpus: list[dict] = []
    gpu_class: str = ""
    operator_detected: bool = False
    gpu_hardware: bool = False
    driver_version: str = ""
    cuda_version: str = ""
    agent_version: str = ""


# Agent contract v1: /api/agent/v1/* is the stable path for the split
# topology; the unversioned paths remain as aliases for older agents.
@app.post("/api/agent/v1/report")
@app.post("/api/agent/report")
def agent_report(req: AgentReport,
                 x_agent_token: str | None = Header(default=None)):
    if not agents.token_valid_for(x_agent_token, req.cluster_id):
        raise HTTPException(401, "invalid or missing agent enrollment token")
    return agents.upsert_report(req.model_dump())


@app.get("/api/agents/token")
def agents_token(request: Request):
    # admin-only via ADMIN_RULES; shown on the GPU Fleet 'connect' card
    return {"token": agents.enroll_token()}


@app.post("/api/agents/clusters/{cluster_id}/token")
def mint_agent_token(cluster_id: str):
    """Mint (or rotate) a per-cluster enrollment token. Rotation
    invalidates the previous token immediately — a stolen token then
    compromises one cluster, not the fleet. Ledgered."""
    token = agents.mint_cluster_token(cluster_id)
    ledger.record("placement", "-",
                  summary=f"enrollment token rotated for cluster '{cluster_id}'",
                  receipt={"cluster_id": cluster_id})
    return {"cluster_id": cluster_id, "token": token}


@app.get("/api/agent/v1/work")
@app.get("/api/agent/work")
def agent_work(cluster_id: str,
               x_agent_token: str | None = Header(default=None)):
    if not agents.token_valid_for(x_agent_token, cluster_id):
        raise HTTPException(401, "invalid or missing agent enrollment token")
    return {"orders": work.orders_for(cluster_id)}


class WorkStatus(BaseModel):
    state: str
    endpoint: str = ""
    message: str = ""


@app.post("/api/agent/v1/work/{order_id}")
@app.post("/api/agent/work/{order_id}")
def agent_work_status(order_id: str, req: WorkStatus,
                      x_agent_token: str | None = Header(default=None)):
    order = work.state_for(order_id)
    if not agents.token_valid_for(x_agent_token,
                                  order["cluster_id"] if order else None):
        raise HTTPException(401, "invalid or missing agent enrollment token")
    if req.state not in ("starting", "pulling", "ready", "error", "deleted",
                         "sleeping"):
        raise HTTPException(400, "invalid state")
    if not work.update_state(order_id, req.state, req.endpoint, req.message):
        raise HTTPException(404, "unknown work order")
    return {"ok": True}


class PlacementRequest(BaseModel):
    model_id: str
    profile_id: str
    residency: str | None = None


@app.post("/api/placement")
def post_placement(req: PlacementRequest):
    profile = next((p for p in deployments.serving_profiles(req.model_id)
                    if p["id"] == req.profile_id), None)
    if not profile:
        raise HTTPException(404, "unknown model/profile")
    return clusters.place(profile["gpus"], req.residency)


# --------------------------- deployments ------------------------------

class DeploymentRequest(BaseModel):
    model_id: str
    profile_id: str
    name: str = ""
    cluster_id: str | None = None
    residency: str | None = None
    serving_class: str | None = None  # reserved | on-demand (default by size)


@app.get("/api/models/{model_id}/profiles")
def get_profiles(model_id: str):
    if model_id not in MODELS_BY_ID:
        raise HTTPException(404, "unknown model")
    return {"profiles": deployments.serving_profiles(model_id),
            "self_hostable": MODELS_BY_ID[model_id]["self_hostable"]}


@app.post("/api/deployments")
def create_deployment(req: DeploymentRequest):
    try:
        return deployments.create(req.model_id, req.profile_id, req.name,
                                  req.cluster_id, req.residency,
                                  serving_class=req.serving_class)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/deployments/{dep_id}/sleep")
def sleep_deployment(dep_id: str):
    """Manual scale-to-zero for an on-demand deployment."""
    try:
        return serving.sleep(dep_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/deployments/{dep_id}/wake")
def wake_deployment(dep_id: str):
    try:
        return serving.wake(dep_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/deployments")
def list_deployments():
    return {"deployments": deployments.list_all()}


@app.delete("/api/deployments/{dep_id}")
def delete_deployment(dep_id: str):
    if not deployments.delete(dep_id):
        raise HTTPException(404, "unknown deployment")
    return {"deleted": dep_id}


# --------------------------- analytics --------------------------------

@app.get("/api/analytics/summary")
def analytics_summary(days: int = 14):
    return analytics.summary(days)


@app.get("/api/ledger")
def ledger_entries(days: int = 14, kind: str | None = None,
                   policy: str | None = None, limit: int = 200):
    """Model Decision Ledger — every routing, enforcement, failover and
    placement decision with its receipt. Governance record, exportable."""
    return ledger.entries(days=days, kind=kind, policy=policy, limit=limit)


@app.get("/api/ledger/export")
def ledger_export(days: int = 30):
    csv_text = ledger.export_csv(days=days)
    return Response(csv_text, media_type="text/csv", headers={
        "Content-Disposition": f"attachment; filename=modelect-ledger-{days}d.csv"})


class WhatIfRequest(BaseModel):
    days: int = 14
    scenario: dict


@app.post("/api/whatif")
def whatif(req: WhatIfRequest):
    """Replay recorded traffic under a hypothetical model or routing
    policy — exact re-pricing of YOUR token shapes, not a calculator."""
    return replay.replay(req.days, req.scenario)


class OutageRequest(BaseModel):
    provider: str | None = None


@app.get("/api/admin/outage")
def get_outage():
    return {"provider": resilience.outage_provider(),
            "providers": sorted({m["provider"] for m in MODELS})}


@app.put("/api/admin/outage")
def set_outage(req: OutageRequest):
    if req.provider is not None and \
            req.provider not in {m["provider"] for m in MODELS}:
        raise HTTPException(400, f"unknown provider '{req.provider}'")
    resilience.kv_set(resilience.OUTAGE_KEY, req.provider)
    return {"provider": req.provider}


class WebhookRequest(BaseModel):
    url: str | None = None


@app.get("/api/admin/webhook")
def get_webhook():
    return {"url": resilience.kv_get(resilience.WEBHOOK_KEY)}


@app.put("/api/admin/webhook")
def set_webhook(req: WebhookRequest):
    if req.url is not None and not req.url.startswith(("http://", "https://")):
        raise HTTPException(400, "webhook URL must be http(s)")
    resilience.kv_set(resilience.WEBHOOK_KEY, req.url)
    return {"url": req.url}


@app.get("/api/dashboard/admin")
def dashboard_admin(days: int = 14):
    """Admin operations layer: attention queue, budget runway,
    counterfactual routing savings, router drift, prompt bloat and
    provider concentration — aggregated from recorded platform state."""
    return insights.admin_summary(days)


@app.get("/api/router/summary")
def router_summary(days: int = 14):
    """Measured routing economics per policy (route/cascade/auto):
    small-model share and savings vs. sending everything to the
    strongest model — computed from recorded traffic, not projected."""
    return analytics.router_summary(days)


# --------------------------- tokenomics --------------------------------

@app.get("/api/tokenomics")
def tokenomics_overview():
    return tokenomics.overview()


class TeamUpdate(BaseModel):
    enabled: bool | None = None
    budget_usd: float | None = None
    policy: str | None = None
    rate_limit_tpm: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    allowed_tiers: str | None = None
    loop_policy: str | None = None
    max_delegation_depth: int | None = None


@app.put("/api/teams/{team_id}")
def put_team(team_id: str, req: TeamUpdate):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(400, "no fields to update")
    try:
        merged = tokenomics.update_team(team_id, fields)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": team_id, **{k: merged[k] for k in fields}}


# ------------------------ config & system ------------------------------

@app.get("/api/config")
def get_config():
    return {"entries": config.all_entries()}


class ConfigUpdate(BaseModel):
    values: dict[str, float]


@app.put("/api/config")
def put_config(req: ConfigUpdate):
    updated = []
    try:
        for key, value in req.values.items():
            updated.append(config.set_value(key, value))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"updated": updated}


@app.get("/api/system")
def system_info():
    with_counts = analytics.summary()["kpis"]
    return {
        "db_backend": backend_name(),
        "data_dir": DATA_DIR,
        "analytics_events": with_counts["requests_total"],
        "deployments": len(deployments.list_all()),
        "demo_seed": analytics.demo_seed_enabled(),
        "version": app.version,
    }


# ---------------- OpenAI-compatible demo gateway ----------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "auto"
    messages: list[ChatMessage]
    stream: bool = False


@app.post("/v1/tasks/{task_id}/complete")
def complete_task(task_id: str,
                  authorization: str | None = Header(default=None)):
    """Mark a mission-budgeted task complete (agent or team key).
    Completed tasks power the cost-per-outcome metric."""
    bearer = (authorization or "").removeprefix("Bearer ").strip() or None
    ag = agentic.resolve_agent(bearer)
    team = tokenomics.team_by_id(ag["team_id"]) if ag \
        else tokenomics.resolve_team(bearer)
    if not team:
        raise HTTPException(401, "a team (tk-…) or agent (ak-…) key is required")
    try:
        return agentic.complete_task(task_id, team["id"])
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/tokenomics/agents")
def tokenomics_agents():
    """Agentic spend tree: per-agent calls, tokens, spend, tasks and
    cost per completed task."""
    return agentic.overview()


class AgentCreateRequest(BaseModel):
    name: str


@app.post("/api/teams/{team_id}/agents")
def create_team_agent(team_id: str, req: AgentCreateRequest):
    if not tokenomics.team_by_id(team_id):
        raise HTTPException(404, "unknown team")
    try:
        return agentic.create_agent(team_id, req.name)
    except ValueError as e:
        raise HTTPException(409, str(e))


class RouterPreviewRequest(BaseModel):
    messages: list[ChatMessage]


@app.post("/api/router/preview")
def router_preview(req: RouterPreviewRequest):
    """Dry-run the smart router: classify without serving, so the UI
    can show where a prompt WOULD go and why."""
    routed = smart_router.route([m.model_dump() for m in req.messages])
    return routed["decision"]


def _ledger_gateway(model: dict, policy_name: str, team: dict | None,
                    enforcement: dict | None, failover_info: dict | None,
                    router_info: dict | None, cascade_info: dict | None,
                    receipt: dict, task_info: dict | None = None,
                    loop_info: dict | None = None) -> None:
    """One ledger entry per gateway decision — what was decided and why."""
    if loop_info:
        kind = "enforcement"
        summary = (f"loop-breaker: {loop_info['requested_model']} → "
                   f"{loop_info['served_by']} — {loop_info['note']}")
    elif task_info and task_info.get("enforcement"):
        te = task_info["enforcement"]
        kind = "enforcement"
        summary = (f"task-budget degrade: {te['requested_model']} → "
                   f"{te['served_by']} ({te['note']})")
    elif enforcement:
        kind = "enforcement"
        summary = (f"budget degrade: {enforcement['requested_model']} → "
                   f"{enforcement['served_by']} (team {enforcement['team']} at "
                   f"{enforcement['budget_pct']:.0f}% of budget)")
    elif failover_info:
        kind = "failover"
        summary = (f"{failover_info['requested']} → {failover_info['served_by']}: "
                   f"{failover_info['reason']}")
    elif router_info:
        kind = "routing"
        summary = (f"smart-router {router_info['verdict']} "
                   f"({router_info['score']}/{router_info['threshold']}) → {model['id']}")
    elif cascade_info:
        kind = "routing"
        summary = f"cascade → {model['id']}: {cascade_info['reason']}"
    elif policy_name == "auto":
        kind = "routing"
        summary = f"recommender routed → {model['id']}"
    else:
        kind = "routing"
        summary = f"caller pinned {model['id']}"
    ledger.record(kind, model["id"], policy=policy_name,
                  team_id=team["id"] if team else None,
                  summary=summary, receipt=receipt)


_CASCADE_KEYWORDS = ("analyze", "architecture", "design", "legal", "contract",
                     "prove", "math", "step by step", "plan", "strategy",
                     "debug", "reason")


def _cascade_strong_model() -> dict:
    return max(MODELS, key=lambda m: m["quality"]["chat"])


def _cascade_route(prompt: str) -> tuple[dict, dict | None, str]:
    """SLM-first cascade: a complexity classifier decides whether the
    tier-1 small model suffices or the request escalates to the
    strongest model. Returns (serving_model, tier1_model, reason)."""
    tier1 = recommend("chatbot", {"quality": 30, "cost": 50, "speed": 20},
                      mode="smallest_capable", quality_floor=75)["results"][0]["model"]
    hard = (len(prompt.split()) > 80
            or any(k in prompt.lower() for k in _CASCADE_KEYWORDS))
    if not hard:
        return tier1, tier1, "classified simple — handled by tier-1 SLM"
    return _cascade_strong_model(), tier1, "classified complex (length/keywords) — escalated"


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest,
                           authorization: str | None = Header(default=None),
                           x_task_id: str | None = Header(default=None),
                           x_task_budget: float | None = Header(default=None),
                           x_delegation_depth: int | None = Header(default=None)):
    """Unified API: `model: "auto"` routes via the recommender,
    `model: "cascade"` applies SLM-first routing with escalation, and
    `model: "route"` classifies the request BEFORE sending — exactly one
    model call, with a per-signal receipt of the decision.
    A team key (tk-…) or agent key (ak-…) in the Authorization header
    attributes the spend and activates that caller's guardrails.
    Agentic headers: X-Task-Id (+ optional X-Task-Budget in USD) meter a
    mission budget across all of a task's calls; X-Delegation-Depth is
    checked against the team's maximum."""
    prompt = req.messages[-1].content if req.messages else ""
    cascade_info = None
    router_info = None
    if req.model == "auto":
        rec = recommend("chatbot", {"quality": 40, "cost": 40, "speed": 20})
        model = rec["results"][0]["model"]
    elif req.model == "cascade":
        model, tier1, cascade_reason = _cascade_route(prompt)
        cascade_info = {"policy": "cascade", "tier1": tier1["id"],
                        "served_by": model["id"],
                        "escalated": model["id"] != tier1["id"],
                        "reason": cascade_reason}
    elif req.model == "route":
        routed = smart_router.route([m.model_dump() for m in req.messages])
        model = routed["model"]
        router_info = routed["decision"]
    elif req.model in MODELS_BY_ID:
        model = MODELS_BY_ID[req.model]
    else:
        raise HTTPException(404, f"unknown model '{req.model}' — GET /api/models for the catalog")

    # resilience drill: provider declared down -> automatic failover to
    # the closest comparable model, receipted like every other decision
    failover_info = None
    fo = resilience.failover_for(model)
    if fo:
        model, failover_info = fo

    # ---- caller identity: team key (tk-) or agent sub-key (ak-) -------
    bearer = (authorization or "").removeprefix("Bearer ").strip() or None
    agent = agentic.resolve_agent(bearer)
    team = tokenomics.team_by_id(agent["team_id"]) if agent \
        else tokenomics.resolve_team(bearer)
    enforcement = None
    task_info = None
    loop_info = None

    if team:
        # delegation-depth guard: the agentic fork-bomb brake
        max_depth = team.get("max_delegation_depth")
        if max_depth and x_delegation_depth and x_delegation_depth > max_depth:
            tokenomics.log_enforcement(
                team["id"], "BLOCK",
                f"delegation depth {x_delegation_depth} exceeds team max {max_depth}")
            raise HTTPException(
                403, f"delegation depth {x_delegation_depth} exceeds the team "
                     f"maximum of {max_depth} — recursive agent spawning stopped")

        # mission budget: meter this task across all of its calls
        if x_task_id:
            task = agentic.get_or_create_task(
                x_task_id, team["id"], agent["id"] if agent else None, x_task_budget)
            verdict = agentic.task_precheck(task)
            task_info = {"id": task["id"], "budget_usd": task["budget_usd"],
                         "spend_before_usd": round(agentic.task_spend(task["id"]), 4)}
            if verdict and verdict["action"] == "block":
                tokenomics.log_enforcement(team["id"], "BLOCK", verdict["reason"])
                raise HTTPException(402, verdict["reason"])
            if verdict and verdict["action"] == "degrade" \
                    and model["size_class"] != "slm":
                small = smart_router.small_model()
                task_info["enforcement"] = {
                    "policy": "task-budget degrade",
                    "requested_model": model["id"], "served_by": small["id"],
                    "note": verdict["reason"]}
                tokenomics.log_enforcement(
                    team["id"], "DEGRADE",
                    f"task '{task['id']}' over budget — {model['id']} served "
                    f"by {small['id']}")
                model = small

        # loop-breaker: contain an anomalous team automatically
        if team.get("loop_policy") == "degrade" \
                and tokenomics.is_anomalous(team["id"]) \
                and model["size_class"] != "slm":
            small = smart_router.small_model()
            loop_info = {
                "policy": "loop-breaker",
                "requested_model": model["id"], "served_by": small["id"],
                "note": "output volume anomalous vs this team's baseline — "
                        "auto-contained on the smallest capable model until "
                        "behavior normalizes"}
            tokenomics.log_enforcement(
                team["id"], "LOOPBREAK",
                f"anomalous output volume — {model['id']} served by {small['id']}")
            model = small

    # ---- tokenomics guardrails (enforced at the gateway) --------------
    if team:
        est_input = max(8, len(prompt.split()) * 4 // 3)
        violation = tokenomics.precheck(team, model, est_input)
        if violation:
            tokenomics.log_enforcement(
                team["id"], "BLOCK", f"{violation['code']}: {violation['reason']}")
            raise HTTPException(violation["code"], violation["reason"])
        status = tokenomics.budget_status(team)
        if status["pct"] >= 100 and team["policy"] == "degrade" \
                and model["size_class"] != "slm":
            slm = recommend("chatbot", {"quality": 30, "cost": 50, "speed": 20},
                            mode="smallest_capable", quality_floor=75)
            if slm["results"]:
                degraded_to = slm["results"][0]["model"]
                enforcement = {
                    "policy": "degrade",
                    "team": team["name"],
                    "budget_pct": status["pct"],
                    "requested_model": model["id"],
                    "served_by": degraded_to["id"],
                    "note": "budget exceeded — served by smallest capable model, no outage",
                }
                tokenomics.log_enforcement(
                    team["id"], "DEGRADE",
                    f"budget at {status['pct']:.0f}% — request for "
                    f"{model['id']} served by {degraded_to['id']}")
                model = degraded_to

    # ---- real serving backend (Phase B2) ------------------------------
    # If an agent-deployed vLLM endpoint is ready for this model, proxy
    # the request there; on failure fall back to simulation, honestly
    # labeled in the receipt.
    backend_info = {"type": "simulated"}
    is_routed = req.model in ("auto", "cascade", "route")
    policy = req.model if is_routed else None
    agent_id = agent["id"] if agent else None
    task_id = task_info["id"] if task_info else None

    # scale-to-zero: first request after sleep wakes the deployment.
    # Simulated clusters wake instantly; agent clusters warm up and the
    # caller gets an honest 503 with Retry-After until vLLM is ready.
    wake_info = serving.ensure_awake(model["id"])
    if wake_info and wake_info.get("warming"):
        raise HTTPException(
            503, f"model '{model['id']}' is waking from scale-to-zero — "
                 "vLLM is restarting and loading weights; retry shortly",
            headers={"Retry-After": "30"})

    real_endpoint = work.ready_endpoint_for_model(model["id"])
    if real_endpoint and not req.stream:
        try:
            upstream = httpx.post(
                f"{real_endpoint.rstrip('/')}/v1/chat/completions",
                json={"model": model["id"],
                      "messages": [m.model_dump() for m in req.messages]},
                timeout=120, verify=False)
            upstream.raise_for_status()
            body = upstream.json()
            usage = body.get("usage", {})
            analytics.record(model["id"],
                             usage.get("prompt_tokens", 0),
                             usage.get("completion_tokens", 0),
                             int(upstream.elapsed.total_seconds() * 1000),
                             team_id=team["id"] if team else None,
                             policy=policy, backend="real",
                             agent_id=agent_id, task_id=task_id)
            body["modelect"] = {
                "routed": is_routed,
                "receipt": {
                    **routing_receipt(model, usage.get("prompt_tokens", 0),
                                      usage.get("completion_tokens", 0),
                                      routed=is_routed),
                    "backend": {"type": "real", "endpoint": real_endpoint},
                    **({"enforcement": enforcement} if enforcement else {}),
                    **({"cascade": cascade_info} if cascade_info else {}),
                    **({"router": router_info} if router_info else {}),
                    **({"failover": failover_info} if failover_info else {}),
                    **({"agent": {"id": agent["id"], "name": agent["name"]}}
                       if agent else {}),
                    **({"task": task_info} if task_info else {}),
                    **({"loopbreak": loop_info} if loop_info else {}),
                },
            }
            _ledger_gateway(model, req.model if is_routed else "direct",
                            team, enforcement, failover_info, router_info,
                            cascade_info, body["modelect"]["receipt"],
                            task_info=task_info, loop_info=loop_info)
            return body
        except Exception as e:
            backend_info = {"type": "simulated-fallback",
                            "endpoint": real_endpoint,
                            "error": str(e)[:200]}

    sim = _simulate_completion(
        model, prompt,
        team_id=team["id"] if team else None,
        max_output_tokens=team.get("max_output_tokens") if team else None,
        policy=policy, agent_id=agent_id, task_id=task_id)

    # routing savings: what the strong model would have cost for this shape
    def _saved_vs_strong(strong: dict) -> float:
        strong_cost = (sim["tokens_in"] * strong["input_price"]
                       + sim["tokens_out"] * strong["output_price"]) / 1_000_000
        return round(max(0.0, strong_cost - sim["cost"]), 6)

    if cascade_info and not cascade_info["escalated"]:
        strong = _cascade_strong_model()
        cascade_info["saved_usd"] = _saved_vs_strong(strong)
        cascade_info["vs_model"] = strong["id"]
    if router_info and router_info["verdict"] == "simple":
        strong = smart_router.strong_model()
        router_info["saved_usd"] = _saved_vs_strong(strong)
        router_info["vs_model"] = strong["id"]

    receipt_obj = {**routing_receipt(model, sim["tokens_in"], sim["tokens_out"],
                                     routed=is_routed),
                   "backend": backend_info,
                   **({"enforcement": enforcement} if enforcement else {}),
                   **({"cascade": cascade_info} if cascade_info else {}),
                   **({"router": router_info} if router_info else {}),
                   **({"failover": failover_info} if failover_info else {}),
                   **({"agent": {"id": agent["id"], "name": agent["name"]}}
                      if agent else {}),
                   **({"task": task_info} if task_info else {}),
                   **({"loopbreak": loop_info} if loop_info else {}),
                   **({"wake": wake_info} if wake_info else {})}
    _ledger_gateway(model, req.model if is_routed else "direct",
                    team, enforcement, failover_info, router_info,
                    cascade_info, receipt_obj,
                    task_info=task_info, loop_info=loop_info)

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if not req.stream:
        return {
            "id": completion_id, "object": "chat.completion", "created": created,
            "model": model["id"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": sim["text"]}}],
            "usage": {"prompt_tokens": sim["tokens_in"], "completion_tokens": sim["tokens_out"],
                      "total_tokens": sim["tokens_in"] + sim["tokens_out"]},
            "modelect": {"routed": is_routed, "latency_ms": sim["latency_ms"],
                        "cost_usd": sim["cost"],
                        "receipt": receipt_obj},
        }

    async def sse():
        words = sim["text"].split(" ")
        for i, w in enumerate(words):
            chunk = {
                "id": completion_id, "object": "chat.completion.chunk", "created": created,
                "model": model["id"],
                "choices": [{"index": 0, "delta": {"content": w + (" " if i < len(words) - 1 else "")},
                             "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(0.02)
        done = {"id": completion_id, "object": "chat.completion.chunk", "created": created,
                "model": model["id"],
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        yield f"data: {json.dumps(done)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


# Optional single-container mode: serve the built dashboard if present.
class _SPAStaticFiles(StaticFiles):
    """Serve index.html for unknown paths so SPA deep links work."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404:
            response = await super().get_response("index.html", scope)
        return response


# ---- split topology: gateway pods keep only the inference surface ----
# MODELECT_ROLE=gateway strips everything but /healthz and /v1/* (the
# gateway's own auth is team/agent API keys, not sessions) and skips the
# UI mount. "combined" (default) and "control" serve the full surface —
# control keeps /v1 as a compatibility path while SDKs migrate to the
# dedicated gateway host.
if _ROLE == "gateway":
    app.router.routes = [
        r for r in app.router.routes
        if getattr(r, "path", "") in ("/healthz", "/metrics")
        or getattr(r, "path", "").startswith("/v1")]

_static = Path(__file__).resolve().parent.parent / "static"
if _static.is_dir() and _ROLE != "gateway":
    app.mount("/", _SPAStaticFiles(directory=_static, html=True), name="ui")
