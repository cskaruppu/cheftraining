"""Admin operations insights — the "what needs my action?" layer.

Every block here answers an operator question from data the platform
already records; nothing is projected from assumptions without saying
so. The attention queue ranks items an admin should act on today;
runway, counterfactual savings, router drift, prompt bloat and
concentration risk are the LLM-estate signals a generic APM cannot see.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from . import clusters, deployments, tokenomics
from .catalog import MODELS, MODELS_BY_ID
from .db import engine, events_t
from .router import small_model, strong_model

_SEV_RANK = {"crit": 0, "warn": 1, "info": 2}
IDLE_AFTER_H = 48


def _iso_ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def _daily_burn(conn, team_id: str | None = None) -> float:
    """Average daily spend over the last 7 days (the honest burn basis
    for runway — 30d averages hide recent spikes)."""
    cond = [events_t.c.ts >= _iso_ago(days=7)]
    if team_id:
        cond.append(events_t.c.team_id == team_id)
    spend = conn.execute(
        select(func.sum(events_t.c.cost)).where(*cond)).scalar() or 0.0
    return spend / 7


def _attention(conn, gov: dict) -> list[dict]:
    items: list[dict] = []

    for d in deployments.list_all():
        if d["status"] == "error":
            items.append({
                "severity": "crit", "kind": "deployment",
                "title": f"Deployment '{d['name']}' failed",
                "detail": (d["message"] or "agent reported an error")[:140]
                          + f" — {d['cluster_name']}",
                "link": "/deploy"})
        elif d["backend"] == "agent" and d["status"] in ("scheduling", "pulling_weights",
                                                         "warming_up", "starting"):
            items.append({
                "severity": "info", "kind": "deployment",
                "title": f"'{d['name']}' still rolling out",
                "detail": f"{d['status'].replace('_', ' ')} on {d['cluster_name']}",
                "link": "/deploy"})

    from .agents import LATEST_AGENT_VERSION
    for c in clusters.snapshot():
        if c.get("source") != "simulated" and c.get("agent_status") != "connected":
            items.append({
                "severity": "warn", "kind": "fleet",
                "title": f"Agent on '{c['name']}' has gone stale",
                "detail": "no heartbeat — deployments there are unreachable "
                          "until it reconnects",
                "link": "/clusters"})
        elif c.get("source") != "simulated" and c.get("agent_version") \
                and c["agent_version"] != LATEST_AGENT_VERSION:
            items.append({
                "severity": "info", "kind": "fleet",
                "title": f"Agent on '{c['name']}' is outdated "
                         f"(v{c['agent_version']} → v{LATEST_AGENT_VERSION})",
                "detail": "re-apply the agent manifest to upgrade — "
                          "imagePullPolicy Always picks up the new image",
                "link": "/clusters"})

    for t in gov["teams"]:
        if not t["enabled"]:
            continue
        if t["pct"] >= 80:
            burn = _daily_burn(conn, t["id"])
            left = max(0.0, t["budget_usd"] - t["spend"])
            runway = f"~{left / burn:.0f}d runway at current burn" if burn else \
                "no spend in the last 7d"
            items.append({
                "severity": "crit" if t["pct"] >= 100 else "warn",
                "kind": "budget",
                "title": f"Team '{t['name']}' at {t['pct']:.0f}% of budget",
                "detail": runway + (" — degrade policy active" if t["pct"] >= 100 else ""),
                "link": "/tokenomics"})

    for a in gov["anomalies"]:
        items.append({
            "severity": "crit", "kind": "anomaly",
            "title": f"Usage anomaly: {a['team_id']}",
            "detail": a["detail"][:140],
            "link": "/tokenomics"})

    # idle GPU serving: a running deployment whose model served nothing
    # for IDLE_AFTER_H hours still holds vGPU slices — reclaimable
    idle_cutoff = _iso_ago(hours=IDLE_AFTER_H)
    for d in deployments.list_all():
        if d["status"] not in ("running", "ready"):
            continue
        served = conn.execute(
            select(func.count()).select_from(events_t)
            .where(events_t.c.model_id == d["model_id"],
                   events_t.c.ts >= idle_cutoff)).scalar() or 0
        if served == 0:
            items.append({
                "severity": "info", "kind": "idle",
                "title": f"'{d['name']}' idle — no traffic in {IDLE_AFTER_H}h",
                "detail": f"{d['model_name']} on {d['cluster_name']} still holds "
                          "its vGPU allocation; deleting it frees the capacity",
                "link": "/deploy"})

    return sorted(items, key=lambda i: _SEV_RANK[i["severity"]])


def _counterfactual(conn, days: int) -> dict | None:
    """What direct (unrouted) traffic would have cost under model:'route',
    using the MEASURED small-model share of actual routed traffic as the
    mix — an estimate, and labeled as one."""
    cutoff = _iso_ago(days=days)
    routed = conn.execute(
        select(func.count().label("n"),
               func.sum(events_t.c.cost).label("cost"))
        .where(events_t.c.policy.isnot(None), events_t.c.ts >= cutoff)).first()
    small_n = conn.execute(
        select(func.count()).select_from(events_t)
        .where(events_t.c.policy.isnot(None), events_t.c.ts >= cutoff,
               events_t.c.model_id.in_(
                   [m["id"] for m in MODELS if m.get("size_class") == "slm"]))
    ).scalar() or 0
    if not routed.n or routed.n < 5:
        return None  # no measured mix to base an estimate on

    direct = conn.execute(
        select(func.count().label("n"),
               func.sum(events_t.c.cost).label("cost"),
               func.sum(events_t.c.tokens_in).label("tin"),
               func.sum(events_t.c.tokens_out).label("tout"))
        .where(events_t.c.policy.is_(None), events_t.c.cached.is_(False),
               events_t.c.ts >= cutoff)).first()
    if not direct.n:
        return None

    share = small_n / routed.n
    small, strong = small_model(), strong_model()

    def price(m: dict) -> float:
        return ((direct.tin or 0) * m["input_price"]
                + (direct.tout or 0) * m["output_price"]) / 1_000_000

    est = share * price(small) + (1 - share) * price(strong)
    savings = (direct.cost or 0.0) - est
    return {
        "direct_requests": direct.n,
        "direct_cost": round(direct.cost or 0.0, 2),
        "est_routed_cost": round(est, 2),
        "est_savings": round(savings, 2),
        "small_share_pct": round(share * 100, 1),
        "basis": f"measured mix of your {routed.n} routed requests",
    }


def _router_trend(conn, days: int) -> dict:
    cutoff = _iso_ago(days=days)
    slm_ids = [m["id"] for m in MODELS if m.get("size_class") == "slm"]
    rows = conn.execute(
        select(events_t.c.day, events_t.c.model_id, func.count().label("n"))
        .where(events_t.c.policy.isnot(None), events_t.c.ts >= cutoff)
        .group_by(events_t.c.day, events_t.c.model_id)
        .order_by(events_t.c.day)).all()
    by_day: dict[str, dict] = {}
    for r in rows:
        d = by_day.setdefault(r.day, {"total": 0, "escalated": 0})
        d["total"] += r.n
        if r.model_id not in slm_ids:
            d["escalated"] += r.n
    trend = [{"day": day[5:], "escalation_pct": round(v["escalated"] / v["total"] * 100, 1),
              "requests": v["total"]}
             for day, v in sorted(by_day.items())]
    cur = round(sum(v["escalated"] for v in by_day.values())
                / max(1, sum(v["total"] for v in by_day.values())) * 100, 1)
    drift = round(trend[-1]["escalation_pct"] - trend[0]["escalation_pct"], 1) \
        if len(trend) >= 3 else None
    return {"trend": trend, "escalation_pct": cur, "drift_pct": drift}


def _prompt_bloat(conn, days: int) -> dict:
    cutoff = _iso_ago(days=days)
    rows = conn.execute(
        select(events_t.c.day, func.avg(events_t.c.tokens_in).label("avg_in"))
        .where(events_t.c.ts >= cutoff, events_t.c.cached.is_(False))
        .group_by(events_t.c.day).order_by(events_t.c.day)).all()
    trend = [{"day": r.day[5:], "avg_tokens_in": int(r.avg_in or 0)} for r in rows]
    change = None
    if len(trend) >= 4:
        head = sum(t["avg_tokens_in"] for t in trend[:3]) / 3
        tail = sum(t["avg_tokens_in"] for t in trend[-3:]) / 3
        if head:
            change = round((tail - head) / head * 100, 1)
    return {"trend": trend, "change_pct": change}


def _concentration(conn, days: int) -> dict | None:
    cutoff = _iso_ago(days=days)
    rows = conn.execute(
        select(events_t.c.model_id, func.count().label("n"))
        .where(events_t.c.ts >= cutoff).group_by(events_t.c.model_id)).all()
    total = sum(r.n for r in rows)
    if not total:
        return None
    by_provider: dict[str, int] = {}
    best_quality = 0
    for r in rows:
        m = MODELS_BY_ID.get(r.model_id)
        prov = m["provider"] if m else "other"
        by_provider[prov] = by_provider.get(prov, 0) + r.n
        if m:
            best_quality = max(best_quality, m["quality"]["chat"])
    top_prov, top_n = max(by_provider.items(), key=lambda kv: kv[1])
    alternatives = sum(
        1 for m in MODELS
        if m["provider"] != top_prov and m["quality"]["chat"] >= best_quality - 5)
    return {
        "provider": top_prov,
        "share_pct": round(top_n / total * 100, 1),
        "providers_used": len(by_provider),
        "alternatives": alternatives,
    }


def admin_summary(days: int = 14) -> dict:
    days = max(1, min(90, int(days)))
    gov = tokenomics.overview()
    with engine.connect() as conn:
        burn = _daily_burn(conn)
        total_budget = sum(t["budget_usd"] for t in gov["teams"] if t["enabled"])
        total_spend = sum(t["spend"] for t in gov["teams"] if t["enabled"])
        runway = round(max(0.0, total_budget - total_spend) / burn, 1) if burn else None
        attention = _attention(conn, gov)
        from . import alerts
        alerts.notify(attention)  # webhook on NEW critical items, deduped
        return {
            "attention": attention,
            "runway_days": runway,
            "counterfactual": _counterfactual(conn, days),
            "router_health": _router_trend(conn, days),
            "prompt_bloat": _prompt_bloat(conn, days),
            "concentration": _concentration(conn, days),
        }
