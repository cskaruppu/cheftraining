import { useEffect, useState } from "react";
import { fmtCompact, fmtMoney, ModelInfo } from "../lib/api";
import { PageHeader, StatTile } from "../components/ui";

interface Result {
  error?: string;
  window_days: number;
  requests: number;
  tokens: number;
  actual: { spend: number; avg_latency_ms: number };
  hypothetical: {
    spend: number; est_latency_ms: number; latency_basis: string;
    label: string; models: string[];
  };
  delta: { spend_usd: number; spend_pct: number | null };
  warnings: string[];
  basis: string;
}

const RANGES = [7, 14, 30];

export default function WhatIf() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [scenario, setScenario] = useState("route");
  const [days, setDays] = useState(14);
  const [res, setRes] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch("/api/models").then((r) => r.json()).then((d) => setModels(d.models));
  }, []);

  const run = async () => {
    setBusy(true);
    setRes(null);
    const body = {
      days,
      scenario: scenario === "route"
        ? { type: "route" }
        : { type: "model", model_id: scenario },
    };
    const r = await fetch("/api/whatif", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((x) => x.json());
    setRes(r);
    setBusy(false);
  };

  const cheaper = res && !res.error && res.delta.spend_usd < 0;

  return (
    <div>
      <PageHeader
        title="What-If Replay"
        sub="Replay your recorded traffic under a hypothetical — exact re-pricing of the token shapes this install actually served, not a generic price calculator."
      />

      <div className="card mb-5">
        <div className="flex flex-wrap items-end gap-4">
          <label className="block">
            <span className="text-xs text-muted block mb-1.5">Scenario</span>
            <select className="input !py-1.5 text-sm min-w-[280px]" value={scenario}
              onChange={(e) => setScenario(e.target.value)}>
              <option value="route">smart router (your measured simple/complex mix)</option>
              <optgroup label="all traffic on one model">
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </optgroup>
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-muted block mb-1.5">Window</span>
            <div className="flex rounded-lg border border-edge overflow-hidden">
              {RANGES.map((d) => (
                <button key={d} onClick={() => setDays(d)}
                  className={`px-3 py-1.5 text-xs transition-colors ${
                    d === days ? "bg-raised text-ink" : "text-muted hover:text-ink2"}`}>
                  {d}d
                </button>
              ))}
            </div>
          </label>
          <button className="btn" onClick={run} disabled={busy}>
            {busy ? "Replaying…" : "Replay my traffic"}
          </button>
        </div>
      </div>

      {res?.error && (
        <div className="card text-sm text-warn">{res.error}</div>
      )}

      {res && !res.error && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
            <StatTile label="Replayed" value={fmtCompact(res.requests)}
              hint={`${fmtCompact(res.tokens)} tokens · last ${res.window_days}d`} />
            <StatTile label="Actual spend" value={fmtMoney(res.actual.spend)}
              hint={`avg latency ${res.actual.avg_latency_ms} ms`} />
            <StatTile label="Hypothetical spend" value={fmtMoney(res.hypothetical.spend)}
              hint={`est latency ${res.hypothetical.est_latency_ms} ms (${res.hypothetical.latency_basis})`} />
            <StatTile label={cheaper ? "You would save" : "It would cost more"}
              value={<span className={cheaper ? "text-good" : "text-warn"}>
                {fmtMoney(Math.abs(res.delta.spend_usd))}
              </span>}
              hint={res.delta.spend_pct != null
                ? `${res.delta.spend_pct > 0 ? "+" : ""}${res.delta.spend_pct}% vs actual`
                : undefined} />
          </div>

          <div className="card">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-ink">{res.hypothetical.label}</span>
              <span className="chip !text-[10px]" title={res.basis}>
                basis: {res.basis}
              </span>
            </div>
            {res.warnings.length > 0 && (
              <div className="mt-3 space-y-1.5">
                {res.warnings.map((w, i) => (
                  <div key={i}
                    className="border-l-2 border-warn rounded-r-lg bg-raised px-3 py-2 text-xs text-ink2">
                    ⚠ {w}
                  </div>
                ))}
              </div>
            )}
            <p className="text-[11px] text-muted mt-3">
              Costs are exact re-pricing of recorded token shapes. Latency is{" "}
              {res.hypothetical.latency_basis} ({res.hypothetical.latency_basis === "measured"
                ? "from live telemetry on this install"
                : "from catalog figures until enough telemetry accumulates"}).
              Quality is not simulated — check Evals before switching.
            </p>
          </div>
        </>
      )}

      {!res && !busy && (
        <div className="card text-sm text-muted">
          Pick a scenario and replay — e.g. <em>"what if everything ran on Gemini 2.5
          Flash?"</em> or <em>"what if the smart router handled all my traffic?"</em>{" "}
          The answer comes from your own workload, with warnings for requests that
          wouldn't fit the candidate's context window.
        </div>
      )}
    </div>
  );
}
