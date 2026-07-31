import { useEffect, useMemo, useState } from "react";
import { ModelInfo, api } from "../lib/api";
import { PageHeader, Spinner } from "../components/ui";
import { FMTS, Fmt, LANGS, Lang, snippet } from "../lib/snippets";

interface DeploymentLite {
  id: string;
  name: string;
  model_id: string;
  status: string;
  api_key: string;
}

interface Check {
  id: string;
  label: string;
  status: "pass" | "warn";
  detail: string;
}

interface TestReport {
  mode: string;
  model_name: string;
  overall: string;
  checks: Check[];
}

export default function Integrate() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [deployments, setDeployments] = useState<DeploymentLite[]>([]);
  const [target, setTarget] = useState("");
  const [lang, setLang] = useState<Lang>("python");
  const [fmt, setFmt] = useState<Fmt>("chat");
  const [copied, setCopied] = useState(false);
  const [report, setReport] = useState<TestReport | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.models().then((d) => {
      setModels(d.models);
      setTarget((t) => t || `model:${d.models[0]?.id ?? ""}`);
    });
    fetch("/api/deployments")
      .then((r) => r.json())
      .then((d) => {
        const ready = (d.deployments as DeploymentLite[]).filter((x) => x.status === "ready");
        setDeployments(ready);
        if (ready.length) setTarget(`dep:${ready[0].id}`);
      });
  }, []);

  const { modelId, apiKey, targetLabel } = useMemo(() => {
    if (target.startsWith("dep:")) {
      const d = deployments.find((x) => x.id === target.slice(4));
      if (d) return { modelId: d.model_id, apiKey: d.api_key, targetLabel: d.name };
    }
    const id = target.startsWith("model:") ? target.slice(6) : target;
    return { modelId: id, apiKey: "", targetLabel: id };
  }, [target, deployments]);

  const code = useMemo(
    () => snippet(lang, fmt, window.location.origin, modelId, apiKey),
    [lang, fmt, modelId, apiKey],
  );

  const copy = () => {
    navigator.clipboard?.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const runTests = async () => {
    setBusy(true);
    setReport(null);
    try {
      const r = await fetch("/api/integration-test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_id: modelId }),
      });
      setReport(await r.json());
    } finally {
      setBusy(false);
    }
  };

  if (!models.length) return <Spinner />;

  return (
    <div>
      <PageHeader
        title="Integrate & Verify"
        sub="Generate working client code in your language and format, then run the integration test suite — connectivity, schema compliance and measured groundedness"
      />

      <div className="card mb-5">
        <div className="grid md:grid-cols-3 gap-4 mb-4">
          <div>
            <label className="text-xs text-muted block mb-1.5">Target</label>
            <select className="input w-full" value={target} onChange={(e) => setTarget(e.target.value)}>
              {deployments.length > 0 && (
                <optgroup label="Your deployments">
                  {deployments.map((d) => (
                    <option key={d.id} value={`dep:${d.id}`}>● {d.name}</option>
                  ))}
                </optgroup>
              )}
              <optgroup label="Gateway models">
                {models.map((m) => (
                  <option key={m.id} value={`model:${m.id}`}>{m.name}</option>
                ))}
              </optgroup>
            </select>
          </div>
          <div>
            <label className="text-xs text-muted block mb-1.5">Language</label>
            <div className="flex flex-wrap gap-1.5">
              {LANGS.map((l) => (
                <button key={l.id} onClick={() => setLang(l.id)}
                  className="chip !py-1 !px-3 !text-xs transition hover:!text-ink"
                  style={lang === l.id ? { borderColor: "#3987e5", color: "#fff" } : {}}>
                  {l.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-xs text-muted block mb-1.5">Format</label>
            <div className="flex flex-wrap gap-1.5">
              {FMTS.map((f) => (
                <button key={f.id} onClick={() => setFmt(f.id)} title={f.hint}
                  className="chip !py-1 !px-3 !text-xs transition hover:!text-ink"
                  style={fmt === f.id ? { borderColor: "#3987e5", color: "#fff" } : {}}>
                  {f.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="relative">
          <button onClick={copy}
            className="btn-ghost !py-1 !px-3 !text-xs absolute right-3 top-3 z-10">
            {copied ? "copied ✓" : "copy"}
          </button>
          <pre className="bg-page border border-edge rounded-xl p-4 text-[12.5px] leading-relaxed text-ink2 overflow-x-auto max-h-[420px]">
            {code}
          </pre>
        </div>
        <p className="text-[11px] text-muted mt-2">
          OpenAI-compatible contract — existing SDKs, LangChain and LlamaIndex work by
          changing only the base URL. Target: <span className="text-ink2">{targetLabel}</span>
        </p>
      </div>

      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-sm font-medium">Integration test suite</h2>
            <p className="text-xs text-muted mt-0.5">
              Verifies your endpoint end-to-end before you ship (demo simulation)
            </p>
          </div>
          <button className="btn" onClick={runTests} disabled={busy}>
            {busy ? "Running…" : "Run tests"}
          </button>
        </div>

        {busy && <Spinner />}

        {report && (
          <>
            <div className={`rounded-lg px-4 py-2.5 mb-4 text-sm border ${
              report.overall === "pass"
                ? "border-good/40 text-good"
                : "border-warn/40 text-warn"
            }`}>
              {report.overall === "pass"
                ? `✓ All checks passed — ${report.model_name} is ready to integrate`
                : `⚠ Passed with warnings — review the flagged checks below`}
            </div>
            <div className="space-y-2">
              {report.checks.map((c) => (
                <div key={c.id}
                  className="flex items-start gap-3 rounded-lg border border-edge bg-raised/40 px-4 py-3">
                  <span className={`mt-0.5 text-sm ${c.status === "pass" ? "text-good" : "text-warn"}`}>
                    {c.status === "pass" ? "✓" : "⚠"}
                  </span>
                  <div>
                    <div className="text-sm">{c.label}</div>
                    <div className="text-xs text-muted mt-0.5">{c.detail}</div>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[11px] text-muted mt-4">
              Groundedness is judge-scored faithfulness against reference context —
              a measured metric, not a "no hallucination" guarantee. Production runs
              these checks against your live endpoint with your own probe set.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
