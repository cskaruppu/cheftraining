import { useEffect, useMemo, useState } from "react";
import { ModelInfo, SERIES, api, fmtMoney } from "../lib/api";
import { PageHeader, ScoreBar, Spinner } from "../components/ui";

interface EvalRun {
  judge_score: number;
  latency_ms: number;
  cost: number;
}

interface EvalResult {
  model_id: string;
  model_name: string;
  provider: string;
  avg_judge_score: number;
  avg_latency_ms: number;
  total_cost: number;
  cost_per_1k_prompts: number;
  per_prompt: EvalRun[];
}

interface EvalResponse {
  mode: string;
  dimension: string;
  prompts: string[];
  results: EvalResult[];
  winner_id: string;
  value_pick_id: string;
  verdict: string;
}

const SAMPLE_PROMPTS = [
  "Summarize the key risks in this vendor contract and suggest mitigations.",
  "Draft a polite escalation email about a delayed shipment to a supplier.",
  "Extract the invoice number, total and due date from this text as JSON.",
];

export default function Evals() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [useCases, setUseCases] = useState<{ id: string; label: string }[]>([]);
  const [useCase, setUseCase] = useState("chatbot");
  const [sel, setSel] = useState<string[]>([
    "claude-sonnet-4.5", "gpt-5-mini", "gemini-2.5-flash", "llama-4-maverick",
  ]);
  const [text, setText] = useState(SAMPLE_PROMPTS.join("\n"));
  const [resp, setResp] = useState<EvalResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.models().then((d) => setModels(d.models));
    api.useCases().then((d) => setUseCases(d.use_cases));
  }, []);

  const prompts = useMemo(
    () => text.split("\n").map((p) => p.trim()).filter(Boolean),
    [text],
  );

  const toggle = (id: string) =>
    setSel((s) =>
      s.includes(id) ? s.filter((x) => x !== id) : s.length >= 5 ? s : [...s, id],
    );

  const run = async () => {
    setBusy(true);
    setErr("");
    try {
      const r = await fetch("/api/evals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompts, model_ids: sel, use_case: useCase }),
      });
      if (!r.ok) throw new Error(await r.text());
      setResp(await r.json());
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!models.length) return <Spinner />;

  return (
    <div>
      <PageHeader
        title="Evals — test on YOUR prompts"
        sub="Paste real prompts from your workload; Modelect runs them across candidate models and scores quality, cost and latency — evidence, not spec sheets (demo simulation)"
      />

      <div className="card mb-5">
        <label className="text-xs text-muted block mb-1.5">
          Your prompts — one per line ({prompts.length}/20)
        </label>
        <textarea
          className="input w-full h-28 resize-y"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="flex flex-wrap items-center gap-3 mt-3">
          <select className="input" value={useCase} onChange={(e) => setUseCase(e.target.value)}>
            {useCases.map((u) => (
              <option key={u.id} value={u.id}>{u.label}</option>
            ))}
          </select>
          <span className="text-xs text-muted">Candidates ({sel.length}/5):</span>
        </div>
        <div className="flex flex-wrap gap-2 mt-2">
          {models.map((m) => {
            const on = sel.includes(m.id);
            return (
              <button
                key={m.id}
                onClick={() => toggle(m.id)}
                className="chip !py-1 !px-3 !text-xs transition hover:!text-ink"
                style={on ? { borderColor: "#3987e5", color: "#fff" } : {}}
              >
                {m.name}
              </button>
            );
          })}
        </div>
        <button
          className="btn mt-4"
          onClick={run}
          disabled={busy || prompts.length === 0 || sel.length < 2}
        >
          {busy ? "Running evals…" : `Run ${prompts.length} prompts x ${sel.length} models`}
        </button>
      </div>

      {err && <div className="card text-sm text-crit mb-4">{err}</div>}
      {busy && <Spinner />}

      {resp && (
        <>
          <div className="card border-s1/40 mb-4">
            <div className="text-xs uppercase tracking-wide text-s1 mb-1">Verdict</div>
            <p className="text-sm text-ink2">{resp.verdict}</p>
          </div>

          <div className="card mb-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-edge">
                  <th className="py-2 pr-3 font-normal">#</th>
                  <th className="py-2 pr-4 font-normal">Model</th>
                  <th className="py-2 pr-4 font-normal w-64">Judge score (avg)</th>
                  <th className="py-2 pr-4 font-normal text-right">Avg latency</th>
                  <th className="py-2 pr-4 font-normal text-right">Run cost</th>
                  <th className="py-2 pr-4 font-normal text-right">$/1k prompts</th>
                  <th className="py-2 font-normal">Tag</th>
                </tr>
              </thead>
              <tbody>
                {resp.results.map((r, i) => (
                  <tr key={r.model_id} className="border-b border-edge/50">
                    <td className="py-2.5 pr-3 text-muted tabular-nums">{i + 1}</td>
                    <td className="py-2.5 pr-4">
                      <div className="text-ink">{r.model_name}</div>
                      <div className="text-[11px] text-muted">{r.provider}</div>
                    </td>
                    <td className="py-2.5 pr-4">
                      <ScoreBar value={r.avg_judge_score} />
                    </td>
                    <td className="py-2.5 pr-4 text-right text-ink2 tabular-nums">{r.avg_latency_ms} ms</td>
                    <td className="py-2.5 pr-4 text-right text-ink2 tabular-nums">{fmtMoney(r.total_cost)}</td>
                    <td className="py-2.5 pr-4 text-right text-ink2 tabular-nums">${r.cost_per_1k_prompts.toFixed(2)}</td>
                    <td className="py-2.5">
                      {r.model_id === resp.winner_id && (
                        <span className="chip border-s1/50 text-s1">top quality</span>
                      )}{" "}
                      {r.model_id === resp.value_pick_id && (
                        <span className="chip border-s3/50 text-s3">value pick</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card overflow-x-auto">
            <h2 className="text-sm font-medium mb-3">Per-prompt judge scores</h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted border-b border-edge">
                  <th className="py-2 pr-4 font-normal">Prompt</th>
                  {resp.results.map((r, i) => (
                    <th key={r.model_id} className="py-2 pr-4 font-normal">
                      <span
                        className="mr-1.5 inline-block h-2 w-2 rounded-full"
                        style={{ background: SERIES[i % 3] }}
                      />
                      {r.model_name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {resp.prompts.map((p, pi) => (
                  <tr key={pi} className="border-b border-edge/50">
                    <td className="py-2 pr-4 text-ink2 max-w-[320px] truncate" title={p}>{p}</td>
                    {resp.results.map((r) => {
                      const s = r.per_prompt[pi]?.judge_score ?? 0;
                      const best = Math.max(...resp.results.map((x) => x.per_prompt[pi]?.judge_score ?? 0));
                      return (
                        <td key={r.model_id} className={`py-2 pr-4 tabular-nums ${s === best ? "text-good" : "text-ink2"}`}>
                          {s.toFixed(1)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-[11px] text-muted mt-3">
              Demo build: scores are simulated from model quality profiles. Production runs live
              provider calls with an LLM-as-judge scoring pass — same report format.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
