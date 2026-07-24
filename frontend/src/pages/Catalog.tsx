import { useEffect, useMemo, useState } from "react";
import { ModelInfo, api, fmtCompact } from "../lib/api";
import { PageHeader, ScoreBar, SourceBadge, Spinner } from "../components/ui";

export default function Catalog() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [providers, setProviders] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [provider, setProvider] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.models().then((d) => {
      setModels(d.models);
      setProviders(d.providers);
      setLoaded(true);
    });
  }, []);

  const filtered = useMemo(
    () =>
      models.filter(
        (m) =>
          (!q || `${m.name} ${m.provider}`.toLowerCase().includes(q.toLowerCase())) &&
          (!provider || m.provider === provider) &&
          (!openOnly || m.source === "open"),
      ),
    [models, q, provider, openOnly],
  );

  if (!loaded) return <Spinner />;

  return (
    <div>
      <PageHeader
        title="Model Catalog"
        sub={`${models.length} models across ${providers.length} providers — auto-synced registry (demo seed)`}
      />

      <div className="flex flex-wrap items-center gap-3 mb-5">
        <input
          className="input w-64"
          placeholder="Search models or providers…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select className="input" value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="">All providers</option>
          {providers.map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-ink2 cursor-pointer">
          <input
            type="checkbox"
            checked={openOnly}
            onChange={(e) => setOpenOnly(e.target.checked)}
            className="accent-s1"
          />
          Open weights only
        </label>
        <span className="text-xs text-muted ml-auto">{filtered.length} shown</span>
      </div>

      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        {filtered.map((m) => {
          const avg = Object.values(m.quality).reduce((a, b) => a + b, 0) / 7;
          return (
            <div key={m.id} className="card flex flex-col gap-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium">{m.name}</div>
                  <div className="text-xs text-muted">{m.provider}</div>
                </div>
                <SourceBadge model={m} />
              </div>

              <ScoreBar value={avg} label="quality" />

              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-ink2">
                <div>
                  In <span className="text-ink tabular-nums">${m.input_price.toFixed(2)}</span>/1M
                </div>
                <div>
                  Out <span className="text-ink tabular-nums">${m.output_price.toFixed(2)}</span>/1M
                </div>
                <div>
                  Context <span className="text-ink tabular-nums">{fmtCompact(m.context_window)}</span>
                </div>
                <div>
                  ~<span className="text-ink tabular-nums">{m.latency_ms}</span> ms ·{" "}
                  <span className="text-ink tabular-nums">{m.throughput_tps}</span> tok/s
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5 mt-auto">
                {m.capabilities.map((c) => (
                  <span key={c} className="chip">
                    {c.replace("_", " ")}
                  </span>
                ))}
                {m.self_hostable && <span className="chip border-s3/40 text-s3">self-host</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
