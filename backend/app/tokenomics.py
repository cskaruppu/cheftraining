"""Tokenomics — token metering, attribution, budgets and enforcement.

The Govern pillar's control panel: every token attributed to a team via
its API key; rolling 30-day budgets enforced AT THE GATEWAY (alert at
80%, and at 100% the "degrade" policy reroutes to the smallest capable
model instead of causing an outage); hybrid statement pricing API and
private GPU-hosted models side by side; anomaly detection over the
same telemetry.

Demo teams are seeded once, and historical events are backfilled with
attribution so the cockpit is alive on first boot. Budgets are seeded
relative to observed spend so each enforcement state is demonstrable;
admins change them like any other value.
"""
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select, update

from . import analytics
from .catalog import MODELS_BY_ID
from .db import ai_agents_t, engine, enforcement_t, events_t, teams_t

CARBON_G_PER_1K_TOKENS = 0.2  # demo factor; production: per-GPU energy data

# model -> team mapping used for seeding/backfilling demo attribution
_MODEL_TEAM = {
    "claude-haiku-4.5": "support-bot",
    "claude-sonnet-4.5": "support-bot",
    "gemini-2.5-flash": "doc-pipeline",
    "llama-4-maverick": "doc-pipeline",
    "gpt-5-mini": "research-agents",
    "deepseek-v3.2": "research-agents",
}

# (id, name, policy, budget multiple of observed spend, extra guardrails)
_TEAM_SEED = [
    ("support-bot", "support-bot", "alert", 1.25, {}),           # ~80% -> warn
    ("doc-pipeline", "doc-pipeline", "degrade", 4.0, {}),        # ~25% -> ok
    ("research-agents", "research-agents", "degrade", 0.95,      # >100% -> degraded
     {"rate_limit_tpm": 120_000}),
    ("intern-sandbox", "intern-sandbox", "degrade", None,        # fixed $50
     {"allowed_tiers": "slm,mid", "max_input_tokens": 8000}),
]


def _now():
    return datetime.now(timezone.utc)


def _cutoff_30d() -> str:
    return (_now() - timedelta(days=30)).isoformat()


# fixed budgets for real-traffic mode (DEMO_SEED=0) — no spend history
_REAL_MODE_BUDGETS = {"support-bot": 500.0, "doc-pipeline": 400.0,
                      "research-agents": 500.0, "intern-sandbox": 50.0}


def seed():
    from .db import IS_GATEWAY_ROLE
    if IS_GATEWAY_ROLE:
        return
    """Idempotent: create teams; in demo mode also backfill attribution
    and seed one anomaly burst + its enforcement log entry."""
    analytics.seed()  # base traffic must exist before attribution/backfill
    demo = analytics.demo_seed_enabled()
    with engine.begin() as conn:
        if conn.execute(select(func.count()).select_from(teams_t)).scalar():
            return
        if not demo:
            for team_id, name, policy, _mult, extra in _TEAM_SEED:
                conn.execute(insert(teams_t).values(
                    id=team_id, name=name, policy=policy,
                    budget_usd=_REAL_MODE_BUDGETS[team_id],
                    api_key=f"tk-{secrets.token_hex(12)}", enabled=True, **extra))
            return
        # 1. backfill team attribution onto existing events by model
        for model_id, team_id in _MODEL_TEAM.items():
            conn.execute(update(events_t)
                         .where(events_t.c.model_id == model_id,
                                events_t.c.team_id.is_(None))
                         .values(team_id=team_id))
        # 2. anomaly burst: research-agents looped ~6h ago (big outputs)
        burst_ts = _now() - timedelta(hours=6)
        m = MODELS_BY_ID["gpt-5-mini"]
        rows = []
        for i in range(40):
            ts = burst_ts + timedelta(seconds=40 * i)
            tokens_in, tokens_out = 900, 12000
            rows.append({
                "ts": ts.isoformat(), "day": ts.strftime("%Y-%m-%d"),
                "model_id": "gpt-5-mini",
                "model_name": "GPT-5 mini",
                "tokens_in": tokens_in, "tokens_out": tokens_out,
                "latency_ms": 2100, "cached": False,
                "cost": round((tokens_in * m["input_price"]
                               + tokens_out * m["output_price"]) / 1e6, 6),
                "team_id": "research-agents",
                "agent_id": "scraper-agent",  # the agent that looped
            })
        conn.execute(insert(events_t), rows)
        # 3. teams with budgets scaled to observed 30d spend
        spend = {r.team_id: r.cost or 0.0 for r in conn.execute(
            select(events_t.c.team_id, func.sum(events_t.c.cost).label("cost"))
            .where(events_t.c.team_id.isnot(None))
            .group_by(events_t.c.team_id))}
        for team_id, name, policy, mult, extra in _TEAM_SEED:
            budget = 50.0 if mult is None else round(max(1.0, spend.get(team_id, 0) * mult), 2)
            conn.execute(insert(teams_t).values(
                id=team_id, name=name, policy=policy, budget_usd=budget,
                api_key=f"tk-{secrets.token_hex(12)}", enabled=True, **extra))
        # 3b. demo AI agents under the teams, plus attribution for the
        # scraper burst so the agentic spend tree has a story to tell
        import time as _time
        for aid, a_team, a_name in (
                ("planner-agent", "research-agents", "Planner Agent"),
                ("scraper-agent", "research-agents", "Scraper Agent"),
                ("triage-agent", "support-bot", "Triage Agent")):
            conn.execute(insert(ai_agents_t).values(
                id=aid, team_id=a_team, name=a_name,
                api_key=f"ak-{secrets.token_hex(12)}", created_at=_time.time()))

        # 4. the burst tripped the budget: log the degrade decision
        conn.execute(insert(enforcement_t).values(
            ts=(burst_ts + timedelta(minutes=3)).isoformat(),
            team_id="research-agents", action="DEGRADE",
            detail="budget hit 100% during output burst — policy 'degrade': "
                   "subsequent requests routed to phi-4 (no outage)"))


def team_by_id(team_id: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(select(teams_t)
                           .where(teams_t.c.id == team_id)).mappings().first()
    return dict(row) if row else None


def is_anomalous(team_id: str) -> bool:
    return any(a["team_id"] == team_id for a in anomalies())


def resolve_team(bearer_key: str | None) -> dict | None:
    if not bearer_key:
        return None
    with engine.connect() as conn:
        row = conn.execute(select(teams_t)
                           .where(teams_t.c.api_key == bearer_key)).mappings().first()
    return dict(row) if row else None


def team_spend_30d(team_id: str) -> float:
    with engine.connect() as conn:
        return conn.execute(
            select(func.sum(events_t.c.cost))
            .where(events_t.c.team_id == team_id,
                   events_t.c.ts >= _cutoff_30d())).scalar() or 0.0


def budget_status(team: dict) -> dict:
    spend = team_spend_30d(team["id"])
    pct = (spend / team["budget_usd"] * 100) if team["budget_usd"] else 0.0
    if pct >= 100:
        state = "degraded" if team["policy"] == "degrade" else "over"
    elif pct >= 70:
        state = "warn"
    else:
        state = "ok"
    return {"spend": round(spend, 4), "pct": round(pct, 1), "state": state}


def tokens_last_minute(team_id: str) -> int:
    cutoff = (_now() - timedelta(seconds=60)).isoformat()
    with engine.connect() as conn:
        return conn.execute(
            select(func.sum(events_t.c.tokens_in + events_t.c.tokens_out))
            .where(events_t.c.team_id == team_id,
                   events_t.c.ts >= cutoff)).scalar() or 0


def precheck(team: dict, model: dict, est_input_tokens: int) -> dict | None:
    """Deterministic guardrails evaluated before serving a request.
    Returns {code, reason} on violation, None when clear. Order:
    kill switch -> tier allowlist -> input shape -> token rate."""
    if not team.get("enabled", True):
        return {"code": 403, "reason": f"team '{team['name']}' is paused (kill switch)"}
    tiers = (team.get("allowed_tiers") or "").strip()
    if tiers and model["size_class"] not in tiers.split(","):
        return {"code": 403,
                "reason": f"model tier '{model['size_class']}' not allowed for "
                          f"team '{team['name']}' (allowed: {tiers})"}
    max_in = team.get("max_input_tokens")
    if max_in and est_input_tokens > max_in:
        return {"code": 400,
                "reason": f"input ~{est_input_tokens} tokens exceeds the team's "
                          f"max_input_tokens ({max_in})"}
    tpm = team.get("rate_limit_tpm")
    if tpm and tokens_last_minute(team["id"]) > tpm:
        return {"code": 429,
                "reason": f"token-rate limit reached ({tpm:,} tokens/min) — retry shortly"}
    return None


def update_team(team_id: str, fields: dict) -> dict:
    allowed = {"enabled", "budget_usd", "policy", "rate_limit_tpm",
               "max_input_tokens", "max_output_tokens", "allowed_tiers",
               "loop_policy", "max_delegation_depth"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"unknown field(s): {sorted(bad)}")
    if "policy" in fields and fields["policy"] not in ("alert", "degrade"):
        raise ValueError("policy must be 'alert' or 'degrade'")
    if "loop_policy" in fields and fields["loop_policy"] not in (None, "off", "degrade"):
        raise ValueError("loop_policy must be 'off' or 'degrade'")
    with engine.begin() as conn:
        row = conn.execute(select(teams_t).where(teams_t.c.id == team_id)).mappings().first()
        if row is None:
            raise ValueError("unknown team")
        conn.execute(update(teams_t).where(teams_t.c.id == team_id).values(**fields))
        merged = {**dict(row), **fields}
    if "enabled" in fields:
        log_enforcement(team_id, "KILLSWITCH",
                        "key paused by admin" if not fields["enabled"] else "key re-enabled")
    return merged


def log_enforcement(team_id: str, action: str, detail: str):
    from . import metrics
    metrics.inc("modelect_enforcement_total", {"action": action})
    with engine.begin() as conn:
        conn.execute(insert(enforcement_t).values(
            ts=_now().isoformat(), team_id=team_id, action=action, detail=detail))


def anomalies() -> list[dict]:
    """Recent output-token behavior vs each team's own baseline."""
    cutoff_24h = (_now() - timedelta(hours=24)).isoformat()
    out = []
    with engine.connect() as conn:
        recent = {r.team_id: (r.avg_out or 0, r.n) for r in conn.execute(
            select(events_t.c.team_id,
                   func.avg(events_t.c.tokens_out).label("avg_out"),
                   func.count().label("n"))
            .where(events_t.c.team_id.isnot(None), events_t.c.ts >= cutoff_24h)
            .group_by(events_t.c.team_id))}
        baseline = {r.team_id: r.avg_out or 0 for r in conn.execute(
            select(events_t.c.team_id,
                   func.avg(events_t.c.tokens_out).label("avg_out"))
            .where(events_t.c.team_id.isnot(None), events_t.c.ts < cutoff_24h)
            .group_by(events_t.c.team_id))}
    for team_id, (avg_out, n) in recent.items():
        base = baseline.get(team_id, 0)
        if n >= 5 and base > 0 and avg_out >= 3 * base:
            out.append({
                "team_id": team_id,
                "ratio": round(avg_out / base, 1),
                "detail": f"output tokens {avg_out / base:.0f}x baseline over the "
                          f"last 24h ({n} requests) — possible agent loop or "
                          f"exfiltration; review the key's recent traffic",
            })
    return out


def overview() -> dict:
    cutoff = _cutoff_30d()
    with engine.connect() as conn:
        teams = [dict(r) for r in conn.execute(select(teams_t)).mappings()]
        # per-team top model + tokens over 30d
        per_team_model = list(conn.execute(
            select(events_t.c.team_id, events_t.c.model_name,
                   func.count().label("n"),
                   func.sum(events_t.c.tokens_in + events_t.c.tokens_out).label("tokens"))
            .where(events_t.c.team_id.isnot(None), events_t.c.ts >= cutoff)
            .group_by(events_t.c.team_id, events_t.c.model_name)))
        stmt_rows = list(conn.execute(
            select(events_t.c.model_id, events_t.c.model_name,
                   func.sum(events_t.c.tokens_in + events_t.c.tokens_out).label("tokens"),
                   func.sum(events_t.c.cost).label("cost"))
            .where(events_t.c.ts >= cutoff)
            .group_by(events_t.c.model_id, events_t.c.model_name)
            .order_by(func.sum(events_t.c.cost).desc())))
        log = [dict(r) for r in conn.execute(
            select(enforcement_t).order_by(enforcement_t.c.ts.desc()).limit(8)).mappings()]

    team_views = []
    health = {"ok": 0, "warn": 0, "degraded": 0}
    for t in teams:
        status = budget_status(t)
        health["degraded" if status["state"] in ("degraded", "over") else
               "warn" if status["state"] == "warn" else "ok"] += 1
        mine = [r for r in per_team_model if r.team_id == t["id"]]
        top = max(mine, key=lambda r: r.n).model_name if mine else "—"
        team_views.append({
            "id": t["id"], "name": t["name"], "policy": t["policy"],
            "budget_usd": t["budget_usd"], "api_key": t["api_key"],
            "enabled": bool(t.get("enabled", True)),
            "rate_limit_tpm": t.get("rate_limit_tpm"),
            "allowed_tiers": t.get("allowed_tiers"),
            "max_input_tokens": t.get("max_input_tokens"),
            "tokens": int(sum(r.tokens or 0 for r in mine)),
            "top_model": top, **status,
        })

    statement, total_tokens, total_cost = [], 0, 0.0
    for r in stmt_rows:
        m = MODELS_BY_ID.get(r.model_id)
        private = bool(m and m["self_hostable"])
        tokens, cost = int(r.tokens or 0), r.cost or 0.0
        total_tokens += tokens
        total_cost += cost
        statement.append({
            "source": (f"Private — {r.model_name}" if private
                       else f"API — {m['provider'] if m else 'unknown'} · {r.model_name}"),
            "private": private,
            "tokens": tokens, "cost": round(cost, 2),
            "per_1m": round(cost / tokens * 1e6, 2) if tokens else 0.0,
        })

    return {
        "kpis": {
            "tokens_30d": total_tokens,
            "blended_per_1m": round(total_cost / total_tokens * 1e6, 2) if total_tokens else 0.0,
            "spend_30d": round(total_cost, 2),
            "budget_health": health,
            "carbon_kg": round(total_tokens / 1000 * CARBON_G_PER_1K_TOKENS / 1000, 2),
        },
        "teams": sorted(team_views, key=lambda t: t["spend"], reverse=True),
        "statement": statement,
        "enforcement_log": log,
        "anomalies": anomalies(),
    }


seed()
