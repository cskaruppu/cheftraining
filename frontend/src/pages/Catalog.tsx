import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ModelInfo, api, fmtCompact } from "../lib/api";
import { PageHeader, ScoreBar, SourceBadge, Spinner } from "../components/ui";

interface RegistryEntry {
  id: string;
  name: string;
  org: string;
  registry: "huggingface" | "openrouter";
  source: "open" | "closed";
  license: string | null;
  downloads: number | null;
  likes: number | null;
  input_price: number | null;
  output_price: number | null;
  context_window: number | null;
  rated: boolean;
  url: string;
  matches_curated: string | null;
}

interface SyncInfo {
  registry: string;
  mode: string;
  count: number;
  synced_at: string;
}

const REGISTRY_LABEL: Record<string, string> = {
  huggingface: "🤗 Hugging Face",
  openrouter: "OpenRouter",
};

export default function Catalog() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [providers, setProviders] = useState<string[]>([]);
  const [entries, setEntries] = useState<RegistryEntry[]>([]);
  const [sync, setSync] = useState<SyncInfo[]>([]);
  const [q, setQ] = useState("");
  const [provider, setProvider] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  const [slmOnly, setSlmOnly] = useState(false);
  const [sources, setSources] = useState<Record<string, boolean>>({
    curated: true, huggingface: true, openrouter: true,
  });
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    Promise.all([
      api.models(),
      fetch("/api/registry/models?sources=huggingface,openrouter").then((r) => r.json()),
    ]).then(([d, reg]) => {
      setModels(d.models);
      setProviders(d.providers);
      setEntries(reg.entries);
      setSync(reg.sync);
      setLoaded(true);
    });
  }, []);

  // registry entries matching a curated model become "channels" on its card
  const channels = useMemo(() => {
    const map: Record<string, RegistryEntry[]> = {};
    for (const e of entries) {
      if (e.matches_curated) (map[e.matches_curated] ??= []).push(e);
    }
    return map;
  }, [entries]);

  const filteredCurated = useMemo(
    () =>
      !sources.curated
        ? []
        : models.filter(
            (m) =>
              (!q || `${m.name} ${m.provider}`.toLowerCase().includes(q.toLowerCase())) &&
              (!provider || m.provider === provider) &&
              (!openOnly || m.source === "open") &&
              (!slmOnly || m.size_class === "slm"),
          ),
    [models, q, provider, openOnly, slmOnly, sources.curated],
  );

  const filteredRegistry = useMemo(
    () =>
      entries.filter(
        (e) =>
          sources[e.registry] &&
          !e.matches_curated && // deduped into channels on curated cards
          (!q || `${e.name} ${e.org}`.toLowerCase().includes(q.toLowerCase())) &&
          !provider &&
          (!openOnly || e.source === "open") &&
          !slmOnly,
      ),
    [entries, sources, q, provider, openOnly, slmOnly],
  );

  if (!loaded) return <Spinner />;

  const total = filteredCurated.length + filteredRegistry.length;

  return (
    <div>
      <PageHeader
        title="Model Catalog"
        sub="Curated, benchmarked models plus live entries from connected registries — one catalog for your whole ecosystem"
      />

      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="text-xs text-muted mr-1">Sources:</span>
        {[
          { id: "curated", label: `Curated (${models.length})` },
          { id: "huggingface", label: `🤗 Hugging Face (${entries.filter((e) => e.registry === "huggingface").length})` },
          { id: "openrouter", label: `OpenRouter (${entries.filter((e) => e.registry === "openrouter").length})` },
        ].map((s) => (
          <button
            key={s.id}
            onClick={() => setSources((x) => ({ ...x, [s.id]: !x[s.id] }))}
            className="chip !py-1 !px-3 !text-xs transition hover:!text-ink"
            style={sources[s.id] ? { borderColor: "#3987e5", color: "#fff" } : {}}
          >
            {s.label}
          </button>
        ))}
        <span className="text-[11px] text-muted ml-auto">
          {sync.map((s) => `${REGISTRY_LABEL[s.registry] ?? s.registry}: ${s.mode} · ${s.synced_at}`).join("  ·  ")}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-5">
        <input
          className="input w-64"
          placeholder="Search models, orgs, providers…"
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
          <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} className="accent-s1" />
          Open weights only
        </label>
        <label className="flex items-center gap-2 text-sm text-ink2 cursor-pointer">
          <input type="checkbox" checked={slmOnly} onChange={(e) => setSlmOnly(e.target.checked)} className="accent-s1" />
          SLMs only
        </label>
        <span className="text-xs text-muted ml-auto">{total} shown</span>
      </div>

      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        {filteredCurated.map((m) => {
          const avg = Object.values(m.quality).reduce((a, b) => a + b, 0) / 7;
          const ch = channels[m.id] ?? [];
          return (
            <div key={m.id} className="card flex flex-col gap-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium">{m.name}</div>
                  <div className="text-xs text-muted">
                    {m.provider}
                    {m.params_b && <> · {m.params_b}B params</>}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <SourceBadge model={m} />
                  {m.size_class === "slm" && <span className="chip border-s1/50 text-s1">SLM</span>}
                </div>
              </div>

              <ScoreBar value={avg} label="quality" />

              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-ink2">
                <div>In <span className="text-ink tabular-nums">${m.input_price.toFixed(2)}</span>/1M</div>
                <div>Out <span className="text-ink tabular-nums">${m.output_price.toFixed(2)}</span>/1M</div>
                <div>Context <span className="text-ink tabular-nums">{fmtCompact(m.context_window)}</span></div>
                <div>~<span className="text-ink tabular-nums">{m.latency_ms}</span> ms · <span className="text-ink tabular-nums">{m.throughput_tps}</span> tok/s</div>
              </div>

              <div className="flex flex-wrap gap-1.5 mt-auto">
                {m.capabilities.map((c) => (
                  <span key={c} className="chip">{c.replace("_", " ")}</span>
                ))}
                {m.self_hostable && <span className="chip border-s3/40 text-s3">self-host</span>}
              </div>

              {ch.length > 0 && (
                <div className="border-t border-edge pt-2 flex flex-wrap gap-1.5">
                  <span className="text-[10px] uppercase tracking-wide text-muted w-full">Also available via</span>
                  {ch.map((c) => (
                    <a key={c.id} href={c.url} target="_blank" rel="noreferrer"
                      className="chip hover:!text-ink transition"
                      title={c.registry === "openrouter" && c.input_price != null
                        ? `$${c.input_price}/$${c.output_price} per 1M via OpenRouter`
                        : "weights on Hugging Face"}>
                      {c.registry === "huggingface" ? "🤗 weights" : `API $${c.input_price?.toFixed(2)}/1M`}
                    </a>
                  ))}
                </div>
              )}
            </div>
          );
        })}

        {filteredRegistry.map((e) => (
          <div key={e.id} className="card flex flex-col gap-3 border-dashed">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-medium">{e.name}</div>
                <div className="text-xs text-muted">{e.org}</div>
              </div>
              <span className="chip">{REGISTRY_LABEL[e.registry]}</span>
            </div>

            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-ink2">
              {e.downloads != null && (
                <div>Downloads <span className="text-ink tabular-nums">{fmtCompact(e.downloads)}</span></div>
              )}
              {e.likes != null && (
                <div>Likes <span className="text-ink tabular-nums">{fmtCompact(e.likes)}</span></div>
              )}
              {e.input_price != null && (
                <div>In <span className="text-ink tabular-nums">${e.input_price.toFixed(2)}</span>/1M</div>
              )}
              {e.output_price != null && (
                <div>Out <span className="text-ink tabular-nums">${e.output_price.toFixed(2)}</span>/1M</div>
              )}
              {e.context_window != null && (
                <div>Context <span className="text-ink tabular-nums">{fmtCompact(e.context_window)}</span></div>
              )}
            </div>

            <div className="flex flex-wrap gap-1.5">
              {e.source === "open" && <span className="chip border-s3/40 text-s3">open weights</span>}
              {e.license && <span className="chip">{e.license}</span>}
              <span className="chip border-warn/40 text-warn">unrated</span>
            </div>

            <div className="flex items-center justify-between mt-auto pt-1">
              <Link to="/evals" className="text-xs text-s1 hover:underline">
                Run an Eval to rate it →
              </Link>
              <a href={e.url} target="_blank" rel="noreferrer" className="text-xs text-muted hover:text-ink2">
                view source ↗
              </a>
            </div>
          </div>
        ))}
      </div>

      <p className="text-[11px] text-muted mt-4">
        Curated models carry Modelect-verified profiles (benchmarks, sizing, serving costs).
        Registry entries are synced metadata only — quality is unrated until you eval them.
        Sync falls back to a bundled snapshot when the registry is unreachable.
      </p>
    </div>
  );
}
