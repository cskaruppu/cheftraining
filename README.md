# Modelect — Multi-LLM Orchestrator (demo build)

A demo of a multi-LLM orchestration platform: one unified, OpenAI-compatible
API in front of many models, plus a **model intelligence layer** — a living
model catalog, a transparent recommendation engine ("tell me which LLM fits my
requirement, and show the math"), side-by-side comparison, and cost/latency
analytics.

**Demo scope:** everything runs self-contained with **no provider API keys** —
model responses are simulated and the catalog/analytics ship with seed data.
The API contracts are the production ones; wiring real providers replaces one
function (`_simulate_completion` in `backend/app/main.py`).

## What's inside

| Piece | Tech | Path |
|---|---|---|
| Control plane + demo gateway | Python 3.12 · FastAPI | `backend/` |
| Dashboard (5 pages) | React 18 · TypeScript · Vite · Tailwind · Recharts | `frontend/` |
| Helm chart (OpenShift + Kubernetes) | `ingress.type: route \| ingress \| none` | `helm/modelect/` |
| One-shot bundles (no Helm needed) | pre-rendered all-in-one YAML | `bundle/` |
| OpenShift manifests | Deployments, Services, Route | `openshift/` |
| Build/deploy scripts | quay.io push + one-shot deploy | `scripts/` |
| Local run | docker compose | `docker-compose.yml` |

Dashboard pages: **Dashboard** (spend/latency/cache KPIs and charts),
**Model Catalog** (19 models, searchable/filterable), **Recommend**
(requirement → scored ranking with reasons + "you chose X, we suggest Y"),
**Deploy** (VM-style self-service provisioning: pick an open-weights
model + serving profile with GPU/quantization/cost sizing → live
provisioning progress → endpoint + API key; simulated in the demo,
production creates vLLM/KServe services), **Compare** (radar +
price-vs-quality scatter + spec matrix), **Playground** (one prompt
across up to 3 models side by side).

Product direction, positioning and roadmap: see [`docs/VISION.md`](docs/VISION.md).

API highlights:

- `GET /api/models` — model registry (seed data; production: auto-synced)
- `POST /api/recommend` — weighted multi-criteria scoring with full breakdown
- `GET /api/models/{id}/profiles`, `POST/GET/DELETE /api/deployments` —
  serving profiles and simulated VM-style provisioning
- `POST /api/compare`, `GET /api/models/{id}/similar`
- `GET /api/analytics/summary` — KPIs, daily spend, per-model usage
- `POST /v1/chat/completions` — OpenAI-compatible; `"model": "auto"` routes
  via the recommender; supports `"stream": true` (SSE)

## One-shot deploy (OpenShift or Kubernetes — recommended)

Requires podman or docker locally, a quay.io account, and a logged-in
`oc` (OpenShift) or configured `kubectl` (Kubernetes).

**Single-file script** — build + push + deploy + URL in one command,
with all manifests embedded (no other deploy files needed). It even
clones this repo itself when run outside a checkout, so the script is
the only file you need:

```bash
podman login quay.io                      # once

# Option A: from anywhere — grab just the script; it clones the source
curl -fsSLO https://raw.githubusercontent.com/cskaruppu/cheftraining/claude/multi-llm-orchestrator-research-eb6w9j/modelect-deploy.sh
chmod +x modelect-deploy.sh
./modelect-deploy.sh <your-quay-user> v0.2.0
# (private repo? set REPO_URL to an authenticated URL or run from a clone)

# Option B: from a clone of this repo — OpenShift auto-detected:
./modelect-deploy.sh <your-quay-user> v0.2.0

# Vanilla Kubernetes (EKS/AKS/GKE/…):
INGRESS_HOST=modelect.example.com ./modelect-deploy.sh <your-quay-user> v0.2.0

# Redeploy without rebuilding / remove everything / preview manifests:
SKIP_BUILD=1 ./modelect-deploy.sh <your-quay-user> v0.2.0
./modelect-deploy.sh <your-quay-user> v0.2.0 undeploy
DRY_RUN=1 ./modelect-deploy.sh <your-quay-user> v0.2.0
```

Equivalent modular flow (uses Helm when installed, `bundle/` otherwise):

```bash
./scripts/one-shot-deploy.sh <your-quay-user> v0.2.0
```

One command: builds both images, pushes to quay.io, deploys (Helm chart
if `helm` is installed, pre-rendered `bundle/` manifests otherwise),
waits for rollout, prints the URL. `SKIP_BUILD=1` redeploys without
rebuilding; `NAMESPACE=...` overrides the target namespace.

Helm directly, if you prefer:

```bash
helm upgrade --install modelect helm/modelect -n llm-orchestrator \
  --create-namespace --set image.namespace=<your-quay-user> \
  --set image.tag=v0.2.0 --set ingress.type=route   # or ingress + ingress.host
```

### Step-by-step alternative (OpenShift)

```bash
./scripts/build-and-push.sh <your-quay-user> v0.2.0
./scripts/deploy.sh <your-quay-user> v0.2.0
./scripts/undeploy.sh                     # cleanup; or --delete-project
```

Private quay repos: export `QUAY_USERNAME` and `QUAY_PASSWORD` before
running the scripts — `build-and-push.sh` uses them to log in and
`deploy.sh` creates a pull secret in the cluster. New quay.io
repositories are private by default; either do that or flip the repos
to public in the quay.io UI.

### Alternative: build on-cluster (no quay.io needed)

```bash
oc new-project llm-orchestrator
oc new-build --name orchestrator-api --binary --strategy docker
oc start-build orchestrator-api --from-dir backend --follow
oc new-build --name orchestrator-ui --binary --strategy docker
oc start-build orchestrator-ui --from-dir frontend --follow
oc apply -f openshift/
echo "https://$(oc get route orchestrator-ui -o jsonpath='{.spec.host}')"
```

Try the gateway from the terminal:

```bash
UI_HOST=$(oc get route orchestrator-ui -o jsonpath='{.spec.host}')
curl -sk "https://$UI_HOST/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"model": "auto", "messages": [{"role": "user", "content": "hello"}]}'
```

Notes:

- If you use a different project name, update the two `image:` references in
  `openshift/*.yaml`.
- Images run as non-root (restricted SCC compatible): the UI uses
  `nginx-unprivileged` on port 8080, the API runs uvicorn as UID 1001.
- Demo touch for presentations: `oc autoscale deployment/orchestrator-api
  --min 1 --max 5 --cpu-percent=70` and show pods scaling under load.

## Run locally

```bash
docker compose up --build
# UI: http://localhost:8080   API: http://localhost:8000/docs
```

Or without containers:

```bash
cd backend && pip install -r requirements.txt && uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev   # http://localhost:5173 (proxies to :8000)
```

Tests: `cd backend && pip install pytest httpx && python -m pytest tests/`

## Production architecture (target)

This demo collapses everything into one Python service. The production design
splits it:

```
apps ──► Go gateway (data plane: unified API, routing, failover, streaming,
         rate limits, semantic cache via Redis)
             │ policies/config          │ async usage events
     Python control plane (FastAPI):    NATS/Kafka ──► ClickHouse (analytics)
       model registry sync, recommendation engine,
       evals, admin APIs ── PostgreSQL
     React dashboard ──► control plane APIs
     Deploy: Helm + ArgoCD (OpenShift GitOps), OTel + Prometheus observability
```

Roadmap beyond the demo: real provider adapters, auto-synced model registry
(provider APIs / OpenRouter / HF Hub / local vLLM discovery), benchmark
ingestion, bring-your-own-prompts evals (LLM-as-judge), semantic caching,
budgets & alerts, SSO/RBAC/audit logs, MCP support.
