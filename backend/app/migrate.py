"""Cloud-to-local migration advisor.

Customer names the commercial model they use (or plan to use) and their
monthly volume; Modelect finds open-weights equivalents that can run on
their own GPUs, with a transparent quality/cost comparison and a
12-month savings projection.

Capacity model (demo): a serving profile's throughput x 30 days at 50%
utilization bounds how many tokens one replica can serve per month;
replicas scale the flat GPU cost. Production refines this with real
utilization telemetry.
"""
import math

from . import config
from .catalog import MODELS, MODELS_BY_ID, blended_price
from .deployments import serving_profiles
from .recommender import USE_CASE_DIM

_SECONDS_PER_MONTH = 30 * 24 * 3600


def migrate_plan(cloud_model_id: str, monthly_m_tokens: float, use_case: str) -> dict:
    cloud = MODELS_BY_ID.get(cloud_model_id)
    if not cloud:
        raise ValueError("unknown model")
    if cloud["self_hostable"]:
        raise ValueError("pick the commercial API model you want to migrate away from")
    monthly_m_tokens = max(1.0, float(monthly_m_tokens))
    dim = USE_CASE_DIM.get(use_case, "chat")
    cloud_monthly = blended_price(cloud) * monthly_m_tokens

    alternatives = []
    for m in MODELS:
        if not m["self_hostable"]:
            continue
        profiles = serving_profiles(m["id"])
        profile = next((p for p in profiles if p["recommended"]), profiles[0])
        utilization = config.get("gpu_utilization_target")
        capacity_m = profile["est_throughput_tps"] * _SECONDS_PER_MONTH * utilization / 1e6
        replicas = max(1, math.ceil(monthly_m_tokens / capacity_m))
        local_monthly = profile["est_cost_month"] * replicas
        quality_delta = m["quality"][dim] - cloud["quality"][dim]
        if quality_delta < -12:
            continue  # too far below the cloud model to call an equivalent
        savings_monthly = cloud_monthly - local_monthly
        savings_pct = (savings_monthly / cloud_monthly * 100) if cloud_monthly else 0.0
        alternatives.append({
            "model_id": m["id"],
            "model_name": m["name"],
            "provider": m["provider"],
            "license": m["license"],
            "quality_delta": quality_delta,
            "quality": m["quality"][dim],
            "profile": profile,
            "replicas": replicas,
            "local_monthly": round(local_monthly, 0),
            "savings_monthly": round(savings_monthly, 0),
            "savings_pct": round(savings_pct, 1),
            "value_score": round(quality_delta + min(max(savings_pct, 0), 100) * 0.15, 2),
        })

    alternatives.sort(key=lambda a: a["value_score"], reverse=True)
    alternatives = alternatives[:3]

    projection = []
    best = alternatives[0] if alternatives else None
    for month in range(1, 13):
        row = {"month": month, "cloud": round(cloud_monthly * month, 0)}
        if best:
            row["local"] = round(best["local_monthly"] * month, 0)
        projection.append(row)

    verdict = None
    if best:
        if best["savings_monthly"] > 0:
            verdict = (
                f"Migrating from {cloud['name']} to {best['model_name']} on your own GPUs "
                f"saves ~${best['savings_monthly']:,.0f}/month "
                f"(${best['savings_monthly'] * 12:,.0f}/year) "
                f"for a {abs(best['quality_delta'])}-point "
                f"{'gain' if best['quality_delta'] >= 0 else 'trade-off'} "
                f"on {dim} quality — and your data never leaves the cluster."
            )
        else:
            verdict = (
                f"At {monthly_m_tokens:.0f}M tokens/month, {cloud['name']} is still "
                f"cost-competitive; self-hosting {best['model_name']} pays off at higher "
                f"volume or when data privacy requires it."
            )

    return {
        "cloud": {
            "model_id": cloud["id"], "model_name": cloud["name"],
            "provider": cloud["provider"],
            "blended_price": round(blended_price(cloud), 2),
            "monthly_cost": round(cloud_monthly, 0),
            "quality": cloud["quality"][dim],
        },
        "dimension": dim,
        "monthly_m_tokens": monthly_m_tokens,
        "alternatives": alternatives,
        "projection": projection,
        "verdict": verdict,
    }
