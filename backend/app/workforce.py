"""Agent workforce — per-agent observability and the FTE translation.

Two questions this module answers that a token dashboard cannot:

1. WHAT IS EACH AGENT DOING?  Tokens, duty cycle, model mix, escalation
   rate, tasks, enforcement hits, latency — the timesheet of a piece of
   software that spends money on its own.

2. HOW MUCH WORK IS THAT IN HUMAN TERMS?  Projects are still planned in
   FTE, so the platform translates completed agent tasks into
   FTE-months using a customer-owned baseline per task type:

       FTE-months = Σ(completed × human_minutes × coverage) / (hours × 60)

   `human_minutes` is what the task takes a person; `coverage` is the
   share of it an agent genuinely does (draft-then-human-review is not
   100%). Both are inputs the customer owns — without them the number
   would be marketing, with them it is a planning figure. The measured
   side (tasks, tokens, spend) is real; the human equivalence is always
   labeled an estimate and shows its basis.

The same bridge runs backwards: plan() sizes an agent for a project
("we need 3 FTE of ticket triage") and prices it from this install's
own token shapes.
"""
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, func, insert, select, update

from . import config
from .db import (ai_agents_t, enforcement_t, engine, events_t, task_types_t,
                 tasks_t)

# Completed tasks of a type before its token cost counts as measured.
MIN_TASK_SAMPLES = 5
# Fallback token shape per task when nothing has been measured yet.
ESTIMATED_TOKENS_PER_TASK = 8_000
IDLE_DAYS = 14  # no calls for this long -> idle key (cost + credential risk)

# Starter baselines. Deliberately generic and openly editable: every
# install replaces them with its own PMO numbers.
DEFAULT_TASK_TYPES = [
    {"id": "ticket-triage", "name": "Support ticket triage",
     "human_minutes": 12, "coverage_pct": 80},
    {"id": "doc-review", "name": "Document review",
     "human_minutes": 25, "coverage_pct": 70},
    {"id": "research-brief", "name": "Research brief",
     "human_minutes": 90, "coverage_pct": 60},
    {"id": "code-review", "name": "Code review pass",
     "human_minutes": 30, "coverage_pct": 50},
]


def _seed():
    from .db import IS_GATEWAY_ROLE
    if IS_GATEWAY_ROLE:
        return
    with engine.begin() as conn:
        have = {r.id for r in conn.execute(select(task_types_t.c.id))}
        rows = [{**t, "team_id": None, "created_at": time.time()}
                for t in DEFAULT_TASK_TYPES if t["id"] not in have]
        if rows:
            conn.execute(insert(task_types_t), rows)


# ---------------- task types (the human baselines) -------------------

def task_types() -> list[dict]:
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            select(task_types_t).order_by(task_types_t.c.id)).mappings()]
    return rows


def task_types_by_id() -> dict:
    return {t["id"]: t for t in task_types()}


def upsert_task_type(tt_id: str, patch: dict) -> dict:
    tt_id = tt_id.lower().replace(" ", "-")[:60]
    values = {}
    if "name" in patch:
        values["name"] = str(patch["name"])[:120]
    if "team_id" in patch:
        values["team_id"] = patch["team_id"] or None
    if patch.get("human_minutes") is not None:
        values["human_minutes"] = max(1.0, min(2400.0, float(patch["human_minutes"])))
    if patch.get("coverage_pct") is not None:
        values["coverage_pct"] = max(1.0, min(100.0, float(patch["coverage_pct"])))
    with engine.begin() as conn:
        exists = conn.execute(select(task_types_t.c.id)
                              .where(task_types_t.c.id == tt_id)).first()
        if exists:
            if values:
                conn.execute(update(task_types_t)
                             .where(task_types_t.c.id == tt_id).values(**values))
        else:
            conn.execute(insert(task_types_t).values(
                id=tt_id, name=values.get("name", tt_id),
                team_id=values.get("team_id"),
                human_minutes=values.get("human_minutes", 15.0),
                coverage_pct=values.get("coverage_pct", 70.0),
                created_at=time.time()))
        row = conn.execute(select(task_types_t)
                           .where(task_types_t.c.id == tt_id)).mappings().first()
    return dict(row)


# ---------------- FTE arithmetic -------------------------------------

def fte_month_minutes() -> float:
    return config.get("fte_hours_per_month") * 60.0


def human_minutes_for(counts: dict, types: dict) -> float:
    """Completed-task counts by type -> human minutes of covered work."""
    total = 0.0
    for tt_id, n in counts.items():
        t = types.get(tt_id)
        if not t or not n:
            continue
        total += n * t["human_minutes"] * (t["coverage_pct"] / 100.0)
    return total


def _fte_block(counts: dict, types: dict, spend: float, days: int) -> dict:
    """The measured -> human-equivalent bridge, with its own basis."""
    minutes = human_minutes_for(counts, types)
    fte_months = minutes / fte_month_minutes() if minutes else 0.0
    # sustained headcount: the same work rate carried over a 30-day month
    sustained = fte_months * (30.0 / days) if days else 0.0
    loaded = config.get("human_loaded_cost_month")
    cost_per_fte_month = round(spend / fte_months, 2) if fte_months else None
    return {
        "fte_months": round(fte_months, 3),
        "fte_sustained": round(sustained, 2),
        "human_minutes": round(minutes),
        "cost_per_fte_month": cost_per_fte_month,
        "human_cost_per_fte_month": loaded,
        "leverage_x": round(loaded / cost_per_fte_month, 1)
                      if cost_per_fte_month else None,
        "untyped_tasks": counts.get(None, 0) + counts.get("", 0),
        "basis": "estimated — completed tasks x your human-effort baseline "
                 "x coverage; tokens and spend are measured",
    }


# ---------------- roster ---------------------------------------------

def _window(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def roster(days: int = 30) -> dict:
    """One row per agent — the workforce view of the estate."""
    from .catalog import MODELS_BY_ID
    lo = _window(days)
    cutoff_ts = time.time() - days * 86400
    types = task_types_by_id()

    with engine.connect() as conn:
        usage = {r.agent_id: r for r in conn.execute(
            select(events_t.c.agent_id,
                   func.count().label("calls"),
                   func.sum(events_t.c.tokens_in).label("tin"),
                   func.sum(events_t.c.tokens_out).label("tout"),
                   func.sum(events_t.c.cost).label("spend"),
                   func.max(events_t.c.ts).label("last_ts"))
            .where(events_t.c.agent_id.isnot(None), events_t.c.ts >= lo)
            .group_by(events_t.c.agent_id))}
        # duty cycle: distinct hours in which the agent made a call
        active_hours = {r.agent_id: int(r.hours) for r in conn.execute(
            select(events_t.c.agent_id,
                   func.count(func.distinct(func.substr(events_t.c.ts, 1, 13)))
                   .label("hours"))
            .where(events_t.c.agent_id.isnot(None), events_t.c.ts >= lo)
            .group_by(events_t.c.agent_id))}
        by_model = conn.execute(
            select(events_t.c.agent_id, events_t.c.model_id,
                   func.count().label("n"))
            .where(events_t.c.agent_id.isnot(None), events_t.c.ts >= lo)
            .group_by(events_t.c.agent_id, events_t.c.model_id)).all()
        lat_rows = conn.execute(
            select(events_t.c.agent_id, events_t.c.latency_ms)
            .where(events_t.c.agent_id.isnot(None), events_t.c.ts >= lo,
                   events_t.c.cached.is_(False))).all()
        task_rows = conn.execute(
            select(tasks_t.c.agent_id, tasks_t.c.task_type,
                   func.count().label("n"),
                   func.sum(func.cast(tasks_t.c.completed, Integer)).label("done"))
            .where(tasks_t.c.created_at >= cutoff_ts)
            .group_by(tasks_t.c.agent_id, tasks_t.c.task_type)).all()
        task_spend = {r.agent_id: r.spend or 0.0 for r in conn.execute(
            select(events_t.c.agent_id, func.sum(events_t.c.cost).label("spend"))
            .where(events_t.c.agent_id.isnot(None), events_t.c.ts >= lo,
                   events_t.c.task_id.isnot(None))
            .group_by(events_t.c.agent_id))}
        enf = {r.agent_id: int(r.n) for r in conn.execute(
            select(enforcement_t.c.agent_id, func.count().label("n"))
            .where(enforcement_t.c.agent_id.isnot(None), enforcement_t.c.ts >= lo)
            .group_by(enforcement_t.c.agent_id))}
        agents = [dict(r) for r in conn.execute(select(ai_agents_t)).mappings()]

    models_by_agent: dict = {}
    for r in by_model:
        models_by_agent.setdefault(r.agent_id, []).append((r.model_id, int(r.n)))
    lats: dict = {}
    for r in lat_rows:
        lats.setdefault(r.agent_id, []).append(r.latency_ms)
    counts_by_agent: dict = {}
    started_by_agent: dict = {}
    for r in task_rows:
        counts_by_agent.setdefault(r.agent_id, {})[r.task_type] = int(r.done or 0)
        started_by_agent[r.agent_id] = started_by_agent.get(r.agent_id, 0) + int(r.n)

    out = []
    fleet_counts: dict = {}
    fleet_spend = 0.0
    for a in agents:
        u = usage.get(a["id"])
        calls = int(u.calls) if u else 0
        tin = int(u.tin or 0) if u else 0
        tout = int(u.tout or 0) if u else 0
        spend = round(float(u.spend or 0.0), 4) if u else 0.0
        mix = sorted(models_by_agent.get(a["id"], []), key=lambda x: -x[1])
        strong = sum(n for mid, n in mix
                     if MODELS_BY_ID.get(mid, {}).get("size_class") != "slm")
        agent_lats = sorted(lats.get(a["id"], []))
        counts = counts_by_agent.get(a["id"], {})
        completed = sum(counts.values())
        on_tasks = task_spend.get(a["id"], 0.0)
        last_ts = u.last_ts if u else None
        idle_days = None
        if last_ts:
            try:
                idle_days = (datetime.now(timezone.utc)
                             - datetime.fromisoformat(last_ts)).days
            except ValueError:
                idle_days = None
        status = ("paused" if a.get("enabled") is False else
                  "idle" if calls == 0 or (idle_days or 0) >= IDLE_DAYS else
                  "active")
        fte = _fte_block(counts, types, spend, days)
        for k, v in counts.items():
            fleet_counts[k] = fleet_counts.get(k, 0) + v
        fleet_spend += spend
        out.append({
            "id": a["id"], "name": a["name"], "team_id": a["team_id"],
            "api_key": a["api_key"], "role": a.get("role"),
            "role_name": types.get(a.get("role"), {}).get("name"),
            "expected_fte": a.get("expected_fte"),
            "enabled": a.get("enabled") is not False,
            "status": status,
            "calls": calls, "tokens_in": tin, "tokens_out": tout,
            "tokens": tin + tout,
            "avg_tokens_per_call": round((tin + tout) / calls) if calls else 0,
            "spend": spend,
            "duty_cycle_pct": round(
                active_hours.get(a["id"], 0) / (days * 24) * 100, 1),
            "active_hours": active_hours.get(a["id"], 0),
            "escalation_pct": round(strong / calls * 100, 1) if calls else 0.0,
            "top_models": [{"model_id": m, "calls": n} for m, n in mix[:3]],
            "tasks_started": started_by_agent.get(a["id"], 0),
            "tasks_completed": completed,
            "cost_per_outcome": round(on_tasks / completed, 4) if completed else None,
            "enforcement_hits": enf.get(a["id"], 0),
            "p50_ms": _pct(agent_lats, 50), "p95_ms": _pct(agent_lats, 95),
            "last_active": last_ts, "idle_days": idle_days,
            "budget_usd": a.get("budget_usd"),
            "budget_pct": round(spend / a["budget_usd"] * 100, 1)
                          if a.get("budget_usd") else None,
            "rate_limit_tpm": a.get("rate_limit_tpm"),
            "allowed_tiers": a.get("allowed_tiers"),
            "max_delegation_depth": a.get("max_delegation_depth"),
            "fte": fte,
        })
    out.sort(key=lambda a: -a["spend"])
    fleet = _fte_block(fleet_counts, types, fleet_spend, days)
    fleet.update({
        "agents": len(out),
        "active": sum(1 for a in out if a["status"] == "active"),
        "idle": sum(1 for a in out if a["status"] == "idle"),
        "spend": round(fleet_spend, 4),
        "tasks_completed": sum(fleet_counts.values()),
        "expected_fte": round(sum(a["expected_fte"] or 0 for a in out), 2),
    })
    if fleet["fte_months"]:
        fleet["human_cost_equivalent"] = round(
            fleet["fte_months"] * config.get("human_loaded_cost_month"), 2)
        fleet["savings_vs_human"] = round(
            fleet["human_cost_equivalent"] - fleet["spend"], 2)
    return {"days": days, "agents": out, "fleet": fleet,
            "task_types": list(types.values())}


def _pct(sorted_vals: list, p: float) -> int:
    if not sorted_vals:
        return 0
    k = max(0, min(len(sorted_vals) - 1, int(round((p / 100) * len(sorted_vals) + 0.5)) - 1))
    return int(sorted_vals[k])


def agent_detail(agent_id: str, days: int = 30) -> dict:
    """Daily series + recent missions for one agent."""
    lo = _window(days)
    cutoff_ts = time.time() - days * 86400
    with engine.connect() as conn:
        agent = conn.execute(select(ai_agents_t)
                             .where(ai_agents_t.c.id == agent_id)).mappings().first()
        if not agent:
            raise ValueError(f"unknown agent '{agent_id}'")
        series = conn.execute(
            select(events_t.c.day,
                   func.count().label("calls"),
                   func.sum(events_t.c.tokens_in + events_t.c.tokens_out).label("tokens"),
                   func.sum(events_t.c.cost).label("spend"))
            .where(events_t.c.agent_id == agent_id, events_t.c.ts >= lo)
            .group_by(events_t.c.day).order_by(events_t.c.day)).all()
        missions = conn.execute(
            select(tasks_t).where(tasks_t.c.agent_id == agent_id,
                                  tasks_t.c.created_at >= cutoff_ts)
            .order_by(tasks_t.c.created_at.desc()).limit(25)).mappings().all()
        enf = conn.execute(
            select(enforcement_t).where(enforcement_t.c.agent_id == agent_id,
                                        enforcement_t.c.ts >= lo)
            .order_by(enforcement_t.c.ts.desc()).limit(20)).mappings().all()

    from . import agentic
    rows = [a for a in roster(days)["agents"] if a["id"] == agent_id]
    return {
        "agent": rows[0] if rows else dict(agent),
        "series": [{"day": r.day, "calls": int(r.calls),
                    "tokens": int(r.tokens or 0),
                    "spend": round(float(r.spend or 0.0), 4)} for r in series],
        "missions": [{"id": m["id"], "task_type": m["task_type"],
                      "budget_usd": m["budget_usd"],
                      "completed": bool(m["completed"]),
                      "spend_usd": agentic.task_spend(m["id"]),
                      "created_at": m["created_at"]} for m in missions],
        "enforcement": [{"ts": e["ts"], "action": e["action"],
                         "detail": e["detail"]} for e in enf],
    }


# ---------------- capacity planning (the estimate direction) ---------

def measured_tokens_per_task(task_type: str | None) -> dict:
    """Average token shape of completed tasks of this type, from THIS
    install's traffic. Falls back to a labeled estimate."""
    with engine.connect() as conn:
        q = select(func.count(func.distinct(tasks_t.c.id)).label("tasks"),
                   func.sum(events_t.c.tokens_in).label("tin"),
                   func.sum(events_t.c.tokens_out).label("tout"),
                   func.sum(events_t.c.cost).label("cost")) \
            .select_from(tasks_t.join(events_t, events_t.c.task_id == tasks_t.c.id)) \
            .where(tasks_t.c.completed.is_(True))
        if task_type:
            q = q.where(tasks_t.c.task_type == task_type)
        r = conn.execute(q).first()
    n = int(r.tasks or 0)
    if n >= MIN_TASK_SAMPLES:
        tokens = int((r.tin or 0) + (r.tout or 0))
        return {"tokens_per_task": round(tokens / n),
                "cost_per_task": round(float(r.cost or 0.0) / n, 5),
                "samples": n, "basis": "measured"}
    return {"tokens_per_task": ESTIMATED_TOKENS_PER_TASK,
            "cost_per_task": None, "samples": n, "basis": "estimated"}


def plan(task_type: str, tasks_per_month: float | None = None,
         target_fte: float | None = None, months: int = 6,
         coverage_pct: float | None = None) -> dict:
    """Size an agent for a project: FTE <-> tasks <-> tokens <-> dollars.

    Give it either the work ("12,000 reviews a month") or the headcount
    ("3 FTE of review"); it returns the other, priced from this
    install's own token shapes, plus the budgets to enforce the plan.
    """
    from .catalog import MODELS_BY_ID
    from . import analytics, router as smart_router
    types = task_types_by_id()
    tt = types.get(task_type)
    if not tt:
        raise ValueError(f"unknown task type '{task_type}'")
    coverage = (coverage_pct if coverage_pct is not None
                else tt["coverage_pct"]) / 100.0
    minutes = tt["human_minutes"] * coverage
    per_fte_month = fte_month_minutes() / minutes  # tasks one FTE-month covers

    if tasks_per_month is None and target_fte is None:
        raise ValueError("give either tasks_per_month or target_fte")
    if tasks_per_month is None:
        tasks_per_month = target_fte * per_fte_month
    fte_covered = tasks_per_month / per_fte_month

    shape = measured_tokens_per_task(task_type)
    tokens_per_task = shape["tokens_per_task"]
    # 30/70 in/out split is the observed shape of agent traffic
    tin, tout = tokens_per_task * 0.3, tokens_per_task * 0.7

    def price(model: dict) -> float:
        return (tin * model["input_price"] + tout * model["output_price"]) / 1_000_000

    small = smart_router.small_model()
    strong = smart_router.strong_model()
    routed = analytics.router_summary(30).get("policies", {}).get("route")
    # the same rule the counterfactual uses: don't call a mix "measured"
    # off a handful of requests
    if routed and routed["requests"] >= 5:
        small_share, mix_basis = routed["small_share_pct"], "measured"
    else:
        small_share, mix_basis = 85.0, "assumed"

    options = []
    for label, cost_task, note in [
        ("router (model:\"route\")",
         price(small) * (small_share / 100) + price(strong) * (1 - small_share / 100),
         f"{small_share:.0f}% small / {100 - small_share:.0f}% strong "
         f"({mix_basis} mix)"),
        (f"smallest capable ({small['name']})", price(small),
         "cheapest floor — quality must be evidenced in Evals"),
        (f"always strong ({strong['name']})", price(strong),
         "the do-nothing baseline most agent stacks run on"),
    ]:
        monthly = cost_task * tasks_per_month
        options.append({
            "option": label, "note": note,
            "cost_per_task": round(cost_task, 5),
            "monthly_usd": round(monthly, 2),
            "total_usd": round(monthly * months, 2),
            "tokens_per_month": int(tokens_per_task * tasks_per_month),
        })
    if shape["cost_per_task"]:
        monthly = shape["cost_per_task"] * tasks_per_month
        options.insert(0, {
            "option": "current mix (as this agent runs today)",
            "note": f"measured over {shape['samples']} completed tasks",
            "cost_per_task": shape["cost_per_task"],
            "monthly_usd": round(monthly, 2),
            "total_usd": round(monthly * months, 2),
            "tokens_per_month": int(tokens_per_task * tasks_per_month),
        })

    # plan on the router, not on the floor: the cheapest line is the
    # smallest model, but committing a project to it is a quality claim
    # this module has no evidence for
    recommended = next(o for o in options if o["option"].startswith("router"))
    cheapest = min(options, key=lambda o: o["monthly_usd"])
    human_monthly = fte_covered * config.get("human_loaded_cost_month")
    return {
        "task_type": {"id": tt["id"], "name": tt["name"],
                      "human_minutes": tt["human_minutes"],
                      "coverage_pct": round(coverage * 100, 1)},
        "tasks_per_month": round(tasks_per_month),
        "fte_covered": round(fte_covered, 2),
        "tasks_per_fte_month": round(per_fte_month),
        "months": months,
        "shape": {**shape, "tokens_per_task": tokens_per_task},
        "options": options,
        "recommended": recommended["option"],
        "cheapest": cheapest["option"],
        "monthly_usd": recommended["monthly_usd"],
        "total_usd": recommended["total_usd"],
        "human_equivalent": {
            "fte": round(fte_covered, 2),
            "monthly_usd": round(human_monthly, 2),
            "total_usd": round(human_monthly * months, 2),
            "savings_monthly_usd": round(human_monthly - recommended["monthly_usd"], 2),
            "basis": "your configured loaded cost per FTE-month x covered FTE",
        },
        "enforce": {
            "agent_budget_usd": round(recommended["monthly_usd"] * 1.2, 2),
            "task_budget_usd": round(recommended["cost_per_task"] * 1.5, 4),
            "note": "20% headroom on the monthly budget, 50% on the mission "
                    "budget — set these on the agent and the plan becomes "
                    "enforced, not aspirational",
        },
        "caveats": [
            "FTE is an estimate: it rests on your human-minutes and coverage "
            "inputs, not on anything measured about a person.",
            "Token cost is "
            + ("measured from this install's completed tasks of this type."
               if shape["basis"] == "measured" else
               f"estimated ({ESTIMATED_TOKENS_PER_TASK:,} tokens/task) — "
               f"only {shape['samples']} completed tasks of this type so far."),
            "Quality is never simulated: evidence the model choice in Evals "
            "before committing a plan.",
        ],
    }


_seed()
