"""Recommendation engine.

Transparent weighted multi-criteria scoring: every recommendation
returns its full score breakdown and human-readable reasons — the
product never gives a black-box answer.
"""
import math

from . import analytics
from .catalog import (MODELS, MODELS_BY_ID, USE_CASES, QUALITY_DIMS,
                      blended_price, avg_quality, size_rank)


def _effective_latency(m: dict, stats: dict) -> tuple[int, bool]:
    """Measured latency from gateway telemetry when available (Phase 3)."""
    t = stats.get(m["id"])
    if t:
        return t["avg_latency_ms"], True
    return m["latency_ms"], False

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
              chosen_id: str | None = None, top_n: int = 6,
              mode: str = "best", quality_floor: int = 80) -> dict:
    """mode='best': weighted quality/cost/speed ranking (default).
    mode='smallest_capable': SLM-first — rank the smallest models that
    clear the quality floor on the use-case dimension."""
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

    stats = analytics.model_stats()
    prices = [blended_price(m) for m in candidates]
    lat = [_effective_latency(m, stats)[0] for m in candidates]
    tps = [m["throughput_tps"] for m in candidates]
    log_lo, log_hi = math.log(min(prices)), math.log(max(prices))

    results = []
    for m in candidates:
        quality_score = m["quality"][dim] / 100
        # log scale: the $0.10 vs $1 difference matters as much as $1 vs $10
        cost_score = 1 - _norm(math.log(blended_price(m)), log_lo, log_hi)
        eff_lat, measured = _effective_latency(m, stats)
        speed_score = 0.6 * (1 - _norm(eff_lat, min(lat), max(lat))) \
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
            "latency_ms": eff_lat,
            "latency_measured": measured,
        })

    if mode == "smallest_capable":
        capable = [r for r in results if r["model"]["quality"][dim] >= quality_floor]
        for r in results:
            if r not in capable:
                excluded.append({"id": r["model"]["id"], "name": r["model"]["name"],
                                 "reason": f"{dim} quality {r['model']['quality'][dim]} "
                                           f"below the {quality_floor} floor"})
        capable.sort(key=lambda r: size_rank(r["model"]))
        results = capable[:top_n]
        for r in results:
            m = r["model"]
            size = f"{m['params_b']}B params" if m["params_b"] else f"{m['size_class']} class (params undisclosed)"
            r["reasons"] = [
                f"Smallest capable option: {size}, clears the {quality_floor} {dim}-quality floor "
                f"({m['quality'][dim]}/100)",
                f"Blended cost ${r['blended_price']:.2f} per 1M tokens",
                f"~{m['latency_ms']} ms first token, ~{m['throughput_tps']} tok/s",
            ]
            if m["self_hostable"]:
                r["reasons"].append(
                    "Open weights — deployable on a single small GPU (see Deploy)"
                    if m["size_class"] == "slm"
                    else "Open weights — self-hostable on your cluster (see Deploy)")
    else:
        results.sort(key=lambda r: r["score"], reverse=True)
        results = results[:top_n]
        for rank, r in enumerate(results):
            r["reasons"] = _reasons(r, results, dim, rank)

    out = {"results": results, "excluded": excluded, "use_case": use_case, "dimension": dim,
           "mode": mode, "quality_floor": quality_floor if mode == "smallest_capable" else None,
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
    lat_src = "measured on your gateway" if r.get("latency_measured") else "est."
    reasons.append(f"~{r.get('latency_ms', m['latency_ms'])} ms first token ({lat_src}), "
                   f"~{m['throughput_tps']} tok/s")
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
    from . import config  # late import to avoid a cycle at module load
    volume = config.get("assumed_monthly_m_tokens")
    monthly_chosen = cp * volume
    monthly_sugg = sp * volume
    deltas.append(f"Projected monthly cost at {volume:.0f}M tokens: "
                  f"${monthly_sugg:,.0f} vs ${monthly_chosen:,.0f}")
    return {"chosen": chosen, "suggested": suggested, "deltas": deltas,
            "same": chosen["id"] == suggested["id"]}


def routing_receipt(model: dict, tokens_in: int, tokens_out: int,
                    dim: str = "chat", routed: bool = False) -> dict:
    """Per-request transparency: what this call cost and what the
    cheapest comparable model would have cost instead."""
    def call_cost(m: dict) -> float:
        return (tokens_in * m["input_price"] + tokens_out * m["output_price"]) / 1_000_000

    cost = call_cost(model)
    comparable = [m for m in MODELS
                  if m["id"] != model["id"]
                  and m["quality"][dim] >= model["quality"][dim] - 5]
    receipt = {
        "model_id": model["id"],
        "reason": ("auto-routed: best weighted quality/cost/speed for this profile"
                   if routed else "explicitly requested by caller"),
        "dimension": dim,
        "cost_usd": round(cost, 6),
    }
    if comparable:
        alt = min(comparable, key=call_cost)
        alt_cost = call_cost(alt)
        if alt_cost < cost:
            receipt["cheapest_comparable"] = {
                "model_id": alt["id"],
                "model_name": alt["name"],
                "cost_usd": round(alt_cost, 6),
                "savings_pct": round((1 - alt_cost / cost) * 100, 1) if cost else 0.0,
                "quality_delta": alt["quality"][dim] - model["quality"][dim],
            }
    return receipt


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
