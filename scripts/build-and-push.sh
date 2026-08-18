#!/usr/bin/env bash
# Build the Modelect images and push them to quay.io.
#
# Usage:
#   ./scripts/build-and-push.sh <quay-namespace> [tag]
#
#   <quay-namespace>  your quay.io user or organization (e.g. cskaruppu)
#   [tag]             image tag; defaults to the short git commit, falling
#                     back to "latest" outside a git checkout
#
# Environment (optional):
#   REGISTRY        registry host (default: quay.io)
#   QUAY_USERNAME   if set together with QUAY_PASSWORD, the script logs in
#   QUAY_PASSWORD   before pushing; otherwise it assumes you are logged in
#                   already (podman/docker login quay.io)
#
# Example:
#   ./scripts/build-and-push.sh cskaruppu v0.1.0

set -euo pipefail

REGISTRY="${REGISTRY:-quay.io}"
NS="${1:-}"
if [[ -z "$NS" ]]; then
  echo "Usage: $0 <quay-namespace> [tag]" >&2
  exit 1
fi
TAG="${2:-$(git rev-parse --short HEAD 2>/dev/null || echo latest)}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_IMAGE="$REGISTRY/$NS/modelect-api"
UI_IMAGE="$REGISTRY/$NS/modelect-ui"

# Pick a container engine: podman preferred (matches OpenShift tooling)
if command -v podman >/dev/null 2>&1; then
  ENGINE=podman
elif command -v docker >/dev/null 2>&1; then
  ENGINE=docker
else
  echo "ERROR: neither podman nor docker found on PATH" >&2
  exit 1
fi
echo "==> Using $ENGINE; pushing to $REGISTRY/$NS with tag '$TAG'"

if [[ -n "${QUAY_USERNAME:-}" && -n "${QUAY_PASSWORD:-}" ]]; then
  echo "==> Logging in to $REGISTRY as $QUAY_USERNAME"
  echo "$QUAY_PASSWORD" | "$ENGINE" login -u "$QUAY_USERNAME" --password-stdin "$REGISTRY"
fi

build() {
  local image="$1" context="$2"
  echo "==> Building $image:$TAG from $context"
  "$ENGINE" build -t "$image:$TAG" -t "$image:latest" "$context"
}

push() {
  local ref="$1" attempt delay
  for attempt in 1 2 3 4; do
    if "$ENGINE" push "$ref"; then
      return 0
    fi
    delay=$((2 ** attempt))
    echo "WARN: push of $ref failed (attempt $attempt); retrying in ${delay}s…" >&2
    sleep "$delay"
  done
  echo "ERROR: failed to push $ref after 4 attempts" >&2
  exit 1
}

AGENT_IMAGE="$REGISTRY/$NS/modelect-agent"
build "$API_IMAGE" "$REPO_ROOT/backend"
build "$UI_IMAGE" "$REPO_ROOT/frontend"
build "$AGENT_IMAGE" "$REPO_ROOT/agent"

echo "==> Pushing images"
push "$API_IMAGE:$TAG"
push "$API_IMAGE:latest"
push "$UI_IMAGE:$TAG"
push "$UI_IMAGE:latest"
push "$AGENT_IMAGE:$TAG"
push "$AGENT_IMAGE:latest"

cat <<EOF

Done. Pushed:
  $API_IMAGE:$TAG
  $UI_IMAGE:$TAG

Next:
  ./scripts/deploy.sh $NS $TAG

NOTE: new quay.io repositories default to PRIVATE. Either make
modelect-api and modelect-ui public in the quay.io UI, or export
QUAY_USERNAME/QUAY_PASSWORD before running deploy.sh so it can create
a pull secret in the cluster.
EOF
