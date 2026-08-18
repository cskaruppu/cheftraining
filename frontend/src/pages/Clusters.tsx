import { useEffect, useState } from "react";
import { PageHeader, Spinner, StatTile } from "../components/ui";

interface GpuPool {
  family: string;
  type: string;
  count: number;
  used: number;
  free: number;
  virtual?: boolean;
  mode?: string;
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
  source: "agent" | "simulated";
}

interface DeploymentLite {
  id: string;
  name: string;
  model_name: string;
  cluster_id: string | null;
  status: string;
}

export default function Clusters() {
  const [clusters, setClusters] = useState<Cluster[]>([]);
  const [deployments, setDeployments] = useState<DeploymentLite[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [agentToken, setAgentToken] = useState("");
  const [showConnect, setShowConnect] = useState(false);

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
        <div className="card mb-6 border-s1/40">
          <h2 className="text-sm font-medium mb-2">Connect a GPU cluster</h2>
          <p className="text-xs text-ink2 mb-3">
            Run this against the cluster you want to register (outbound-only agent;
            read-only RBAC on nodes; detects dedicated GPUs, MIG slices and
            time-sliced vGPUs from the NVIDIA GPU Operator):
          </p>
          <pre className="bg-page border border-edge rounded-lg px-3 py-2.5 text-[11.5px] leading-relaxed text-ink2 overflow-x-auto">{`sed -e 's|__CONTROL_PLANE_URL__|${window.location.origin}|' \\
    -e 's|__AGENT_TOKEN__|${agentToken}|' \\
    -e 's|__CLUSTER_ID__|my-gpu-cluster|' \\
    -e 's|__QUAY_NS__|<your-quay-user>|' \\
    agent/install/modelect-agent.yaml | oc apply -f -`}</pre>
          <p className="text-[11px] text-muted mt-2">
            Enrollment token: <code className="text-ink2">{agentToken}</code> — full
            instructions in <code className="text-ink2">agent/README.md</code>. The
            cluster appears here within ~30 seconds, labeled "live agent".
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatTile label="Clusters" value={clusters.length} hint="all agents connected" />
        <StatTile label="Total GPUs" value={totalGpus} hint={`${freeGpus} free for scheduling`} />
        <StatTile label="Avg utilization" value={`${avgUtil}%`} hint="across the fleet" />
        <StatTile label="Models deployed" value={deployments.length} hint="fleet-wide" />
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        {clusters.map((c) => {
          const deps = deployments.filter((d) => d.cluster_id === c.id);
          return (
            <div key={c.id} className="card flex flex-col gap-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium">{c.name}</div>
                  <div className="text-xs text-muted">
                    {c.platform === "openshift" ? "OpenShift" : "Kubernetes"} {c.version} ·{" "}
                    {c.region}
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
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5">
                <span className="chip">residency: {c.residency}</span>
                <span className="chip">cost {c.cost_factor}x</span>
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

              <div className="border-t border-edge pt-3 mt-auto">
                <div className="text-xs text-muted mb-1.5">
                  Deployments ({deps.length})
                </div>
                {deps.length === 0 ? (
                  <div className="text-xs text-muted">none scheduled here yet</div>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {deps.map((d) => (
                      <span key={d.id} className="chip border-s1/40 text-ink2">
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
