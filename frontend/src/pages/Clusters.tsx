import { useEffect, useState } from "react";
import { PageHeader, Sparkline, Spinner, StatTile } from "../components/ui";

interface GpuPool {
  family: string;
  type: string;
  count: number;
  used: number;
  free: number;
  virtual?: boolean;
  mode?: string;
  vram_gb?: number;
}

interface Cluster {
  id: string;
  name: string;
  platform: string;
  version: string;
  region: string;
  residency: string;
  cost_factor: number;
  labels: string[];
  gpus: GpuPool[];
  utilization_pct: number;
  agent_status: string;
  last_heartbeat_s: number;
  gpu_class?: "gpu-ready" | "gpu-unmanaged" | "cpu-only";
  operator_detected?: boolean;
  driver_version?: string;
  cuda_version?: string;
  cordoned?: boolean;
  util_history?: number[];
  carbon_kg_day?: number;
  fits?: { model_id: string; model_name: string; profile: string; quantization: string } | null;
  source: "agent" | "simulated";
}

const DEP_STATUS_CHIP: Record<string, string> = {
  running: "border-good/40 text-good",
  ready: "border-good/40 text-good",
  error: "border-crit/50 text-crit",
};

function ClassBadge({ c }: { c: Cluster }) {
  if (c.gpu_class === "gpu-unmanaged")
    return (
      <span className="chip border-warn/50 text-warn"
        title="NVIDIA GPUs detected but the GPU Operator is not exposing them — install/enable the GPU Operator to make this cluster schedulable">
        GPU · operator missing
      </span>
    );
  if (c.gpu_class === "cpu-only")
    return <span className="chip" title="no NVIDIA GPUs detected on any node">CPU-only</span>;
  return <span className="chip border-good/40 text-good" title="GPU Operator running, GPUs schedulable">GPU ready</span>;
}

interface DeploymentLite {
  id: string;
  name: string;
  model_name: string;
  cluster_id: string | null;
  status: string;
}

function ConnectWizard({ token, clusters }: { token: string; clusters: Cluster[] }) {
  const [step, setStep] = useState(1);
  const [clusterId, setClusterId] = useState("");
  const [region, setRegion] = useState("");
  const [residency, setResidency] = useState("us");
  const [quayNs, setQuayNs] = useState("");
  const [copied, setCopied] = useState("");

  const connected = clusters.find((c) => c.id === clusterId && c.source === "agent");
  const apiUrl = window.location.origin;
  const command = `sed -e 's|__CONTROL_PLANE_URL__|${apiUrl}|' \\
    -e 's|__AGENT_TOKEN__|${token}|' \\
    -e 's|__CLUSTER_ID__|${clusterId || "my-cluster"}|' \\
    -e 's|__QUAY_NS__|${quayNs || "<your-quay-user>"}|' \\
    agent/install/modelect-agent.yaml \\
  | oc apply -f -`;

  const copy = (text: string, tag: string) => {
    navigator.clipboard?.writeText(text);
    setCopied(tag);
    setTimeout(() => setCopied(""), 1500);
  };

  const StepDot = ({ n, label }: { n: number; label: string }) => (
    <button onClick={() => n < step && setStep(n)}
      className={`flex items-center gap-2 text-xs ${n === step ? "text-ink" : n < step ? "text-s3" : "text-muted"}`}>
      <span className={`h-5 w-5 rounded-full grid place-items-center text-[11px] font-medium border ${
        n === step ? "border-s1 text-s1" : n < step ? "border-s3/60 text-s3" : "border-edge"}`}>
        {n < step ? "✓" : n}
      </span>
      {label}
    </button>
  );

  return (
    <div className="card mb-6 border-s1/40">
      <div className="flex items-center gap-6 mb-5">
        <StepDot n={1} label="Cluster details" />
        <span className="h-px flex-1 bg-grid" />
        <StepDot n={2} label="Install the agent" />
        <span className="h-px flex-1 bg-grid" />
        <StepDot n={3} label="Verify connection" />
      </div>

      {step === 1 && (
        <div>
          <p className="text-xs text-ink2 mb-4">
            The agent installs on <span className="text-ink">any</span> OpenShift/Kubernetes
            cluster — with or without GPUs. Modelect classifies each cluster automatically
            (GPU ready / GPU present but operator missing / CPU-only) and only schedules
            models onto GPU-ready ones.
          </p>
          <div className="grid md:grid-cols-4 gap-3 mb-4">
            <div>
              <label className="text-xs text-muted block mb-1.5">Cluster ID *</label>
              <input className="input w-full" placeholder="e.g. caaslab" value={clusterId}
                onChange={(e) => setClusterId(e.target.value.trim())} />
            </div>
            <div>
              <label className="text-xs text-muted block mb-1.5">Region</label>
              <input className="input w-full" placeholder="e.g. lab / us-east" value={region}
                onChange={(e) => setRegion(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-muted block mb-1.5">Data residency</label>
              <select className="input w-full" value={residency} onChange={(e) => setResidency(e.target.value)}>
                <option value="us">us</option>
                <option value="eu">eu</option>
                <option value="asia">asia</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-muted block mb-1.5">Quay namespace *</label>
              <input className="input w-full" placeholder="where images live" value={quayNs}
                onChange={(e) => setQuayNs(e.target.value.trim())} />
            </div>
          </div>
          <button className="btn" disabled={!clusterId || !quayNs} onClick={() => setStep(2)}>
            Next: install command →
          </button>
        </div>
      )}

      {step === 2 && (
        <div>
          <div className="grid md:grid-cols-2 gap-3 mb-4">
            <div>
              <label className="text-xs text-muted block mb-1.5">Control plane API URL</label>
              <div className="flex items-center gap-2">
                <code className="bg-raised rounded px-2.5 py-1.5 text-xs text-ink2 flex-1 truncate">{apiUrl}</code>
                <button className="btn-ghost !py-1 !px-2.5 !text-xs" onClick={() => copy(apiUrl, "url")}>
                  {copied === "url" ? "✓" : "copy"}
                </button>
              </div>
            </div>
            <div>
              <label className="text-xs text-muted block mb-1.5">Enrollment token</label>
              <div className="flex items-center gap-2">
                <code className="bg-raised rounded px-2.5 py-1.5 text-xs text-ink2 flex-1 truncate">{token}</code>
                <button className="btn-ghost !py-1 !px-2.5 !text-xs" onClick={() => copy(token, "tok")}>
                  {copied === "tok" ? "✓" : "copy"}
                </button>
              </div>
            </div>
          </div>
          <label className="text-xs text-muted block mb-1.5">
            Run against the target cluster (logged in with cluster-admin):
          </label>
          <div className="relative">
            <button className="btn-ghost !py-1 !px-2.5 !text-xs absolute right-2 top-2"
              onClick={() => copy(command, "cmd")}>
              {copied === "cmd" ? "copied ✓" : "copy"}
            </button>
            <pre className="bg-page border border-edge rounded-lg px-3 py-2.5 text-[11.5px] leading-relaxed text-ink2 overflow-x-auto">{command}</pre>
          </div>
          <p className="text-[11px] text-muted mt-2">
            Outbound-only · read-only RBAC on nodes · self-signed routes: set{" "}
            <code className="text-ink2">INSECURE_TLS: "1"</code> in the agent env ·
            details in <code className="text-ink2">agent/README.md</code>
          </p>
          <button className="btn mt-3" onClick={() => setStep(3)}>
            I've applied it — verify →
          </button>
        </div>
      )}

      {step === 3 && (
        <div>
          {connected ? (
            <div className="rounded-lg border border-good/40 px-4 py-3">
              <div className="text-sm text-good mb-1">
                ✓ Connected — "{connected.name}" is reporting ({connected.last_heartbeat_s}s ago)
              </div>
              <div className="text-xs text-ink2">
                Classified as <ClassBadge c={connected} /> · {connected.gpus.length} GPU pool(s) ·{" "}
                {connected.platform} {connected.version}
                {connected.gpu_class === "gpu-ready" &&
                  " — this cluster is now a placement target for deployments."}
                {connected.gpu_class === "gpu-unmanaged" &&
                  " — install the NVIDIA GPU Operator to make its GPUs schedulable."}
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-edge px-4 py-3">
              <div className="flex items-center gap-2 text-sm text-ink2">
                <span className="h-4 w-4 rounded-full border-2 border-grid border-t-s1 animate-spin" />
                Waiting for the first heartbeat from "{clusterId}"… (checks every 5s;
                the agent reports ~30s after install)
              </div>
              <div className="text-[11px] text-muted mt-2">
                Not appearing? Check <code className="text-ink2">oc -n modelect-agent logs deploy/modelect-agent</code>{" "}
                — the usual causes are a wrong control-plane URL, TLS verification on a
                self-signed route, or a mistyped token.
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Clusters() {
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [deployments, setDeployments] = useState<DeploymentLite[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [agentToken, setAgentToken] = useState("");
  const [showConnect, setShowConnect] = useState(false);
  const [filter, setFilter] = useState<"all" | "gpu-ready" | "gpu-unmanaged" | "cpu-only" | "live">("all");

  const toggleCordon = async (c: Cluster) => {
    await fetch(`/api/clusters/${c.id}/cordon`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cordoned: !c.cordoned }),
    });
    refresh();
  };

  const refresh = () =>
    Promise.all([
      fetch("/api/clusters").then((r) => r.json()),
      fetch("/api/deployments").then((r) => r.json()),
    ]).then(([c, d]) => {
      setClusters(c.clusters);
      setDeployments(d.deployments);
      setLoaded(true);
    });

  useEffect(() => {
    refresh();
    fetch("/api/agents/token")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setAgentToken(d.token))
      .catch(() => {});
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, []);

  if (!loaded) return <Spinner />;

  const totalGpus = clusters.reduce((a, c) => a + c.gpus.reduce((x, g) => x + g.count, 0), 0);
  const freeGpus = clusters.reduce((a, c) => a + c.gpus.reduce((x, g) => x + g.free, 0), 0);
  const avgUtil = clusters.length
    ? Math.round(clusters.reduce((a, c) => a + c.utilization_pct, 0) / clusters.length)
    : 0;
  const hottest = clusters.reduce<Cluster | null>(
    (h, c) => (!h || c.utilization_pct > h.utilization_pct ? c : h), null);
  const staleAgents = clusters.filter(
    (c) => c.source === "agent" && c.agent_status !== "connected");
  const shown = clusters.filter((c) =>
    filter === "all" ? true :
    filter === "live" ? c.source === "agent" :
    (c.gpu_class ?? "gpu-ready") === filter);

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <PageHeader
          title="GPU Fleet"
          sub="Every registered OpenShift and Kubernetes cluster with its live GPU inventory — install the Modelect agent on any GPU cluster and it appears here"
        />
        {agentToken && (
          <button className="btn-ghost mt-1 shrink-0" onClick={() => setShowConnect(!showConnect)}>
            {showConnect ? "close" : "+ Connect a cluster"}
          </button>
        )}
      </div>

      {showConnect && agentToken && (
        <ConnectWizard token={agentToken} clusters={clusters} />
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatTile label="Clusters" value={clusters.length}
          hint={`${clusters.filter((c) => (c.gpu_class ?? "gpu-ready") === "gpu-ready").length} GPU-ready · ${clusters.filter((c) => c.gpu_class === "gpu-unmanaged").length} unmanaged · ${clusters.filter((c) => c.gpu_class === "cpu-only").length} CPU-only`} />
        <StatTile label="Total GPUs" value={totalGpus} hint={`${freeGpus} free for scheduling`} />
        <StatTile label="Fleet allocation" value={`${avgUtil}%`}
          hint={hottest
            ? `hottest: ${hottest.name.split("—")[0].trim()} at ${hottest.utilization_pct}% · allocated ≠ busy`
            : "allocated GPU slices, not measured load"} />
        <StatTile label="Models deployed" value={deployments.length} hint="fleet-wide" />
      </div>

      {staleAgents.length > 0 && (
        <div className="mb-4 border-l-2 border-warn rounded-r-lg bg-raised px-4 py-2.5 text-xs text-ink2">
          <span className="text-warn font-medium">
            {staleAgents.length} agent{staleAgents.length > 1 ? "s" : ""} stale:
          </span>{" "}
          {staleAgents.map((c) => c.name).join(", ")} — no recent heartbeat; their
          deployments are unreachable and placement skips them until they reconnect.
        </div>
      )}

      <div className="flex items-center gap-2 mb-4">
        <div className="flex rounded-lg border border-edge overflow-hidden">
          {(["all", "gpu-ready", "gpu-unmanaged", "cpu-only", "live"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-2.5 py-1 text-[11px] transition-colors ${
                f === filter ? "bg-raised text-ink" : "text-muted hover:text-ink2"}`}>
              {f === "live" ? "live agents" : f}
            </button>
          ))}
        </div>
        {filter !== "all" && (
          <span className="text-[11px] text-muted">{shown.length} of {clusters.length} clusters</span>
        )}
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        {shown.map((c) => {
          const deps = deployments.filter((d) => d.cluster_id === c.id);
          return (
            <div key={c.id}
              className={`card flex flex-col gap-3 ${c.cordoned ? "opacity-60 border-warn/40" : ""}`}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium">
                    {c.name}
                    {c.cordoned && (
                      <span className="chip !ml-2 !py-0 !text-[10px] border-warn/50 text-warn"
                        title="maintenance mode — placement skips this cluster">
                        ⏸ maintenance
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-muted">
                    {c.platform === "openshift" ? "OpenShift" : "Kubernetes"} {c.version} ·{" "}
                    {c.region}
                    {c.driver_version && (
                      <span title="NVIDIA driver / CUDA, from GPU Operator node labels">
                        {" "}· drv {c.driver_version}{c.cuda_version ? ` · CUDA ${c.cuda_version}` : ""}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className={`chip ${c.agent_status === "connected" ? "border-good/40 text-good" : "border-warn/40 text-warn"}`}>
                    ● agent · {c.last_heartbeat_s}s ago
                  </span>
                  {c.source === "agent" ? (
                    <span className="chip border-s1/50 text-s1">live agent</span>
                  ) : (
                    <span className="chip">simulated</span>
                  )}
                  <ClassBadge c={c} />
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5">
                <span className="chip">residency: {c.residency}</span>
                <span className="chip">cost {c.cost_factor}x</span>
                <span className="chip" title="0.4 kW per allocated GPU x regional grid factor — an estimate, refined by power telemetry in production">
                  ~{c.carbon_kg_day ?? 0} kg CO₂e/day
                </span>
                {c.labels.map((l) => (
                  <span key={l} className="chip">{l}</span>
                ))}
              </div>

              <div className="space-y-2">
                {c.gpus.map((g) => {
                  const pct = Math.round((g.used / g.count) * 100);
                  return (
                    <div key={g.family}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-ink2">
                          {g.type}
                          {g.vram_gb && !g.type.includes("GB") ? (
                            <span className="text-muted"> · {g.vram_gb}GB</span>
                          ) : null}
                          {g.virtual && (
                            <span className="chip !ml-1.5 !py-0 !px-1.5 !text-[10px] border-s3/50 text-s3"
                              title={`virtual GPUs (${g.mode}) — several models share one physical card`}>
                              vGPU
                            </span>
                          )}
                        </span>
                        <span className="text-muted tabular-nums">
                          {g.used}/{g.count} used · {g.free} free
                        </span>
                      </div>
                      <div className="h-1.5 rounded-full bg-grid overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${pct}%`,
                            background: pct >= 90 ? "#d03b3b" : pct >= 70 ? "#fab219" : "#3987e5",
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>

              {(c.util_history?.length ?? 0) >= 2 && (
                <div className="flex items-center justify-between gap-2 text-[10px] text-muted"
                  title="allocation history, sampled every 10 minutes">
                  <span>allocation · 24h</span>
                  <Sparkline values={c.util_history!} color="#3987e5" />
                </div>
              )}

              <div className="text-[11px] border border-edge rounded-lg px-2.5 py-2"
                title="admission preview from the placement engine — the largest self-hostable model this cluster can still schedule right now">
                {c.cordoned ? (
                  <span className="text-muted">in maintenance — not accepting deployments</span>
                ) : c.fits ? (
                  <>
                    <span className="text-muted">fits up to: </span>
                    <span className="text-ink">{c.fits.model_name}</span>
                    <span className="text-muted"> · {c.fits.profile} ({c.fits.quantization})</span>
                  </>
                ) : (
                  <span className="text-muted">no free GPU capacity for any serving profile</span>
                )}
              </div>

              <div className="border-t border-edge pt-3 mt-auto">
                <div className="flex items-center justify-between mb-1.5">
                  <div className="text-xs text-muted">Deployments ({deps.length})</div>
                  <button className="chip !text-[10px] hover:!text-ink transition"
                    title={c.cordoned
                      ? "return this cluster to the schedulable pool"
                      : "maintenance mode: keep it visible but stop new placements"}
                    onClick={() => toggleCordon(c)}>
                    {c.cordoned ? "uncordon" : "cordon"}
                  </button>
                </div>
                {deps.length === 0 ? (
                  <div className="text-xs text-muted">none scheduled here yet</div>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {deps.map((d) => (
                      <span key={d.id}
                        className={`chip ${DEP_STATUS_CHIP[d.status] ?? "border-warn/40 text-warn"}`}
                        title={`status: ${d.status}`}>
                        {d.name}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-[11px] text-muted mt-4">
        Inventory reported by cluster agents (NVIDIA GPU Operator node labels). Utilization
        colors: blue &lt;70%, amber 70-90%, red &ge;90%. GPU allocations update live as
        deployments are created and deleted.
      </p>
    </div>
  );
}
