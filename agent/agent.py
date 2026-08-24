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
import urllib.error
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
    driver_version = ""        # from GPU Operator node labels
    cuda_version = ""
    for n in nodes:
        labels = n["metadata"].get("labels", {})
        if not driver_version:
            # nvidia.com/cuda.driver.major/.minor/.rev -> "550.90.07"
            parts = [labels.get(f"nvidia.com/cuda.driver.{p}", "")
                     for p in ("major", "minor", "rev")]
            if parts[0]:
                driver_version = ".".join(p for p in parts if p)
        if not cuda_version:
            rt = [labels.get(f"nvidia.com/cuda.runtime.{p}", "")
                  for p in ("major", "minor")]
            if rt[0]:
                cuda_version = ".".join(p for p in rt if p)
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
        vram_gb = int(mem_mb) // 1024 if mem_mb.isdigit() else 0
        base_type = product.replace("-", " ") \
            + (f" {vram_gb}GB" if vram_gb else "")

        # Virtual GPUs, preferred over dedicating physical cards:
        # 1) MIG slices — allocatable resources like nvidia.com/mig-1g.10gb
        for res, qty in alloc.items():
            if res.startswith("nvidia.com/mig-") and int(qty) > 0:
                profile = res.removeprefix("nvidia.com/mig-")
                fam = f"{_family(product)}-MIG-{profile}"
                pool = pools.setdefault(fam, {
                    "family": fam,
                    "type": f"{base_type} · MIG {profile} slice",
                    "count": 0, "virtual": True, "mode": "mig",
                    **({"vram_gb": vram_gb} if vram_gb else {})})
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
                "mode": "time-slice" if sliced else "dedicated",
                **({"vram_gb": vram_gb} if vram_gb else {})})
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
        "driver_version": driver_version,
        "cuda_version": cuda_version,
    }


def _cp_ctx():
    if os.environ.get("INSECURE_TLS") == "1":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


def _cp_call(path: str, payload: dict | None = None, method: str = "POST"):
    url = os.environ["MODELECT_URL"].rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "X-Agent-Token": os.environ["MODELECT_AGENT_TOKEN"]})
    with urllib.request.urlopen(req, context=_cp_ctx(), timeout=20) as resp:
        return json.load(resp)


def report(payload: dict):
    return _cp_call("/api/agent/report", payload)


# ------------------- serving execution (Phase B2) ----------------------
NAMESPACE = os.environ.get("AGENT_NAMESPACE", "modelect-agent")
SERVING_IMAGE = os.environ.get("SERVING_IMAGE", "vllm/vllm-openai:latest")


def _kube_write(method: str, path: str, body: dict | None = None) -> int:
    with open(f"{SA_DIR}/token") as f:
        token = f.read().strip()
    ctx = ssl.create_default_context(cafile=f"{SA_DIR}/ca.crt")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        KUBE_HOST + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        if e.code in (404, 409):  # missing on delete / already exists
            return e.code
        raise


def _serving_manifests(order: dict, openshift: bool) -> list[tuple[str, dict]]:
    name = f"modelect-{order['id']}"
    labels = {"app": name, "app.kubernetes.io/part-of": "modelect"}
    dep = {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": name, "labels": labels},
        "spec": {
            "replicas": 1, "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": labels},
                "spec": {"containers": [{
                    "name": "vllm", "image": SERVING_IMAGE,
                    "args": ["--model", order["hf_repo"],
                             "--served-model-name", order["model_id"],
                             "--max-model-len", "8192"],
                    "ports": [{"containerPort": 8000}],
                    "env": ([{"name": "HUGGING_FACE_HUB_TOKEN",
                              "valueFrom": {"secretKeyRef": {
                                  "name": "hf-token", "key": "token",
                                  "optional": True}}}]),
                    "resources": {"limits": {"nvidia.com/gpu": order["gpu_count"]}},
                    "readinessProbe": {"httpGet": {"path": "/health", "port": 8000},
                                       "initialDelaySeconds": 30,
                                       "periodSeconds": 15},
                }]},
            },
        },
    }
    svc = {"apiVersion": "v1", "kind": "Service",
           "metadata": {"name": name, "labels": labels},
           "spec": {"selector": {"app": name},
                    "ports": [{"port": 8000, "targetPort": 8000}]}}
    out = [(f"/apis/apps/v1/namespaces/{NAMESPACE}/deployments", dep),
           (f"/api/v1/namespaces/{NAMESPACE}/services", svc)]
    if openshift:
        route = {"apiVersion": "route.openshift.io/v1", "kind": "Route",
                 "metadata": {"name": name, "labels": labels},
                 "spec": {"to": {"kind": "Service", "name": name},
                          "port": {"targetPort": 8000}}}
        out.append((f"/apis/route.openshift.io/v1/namespaces/{NAMESPACE}/routes", route))
    return out


def _order_endpoint(order: dict, openshift: bool) -> str:
    name = f"modelect-{order['id']}"
    if openshift:
        try:
            r = _kube_get(f"/apis/route.openshift.io/v1/namespaces/{NAMESPACE}/routes/{name}")
            host = r.get("spec", {}).get("host")
            if host:
                return f"http://{host}"
        except Exception:
            pass
    return f"http://{name}.{NAMESPACE}.svc:8000"


def _order_state(order: dict) -> str:
    name = f"modelect-{order['id']}"
    try:
        d = _kube_get(f"/apis/apps/v1/namespaces/{NAMESPACE}/deployments/{name}")
    except Exception:
        return "starting"
    status = d.get("status", {})
    if status.get("availableReplicas", 0) >= 1:
        return "ready"
    return "pulling"  # image pull + weight download dominate startup


def process_work(openshift: bool):
    orders = _cp_call(f"/api/agent/work?cluster_id={os.environ['CLUSTER_ID']}",
                      method="GET")["orders"]
    for order in orders:
        name = f"modelect-{order['id']}"
        try:
            if order["action"] == "delete":
                for kind, path in [
                        ("deployments", f"/apis/apps/v1/namespaces/{NAMESPACE}/deployments/{name}"),
                        ("services", f"/api/v1/namespaces/{NAMESPACE}/services/{name}"),
                        ("routes", f"/apis/route.openshift.io/v1/namespaces/{NAMESPACE}/routes/{name}")]:
                    _kube_write("DELETE", path)
                _cp_call(f"/api/agent/work/{order['id']}", {"state": "deleted"})
                print(f"work {order['id']}: deleted {name}", flush=True)
                continue
            if not order["hf_repo"]:
                _cp_call(f"/api/agent/work/{order['id']}",
                         {"state": "error", "message": "model has no HF repo mapping"})
                continue
            if order["state"] == "pending":
                for path, body in _serving_manifests(order, openshift):
                    _kube_write("POST", path, body)
                _cp_call(f"/api/agent/work/{order['id']}", {"state": "starting"})
                print(f"work {order['id']}: applied {name}", flush=True)
            else:
                state = _order_state(order)
                payload = {"state": state}
                if state == "ready":
                    payload["endpoint"] = _order_endpoint(order, openshift)
                _cp_call(f"/api/agent/work/{order['id']}", payload)
        except Exception as e:
            try:
                _cp_call(f"/api/agent/work/{order['id']}",
                         {"state": "error", "message": str(e)[:280]})
            except Exception:
                pass
            print(f"work {order['id']} failed: {e}", file=sys.stderr, flush=True)


def main():
    for var in ("MODELECT_URL", "MODELECT_AGENT_TOKEN", "CLUSTER_ID"):
        if not os.environ.get(var):
            print(f"FATAL: {var} is required", file=sys.stderr)
            sys.exit(1)
    interval = int(os.environ.get("INTERVAL_S", "30"))
    print(f"modelect-agent starting: cluster={os.environ['CLUSTER_ID']} "
          f"-> {os.environ['MODELECT_URL']} every {interval}s", flush=True)
    while True:
        openshift = False
        try:
            payload = collect()
            openshift = payload["platform"] == "openshift"
            result = report(payload)
            gpus = ", ".join(f"{g['count']}x {g['family']}" for g in payload["gpus"]) or "no GPUs"
            print(f"reported: {payload['nodes']} nodes · {gpus} · {result}", flush=True)
        except Exception as e:  # keep heartbeating through transient errors
            print(f"report failed: {e}", file=sys.stderr, flush=True)
        try:
            process_work(openshift)
        except Exception as e:
            print(f"work loop failed: {e}", file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
