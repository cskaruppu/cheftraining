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

from fastapi import FastAPI, HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analytics, clusters, deployments, evals, integration, migrate, registry
from .catalog import MODELS, MODELS_BY_ID, USE_CASES, QUALITY_DIMS
from .recommender import recommend, routing_receipt, similar_models

app = FastAPI(title="Modelect — Multi-LLM Orchestrator", version="0.1.0-demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


analytics.seed()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


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
    return {"models": items, "providers": sorted({m["provider"] for m in MODELS}),
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


def _simulate_completion(model: dict, prompt: str) -> dict:
    """Demo mode: synthesizes a response instead of calling the provider.

    Production wiring point — replace with the provider adapter call
    (or route through the Go gateway) once API keys are configured.
    """
    rng = random.Random(hash((model["id"], prompt)) & 0xFFFF)
    tokens_in = max(8, len(prompt.split()) * 4 // 3)
    tokens_out = rng.randint(90, 220)
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
    analytics.record(model["id"], tokens_in, tokens_out, latency)
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


# ---------------- OpenAI-compatible demo gateway ----------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "auto"
    messages: list[ChatMessage]
    stream: bool = False


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    """Unified API: `model: "auto"` lets the recommender route the call."""
    if req.model == "auto":
        rec = recommend("chatbot", {"quality": 40, "cost": 40, "speed": 20})
        model = rec["results"][0]["model"]
    elif req.model in MODELS_BY_ID:
        model = MODELS_BY_ID[req.model]
    else:
        raise HTTPException(404, f"unknown model '{req.model}' — GET /api/models for the catalog")

    prompt = req.messages[-1].content if req.messages else ""
    sim = _simulate_completion(model, prompt)
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
            "modelect": {"routed": req.model == "auto", "latency_ms": sim["latency_ms"],
                        "cost_usd": sim["cost"],
                        "receipt": routing_receipt(model, sim["tokens_in"],
                                                   sim["tokens_out"],
                                                   routed=req.model == "auto")},
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
