import { useEffect, useState } from "react";
import { PageHeader, Spinner } from "../components/ui";

interface ConfigEntry {
  key: string;
  value: number;
  label: string;
  description: string;
  min_value: number;
  max_value: number;
}

interface SystemInfo {
  db_backend: string;
  data_dir: string;
  analytics_events: number;
  deployments: number;
  version: string;
}

interface SyncInfo {
  registry: string;
  mode: string;
  count: number;
  synced_at: string;
}

export default function Settings() {
  const [entries, setEntries] = useState<ConfigEntry[]>([]);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [sync, setSync] = useState<SyncInfo[]>([]);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [outage, setOutage] = useState<{ provider: string | null; providers: string[] } | null>(null);
  const [webhook, setWebhook] = useState("");
  const [webhookSaved, setWebhookSaved] = useState(false);

  useEffect(() => {
    fetch("/api/admin/outage").then((r) => r.json()).then(setOutage).catch(() => {});
    fetch("/api/admin/webhook").then((r) => r.json())
      .then((w) => setWebhook(w.url ?? "")).catch(() => {});
  }, []);

  const setDrill = async (provider: string | null) => {
    const r = await fetch("/api/admin/outage", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    }).then((x) => x.json());
    setOutage((o) => (o ? { ...o, provider: r.provider } : o));
  };

  const saveWebhook = async () => {
    await fetch("/api/admin/webhook", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: webhook.trim() || null }),
    });
    setWebhookSaved(true);
    setTimeout(() => setWebhookSaved(false), 1500);
  };

  useEffect(() => {
    Promise.all([
      fetch("/api/config").then((r) => r.json()),
      fetch("/api/system").then((r) => r.json()),
      fetch("/api/registry/models?sources=huggingface,openrouter").then((r) => r.json()),
    ]).then(([c, s, reg]) => {
      setEntries(c.entries);
      setSystem(s);
      setSync(reg.sync);
    });
  }, []);

  const save = async () => {
    setBusy(true);
    setErr("");
    setSaved(false);
    try {
      const values: Record<string, number> = {};
      for (const [k, v] of Object.entries(edits)) {
        if (v !== "") values[k] = Number(v);
      }
      const r = await fetch("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values }),
      });
      if (!r.ok) {
        setErr((await r.json()).detail ?? "save failed");
        return;
      }
      const c = await fetch("/api/config").then((x) => x.json());
      setEntries(c.entries);
      setEdits({});
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setBusy(false);
    }
  };

  if (!entries.length || !system) return <Spinner />;

  return (
    <div>
      <PageHeader
        title="Settings"
        sub="Business assumptions are server-side data, not code — tune them here and every engine picks them up instantly, no redeploy"
      />

      <div className="grid lg:grid-cols-[1fr_340px] gap-5">
        <div className="card">
          <h2 className="text-sm font-medium mb-4">Platform configuration</h2>
          <div className="space-y-5">
            {entries.map((e) => (
              <div key={e.key} className="grid md:grid-cols-[240px_1fr] gap-3 items-start">
                <div>
                  <div className="text-sm text-ink">{e.label}</div>
                  <div className="text-[11px] text-muted mt-0.5">{e.description}</div>
                </div>
                <div className="flex items-center gap-3">
                  <input
                    className="input w-32 tabular-nums"
                    value={edits[e.key] ?? String(e.value)}
                    onChange={(ev) => setEdits({ ...edits, [e.key]: ev.target.value })}
                  />
                  <span className="text-[11px] text-muted">
                    range {e.min_value}–{e.max_value}
                  </span>
                </div>
              </div>
            ))}
          </div>
          {err && <div className="text-sm text-crit mt-4">{err}</div>}
          <div className="flex items-center gap-3 mt-5">
            <button className="btn" onClick={save}
              disabled={busy || Object.keys(edits).length === 0}>
              {busy ? "Saving…" : "Save changes"}
            </button>
            {saved && <span className="text-sm text-good">✓ saved — live immediately</span>}
          </div>
        </div>

        <div className="space-y-4">
          <div className="card">
            <h2 className="text-sm font-medium mb-3">System</h2>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-muted">Database</span>
                <span className="text-ink2">
                  {system.db_backend}
                  {system.db_backend === "sqlite" && (
                    <span className="text-muted"> (set DATABASE_URL for PostgreSQL)</span>
                  )}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Analytics events</span>
                <span className="text-ink2 tabular-nums">{system.analytics_events.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Deployments</span>
                <span className="text-ink2 tabular-nums">{system.deployments}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">Version</span>
                <span className="text-ink2">{system.version}</span>
              </div>
            </div>
            <p className="text-[11px] text-muted mt-3 border-t border-edge/50 pt-2.5">
              <span className="text-good">Privacy:</span> prompt and response contents
              are never stored — the platform records only token counts, latency, cost
              and routing decisions.
            </p>
          </div>

          <div className="card">
            <h2 className="text-sm font-medium mb-1.5">Resilience drill</h2>
            <p className="text-[11px] text-muted mb-3">
              Declare a provider down and the gateway fails its traffic over to the
              closest comparable model — receipted and ledgered. Prove failover works
              before an outage proves it for you.
            </p>
            {outage && (
              <div className="flex flex-wrap items-center gap-2">
                <select className="input !py-1.5 text-sm"
                  value={outage.provider ?? ""}
                  onChange={(e) => setDrill(e.target.value || null)}>
                  <option value="">no drill — all providers up</option>
                  {outage.providers.map((p) => (
                    <option key={p} value={p}>{p} down</option>
                  ))}
                </select>
                {outage.provider && (
                  <span className="chip !text-[10px] border-crit/50 text-crit">
                    drill active: {outage.provider} traffic failing over
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="card">
            <h2 className="text-sm font-medium mb-1.5">Alert webhook</h2>
            <p className="text-[11px] text-muted mb-3">
              New critical attention items are pushed here as a Slack-compatible{" "}
              <code className="text-ink2">{'{"text": …}'}</code> POST — deduped, so a
              standing condition alerts once.
            </p>
            <div className="flex gap-2">
              <input className="input !py-1.5 text-sm flex-1"
                placeholder="https://hooks.slack.com/services/…"
                value={webhook} onChange={(e) => setWebhook(e.target.value)} />
              <button className="btn !text-xs" onClick={saveWebhook}>
                {webhookSaved ? "✓ saved" : "Save"}
              </button>
            </div>
          </div>

          <div className="card">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-medium">Data sources</h2>
              <button
                className="btn-ghost !py-1 !px-3 !text-xs"
                onClick={async () => {
                  const r = await fetch("/api/registry/sync", { method: "POST" });
                  const d = await r.json();
                  setSync(d.sync);
                }}
              >
                Sync now
              </button>
            </div>
            <div className="space-y-2">
              {sync.map((s) => (
                <div key={s.registry}
                  className="flex items-center justify-between rounded-lg border border-edge bg-raised/40 px-3 py-2 text-xs">
                  <span className="text-ink2">
                    {s.registry === "huggingface" ? "🤗 Hugging Face" : "OpenRouter"}
                  </span>
                  <span className="text-muted">
                    <span className={s.mode === "live" ? "text-good" : "text-warn"}>
                      {s.mode}
                    </span>{" "}
                    · {s.count} models · {s.synced_at}
                  </span>
                </div>
              ))}
            </div>
            <p className="text-[11px] text-muted mt-3">
              "snapshot" means the registry was unreachable and the bundled
              fallback is serving — sync retries automatically per the TTL.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
