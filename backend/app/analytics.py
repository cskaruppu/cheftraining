"""Usage analytics — persisted event store.

Events live in the database (SQLite by default, PostgreSQL via
DATABASE_URL), so history survives pod restarts and supports multiple
replicas. A deterministic 14-day seed is inserted once on first boot so
the dashboard has data immediately; live gateway/playground traffic
appends on top. Production swaps writes to a NATS -> ClickHouse
pipeline behind this same read API.
"""
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
         cached: bool, ts: datetime, team_id: str | None = None) -> dict:
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
    }


def record(model_id: str, tokens_in: int, tokens_out: int, latency_ms: int,
           cached: bool = False, ts: datetime | None = None,
           team_id: str | None = None):
    row = _row(model_id, tokens_in, tokens_out, latency_ms, cached,
               ts or datetime.now(timezone.utc), team_id)
    with engine.begin() as conn:
        conn.execute(insert(events_t).values(**row))


def seed():
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


def summary() -> dict:
    now = datetime.now(timezone.utc)
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    today = now.strftime("%Y-%m-%d")

    with engine.connect() as conn:
        total = conn.execute(select(func.count()).select_from(events_t)).scalar() or 0
        last24 = conn.execute(select(func.count()).select_from(events_t)
                              .where(events_t.c.ts >= cutoff_24h)).scalar() or 0
        spend = conn.execute(select(func.sum(events_t.c.cost))).scalar() or 0.0
        cached = conn.execute(select(func.count()).select_from(events_t)
                              .where(events_t.c.cached.is_(True))).scalar() or 0
        avg_lat = conn.execute(select(func.avg(events_t.c.latency_ms))
                               .where(events_t.c.cached.is_(False))).scalar() or 0

        daily_rows = [
            {"day": r.day, "requests": r.requests, "cost": round(r.cost or 0, 2)}
            for r in conn.execute(
                select(events_t.c.day,
                       func.count().label("requests"),
                       func.sum(events_t.c.cost).label("cost"))
                .where(events_t.c.day != today)  # partial day would mislead
                .group_by(events_t.c.day).order_by(events_t.c.day))
        ]

        model_rows = [
            {"model": r.model_name, "requests": r.requests,
             "cost": round(r.cost or 0, 2), "tokens": int(r.tokens or 0)}
            for r in conn.execute(
                select(events_t.c.model_name,
                       func.count().label("requests"),
                       func.sum(events_t.c.cost).label("cost"),
                       func.sum(events_t.c.tokens_in + events_t.c.tokens_out).label("tokens"))
                .group_by(events_t.c.model_name)
                .order_by(desc("requests")))
        ]

        recent = [
            {"ts": r.ts, "model_name": r.model_name, "tokens_in": r.tokens_in,
             "tokens_out": r.tokens_out, "latency_ms": r.latency_ms,
             "cached": r.cached, "cost": r.cost}
            for r in conn.execute(
                select(events_t).order_by(desc(events_t.c.ts)).limit(12))
        ]

    return {
        "kpis": {
            "requests_24h": last24,
            "requests_total": total,
            "spend_total": round(spend, 2),
            "avg_latency_ms": int(avg_lat),
            "cache_hit_rate": round(cached / total * 100, 1) if total else 0.0,
        },
        "daily": daily_rows,
        "by_model": model_rows,
        "recent": recent,
    }
