"""Deployment manager — persisted, VM-style provisioning (simulated).

Deployment records live in the database, so they survive pod restarts;
GPU allocations on the fleet are re-derived from stored deployments at
boot. The provisioning lifecycle is still simulated; production swaps
the simulation for KServe/vLLM InferenceServices behind the same API.
"""
import json
import secrets
import time
import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import insert, select

from . import clusters
from .catalog import MODELS_BY_ID
from .db import deployments_t, engine

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

_STAGES = [("scheduling", 4), ("pulling_weights", 6), ("warming_up", 6)]
_TOTAL = sum(d for _, d in _STAGES)


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
    cluster_name = clusters.get_cluster_name(cluster_id)
    if cluster_name is None:
        raise ValueError("unknown cluster")
    if not clusters.allocate(cluster_id, profile["gpus"]):
        raise ValueError(f"cluster '{cluster_id}' lacks free GPUs for this profile")

    dep_id = uuid.uuid4().hex[:10]
    row = {
        "id": dep_id,
        "name": name or f"{model_id}-{dep_id[:4]}",
        "model_id": model_id,
        "model_name": model["name"],
        "profile_json": json.dumps(profile),
        "cluster_id": cluster_id,
        "cluster_name": cluster_name,
        "api_key": f"mk-{secrets.token_hex(16)}",
        "created_at": time.time(),
    }
    with engine.begin() as conn:
        conn.execute(insert(deployments_t).values(**row))
    return _public(row)


def _status(created_at: float) -> tuple[str, int]:
    elapsed = time.time() - created_at
    progress = min(100, int(elapsed / _TOTAL * 100))
    t = 0.0
    for status, duration in _STAGES:
        t += duration
        if elapsed < t:
            return status, progress
    return "ready", 100


def _public(row) -> dict:
    r = dict(row) if not isinstance(row, dict) else row
    status, progress = _status(r["created_at"])
    return {
        "id": r["id"], "name": r["name"],
        "model_id": r["model_id"], "model_name": r["model_name"],
        "profile": json.loads(r["profile_json"]),
        "api_key": r["api_key"],
        "cluster_id": r["cluster_id"], "cluster_name": r["cluster_name"],
        "status": status, "progress": progress,
        "endpoint_path": "/v1/chat/completions",
    }


def list_all() -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(select(deployments_t)).mappings().all()
    return sorted((_public(r) for r in rows), key=lambda d: d["name"])


def delete(dep_id: str) -> bool:
    with engine.begin() as conn:
        row = conn.execute(select(deployments_t)
                           .where(deployments_t.c.id == dep_id)).mappings().first()
        if row is None:
            return False
        conn.execute(sa_delete(deployments_t).where(deployments_t.c.id == dep_id))
    profile = json.loads(row["profile_json"])
    clusters.release(row["cluster_id"], profile["gpus"])
    return True


def restore_allocations():
    """Re-derive fleet GPU allocations from persisted deployments (boot)."""
    with engine.connect() as conn:
        rows = conn.execute(select(deployments_t)).mappings().all()
    for r in rows:
        profile = json.loads(r["profile_json"])
        clusters.allocate(r["cluster_id"], profile["gpus"])


restore_allocations()
