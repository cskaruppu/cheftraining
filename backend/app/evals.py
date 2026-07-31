"""Bring-your-own-prompts evaluation runner.

Users paste their real prompts; Modelect runs them across candidate
models and scores quality / cost / latency, turning the recommendation
from spec-sheet advice into evidence.

Demo mode: runs are simulated deterministically from each model's
quality profile (clearly labeled in the API response). Production
replaces `_simulate_run` with real provider calls plus an LLM-as-judge
scoring pass — the response contract stays identical.
"""
import random
import zlib

from .catalog import MODELS_BY_ID, blended_price
from .recommender import USE_CASE_DIM

MAX_PROMPTS = 20
MAX_MODELS = 5


def _seed(*parts: str) -> int:
    return zlib.crc32("|".join(parts).encode())


def _simulate_run(model: dict, prompt: str, dim: str) -> dict:
    rng = random.Random(_seed(model["id"], prompt, dim))
    tokens_in = max(10, len(prompt.split()) * 4 // 3)
    tokens_out = rng.randint(120, 380)
    latency_ms = max(60, int(rng.gauss(model["latency_ms"], model["latency_ms"] * 0.18)))
    # judge score: model's real strength on this dimension +/- per-prompt variance
    judge = max(0.0, min(100.0, rng.gauss(model["quality"][dim], 4.5)))
    cost = (tokens_in * model["input_price"] + tokens_out * model["output_price"]) / 1_000_000
    return {
        "judge_score": round(judge, 1),
        "latency_ms": latency_ms,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost": round(cost, 6),
    }


def run_eval(prompts: list[str], model_ids: list[str], use_case: str) -> dict:
    prompts = [p.strip() for p in prompts if p.strip()][:MAX_PROMPTS]
    model_ids = model_ids[:MAX_MODELS]
    if not prompts:
        raise ValueError("provide at least one prompt")
    unknown = [i for i in model_ids if i not in MODELS_BY_ID]
    if unknown:
        raise ValueError(f"unknown model(s): {unknown}")
    if len(model_ids) < 2:
        raise ValueError("select at least two models to compare")

    dim = USE_CASE_DIM.get(use_case, "chat")
    results = []
    for mid in model_ids:
        model = MODELS_BY_ID[mid]
        runs = [_simulate_run(model, p, dim) for p in prompts]
        avg_judge = sum(r["judge_score"] for r in runs) / len(runs)
        total_cost = sum(r["cost"] for r in runs)
        results.append({
            "model_id": mid,
            "model_name": model["name"],
            "provider": model["provider"],
            "avg_judge_score": round(avg_judge, 1),
            "avg_latency_ms": int(sum(r["latency_ms"] for r in runs) / len(runs)),
            "total_cost": round(total_cost, 6),
            "cost_per_1k_prompts": round(total_cost / len(prompts) * 1000, 2),
            "blended_price": round(blended_price(model), 2),
            "per_prompt": runs,
        })

    results.sort(key=lambda r: r["avg_judge_score"], reverse=True)
    winner = results[0]
    # value pick: best judge-score-per-dollar among models within 8 points of the winner
    contenders = [r for r in results
                  if winner["avg_judge_score"] - r["avg_judge_score"] <= 8]
    value = min(contenders, key=lambda r: r["cost_per_1k_prompts"])

    verdict = (
        f"{winner['model_name']} scored highest on your prompts "
        f"({winner['avg_judge_score']}/100)."
    )
    if value["model_id"] != winner["model_id"]:
        savings = (1 - value["cost_per_1k_prompts"] / winner["cost_per_1k_prompts"]) * 100
        verdict += (
            f" {value['model_name']} is the value pick: within "
            f"{winner['avg_judge_score'] - value['avg_judge_score']:.1f} points "
            f"at {savings:.0f}% lower cost."
        )

    return {
        "mode": "simulated",  # production: "live"
        "dimension": dim,
        "prompts": prompts,
        "results": results,
        "winner_id": winner["model_id"],
        "value_pick_id": value["model_id"],
        "verdict": verdict,
    }
