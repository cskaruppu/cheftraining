"""Modelect agent — runs on any OpenShift/Kubernetes cluster with GPUs.

Reads GPU inventory from the Kubernetes node API (NVIDIA GPU Operator
labels + allocatable resources) and reports it to the Modelect control
plane on a heartbeat. Outbound-only: the agent dials out, nothing dials
in, no kubeconfig ever leaves the cluster.

Environment:
  MODELECT_URL          control plane base URL (required),
                        e.g. https://orchestrator-ui-....apps.../
  MODELECT_AGENT_TOKEN  enrollment token from the GPU Fleet page (required)
  CLUSTER_ID            stable id for this cluster (required, e.g. caaslab)
  CLUSTER_NAME          display name          (default: CLUSTER_ID)
  REGION / RESIDENCY    metadata for placement (default: "" )
  COST_FACTOR           relative GPU cost      (default: 1.0)
  INTERVAL_S            heartbeat seconds      (default: 30)
  INSECURE_TLS          "1" to skip TLS verify (self-signed lab routes)
"""
import json
import os
import sys
import time
import urllib.request
import ssl

KUBE_HOST = "https://kubernetes.default.svc"
SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"

# family extracted from nvidia.com/gpu.product, e.g.
# "NVIDIA-A100-SXM4-80GB" -> A100; "Tesla-T4" -> T4
_KNOWN_FAMILIES = ["H200", "H100", "A100", "A30", "A10", "L40S", "L4",
                   "T4", "V100", "GH200", "B200"]


def _kube_get(path: str) -> dict:
    with open(f"{SA_DIR}/token") as f:
        token = f.read().strip()
    ctx = ssl.create_default_context(cafile=f"{SA_DIR}/ca.crt")
    req = urllib.request.Request(
        KUBE_HOST + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.load(resp)


def _family(product: str) -> str:
    up = (product or "").upper().replace("-", " ")
    for fam in _KNOWN_FAMILIES:
        if fam in up:
            return fam
    return product or "GPU"


def collect() -> dict:
    nodes = _kube_get("/api/v1/nodes")["items"]
    version = _kube_get("/version").get("gitVersion", "")
    pools: dict[str, dict] = {}
    openshift = False
    gpu_hardware = False       # NVIDIA PCI device present (NFD label)
    operator_detected = False  # device plugin registered nvidia.com resources
    for n in nodes:
        labels = n["metadata"].get("labels", {})
        if any(k.startswith("node.openshift.io") or "openshift" in k for k in labels):
            openshift = True
        alloc = n.get("status", {}).get("allocatable", {})
        if (labels.get("feature.node.kubernetes.io/pci-10de.present") == "true"
                or labels.get("nvidia.com/gpu.present") == "true"
                or "nvidia.com/gpu.product" in labels):
            gpu_hardware = True
        if "nvidia.com/gpu" in alloc or any(k.startswith("nvidia.com/mig-") for k in alloc):
            operator_detected = True
            gpu_hardware = True
        product = labels.get("nvidia.com/gpu.product", "GPU")
        mem_mb = labels.get("nvidia.com/gpu.memory", "")
        base_type = product.replace("-", " ") \
            + (f" {int(mem_mb) // 1024}GB" if mem_mb.isdigit() else "")

        # Virtual GPUs, preferred over dedicating physical cards:
        # 1) MIG slices — allocatable resources like nvidia.com/mig-1g.10gb
        for res, qty in alloc.items():
            if res.startswith("nvidia.com/mig-") and int(qty) > 0:
                profile = res.removeprefix("nvidia.com/mig-")
                fam = f"{_family(product)}-MIG-{profile}"
                pool = pools.setdefault(fam, {
                    "family": fam,
                    "type": f"{base_type} · MIG {profile} slice",
                    "count": 0, "virtual": True, "mode": "mig"})
                pool["count"] += int(qty)

        # 2) whole-GPU resource — time-sliced replicas count as virtual
        count = int(alloc.get("nvidia.com/gpu", "0"))
        if count > 0:
            replicas = int(labels.get("nvidia.com/gpu.replicas", "1") or 1)
            sliced = replicas > 1
            fam = _family(product)
            pool = pools.setdefault(fam, {
                "family": fam,
                "type": base_type + (f" · time-sliced x{replicas}" if sliced else ""),
                "count": 0, "virtual": sliced,
                "mode": "time-slice" if sliced else "dedicated"})
            pool["count"] += count
    schedulable = sum(p["count"] for p in pools.values())
    if operator_detected and schedulable > 0:
        gpu_class = "gpu-ready"        # operator running, GPUs schedulable
    elif gpu_hardware:
        gpu_class = "gpu-unmanaged"    # GPUs present, operator missing/idle
    else:
        gpu_class = "cpu-only"
    return {
        "cluster_id": os.environ["CLUSTER_ID"],
        "name": os.environ.get("CLUSTER_NAME", os.environ["CLUSTER_ID"]),
        "platform": "openshift" if openshift else "kubernetes",
        "version": version,
        "region": os.environ.get("REGION", ""),
        "residency": os.environ.get("RESIDENCY", ""),
        "cost_factor": float(os.environ.get("COST_FACTOR", "1.0")),
        "nodes": len(nodes),
        "gpus": list(pools.values()),
        "gpu_class": gpu_class,
        "operator_detected": operator_detected,
        "gpu_hardware": gpu_hardware,
    }


def report(payload: dict):
    url = os.environ["MODELECT_URL"].rstrip("/") + "/api/agent/report"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Agent-Token": os.environ["MODELECT_AGENT_TOKEN"]})
    ctx = None
    if os.environ.get("INSECURE_TLS") == "1":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.load(resp)


def main():
    for var in ("MODELECT_URL", "MODELECT_AGENT_TOKEN", "CLUSTER_ID"):
        if not os.environ.get(var):
            print(f"FATAL: {var} is required", file=sys.stderr)
            sys.exit(1)
    interval = int(os.environ.get("INTERVAL_S", "30"))
    print(f"modelect-agent starting: cluster={os.environ['CLUSTER_ID']} "
          f"-> {os.environ['MODELECT_URL']} every {interval}s", flush=True)
    while True:
        try:
            payload = collect()
            result = report(payload)
            gpus = ", ".join(f"{g['count']}x {g['family']}" for g in payload["gpus"]) or "no GPUs"
            print(f"reported: {payload['nodes']} nodes · {gpus} · {result}", flush=True)
        except Exception as e:  # keep heartbeating through transient errors
            print(f"report failed: {e}", file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
