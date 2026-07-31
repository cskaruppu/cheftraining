import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ModelInfo, api, fmtMoney } from "../lib/api";
import { PageHeader, Spinner, tooltipStyle } from "../components/ui";

interface Alternative {
  model_id: string;
  model_name: string;
  provider: string;
  license: string;
  quality_delta: number;
  quality: number;
  profile: { gpus: string; quantization: string; est_cost_month: number };
  replicas: number;
  local_monthly: number;
  savings_monthly: number;
  savings_pct: number;
}

interface MigratePlan {
  cloud: {
    model_id: string;
    model_name: string;
    provider: string;
    blended_price: number;
    monthly_cost: number;
    quality: number;
  };
  dimension: string;
  alternatives: Alternative[];
  projection: { month: number; cloud: number; local?: number }[];
  verdict: string | null;
}

export default function Migrate() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [useCases, setUseCases] = useState<{ id: string; label: string }[]>([]);
  const [cloudId, setCloudId] = useState("claude-opus-4.5");
  const [useCase, setUseCase] = useState("chatbot");
  const [volume, setVolume] = useState(200);
  const [plan, setPlan] = useState<MigratePlan | null>(null);
  const [radar, setRadar] = useState<Record<string, number | string>[]>([]);
  const [busy, setBusy] = useState(false);

  const cloudModels = useMemo(() => models.filter((m) => !m.self_hostable), [models]);

  useEffect(() => {
    api.models().then((d) => setModels(d.models));
    api.useCases().then((d) => setUseCases(d.use_cases));
  }, []);

  const run = async () => {
    setBusy(true);
    try {
      const r = await fetch("/api/migrate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cloud_model_id: cloudId,
          monthly_m_tokens: volume,
          use_case: useCase,
        }),
      });
      const p: MigratePlan = await r.json();
      setPlan(p);
      if (p.alternatives.length) {
        const c = await api.compare([p.cloud.model_id, p.alternatives[0].model_id]);
        setRadar(c.radar);
      }
    } finally {
      setBusy(false);
    }
  };

  if (!models.length) return <Spinner />;

  const best = plan?.alternatives[0];

  return (
    <div>
      <PageHeader
        title="Migrate from Cloud"
        sub="Using a commercial API model? See the closest open-weights equivalents you can run on your own GPUs — with the savings, the quality trade-off, and one-click deploy"
      />

      <div className="card mb-5">
        <div className="grid md:grid-cols-3 gap-4">
          <div>
            <label className="text-xs text-muted block mb-1.5">Current / planned cloud model</label>
            <select className="input w-full" value={cloudId} onChange={(e) => setCloudId(e.target.value)}>
              {cloudModels.map((m) => (
                <option key={m.id} value={m.id}>{m.name} — {m.provider}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted block mb-1.5">Use case</label>
            <select className="input w-full" value={useCase} onChange={(e) => setUseCase(e.target.value)}>
              {useCases.map((u) => (
                <option key={u.id} value={u.id}>{u.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted block mb-1.5">
              Monthly volume: <span className="text-ink tabular-nums">{volume}M</span> tokens
            </label>
            <input
              type="range" min={5} max={500} step={5} value={volume}
              onChange={(e) => setVolume(Number(e.target.value))}
              className="mt-2"
            />
          </div>
        </div>
        <button className="btn mt-4" onClick={run} disabled={busy}>
          {busy ? "Analyzing…" : "Find local equivalents"}
        </button>
      </div>

      {busy && <Spinner />}

      {plan && best && (
        <>
          {plan.verdict && (
            <div className="card border-s3/40 mb-4">
              <div className="text-xs uppercase tracking-wide text-s3 mb-1">Migration verdict</div>
              <p className="text-sm text-ink2">{plan.verdict}</p>
            </div>
          )}

          <div className="grid lg:grid-cols-2 gap-4 mb-4">
            <div className="card">
              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-xl border border-edge bg-raised/40 p-4">
                  <div className="text-xs text-muted mb-1">Cloud (today)</div>
                  <div className="font-medium">{plan.cloud.model_name}</div>
                  <div className="text-xs text-muted mb-3">{plan.cloud.provider}</div>
                  <div className="text-2xl font-semibold tabular-nums">
                    {fmtMoney(plan.cloud.monthly_cost)}<span className="text-xs text-muted font-normal">/mo</span>
                  </div>
                  <div className="text-xs text-ink2 mt-2">
                    {plan.dimension} quality {plan.cloud.quality}/100
                  </div>
                  <div className="text-xs text-muted">data leaves your cluster</div>
                </div>
                <div className="rounded-xl border border-s3/50 bg-raised/40 p-4">
                  <div className="text-xs text-s3 mb-1">Local equivalent (suggested)</div>
                  <div className="font-medium">{best.model_name}</div>
                  <div className="text-xs text-muted mb-3">
                    {best.profile.gpus} · {best.profile.quantization}
                    {best.replicas > 1 ? ` · ${best.replicas} replicas` : ""}
                  </div>
                  <div className="text-2xl font-semibold tabular-nums">
                    {fmtMoney(best.local_monthly)}<span className="text-xs text-muted font-normal">/mo</span>
                  </div>
                  <div className="text-xs text-ink2 mt-2">
                    {plan.dimension} quality {best.quality}/100 ({best.quality_delta >= 0 ? "+" : ""}{best.quality_delta})
                  </div>
                  <div className="text-xs text-s3">stays on your OpenShift cluster</div>
                </div>
              </div>
              {best.savings_monthly > 0 && (
                <div className="mt-4 rounded-lg bg-raised px-4 py-3 flex items-baseline gap-3">
                  <span className="text-xl font-semibold text-s3 tabular-nums">
                    {fmtMoney(best.savings_monthly)}/mo
                  </span>
                  <span className="text-sm text-ink2">
                    saved ({best.savings_pct.toFixed(0)}%) — {fmtMoney(best.savings_monthly * 12)}/year
                  </span>
                </div>
              )}
              <Link to={`/deploy?model=${best.model_id}`} className="btn inline-block mt-4">
                Deploy {best.model_name} →
              </Link>
            </div>

            <div className="card">
              <h2 className="text-sm font-medium mb-2">Quality: cloud vs suggested local</h2>
              <ResponsiveContainer width="100%" height={260}>
                <RadarChart data={radar} outerRadius="70%">
                  <PolarGrid stroke="#2c2c2a" />
                  <PolarAngleAxis dataKey="dimension" tick={{ fill: "#c3c2b7", fontSize: 11 }} />
                  <PolarRadiusAxis domain={[60, 100]} tick={{ fill: "#898781", fontSize: 10 }} stroke="#383835" />
                  <Radar name={plan.cloud.model_name} dataKey={plan.cloud.model_id}
                    stroke="#3987e5" fill="#3987e5" fillOpacity={0.12} strokeWidth={2} />
                  <Radar name={best.model_name} dataKey={best.model_id}
                    stroke="#d95926" fill="#d95926" fillOpacity={0.12} strokeWidth={2} />
                  <Legend wrapperStyle={{ fontSize: 12, color: "#c3c2b7" }} />
                  <Tooltip contentStyle={tooltipStyle} />
                </RadarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="grid lg:grid-cols-2 gap-4 mb-4">
            <div className="card">
              <h2 className="text-sm font-medium mb-2">Cumulative cost — 12 months (USD)</h2>
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={plan.projection} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="#2c2c2a" vertical={false} />
                  <XAxis dataKey="month" stroke="#898781" fontSize={11} tickLine={false}
                    axisLine={{ stroke: "#383835" }} />
                  <YAxis stroke="#898781" fontSize={11} tickLine={false} axisLine={false}
                    tickFormatter={(v: number) => `$${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`} />
                  <Tooltip contentStyle={tooltipStyle}
                    cursor={{ stroke: "#898781", strokeDasharray: "3 3" }} />
                  <Line type="monotone" dataKey="cloud" name={plan.cloud.model_name}
                    stroke="#3987e5" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="local" name={`${best.model_name} (local)`}
                    stroke="#d95926" strokeWidth={2} dot={false} />
                  <Legend wrapperStyle={{ fontSize: 12, color: "#c3c2b7" }} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="card">
              <h2 className="text-sm font-medium mb-3">Other equivalents</h2>
              <div className="space-y-3">
                {plan.alternatives.slice(1).map((a) => (
                  <div key={a.model_id} className="flex items-center justify-between rounded-lg border border-edge bg-raised/40 px-4 py-3">
                    <div>
                      <div className="text-sm">{a.model_name}</div>
                      <div className="text-[11px] text-muted">
                        {a.profile.gpus}
                        {a.replicas > 1 ? ` · ${a.replicas} replicas` : ""} · quality {a.quality_delta >= 0 ? "+" : ""}{a.quality_delta} · {a.license}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm tabular-nums">{fmtMoney(a.local_monthly)}/mo</div>
                      {a.savings_monthly > 0 && (
                        <div className="text-[11px] text-s3 tabular-nums">−{a.savings_pct.toFixed(0)}%</div>
                      )}
                    </div>
                  </div>
                ))}
                {plan.alternatives.length <= 1 && (
                  <div className="text-sm text-muted">No other equivalents within the quality window.</div>
                )}
              </div>
              <p className="text-[11px] text-muted mt-4">
                GPU costs from recommended serving profiles at 50% utilization; production
                refines these with live telemetry. Open-weights licenses shown — verify terms
                for your use.
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
