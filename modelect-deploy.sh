#!/usr/bin/env bash
# ============================================================================
#  Modelect — single-file build & deploy
#  Builds both images, pushes to quay.io, deploys to OpenShift or
#  Kubernetes (manifests embedded — no other files needed), waits for
#  rollout and prints the dashboard URL.
#
#  Usage:
#    ./modelect-deploy.sh <quay-namespace> [tag]          deploy (default: latest)
#    ./modelect-deploy.sh <quay-namespace> [tag] undeploy remove everything
#
#  Re-running the script with the SAME tag always rolls out the newest image:
#  containers use imagePullPolicy Always, and on redeploys the script issues a
#  'rollout restart' so pods re-pull even when the manifests are unchanged.
#  No tag bumping needed — build, push, restart, done.
#
#  The script is fully standalone: if it is NOT running inside a clone of
#  the repo, it clones it first (REPO_URL/REPO_BRANCH below) — so you can
#  download just this one file and run it from anywhere.
#
#  Environment (all optional):
#    NAMESPACE       target project/namespace     (default: llm-orchestrator)
#    PLATFORM        openshift | kubernetes       (default: auto-detect)
#    INGRESS_HOST    hostname — required for kubernetes deploys
#    SKIP_BUILD=1    skip build & push (redeploy existing images)
#    DRY_RUN=1       print the manifests instead of applying them
#    WITH_POSTGRES=1 deploy a PostgreSQL instance and point the API at it
#                    (default: durable SQLite on a 1Gi PVC)
#    TOPOLOGY=split  production shape: a dedicated, horizontally-scaled
#                    gateway deployment (MODELECT_ROLE=gateway, /v1 only,
#                    2 replicas, own route) beside the control API.
#                    Requires WITH_POSTGRES=1 (SQLite on RWO cannot be
#                    shared across pods). Default: combined (one pod).
#    REPO_URL        source repo to clone when not run from a checkout
#                    (default: https://github.com/cskaruppu/cheftraining.git)
#    REPO_BRANCH     branch to check out
#                    (default: claude/multi-llm-orchestrator-research-eb6w9j)
#    WORKDIR         where to clone (default: ./modelect-src)
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
TAG="${2:-latest}"
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
  # Storage mode: PostgreSQL (env from secret) or SQLite on a PVC.
  # Recreate strategy: the data PVC is RWO, and SQLite must never have
  # two writers — a rolling update would try both.
  ENV_ITEMS=""
  if [[ -n "${DEMO_SEED:-}" ]]; then
    ENV_ITEMS="{name: DEMO_SEED, value: \"${DEMO_SEED}\"}"
  fi
  if [[ "${WITH_POSTGRES:-0}" == "1" ]]; then
    ENV_ITEMS="${ENV_ITEMS:+${ENV_ITEMS}, }{name: DATABASE_URL, valueFrom: {secretKeyRef: {name: modelect-db, key: database-url}}}"
    API_VOLUMES=""
    API_MOUNTS=""
  else
    API_VOLUMES='volumes: [{name: data, persistentVolumeClaim: {claimName: modelect-data}}]'
    API_MOUNTS='volumeMounts: [{name: data, mountPath: /opt/app/data}]'
    :
  fi
  API_ENV_LINE=""
  [[ -n "$ENV_ITEMS" ]] && API_ENV_LINE="env: [${ENV_ITEMS}]"
  if [[ "${WITH_POSTGRES:-0}" != "1" ]]; then
    cat <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: modelect-data
  labels: {app: orchestrator-api, app.kubernetes.io/part-of: modelect}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests: {storage: 1Gi}
---
EOF
  fi
  cat <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orchestrator-api
  labels: {app: orchestrator-api, app.kubernetes.io/part-of: modelect}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector:
    matchLabels: {app: orchestrator-api}
  template:
    metadata:
      labels: {app: orchestrator-api, app.kubernetes.io/part-of: modelect}
    spec:
      ${PULL_SECRET_LINE}
      ${API_VOLUMES}
      containers:
        - name: api
          image: ${API_IMAGE}
          imagePullPolicy: Always
          ports: [{containerPort: 8000}]
          ${API_ENV_LINE}
          ${API_MOUNTS}
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
          imagePullPolicy: Always
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
  "$CLI" -n "$NAMESPACE" delete deployment/orchestrator-gateway \
    service/orchestrator-gateway route/orchestrator-gateway \
    --ignore-not-found 2>/dev/null || true
  "$CLI" -n "$NAMESPACE" delete secret quay-pull --ignore-not-found
  log "Done."
  exit 0
fi

# --------------------------------------------------------------- build & push
if [[ "${SKIP_BUILD:-0}" != "1" && "${DRY_RUN:-0}" != "1" ]]; then
  # Standalone mode: no source alongside the script? Clone the repo first.
  if [[ ! -d "$REPO_ROOT/backend" || ! -d "$REPO_ROOT/frontend" ]]; then
    REPO_URL="${REPO_URL:-https://github.com/cskaruppu/cheftraining.git}"
    REPO_BRANCH="${REPO_BRANCH:-claude/multi-llm-orchestrator-research-eb6w9j}"
    WORKDIR="${WORKDIR:-$PWD/modelect-src}"
    command -v git >/dev/null 2>&1 || { echo "ERROR: git is required to fetch the source" >&2; exit 1; }
    if [[ -d "$WORKDIR/.git" ]]; then
      log "Updating source in $WORKDIR ($REPO_BRANCH)"
      git -C "$WORKDIR" fetch origin "$REPO_BRANCH"
      git -C "$WORKDIR" checkout "$REPO_BRANCH"
      git -C "$WORKDIR" pull --ff-only origin "$REPO_BRANCH"
    else
      log "Cloning $REPO_URL ($REPO_BRANCH) into $WORKDIR"
      git clone --branch "$REPO_BRANCH" --single-branch "$REPO_URL" "$WORKDIR"
    fi
    REPO_ROOT="$WORKDIR"
  fi

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
  AGENT_IMAGE="$REGISTRY/$NS/modelect-agent:$TAG"
  "$ENGINE" build -t "$AGENT_IMAGE" "$REPO_ROOT/agent"

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
  push_retry "$AGENT_IMAGE"
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

if [[ "${TOPOLOGY:-combined}" == "split" && "${WITH_POSTGRES:-0}" != "1" ]]; then
  echo "ERROR: TOPOLOGY=split requires WITH_POSTGRES=1 — SQLite on an RWO" >&2
  echo "       PVC cannot be shared between the gateway and control pods." >&2
  exit 1
fi

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

# ---- optional PostgreSQL (WITH_POSTGRES=1) --------------------------------
if [[ "${WITH_POSTGRES:-0}" == "1" ]]; then
  if ! "$CLI" -n "$NAMESPACE" get secret modelect-db >/dev/null 2>&1; then
    log "Creating PostgreSQL credentials secret"
    DB_PASS="$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 20)"
    "$CLI" -n "$NAMESPACE" create secret generic modelect-db \
      --from-literal=username=modelect \
      --from-literal=password="$DB_PASS" \
      --from-literal=database=modelect \
      --from-literal=database-url="postgresql://modelect:${DB_PASS}@modelect-postgres:5432/modelect"
  fi
  log "Deploying PostgreSQL (sclorg image, restricted-SCC friendly)"
  cat <<EOF | "$CLI" -n "$NAMESPACE" apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: modelect-postgres-data
  labels: {app: modelect-postgres, app.kubernetes.io/part-of: modelect}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests: {storage: 2Gi}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: modelect-postgres
  labels: {app: modelect-postgres, app.kubernetes.io/part-of: modelect}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector:
    matchLabels: {app: modelect-postgres}
  template:
    metadata:
      labels: {app: modelect-postgres, app.kubernetes.io/part-of: modelect}
    spec:
      volumes: [{name: pgdata, persistentVolumeClaim: {claimName: modelect-postgres-data}}]
      containers:
        - name: postgres
          image: quay.io/sclorg/postgresql-15-c9s:latest
          ports: [{containerPort: 5432}]
          env:
            - {name: POSTGRESQL_USER, valueFrom: {secretKeyRef: {name: modelect-db, key: username}}}
            - {name: POSTGRESQL_PASSWORD, valueFrom: {secretKeyRef: {name: modelect-db, key: password}}}
            - {name: POSTGRESQL_DATABASE, valueFrom: {secretKeyRef: {name: modelect-db, key: database}}}
          volumeMounts: [{name: pgdata, mountPath: /var/lib/pgsql/data}]
          resources:
            requests: {cpu: 100m, memory: 256Mi}
            limits: {cpu: 500m, memory: 512Mi}
          readinessProbe:
            exec: {command: [/usr/libexec/check-container]}
            initialDelaySeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: modelect-postgres
  labels: {app: modelect-postgres, app.kubernetes.io/part-of: modelect}
spec:
  selector: {app: modelect-postgres}
  ports: [{port: 5432, targetPort: 5432}]
EOF
  "$CLI" -n "$NAMESPACE" rollout status deployment/modelect-postgres --timeout=300s
fi

# Same-tag redeploys: 'apply' with an unchanged spec triggers no rollout, so
# note which deployments already exist and restart them after apply — with
# imagePullPolicy Always the new pods re-pull the freshly pushed image.
API_EXISTS=0; UI_EXISTS=0
"$CLI" -n "$NAMESPACE" get deployment/orchestrator-api >/dev/null 2>&1 && API_EXISTS=1
"$CLI" -n "$NAMESPACE" get deployment/orchestrator-ui  >/dev/null 2>&1 && UI_EXISTS=1

log "Applying manifests"
manifests | "$CLI" -n "$NAMESPACE" apply -f -

if [[ "$API_EXISTS" == "1" || "$UI_EXISTS" == "1" ]]; then
  log "Restarting existing deployments to pull the newest '$TAG' image"
  [[ "$API_EXISTS" == "1" ]] && "$CLI" -n "$NAMESPACE" rollout restart deployment/orchestrator-api
  [[ "$UI_EXISTS" == "1" ]] && "$CLI" -n "$NAMESPACE" rollout restart deployment/orchestrator-ui
fi

# ---- split topology: dedicated horizontally-scaled gateway ----------
if [[ "${TOPOLOGY:-combined}" == "split" ]]; then
  log "Deploying dedicated gateway (MODELECT_ROLE=gateway, 2 replicas)"
  cat <<EOF | "$CLI" -n "$NAMESPACE" apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orchestrator-gateway
  labels: {app: orchestrator-gateway, app.kubernetes.io/part-of: modelect}
spec:
  replicas: 2
  selector:
    matchLabels: {app: orchestrator-gateway}
  template:
    metadata:
      labels: {app: orchestrator-gateway, app.kubernetes.io/part-of: modelect}
    spec:
      ${PULL_SECRET_LINE}
      containers:
        - name: gateway
          image: ${API_IMAGE}
          imagePullPolicy: Always
          ports: [{containerPort: 8000}]
          env:
            - {name: MODELECT_ROLE, value: "gateway"}
            - {name: DATABASE_URL, valueFrom: {secretKeyRef: {name: modelect-db, key: database-url}}}
$( [[ -n "${DEMO_SEED:-}" ]] && printf '            - {name: DEMO_SEED, value: "%s"}\n' "$DEMO_SEED" )
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
  name: orchestrator-gateway
  labels: {app: orchestrator-gateway, app.kubernetes.io/part-of: modelect}
spec:
  selector: {app: orchestrator-gateway}
  ports: [{port: 8000, targetPort: 8000}]
EOF
  if [[ "$PLATFORM" == "openshift" ]]; then
    cat <<EOF | "$CLI" -n "$NAMESPACE" apply -f -
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: orchestrator-gateway
  labels: {app: orchestrator-gateway, app.kubernetes.io/part-of: modelect}
spec:
  to: {kind: Service, name: orchestrator-gateway}
  port: {targetPort: 8000}
  tls: {termination: edge, insecureEdgeTerminationPolicy: Redirect}
EOF
  fi
  "$CLI" -n "$NAMESPACE" rollout restart deployment/orchestrator-gateway >/dev/null 2>&1 || true
fi

log "Waiting for rollouts"
"$CLI" -n "$NAMESPACE" rollout status deployment/orchestrator-api --timeout=300s
"$CLI" -n "$NAMESPACE" rollout status deployment/orchestrator-ui --timeout=300s
if [[ "${TOPOLOGY:-combined}" == "split" ]]; then
  "$CLI" -n "$NAMESPACE" rollout status deployment/orchestrator-gateway --timeout=300s
fi

echo
if [[ "$PLATFORM" == "openshift" ]]; then
  HOST="$("$CLI" -n "$NAMESPACE" get route orchestrator-ui -o jsonpath='{.spec.host}')"
  echo "──────────────────────────────────────────────────────"
  echo "  Modelect is up:  https://$HOST"
  if [[ "${TOPOLOGY:-combined}" == "split" ]]; then
    GW="$("$CLI" -n "$NAMESPACE" get route orchestrator-gateway -o jsonpath='{.spec.host}' 2>/dev/null || true)"
    echo "  Gateway (dedicated, 2 replicas):"
    echo "                   https://$GW/v1/chat/completions"
  else
    echo "  Gateway:         https://$HOST/v1/chat/completions"
  fi
  echo "──────────────────────────────────────────────────────"
else
  echo "──────────────────────────────────────────────────────"
  echo "  Modelect is up:  http://$INGRESS_HOST"
  echo "  Gateway:         http://$INGRESS_HOST/v1/chat/completions"
  echo "  (DNS for $INGRESS_HOST must point at your ingress controller)"
  echo "──────────────────────────────────────────────────────"
fi
