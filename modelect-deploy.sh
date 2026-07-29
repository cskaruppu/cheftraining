#!/usr/bin/env bash
# ============================================================================
#  Modelect — single-file build & deploy
#  Builds both images, pushes to quay.io, deploys to OpenShift or
#  Kubernetes (manifests embedded — no other files needed), waits for
#  rollout and prints the dashboard URL.
#
#  Usage:
#    ./modelect-deploy.sh <quay-namespace> [tag]          deploy (default)
#    ./modelect-deploy.sh <quay-namespace> [tag] undeploy remove everything
#
#  Environment (all optional):
#    NAMESPACE       target project/namespace     (default: llm-orchestrator)
#    PLATFORM        openshift | kubernetes       (default: auto-detect)
#    INGRESS_HOST    hostname — required for kubernetes deploys
#    SKIP_BUILD=1    skip build & push (redeploy existing images)
#    DRY_RUN=1       print the manifests instead of applying them
#    QUAY_USERNAME / QUAY_PASSWORD
#                    registry login for push + pull secret for private repos
#
#  Examples:
#    ./modelect-deploy.sh cskaruppu v0.2.0
#    INGRESS_HOST=modelect.example.com ./modelect-deploy.sh cskaruppu v0.2.0
#    SKIP_BUILD=1 ./modelect-deploy.sh cskaruppu v0.2.0
# ============================================================================

set -euo pipefail

NS="${1:-}"
if [[ -z "$NS" ]]; then
  echo "Usage: $0 <quay-namespace> [tag] [undeploy]" >&2
  exit 1
fi
TAG="${2:-$(git rev-parse --short HEAD 2>/dev/null || echo latest)}"
ACTION="${3:-deploy}"
NAMESPACE="${NAMESPACE:-llm-orchestrator}"
REGISTRY="quay.io"
API_IMAGE="$REGISTRY/$NS/modelect-api:$TAG"
UI_IMAGE="$REGISTRY/$NS/modelect-ui:$TAG"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "==> $*"; }

# ---------------------------------------------------------------- cluster CLI
detect_cli() {
  if command -v oc >/dev/null 2>&1 && oc whoami >/dev/null 2>&1; then
    CLI=oc
  elif command -v kubectl >/dev/null 2>&1; then
    CLI=kubectl
  else
    echo "ERROR: need a logged-in 'oc' or a configured 'kubectl'" >&2
    exit 1
  fi
  if [[ -z "${PLATFORM:-}" ]]; then
    if "$CLI" api-resources --api-group=route.openshift.io 2>/dev/null | grep -q routes; then
      PLATFORM=openshift
    else
      PLATFORM=kubernetes
    fi
  fi
}

# ------------------------------------------------------------------ manifests
manifests() {
  cat <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orchestrator-api
  labels: {app: orchestrator-api, app.kubernetes.io/part-of: modelect}
spec:
  replicas: 1
  selector:
    matchLabels: {app: orchestrator-api}
  template:
    metadata:
      labels: {app: orchestrator-api, app.kubernetes.io/part-of: modelect}
    spec:
      ${PULL_SECRET_LINE}
      containers:
        - name: api
          image: ${API_IMAGE}
          ports: [{containerPort: 8000}]
          resources:
            requests: {cpu: 100m, memory: 128Mi}
            limits: {cpu: 500m, memory: 512Mi}
          readinessProbe:
            httpGet: {path: /healthz, port: 8000}
            initialDelaySeconds: 3
          livenessProbe:
            httpGet: {path: /healthz, port: 8000}
            initialDelaySeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: orchestrator-api
  labels: {app: orchestrator-api, app.kubernetes.io/part-of: modelect}
spec:
  selector: {app: orchestrator-api}
  ports: [{port: 8000, targetPort: 8000}]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orchestrator-ui
  labels: {app: orchestrator-ui, app.kubernetes.io/part-of: modelect}
spec:
  replicas: 1
  selector:
    matchLabels: {app: orchestrator-ui}
  template:
    metadata:
      labels: {app: orchestrator-ui, app.kubernetes.io/part-of: modelect}
    spec:
      ${PULL_SECRET_LINE}
      containers:
        - name: ui
          image: ${UI_IMAGE}
          ports: [{containerPort: 8080}]
          resources:
            requests: {cpu: 50m, memory: 64Mi}
            limits: {cpu: 250m, memory: 128Mi}
          readinessProbe:
            httpGet: {path: /healthz, port: 8080}
            initialDelaySeconds: 3
---
apiVersion: v1
kind: Service
metadata:
  name: orchestrator-ui
  labels: {app: orchestrator-ui, app.kubernetes.io/part-of: modelect}
spec:
  selector: {app: orchestrator-ui}
  ports: [{port: 8080, targetPort: 8080}]
EOF
  if [[ "$PLATFORM" == "openshift" ]]; then
    cat <<EOF
---
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: orchestrator-ui
  labels: {app: orchestrator-ui, app.kubernetes.io/part-of: modelect}
spec:
  to: {kind: Service, name: orchestrator-ui}
  port: {targetPort: 8080}
  tls: {termination: edge, insecureEdgeTerminationPolicy: Redirect}
EOF
  else
    cat <<EOF
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: orchestrator-ui
  labels: {app: orchestrator-ui, app.kubernetes.io/part-of: modelect}
spec:
  rules:
    - host: ${INGRESS_HOST}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: orchestrator-ui
                port: {number: 8080}
EOF
  fi
}

# ------------------------------------------------------------------- undeploy
if [[ "$ACTION" == "undeploy" ]]; then
  detect_cli
  PULL_SECRET_LINE=""
  INGRESS_HOST="${INGRESS_HOST:-placeholder.local}"
  log "Removing Modelect from namespace $NAMESPACE ($PLATFORM)"
  manifests | "$CLI" -n "$NAMESPACE" delete --ignore-not-found -f -
  "$CLI" -n "$NAMESPACE" delete secret quay-pull --ignore-not-found
  log "Done."
  exit 0
fi

# --------------------------------------------------------------- build & push
if [[ "${SKIP_BUILD:-0}" != "1" && "${DRY_RUN:-0}" != "1" ]]; then
  if command -v podman >/dev/null 2>&1; then ENGINE=podman
  elif command -v docker >/dev/null 2>&1; then ENGINE=docker
  else echo "ERROR: neither podman nor docker found" >&2; exit 1; fi

  if [[ -n "${QUAY_USERNAME:-}" && -n "${QUAY_PASSWORD:-}" ]]; then
    log "Logging in to $REGISTRY as $QUAY_USERNAME"
    echo "$QUAY_PASSWORD" | "$ENGINE" login -u "$QUAY_USERNAME" --password-stdin "$REGISTRY"
  fi

  log "Building images with $ENGINE"
  "$ENGINE" build -t "$API_IMAGE" "$REPO_ROOT/backend"
  "$ENGINE" build -t "$UI_IMAGE" "$REPO_ROOT/frontend"

  push_retry() {
    local ref="$1" attempt
    for attempt in 1 2 3 4; do
      "$ENGINE" push "$ref" && return 0
      log "push failed (attempt $attempt), retrying in $((2 ** attempt))s"
      sleep $((2 ** attempt))
    done
    echo "ERROR: failed to push $ref" >&2
    exit 1
  }
  log "Pushing images"
  push_retry "$API_IMAGE"
  push_retry "$UI_IMAGE"
fi

# --------------------------------------------------------------------- deploy
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  PLATFORM="${PLATFORM:-openshift}"
  PULL_SECRET_LINE=""
  INGRESS_HOST="${INGRESS_HOST:-modelect.example.com}"
  manifests
  exit 0
fi

detect_cli
log "Platform: $PLATFORM (cli: $CLI) — namespace: $NAMESPACE — tag: $TAG"

if [[ "$PLATFORM" == "kubernetes" && -z "${INGRESS_HOST:-}" ]]; then
  echo "ERROR: set INGRESS_HOST=<hostname> for kubernetes deployments" >&2
  exit 1
fi

"$CLI" get namespace "$NAMESPACE" >/dev/null 2>&1 || "$CLI" create namespace "$NAMESPACE"

PULL_SECRET_LINE=""
if [[ -n "${QUAY_USERNAME:-}" && -n "${QUAY_PASSWORD:-}" ]]; then
  log "Creating/refreshing quay pull secret"
  "$CLI" -n "$NAMESPACE" delete secret quay-pull --ignore-not-found >/dev/null
  "$CLI" -n "$NAMESPACE" create secret docker-registry quay-pull \
    --docker-server="$REGISTRY" \
    --docker-username="$QUAY_USERNAME" \
    --docker-password="$QUAY_PASSWORD" >/dev/null
  PULL_SECRET_LINE='imagePullSecrets: [{name: quay-pull}]'
fi

log "Applying manifests"
manifests | "$CLI" -n "$NAMESPACE" apply -f -

log "Waiting for rollouts"
"$CLI" -n "$NAMESPACE" rollout status deployment/orchestrator-api --timeout=300s
"$CLI" -n "$NAMESPACE" rollout status deployment/orchestrator-ui --timeout=300s

echo
if [[ "$PLATFORM" == "openshift" ]]; then
  HOST="$("$CLI" -n "$NAMESPACE" get route orchestrator-ui -o jsonpath='{.spec.host}')"
  echo "──────────────────────────────────────────────────────"
  echo "  Modelect is up:  https://$HOST"
  echo "  Gateway:         https://$HOST/v1/chat/completions"
  echo "──────────────────────────────────────────────────────"
else
  echo "──────────────────────────────────────────────────────"
  echo "  Modelect is up:  http://$INGRESS_HOST"
  echo "  Gateway:         http://$INGRESS_HOST/v1/chat/completions"
  echo "  (DNS for $INGRESS_HOST must point at your ingress controller)"
  echo "──────────────────────────────────────────────────────"
fi
