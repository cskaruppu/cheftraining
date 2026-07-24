"""Usage analytics store.

Demo implementation: an in-memory event log seeded with 14 days of
deterministic synthetic traffic so the dashboard has data on first
boot. Live playground/gateway calls append real events on top.
Production swaps this for a NATS -> ClickHouse pipeline behind the
same read API.
"""
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .catalog import MODELS_BY_ID

_EVENTS: list[dict] = []
_SEED_MODELS = ["gpt-5-mini", "claude-sonnet-4.5", "gemini-2.5-flash",
                "llama-4-maverick", "deepseek-v3.2", "claude-haiku-4.5"]


def _cost(model_id: str, tokens_in: int, tokens_out: int) -> float:
    m = MODELS_BY_ID[model_id]
    return (tokens_in * m["input_price"] + tokens_out * m["output_price"]) / 1_000_000


def record(model_id: str, tokens_in: int, tokens_out: int, latency_ms: int,
           cached: bool = False, ts: datetime | None = None):
    ts = ts or datetime.now(timezone.utc)
    _EVENTS.append({
        "ts": ts.isoformat(),
        "day": ts.strftime("%Y-%m-%d"),
        "model_id": model_id,
        "model_name": MODELS_BY_ID[model_id]["name"],
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": latency_ms,
        "cached": cached,
        "cost": 0.0 if cached else round(_cost(model_id, tokens_in, tokens_out), 6),
    })


def seed():
    if _EVENTS:
        return
    rng = random.Random(42)
    now = datetime.now(timezone.utc)
    for day_offset in range(14, 0, -1):
        day = now - timedelta(days=day_offset)
        # weekday traffic higher than weekend; slight growth trend
        base = 260 + (14 - day_offset) * 22
        if day.weekday() >= 5:
            base = int(base * 0.45)
        for _ in range(rng.randint(int(base * 0.85), int(base * 1.15))):
            model_id = rng.choices(_SEED_MODELS, weights=[28, 22, 18, 14, 10, 8])[0]
            m = MODELS_BY_ID[model_id]
            ts = day.replace(hour=rng.randint(0, 23), minute=rng.randint(0, 59))
            record(
                model_id,
                tokens_in=rng.randint(300, 6000),
                tokens_out=rng.randint(80, 1800),
                latency_ms=int(rng.gauss(m["latency_ms"], m["latency_ms"] * 0.2)),
                cached=rng.random() < 0.18,
                ts=ts,
            )


def summary() -> dict:
    now = datetime.now(timezone.utc)
    last24 = [e for e in _EVENTS if e["ts"] >= (now - timedelta(hours=24)).isoformat()]
    total_cost = sum(e["cost"] for e in _EVENTS)
    cached = sum(1 for e in _EVENTS if e["cached"])
    lat = [e["latency_ms"] for e in _EVENTS if not e["cached"]]

    today = now.strftime("%Y-%m-%d")
    daily = defaultdict(lambda: {"requests": 0, "cost": 0.0})
    for e in _EVENTS:
        if e["day"] == today:  # partial day would render a misleading drop
            continue
        d = daily[e["day"]]
        d["requests"] += 1
        d["cost"] += e["cost"]
    daily_rows = [{"day": k, "requests": v["requests"], "cost": round(v["cost"], 2)}
                  for k, v in sorted(daily.items())]

    by_model = defaultdict(lambda: {"requests": 0, "cost": 0.0, "tokens": 0})
    for e in _EVENTS:
        b = by_model[e["model_name"]]
        b["requests"] += 1
        b["cost"] += e["cost"]
        b["tokens"] += e["tokens_in"] + e["tokens_out"]
    model_rows = sorted(
        [{"model": k, **{kk: (round(vv, 2) if kk == "cost" else vv) for kk, vv in v.items()}}
         for k, v in by_model.items()],
        key=lambda r: r["requests"], reverse=True)

    recent = sorted(_EVENTS, key=lambda e: e["ts"], reverse=True)[:12]

    return {
        "kpis": {
            "requests_24h": len(last24),
            "requests_total": len(_EVENTS),
            "spend_total": round(total_cost, 2),
            "avg_latency_ms": int(sum(lat) / len(lat)) if lat else 0,
            "cache_hit_rate": round(cached / len(_EVENTS) * 100, 1) if _EVENTS else 0.0,
        },
        "daily": daily_rows,
        "by_model": model_rows,
        "recent": recent,
    }
