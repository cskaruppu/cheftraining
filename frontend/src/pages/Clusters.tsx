import { useEffect, useState } from "react";
import { PageHeader, Spinner, StatTile } from "../components/ui";

interface GpuPool {
  family: string;
  type: string;
  count: number;
  used: number;
  free: number;
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
      <PageHeader
        title="GPU Fleet"
        sub="Every registered OpenShift and Kubernetes cluster with its live GPU inventory — one pane for your whole estate (simulated agents; production uses OCM/ACM-style pull agents)"
      />

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
                <span className="chip border-good/40 text-good">
                  ● agent · {c.last_heartbeat_s}s ago
                </span>
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
                        <span className="text-ink2">{g.type}</span>
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
