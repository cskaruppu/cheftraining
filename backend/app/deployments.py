"""Deployment manager — Phase 1 (simulated provisioning).

VM-style self-service: pick a self-hostable model, pick a serving
profile (GPU + quantization sizing), deploy, get an endpoint + API key.
This demo simulates the provisioning lifecycle in-memory; production
swaps the simulation for a KServe/vLLM InferenceService created on the
cluster — the API contract stays identical.
"""
import secrets
import time
import uuid

from . import clusters
from .catalog import MODELS_BY_ID

# Rough deployment size classes for the self-hostable catalog entries.
_SIZE_CLASS = {
    "phi-4": "small",
    "mistral-small-3.2": "small",
    "llama-4-scout": "medium",
    "vllm-local-llama-3.3-70b": "medium",
    "llama-4-maverick": "large",
    "qwen3-235b": "large",
    "deepseek-v3.2": "xl",
    "deepseek-r1": "xl",
}

# Per class: (profile id, GPUs, quantization, $/hr, throughput multiplier)
_PROFILE_TEMPLATES = {
    "small": [
        ("econ", "1x NVIDIA L4 24GB", "INT8", 0.60, 0.8, False),
        ("balanced", "1x NVIDIA L40S 48GB", "FP16", 1.10, 1.0, True),
    ],
    "medium": [
        ("econ", "2x NVIDIA L40S 48GB", "AWQ 4-bit", 2.20, 0.7, False),
        ("balanced", "1x NVIDIA H100 80GB", "FP8", 3.80, 1.0, True),
        ("perf", "2x NVIDIA A100 80GB", "FP16", 4.40, 1.2, False),
    ],
    "large": [
        ("balanced", "2x NVIDIA H100 80GB", "FP8", 7.60, 1.0, True),
        ("perf", "4x NVIDIA A100 80GB", "FP16", 8.80, 1.2, False),
    ],
    "xl": [
        ("balanced", "4x NVIDIA H100 80GB", "FP8", 15.20, 1.0, True),
        ("perf", "8x NVIDIA A100 80GB", "FP16", 17.60, 1.15, False),
    ],
}

# Provisioning stages: (status, duration seconds) — then "ready".
_STAGES = [("scheduling", 4), ("pulling_weights", 6), ("warming_up", 6)]
_TOTAL = sum(d for _, d in _STAGES)

_DEPLOYMENTS: dict[str, dict] = {}


def serving_profiles(model_id: str) -> list[dict]:
    model = MODELS_BY_ID.get(model_id)
    if not model or not model["self_hostable"]:
        return []
    cls = _SIZE_CLASS.get(model_id, "medium")
    out = []
    for pid, gpus, quant, cost_hr, tps_mult, recommended in _PROFILE_TEMPLATES[cls]:
        out.append({
            "id": pid,
            "gpus": gpus,
            "quantization": quant,
            "est_cost_hr": cost_hr,
            "est_cost_month": round(cost_hr * 730, 0),
            "est_throughput_tps": int(model["throughput_tps"] * tps_mult),
            "recommended": recommended,
        })
    return out


def create(model_id: str, profile_id: str, name: str,
           cluster_id: str | None = None, residency: str | None = None) -> dict:
    model = MODELS_BY_ID.get(model_id)
    if not model or not model["self_hostable"]:
        raise ValueError("model is not self-hostable")
    profile = next((p for p in serving_profiles(model_id) if p["id"] == profile_id), None)
    if not profile:
        raise ValueError("unknown serving profile")

    if not cluster_id:  # auto-placement via the fleet engine
        placement = clusters.place(profile["gpus"], residency)
        if not placement["recommended"]:
            raise ValueError("no cluster has capacity for this profile"
                             + (f" with residency '{residency}'" if residency else ""))
        cluster_id = placement["recommended"]["cluster_id"]
    if cluster_id not in clusters.CLUSTERS_BY_ID:
        raise ValueError("unknown cluster")
    if not clusters.allocate(cluster_id, profile["gpus"]):
        raise ValueError(f"cluster '{cluster_id}' lacks free GPUs for this profile")

    dep_id = uuid.uuid4().hex[:10]
    dep = {
        "id": dep_id,
        "name": name or f"{model_id}-{dep_id[:4]}",
        "model_id": model_id,
        "model_name": model["name"],
        "profile": profile,
        "cluster_id": cluster_id,
        "cluster_name": clusters.CLUSTERS_BY_ID[cluster_id]["name"],
        "api_key": f"mk-{secrets.token_hex(16)}",
        "created_at": time.time(),
    }
    _DEPLOYMENTS[dep_id] = dep
    return _public(dep)


def _status(dep: dict) -> tuple[str, int]:
    elapsed = time.time() - dep["created_at"]
    progress = min(100, int(elapsed / _TOTAL * 100))
    t = 0.0
    for status, duration in _STAGES:
        t += duration
        if elapsed < t:
            return status, progress
    return "ready", 100


def _public(dep: dict) -> dict:
    status, progress = _status(dep)
    return {
        "id": dep["id"], "name": dep["name"],
        "model_id": dep["model_id"], "model_name": dep["model_name"],
        "profile": dep["profile"], "api_key": dep["api_key"],
        "cluster_id": dep.get("cluster_id"), "cluster_name": dep.get("cluster_name"),
        "status": status, "progress": progress,
        # In production this is the per-deployment KServe endpoint; in the
        # demo every deployment is served by the built-in gateway.
        "endpoint_path": "/v1/chat/completions",
    }


def list_all() -> list[dict]:
    return sorted((_public(d) for d in _DEPLOYMENTS.values()),
                  key=lambda d: d["name"])


def delete(dep_id: str) -> bool:
    dep = _DEPLOYMENTS.pop(dep_id, None)
    if dep is None:
        return False
    if dep.get("cluster_id"):
        clusters.release(dep["cluster_id"], dep["profile"]["gpus"])
    return True
