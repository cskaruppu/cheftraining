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

from . import agents, clusters, work
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


_SIZE_ORDER = {"xl": 0, "large": 1, "medium": 2, "small": 3}


def fits_preview(cluster: dict) -> dict | None:
    """Admission preview for a fleet card: the LARGEST self-hostable
    model this cluster could still schedule right now, and on which
    profile. Answers 'can I deploy model X here?' before anyone tries."""
    if cluster.get("cordoned") or cluster.get("gpu_class") not in (None, "gpu-ready"):
        return None
    free = {g["family"]: g["free"] for g in cluster.get("gpus", [])}
    for model_id in sorted(_SIZE_CLASS, key=lambda m: _SIZE_ORDER[_SIZE_CLASS[m]]):
        model = MODELS_BY_ID.get(model_id)
        if not model:
            continue
        for p in serving_profiles(model_id):
            needed, family = clusters.parse_profile_gpus(p["gpus"])
            if free.get(family, 0) >= needed:
                return {"model_id": model_id, "model_name": model["name"],
                        "profile": p["gpus"], "quantization": p["quantization"]}
    return None


def create(model_id: str, profile_id: str, name: str,
           cluster_id: str | None = None, residency: str | None = None,
           serving_class: str | None = None) -> dict:
    if serving_class not in (None, "reserved", "on-demand"):
        raise ValueError("serving_class must be 'reserved' or 'on-demand'")
    if cluster_id and cluster_id in clusters.cordoned_ids():
        raise ValueError(f"cluster '{cluster_id}' is cordoned for maintenance "
                         "— uncordon it or let auto-placement choose")
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

    # thin provisioning is the norm for small models: SLMs default to
    # on-demand (scale-to-zero), larger models to reserved
    if serving_class is None:
        serving_class = "on-demand" if model.get("size_class") == "slm" \
            else "reserved"

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
        "serving_class": serving_class,
        "asleep": False,
    }
    with engine.begin() as conn:
        conn.execute(insert(deployments_t).values(**row))

    from . import ledger
    ledger.record("placement", model_id,
                  summary=f"deployed '{row['name']}' ({profile['gpus']}) "
                          f"on {cluster_name}",
                  receipt={"cluster_id": cluster_id, "profile": profile,
                           "residency": residency})

    # real (agent) cluster: queue the serving work order for its agent
    if cluster_id in {c["id"] for c in agents.real_clusters()}:
        gpu_count, _fam = clusters.parse_profile_gpus(profile["gpus"])
        work.enqueue(dep_id, cluster_id, model_id,
                     model.get("hf_repo"), gpu_count)
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


_WORK_STATUS = {"pending": ("scheduling", 10), "starting": ("warming_up", 60),
                "pulling": ("pulling_weights", 40), "ready": ("ready", 100),
                "error": ("error", 100)}


def _public(row) -> dict:
    r = dict(row) if not isinstance(row, dict) else row
    status, progress = _status(r["created_at"])
    backend, real_endpoint, message = "simulated", "", ""
    order = work.state_for(r["id"])
    if order and order["action"] in ("deploy", "wake"):
        # agent-executed deployment: real state beats the simulated timeline
        status, progress = _WORK_STATUS.get(order["state"], ("scheduling", 10))
        backend = "agent"
        real_endpoint = order["endpoint"] or ""
        message = order["message"] or ""
    elif order:
        backend = "agent"
    if r.get("asleep"):
        status, progress = "sleeping", 100
        message = "scale-to-zero: vGPU returned to the pool — first request wakes it"
    return {
        "id": r["id"], "name": r["name"],
        "model_id": r["model_id"], "model_name": r["model_name"],
        "profile": json.loads(r["profile_json"]),
        "api_key": r["api_key"],
        "cluster_id": r["cluster_id"], "cluster_name": r["cluster_name"],
        "status": status, "progress": progress,
        "backend": backend, "real_endpoint": real_endpoint, "message": message,
        "endpoint_path": "/v1/chat/completions",
        "serving_class": r.get("serving_class") or "reserved",
        "asleep": bool(r.get("asleep")),
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
        # close any open sleep period so GPU-hours stop accruing
        from .db import sleep_log_t
        conn.execute(sleep_log_t.update()
                     .where(sleep_log_t.c.dep_id == dep_id,
                            sleep_log_t.c.woke_at.is_(None))
                     .values(woke_at=time.time()))
    if not row["asleep"]:  # a sleeping deployment already released its slice
        profile = json.loads(row["profile_json"])
        clusters.release(row["cluster_id"], profile["gpus"])
    work.request_delete(dep_id)  # agent tears down the serving pod
    return True


def restore_allocations():
    """Re-derive fleet GPU allocations from persisted deployments (boot).
    Sleeping on-demand deployments hold no allocation — that's the point
    of scale-to-zero — so they are skipped."""
    with engine.connect() as conn:
        rows = conn.execute(select(deployments_t)).mappings().all()
    for r in rows:
        if r["asleep"]:
            continue
        profile = json.loads(r["profile_json"])
        clusters.allocate(r["cluster_id"], profile["gpus"])


restore_allocations()
