"""Modelect — Multi-LLM Orchestrator (demo build).

Single FastAPI service combining the control plane (catalog,
recommendations, analytics) and a demo gateway (OpenAI-compatible
/v1/chat/completions). In the production architecture the gateway
hot path moves to the Go data plane; the API contracts stay the same.
"""
import asyncio
import json
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

from . import (agents, analytics, auth, clusters, config, deployments, evals,
               integration, migrate, registry, tokenomics, work)
from . import router as smart_router
from .db import DATA_DIR, backend_name
from .catalog import MODELS, MODELS_BY_ID, USE_CASES, QUALITY_DIMS
from .recommender import recommend, routing_receipt, similar_models

app = FastAPI(title="Modelect — Multi-LLM Orchestrator", version="0.1.0-demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


analytics.seed()

# Paths that never require a portal session: health, the OpenAI-compatible
# gateway (team API keys are its auth), login, agent reports (enrollment
# token is their auth), and the static UI.
_SESSION_EXEMPT = ("/healthz", "/v1/", "/api/auth/", "/api/agent/")


@app.middleware("http")
async def _session_gate(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not any(path.startswith(p) for p in _SESSION_EXEMPT):
        try:
            request.state.user = auth.authorize(request)
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)
    return await call_next(request)


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
                         policy: str | None = None) -> dict:
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
                     team_id=team_id, policy=policy)
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
    return {"clusters": clusters.snapshot()}


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


@app.post("/api/agent/report")
def agent_report(req: AgentReport,
                 x_agent_token: str | None = Header(default=None)):
    if not agents.token_valid(x_agent_token):
        raise HTTPException(401, "invalid or missing agent enrollment token")
    return agents.upsert_report(req.model_dump())


@app.get("/api/agents/token")
def agents_token(request: Request):
    # admin-only via ADMIN_RULES; shown on the GPU Fleet 'connect' card
    return {"token": agents.enroll_token()}


@app.get("/api/agent/work")
def agent_work(cluster_id: str,
               x_agent_token: str | None = Header(default=None)):
    if not agents.token_valid(x_agent_token):
        raise HTTPException(401, "invalid or missing agent enrollment token")
    return {"orders": work.orders_for(cluster_id)}


class WorkStatus(BaseModel):
    state: str
    endpoint: str = ""
    message: str = ""


@app.post("/api/agent/work/{order_id}")
def agent_work_status(order_id: str, req: WorkStatus,
                      x_agent_token: str | None = Header(default=None)):
    if not agents.token_valid(x_agent_token):
        raise HTTPException(401, "invalid or missing agent enrollment token")
    if req.state not in ("starting", "pulling", "ready", "error", "deleted"):
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
                                  req.cluster_id, req.residency)
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
def analytics_summary():
    return analytics.summary()


@app.get("/api/router/summary")
def router_summary():
    """Measured routing economics per policy (route/cascade/auto):
    small-model share and savings vs. sending everything to the
    strongest model — computed from recorded traffic, not projected."""
    return analytics.router_summary()


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


class RouterPreviewRequest(BaseModel):
    messages: list[ChatMessage]


@app.post("/api/router/preview")
def router_preview(req: RouterPreviewRequest):
    """Dry-run the smart router: classify without serving, so the UI
    can show where a prompt WOULD go and why."""
    routed = smart_router.route([m.model_dump() for m in req.messages])
    return routed["decision"]


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
                           authorization: str | None = Header(default=None)):
    """Unified API: `model: "auto"` routes via the recommender,
    `model: "cascade"` applies SLM-first routing with escalation, and
    `model: "route"` classifies the request BEFORE sending — exactly one
    model call, with a per-signal receipt of the decision.
    A team API key in the Authorization header attributes the spend and
    activates that team's tokenomics guardrails."""
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

    # ---- tokenomics guardrails (enforced at the gateway) --------------
    bearer = (authorization or "").removeprefix("Bearer ").strip() or None
    team = tokenomics.resolve_team(bearer)
    enforcement = None
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
                             policy=policy)
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
                },
            }
            return body
        except Exception as e:
            backend_info = {"type": "simulated-fallback",
                            "endpoint": real_endpoint,
                            "error": str(e)[:200]}

    sim = _simulate_completion(
        model, prompt,
        team_id=team["id"] if team else None,
        max_output_tokens=team.get("max_output_tokens") if team else None,
        policy=policy)

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
                        "receipt": {**routing_receipt(model, sim["tokens_in"],
                                                      sim["tokens_out"],
                                                      routed=is_routed),
                                    "backend": backend_info,
                                    **({"enforcement": enforcement} if enforcement else {}),
                                    **({"cascade": cascade_info} if cascade_info else {}),
                                    **({"router": router_info} if router_info else {})}},
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


_static = Path(__file__).resolve().parent.parent / "static"
if _static.is_dir():
    app.mount("/", _SPAStaticFiles(directory=_static, html=True), name="ui")
