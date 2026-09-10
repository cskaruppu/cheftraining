import { useEffect, useState } from "react";
import { PageHeader, Sparkline, Spinner, StatTile } from "../components/ui";

interface FteBlock {
  fte_months: number;
  fte_sustained: number;
  human_minutes: number;
  cost_per_fte_month: number | null;
  human_cost_per_fte_month: number;
  leverage_x: number | null;
  untyped_tasks: number;
  basis: string;
}

interface Agent {
  id: string; name: string; team_id: string; api_key: string;
  role: string | null; role_name: string | null;
  expected_fte: number | null; enabled: boolean; status: string;
  calls: number; tokens_in: number; tokens_out: number; tokens: number;
  avg_tokens_per_call: number; spend: number;
  duty_cycle_pct: number; active_hours: number; escalation_pct: number;
  top_models: { model_id: string; calls: number }[];
  tasks_started: number; tasks_completed: number;
  cost_per_outcome: number | null; enforcement_hits: number;
  p50_ms: number; p95_ms: number;
  last_active: string | null; idle_days: number | null;
  budget_usd: number | null; budget_pct: number | null;
  rate_limit_tpm: number | null; allowed_tiers: string | null;
  max_delegation_depth: number | null;
  fte: FteBlock;
}

interface Fleet extends FteBlock {
  agents: number; active: number; idle: number; spend: number;
  tasks_completed: number; expected_fte: number;
  human_cost_equivalent?: number; savings_vs_human?: number;
}

interface TaskType {
  id: string; name: string; team_id: string | null;
  human_minutes: number; coverage_pct: number;
}

interface Roster { days: number; agents: Agent[]; fleet: Fleet; task_types: TaskType[] }

interface Detail {
  agent: Agent;
  series: { day: string; calls: number; tokens: number; spend: number }[];
  missions: { id: string; task_type: string | null; budget_usd: number | null;
              completed: boolean; spend_usd: number; created_at: number }[];
  enforcement: { ts: string; action: string; detail: string }[];
}

interface PlanOption {
  option: string; note: string; cost_per_task: number;
  monthly_usd: number; total_usd: number; tokens_per_month: number;
}

interface Plan {
  task_type: { id: string; name: string; human_minutes: number; coverage_pct: number };
  tasks_per_month: number; fte_covered: number; tasks_per_fte_month: number;
  months: number;
  shape: { tokens_per_task: number; cost_per_task: number | null; samples: number; basis: string };
  options: PlanOption[]; recommended: string; cheapest: string;
  monthly_usd: number; total_usd: number;
  human_equivalent: { fte: number; monthly_usd: number; total_usd: number;
                      savings_monthly_usd: number; basis: string };
  enforce: { agent_budget_usd: number; task_budget_usd: number; note: string };
  caveats: string[];
}

const STATUS_CHIP: Record<string, string> = {
  active: "border-good/40 text-good",
  idle: "border-warn/40 text-warn",
  paused: "border-crit/40 text-crit",
};

const RANGES = [7, 30, 90];
const usd = (n: number) =>
  n >= 100 ? `$${Math.round(n).toLocaleString()}` : `$${n.toFixed(2)}`;
// cost per outcome is often sub-cent — 4dp would round every agent to the
// same number, which hides exactly the difference the column exists for
const cents = (n: number) => `$${n < 0.001 ? n.toFixed(6) : n.toFixed(4)}`;

export default function Workforce() {
  const [data, setData] = useState<Roster | null>(null);
  const [days, setDays] = useState(30);
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [tab, setTab] = useState<"roster" | "plan" | "baselines">("roster");

  const refresh = () =>
    fetch(`/api/workforce?days=${days}`).then((r) => r.json()).then(setData);

  useEffect(() => { setData(null); refresh(); }, [days]);

  useEffect(() => {
    if (!open) { setDetail(null); return; }
    setDetail(null);
    fetch(`/api/workforce/agents/${open}?days=${days}`)
      .then((r) => r.json()).then(setDetail);
  }, [open, days]);

  if (!data) return <Spinner />;
  const f = data.fleet;

  return (
    <div>
      <PageHeader
        title="Agent Workforce"
        sub="Agents as staffed capacity, not just API keys: what each one consumed and delivered, and what that work is worth in the unit projects are still planned in — FTE. Tokens, spend and tasks are measured; the human equivalence rests on your own effort baselines and is labelled throughout."
      />

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="flex rounded-lg border border-edge overflow-hidden">
          {RANGES.map((d) => (
            <button key={d} onClick={() => setDays(d)}
              className={`px-3 py-1.5 text-xs transition ${
                days === d ? "bg-raised text-ink" : "text-muted hover:text-ink2"}`}>
              {d}d
            </button>
          ))}
        </div>
        <div className="flex rounded-lg border border-edge overflow-hidden">
          {([["roster", "Roster"], ["plan", "FTE planner"],
             ["baselines", "Effort baselines"]] as const).map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)}
              className={`px-3 py-1.5 text-xs transition ${
                tab === k ? "bg-raised text-ink" : "text-muted hover:text-ink2"}`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4 mb-3">
        <StatTile label="Agents"
          value={`${f.active} active`}
          hint={`${f.agents} identities · ${f.idle} idle`} />
        <StatTile label="FTE delivered"
          value={f.fte_sustained.toFixed(2)}
          hint={`sustained headcount equivalent · ${f.expected_fte.toFixed(2)} requisitioned`} />
        <StatTile label="Cost per FTE-month"
          value={f.cost_per_fte_month === null ? "—" : usd(f.cost_per_fte_month)}
          hint={`vs ${usd(f.human_cost_per_fte_month)} loaded human cost`} />
        <StatTile label="Leverage"
          value={f.leverage_x === null ? "—" : `${f.leverage_x.toLocaleString()}x`}
          hint={`${f.tasks_completed.toLocaleString()} tasks completed in ${data.days}d`} />
      </div>

      {f.human_cost_equivalent !== undefined && (
        <div className="card mb-4 border-s3/40">
          <div className="text-sm">
            The agent fleet delivered{" "}
            <b className="text-ink">{f.fte_months.toFixed(2)} FTE-months</b> of covered
            work in {data.days} days — about{" "}
            <b className="text-ink">{usd(f.human_cost_equivalent)}</b> at your loaded
            human rate — for <b className="text-ink">{usd(f.spend)}</b> of tokens.
          </div>
          <div className="text-[11px] text-muted mt-1.5">{f.basis}.{" "}
            {f.untyped_tasks > 0 && (
              <>· {f.untyped_tasks} completed task{f.untyped_tasks === 1 ? "" : "s"} carried
                no <code className="text-ink2">X-Task-Type</code> and are excluded from FTE.</>
            )}
          </div>
        </div>
      )}

      {tab === "roster" && (
        <Roster data={data} onOpen={setOpen} />
      )}
      {tab === "plan" && <Planner types={data.task_types} />}
      {tab === "baselines" && (
        <Baselines types={data.task_types} onSaved={refresh} />
      )}

      {open && (
        <Drawer agentId={open} detail={detail} days={days}
          types={data.task_types}
          onClose={() => setOpen(null)}
          onSaved={() => { refresh(); setOpen(null); }} />
      )}
    </div>
  );
}

function Roster({ data, onOpen }: { data: Roster; onOpen: (id: string) => void }) {
  if (data.agents.length === 0) {
    return <div className="card text-sm text-muted">
      No agent identities yet — create one from Tokenomics, or requisition it
      with a role and a budget from the FTE planner.
    </div>;
  }
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] uppercase tracking-wide text-muted">
            <th className="text-left font-medium pb-2">Agent</th>
            <th className="text-left font-medium pb-2">Role</th>
            <th className="text-right font-medium pb-2">Tokens</th>
            <th className="text-right font-medium pb-2">Spend</th>
            <th className="text-right font-medium pb-2"
              title="share of the window's hours in which this agent made at least one call — an agent is never 'busy' like a person, so this is duty cycle, not utilization">
              Duty cycle
            </th>
            <th className="text-right font-medium pb-2"
              title="share of calls served by a non-SLM model — a measured proxy for how hard this agent's work is">
              Escalation
            </th>
            <th className="text-right font-medium pb-2">Tasks</th>
            <th className="text-right font-medium pb-2">$/outcome</th>
            <th className="text-right font-medium pb-2"
              title="delivered vs requisitioned, sustained over a 30-day month">
              FTE
            </th>
            <th className="text-right font-medium pb-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {data.agents.map((a) => (
            <tr key={a.id}
              className="border-t border-edge hover:bg-raised/60 cursor-pointer transition"
              onClick={() => onOpen(a.id)}>
              <td className="py-2.5">
                <div className="text-ink">{a.name}</div>
                <div className="text-[11px] text-muted">{a.team_id}</div>
              </td>
              <td className="py-2.5 text-ink2">
                {a.role_name ?? <span className="text-muted">unassigned</span>}
              </td>
              <td className="py-2.5 text-right tabular-nums text-ink2">
                {a.tokens.toLocaleString()}
                <div className="text-[10px] text-muted">
                  {a.avg_tokens_per_call.toLocaleString()}/call
                </div>
              </td>
              <td className="py-2.5 text-right tabular-nums text-ink2">
                ${a.spend.toFixed(3)}
                {a.budget_pct !== null && (
                  <div className={`text-[10px] ${
                    a.budget_pct >= 100 ? "text-crit"
                      : a.budget_pct >= 80 ? "text-warn" : "text-muted"}`}>
                    {a.budget_pct.toFixed(0)}% of ${a.budget_usd?.toFixed(2)}
                  </div>
                )}
              </td>
              <td className="py-2.5 text-right tabular-nums text-ink2">
                {a.duty_cycle_pct}%
                <div className="text-[10px] text-muted">{a.active_hours}h active</div>
              </td>
              <td className="py-2.5 text-right tabular-nums text-ink2">
                {a.escalation_pct}%
              </td>
              <td className="py-2.5 text-right tabular-nums text-ink2">
                {a.tasks_completed}
                <div className="text-[10px] text-muted">of {a.tasks_started}</div>
              </td>
              <td className="py-2.5 text-right tabular-nums text-ink2">
                {a.cost_per_outcome === null ? "—" : cents(a.cost_per_outcome)}
              </td>
              <td className="py-2.5 text-right tabular-nums text-ink2">
                {a.fte.fte_sustained.toFixed(2)}
                <div className="text-[10px] text-muted">
                  of {a.expected_fte?.toFixed(2) ?? "—"}
                </div>
              </td>
              <td className="py-2.5 text-right">
                <span className={`chip ${STATUS_CHIP[a.status] ?? ""}`}>{a.status}</span>
                {a.enforcement_hits > 0 && (
                  <div className="text-[10px] text-warn mt-1">
                    {a.enforcement_hits} enforcement
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[11px] text-muted mt-3">
        Click a row for the agent's daily series, its missions and its guardrails.
        FTE columns are estimates built on the effort baselines; every other
        column is measured at the gateway.
      </p>
    </div>
  );
}

function Drawer({ agentId, detail, days, types, onClose, onSaved }: {
  agentId: string; detail: Detail | null; days: number;
  types: TaskType[]; onClose: () => void; onSaved: () => void;
}) {
  const a = detail?.agent;
  const [form, setForm] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!a) return;
    setForm({
      role: a.role ?? "",
      expected_fte: a.expected_fte?.toString() ?? "",
      budget_usd: a.budget_usd?.toString() ?? "",
      rate_limit_tpm: a.rate_limit_tpm?.toString() ?? "",
      allowed_tiers: a.allowed_tiers ?? "",
      max_delegation_depth: a.max_delegation_depth?.toString() ?? "",
    });
  }, [a?.id]);

  const save = async (extra: Record<string, unknown> = {}) => {
    const body: Record<string, unknown> = { ...extra };
    if (form.role) body.role = form.role;
    if (form.expected_fte) body.expected_fte = Number(form.expected_fte);
    if (form.budget_usd) body.budget_usd = Number(form.budget_usd);
    if (form.rate_limit_tpm) body.rate_limit_tpm = Number(form.rate_limit_tpm);
    if (form.allowed_tiers) body.allowed_tiers = form.allowed_tiers;
    if (form.max_delegation_depth)
      body.max_delegation_depth = Number(form.max_delegation_depth);
    await fetch(`/api/workforce/agents/${agentId}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    onSaved();
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50" onClick={onClose}>
      <div className="w-full max-w-xl h-full overflow-y-auto bg-surface border-l border-edge p-5"
        onClick={(e) => e.stopPropagation()}>
        {!detail || !a ? <Spinner /> : (
          <>
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <div className="text-lg font-medium">{a.name}</div>
                <div className="text-xs text-muted">
                  {a.team_id} · {a.role_name ?? "unassigned"} ·{" "}
                  {a.last_active ? `last active ${a.last_active.slice(0, 16).replace("T", " ")}`
                    : "never active"}
                </div>
              </div>
              <button className="btn-ghost !py-1 !px-2.5 !text-xs" onClick={onClose}>
                close
              </button>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs mb-4">
              {[["calls", a.calls.toLocaleString()],
                ["tokens in / out", `${a.tokens_in.toLocaleString()} / ${a.tokens_out.toLocaleString()}`],
                ["spend", `$${a.spend.toFixed(4)}`],
                ["cost per outcome", a.cost_per_outcome === null ? "—" : cents(a.cost_per_outcome)],
                ["latency p50 / p95", `${a.p50_ms} / ${a.p95_ms} ms`],
                ["duty cycle", `${a.duty_cycle_pct}% (${a.active_hours}h)`],
                ["escalation", `${a.escalation_pct}%`],
                ["FTE delivered", `${a.fte.fte_sustained.toFixed(2)} of ${a.expected_fte?.toFixed(2) ?? "—"}`],
              ].map(([k, v]) => (
                <div key={k} className="border border-edge rounded-lg px-2.5 py-2">
                  <div className="text-[10px] uppercase tracking-wide text-muted">{k}</div>
                  <div className="text-ink2 tabular-nums mt-0.5">{v}</div>
                </div>
              ))}
            </div>

            {detail.series.length > 1 && (
              <div className="card mb-4">
                <div className="flex items-center justify-between text-xs mb-2">
                  <span className="text-muted">tokens · {days}d</span>
                  <Sparkline values={detail.series.map((s) => s.tokens)} />
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted">spend · {days}d</span>
                  <Sparkline values={detail.series.map((s) => s.spend)} color="#d95926" />
                </div>
              </div>
            )}

            {a.top_models.length > 0 && (
              <div className="mb-4">
                <div className="text-xs text-muted mb-1.5">Model mix</div>
                <div className="flex flex-wrap gap-1.5">
                  {a.top_models.map((m) => (
                    <span key={m.model_id} className="chip">
                      {m.model_id} · {m.calls}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="text-xs text-muted mb-1.5">Guardrails — this agent only</div>
            <div className="card mb-4 space-y-2">
              <label className="block text-[11px] text-muted">
                Role (task type)
                <select className="input mt-1" value={form.role ?? ""}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}>
                  <option value="">unassigned</option>
                  {types.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              </label>
              <div className="grid grid-cols-2 gap-2">
                {([["expected_fte", "Requisitioned FTE"],
                   ["budget_usd", "Monthly budget ($)"],
                   ["rate_limit_tpm", "Rate limit (tokens/min)"],
                   ["max_delegation_depth", "Max delegation depth"],
                   ["allowed_tiers", "Allowed tiers (slm,mid,large)"]] as const).map(
                  ([k, label]) => (
                    <label key={k} className="block text-[11px] text-muted">
                      {label}
                      <input className="input mt-1" value={form[k] ?? ""}
                        onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                    </label>
                  ))}
              </div>
              <div className="flex items-center gap-2 pt-1">
                <button className="btn !text-xs" onClick={() => save()}>Save</button>
                <button className="btn-ghost !text-xs"
                  title={a.enabled
                    ? "pause this key — calls are refused until it is resumed"
                    : "resume this agent"}
                  onClick={() => save({ enabled: !a.enabled })}>
                  {a.enabled ? "Pause agent" : "Resume agent"}
                </button>
              </div>
              <p className="text-[11px] text-muted">
                Past 100% of its budget the agent degrades to the smallest capable
                model rather than failing — it keeps working, cheaply.
              </p>
            </div>

            {detail.missions.length > 0 && (
              <>
                <div className="text-xs text-muted mb-1.5">
                  Recent missions ({detail.missions.length})
                </div>
                <div className="card mb-4 max-h-56 overflow-y-auto text-xs">
                  {detail.missions.map((m) => (
                    <div key={m.id}
                      className="flex items-center justify-between gap-2 py-1 border-b border-edge last:border-0">
                      <span className="text-ink2 truncate">{m.id}</span>
                      <span className="text-muted shrink-0">
                        {m.task_type ?? "untyped"} · ${m.spend_usd.toFixed(4)}
                        {m.budget_usd ? ` / $${m.budget_usd.toFixed(2)}` : ""}
                        {" "}
                        <span className={m.completed ? "text-good" : "text-muted"}>
                          {m.completed ? "done" : "open"}
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {detail.enforcement.length > 0 && (
              <>
                <div className="text-xs text-muted mb-1.5">Enforcement</div>
                <div className="card text-xs space-y-1">
                  {detail.enforcement.map((e, i) => (
                    <div key={i} className="flex gap-2">
                      <span className="chip border-warn/40 text-warn shrink-0">{e.action}</span>
                      <span className="text-ink2">{e.detail}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Planner({ types }: { types: TaskType[] }) {
  const [taskType, setTaskType] = useState(types[0]?.id ?? "");
  const [mode, setMode] = useState<"fte" | "work">("fte");
  const [value, setValue] = useState("3");
  const [months, setMonths] = useState("6");
  const [coverage, setCoverage] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const run = async () => {
    setBusy(true); setErr(""); setPlan(null);
    const body: Record<string, unknown> = {
      task_type: taskType, months: Number(months) || 6,
    };
    if (mode === "fte") body.target_fte = Number(value) || 1;
    else body.tasks_per_month = Number(value) || 100;
    if (coverage) body.coverage_pct = Number(coverage);
    const r = await fetch("/api/workforce/plan", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    setBusy(false);
    if (!r.ok) { setErr(d.detail ?? "plan failed"); return; }
    setPlan(d);
  };

  return (
    <div className="grid gap-3 lg:grid-cols-[340px_minmax(0,1fr)]">
      <div className="card min-w-0">
        <div className="text-sm font-medium mb-1">Size an agent for a project</div>
        <p className="text-[11px] text-muted mb-3">
          Give it the headcount or the work — it returns the other, priced from
          this install's own token shapes, plus the budgets that turn the plan
          into enforcement.
        </p>
        <label className="block text-[11px] text-muted mb-2">
          Work type
          <select className="input mt-1" value={taskType}
            onChange={(e) => setTaskType(e.target.value)}>
            {types.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} · {t.human_minutes}min · {t.coverage_pct}% covered
              </option>
            ))}
          </select>
        </label>
        <div className="flex rounded-lg border border-edge overflow-hidden mb-2">
          {([["fte", "I need N FTE"], ["work", "I have N tasks/month"]] as const)
            .map(([k, label]) => (
              <button key={k} onClick={() => setMode(k)}
                className={`flex-1 px-2 py-1.5 text-[11px] transition ${
                  mode === k ? "bg-raised text-ink" : "text-muted hover:text-ink2"}`}>
                {label}
              </button>
            ))}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="block text-[11px] text-muted">
            {mode === "fte" ? "FTE needed" : "Tasks per month"}
            <input className="input mt-1" value={value}
              onChange={(e) => setValue(e.target.value)} />
          </label>
          <label className="block text-[11px] text-muted">
            Months
            <input className="input mt-1" value={months}
              onChange={(e) => setMonths(e.target.value)} />
          </label>
        </div>
        <label className="block text-[11px] text-muted mt-2">
          Coverage override (%) — how much of the task the agent really does
          <input className="input mt-1" placeholder="use the baseline"
            value={coverage} onChange={(e) => setCoverage(e.target.value)} />
        </label>
        <button className="btn !text-xs w-full mt-3" onClick={run} disabled={busy}>
          {busy ? "Planning…" : "Plan capacity"}
        </button>
        {err && <div className="text-xs text-crit mt-2">{err}</div>}
      </div>

      <div className="min-w-0">
        {!plan ? (
          <div className="card text-sm text-muted h-full flex items-center justify-center">
            The plan appears here — capacity, cost per option, the human
            comparison and the budgets to enforce it.
          </div>
        ) : (
          <div className="space-y-3">
            <div className="card">
              <div className="text-sm">
                <b className="text-ink">{plan.tasks_per_month.toLocaleString()}</b>{" "}
                {plan.task_type.name.toLowerCase()} tasks a month ={" "}
                <b className="text-ink">{plan.fte_covered.toFixed(2)} FTE</b> of covered
                work ({plan.tasks_per_fte_month.toLocaleString()} tasks per FTE-month at{" "}
                {plan.task_type.human_minutes} min and {plan.task_type.coverage_pct}%
                coverage).
              </div>
              <div className="text-[11px] text-muted mt-1.5">
                Token shape: {plan.shape.tokens_per_task.toLocaleString()} tokens/task
                {" "}({plan.shape.basis}
                {plan.shape.basis === "measured"
                  ? `, ${plan.shape.samples} completed tasks`
                  : `, only ${plan.shape.samples} completed tasks of this type so far`}).
              </div>
            </div>

            <div className="card overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[11px] uppercase tracking-wide text-muted">
                    <th className="text-left font-medium pb-2">Serving option</th>
                    <th className="text-right font-medium pb-2">$/task</th>
                    <th className="text-right font-medium pb-2">Monthly</th>
                    <th className="text-right font-medium pb-2">
                      {plan.months} months
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {plan.options.map((o) => (
                    <tr key={o.option} className="border-t border-edge">
                      <td className="py-2">
                        <div className={o.option === plan.recommended ? "text-ink" : "text-ink2"}>
                          {o.option}
                          {o.option === plan.recommended && (
                            <span className="chip !ml-2 !py-0 !text-[10px] border-s1/50 text-s1">
                              plan on this
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] text-muted">{o.note}</div>
                      </td>
                      <td className="py-2 text-right tabular-nums text-ink2">
                        ${o.cost_per_task.toFixed(5)}
                      </td>
                      <td className="py-2 text-right tabular-nums text-ink2">
                        {usd(o.monthly_usd)}
                      </td>
                      <td className="py-2 text-right tabular-nums text-ink2">
                        {usd(o.total_usd)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-[11px] text-muted mt-2">
                {plan.cheapest === plan.recommended
                  ? "The planned option is also the cheapest here — the model mix your traffic already uses."
                  : `Cheapest is "${plan.cheapest}", but cheapest is a floor, not a recommendation: `
                    + "committing a project to a smaller model is a quality claim, and quality is never simulated here."}
              </p>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div className="card">
                <div className="text-xs uppercase tracking-wide text-muted">
                  Human equivalent
                </div>
                <div className="text-2xl font-semibold mt-2">
                  {usd(plan.human_equivalent.monthly_usd)}<span className="text-sm text-muted">/mo</span>
                </div>
                <div className="text-xs text-ink2 mt-1">
                  {plan.human_equivalent.fte.toFixed(2)} FTE ·{" "}
                  {usd(plan.human_equivalent.total_usd)} over {plan.months} months
                </div>
                <div className="text-[11px] text-good mt-1.5">
                  ≈ {usd(plan.human_equivalent.savings_monthly_usd)}/mo difference vs
                  the planned agent option
                </div>
                <div className="text-[10px] text-muted mt-1">
                  {plan.human_equivalent.basis}
                </div>
              </div>
              <div className="card">
                <div className="text-xs uppercase tracking-wide text-muted">
                  Make it enforceable
                </div>
                <div className="text-sm mt-2 space-y-1">
                  <div>Agent monthly budget:{" "}
                    <b className="text-ink tabular-nums">
                      ${plan.enforce.agent_budget_usd.toFixed(2)}
                    </b>
                  </div>
                  <div>Mission budget per task:{" "}
                    <b className="text-ink tabular-nums">
                      ${plan.enforce.task_budget_usd.toFixed(4)}
                    </b>
                    <span className="text-[11px] text-muted"> (X-Task-Budget)</span>
                  </div>
                </div>
                <div className="text-[10px] text-muted mt-2">{plan.enforce.note}</div>
              </div>
            </div>

            <div className="card">
              <div className="text-xs uppercase tracking-wide text-muted mb-1.5">
                Read this before you commit the plan
              </div>
              <ul className="text-[11px] text-muted space-y-1 list-disc pl-4">
                {plan.caveats.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Baselines({ types, onSaved }: { types: TaskType[]; onSaved: () => void }) {
  const [draft, setDraft] = useState<Record<string, { m: string; c: string }>>(
    Object.fromEntries(types.map((t) => [
      t.id, { m: String(t.human_minutes), c: String(t.coverage_pct) }])));
  const [saved, setSaved] = useState("");

  const save = async (t: TaskType) => {
    const d = draft[t.id];
    await fetch(`/api/workforce/task-types/${t.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        human_minutes: Number(d.m), coverage_pct: Number(d.c) }),
    });
    setSaved(t.id);
    setTimeout(() => setSaved(""), 1500);
    onSaved();
  };

  return (
    <div className="card">
      <div className="text-sm font-medium">Human-effort baselines</div>
      <p className="text-[11px] text-muted mb-3 max-w-3xl">
        These two numbers are the whole bridge between tokens and FTE, and they
        are yours, not ours: how long the task takes a person, and how much of it
        an agent genuinely does end-to-end. Draft-then-human-review is not 100%
        coverage — say so here and every FTE figure in the product follows.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-wide text-muted">
              <th className="text-left font-medium pb-2">Work type</th>
              <th className="text-right font-medium pb-2">Human minutes/task</th>
              <th className="text-right font-medium pb-2">Agent coverage %</th>
              <th className="text-right font-medium pb-2">Tasks per FTE-month</th>
              <th className="text-right font-medium pb-2"></th>
            </tr>
          </thead>
          <tbody>
            {types.map((t) => {
              const d = draft[t.id] ?? { m: String(t.human_minutes), c: String(t.coverage_pct) };
              const per = Math.round(
                (160 * 60) / (Number(d.m) * (Number(d.c) / 100) || 1));
              return (
                <tr key={t.id} className="border-t border-edge">
                  <td className="py-2">
                    <div className="text-ink">{t.name}</div>
                    <div className="text-[10px] text-muted">{t.id}</div>
                  </td>
                  <td className="py-2 text-right">
                    <input className="input !w-24 text-right" value={d.m}
                      onChange={(e) => setDraft({ ...draft, [t.id]: { ...d, m: e.target.value } })} />
                  </td>
                  <td className="py-2 text-right">
                    <input className="input !w-24 text-right" value={d.c}
                      onChange={(e) => setDraft({ ...draft, [t.id]: { ...d, c: e.target.value } })} />
                  </td>
                  <td className="py-2 text-right tabular-nums text-ink2">
                    {per.toLocaleString()}
                  </td>
                  <td className="py-2 text-right">
                    <button className="btn-ghost !py-1 !px-2.5 !text-xs"
                      onClick={() => save(t)}>
                      {saved === t.id ? "saved" : "save"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-muted mt-3">
        Tasks per FTE-month assumes the configured working month (Settings →
        working hours per FTE-month). Agents declare their work type with the{" "}
        <code className="text-ink2">X-Task-Type</code> header, or inherit it from
        their assigned role.
      </p>
    </div>
  );
}
