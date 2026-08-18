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
        "gpus": [
            {"family": "A100", "type": "NVIDIA A100 80GB", "count": 8, "used": 5},
            {"family": "L40S", "type": "NVIDIA L40S 48GB", "count": 4, "used": 1},
        ],
    },
    {
        "id": "eu-west-osh",
        "name": "EU West — OpenShift",
        "platform": "openshift", "version": "4.15",
        "region": "eu-west", "residency": "eu",
        "cost_factor": 1.15,
        "labels": ["env=prod", "data-residency=eu"],
        "gpus": [
            {"family": "H100", "type": "NVIDIA H100 80GB", "count": 2, "used": 2},
            {"family": "L40S", "type": "NVIDIA L40S 48GB", "count": 4, "used": 3},
        ],
    },
    {
        "id": "cloud-burst",
        "name": "Cloud Burst — EKS (spot)",
        "platform": "kubernetes", "version": "1.30",
        "region": "us-west", "residency": "us",
        "cost_factor": 0.6,
        "labels": ["env=burst", "pricing=spot"],
        "gpus": [
            {"family": "H100", "type": "NVIDIA H100 80GB", "count": 4, "used": 0},
            {"family": "L4", "type": "NVIDIA L4 24GB", "count": 8, "used": 1},
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


def snapshot() -> list[dict]:
    now = time.time()
    out = []
    if _sims_enabled():
        for c in _SIM_CLUSTERS:
            total = sum(g["count"] for g in c["gpus"])
            used = sum(g["used"] for g in c["gpus"])
            out.append({
                **{k: c[k] for k in ("id", "name", "platform", "version",
                                     "region", "residency", "cost_factor", "labels")},
                "gpus": [{**g, "free": g["count"] - g["used"]} for g in c["gpus"]],
                "utilization_pct": int(used / total * 100) if total else 0,
                "agent_status": "connected",
                "last_heartbeat_s": int(now % 9) + 2,
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
                         "mode": g.get("mode", "dedicated")})
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
            "source": "agent",
        })
    return out


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
