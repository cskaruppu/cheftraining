#!/usr/bin/env bash
# Deploy Modelect to an OpenShift cluster using the quay.io images
# produced by scripts/build-and-push.sh.
#
# Usage:
#   ./scripts/deploy.sh <quay-namespace> [tag]
#
#   <quay-namespace>  quay.io user/org the images were pushed to
#   [tag]             image tag to deploy (default: latest)
#
# Environment (optional):
#   REGISTRY        registry host (default: quay.io)
#   NAMESPACE       OpenShift project to deploy into (default: llm-orchestrator)
#   QUAY_USERNAME   if set together with QUAY_PASSWORD, a pull secret is
#   QUAY_PASSWORD   created and linked so private quay repos work
#
# Example:
#   ./scripts/deploy.sh cskaruppu v0.1.0

set -euo pipefail

REGISTRY="${REGISTRY:-quay.io}"
NAMESPACE="${NAMESPACE:-llm-orchestrator}"
NS="${1:-}"
if [[ -z "$NS" ]]; then
  echo "Usage: $0 <quay-namespace> [tag]" >&2
  exit 1
fi
TAG="${2:-latest}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_IMAGE="$REGISTRY/$NS/modelect-api:$TAG"
UI_IMAGE="$REGISTRY/$NS/modelect-ui:$TAG"

command -v oc >/dev/null 2>&1 || { echo "ERROR: 'oc' CLI not found" >&2; exit 1; }
oc whoami >/dev/null 2>&1 || { echo "ERROR: not logged in — run 'oc login' first" >&2; exit 1; }

echo "==> Deploying to project '$NAMESPACE' on $(oc whoami --show-server)"
echo "    api: $API_IMAGE"
echo "    ui:  $UI_IMAGE"

if ! oc get project "$NAMESPACE" >/dev/null 2>&1; then
  echo "==> Creating project $NAMESPACE"
  oc new-project "$NAMESPACE" >/dev/null
fi

# Pull secret for private quay repositories (skipped when creds not given)
if [[ -n "${QUAY_USERNAME:-}" && -n "${QUAY_PASSWORD:-}" ]]; then
  echo "==> Creating/refreshing quay pull secret"
  oc -n "$NAMESPACE" delete secret quay-pull --ignore-not-found >/dev/null
  oc -n "$NAMESPACE" create secret docker-registry quay-pull \
    --docker-server="$REGISTRY" \
    --docker-username="$QUAY_USERNAME" \
    --docker-password="$QUAY_PASSWORD" >/dev/null
  oc -n "$NAMESPACE" secrets link default quay-pull --for=pull
fi

echo "==> Applying manifests"
oc -n "$NAMESPACE" apply -f "$REPO_ROOT/openshift/"

echo "==> Pointing deployments at the quay images"
oc -n "$NAMESPACE" set image deployment/orchestrator-api api="$API_IMAGE"
oc -n "$NAMESPACE" set image deployment/orchestrator-ui ui="$UI_IMAGE"

echo "==> Waiting for rollouts"
oc -n "$NAMESPACE" rollout status deployment/orchestrator-api --timeout=180s
oc -n "$NAMESPACE" rollout status deployment/orchestrator-ui --timeout=180s

HOST="$(oc -n "$NAMESPACE" get route orchestrator-ui -o jsonpath='{.spec.host}')"
cat <<EOF

Modelect is up.

  Dashboard : https://$HOST
  Gateway   : https://$HOST/v1/chat/completions
  Try it    : curl -sk https://$HOST/v1/chat/completions \\
                -H 'Content-Type: application/json' \\
                -d '{"model":"auto","messages":[{"role":"user","content":"hello"}]}'
EOF
