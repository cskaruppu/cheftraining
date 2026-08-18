import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ModelInfo, api } from "../lib/api";
import { PageHeader, Spinner } from "../components/ui";

interface Profile {
  id: string;
  gpus: string;
  quantization: string;
  est_cost_hr: number;
  est_cost_month: number;
  est_throughput_tps: number;
  recommended: boolean;
}

interface Deployment {
  id: string;
  name: string;
  model_id: string;
  model_name: string;
  profile: Profile;
  api_key: string;
  cluster_id: string | null;
  cluster_name: string | null;
  status: string;
  progress: number;
  backend: "simulated" | "agent";
  real_endpoint: string;
  message: string;
  endpoint_path: string;
}

interface Placement {
  recommended: { cluster_id: string; cluster_name: string; reasons: string[] } | null;
  clusters: { cluster_id: string; cluster_name: string; eligible: boolean; reasons: string[] }[];
  requirement: string;
}

const STAGES = [
  { key: "scheduling", label: "Scheduling" },
  { key: "pulling_weights", label: "Pulling weights" },
  { key: "warming_up", label: "Warming up" },
  { key: "ready", label: "Ready" },
];

async function fetchProfiles(modelId: string): Promise<Profile[]> {
  const r = await fetch(`/api/models/${modelId}/profiles`);
  return (await r.json()).profiles;
}

async function fetchDeployments(): Promise<Deployment[]> {
  const r = await fetch("/api/deployments");
  return (await r.json()).deployments;
}

export default function Deploy() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelId, setModelId] = useState("");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profileId, setProfileId] = useState("");
  const [name, setName] = useState("");
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState("");
  const [cluster, setCluster] = useState("auto");
  const [clusterList, setClusterList] = useState<{ id: string; name: string }[]>([]);
  const [placement, setPlacement] = useState<Placement | null>(null);
  const [err, setErr] = useState("");

  const hostable = useMemo(() => models.filter((m) => m.self_hostable), [models]);
  const [params] = useSearchParams();

  useEffect(() => {
    api.models().then((d) => {
      setModels(d.models);
      // honor ?model=<id> handoff (e.g. from the Migrate page CTA)
      const wanted = params.get("model");
      const preselect =
        d.models.find((m) => m.self_hostable && m.id === wanted) ??
        d.models.find((m) => m.self_hostable);
      if (preselect) setModelId(preselect.id);
    });
    fetchDeployments().then(setDeployments);
    fetch("/api/clusters")
      .then((r) => r.json())
      .then((d) => setClusterList(d.clusters.map((c: any) => ({ id: c.id, name: c.name }))));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // fleet placement preview whenever model/profile changes
  useEffect(() => {
    if (!modelId || !profileId) return;
    fetch("/api/placement", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId, profile_id: profileId }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then(setPlacement)
      .catch(() => setPlacement(null));
  }, [modelId, profileId]);

  useEffect(() => {
    if (!modelId) return;
    fetchProfiles(modelId).then((p) => {
      setProfiles(p);
      setProfileId(p.find((x) => x.recommended)?.id ?? p[0]?.id ?? "");
    });
  }, [modelId]);

  // poll while any deployment is still provisioning
  useEffect(() => {
    const pending = deployments.some((d) => d.status !== "ready");
    if (!pending) return;
    const t = setInterval(() => fetchDeployments().then(setDeployments), 2000);
    return () => clearInterval(t);
  }, [deployments]);

  const deploy = async () => {
    setBusy(true);
    setErr("");
    try {
      const r = await fetch("/api/deployments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_id: modelId, profile_id: profileId, name,
          cluster_id: cluster === "auto" ? null : cluster,
        }),
      });
      if (!r.ok) {
        setErr((await r.json()).detail ?? "deployment failed");
        return;
      }
      setName("");
      setDeployments(await fetchDeployments());
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    await fetch(`/api/deployments/${id}`, { method: "DELETE" });
    setDeployments(await fetchDeployments());
  };

  const copy = (text: string, tag: string) => {
    navigator.clipboard?.writeText(text);
    setCopied(tag);
    setTimeout(() => setCopied(""), 1500);
  };

  if (!models.length) return <Spinner />;

  const model = models.find((m) => m.id === modelId);

  return (
    <div>
      <PageHeader
        title="Deploy a Model"
        sub="Provision a private LLM like you provision a VM — pick a model, pick a serving profile, get an endpoint (demo simulation; production creates a vLLM/KServe service on your cluster)"
      />

      <div className="card mb-6">
        <div className="grid md:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="text-xs text-muted block mb-1.5">
              Model (open weights — deployable on your GPUs)
            </label>
            <select className="input w-full" value={modelId} onChange={(e) => setModelId(e.target.value)}>
              {hostable.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} — {m.provider}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted block mb-1.5">Deployment name</label>
            <input
              className="input w-full"
              placeholder={`${modelId || "model"}-prod`}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
        </div>

        <label className="text-xs text-muted block mb-2">Serving profile</label>
        <div className="grid md:grid-cols-3 gap-3 mb-4">
          {profiles.map((p) => (
            <button
              key={p.id}
              onClick={() => setProfileId(p.id)}
              className={`text-left rounded-xl border p-4 transition ${
                profileId === p.id ? "border-s1 bg-raised" : "border-edge bg-raised/40 hover:border-muted"
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium capitalize">{p.id}</span>
                {p.recommended && <span className="chip border-s1/50 text-s1">recommended</span>}
              </div>
              <div className="text-xs text-ink2">{p.gpus}</div>
              <div className="text-xs text-muted mb-2">{p.quantization} · ~{p.est_throughput_tps} tok/s</div>
              <div className="text-sm tabular-nums">
                ${p.est_cost_hr.toFixed(2)}/hr
                <span className="text-muted text-xs"> · ~${p.est_cost_month.toFixed(0)}/mo</span>
              </div>
            </button>
          ))}
        </div>

        <div className="grid md:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="text-xs text-muted block mb-1.5">Target cluster</label>
            <select className="input w-full" value={cluster} onChange={(e) => setCluster(e.target.value)}>
              <option value="auto">Auto — fleet placement engine decides</option>
              {clusterList.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          {cluster === "auto" && placement && (
            <div className="rounded-xl border border-edge bg-raised/40 px-4 py-3 text-xs">
              {placement.recommended ? (
                <>
                  <div className="text-s1 mb-1">
                    → will schedule on {placement.recommended.cluster_name}
                  </div>
                  <div className="text-muted">
                    {placement.recommended.reasons.join(" · ")}
                  </div>
                </>
              ) : (
                <div className="text-warn">
                  No cluster currently has {placement.requirement} free — pick a smaller
                  profile or free capacity.
                </div>
              )}
            </div>
          )}
        </div>

        {err && <div className="text-sm text-crit mb-3">{err}</div>}
        <button className="btn" onClick={deploy} disabled={busy || !modelId || !profileId}>
          {busy ? "Deploying…" : `Deploy ${model?.name ?? ""}`}
        </button>
      </div>

      <h2 className="text-sm font-medium mb-3">
        Deployments {deployments.length > 0 && <span className="text-muted">({deployments.length})</span>}
      </h2>
      {deployments.length === 0 && (
        <div className="card text-sm text-muted">
          Nothing deployed yet — provision your first model above.
        </div>
      )}

      <div className="space-y-4">
        {deployments.map((d) => {
          const stageIdx = STAGES.findIndex((s) => s.key === d.status);
          const ready = d.status === "ready";
          const curl = `curl -sk ${window.location.origin}${d.endpoint_path} \\\n  -H 'Authorization: Bearer ${d.api_key}' \\\n  -H 'Content-Type: application/json' \\\n  -d '{"model":"${d.model_id}","messages":[{"role":"user","content":"hello"}]}'`;
          return (
            <div key={d.id} className="card">
              <div className="flex items-start justify-between gap-3 mb-3">
                <div>
                  <div className="font-medium">{d.name}</div>
                  <div className="text-xs text-muted">
                    {d.model_name} · {d.profile.gpus} · {d.profile.quantization} · $
                    {d.profile.est_cost_hr.toFixed(2)}/hr
                    {d.cluster_name && (
                      <> · <span className="text-ink2">{d.cluster_name}</span></>
                    )}
                    {d.backend === "agent" && (
                      <span className="chip !ml-2 !py-0 !px-1.5 !text-[10px] border-s3/50 text-s3"
                        title={d.real_endpoint
                          ? `real vLLM serving at ${d.real_endpoint} — the gateway proxies to it`
                          : "executed by the cluster's Modelect agent (real vLLM pod)"}>
                        live vLLM
                      </span>
                    )}
                    {d.status === "error" && d.message && (
                      <span className="text-crit"> · {d.message}</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {ready ? (
                    <span className="chip border-good/50 text-good">● running</span>
                  ) : (
                    <span className="chip border-warn/50 text-warn">provisioning {d.progress}%</span>
                  )}
                  <button className="btn-ghost !py-1 !px-3 !text-xs" onClick={() => remove(d.id)}>
                    Delete
                  </button>
                </div>
              </div>

              <div className="flex items-center gap-2 mb-1">
                {STAGES.map((s, i) => (
                  <div key={s.key} className="flex-1">
                    <div
                      className={`h-1.5 rounded-full ${
                        i < stageIdx || ready ? "bg-s3" : i === stageIdx ? "bg-s1" : "bg-grid"
                      }`}
                    />
                    <div
                      className={`text-[10px] mt-1 ${
                        i === stageIdx && !ready ? "text-s1" : i <= stageIdx ? "text-ink2" : "text-muted"
                      }`}
                    >
                      {s.label}
                    </div>
                  </div>
                ))}
              </div>

              {ready && (
                <div className="mt-4 border-t border-edge pt-4 grid gap-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-muted w-16">Endpoint</span>
                    <code className="bg-raised rounded px-2 py-1 text-ink2">
                      {window.location.origin}{d.endpoint_path}
                    </code>
                    <button className="btn-ghost !py-0.5 !px-2 !text-[11px]"
                      onClick={() => copy(`${window.location.origin}${d.endpoint_path}`, `ep-${d.id}`)}>
                      {copied === `ep-${d.id}` ? "copied" : "copy"}
                    </button>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-muted w-16">API key</span>
                    <code className="bg-raised rounded px-2 py-1 text-ink2">
                      {d.api_key.slice(0, 8)}…{d.api_key.slice(-4)}
                    </code>
                    <button className="btn-ghost !py-0.5 !px-2 !text-[11px]"
                      onClick={() => copy(d.api_key, `key-${d.id}`)}>
                      {copied === `key-${d.id}` ? "copied" : "copy key"}
                    </button>
                  </div>
                  <div className="flex flex-wrap items-start gap-2">
                    <span className="text-muted w-16 pt-1">Try it</span>
                    <pre className="bg-raised rounded px-2 py-1.5 text-[11px] text-ink2 overflow-x-auto flex-1">{curl}</pre>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
