import { useEffect, useState } from "react";
import { fmtCompact, fmtMoney } from "../lib/api";
import { PageHeader, Spinner, StatTile } from "../components/ui";

interface TeamView {
  id: string;
  name: string;
  policy: string;
  budget_usd: number;
  api_key: string;
  tokens: number;
  top_model: string;
  spend: number;
  pct: number;
  state: string;
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
  const [copied, setCopied] = useState("");

  const refresh = () =>
    fetch("/api/tokenomics").then((r) => r.json()).then(setData);

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
        <div className="space-y-4">
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
                    return (
                      <tr key={t.id} className="border-b border-edge/50">
                        <td className="py-2.5 pr-4 text-ink">{t.name}</td>
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
                          <span className={`chip ${chip.cls}`}>{chip.label(t)}</span>
                        </td>
                        <td className="py-2.5 pr-4 text-ink2">{t.top_model}</td>
                        <td className="py-2.5">
                          <button className="chip hover:!text-ink transition"
                            title="copy this team's API key — use it as the Bearer token to see attribution and enforcement live"
                            onClick={() => copyKey(t)}>
                            {copied === t.id ? "copied ✓" : `${t.api_key.slice(0, 7)}…`}
                          </button>
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
        </div>

        <div className="space-y-4">
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
