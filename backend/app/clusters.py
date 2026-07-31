"""Multi-cluster GPU fleet (Phase A — simulated agents).

Hub-and-spoke model: each OpenShift/Kubernetes cluster runs a Modelect
agent that dials out to this control plane, registers, and reports GPU
inventory and utilization (in production: read from the NVIDIA GPU
Operator's node labels; executed via OCM/ACM manifestwork). The demo
ships three simulated registered clusters so the placement engine and
fleet view work end-to-end.
"""
import re
import time

_CLUSTERS = [
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

CLUSTERS_BY_ID = {c["id"]: c for c in _CLUSTERS}

_GPU_RE = re.compile(r"(\d+)x NVIDIA (\S+)")


def parse_profile_gpus(gpus: str) -> tuple[int, str]:
    """'2x NVIDIA H100 80GB' -> (2, 'H100')"""
    m = _GPU_RE.match(gpus)
    if not m:
        return 1, ""
    return int(m.group(1)), m.group(2)


def _utilization(c: dict) -> int:
    total = sum(g["count"] for g in c["gpus"])
    used = sum(g["used"] for g in c["gpus"])
    return int(used / total * 100) if total else 0


def snapshot() -> list[dict]:
    now = time.time()
    out = []
    for c in _CLUSTERS:
        out.append({
            **{k: c[k] for k in ("id", "name", "platform", "version",
                                 "region", "residency", "cost_factor", "labels")},
            "gpus": [{**g, "free": g["count"] - g["used"]} for g in c["gpus"]],
            "utilization_pct": _utilization(c),
            "agent_status": "connected",
            "last_heartbeat_s": int(now % 9) + 2,  # demo: a few seconds ago
        })
    return out


def place(profile_gpus: str, residency: str | None = None) -> dict:
    """Rank clusters for a serving profile. Transparent scoring:
    free capacity, headroom, cost, with residency as a hard filter."""
    needed, family = parse_profile_gpus(profile_gpus)
    ranked = []
    for c in _CLUSTERS:
        entry = {"cluster_id": c["id"], "cluster_name": c["name"], "reasons": []}
        if residency and c["residency"] != residency:
            entry.update(eligible=False)
            entry["reasons"].append(f"excluded: residency '{c['residency']}' != required '{residency}'")
            ranked.append(entry)
            continue
        pool = next((g for g in c["gpus"] if g["family"] == family), None)
        free = (pool["count"] - pool["used"]) if pool else 0
        if free < needed:
            entry.update(eligible=False)
            entry["reasons"].append(
                f"insufficient capacity: needs {needed}x {family}, {free} free")
            ranked.append(entry)
            continue
        util = _utilization(c)
        score = (free / pool["count"]) * 40 + (100 - util) * 0.3 + (1 / c["cost_factor"]) * 20
        entry.update(eligible=True, score=round(score, 1))
        entry["reasons"] = [
            f"{free}x {family} free of {pool['count']}",
            f"cluster utilization {util}%",
            f"cost factor {c['cost_factor']}x" + (" (spot pricing)" if c["cost_factor"] < 1 else ""),
        ]
        ranked.append(entry)
    ranked.sort(key=lambda e: (e.get("eligible", False), e.get("score", 0)), reverse=True)
    best = ranked[0] if ranked and ranked[0].get("eligible") else None
    return {"recommended": best, "clusters": ranked,
            "requirement": f"{needed}x {family}"}


def allocate(cluster_id: str, profile_gpus: str) -> bool:
    needed, family = parse_profile_gpus(profile_gpus)
    c = CLUSTERS_BY_ID.get(cluster_id)
    if not c:
        return False
    pool = next((g for g in c["gpus"] if g["family"] == family), None)
    if not pool or pool["count"] - pool["used"] < needed:
        return False
    pool["used"] += needed
    return True


def release(cluster_id: str, profile_gpus: str) -> None:
    needed, family = parse_profile_gpus(profile_gpus)
    c = CLUSTERS_BY_ID.get(cluster_id)
    if not c:
        return
    pool = next((g for g in c["gpus"] if g["family"] == family), None)
    if pool:
        pool["used"] = max(0, pool["used"] - needed)
