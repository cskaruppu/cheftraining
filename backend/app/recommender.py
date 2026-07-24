"""Recommendation engine.

Transparent weighted multi-criteria scoring: every recommendation
returns its full score breakdown and human-readable reasons — the
product never gives a black-box answer.
"""
import math

from .catalog import MODELS, MODELS_BY_ID, USE_CASES, QUALITY_DIMS, blended_price, avg_quality

USE_CASE_DIM = {u["id"]: u["dimension"] for u in USE_CASES}


def _norm(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 1.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _passes_constraints(model: dict, c: dict) -> tuple[bool, list[str]]:
    notes = []
    if c.get("min_context") and model["context_window"] < c["min_context"]:
        return False, [f"context window {model['context_window']:,} < required {c['min_context']:,}"]
    if c.get("max_blended_price") and blended_price(model) > c["max_blended_price"]:
        return False, [f"blended price ${blended_price(model):.2f}/1M exceeds budget ${c['max_blended_price']:.2f}/1M"]
    if c.get("open_source_only") and model["source"] != "open":
        return False, ["not open source"]
    if c.get("self_hostable_only") and not model["self_hostable"]:
        return False, ["cannot be self-hosted"]
    if c.get("require_vision") and "vision" not in model["capabilities"]:
        return False, ["no vision support"]
    if c.get("require_function_calling") and "function_calling" not in model["capabilities"]:
        return False, ["no function calling"]
    if c.get("region") and c["region"] not in model["regions"]:
        return False, [f"not available in region '{c['region']}'"]
    return True, notes


def recommend(use_case: str, weights: dict, constraints: dict | None = None,
              chosen_id: str | None = None, top_n: int = 6) -> dict:
    constraints = constraints or {}
    dim = USE_CASE_DIM.get(use_case, "chat")

    w_quality = max(0, weights.get("quality", 50))
    w_cost = max(0, weights.get("cost", 30))
    w_speed = max(0, weights.get("speed", 20))
    total_w = (w_quality + w_cost + w_speed) or 1

    candidates, excluded = [], []
    for m in MODELS:
        ok, notes = _passes_constraints(m, constraints)
        if ok:
            candidates.append(m)
        else:
            excluded.append({"id": m["id"], "name": m["name"], "reason": notes[0]})

    if not candidates:
        return {"results": [], "excluded": excluded, "message": "No model satisfies all constraints — relax one and retry."}

    prices = [blended_price(m) for m in candidates]
    lat = [m["latency_ms"] for m in candidates]
    tps = [m["throughput_tps"] for m in candidates]
    log_lo, log_hi = math.log(min(prices)), math.log(max(prices))

    results = []
    for m in candidates:
        quality_score = m["quality"][dim] / 100
        # log scale: the $0.10 vs $1 difference matters as much as $1 vs $10
        cost_score = 1 - _norm(math.log(blended_price(m)), log_lo, log_hi)
        speed_score = 0.6 * (1 - _norm(m["latency_ms"], min(lat), max(lat))) \
            + 0.4 * _norm(m["throughput_tps"], min(tps), max(tps))
        total = (w_quality * quality_score + w_cost * cost_score + w_speed * speed_score) / total_w

        results.append({
            "model": m,
            "score": round(total * 100, 1),
            "breakdown": {
                "quality": round(quality_score * 100, 1),
                "cost": round(cost_score * 100, 1),
                "speed": round(speed_score * 100, 1),
            },
            "blended_price": round(blended_price(m), 2),
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:top_n]

    for rank, r in enumerate(results):
        r["reasons"] = _reasons(r, results, dim, rank)

    out = {"results": results, "excluded": excluded, "use_case": use_case, "dimension": dim,
           "weights": {"quality": w_quality, "cost": w_cost, "speed": w_speed}}

    if chosen_id and chosen_id in MODELS_BY_ID:
        out["chosen_vs_suggested"] = _compare_chosen(chosen_id, results, dim)
    return out


def _reasons(r: dict, results: list, dim: str, rank: int) -> list[str]:
    m = r["model"]
    reasons = []
    qs = sorted(results, key=lambda x: x["model"]["quality"][dim], reverse=True)
    if m["id"] == qs[0]["model"]["id"]:
        reasons.append(f"Highest {dim} quality of all matching models ({m['quality'][dim]}/100)")
    else:
        reasons.append(f"{dim.capitalize()} quality {m['quality'][dim]}/100")
    cheapest = min(results, key=lambda x: x["blended_price"])
    priciest = max(results, key=lambda x: x["blended_price"])
    if m["id"] == cheapest["model"]["id"] and priciest["blended_price"] > r["blended_price"]:
        reasons.append(f"Cheapest option — {priciest['blended_price'] / max(r['blended_price'], 0.01):.1f}x cheaper than {priciest['model']['name']}")
    else:
        reasons.append(f"Blended cost ${r['blended_price']:.2f} per 1M tokens")
    reasons.append(f"~{m['latency_ms']} ms first token, ~{m['throughput_tps']} tok/s")
    if m["self_hostable"]:
        reasons.append("Open weights — can run on your own OpenShift cluster (vLLM)")
    return reasons


def _compare_chosen(chosen_id: str, results: list, dim: str) -> dict:
    chosen = MODELS_BY_ID[chosen_id]
    suggested = results[0]["model"] if results else chosen
    cp, sp = blended_price(chosen), blended_price(suggested)
    deltas = []
    if sp < cp:
        deltas.append(f"{suggested['name']} is {cp / max(sp, 0.01):.1f}x cheaper (${sp:.2f} vs ${cp:.2f} per 1M tokens)")
    elif sp > cp:
        deltas.append(f"{suggested['name']} costs {sp / max(cp, 0.01):.1f}x more, but scores higher on your priorities")
    dq = suggested["quality"][dim] - chosen["quality"][dim]
    if dq > 0:
        deltas.append(f"+{dq} points on {dim} quality ({suggested['quality'][dim]} vs {chosen['quality'][dim]})")
    elif dq < 0:
        deltas.append(f"{dq} points on {dim} quality — an accepted trade-off given your cost/speed weights")
    dl = chosen["latency_ms"] - suggested["latency_ms"]
    if dl > 0:
        deltas.append(f"{dl} ms faster first token")
    monthly_chosen = cp * 50  # demo assumption: 50M tokens/month
    monthly_sugg = sp * 50
    deltas.append(f"Projected monthly cost at 50M tokens: ${monthly_sugg:,.0f} vs ${monthly_chosen:,.0f}")
    return {"chosen": chosen, "suggested": suggested, "deltas": deltas,
            "same": chosen["id"] == suggested["id"]}


def similar_models(model_id: str, top_n: int = 3) -> list[dict]:
    """Nearest neighbours over a normalized capability/price/quality vector."""
    base = MODELS_BY_ID.get(model_id)
    if not base:
        return []

    def vec(m):
        return (
            math.log(blended_price(m) + 0.01),
            avg_quality(m) / 100 * 4,
            math.log(m["context_window"]) / 4,
            len(m["capabilities"]) * 0.5,
            2.0 if m["self_hostable"] else 0.0,
        )

    bv = vec(base)
    scored = []
    for m in MODELS:
        if m["id"] == model_id:
            continue
        d = math.dist(bv, vec(m))
        scored.append((d, m))
    scored.sort(key=lambda t: t[0])
    return [{"id": m["id"], "name": m["name"], "provider": m["provider"],
             "distance": round(d, 3)} for d, m in scored[:top_n]]
