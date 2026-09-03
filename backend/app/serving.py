"""Serving lifecycle — GPU thin provisioning for models.

vSphere's most-loved disciplines, applied to LLM serving:

- SERVING CLASSES: "reserved" (always-on slice, SLO latency) and
  "on-demand" (scale-to-zero: idle beyond a threshold -> the vLLM
  deployment sleeps and its vGPU allocation returns to the pool; the
  first request wakes it). SLMs default to on-demand — thin
  provisioning should be the norm for small models.
- AUTO-RECLAIM: a throttled sweep finds idle on-demand deployments
  (no traffic for `idle_sleep_minutes`, admin-tunable) and puts them
  to sleep — the attention queue's "idle GPU" nag becomes an action
  the platform takes itself, ledgered like every other decision.
- WAKE: simulated clusters wake instantly (the demo timeline); agent
  clusters get a wake work order and the gateway answers 503 +
  Retry-After with an honest "warming up" body until vLLM is ready.
- GPU-HOURS RECLAIMED: every sleep period is logged (sleep_log);
  the summed hours are the measured thin-provisioning payoff.
"""
import json
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select, update

from . import clusters, config, ledger, work
from .db import deployments_t, engine, events_t, sleep_log_t

_SWEEP_EVERY_S = 60
_last_sweep = {"at": 0.0}


def _dep(dep_id: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(select(deployments_t)
                           .where(deployments_t.c.id == dep_id)).mappings().first()
    return dict(row) if row else None


def _gpus_of(dep: dict) -> tuple[str, int]:
    profile = json.loads(dep["profile_json"])
    count, _fam = clusters.parse_profile_gpus(profile["gpus"])
    return profile["gpus"], count


def _is_sim(cluster_id: str) -> bool:
    c = next((c for c in clusters.snapshot() if c["id"] == cluster_id), None)
    return bool(c and c["source"] == "simulated")


def sleep(dep_id: str, reason: str = "manual") -> dict:
    dep = _dep(dep_id)
    if not dep:
        raise ValueError("unknown deployment")
    if dep.get("asleep"):
        return {"dep_id": dep_id, "asleep": True, "note": "already sleeping"}
    if (dep.get("serving_class") or "reserved") != "on-demand":
        raise ValueError("only on-demand deployments sleep — reserved keeps "
                         "its slice for SLO latency")
    gpus_str, count = _gpus_of(dep)
    clusters.release(dep["cluster_id"], gpus_str)
    with engine.begin() as conn:
        conn.execute(update(deployments_t).where(deployments_t.c.id == dep_id)
                     .values(asleep=True))
        conn.execute(insert(sleep_log_t).values(
            dep_id=dep_id, cluster_id=dep["cluster_id"], gpus=count,
            slept_at=time.time(), woke_at=None))
    if not _is_sim(dep["cluster_id"]):
        work.request_action(dep_id, "sleep")
    ledger.record("placement", dep["model_id"],
                  summary=f"scale-to-zero: '{dep['name']}' asleep ({reason}) — "
                          f"{count} vGPU returned to {dep['cluster_name']}",
                  receipt={"dep_id": dep_id, "reason": reason,
                           "gpus_freed": count, "class": "on-demand"})
    return {"dep_id": dep_id, "asleep": True, "gpus_freed": count}


def wake(dep_id: str, reason: str = "manual") -> dict:
    dep = _dep(dep_id)
    if not dep:
        raise ValueError("unknown deployment")
    if not dep.get("asleep"):
        return {"dep_id": dep_id, "asleep": False, "note": "already awake"}
    gpus_str, count = _gpus_of(dep)
    if not clusters.allocate(dep["cluster_id"], gpus_str):
        raise ValueError(
            f"cluster '{dep['cluster_name']}' no longer has {count} free "
            "vGPU for this profile — capacity was reused while asleep")
    now = time.time()
    with engine.begin() as conn:
        conn.execute(update(deployments_t).where(deployments_t.c.id == dep_id)
                     .values(asleep=False))
        conn.execute(update(sleep_log_t)
                     .where(sleep_log_t.c.dep_id == dep_id,
                            sleep_log_t.c.woke_at.is_(None))
                     .values(woke_at=now))
    warming = False
    if not _is_sim(dep["cluster_id"]):
        work.request_action(dep_id, "wake")
        warming = True  # vLLM restart + weight load; gateway 503s meanwhile
    ledger.record("placement", dep["model_id"],
                  summary=f"wake: '{dep['name']}' ({reason}) — {count} vGPU "
                          f"re-allocated on {dep['cluster_name']}"
                          + (" — warming up" if warming else ""),
                  receipt={"dep_id": dep_id, "reason": reason, "warming": warming})
    return {"dep_id": dep_id, "asleep": False, "warming": warming}


def ensure_awake(model_id: str) -> dict | None:
    """Gateway hook: if this model's only deployments are asleep, wake
    them. Returns a wake receipt block, or None when nothing applied.
    Simulated clusters wake instantly; agent clusters warm up (the
    caller should 503 with Retry-After)."""
    with engine.connect() as conn:
        rows = conn.execute(select(deployments_t)
                            .where(deployments_t.c.model_id == model_id,
                                   deployments_t.c.asleep.is_(True))).mappings().all()
    if not rows:
        return None
    results = []
    for dep in rows:
        try:
            results.append(wake(dep["id"], reason="first request after sleep"))
        except ValueError as e:
            results.append({"dep_id": dep["id"], "error": str(e)})
    warming = any(r.get("warming") for r in results)
    return {"woke": [r["dep_id"] for r in results if not r.get("error")],
            "warming": warming}


def auto_sweep() -> list[str]:
    """Throttled reclaim loop: sleep idle on-demand deployments.
    A deployment is idle when its model served no traffic for
    `idle_sleep_minutes` AND it is at least that old (a fresh deploy
    must get its chance to receive traffic first)."""
    now = time.time()
    if now - _last_sweep["at"] < _SWEEP_EVERY_S:
        return []
    _last_sweep["at"] = now
    idle_min = config.get("idle_sleep_minutes")
    cutoff_iso = (datetime.now(timezone.utc)
                  - timedelta(minutes=idle_min)).isoformat()
    slept = []
    with engine.connect() as conn:
        deps = conn.execute(select(deployments_t)
                            .where(deployments_t.c.serving_class == "on-demand",
                                   deployments_t.c.asleep.is_(False))).mappings().all()
        for dep in deps:
            if now - (dep["created_at"] or now) < idle_min * 60:
                continue
            recent = conn.execute(
                select(func.count()).select_from(events_t)
                .where(events_t.c.model_id == dep["model_id"],
                       events_t.c.ts >= cutoff_iso)).scalar() or 0
            if recent == 0:
                slept.append(dep["id"])
    for dep_id in slept:
        try:
            sleep(dep_id, reason=f"auto — idle > {idle_min:.0f} min")
        except ValueError:
            pass
    return slept


def reclaimed() -> dict:
    """Measured thin-provisioning payoff: GPU-hours returned to the
    pool by scale-to-zero (open sleep periods count up to now)."""
    now = time.time()
    hours = 0.0
    with engine.connect() as conn:
        rows = conn.execute(select(sleep_log_t)).mappings().all()
    for r in rows:
        end = r["woke_at"] or now
        hours += max(0.0, end - r["slept_at"]) * (r["gpus"] or 1) / 3600
    return {"gpu_hours": round(hours, 1), "sleeps": len(rows),
            "asleep_now": sum(1 for r in rows if r["woke_at"] is None)}
