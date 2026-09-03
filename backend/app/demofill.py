"""Demo fill — populate every feature surface with plausible history.

Runs once (kv-flagged) in demo mode, AFTER the base seeds, so that no
page shows an empty state: routed traffic for the smart router and its
savings cards, agent missions with completed tasks for cost-per-outcome,
deployments on the simulated fleet, a Decision Ledger backfill, cluster
allocation history for the sparklines, and a varied enforcement pulse.

Everything here is additive and deliberately small in dollar terms so
the seeded team budget states (ok / warn / degraded) are not disturbed.
DEMO_SEED=0 disables all of it — real installs start honest and empty.
"""
import json
import random
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, select, func

from . import agentic, analytics, deployments, resilience
from .catalog import MODELS_BY_ID
from .db import (cluster_util_t, deployments_t, engine, enforcement_t,
                 events_t, ledger_t, tasks_t, teams_t)

_FLAG = "demo_filled_v1"


def _cost(mid: str, tin: int, tout: int) -> float:
    m = MODELS_BY_ID[mid]
    return round((tin * m["input_price"] + tout * m["output_price"]) / 1e6, 6)


def _event(ts, mid, tin, tout, lat, **kw):
    return {"ts": ts.isoformat(), "day": ts.strftime("%Y-%m-%d"),
            "model_id": mid, "model_name": MODELS_BY_ID[mid]["name"],
            "tokens_in": tin, "tokens_out": tout, "latency_ms": lat,
            "cached": False, "cost": _cost(mid, tin, tout),
            "backend": "simulated", "policy": None,
            "team_id": None, "agent_id": None, "task_id": None, **kw}


def _ensure_agents():
    """Demo agents must exist even on databases created before the
    agentic module (team seeding exits early there and never reaches
    agent creation). Idempotent, runs on every demo-mode boot."""
    from .db import ai_agents_t
    import secrets
    with engine.begin() as conn:
        have = {r.id for r in conn.execute(select(ai_agents_t.c.id))}
        for aid, team, name in (
                ("planner-agent", "research-agents", "Planner Agent"),
                ("scraper-agent", "research-agents", "Scraper Agent"),
                ("triage-agent", "support-bot", "Triage Agent")):
            if aid not in have:
                conn.execute(insert(ai_agents_t).values(
                    id=aid, team_id=team, name=name,
                    api_key=f"ak-{secrets.token_hex(12)}",
                    created_at=time.time()))


def seed():
    from .db import IS_GATEWAY_ROLE
    if IS_GATEWAY_ROLE or not analytics.demo_seed_enabled():
        return
    _ensure_agents()
    if resilience.kv_get(_FLAG):
        return
    rng = random.Random(7)
    now = datetime.now(timezone.utc)
    events, ledgers = [], []

    # ---- 1. routed traffic history: route / cascade / auto ----------
    # escalation share drifts gently upward so the router-health trend
    # has a story; costs kept small (SLM-dominated, few strong calls)
    for day_off in range(13, -1, -1):
        day = now - timedelta(days=day_off)
        esc_pct = 0.08 + (13 - day_off) * 0.004        # 8% -> ~13%
        for _ in range(rng.randint(38, 60)):
            ts = day.replace(hour=rng.randint(7, 21), minute=rng.randint(0, 59),
                             second=rng.randint(0, 59))
            escalated = rng.random() < esc_pct
            if escalated:
                e = _event(ts, "claude-opus-4.5", rng.randint(300, 1400),
                           rng.randint(200, 700), rng.randint(700, 1500),
                           policy="route", team_id="doc-pipeline")
            else:
                e = _event(ts, "phi-4", rng.randint(20, 220),
                           rng.randint(60, 260), rng.randint(90, 260),
                           policy="route", team_id="doc-pipeline")
            events.append(e)
        for _ in range(rng.randint(8, 16)):            # cascade + auto
            ts = day.replace(hour=rng.randint(8, 20), minute=rng.randint(0, 59))
            pol = rng.choice(["cascade", "cascade", "auto"])
            mid = "phi-4" if pol == "cascade" and rng.random() < 0.85 else \
                rng.choice(["gemini-2.5-flash", "claude-haiku-4.5"])
            events.append(_event(ts, mid, rng.randint(30, 400),
                                 rng.randint(80, 300), rng.randint(150, 500),
                                 policy=pol))

    # ---- 2. agent missions: tasks with budgets, mostly completed ----
    tasks = []
    for i in range(24):
        agent_id, team_id, prefix = rng.choice([
            ("triage-agent", "support-bot", "ticket"),
            ("planner-agent", "research-agents", "research"),
            ("scraper-agent", "research-agents", "crawl")])
        created = now - timedelta(days=rng.randint(0, 9),
                                  hours=rng.randint(0, 20))
        task_id = f"{prefix}-{1000 + i}"
        completed = rng.random() < 0.8
        tasks.append({"id": task_id, "team_id": team_id, "agent_id": agent_id,
                      "budget_usd": rng.choice([0.10, 0.25, 0.50]),
                      "created_at": created.timestamp(),
                      "completed": completed,
                      "completed_at": created.timestamp() + rng.randint(120, 1800)
                      if completed else None})
        for _ in range(rng.randint(3, 9)):             # the mission's calls
            ts = created + timedelta(seconds=rng.randint(10, 1500))
            events.append(_event(ts, "phi-4", rng.randint(40, 300),
                                 rng.randint(60, 240), rng.randint(90, 240),
                                 policy="route", team_id=team_id,
                                 agent_id=agent_id, task_id=task_id))

    # ---- 3. deployments on the simulated fleet ----------------------
    made = []
    with engine.connect() as conn:
        have = conn.execute(select(func.count()).select_from(deployments_t)).scalar()
    if not have:
        for mid, profile, name, cluster, cls in [
                ("phi-4", "balanced", "support-slm", "onprem-dc1", "reserved"),
                ("llama-4-maverick", "balanced", "legal-70b", "cloud-burst", "reserved"),
                ("mistral-small-3.2", "balanced", "dev-mistral", "onprem-dc1", "on-demand")]:
            try:
                made.append(deployments.create(mid, profile, name,
                                               cluster_id=cluster,
                                               serving_class=cls))
            except ValueError:
                pass  # capacity may differ on older databases — skip honestly
        if made:
            with engine.begin() as conn:  # backdate so they show as running
                for i, d in enumerate(made):
                    conn.execute(deployments_t.update()
                                 .where(deployments_t.c.id == d["id"])
                                 .values(created_at=time.time() - 7200 - i * 3600))
            # dev-mistral demonstrates scale-to-zero: asleep for ~20h,
            # its vGPU back in the pool, GPU-hours accruing live
            from . import serving
            from .db import sleep_log_t
            dev = next((d for d in made if d["name"] == "dev-mistral"), None)
            if dev:
                serving.sleep(dev["id"], reason="auto — idle > 60 min")
                with engine.begin() as conn:
                    conn.execute(sleep_log_t.update()
                                 .where(sleep_log_t.c.dep_id == dev["id"])
                                 .values(slept_at=time.time() - 20 * 3600))
    # traffic for two of them so only 'dev-mistral' is a deliberate
    # idle-reclamation example in the attention queue
    for mid in ("phi-4", "llama-4-maverick"):
        for _ in range(6):
            ts = now - timedelta(hours=rng.randint(1, 40))
            events.append(_event(ts, mid, rng.randint(50, 400),
                                 rng.randint(80, 400), rng.randint(120, 600)))

    # ---- 4. enforcement pulse variety (recent, inside 24h) ----------
    with engine.begin() as conn:
        conn.execute(insert(enforcement_t), [
            {"ts": (now - timedelta(hours=2, minutes=12)).isoformat(),
             "team_id": "intern-sandbox", "action": "BLOCK",
             "detail": "tier allowlist: request for claude-opus-4.5 outside "
                       "'slm,mid' — refused (403)"},
            {"ts": (now - timedelta(minutes=48)).isoformat(),
             "team_id": "research-agents", "action": "LOOPBREAK",
             "detail": "anomalous output volume — gemini-2.5-pro served by "
                       "phi-4 until behavior normalizes"},
        ])
        # delegation guard visible on doc-pipeline; loop policy left off so
        # the admin can arm it live during a demo (the LOOPBREAK log line
        # above shows what containment looked like when it last fired)
        conn.execute(teams_t.update().where(teams_t.c.id == "doc-pipeline")
                     .values(max_delegation_depth=4))

    # ---- 5. decision-ledger backfill --------------------------------
    for e in rng.sample(events, min(70, len(events))):
        pol = e.get("policy")
        if not pol:
            continue
        mid = e["model_id"]
        if pol == "route":
            small = mid == "phi-4"
            summary = (f"smart-router {'simple' if small else 'complex'} "
                       f"({'0.15' if small else '0.6'}/0.5) → {mid}")
            receipt = {"router": {
                "verdict": "simple" if small else "complex",
                "score": 0.15 if small else 0.6,
                "threshold": 0.5, "served_by": mid,
                "signals": [
                    {"signal": "reasoning_keywords", "weight": 0.25,
                     "fired": not small, "detail": "analyze, plan" if not small else None},
                    {"signal": "short_question", "weight": -0.15,
                     "fired": small, "detail": "12 words" if small else None},
                ]}}
        elif pol == "cascade":
            summary = f"cascade → {mid}: classified simple — handled by tier-1 SLM"
            receipt = {"cascade": {"tier1": "phi-4", "served_by": mid}}
        else:
            summary = f"recommender routed → {mid}"
            receipt = {"reason": "auto policy — weighted quality/cost/speed"}
        ledgers.append({
            "ts": e["ts"], "day": e["day"], "kind": "routing", "policy": pol,
            "model_id": mid, "team_id": e.get("team_id"),
            "summary": summary, "receipt_json": json.dumps(receipt)})
    ledgers.append({
        "ts": (now - timedelta(hours=2, minutes=12)).isoformat(),
        "day": now.strftime("%Y-%m-%d"), "kind": "enforcement", "policy": "direct",
        "model_id": "claude-opus-4.5", "team_id": "intern-sandbox",
        "summary": "tier allowlist: intern-sandbox blocked from claude-opus-4.5",
        "receipt_json": json.dumps({"enforcement": {"code": 403, "rule": "allowed_tiers"}})})
    ledgers.append({
        "ts": (now - timedelta(minutes=48)).isoformat(),
        "day": now.strftime("%Y-%m-%d"), "kind": "enforcement", "policy": "direct",
        "model_id": "phi-4", "team_id": "research-agents",
        "summary": "loop-breaker: gemini-2.5-pro → phi-4 — output volume "
                   "anomalous vs baseline, auto-contained",
        "receipt_json": json.dumps({"loopbreak": {"served_by": "phi-4"}})})
    ledgers.append({
        "ts": (now - timedelta(days=1, hours=3)).isoformat(),
        "day": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
        "kind": "failover", "policy": "direct",
        "model_id": "gemini-2.5-pro", "team_id": None,
        "summary": "gpt-5.1 → gemini-2.5-pro: OpenAI declared down "
                   "(resilience drill) — failed over to closest comparable model",
        "receipt_json": json.dumps({"failover": {"requested": "gpt-5.1",
                                                 "served_by": "gemini-2.5-pro",
                                                 "provider_down": "OpenAI"}})})

    # ---- 6. cluster allocation history for the 24h sparklines -------
    hist = []
    for cid, base in (("onprem-dc1", 48), ("eu-west-osh", 78), ("cloud-burst", 8)):
        for h in range(24, 0, -1):
            ts = (now - timedelta(hours=h)).timestamp()
            wobble = int(8 * rng.random()) + (6 if 9 <= (now.hour - h) % 24 <= 18 else 0)
            hist.append({"cluster_id": cid, "ts": ts,
                         "util_pct": max(0, min(100, base + wobble))})

    with engine.begin() as conn:
        existing_tasks = {r.id for r in conn.execute(select(tasks_t.c.id))}
        tasks = [t for t in tasks if t["id"] not in existing_tasks]
        conn.execute(insert(events_t), events)
        if tasks:
            conn.execute(insert(tasks_t), tasks)
        if ledgers:
            conn.execute(insert(ledger_t), ledgers)
        conn.execute(insert(cluster_util_t), hist)
    resilience.kv_set(_FLAG, "1")
