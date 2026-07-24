import { useEffect, useState } from "react";
import { ModelInfo, PlaygroundResult, api, fmtMoney } from "../lib/api";
import { PageHeader, Spinner } from "../components/ui";
import { SERIES } from "../lib/api";

export default function Playground() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [sel, setSel] = useState<string[]>(["claude-sonnet-4.5", "gemini-2.5-flash"]);
  const [prompt, setPrompt] = useState(
    "Summarize the key risks in our Q3 vendor contracts and suggest mitigations.",
  );
  const [results, setResults] = useState<PlaygroundResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.models().then((d) => setModels(d.models));
  }, []);

  const toggle = (id: string) =>
    setSel((s) =>
      s.includes(id) ? s.filter((x) => x !== id) : s.length >= 3 ? s : [...s, id],
    );

  const run = async () => {
    setBusy(true);
    setErr("");
    setResults(null);
    try {
      const r = await api.playground(sel, prompt);
      setResults(r.results);
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
        title="Playground"
        sub="Run one prompt across up to three models side by side — with latency and cost per response (demo simulation)"
      />

      <div className="card mb-5">
        <textarea
          className="input w-full h-24 resize-y font-normal"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Enter a prompt…"
        />
        <div className="flex flex-wrap gap-2 mt-3">
          {models.map((m) => {
            const idx = sel.indexOf(m.id);
            return (
              <button
                key={m.id}
                onClick={() => toggle(m.id)}
                className="chip !py-1 !px-3 !text-xs transition hover:!text-ink"
                style={idx >= 0 ? { borderColor: SERIES[idx], color: "#fff" } : {}}
              >
                {m.name}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-3 mt-4">
          <button className="btn" onClick={run} disabled={busy || sel.length === 0 || !prompt.trim()}>
            {busy ? "Running…" : `Run on ${sel.length} model${sel.length === 1 ? "" : "s"}`}
          </button>
          <span className="text-xs text-muted">
            Simulated in demo mode — wire provider keys to go live
          </span>
        </div>
      </div>

      {err && <div className="card text-sm text-crit mb-4">{err}</div>}
      {busy && <Spinner />}

      {results && (
        <div className={`grid gap-4 ${results.length === 2 ? "lg:grid-cols-2" : results.length >= 3 ? "lg:grid-cols-3" : ""}`}>
          {results.map((r, i) => (
            <div key={r.model_id} className="card flex flex-col">
              <div className="flex items-center gap-2 mb-3">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: SERIES[i] }} />
                <span className="font-medium text-sm">{r.model_name}</span>
                <span className="text-xs text-muted">{r.provider}</span>
              </div>
              <p className="text-sm text-ink2 whitespace-pre-wrap flex-1">{r.text}</p>
              <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted border-t border-edge mt-4 pt-3 tabular-nums">
                <span>
                  <span className="text-ink2">{r.latency_ms} ms</span> latency
                </span>
                <span>
                  <span className="text-ink2">
                    {r.tokens_in}/{r.tokens_out}
                  </span>{" "}
                  tokens
                </span>
                <span>
                  <span className="text-ink2">{fmtMoney(r.cost)}</span> cost
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
