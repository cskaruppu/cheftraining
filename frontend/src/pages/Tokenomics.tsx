import { useEffect, useState } from "react";
import { fmtCompact, fmtMoney } from "../lib/api";
import { PageHeader, Spinner, StatTile } from "../components/ui";

interface TeamView {
  id: string;
  name: string;
  policy: string;
  budget_usd: number;
  api_key: string;
  enabled: boolean;
  rate_limit_tpm: number | null;
  allowed_tiers: string | null;
  max_input_tokens: number | null;
  tokens: number;
  top_model: string;
  spend: number;
  pct: number;
  state: string;
}

interface RouterPolicy {
  requests: number;
  small_requests: number;
  small_share_pct: number;
  actual_usd: number;
  strong_usd: number;
  saved_usd: number;
}

interface RouterSummary {
  window_days: number;
  vs_model: string;
  provenance: string;
  policies: Record<string, RouterPolicy>;
}

const POLICY_LABEL: Record<string, string> = {
  route: "route — classified before sending",
  cascade: "cascade — SLM-first, escalates",
  auto: "auto — recommender routed",
};

interface AgentRow {
  id: string;
  name: string;
  team_id: string;
  api_key: string;
  calls: number;
  tokens: number;
  spend: number;
  tasks: number;
  tasks_completed: number;
  cost_per_outcome: number | null;
}

interface Overview {
  kpis: {
    tokens_30d: number;
    blended_per_1m: number;
    spend_30d: number;
    budget_health: { ok: number; warn: number; degraded: number };
    carbon_kg: number;
  };
  teams: TeamView[];
  statement: { source: string; private: boolean; tokens: number; cost: number; per_1m: number }[];
  enforcement_log: { ts: string; team_id: string; action: string; detail: string }[];
  anomalies: { team_id: string; ratio: number; detail: string }[];
}

const STATE_CHIP: Record<string, { cls: string; label: (t: TeamView) => string }> = {
  ok: { cls: "border-good/50 text-good", label: () => "ok" },
  warn: { cls: "border-warn/50 text-warn", label: (t) => `${t.pct.toFixed(0)}% — alerted` },
  degraded: { cls: "border-crit/50 text-crit", label: () => "degraded → SLM" },
  over: { cls: "border-crit/50 text-crit", label: (t) => `${t.pct.toFixed(0)}% — over` },
};

export default function Tokenomics() {
  const [data, setData] = useState<Overview | null>(null);
  const [routing, setRouting] = useState<RouterSummary | null>(null);
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [copied, setCopied] = useState("");

  const refresh = () => {
    fetch("/api/tokenomics").then((r) => r.json()).then(setData);
    fetch("/api/router/summary").then((r) => r.json()).then(setRouting);
    fetch("/api/tokenomics/agents").then((r) => r.json())
      .then((d) => setAgents(d.agents ?? [])).catch(() => {});
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8000);
    return () => clearInterval(t);
  }, []);

  if (!data) return <Spinner />;
  const { kpis } = data;

  const copyKey = (t: TeamView) => {
    navigator.clipboard?.writeText(t.api_key);
    setCopied(t.id);
    setTimeout(() => setCopied(""), 1500);
  };

  const togglePause = async (t: TeamView) => {
    await fetch(`/api/teams/${t.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !t.enabled }),
    });
    refresh();
  };

  return (
    <div>
      <PageHeader
        title="Tokenomics"
        sub="Token metering, budgets and enforcement across your whole estate — API models and private GPUs in one statement. Others report tokenomics; Modelect enforces it."
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatTile label="Tokens · 30d" value={fmtCompact(kpis.tokens_30d)}
          hint={`${fmtMoney(kpis.spend_30d)} total spend`} />
        <StatTile label="True blended cost" value={<>{fmtMoney(kpis.blended_per_1m)}<span className="text-xs text-muted font-normal">/1M</span></>}
          hint="API + private, measured" />
        <StatTile label="Budget health"
          value={<span className="text-lg">
            <span className="text-good">{kpis.budget_health.ok} ok</span>
            {" · "}<span className="text-warn">{kpis.budget_health.warn} warn</span>
            {" · "}<span className="text-crit">{kpis.budget_health.degraded} degraded</span>
          </span>}
          hint="policies enforced at the gateway" />
        <StatTile label="Est. carbon" value={`${kpis.carbon_kg} kg`}
          hint="CO2e from token telemetry" />
      </div>

      <div className="grid lg:grid-cols-[1.5fr_1fr] gap-4">
        <div className="space-y-4 min-w-0">
          <div className="card">
            <h2 className="text-sm font-medium mb-3">Team budgets &amp; enforcement</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted border-b border-edge">
                    <th className="py-2 pr-4 font-normal">Team</th>
                    <th className="py-2 pr-4 font-normal text-right">Tokens · 30d</th>
                    <th className="py-2 pr-4 font-normal text-right">Spend / budget</th>
                    <th className="py-2 pr-4 font-normal w-40"></th>
                    <th className="py-2 pr-4 font-normal">Status</th>
                    <th className="py-2 pr-4 font-normal">Top model</th>
                    <th className="py-2 font-normal">Key</th>
                  </tr>
                </thead>
                <tbody>
                  {data.teams.map((t) => {
                    const chip = STATE_CHIP[t.state] ?? STATE_CHIP.ok;
                    const barColor = t.pct >= 90 ? "#d03b3b" : t.pct >= 70 ? "#fab219" : "#3987e5";
                    const guards = [
                      t.allowed_tiers && `tiers: ${t.allowed_tiers}`,
                      t.rate_limit_tpm && `${(t.rate_limit_tpm / 1000).toFixed(0)}k tpm`,
                      t.max_input_tokens && `max in: ${fmtCompact(t.max_input_tokens)}`,
                    ].filter(Boolean).join(" · ");
                    return (
                      <tr key={t.id} className={`border-b border-edge/50 ${t.enabled ? "" : "opacity-50"}`}>
                        <td className="py-2.5 pr-4">
                          <div className="text-ink">{t.name}</div>
                          {guards && <div className="text-[10px] text-muted mt-0.5">{guards}</div>}
                        </td>
                        <td className="py-2.5 pr-4 text-right text-ink2 tabular-nums">{fmtCompact(t.tokens)}</td>
                        <td className="py-2.5 pr-4 text-right text-ink2 tabular-nums">
                          {fmtMoney(t.spend)} / {fmtMoney(t.budget_usd)}
                        </td>
                        <td className="py-2.5 pr-4">
                          <div className="h-1.5 rounded-full bg-grid overflow-hidden">
                            <div className="h-full rounded-full"
                              style={{ width: `${Math.min(100, t.pct)}%`, background: barColor }} />
                          </div>
                        </td>
                        <td className="py-2.5 pr-4">
                          {t.enabled ? (
                            <span className={`chip ${chip.cls}`}>{chip.label(t)}</span>
                          ) : (
                            <span className="chip">⏸ paused</span>
                          )}
                        </td>
                        <td className="py-2.5 pr-4 text-ink2">{t.top_model}</td>
                        <td className="py-2.5">
                          <div className="flex items-center gap-1.5">
                            <button className="chip hover:!text-ink transition"
                              title="copy this team's API key — use it as the Bearer token to see attribution and enforcement live"
                              onClick={() => copyKey(t)}>
                              {copied === t.id ? "copied ✓" : `${t.api_key.slice(0, 7)}…`}
                            </button>
                            <button className="chip hover:!text-ink transition"
                              title={t.enabled ? "kill switch: pause this key immediately" : "re-enable this key"}
                              onClick={() => togglePause(t)}>
                              {t.enabled ? "pause" : "resume"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {data.enforcement_log.length > 0 && (
              <pre className="mt-4 bg-page border border-edge rounded-lg px-3 py-2.5 text-[11.5px] leading-relaxed text-muted overflow-x-auto font-mono">
                {data.enforcement_log.map((l) =>
                  `${l.ts.slice(5, 16).replace("T", " ")}  ${l.action.padEnd(8)} ${l.team_id} — ${l.detail}`
                ).join("\n")}
              </pre>
            )}
            <p className="text-[11px] text-muted mt-2">
              Policy "degrade": at 100% of budget, requests are served by the smallest capable
              model instead of failing — the receipt records every enforcement.
            </p>
          </div>

          <div className="card">
            <div className="flex items-center justify-between mb-1.5">
              <h2 className="text-sm font-medium">Agentic spend — team → agent</h2>
              <span className="chip !text-[10px] border-s1/50 text-s1">agentic era</span>
            </div>
            <p className="text-[11px] text-muted mb-3">
              Agents spend at machine speed, so attribution goes one level deeper than teams:
              each agent has its own key (<code>ak-…</code>), mission budgets bound a task's
              spend (<code>X-Task-Id</code> + <code>X-Task-Budget</code> headers — degrade at
              100%, stop at 150%), and cost per <i>completed task</i> prices the work in
              outcomes, not tokens.
            </p>
            {agents.length === 0 ? (
              <p className="text-sm text-muted">No agents yet — create one per team via the API.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted border-b border-edge">
                      <th className="py-1.5 pr-3 font-normal">Agent</th>
                      <th className="py-1.5 pr-3 font-normal text-right">Calls</th>
                      <th className="py-1.5 pr-3 font-normal text-right">Tokens</th>
                      <th className="py-1.5 pr-3 font-normal text-right">Spend</th>
                      <th className="py-1.5 pr-3 font-normal text-right">Tasks ✓</th>
                      <th className="py-1.5 pr-3 font-normal text-right">$/outcome</th>
                      <th className="py-1.5 font-normal">Key</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.map((a) => (
                      <tr key={a.id} className="border-b border-edge/50">
                        <td className="py-2 pr-3">
                          <div className="text-ink">{a.name}</div>
                          <div className="text-[10px] text-muted">team: {a.team_id}</div>
                        </td>
                        <td className="py-2 pr-3 text-right text-ink2 tabular-nums">{fmtCompact(a.calls)}</td>
                        <td className="py-2 pr-3 text-right text-ink2 tabular-nums">{fmtCompact(a.tokens)}</td>
                        <td className="py-2 pr-3 text-right text-ink2 tabular-nums">{fmtMoney(a.spend)}</td>
                        <td className="py-2 pr-3 text-right text-ink2 tabular-nums">
                          {a.tasks_completed}/{a.tasks}
                        </td>
                        <td className="py-2 pr-3 text-right text-ink2 tabular-nums">
                          {a.cost_per_outcome != null ? fmtMoney(a.cost_per_outcome) : "—"}
                        </td>
                        <td className="py-2">
                          <button className="chip hover:!text-ink transition"
                            title="copy this agent's key — spend under it is attributed to the agent, within the team's budget and guardrails"
                            onClick={() => {
                              navigator.clipboard?.writeText(a.api_key);
                              setCopied(a.id);
                              setTimeout(() => setCopied(""), 1500);
                            }}>
                            {copied === a.id ? "copied ✓" : `${a.api_key.slice(0, 6)}…`}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="text-[11px] text-muted mt-2">
              Loop-breaker: set a team's <code>loop_policy</code> to "degrade" and anomalous
              output volume is auto-contained on the smallest capable model — receipted, logged
              as LOOPBREAK, no outage. <code>X-Delegation-Depth</code> beyond the team maximum
              is refused (the agentic fork-bomb brake).
            </p>
          </div>
        </div>

        <div className="space-y-4 min-w-0">
          <div className="card">
            <h2 className="text-sm font-medium mb-3">Hybrid statement · 30d</h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-edge">
                  <th className="py-1.5 pr-3 font-normal">Source</th>
                  <th className="py-1.5 pr-3 font-normal text-right">Tokens</th>
                  <th className="py-1.5 pr-3 font-normal text-right">Cost</th>
                  <th className="py-1.5 font-normal text-right">$/1M</th>
                </tr>
              </thead>
              <tbody>
                {data.statement.map((s) => (
                  <tr key={s.source} className="border-b border-edge/50">
                    <td className="py-2 pr-3 text-ink2">
                      {s.source}
                      {s.private && (
                        <span className="chip !ml-1.5 !py-0 !px-1.5 !text-[10px] border-s1/50 text-s1">GPU</span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-right text-ink2 tabular-nums">{fmtCompact(s.tokens)}</td>
                    <td className="py-2 pr-3 text-right text-ink2 tabular-nums">{fmtMoney(s.cost)}</td>
                    <td className="py-2 text-right text-ink2 tabular-nums">${s.per_1m.toFixed(2)}</td>
                  </tr>
                ))}
                <tr>
                  <td className="py-2 pr-3 font-medium text-ink">Total</td>
                  <td className="py-2 pr-3 text-right font-medium text-ink tabular-nums">{fmtCompact(kpis.tokens_30d)}</td>
                  <td className="py-2 pr-3 text-right font-medium text-ink tabular-nums">{fmtMoney(kpis.spend_30d)}</td>
                  <td className="py-2 text-right font-medium text-ink tabular-nums">${kpis.blended_per_1m.toFixed(2)}</td>
                </tr>
              </tbody>
            </table>
            <p className="text-[11px] text-muted mt-2">
              One statement across API providers and private GPU-hosted models — the number
              observability-only tools can't produce.
            </p>
          </div>

          <div className="card">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-medium">Routing savings · {routing?.window_days ?? 14}d</h2>
              <span className="chip !text-[10px] border-good/50 text-good">measured, not promised</span>
            </div>
            {!routing || Object.keys(routing.policies).length === 0 ? (
              <p className="text-sm text-muted">
                No routed traffic yet — send gateway requests with{" "}
                <code className="text-ink2">model: "route"</code>,{" "}
                <code className="text-ink2">"cascade"</code> or <code className="text-ink2">"auto"</code>.
              </p>
            ) : (
              <div className="space-y-2.5">
                {Object.entries(routing.policies).map(([name, p]) => (
                  <div key={name} className="border border-edge rounded-lg px-3 py-2.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-ink">{POLICY_LABEL[name] ?? name}</span>
                      <span className="text-good font-medium tabular-nums">
                        {fmtMoney(p.saved_usd)} saved
                      </span>
                    </div>
                    <div className="mt-2 h-1.5 rounded-full bg-grid overflow-hidden">
                      <div className="h-full rounded-full bg-s3"
                        style={{ width: `${Math.min(100, p.small_share_pct)}%` }} />
                    </div>
                    <div className="mt-1.5 text-[10px] text-muted">
                      {p.requests} requests · {p.small_share_pct.toFixed(0)}% served by a small
                      model · {fmtMoney(p.actual_usd)} actual vs {fmtMoney(p.strong_usd)} if all
                      went to {routing.vs_model}
                    </div>
                  </div>
                ))}
              </div>
            )}
            <p className="text-[11px] text-muted mt-3">
              Computed from recorded traffic: each routed request's actual cost against what the
              strongest model would have charged for the same token shape.
            </p>
          </div>

          <div className="card">
            <h2 className="text-sm font-medium mb-3">Anomalies</h2>
            {data.anomalies.length === 0 ? (
              <p className="text-sm text-muted">No anomalies in the last 24h.</p>
            ) : (
              <div className="space-y-2">
                {data.anomalies.map((a) => (
                  <div key={a.team_id}
                    className="border-l-2 border-crit rounded-r-lg bg-raised px-3 py-2.5 text-xs">
                    <span className="text-crit font-medium">{a.team_id}</span>{" "}
                    <span className="text-ink2">— {a.detail}</span>
                  </div>
                ))}
              </div>
            )}
            <p className="text-[11px] text-muted mt-3">
              Detected from token telemetry: each team's recent output volume vs its own
              baseline. Loops and leaked keys change token shapes before they show up anywhere else.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
