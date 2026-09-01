"""Agentic tokenomics — treasury management for software that spends.

Humans make one request per thought; agents fan a single instruction
into dozens of calls, fail at machine speed, and choose which model to
pay for each step. This module adds the agentic-era layer on top of
team tokenomics:

- AGENT IDENTITIES: sub-keys under a team (ak-…). Every existing
  control — budgets, limits, anomalies, the ledger — gains per-agent
  attribution simply because events now carry agent_id.
- MISSION BUDGETS: a task ("this research job may spend $0.50") metered
  across every call carrying its X-Task-Id. At 100% of the task budget
  requests degrade to the smallest capable model; at 150% they stop.
  Degrade-before-block keeps an agent mid-task working, cheaply.
- LOOP-BREAKER: teams can opt into automatic containment — when a
  team's output volume trips the anomaly detector, traffic is forced
  onto the smallest capable model until behavior normalizes.
- COST PER OUTCOME: agents mark tasks complete; spend ÷ completed
  tasks is the metric that prices agent work, not raw tokens.
- DELEGATION DEPTH: X-Delegation-Depth vs a per-team maximum — the
  agentic equivalent of a fork-bomb guard.
"""
import secrets
import time

from sqlalchemy import Integer, func, insert, select, update

from .db import ai_agents_t, engine, events_t, tasks_t

TASK_HARD_STOP = 1.5  # x budget: degrade at 1.0, refuse beyond this


# ---------------- agent identities -----------------------------------

def create_agent(team_id: str, name: str) -> dict:
    agent_id = name.lower().replace(" ", "-")[:60]
    row = {"id": agent_id, "team_id": team_id, "name": name,
           "api_key": f"ak-{secrets.token_hex(12)}", "created_at": time.time()}
    with engine.begin() as conn:
        exists = conn.execute(select(ai_agents_t.c.id)
                              .where(ai_agents_t.c.id == agent_id)).first()
        if exists:
            raise ValueError(f"agent '{agent_id}' already exists")
        conn.execute(insert(ai_agents_t).values(**row))
    return row


def resolve_agent(bearer_key: str | None) -> dict | None:
    if not bearer_key or not bearer_key.startswith("ak-"):
        return None
    with engine.connect() as conn:
        row = conn.execute(select(ai_agents_t)
                           .where(ai_agents_t.c.api_key == bearer_key)).mappings().first()
    return dict(row) if row else None


def agents_for(team_id: str | None = None) -> list[dict]:
    with engine.connect() as conn:
        q = select(ai_agents_t)
        if team_id:
            q = q.where(ai_agents_t.c.team_id == team_id)
        return [dict(r) for r in conn.execute(q).mappings()]


# ---------------- mission budgets ------------------------------------

def get_or_create_task(task_id: str, team_id: str,
                       agent_id: str | None, budget_usd: float | None) -> dict:
    with engine.begin() as conn:
        row = conn.execute(select(tasks_t)
                           .where(tasks_t.c.id == task_id)).mappings().first()
        if row:
            task = dict(row)
            # a budget supplied later attaches to a budget-less task,
            # but an existing budget is immutable (no mid-task raises)
            if budget_usd and not task["budget_usd"]:
                conn.execute(update(tasks_t).where(tasks_t.c.id == task_id)
                             .values(budget_usd=budget_usd))
                task["budget_usd"] = budget_usd
            return task
        task = {"id": task_id[:80], "team_id": team_id, "agent_id": agent_id,
                "budget_usd": budget_usd, "created_at": time.time(),
                "completed": False, "completed_at": None}
        conn.execute(insert(tasks_t).values(**task))
        return task


def task_spend(task_id: str) -> float:
    with engine.connect() as conn:
        return conn.execute(
            select(func.sum(events_t.c.cost))
            .where(events_t.c.task_id == task_id)).scalar() or 0.0


def task_precheck(task: dict) -> dict | None:
    """Mission-budget gate, evaluated BEFORE serving a call.
    Returns None (fine), {"action": "degrade", ...} or {"action": "block", ...}."""
    if not task.get("budget_usd"):
        return None
    spend = task_spend(task["id"])
    budget = task["budget_usd"]
    if spend >= budget * TASK_HARD_STOP:
        return {"action": "block", "spend": round(spend, 4), "budget": budget,
                "reason": f"task '{task['id']}' spent ${spend:.4f} of its "
                          f"${budget:.2f} budget (hard stop at {TASK_HARD_STOP:.0%})"}
    if spend >= budget:
        return {"action": "degrade", "spend": round(spend, 4), "budget": budget,
                "reason": f"task '{task['id']}' reached its ${budget:.2f} "
                          "budget — serving smallest capable model"}
    return None


def complete_task(task_id: str, team_id: str) -> dict:
    with engine.begin() as conn:
        row = conn.execute(select(tasks_t).where(
            tasks_t.c.id == task_id, tasks_t.c.team_id == team_id)).mappings().first()
        if not row:
            raise ValueError("unknown task for this team")
        conn.execute(update(tasks_t).where(tasks_t.c.id == task_id)
                     .values(completed=True, completed_at=time.time()))
    return {"task_id": task_id, "completed": True,
            "spend_usd": round(task_spend(task_id), 4)}


# ---------------- per-agent rollup (cost per outcome) ----------------

def overview() -> dict:
    """Spend tree: team → agent, with tasks and cost-per-completed-task
    — the metric that prices agent work in outcomes, not tokens."""
    with engine.connect() as conn:
        usage = {r.agent_id: r for r in conn.execute(
            select(events_t.c.agent_id,
                   func.count().label("calls"),
                   func.sum(events_t.c.tokens_in + events_t.c.tokens_out).label("tokens"),
                   func.sum(events_t.c.cost).label("spend"))
            .where(events_t.c.agent_id.isnot(None))
            .group_by(events_t.c.agent_id))}
        task_rows = conn.execute(
            select(tasks_t.c.agent_id,
                   func.count().label("tasks"),
                   func.sum(func.cast(tasks_t.c.completed, Integer))
                   .label("completed"))
            .group_by(tasks_t.c.agent_id)).all()
        tasks_by_agent = {r.agent_id: r for r in task_rows}
        task_spend_rows = conn.execute(
            select(events_t.c.agent_id, func.sum(events_t.c.cost).label("spend"))
            .where(events_t.c.task_id.isnot(None), events_t.c.agent_id.isnot(None))
            .group_by(events_t.c.agent_id)).all()
        task_spend_by_agent = {r.agent_id: r.spend or 0.0 for r in task_spend_rows}

    out = []
    for a in agents_for():
        u = usage.get(a["id"])
        t = tasks_by_agent.get(a["id"])
        completed = int(t.completed or 0) if t else 0
        on_tasks = task_spend_by_agent.get(a["id"], 0.0)
        out.append({
            "id": a["id"], "name": a["name"], "team_id": a["team_id"],
            "api_key": a["api_key"],
            "calls": int(u.calls) if u else 0,
            "tokens": int(u.tokens or 0) if u else 0,
            "spend": round(u.spend or 0.0, 4) if u else 0.0,
            "tasks": int(t.tasks) if t else 0,
            "tasks_completed": completed,
            "cost_per_outcome": round(on_tasks / completed, 4) if completed else None,
        })
    out.sort(key=lambda a: -a["spend"])
    return {"agents": out}
