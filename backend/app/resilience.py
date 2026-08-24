"""Resilience drill — prove failover works before an outage proves it.

An admin can declare a provider "down" (a drill, persisted so it
survives restarts); the gateway then fails traffic for that provider's
models over to the best comparable model from another provider, and
every failover is receipted and ledgered. Flip it off and routing
returns to normal. Chaos-engineering for the model estate.
"""
from sqlalchemy import delete, insert, select, update

from .catalog import MODELS, MODELS_BY_ID
from .db import engine, settings_kv_t
from .recommender import similar_models

OUTAGE_KEY = "outage_provider"
WEBHOOK_KEY = "alert_webhook"


def kv_get(key: str) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(
            select(settings_kv_t.c.value).where(settings_kv_t.c.key == key)).first()
    return row.value if row else None


def kv_set(key: str, value: str | None) -> None:
    with engine.begin() as conn:
        if value is None:
            conn.execute(delete(settings_kv_t).where(settings_kv_t.c.key == key))
        elif conn.execute(select(settings_kv_t.c.key)
                          .where(settings_kv_t.c.key == key)).first():
            conn.execute(update(settings_kv_t)
                         .where(settings_kv_t.c.key == key).values(value=value))
        else:
            conn.execute(insert(settings_kv_t).values(key=key, value=value))


def outage_provider() -> str | None:
    return kv_get(OUTAGE_KEY)


def failover_for(model: dict) -> tuple[dict, dict] | None:
    """If the model's provider is in a declared outage, pick the best
    comparable model from another provider. Returns (substitute,
    failover_receipt) or None when no drill applies."""
    down = outage_provider()
    if not down or model["provider"] != down:
        return None
    candidates = [MODELS_BY_ID.get(s["id"]) for s in similar_models(model["id"])]
    candidates = [c for c in candidates if c and c["provider"] != down]
    if not candidates:
        candidates = sorted((m for m in MODELS if m["provider"] != down),
                            key=lambda m: -m["quality"]["chat"])[:1]
    if not candidates:
        return None
    sub = candidates[0]
    return sub, {
        "requested": model["id"],
        "served_by": sub["id"],
        "provider_down": down,
        "reason": f"{down} declared down (resilience drill) — "
                  f"failed over to closest comparable model",
    }
