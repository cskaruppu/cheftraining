import { useEffect, useState } from "react";
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
import { PageHeader, Spinner, StatTile, tooltipStyle } from "../components/ui";

export default function Dashboard() {
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [demoSeed, setDemoSeed] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    const refresh = () =>
      api.analytics()
        .then((d) => {
          setData(d);
          setUpdatedAt(new Date());
        })
        .catch((e) => setErr(String(e)));
    refresh();
    fetch("/api/system").then((r) => r.json()).then((s) => setDemoSeed(s.demo_seed)).catch(() => {});
    const t = setInterval(refresh, 10_000);
    return () => clearInterval(t);
  }, []);

  if (err) return <div className="text-crit text-sm">API error: {err}</div>;
  if (!data) return <Spinner />;

  const { kpis } = data;
  const daily = data.daily.map((d) => ({ ...d, label: d.day.slice(5) }));
  const byModel = data.by_model.slice(0, 6);

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <PageHeader
          title="Dashboard"
          sub={demoSeed
            ? "Live traffic, spend and latency observed through the gateway — real events plus seeded demo history"
            : "Live traffic, spend and latency observed through the gateway — real traffic only"}
        />
        <span className="chip !text-[11px] mt-1 shrink-0" title="the page re-queries the event store every 10 seconds">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-good mr-1.5 animate-pulse" />
          live · {updatedAt ? updatedAt.toLocaleTimeString() : "…"}
        </span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatTile label="Requests · 24h" value={fmtCompact(kpis.requests_24h)} hint={`${fmtCompact(kpis.requests_total)} total (14d)`} />
        <StatTile label="Spend · 14d" value={fmtMoney(kpis.spend_total)} hint="across all providers" />
        <StatTile label="Avg latency" value={`${kpis.avg_latency_ms} ms`} hint="first-token, non-cached" />
        <StatTile label="Cache hit rate" value={`${kpis.cache_hit_rate}%`} hint="semantic cache savings" />
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mb-6">
        <div className="card">
          <h2 className="text-sm font-medium mb-4">Daily spend (USD)</h2>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={daily} margin={{ top: 4, right: 8, left: -14, bottom: 0 }}>
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
        </div>

        <div className="card">
          <h2 className="text-sm font-medium mb-4">Requests by model · 14d</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={byModel} layout="vertical" margin={{ top: 0, right: 24, left: 40, bottom: 0 }}>
              <CartesianGrid stroke="#2c2c2a" horizontal={false} />
              <XAxis type="number" stroke="#898781" fontSize={11} tickLine={false} axisLine={{ stroke: "#383835" }} />
              <YAxis type="category" dataKey="model" stroke="#c3c2b7" fontSize={11} width={120} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Bar dataKey="requests" name="Requests" fill="#3987e5" radius={[0, 4, 4, 0]} barSize={14} />
            </BarChart>
          </ResponsiveContainer>
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
                <th className="py-2 pr-4 font-normal text-right">Tokens in/out</th>
                <th className="py-2 pr-4 font-normal text-right">Latency</th>
                <th className="py-2 pr-4 font-normal text-right">Cost</th>
                <th className="py-2 font-normal">Cache</th>
              </tr>
            </thead>
            <tbody>
              {data.recent.map((r, i) => (
                <tr key={i} className="border-b border-edge/50 text-ink2">
                  <td className="py-2 pr-4 tabular-nums">{r.ts.slice(5, 16).replace("T", " ")}</td>
                  <td className="py-2 pr-4 text-ink">{r.model_name}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">
                    {fmtCompact(r.tokens_in)} / {fmtCompact(r.tokens_out)}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums">{r.cached ? "—" : `${r.latency_ms} ms`}</td>
                  <td className="py-2 pr-4 text-right tabular-nums">{r.cached ? "$0" : fmtMoney(r.cost)}</td>
                  <td className="py-2">
                    {r.cached ? <span className="chip border-s3/40 text-s3">hit</span> : <span className="chip">miss</span>}
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
