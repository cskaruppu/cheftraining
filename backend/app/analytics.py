"""Usage analytics — persisted event store.

Events live in the database (SQLite by default, PostgreSQL via
DATABASE_URL), so history survives pod restarts and supports multiple
replicas. A deterministic 14-day seed is inserted once on first boot so
the dashboard has data immediately; live gateway/playground traffic
appends on top. Production swaps writes to a NATS -> ClickHouse
pipeline behind this same read API.
"""
import os
import random
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, insert, select

from .catalog import MODELS_BY_ID
from .db import engine, events_t

# Telemetry a model needs before "measured" replaces "estimated".
MIN_SAMPLES = 20
_STATS_TTL = 60
_stats_cache: dict = {"at": 0.0, "data": {}}

_SEED_MODELS = ["gpt-5-mini", "claude-sonnet-4.5", "gemini-2.5-flash",
                "llama-4-maverick", "deepseek-v3.2", "claude-haiku-4.5"]


def _cost(model_id: str, tokens_in: int, tokens_out: int) -> float:
    m = MODELS_BY_ID[model_id]
    return (tokens_in * m["input_price"] + tokens_out * m["output_price"]) / 1_000_000


def _row(model_id: str, tokens_in: int, tokens_out: int, latency_ms: int,
         cached: bool, ts: datetime, team_id: str | None = None,
         policy: str | None = None, backend: str | None = None,
         agent_id: str | None = None, task_id: str | None = None) -> dict:
    return {
        "ts": ts.isoformat(),
        "day": ts.strftime("%Y-%m-%d"),
        "model_id": model_id,
        "model_name": MODELS_BY_ID[model_id]["name"],
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": latency_ms,
        "cached": cached,
        "cost": 0.0 if cached else round(_cost(model_id, tokens_in, tokens_out), 6),
        "team_id": team_id,
        "policy": policy,
        "backend": backend,
        "agent_id": agent_id,
        "task_id": task_id,
    }


def record(model_id: str, tokens_in: int, tokens_out: int, latency_ms: int,
           cached: bool = False, ts: datetime | None = None,
           team_id: str | None = None, policy: str | None = None,
           backend: str | None = None, agent_id: str | None = None,
           task_id: str | None = None):
    row = _row(model_id, tokens_in, tokens_out, latency_ms, cached,
               ts or datetime.now(timezone.utc), team_id, policy, backend,
               agent_id, task_id)
    with engine.begin() as conn:
        conn.execute(insert(events_t).values(**row))


def demo_seed_enabled() -> bool:
    """DEMO_SEED=0 runs the platform with real traffic only — every
    number starts at zero and grows from actual gateway usage."""
    return os.environ.get("DEMO_SEED", "1") != "0"


def seed():
    from .db import IS_GATEWAY_ROLE
    if IS_GATEWAY_ROLE or not demo_seed_enabled():
        return
    with engine.connect() as conn:
        count = conn.execute(select(func.count()).select_from(events_t)).scalar()
    if count:
        return
    rng = random.Random(42)
    now = datetime.now(timezone.utc)
    rows = []
    for day_offset in range(14, 0, -1):
        day = now - timedelta(days=day_offset)
        base = 260 + (14 - day_offset) * 22
        if day.weekday() >= 5:
            base = int(base * 0.45)
        for _ in range(rng.randint(int(base * 0.85), int(base * 1.15))):
            model_id = rng.choices(_SEED_MODELS, weights=[28, 22, 18, 14, 10, 8])[0]
            m = MODELS_BY_ID[model_id]
            ts = day.replace(hour=rng.randint(0, 23), minute=rng.randint(0, 59))
            rows.append(_row(
                model_id,
                tokens_in=rng.randint(300, 6000),
                tokens_out=rng.randint(80, 1800),
                latency_ms=int(rng.gauss(m["latency_ms"], m["latency_ms"] * 0.2)),
                cached=rng.random() < 0.18,
                ts=ts,
            ))
    with engine.begin() as conn:
        conn.execute(insert(events_t), rows)


def model_stats() -> dict:
    """Observed per-model telemetry from real gateway traffic.

    This is the Phase-3 feedback loop: the catalog's latency values and
    the recommender's speed scoring switch from spec-sheet estimates to
    measured numbers once a model has MIN_SAMPLES real requests.
    Cached briefly to keep catalog reads cheap.
    """
    if time.time() - _stats_cache["at"] < _STATS_TTL:
        return _stats_cache["data"]
    with engine.connect() as conn:
        rows = conn.execute(
            select(events_t.c.model_id,
                   func.count().label("samples"),
                   func.avg(events_t.c.latency_ms).label("avg_latency_ms"),
                   func.avg(events_t.c.cost).label("avg_cost"))
            .where(events_t.c.cached.is_(False))
            .group_by(events_t.c.model_id))
        data = {
            r.model_id: {
                "samples": r.samples,
                "avg_latency_ms": int(r.avg_latency_ms or 0),
                "avg_cost": round(r.avg_cost or 0, 6),
            }
            for r in rows if r.samples >= MIN_SAMPLES
        }
    _stats_cache.update(at=time.time(), data=data)
    return data


def router_summary(days: int = 14) -> dict:
    """Measured (not promised) routing economics: for every request
    served under a routing policy, compare its actual cost against what
    the strongest catalog model would have charged for the same token
    shape. Savings are computed at read time from recorded traffic."""
    from .catalog import MODELS
    days = max(1, min(90, int(days)))
    strong = max(MODELS, key=lambda m: m["quality"]["chat"])
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    with engine.connect() as conn:
        rows = conn.execute(
            select(events_t.c.model_id, events_t.c.tokens_in,
                   events_t.c.tokens_out, events_t.c.cost, events_t.c.policy)
            .where(events_t.c.policy.isnot(None), events_t.c.day >= since)
        ).all()

    policies: dict[str, dict] = {}
    for r in rows:
        p = policies.setdefault(r.policy, {
            "requests": 0, "small_requests": 0,
            "actual_usd": 0.0, "strong_usd": 0.0})
        m = MODELS_BY_ID.get(r.model_id)
        p["requests"] += 1
        if m and m.get("size_class") == "slm":
            p["small_requests"] += 1
        p["actual_usd"] += r.cost or 0.0
        p["strong_usd"] += (r.tokens_in * strong["input_price"]
                            + r.tokens_out * strong["output_price"]) / 1_000_000
    for p in policies.values():
        p["small_share_pct"] = round(p["small_requests"] / p["requests"] * 100, 1) \
            if p["requests"] else 0.0
        p["saved_usd"] = round(max(0.0, p["strong_usd"] - p["actual_usd"]), 4)
        p["actual_usd"] = round(p["actual_usd"], 4)
        p["strong_usd"] = round(p["strong_usd"], 4)
    return {"window_days": days, "vs_model": strong["id"],
            "provenance": "measured", "policies": policies}


def _percentile(sorted_vals: list, p: float) -> int:
    if not sorted_vals:
        return 0
    k = min(len(sorted_vals) - 1, int(round(p / 100 * (len(sorted_vals) - 1))))
    return int(sorted_vals[k])


def _delta_pct(cur: float, prev: float) -> float | None:
    """Period-over-period change; None when the previous window is empty
    (a delta against nothing would mislead)."""
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def summary(days: int = 14) -> dict:
    days = max(1, min(90, int(days)))
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()
    prev_cutoff = (now - timedelta(days=2 * days)).isoformat()
    today = now.strftime("%Y-%m-%d")

    def window_stats(conn, lo: str, hi: str) -> dict:
        in_win = (events_t.c.ts >= lo, events_t.c.ts < hi)
        row = conn.execute(
            select(func.count().label("requests"),
                   func.sum(events_t.c.cost).label("spend"),
                   func.sum(events_t.c.tokens_in).label("tin"),
                   func.sum(events_t.c.tokens_out).label("tout"))
            .where(*in_win)).first()
        cached = conn.execute(select(func.count()).select_from(events_t)
                              .where(*in_win, events_t.c.cached.is_(True))).scalar() or 0
        lats = sorted(r[0] for r in conn.execute(
            select(events_t.c.latency_ms)
            .where(*in_win, events_t.c.cached.is_(False))))
        return {
            "requests": row.requests or 0,
            "spend": row.spend or 0.0,
            "tokens_in": int(row.tin or 0),
            "tokens_out": int(row.tout or 0),
            "cached": cached,
            "p50": _percentile(lats, 50),
            "p95": _percentile(lats, 95),
        }

    with engine.connect() as conn:
        total = conn.execute(select(func.count()).select_from(events_t)).scalar() or 0
        cur = window_stats(conn, cutoff, now.isoformat())
        prev = window_stats(conn, prev_cutoff, cutoff)

        # guardrail BLOCK/KILLSWITCH count as failed requests: they hit the
        # gateway and were rejected — that IS the error rate of the estate
        from .db import enforcement_t
        blocks = conn.execute(
            select(func.count()).select_from(enforcement_t)
            .where(enforcement_t.c.ts >= cutoff,
                   enforcement_t.c.action.in_(["BLOCK", "KILLSWITCH"]))).scalar() or 0

        # traffic series: hourly buckets on the 24h view, complete days otherwise
        if days == 1:
            series_map: dict[str, dict] = {}
            for r in conn.execute(
                    select(events_t.c.ts, events_t.c.cost,
                           events_t.c.tokens_in, events_t.c.tokens_out)
                    .where(events_t.c.ts >= cutoff).order_by(events_t.c.ts)):
                label = r.ts[11:13] + ":00"
                b = series_map.setdefault(label, {"label": label, "requests": 0,
                                                  "cost": 0.0, "tokens": 0})
                b["requests"] += 1
                b["cost"] += r.cost or 0.0
                b["tokens"] += (r.tokens_in or 0) + (r.tokens_out or 0)
            series = [{**b, "cost": round(b["cost"], 4)} for b in series_map.values()]
            granularity = "hour"
        else:
            start_day = (now - timedelta(days=days)).strftime("%Y-%m-%d")
            series = [
                {"label": r.day[5:], "requests": r.requests,
                 "cost": round(r.cost or 0, 2), "tokens": int(r.tokens or 0)}
                for r in conn.execute(
                    select(events_t.c.day,
                           func.count().label("requests"),
                           func.sum(events_t.c.cost).label("cost"),
                           func.sum(events_t.c.tokens_in + events_t.c.tokens_out).label("tokens"))
                    .where(events_t.c.day >= start_day,
                           events_t.c.day != today)  # partial day would mislead
                    .group_by(events_t.c.day).order_by(events_t.c.day))
            ]
            granularity = "day"

        model_rows = [
            {"model_id": r.model_id, "model": r.model_name, "requests": r.requests,
             "cost": round(r.cost or 0, 2), "tokens": int(r.tokens or 0)}
            for r in conn.execute(
                select(events_t.c.model_id, events_t.c.model_name,
                       func.count().label("requests"),
                       func.sum(events_t.c.cost).label("cost"),
                       func.sum(events_t.c.tokens_in + events_t.c.tokens_out).label("tokens"))
                .where(events_t.c.ts >= cutoff)
                .group_by(events_t.c.model_id, events_t.c.model_name)
                .order_by(desc("requests")))
        ]

        recent = [
            {"ts": r.ts, "model_name": r.model_name, "tokens_in": r.tokens_in,
             "tokens_out": r.tokens_out, "latency_ms": r.latency_ms,
             "cached": r.cached, "cost": r.cost, "policy": r.policy,
             "backend": r.backend, "team_id": r.team_id}
            for r in conn.execute(
                select(events_t).order_by(desc(events_t.c.ts)).limit(12))
        ]

    # provider + hybrid estate splits, derived from the window's model rows
    providers: dict[str, dict] = {}
    hybrid = {"api": {"tokens": 0, "cost": 0.0}, "private": {"tokens": 0, "cost": 0.0}}
    for m in model_rows:
        cat = MODELS_BY_ID.get(m["model_id"])
        prov = cat["provider"] if cat else "other"
        p = providers.setdefault(prov, {"provider": prov, "requests": 0, "cost": 0.0})
        p["requests"] += m["requests"]
        p["cost"] = round(p["cost"] + m["cost"], 2)
        side = "private" if cat and cat.get("self_hostable") else "api"
        hybrid[side]["tokens"] += m["tokens"]
        hybrid[side]["cost"] = round(hybrid[side]["cost"] + m["cost"], 2)
    by_provider = sorted(providers.values(), key=lambda p: -p["cost"])

    completed = cur["requests"]
    attempted = completed + blocks
    return {
        "window_days": days,
        "granularity": granularity,
        "kpis": {
            "requests": completed,
            "requests_total": total,
            "spend": round(cur["spend"], 2),
            "p50_ms": cur["p50"],
            "p95_ms": cur["p95"],
            "success_rate": round(completed / attempted * 100, 1) if attempted else 100.0,
            "blocks": blocks,
            "cache_hit_rate": round(cur["cached"] / completed * 100, 1) if completed else 0.0,
            "tokens_in": cur["tokens_in"],
            "tokens_out": cur["tokens_out"],
            # deltas need a real baseline: a sparse previous window (fewer
            # than 20 requests, or under 5% of the current window's volume)
            # would produce a huge, misleading percentage — omit instead
            "deltas": {
                "requests_pct": _delta_pct(completed, prev["requests"]),
                "spend_pct": _delta_pct(cur["spend"], prev["spend"]),
                "p95_pct": _delta_pct(cur["p95"], prev["p95"]),
            } if prev["requests"] >= max(20, completed * 0.05) else
            {"requests_pct": None, "spend_pct": None, "p95_pct": None},
        },
        "series": series,
        "by_model": model_rows,
        "model_count": len(model_rows),
        "by_provider": by_provider,
        "hybrid": hybrid,
        "recent": recent,
    }
