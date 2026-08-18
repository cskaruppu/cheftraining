"""Work orders — how deployments become real serving pods.

A deployment targeted at an agent-reported cluster is queued here; the
cluster's agent fetches its orders on each heartbeat, creates/deletes
the vLLM serving resources, and reports state back. The gateway proxies
to the reported endpoint once an order is ready.
"""
import time

from sqlalchemy import delete as sa_delete
from sqlalchemy import insert, select, update

from .db import engine, work_t

ACTIVE_STATES = ("pending", "starting", "pulling", "ready")


def enqueue(dep_id: str, cluster_id: str, model_id: str,
            hf_repo: str | None, gpu_count: int):
    with engine.begin() as conn:
        conn.execute(insert(work_t).values(
            id=dep_id, cluster_id=cluster_id, model_id=model_id,
            hf_repo=hf_repo or "", gpu_count=gpu_count,
            action="deploy", state="pending", endpoint="", message="",
            updated=time.time()))


def request_delete(dep_id: str):
    with engine.begin() as conn:
        row = conn.execute(select(work_t).where(work_t.c.id == dep_id)).mappings().first()
        if row is None:
            return
        conn.execute(update(work_t).where(work_t.c.id == dep_id)
                     .values(action="delete", state="pending", updated=time.time()))


def orders_for(cluster_id: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(select(work_t)
                            .where(work_t.c.cluster_id == cluster_id)).mappings().all()
    return [dict(r) for r in rows
            if not (r["action"] == "delete" and r["state"] == "deleted")]


def update_state(order_id: str, state: str, endpoint: str = "",
                 message: str = "") -> bool:
    with engine.begin() as conn:
        row = conn.execute(select(work_t).where(work_t.c.id == order_id)).mappings().first()
        if row is None:
            return False
        if row["action"] == "delete" and state == "deleted":
            conn.execute(sa_delete(work_t).where(work_t.c.id == order_id))
            return True
        values = {"state": state, "updated": time.time(), "message": message[:300]}
        if endpoint:
            values["endpoint"] = endpoint[:300]
        conn.execute(update(work_t).where(work_t.c.id == order_id).values(**values))
    return True


def state_for(dep_id: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(select(work_t).where(work_t.c.id == dep_id)).mappings().first()
    return dict(row) if row else None


def ready_endpoint_for_model(model_id: str) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(
            select(work_t.c.endpoint)
            .where(work_t.c.model_id == model_id,
                   work_t.c.state == "ready",
                   work_t.c.action == "deploy",
                   work_t.c.endpoint != "")).first()
    return row.endpoint if row else None
