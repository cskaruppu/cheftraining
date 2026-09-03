"""Alert delivery — the attention queue, pushed instead of polled.

When a NEW critical item appears in the admin attention queue, POST a
Slack-compatible {"text": ...} payload to the configured webhook.
Dedupe state is persisted (settings_kv) so a standing condition alerts
once — across restarts and across replicas, which matters once the
control plane runs more than one pod. Delivery is best-effort: a down
webhook must never break the dashboard.
"""
import json

import httpx

from .resilience import WEBHOOK_KEY, kv_get, kv_set

_SENT_KEY = "alert_sent_titles"
_SENT_CAP = 200


def _sent() -> list[str]:
    try:
        return json.loads(kv_get(_SENT_KEY) or "[]")
    except ValueError:
        return []


def _mark(titles: list[str]) -> None:
    kept = (_sent() + titles)[-_SENT_CAP:]
    kv_set(_SENT_KEY, json.dumps(kept))


def new_criticals(items: list[dict]) -> list[dict]:
    seen = set(_sent())
    return [i for i in items
            if i["severity"] == "crit" and i["title"] not in seen]


def notify(items: list[dict]) -> list[str]:
    url = kv_get(WEBHOOK_KEY)
    if not url:
        return []
    fresh = new_criticals(items)
    if not fresh:
        return []
    _mark([i["title"] for i in fresh])
    text = "🔴 Modelect needs attention:\n" + "\n".join(
        f"• [{i['kind']}] {i['title']} — {i['detail']}" for i in fresh)
    try:
        httpx.post(url, json={"text": text}, timeout=4)
    except Exception:
        pass  # best-effort: alerting must never take the dashboard down
    return [i["title"] for i in fresh]
