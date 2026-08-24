import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AnalyticsSummary, api, fmtCompact, fmtMoney } from "../lib/api";
import { PageHeader, Sparkline, Spinner, StatTile, tooltipStyle } from "../components/ui";

const RANGES = [
  { days: 1, label: "24h" },
  { days: 7, label: "7d" },
  { days: 14, label: "14d" },
  { days: 30, label: "30d" },
];

interface RouterSummary {
  vs_model: string;
  policies: Record<string, { requests: number; small_requests: number; saved_usd: number }>;
}

interface TokenomicsOverview {
  enforcement_log: { ts: string; action: string }[];
  anomalies: unknown[];
}

interface ClusterRow {
  source: string;
  gpu_class: string;
  agent_status: string;
}

interface AdminOps {
  attention: { severity: "crit" | "warn" | "info"; kind: string; title: string; detail: string; link: string }[];
  runway_days: number | null;
  counterfactual: {
    direct_requests: number; direct_cost: number; est_routed_cost: number;
    est_savings: number; small_share_pct: number; basis: string;
  } | null;
  router_health: {
    trend: { day: string; escalation_pct: number; requests: number }[];
    escalation_pct: number; drift_pct: number | null;
  };
  prompt_bloat: { trend: { day: string; avg_tokens_in: number }[]; change_pct: number | null };
  concentration: { provider: string; share_pct: number; providers_used: number; alternatives: number } | null;
}

const SEV_DOT: Record<string, string> = {
  crit: "bg-crit", warn: "bg-warn", info: "bg-s1",
};

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="h-[220px] grid place-items-center text-center">
      <div>
        <div className="text-sm text-muted">{label}</div>
        <div className="text-[11px] text-muted mt-1.5">
          Send a request through the gateway or the Playground to start the clock.
        </div>
      </div>
    </div>
  );
}

function SignatureCard({ title, to, chip, children }: {
  title: string; to: string; chip?: string; children: React.ReactNode;
}) {
  return (
    <Link to={to} className="card block hover:border-s1/40 transition-colors group">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="text-[10px] uppercase tracking-[0.12em] text-muted group-hover:text-ink2 transition-colors">
          {title}
        </div>
        {chip && <span className="chip !py-0 !px-1.5 !text-[9px] border-good/50 text-good shrink-0">{chip}</span>}
      </div>
      {children}
    </Link>
  );
}

export default function Dashboard() {
  const [days, setDays] = useState(14);
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [routing, setRouting] = useState<RouterSummary | null>(null);
  const [gov, setGov] = useState<TokenomicsOverview | null>(null);
  const [fleet, setFleet] = useState<ClusterRow[] | null>(null);
  const [ops, setOps] = useState<AdminOps | null>(null);
  const [demoSeed, setDemoSeed] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    const refresh = () => {
      api.analytics(days)
        .then((d) => {
          setData(d);
          setUpdatedAt(new Date());
        })
        .catch((e) => setErr(String(e)));
      fetch(`/api/router/summary?days=${days}`).then((r) => r.json()).then(setRouting).catch(() => {});
      fetch("/api/tokenomics").then((r) => r.json()).then(setGov).catch(() => {});
      fetch("/api/clusters").then((r) => r.json()).then((c) => setFleet(c.clusters ?? [])).catch(() => {});
      fetch(`/api/dashboard/admin?days=${days}`).then((r) => r.json()).then(setOps).catch(() => {});
    };
    refresh();
    fetch("/api/system").then((r) => r.json()).then((s) => setDemoSeed(s.demo_seed)).catch(() => {});
    const t = setInterval(refresh, 10_000);
    return () => clearInterval(t);
  }, [days]);

  if (err) return <div className="text-crit text-sm">API error: {err}</div>;
  if (!data) return <Spinner />;

  const { kpis, series } = data;
  const rangeLabel = RANGES.find((r) => r.days === days)?.label ?? `${days}d`;
  const byModel = data.by_model.slice(0, 6);
  const empty = kpis.requests === 0;

  // signature-row derivations
  const routePolicies = Object.values(routing?.policies ?? {});
  const routedReqs = routePolicies.reduce((a, p) => a + p.requests, 0);
  const routedSmall = routePolicies.reduce((a, p) => a + p.small_requests, 0);
  const routedSaved = routePolicies.reduce((a, p) => a + p.saved_usd, 0);
  const dayAgo = Date.now() - 24 * 3600 * 1000;
  const enf24 = (gov?.enforcement_log ?? []).filter((l) => new Date(l.ts).getTime() >= dayAgo);
  const enfByAction = enf24.reduce<Record<string, number>>((acc, l) => {
    acc[l.action] = (acc[l.action] ?? 0) + 1;
    return acc;
  }, {});
  const anomalies = gov?.anomalies?.length ?? 0;
  const liveAgents = (fleet ?? []).filter((c) => c.source !== "simulated");
  const gpuReady = (fleet ?? []).filter((c) => c.gpu_class === "gpu-ready").length;
  const stale = liveAgents.filter((c) => c.agent_status !== "connected").length;
  const hybridTotal = data.hybrid.api.tokens + data.hybrid.private.tokens;
  const privatePct = hybridTotal ? Math.round((data.hybrid.private.tokens / hybridTotal) * 100) : 0;

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <PageHeader
          title="Dashboard"
          sub={demoSeed
            ? "Live traffic, spend and latency observed through the gateway — real events plus seeded demo history"
            : "Live traffic, spend and latency observed through the gateway — real traffic only"}
        />
        <div className="flex items-center gap-2 mt-1 shrink-0">
          <div className="flex rounded-lg border border-edge overflow-hidden"
            title="time range — every number and chart on this page follows it">
            {RANGES.map((r) => (
              <button key={r.days} onClick={() => { setDays(r.days); setData(null); }}
                className={`px-2.5 py-1 text-[11px] transition-colors ${
                  r.days === days ? "bg-raised text-ink" : "text-muted hover:text-ink2"}`}>
                {r.label}
              </button>
            ))}
          </div>
          <span className="chip !text-[11px]" title="the page re-queries the event store every 10 seconds">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-good mr-1.5 animate-pulse" />
            live · {updatedAt ? updatedAt.toLocaleTimeString() : "…"}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-4">
        <StatTile label={`Requests · ${rangeLabel}`} value={fmtCompact(kpis.requests)}
          delta={kpis.deltas.requests_pct} spark={series.map((s) => s.requests)}
          hint={`${fmtCompact(kpis.tokens_in + kpis.tokens_out)} tokens`} />
        <StatTile label={`Spend · ${rangeLabel}`} value={fmtMoney(kpis.spend)}
          delta={kpis.deltas.spend_pct} goodWhenDown spark={series.map((s) => s.cost)}
          hint={ops?.runway_days != null
            ? `runway ~${Math.round(ops.runway_days)}d at current burn`
            : "across all providers"} />
        <StatTile label="Latency p50 / p95"
          value={<span className="tabular-nums">{kpis.p50_ms}<span className="text-muted text-base"> / </span>{kpis.p95_ms}<span className="text-sm text-muted"> ms</span></span>}
          delta={kpis.deltas.p95_pct} goodWhenDown hint="non-cached, measured" />
        <StatTile label="Success rate" value={`${kpis.success_rate}%`}
          hint={kpis.blocks ? `${kpis.blocks} blocked by guardrails` : "no guardrail blocks"} />
        <StatTile label="Cache hit rate" value={`${kpis.cache_hit_rate}%`}
          hint="semantic cache savings" />
      </div>

      {ops?.counterfactual && ops.counterfactual.est_savings > 0.01 && (
        <Link to="/integrate"
          className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-good/30 bg-good/5 px-4 py-2.5 hover:border-good/60 transition-colors">
          <span className="text-good text-sm font-medium">
            {fmtMoney(ops.counterfactual.est_savings)} left on the table
          </span>
          <span className="text-xs text-ink2">
            your {fmtCompact(ops.counterfactual.direct_requests)} direct requests cost{" "}
            {fmtMoney(ops.counterfactual.direct_cost)}; under <code>model: "route"</code> the same
            token shapes would cost ~{fmtMoney(ops.counterfactual.est_routed_cost)}
          </span>
          <span className="chip !text-[10px] ml-auto shrink-0"
            title={ops.counterfactual.basis}>
            estimate · {ops.counterfactual.small_share_pct.toFixed(0)}% small mix, measured
          </span>
        </Link>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <SignatureCard title="Routing savings" to="/tokenomics" chip="measured">
          <div className="text-lg font-semibold text-good">{fmtMoney(routedSaved)}</div>
          <div className="text-[11px] text-muted mt-0.5">
            {routedReqs
              ? `${routedReqs ? Math.round((routedSmall / routedReqs) * 100) : 0}% of ${fmtCompact(routedReqs)} routed requests served small`
              : "no routed traffic yet — try model: \"route\""}
          </div>
        </SignatureCard>
        <SignatureCard title="Hybrid estate" to="/tokenomics">
          <div className="text-lg font-semibold tabular-nums">
            {privatePct}<span className="text-sm text-muted">% private GPU</span>
          </div>
          <div className="mt-1.5 h-1.5 rounded-full bg-grid overflow-hidden flex">
            <div className="h-full bg-s1" style={{ width: `${100 - privatePct}%` }} />
            <div className="h-full bg-s3" style={{ width: `${privatePct}%` }} />
          </div>
          <div className="text-[11px] text-muted mt-1">
            API {fmtCompact(data.hybrid.api.tokens)} · private {fmtCompact(data.hybrid.private.tokens)} tokens
          </div>
        </SignatureCard>
        <SignatureCard title="Enforcement · 24h" to="/tokenomics">
          <div className="text-lg font-semibold tabular-nums">{enf24.length + anomalies}</div>
          <div className="text-[11px] text-muted mt-0.5">
            {enf24.length + anomalies === 0
              ? "no guardrail actions — all teams within policy"
              : [
                  ...Object.entries(enfByAction).map(([a, n]) => `${n} ${a.toLowerCase()}`),
                  anomalies ? `${anomalies} anomal${anomalies === 1 ? "y" : "ies"}` : "",
                ].filter(Boolean).join(" · ")}
          </div>
        </SignatureCard>
        <SignatureCard title="GPU fleet" to="/clusters">
          <div className="text-lg font-semibold tabular-nums">
            {fleet?.length ?? "…"}<span className="text-sm text-muted"> clusters</span>
          </div>
          <div className="text-[11px] text-muted mt-0.5">
            {fleet
              ? `${gpuReady} gpu-ready · ${liveAgents.length} live agent${liveAgents.length === 1 ? "" : "s"}${stale ? ` · ${stale} stale` : ""}`
              : "loading fleet…"}
          </div>
        </SignatureCard>
      </div>

      <div className="grid lg:grid-cols-[1.5fr_1fr] gap-4 mb-6">
        <div className="card min-w-0">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium">Needs attention</h2>
            {ops && ops.attention.length > 0 && (
              <span className="chip !text-[10px]">
                {ops.attention.filter((i) => i.severity === "crit").length} critical ·{" "}
                {ops.attention.length} total
              </span>
            )}
          </div>
          {!ops ? (
            <div className="text-xs text-muted py-4">loading…</div>
          ) : ops.attention.length === 0 ? (
            <div className="py-6 text-center">
              <div className="text-sm text-good">Nothing needs you — all green.</div>
              <div className="text-[11px] text-muted mt-1">
                Deployments healthy, agents reporting, budgets within policy, no anomalies.
              </div>
            </div>
          ) : (
            <div className="divide-y divide-edge/50">
              {ops.attention.slice(0, 6).map((i, n) => (
                <Link key={n} to={i.link} className="flex items-start gap-2.5 py-2 group">
                  <span className={`mt-1.5 h-2 w-2 rounded-full shrink-0 ${SEV_DOT[i.severity]}`} />
                  <span className="min-w-0">
                    <span className="block text-sm text-ink group-hover:text-s1 transition-colors truncate">
                      {i.title}
                    </span>
                    <span className="block text-[11px] text-muted truncate">{i.detail}</span>
                  </span>
                  <span className="chip !text-[9px] !py-0 ml-auto shrink-0 mt-1">{i.kind}</span>
                </Link>
              ))}
              {ops.attention.length > 6 && (
                <div className="pt-2 text-[11px] text-muted">
                  +{ops.attention.length - 6} more — see the linked pages
                </div>
              )}
            </div>
          )}
        </div>

        <div className="card min-w-0">
          <h2 className="text-sm font-medium mb-3">Router health &amp; efficiency</h2>
          {!ops ? (
            <div className="text-xs text-muted py-4">loading…</div>
          ) : (
            <div className="space-y-3.5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold tabular-nums">
                    {ops.router_health.escalation_pct}
                    <span className="text-sm text-muted">% escalated</span>
                  </div>
                  <div className="text-[11px] text-muted">
                    routed traffic sent to the strong model
                    {ops.router_health.drift_pct != null && (
                      <span className={ops.router_health.drift_pct > 10 ? " text-warn" : ""}>
                        {" "}· drift {ops.router_health.drift_pct > 0 ? "+" : ""}
                        {ops.router_health.drift_pct}pt
                      </span>
                    )}
                  </div>
                </div>
                <Sparkline values={ops.router_health.trend.map((t) => t.escalation_pct)} color="#d95926" />
              </div>
              <div className="flex items-center justify-between gap-3 border-t border-edge/50 pt-3">
                <div>
                  <div className="text-lg font-semibold tabular-nums">
                    {fmtCompact(ops.prompt_bloat.trend[ops.prompt_bloat.trend.length - 1]?.avg_tokens_in ?? 0)}
                    <span className="text-sm text-muted"> avg tokens in</span>
                  </div>
                  <div className="text-[11px] text-muted">
                    prompt size per request
                    {ops.prompt_bloat.change_pct != null && (
                      <span className={ops.prompt_bloat.change_pct > 25 ? " text-warn" : ""}>
                        {" "}· {ops.prompt_bloat.change_pct > 0 ? "+" : ""}
                        {ops.prompt_bloat.change_pct}% over window
                      </span>
                    )}
                  </div>
                </div>
                <Sparkline values={ops.prompt_bloat.trend.map((t) => t.avg_tokens_in)} color="#199e70" />
              </div>
              {ops.concentration && (
                <div className="border-t border-edge/50 pt-3">
                  <div className="text-[11px] text-ink2">
                    <span className={ops.concentration.share_pct > 60 ? "text-warn" : "text-ink"}>
                      {ops.concentration.share_pct.toFixed(0)}%
                    </span>{" "}
                    of traffic on {ops.concentration.provider} · {ops.concentration.providers_used} providers in use
                  </div>
                  <div className="text-[11px] text-muted mt-0.5">
                    {ops.concentration.alternatives} comparable-quality alternatives in the catalog
                    {ops.concentration.share_pct > 60 ? " — failover path available" : ""}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mb-6">
        <div className="card">
          <h2 className="text-sm font-medium mb-4">
            Spend (USD){data.granularity === "hour" ? " · hourly" : " · daily"}
          </h2>
          {empty ? <EmptyChart label={`No traffic in the last ${rangeLabel}`} /> : (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={series} margin={{ top: 4, right: 8, left: -14, bottom: 0 }}>
                <defs>
                  <linearGradient id="spend" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3987e5" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#3987e5" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#2c2c2a" vertical={false} />
                <XAxis dataKey="label" stroke="#898781" fontSize={11} tickLine={false} axisLine={{ stroke: "#383835" }} />
                <YAxis stroke="#898781" fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: "#898781", strokeDasharray: "3 3" }} />
                <Area type="monotone" dataKey="cost" name="Spend" stroke="#3987e5" strokeWidth={2} fill="url(#spend)" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="card">
          <h2 className="text-sm font-medium mb-4">
            Token throughput{data.granularity === "hour" ? " · hourly" : " · daily"}
          </h2>
          {empty ? <EmptyChart label={`No tokens metered in the last ${rangeLabel}`} /> : (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={series} margin={{ top: 4, right: 8, left: -14, bottom: 0 }}>
                <defs>
                  <linearGradient id="tokens" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#199e70" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#199e70" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#2c2c2a" vertical={false} />
                <XAxis dataKey="label" stroke="#898781" fontSize={11} tickLine={false} axisLine={{ stroke: "#383835" }} />
                <YAxis stroke="#898781" fontSize={11} tickLine={false} axisLine={false}
                  tickFormatter={(v: number) => fmtCompact(v)} />
                <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: "#898781", strokeDasharray: "3 3" }}
                  formatter={(v: number) => fmtCompact(v)} />
                <Area type="monotone" dataKey="tokens" name="Tokens" stroke="#199e70" strokeWidth={2} fill="url(#tokens)" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mb-6">
        <div className="card">
          <h2 className="text-sm font-medium mb-4">
            Requests by model · {rangeLabel}
            {data.model_count > 6 && (
              <span className="text-xs text-muted font-normal"> — top 6 of {data.model_count}</span>
            )}
          </h2>
          {empty ? <EmptyChart label="No model traffic yet" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={byModel} layout="vertical" margin={{ top: 0, right: 24, left: 40, bottom: 0 }}>
                <CartesianGrid stroke="#2c2c2a" horizontal={false} />
                <XAxis type="number" stroke="#898781" fontSize={11} tickLine={false} axisLine={{ stroke: "#383835" }} />
                <YAxis type="category" dataKey="model" stroke="#c3c2b7" fontSize={11} width={120} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
                <Bar dataKey="requests" name="Requests" fill="#3987e5" radius={[0, 4, 4, 0]} barSize={14} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="card">
          <h2 className="text-sm font-medium mb-4">Spend by provider · {rangeLabel}</h2>
          {empty ? <EmptyChart label="No spend recorded yet" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data.by_provider.slice(0, 6)} layout="vertical"
                margin={{ top: 0, right: 24, left: 40, bottom: 0 }}>
                <CartesianGrid stroke="#2c2c2a" horizontal={false} />
                <XAxis type="number" stroke="#898781" fontSize={11} tickLine={false}
                  axisLine={{ stroke: "#383835" }} tickFormatter={(v: number) => `$${v}`} />
                <YAxis type="category" dataKey="provider" stroke="#c3c2b7" fontSize={11} width={120} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(255,255,255,0.04)" }}
                  formatter={(v: number) => fmtMoney(v)} />
                <Bar dataKey="cost" name="Spend" fill="#d95926" radius={[0, 4, 4, 0]} barSize={14} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="card">
        <h2 className="text-sm font-medium mb-3">Recent requests</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-edge">
                <th className="py-2 pr-4 font-normal">Time (UTC)</th>
                <th className="py-2 pr-4 font-normal">Model</th>
                <th className="py-2 pr-4 font-normal">Routing</th>
                <th className="py-2 pr-4 font-normal text-right">Tokens in/out</th>
                <th className="py-2 pr-4 font-normal text-right">Latency</th>
                <th className="py-2 pr-4 font-normal text-right">Cost</th>
                <th className="py-2 font-normal">Backend</th>
              </tr>
            </thead>
            <tbody>
              {data.recent.length === 0 && (
                <tr><td colSpan={7} className="py-6 text-center text-muted text-xs">
                  No requests yet — the gateway records every call here with its routing provenance.
                </td></tr>
              )}
              {data.recent.map((r, i) => (
                <tr key={i} className="border-b border-edge/50 text-ink2">
                  <td className="py-2 pr-4 tabular-nums">{r.ts.slice(5, 16).replace("T", " ")}</td>
                  <td className="py-2 pr-4 text-ink">{r.model_name}</td>
                  <td className="py-2 pr-4">
                    {r.policy ? (
                      <span className="chip !py-0 !text-[10px] border-s1/40 text-s1"
                        title={r.policy === "route" ? "classified before sending — smart router"
                          : r.policy === "cascade" ? "SLM-first with escalation"
                          : "recommender-routed"}>
                        {r.policy}
                      </span>
                    ) : (
                      <span className="text-[10px] text-muted">direct</span>
                    )}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums">
                    {fmtCompact(r.tokens_in)} / {fmtCompact(r.tokens_out)}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums">{r.cached ? "—" : `${r.latency_ms} ms`}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">{r.cached ? "$0" : fmtMoney(r.cost)}</td>
                  <td className="py-2">
                    {r.cached ? (
                      <span className="chip border-s3/40 text-s3">cache hit</span>
                    ) : r.backend === "real" ? (
                      <span className="chip !text-[10px] border-good/50 text-good"
                        title="served by a live vLLM endpoint on your GPU fleet">real vLLM</span>
                    ) : (
                      <span className="chip !text-[10px]"
                        title="synthesized response — provider call not wired in this build">simulated</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
