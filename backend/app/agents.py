"""Agent registry — real clusters reporting into the control plane.

The Modelect agent (see agent/ in the repo) runs on any OpenShift or
Kubernetes cluster with GPUs, reads inventory from the NVIDIA GPU
Operator's node labels, and POSTs reports here on a heartbeat. The
pull model means outbound-only connectivity: no central kubeconfigs,
works through firewalls.

Enrollment uses a shared token generated once per install and persisted
in the data dir; admins read it from the GPU Fleet page.
"""
import hmac
import json
import os
import secrets
import time

from sqlalchemy import insert, select, update

from .db import DATA_DIR, agents_t, engine

STALE_AFTER = 90  # seconds without a heartbeat -> "stale"

# Contract version the control plane ships; agents report theirs and
# older ones are flagged in the attention queue (rolling upgrades:
# the /api/agent/v1/* paths stay stable within a major version).
LATEST_AGENT_VERSION = "2.0"


def enroll_token() -> str:
    path = os.path.join(DATA_DIR, "agent-token.txt")
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        token = f"ma-{secrets.token_hex(16)}"
        with open(path, "w") as f:
            f.write(token)
        return token


def token_valid(candidate: str | None) -> bool:
    return bool(candidate) and hmac.compare_digest(candidate, enroll_token())


def upsert_report(report: dict) -> dict:
    cluster_id = report["cluster_id"]
    row = {
        "cluster_id": cluster_id,
        "name": report.get("name") or cluster_id,
        "platform": report.get("platform", "kubernetes"),
        "version": report.get("version", ""),
        "region": report.get("region", ""),
        "residency": report.get("residency", ""),
        "cost_factor": float(report.get("cost_factor", 1.0)),
        "gpus_json": json.dumps(report.get("gpus", []))[:4000],
        "nodes": int(report.get("nodes", 0)),
        "last_seen": time.time(),
        "gpu_class": report.get("gpu_class")
                     or ("gpu-ready" if report.get("gpus") else "cpu-only"),
        "operator_detected": bool(report.get("operator_detected",
                                             bool(report.get("gpus")))),
        "driver_version": (report.get("driver_version") or "")[:40],
        "cuda_version": (report.get("cuda_version") or "")[:20],
        "agent_version": (report.get("agent_version") or "")[:20],
    }
    with engine.begin() as conn:
        existing = conn.execute(
            select(agents_t.c.cluster_id)
            .where(agents_t.c.cluster_id == cluster_id)).first()
        if existing:
            conn.execute(update(agents_t)
                         .where(agents_t.c.cluster_id == cluster_id).values(**row))
        else:
            conn.execute(insert(agents_t).values(**row))
    return {"ok": True, "cluster_id": cluster_id}


def real_clusters() -> list[dict]:
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(select(agents_t)).mappings()]
    out = []
    for r in rows:
        age = time.time() - (r["last_seen"] or 0)
        out.append({
            "id": r["cluster_id"], "name": r["name"],
            "platform": r["platform"], "version": r["version"],
            "region": r["region"], "residency": r["residency"],
            "cost_factor": r["cost_factor"] or 1.0,
            "labels": [],
            "gpus": json.loads(r["gpus_json"] or "[]"),
            "nodes": r["nodes"],
            "agent_age_s": int(age),
            "agent_status": "connected" if age < STALE_AFTER else "stale",
            "gpu_class": r["gpu_class"] or "cpu-only",
            "operator_detected": bool(r["operator_detected"]),
            "driver_version": r["driver_version"] or "",
            "cuda_version": r["cuda_version"] or "",
            "agent_version": r["agent_version"] or "",
            "source": "agent",
        })
    return out
