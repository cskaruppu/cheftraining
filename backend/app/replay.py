"""What-If Replay — re-price recorded traffic under a hypothetical.

Not a price calculator: it replays the ACTUAL token shapes the gateway
metered ("your last N requests"), so the answer is specific to this
install's workload. Two scenarios:

  {"type": "model", "model_id": ...}  every request served by one model
  {"type": "route"}                   the smart router, using the
                                      MEASURED small/strong mix of real
                                      routed traffic as the assumption

Costs are exact re-pricing of recorded shapes; latency is estimated
from telemetry when available (measured) else catalog figures; every
result says which basis it used. Requests whose recorded input exceeds
the candidate's context window are counted as would-not-fit warnings
instead of being silently priced.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from . import analytics
from .catalog import MODELS_BY_ID
from .db import engine, events_t
from .router import small_model, strong_model


def _latency_for(model: dict) -> tuple[int, str]:
    stats = analytics.model_stats().get(model["id"])
    if stats:
        return int(stats["avg_latency_ms"]), "measured"
    return int(model["latency_ms"]), "estimated"


def _price(m: dict, tin: int, tout: int) -> float:
    return (tin * m["input_price"] + tout * m["output_price"]) / 1_000_000


def replay(days: int, scenario: dict) -> dict:
    days = max(1, min(90, int(days)))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    base = (events_t.c.ts >= cutoff, events_t.c.cached.is_(False))
    with engine.connect() as conn:
        cur = conn.execute(
            select(func.count().label("n"),
                   func.sum(events_t.c.cost).label("cost"),
                   func.sum(events_t.c.tokens_in).label("tin"),
                   func.sum(events_t.c.tokens_out).label("tout"),
                   func.avg(events_t.c.latency_ms).label("lat")).where(*base)).first()
        if not cur.n:
            return {"error": "no recorded traffic in this window"}

        warnings: list[str] = []
        if scenario.get("type") == "model":
            m = MODELS_BY_ID.get(scenario.get("model_id", ""))
            if not m:
                return {"error": f"unknown model '{scenario.get('model_id')}'"}
            overflow = conn.execute(
                select(func.count()).select_from(events_t)
                .where(*base, events_t.c.tokens_in > m["context_window"])).scalar() or 0
            if overflow:
                warnings.append(
                    f"{overflow} recorded requests exceed {m['name']}'s "
                    f"{m['context_window']:,}-token context window and would fail")
            if m["quality"]["chat"] < 75:
                warnings.append(
                    f"{m['name']} scores {m['quality']['chat']} on chat quality — "
                    "below the default 75 quality floor")
            hyp_cost = _price(m, cur.tin or 0, cur.tout or 0)
            lat, lat_basis = _latency_for(m)
            hypothesis = {"label": f"all traffic on {m['name']}",
                          "models": [m["id"]]}
            basis = "exact re-pricing of recorded token shapes"

        elif scenario.get("type") == "route":
            routed_n = conn.execute(
                select(func.count()).select_from(events_t)
                .where(events_t.c.policy.isnot(None),
                       events_t.c.ts >= cutoff)).scalar() or 0
            slm_ids = [mid for mid, mm in MODELS_BY_ID.items()
                       if mm.get("size_class") == "slm"]
            routed_small = conn.execute(
                select(func.count()).select_from(events_t)
                .where(events_t.c.policy.isnot(None), events_t.c.ts >= cutoff,
                       events_t.c.model_id.in_(slm_ids))).scalar() or 0
            if routed_n < 5:
                return {"error": "route some traffic with model:\"route\" first — "
                                 "the replay uses your measured routed mix, not a guess"}
            share = routed_small / routed_n
            small, strong = small_model(), strong_model()
            hyp_cost = (share * _price(small, cur.tin or 0, cur.tout or 0)
                        + (1 - share) * _price(strong, cur.tin or 0, cur.tout or 0))
            lat_s, b1 = _latency_for(small)
            lat_g, b2 = _latency_for(strong)
            lat = int(share * lat_s + (1 - share) * lat_g)
            lat_basis = "measured" if b1 == b2 == "measured" else "estimated"
            hypothesis = {
                "label": f"smart router ({share * 100:.0f}% {small['name']}, "
                         f"{(1 - share) * 100:.0f}% {strong['name']})",
                "models": [small["id"], strong["id"]]}
            basis = (f"measured mix of your {routed_n} routed requests, "
                     "applied to recorded token shapes")
        else:
            return {"error": "scenario.type must be 'model' or 'route'"}

    actual_cost = round(cur.cost or 0.0, 2)
    hyp_cost = round(hyp_cost, 2)
    return {
        "window_days": days,
        "requests": cur.n,
        "tokens": int((cur.tin or 0) + (cur.tout or 0)),
        "actual": {"spend": actual_cost, "avg_latency_ms": int(cur.lat or 0)},
        "hypothetical": {"spend": hyp_cost, "est_latency_ms": lat,
                         "latency_basis": lat_basis, **hypothesis},
        "delta": {
            "spend_usd": round(hyp_cost - actual_cost, 2),
            "spend_pct": round((hyp_cost - actual_cost) / actual_cost * 100, 1)
            if actual_cost else None,
        },
        "warnings": warnings,
        "basis": basis,
    }
