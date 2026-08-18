# Modelect agent

Installs on any OpenShift/Kubernetes cluster with GPUs and reports
real inventory into the Modelect control plane — outbound-only, no
kubeconfig leaves the cluster. Detects dedicated GPUs, **MIG slices**
and **time-sliced vGPUs** from the NVIDIA GPU Operator, so Modelect
schedules virtual GPU units instead of dedicating physical cards.

## Install (per GPU cluster)

```bash
# 0. Build/push the agent image once (from the repo root):
#    ./scripts/build-and-push.sh <quay-ns> <tag>   # now also builds modelect-agent

# 1. Get the enrollment token: GPU Fleet page (admin) -> "Connect a cluster",
#    or: curl -s -b <admin-session> https://<control-plane>/api/agents/token

# 2. Fill placeholders and apply (run against the GPU cluster):
sed -e 's|__CONTROL_PLANE_URL__|https://<your-modelect-route>|' \
    -e 's|__AGENT_TOKEN__|ma-...token-from-fleet-page...|' \
    -e 's|__CLUSTER_ID__|caaslab|' \
    -e 's|__QUAY_NS__|<your-quay-user>|' \
    install/modelect-agent.yaml | oc apply -f -

# 3. Watch it appear on the GPU Fleet page within ~30s, labeled "live agent".
oc -n modelect-agent logs deploy/modelect-agent -f
```

Self-signed lab routes: set `INSECURE_TLS: "1"` in the Deployment env.

## Virtual GPUs (share physical cards)

The agent reports whatever the NVIDIA GPU Operator exposes:

- **MIG**: enable a MIG profile on the node (e.g. `all-1g.10gb` via the
  operator's `mig.config` label) — each slice appears as its own pool,
  e.g. `A100-MIG-1g.10gb · 14 free`.
- **Time-slicing**: apply the operator's time-slicing ConfigMap
  (`replicas: 4`) — the agent reports 4 vGPUs per physical card,
  marked `time-sliced x4`.

Modelect places deployments against these virtual units, so several
models share one physical GPU.
