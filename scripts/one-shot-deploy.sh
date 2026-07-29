#!/usr/bin/env bash
# One-shot: build images, push to quay.io, deploy to OpenShift or
# Kubernetes, wait for rollout, print the URL.
#
# Usage:
#   ./scripts/one-shot-deploy.sh <quay-namespace> [tag]
#
# Environment (optional):
#   NAMESPACE       target project/namespace   (default: llm-orchestrator)
#   PLATFORM        openshift | kubernetes     (default: auto-detect)
#   INGRESS_HOST    required for kubernetes    (e.g. modelect.example.com)
#   SKIP_BUILD=1    deploy only — skip build & push
#   QUAY_USERNAME / QUAY_PASSWORD
#                   login for push, and pull secret for private repos
#
# Uses Helm (helm/modelect) when the helm CLI is available; otherwise
# falls back to the pre-rendered bundle/ manifests.

set -euo pipefail

NS="${1:-}"
if [[ -z "$NS" ]]; then
  echo "Usage: $0 <quay-namespace> [tag]" >&2
  exit 1
fi
TAG="${2:-$(git rev-parse --short HEAD 2>/dev/null || echo latest)}"
NAMESPACE="${NAMESPACE:-llm-orchestrator}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---- pick CLI + platform --------------------------------------------------
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
echo "==> Platform: $PLATFORM (cli: $CLI), namespace: $NAMESPACE, tag: $TAG"

if [[ "$PLATFORM" == "kubernetes" && -z "${INGRESS_HOST:-}" ]]; then
  echo "ERROR: set INGRESS_HOST=<hostname> for kubernetes deployments" >&2
  exit 1
fi

# ---- build & push ---------------------------------------------------------
if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  "$REPO_ROOT/scripts/build-and-push.sh" "$NS" "$TAG"
fi

# ---- namespace + optional pull secret ------------------------------------
"$CLI" get namespace "$NAMESPACE" >/dev/null 2>&1 || "$CLI" create namespace "$NAMESPACE"

PULL_SECRET_ARGS=()
if [[ -n "${QUAY_USERNAME:-}" && -n "${QUAY_PASSWORD:-}" ]]; then
  echo "==> Creating/refreshing quay pull secret"
  "$CLI" -n "$NAMESPACE" delete secret quay-pull --ignore-not-found >/dev/null
  "$CLI" -n "$NAMESPACE" create secret docker-registry quay-pull \
    --docker-server=quay.io \
    --docker-username="$QUAY_USERNAME" \
    --docker-password="$QUAY_PASSWORD" >/dev/null
  PULL_SECRET_ARGS=(--set 'imagePullSecrets[0].name=quay-pull')
fi

# ---- deploy: helm when available, bundle otherwise ------------------------
if command -v helm >/dev/null 2>&1; then
  echo "==> Deploying with Helm"
  INGRESS_ARGS=(--set "ingress.type=route")
  if [[ "$PLATFORM" == "kubernetes" ]]; then
    INGRESS_ARGS=(--set "ingress.type=ingress" --set "ingress.host=$INGRESS_HOST")
  fi
  helm upgrade --install modelect "$REPO_ROOT/helm/modelect" \
    -n "$NAMESPACE" \
    --set "image.namespace=$NS" \
    --set "image.tag=$TAG" \
    "${INGRESS_ARGS[@]}" \
    ${PULL_SECRET_ARGS[@]+"${PULL_SECRET_ARGS[@]}"} \
    --wait --timeout 5m
else
  echo "==> helm not found — deploying pre-rendered bundle"
  BUNDLE="$REPO_ROOT/bundle/openshift-all-in-one.yaml"
  [[ "$PLATFORM" == "kubernetes" ]] && BUNDLE="$REPO_ROOT/bundle/kubernetes-all-in-one.yaml"
  sed -e "s/__IMAGE_NS__/$NS/g" \
      -e "s/__IMAGE_TAG__/$TAG/g" \
      -e "s/__INGRESS_HOST__/${INGRESS_HOST:-}/g" \
      "$BUNDLE" | "$CLI" -n "$NAMESPACE" apply -f -
  if [[ -n "${QUAY_USERNAME:-}" && -n "${QUAY_PASSWORD:-}" ]]; then
    for d in orchestrator-api orchestrator-ui; do
      "$CLI" -n "$NAMESPACE" patch deployment "$d" -p \
        '{"spec":{"template":{"spec":{"imagePullSecrets":[{"name":"quay-pull"}]}}}}'
    done
  fi
  "$CLI" -n "$NAMESPACE" rollout status deployment/orchestrator-api --timeout=300s
  "$CLI" -n "$NAMESPACE" rollout status deployment/orchestrator-ui --timeout=300s
fi

# ---- print URL ------------------------------------------------------------
echo
if [[ "$PLATFORM" == "openshift" ]]; then
  HOST="$("$CLI" -n "$NAMESPACE" get route orchestrator-ui -o jsonpath='{.spec.host}')"
  echo "Modelect is up:  https://$HOST"
  echo "Gateway:         https://$HOST/v1/chat/completions"
else
  echo "Modelect is up:  http://$INGRESS_HOST   (DNS must point at your ingress controller)"
  echo "Gateway:         http://$INGRESS_HOST/v1/chat/completions"
fi
