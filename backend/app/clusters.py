"""Multi-cluster GPU fleet.

Two sources, one fleet view:
- REAL clusters: reported by the Modelect agent (agent/ in the repo)
  running on the cluster — inventory from NVIDIA GPU Operator node
  labels, outbound-only heartbeats (see agents.py).
- SIMULATED clusters: three demo clusters so the fleet story works
  before any agent is installed. Hide them with SIM_CLUSTERS=0.

Placement, allocation and release treat both identically; Modelect's
own GPU allocations (from deployments) are tracked per cluster/family.
"""
import os
import re
import time

from . import agents

_SIM_CLUSTERS = [
    {
        "id": "onprem-dc1",
        "name": "DC1 — On-prem OpenShift",
        "platform": "openshift", "version": "4.16",
        "region": "us-east", "residency": "us",
        "cost_factor": 1.0,
        "labels": ["env=prod", "tier=primary"],
        "driver_version": "550.90.07", "cuda_version": "12.4",
        "gpus": [
            {"family": "A100", "type": "NVIDIA A100 80GB", "count": 8, "used": 5, "vram_gb": 80},
            {"family": "L40S", "type": "NVIDIA L40S 48GB", "count": 4, "used": 1, "vram_gb": 48},
        ],
    },
    {
        "id": "eu-west-osh",
        "name": "EU West — OpenShift",
        "platform": "openshift", "version": "4.15",
        "region": "eu-west", "residency": "eu",
        "cost_factor": 1.15,
        "labels": ["env=prod", "data-residency=eu"],
        "driver_version": "550.54.15", "cuda_version": "12.4",
        "gpus": [
            {"family": "H100", "type": "NVIDIA H100 80GB", "count": 2, "used": 2, "vram_gb": 80},
            {"family": "L40S", "type": "NVIDIA L40S 48GB", "count": 4, "used": 3, "vram_gb": 48},
        ],
    },
    {
        "id": "cloud-burst",
        "name": "Cloud Burst — EKS (spot)",
        "platform": "kubernetes", "version": "1.30",
        "region": "us-west", "residency": "us",
        "cost_factor": 0.6,
        "labels": ["env=burst", "pricing=spot"],
        "driver_version": "560.28.03", "cuda_version": "12.6",
        "gpus": [
            {"family": "H100", "type": "NVIDIA H100 80GB", "count": 4, "used": 0, "vram_gb": 80},
            {"family": "L4", "type": "NVIDIA L4 24GB", "count": 8, "used": 1, "vram_gb": 24},
        ],
    },
]

# Modelect's own allocations on real (agent) clusters: (cluster_id, family) -> used
_REAL_USED: dict[tuple[str, str], int] = {}

_GPU_RE = re.compile(r"(\d+)x NVIDIA (\S+)")


def parse_profile_gpus(gpus: str) -> tuple[int, str]:
    """'2x NVIDIA H100 80GB' -> (2, 'H100')"""
    m = _GPU_RE.match(gpus)
    if not m:
        return 1, ""
    return int(m.group(1)), m.group(2)


def _sims_enabled() -> bool:
    return os.environ.get("SIM_CLUSTERS", "1") != "0"


# ---- maintenance mode (cordon) --------------------------------------
# vSphere-style: a cordoned cluster stays visible but the placement
# engine skips it, with the reason in every receipt.

def cordoned_ids() -> set[str]:
    from .resilience import kv_get
    raw = kv_get("cordoned_clusters") or ""
    return {c for c in raw.split(",") if c}


def set_cordon(cluster_id: str, cordoned: bool) -> set[str]:
    from .resilience import kv_set
    ids = cordoned_ids()
    (ids.add if cordoned else ids.discard)(cluster_id)
    kv_set("cordoned_clusters", ",".join(sorted(ids)) or None)
    return ids


# ---- allocation history (24h sparkline) -----------------------------
# Sampled from the fleet snapshot, throttled to one point per cluster
# per 10 minutes so dashboard polling doesn't flood the table.

_HIST_EVERY_S = 600
_last_hist: dict[str, float] = {}


def _record_history(cluster_id: str, util_pct: int) -> None:
    from sqlalchemy import delete, insert
    from .db import cluster_util_t, engine
    now = time.time()
    if now - _last_hist.get(cluster_id, 0) < _HIST_EVERY_S:
        return
    _last_hist[cluster_id] = now
    with engine.begin() as conn:
        conn.execute(insert(cluster_util_t).values(
            cluster_id=cluster_id, ts=now, util_pct=util_pct))
        conn.execute(delete(cluster_util_t)
                     .where(cluster_util_t.c.ts < now - 48 * 3600))


def _history(cluster_id: str) -> list[int]:
    from sqlalchemy import select
    from .db import cluster_util_t, engine
    since = time.time() - 24 * 3600
    with engine.connect() as conn:
        rows = conn.execute(
            select(cluster_util_t.c.util_pct)
            .where(cluster_util_t.c.cluster_id == cluster_id,
                   cluster_util_t.c.ts >= since)
            .order_by(cluster_util_t.c.ts)).all()
    return [r.util_pct for r in rows]


# 0.4 kW sustained draw per allocated GPU x 0.35 kgCO2e/kWh grid factor.
# An estimate and labeled as one in the UI; refined by DCGM power
# telemetry in production.
def _carbon_kg_day(used_gpus: int) -> float:
    return round(used_gpus * 0.4 * 24 * 0.35, 1)


def _enrich(c: dict) -> dict:
    used = sum(g["used"] for g in c["gpus"])
    c["cordoned"] = c["id"] in cordoned_ids()
    c["carbon_kg_day"] = _carbon_kg_day(used)
    _record_history(c["id"], c["utilization_pct"])
    c["util_history"] = _history(c["id"])
    return c


def snapshot() -> list[dict]:
    now = time.time()
    out = []
    if _sims_enabled():
        for c in _SIM_CLUSTERS:
            total = sum(g["count"] for g in c["gpus"])
            used = sum(g["used"] for g in c["gpus"])
            out.append({
                **{k: c[k] for k in ("id", "name", "platform", "version",
                                     "region", "residency", "cost_factor", "labels",
                                     "driver_version", "cuda_version")},
                "gpus": [{**g, "free": g["count"] - g["used"]} for g in c["gpus"]],
                "utilization_pct": int(used / total * 100) if total else 0,
                "agent_status": "connected",
                "last_heartbeat_s": int(now % 9) + 2,
                "gpu_class": "gpu-ready",
                "operator_detected": True,
                "source": "simulated",
            })
    for c in agents.real_clusters():
        gpus = []
        for g in c["gpus"]:
            used = _REAL_USED.get((c["id"], g.get("family", "")), 0)
            count = int(g.get("count", 0))
            gpus.append({"family": g.get("family", ""), "type": g.get("type", ""),
                         "count": count, "used": used, "free": max(0, count - used),
                         "virtual": bool(g.get("virtual", False)),
                         "mode": g.get("mode", "dedicated"),
                         **({"vram_gb": g["vram_gb"]} if g.get("vram_gb") else {})})
        total = sum(g["count"] for g in gpus)
        used_total = sum(g["used"] for g in gpus)
        out.append({
            "id": c["id"], "name": c["name"], "platform": c["platform"],
            "version": c["version"], "region": c["region"],
            "residency": c["residency"], "cost_factor": c["cost_factor"],
            "labels": c["labels"] + [f"nodes={c['nodes']}"],
            "gpus": gpus,
            "utilization_pct": int(used_total / total * 100) if total else 0,
            "agent_status": c["agent_status"],
            "last_heartbeat_s": c["agent_age_s"],
            "gpu_class": c["gpu_class"],
            "operator_detected": c["operator_detected"],
            "driver_version": c.get("driver_version", ""),
            "cuda_version": c.get("cuda_version", ""),
            "source": "agent",
        })
    return [_enrich(c) for c in out]


def get_cluster_name(cluster_id: str) -> str | None:
    for c in snapshot():
        if c["id"] == cluster_id:
            return c["name"]
    return None


def place(profile_gpus: str, residency: str | None = None) -> dict:
    """Rank clusters for a serving profile. Transparent scoring:
    free capacity, headroom, cost, with residency as a hard filter."""
    needed, family = parse_profile_gpus(profile_gpus)
    ranked = []
    for c in snapshot():
        entry = {"cluster_id": c["id"], "cluster_name": c["name"],
                 "source": c["source"], "reasons": []}
        if c.get("cordoned"):
            entry.update(eligible=False)
            entry["reasons"].append(
                "cordoned for maintenance — placement skips this cluster")
            ranked.append(entry)
            continue
        if residency and c["residency"] != residency:
            entry.update(eligible=False)
            entry["reasons"].append(f"excluded: residency '{c['residency']}' != required '{residency}'")
            ranked.append(entry)
            continue
        if c["source"] == "agent" and c["agent_status"] != "connected":
            entry.update(eligible=False)
            entry["reasons"].append("agent heartbeat stale — not schedulable")
            ranked.append(entry)
            continue
        if c.get("gpu_class") and c["gpu_class"] != "gpu-ready":
            entry.update(eligible=False)
            reason = f"not GPU-schedulable (class: {c['gpu_class']})"
            if c["gpu_class"] == "gpu-unmanaged":
                reason += " — GPUs present but the NVIDIA GPU Operator is missing"
            entry["reasons"].append(reason)
            ranked.append(entry)
            continue
        pool = next((g for g in c["gpus"] if g["family"] == family), None)
        free = pool["free"] if pool else 0
        if free < needed:
            entry.update(eligible=False)
            entry["reasons"].append(
                f"insufficient capacity: needs {needed}x {family}, {free} free")
            ranked.append(entry)
            continue
        util = c["utilization_pct"]
        score = (free / pool["count"]) * 40 + (100 - util) * 0.3 + (1 / c["cost_factor"]) * 20
        entry.update(eligible=True, score=round(score, 1))
        entry["reasons"] = [
            f"{free}x {family} free of {pool['count']}",
            f"cluster utilization {util}%",
            f"cost factor {c['cost_factor']}x" + (" (spot pricing)" if c["cost_factor"] < 1 else ""),
        ]
        if c["source"] == "agent":
            entry["reasons"].append("live agent-reported inventory")
        ranked.append(entry)
    ranked.sort(key=lambda e: (e.get("eligible", False), e.get("score", 0)), reverse=True)
    best = ranked[0] if ranked and ranked[0].get("eligible") else None
    return {"recommended": best, "clusters": ranked,
            "requirement": f"{needed}x {family}"}


def _sim_pool(cluster_id: str, family: str):
    c = next((x for x in _SIM_CLUSTERS if x["id"] == cluster_id), None)
    if not c:
        return None
    return next((g for g in c["gpus"] if g["family"] == family), None)


def allocate(cluster_id: str, profile_gpus: str) -> bool:
    needed, family = parse_profile_gpus(profile_gpus)
    pool = _sim_pool(cluster_id, family)
    if pool is not None:
        if pool["count"] - pool["used"] < needed:
            return False
        pool["used"] += needed
        return True
    # real (agent) cluster
    real = next((c for c in agents.real_clusters() if c["id"] == cluster_id), None)
    if real is None:
        return False
    cap = next((int(g.get("count", 0)) for g in real["gpus"]
                if g.get("family") == family), 0)
    used = _REAL_USED.get((cluster_id, family), 0)
    if cap - used < needed:
        return False
    _REAL_USED[(cluster_id, family)] = used + needed
    return True


def release(cluster_id: str, profile_gpus: str) -> None:
    needed, family = parse_profile_gpus(profile_gpus)
    pool = _sim_pool(cluster_id, family)
    if pool is not None:
        pool["used"] = max(0, pool["used"] - needed)
        return
    key = (cluster_id, family)
    if key in _REAL_USED:
        _REAL_USED[key] = max(0, _REAL_USED[key] - needed)
