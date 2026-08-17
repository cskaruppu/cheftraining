"""Config service — business constants as admin-editable server values.

Nothing here requires a redeploy to change: capacity assumptions, cost
projections and default thresholds are data, tunable per install from
the Settings page. Every engine reads through get() at call time.
"""
from sqlalchemy import insert, select, update

from .db import config_t, engine

DEFAULTS = [
    {"key": "gpu_utilization_target", "value": 0.5,
     "label": "GPU utilization target",
     "description": "Assumed sustained utilization when sizing capacity and "
                    "migration economics (0.1–0.9). Refined by telemetry in production.",
     "min_value": 0.1, "max_value": 0.9},
    {"key": "assumed_monthly_m_tokens", "value": 50,
     "label": "Assumed monthly volume (M tokens)",
     "description": "Default monthly token volume used for cost projections "
                    "when the user hasn't specified one.",
     "min_value": 1, "max_value": 10000},
    {"key": "default_quality_floor", "value": 80,
     "label": "Default quality floor",
     "description": "Starting quality bar for SLM-first ('smallest capable') "
                    "recommendations.",
     "min_value": 60, "max_value": 95},
    {"key": "cache_ttl_hours", "value": 6,
     "label": "Registry sync TTL (hours)",
     "description": "How long registry connector results are cached before "
                    "a re-sync.",
     "min_value": 1, "max_value": 48},
]


def _seed():
    with engine.begin() as conn:
        existing = {r.key for r in conn.execute(select(config_t.c.key))}
        for d in DEFAULTS:
            if d["key"] not in existing:
                conn.execute(insert(config_t).values(**d))


_seed()


def get(key: str) -> float:
    with engine.connect() as conn:
        row = conn.execute(
            select(config_t.c.value).where(config_t.c.key == key)).first()
    if row is None:
        default = next((d for d in DEFAULTS if d["key"] == key), None)
        return default["value"] if default else 0.0
    return row.value


def all_entries() -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(select(config_t)).mappings().all()
    return [dict(r) for r in rows]


def set_value(key: str, value: float) -> dict:
    entry = next((d for d in DEFAULTS if d["key"] == key), None)
    if entry is None:
        raise ValueError(f"unknown config key '{key}'")
    if not (entry["min_value"] <= value <= entry["max_value"]):
        raise ValueError(
            f"'{key}' must be between {entry['min_value']} and {entry['max_value']}")
    with engine.begin() as conn:
        conn.execute(update(config_t).where(config_t.c.key == key)
                     .values(value=value))
    return {"key": key, "value": value}
