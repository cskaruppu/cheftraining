#!/usr/bin/env bash
# Topology smoke test: boots the backend in each role and in real-data
# mode, asserting the surfaces each one must (and must not) serve.
#   ./scripts/smoke-roles.sh [python]     (default: python3)
set -euo pipefail
PY="${1:-python3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)/backend"
TMP="$(mktemp -d)"
PORT_BASE=${PORT_BASE:-8300}
pids=()
cleanup() { for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

boot() { # name port extra-env...
  local name="$1" port="$2"; shift 2
  ( cd "$ROOT" && env MODELECT_DATA_DIR="$TMP/$name" "$@" \
      "$PY" -m uvicorn app.main:app --port "$port" --host 127.0.0.1 \
      >"$TMP/$name.log" 2>&1 ) & pids+=($!)
  for _ in $(seq 1 60); do
    curl -sf "http://127.0.0.1:$port/healthz" >/dev/null && return 0
    sleep 0.5
  done
  echo "FAIL: $name did not become healthy"; tail -5 "$TMP/$name.log"; exit 1
}

code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

# ---- combined (default) ------------------------------------------------
boot combined $((PORT_BASE)) env
[[ "$(code http://127.0.0.1:$PORT_BASE/api/models)" == 401 ]]        # portal gated
[[ "$(code -X POST http://127.0.0.1:$PORT_BASE/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"model":"auto","messages":[{"role":"user","content":"hi"}]}')" == 200 ]]
echo "PASS combined: portal + gateway served"

# ---- gateway role: /v1 + /healthz ONLY --------------------------------
boot gateway $((PORT_BASE+1)) env MODELECT_ROLE=gateway
[[ "$(code -X POST http://127.0.0.1:$((PORT_BASE+1))/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"model":"route","messages":[{"role":"user","content":"hi"}]}')" == 200 ]]
[[ "$(code http://127.0.0.1:$((PORT_BASE+1))/api/models)" == 404 ]]   # stripped
[[ "$(code http://127.0.0.1:$((PORT_BASE+1))/api/auth/login)" == 404 ]]
echo "PASS gateway role: /v1 only, portal surface stripped"

# gateway pods must not seed: their fresh DB stays empty
rows="$(env MODELECT_DATA_DIR="$TMP/gateway" "$PY" - <<'EOF'
import os, sqlite3
db = os.path.join(os.environ["MODELECT_DATA_DIR"], "modelect.db")
c = sqlite3.connect(db)
print(c.execute("select count(*) from teams").fetchone()[0])
EOF
)"
[[ "$rows" == "0" ]] && echo "PASS gateway role: seeders skipped (0 teams)"

# ---- real-data mode: empty, honest boot -------------------------------
boot realdata $((PORT_BASE+2)) env DEMO_SEED=0 SIM_CLUSTERS=0
CK="$(curl -si -X POST http://127.0.0.1:$((PORT_BASE+2))/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"modelect-admin"}' \
  | grep -i set-cookie | sed 's/[Ss]et-[Cc]ookie: //;s/;.*//' | tr -d '\r')"
env CK="$CK" PORT=$((PORT_BASE+2)) "$PY" - <<'EOF'
import json, os, urllib.request
req = urllib.request.Request(
    f"http://127.0.0.1:{os.environ['PORT']}/api/analytics/summary",
    headers={"Cookie": os.environ["CK"]})
d = json.load(urllib.request.urlopen(req))
assert d["kpis"]["requests_total"] == 0, d["kpis"]
req = urllib.request.Request(
    f"http://127.0.0.1:{os.environ['PORT']}/api/clusters",
    headers={"Cookie": os.environ["CK"]})
c = json.load(urllib.request.urlopen(req))
assert c["clusters"] == [], c
print("PASS real-data mode: zero events, empty fleet, clean boot")
EOF

echo "ALL TOPOLOGY SMOKE TESTS PASSED"
