"""Alert delivery — the attention queue, pushed instead of polled.

When a NEW critical item appears in the admin attention queue, POST a
Slack-compatible {"text": ...} payload to the configured webhook.
Deduped per item title for the process lifetime so a standing condition
alerts once, not on every dashboard refresh. Delivery is best-effort:
a down webhook must never break the dashboard.
"""
import httpx

from .resilience import WEBHOOK_KEY, kv_get

_sent: set[str] = set()


def new_criticals(items: list[dict]) -> list[dict]:
    return [i for i in items
            if i["severity"] == "crit" and i["title"] not in _sent]


def notify(items: list[dict]) -> list[str]:
    url = kv_get(WEBHOOK_KEY)
    if not url:
        return []
    fresh = new_criticals(items)
    if not fresh:
        return []
    for i in fresh:
        _sent.add(i["title"])
    text = "🔴 Modelect needs attention:\n" + "\n".join(
        f"• [{i['kind']}] {i['title']} — {i['detail']}" for i in fresh)
    try:
        httpx.post(url, json={"text": text}, timeout=4)
    except Exception:
        pass  # best-effort: alerting must never take the dashboard down
    return [i["title"] for i in fresh]
