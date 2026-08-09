import { useEffect, useState } from "react";
import {
  ModelInfo,
  RecommendResponse,
  api,
} from "../lib/api";
import { PageHeader, ScoreBar, SourceBadge, Spinner } from "../components/ui";

const CONSTRAINT_DEFS = [
  { key: "open_source_only", label: "Open source only" },
  { key: "self_hostable_only", label: "Must be self-hostable" },
  { key: "require_vision", label: "Needs vision" },
  { key: "require_function_calling", label: "Needs function calling" },
] as const;

export default function Recommend() {
  const [useCases, setUseCases] = useState<{ id: string; label: string }[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [useCase, setUseCase] = useState("chatbot");
  const [weights, setWeights] = useState({ quality: 50, cost: 30, speed: 20 });
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [minContext, setMinContext] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [chosen, setChosen] = useState("");
  const [mode, setMode] = useState<"best" | "smallest_capable">("best");
  const [floor, setFloor] = useState(80);
  const [resp, setResp] = useState<RecommendResponse | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.useCases().then((d) => setUseCases(d.use_cases));
    api.models().then((d) => setModels(d.models));
  }, []);

  const run = async () => {
    setBusy(true);
    try {
      const constraints: Record<string, unknown> = { ...flags };
      if (minContext) constraints.min_context = Number(minContext);
      if (maxPrice) constraints.max_blended_price = Number(maxPrice);
      setResp(
        await api.recommend({
          use_case: useCase,
          weights,
          constraints,
          chosen_id: chosen || null,
          mode,
          quality_floor: floor,
        }),
      );
    } finally {
      setBusy(false);
    }
  };

  const cvs = resp?.chosen_vs_suggested;

  return (
    <div>
      <PageHeader
        title="Recommendation Engine"
        sub="Describe your requirement — get a transparent, scored ranking with the reasoning shown"
      />

      <div className="grid lg:grid-cols-[340px_1fr] gap-5">
        <div className="card h-fit space-y-5">
          <div>
            <label className="text-xs text-muted block mb-1.5">Use case</label>
            <select className="input w-full" value={useCase} onChange={(e) => setUseCase(e.target.value)}>
              {useCases.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs text-muted block mb-1.5">Objective</label>
            <div className="grid grid-cols-2 gap-1 rounded-lg bg-raised p-1">
              {([
                ["best", "Best overall"],
                ["smallest_capable", "Smallest capable"],
              ] as const).map(([m, label]) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={`rounded-md px-2 py-1.5 text-xs transition ${
                    mode === m ? "bg-s1 text-white" : "text-ink2 hover:text-ink"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {mode === "smallest_capable" && (
              <div className="mt-2">
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-ink2">Quality floor</span>
                  <span className="text-muted tabular-nums">{floor}/100</span>
                </div>
                <input type="range" min={70} max={95} value={floor}
                  onChange={(e) => setFloor(Number(e.target.value))} />
                <p className="text-[11px] text-muted mt-1">
                  SLM-first: ranks the smallest model that clears this quality bar
                </p>
              </div>
            )}
          </div>

          <div className="space-y-3">
            {(["quality", "cost", "speed"] as const).map((k) => (
              <div key={k}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-ink2 capitalize">{k} priority</span>
                  <span className="text-muted tabular-nums">{weights[k]}</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={weights[k]}
                  onChange={(e) => setWeights({ ...weights, [k]: Number(e.target.value) })}
                />
              </div>
            ))}
          </div>

          <div className="space-y-2">
            {CONSTRAINT_DEFS.map((c) => (
              <label key={c.key} className="flex items-center gap-2 text-sm text-ink2 cursor-pointer">
                <input
                  type="checkbox"
                  className="accent-s1"
                  checked={!!flags[c.key]}
                  onChange={(e) => setFlags({ ...flags, [c.key]: e.target.checked })}
                />
                {c.label}
              </label>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted block mb-1.5">Min context</label>
              <input className="input w-full" placeholder="e.g. 128000" value={minContext} onChange={(e) => setMinContext(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-muted block mb-1.5">Max $/1M blended</label>
              <input className="input w-full" placeholder="e.g. 2.50" value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} />
            </div>
          </div>

          <div>
            <label className="text-xs text-muted block mb-1.5">I was planning to use…</label>
            <select className="input w-full" value={chosen} onChange={(e) => setChosen(e.target.value)}>
              <option value="">(no current choice)</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>

          <button className="btn w-full" onClick={run} disabled={busy}>
            {busy ? "Scoring…" : "Get recommendation"}
          </button>
        </div>

        <div className="space-y-4">
          {!resp && !busy && (
            <div className="card text-sm text-muted">
              Set your requirement on the left and run the engine. Every result shows its full
              score breakdown — no black-box answers.
            </div>
          )}
          {busy && <Spinner />}

          {cvs && !cvs.same && (
            <div className="card border-s1/40">
              <div className="text-xs uppercase tracking-wide text-s1 mb-2">
                You chose {cvs.chosen.name} — we suggest {cvs.suggested.name}
              </div>
              <ul className="text-sm text-ink2 space-y-1">
                {cvs.deltas.map((d, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-s1">→</span>
                    {d}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {cvs && cvs.same && (
            <div className="card border-s3/40 text-sm text-ink2">
              <span className="text-s3 font-medium">Good choice —</span> {cvs.chosen.name} is
              also our top suggestion for this requirement.
            </div>
          )}

          {resp?.message && <div className="card text-sm text-warn">{resp.message}</div>}

          {resp?.results.map((r, rank) => (
            <div key={r.model.id} className={`card ${rank === 0 ? "border-s1/50" : ""}`}>
              <div className="flex items-start justify-between gap-3 mb-3">
                <div className="flex items-center gap-3">
                  <span
                    className={`h-7 w-7 rounded-lg grid place-items-center text-xs font-semibold ${
                      rank === 0 ? "bg-s1 text-white" : "bg-raised text-ink2"
                    }`}
                  >
                    {rank + 1}
                  </span>
                  <div>
                    <div className="font-medium flex items-center gap-2">
                      {r.model.name}
                      {rank === 0 && (
                        <span className="chip border-s1/50 text-s1">suggested</span>
                      )}
                      {r.model.size_class === "slm" && (
                        <span className="chip border-s3/50 text-s3">SLM</span>
                      )}
                    </div>
                    <div className="text-xs text-muted">
                      {r.model.provider}
                      {r.model.params_b && <> · {r.model.params_b}B</>} · $
                      {r.blended_price.toFixed(2)}/1M blended
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xl font-semibold tabular-nums">{r.score.toFixed(1)}</div>
                  <div className="text-[11px] text-muted">weighted score</div>
                </div>
              </div>

              <div className="grid sm:grid-cols-3 gap-x-6 gap-y-1 mb-3">
                <ScoreBar value={r.breakdown.quality} label="quality" />
                <ScoreBar value={r.breakdown.cost} label="cost" color="#199e70" />
                <ScoreBar value={r.breakdown.speed} label="speed" color="#d95926" />
              </div>

              <ul className="text-xs text-ink2 space-y-1">
                {r.reasons.map((reason, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-muted">•</span>
                    {reason}
                  </li>
                ))}
              </ul>
            </div>
          ))}

          {resp && resp.excluded.length > 0 && (
            <div className="card">
              <div className="text-xs text-muted mb-2">
                Excluded by constraints ({resp.excluded.length})
              </div>
              <div className="flex flex-wrap gap-2">
                {resp.excluded.map((e) => (
                  <span key={e.id} className="chip" title={e.reason}>
                    {e.name} — {e.reason}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
