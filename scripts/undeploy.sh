#!/usr/bin/env bash
# Remove the Modelect deployment from the cluster (keeps the project
# unless --delete-project is passed).
#
# Usage: ./scripts/undeploy.sh [--delete-project]
# Environment: NAMESPACE (default: llm-orchestrator)

set -euo pipefail

NAMESPACE="${NAMESPACE:-llm-orchestrator}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

oc whoami >/dev/null 2>&1 || { echo "ERROR: not logged in — run 'oc login' first" >&2; exit 1; }

if [[ "${1:-}" == "--delete-project" ]]; then
  echo "==> Deleting project $NAMESPACE"
  oc delete project "$NAMESPACE"
else
  echo "==> Deleting Modelect resources in $NAMESPACE"
  oc -n "$NAMESPACE" delete -f "$REPO_ROOT/openshift/" --ignore-not-found
  oc -n "$NAMESPACE" delete secret quay-pull --ignore-not-found
fi
echo "Done."
