"""Model Decision Ledger — the governance record competitors don't keep.

Every routing choice, guardrail enforcement, failover and placement the
platform makes is written here with its full receipt: what was decided,
for whom, and WHY. Gateways log requests; Modelect logs justifications.
That is the record-keeping AI-governance frameworks (e.g. the EU AI
Act's traceability requirements) ask for — exportable as CSV/JSON for
auditors. Prompt contents are never stored, only decisions about them.
"""
import csv
import io
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, insert, select

from .db import engine, ledger_t

KINDS = ("routing", "enforcement", "failover", "placement")


def record(kind: str, model_id: str, policy: str | None = None,
           team_id: str | None = None, summary: str = "",
           receipt: dict | None = None) -> None:
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(insert(ledger_t).values(
            ts=now.isoformat(), day=now.strftime("%Y-%m-%d"),
            kind=kind, policy=policy, model_id=model_id, team_id=team_id,
            summary=summary[:400],
            receipt_json=json.dumps(receipt or {}, default=str)))


def entries(days: int = 14, kind: str | None = None,
            policy: str | None = None, limit: int = 200) -> dict:
    days = max(1, min(90, int(days)))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cond = [ledger_t.c.ts >= cutoff]
    if kind:
        cond.append(ledger_t.c.kind == kind)
    if policy:
        cond.append(ledger_t.c.policy == policy)
    with engine.connect() as conn:
        total = conn.execute(
            select(func.count()).select_from(ledger_t).where(*cond)).scalar() or 0
        rows = conn.execute(
            select(ledger_t).where(*cond)
            .order_by(desc(ledger_t.c.ts)).limit(max(1, min(500, limit)))).mappings().all()
    return {
        "total": total,
        "window_days": days,
        "entries": [{
            "id": r["id"], "ts": r["ts"], "kind": r["kind"],
            "policy": r["policy"], "model_id": r["model_id"],
            "team_id": r["team_id"], "summary": r["summary"],
            "receipt": json.loads(r["receipt_json"] or "{}"),
        } for r in rows],
    }


def export_csv(days: int = 30) -> str:
    data = entries(days=days, limit=500)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ts", "kind", "policy", "model_id", "team_id",
                "summary", "receipt_json"])
    for e in data["entries"]:
        w.writerow([e["ts"], e["kind"], e["policy"] or "", e["model_id"],
                    e["team_id"] or "", e["summary"],
                    json.dumps(e["receipt"], default=str)])
    return buf.getvalue()
