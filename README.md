# Maestro — Multi-LLM Orchestrator (demo build)

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
| OpenShift manifests | Deployments, Services, Route | `openshift/` |
| Local run | docker compose | `docker-compose.yml` |

Dashboard pages: **Dashboard** (spend/latency/cache KPIs and charts),
**Model Catalog** (19 models, searchable/filterable), **Recommend**
(requirement → scored ranking with reasons + "you chose X, we suggest Y"),
**Compare** (radar + price-vs-quality scatter + spec matrix), **Playground**
(one prompt across up to 3 models side by side).

API highlights:

- `GET /api/models` — model registry (seed data; production: auto-synced)
- `POST /api/recommend` — weighted multi-criteria scoring with full breakdown
- `POST /api/compare`, `GET /api/models/{id}/similar`
- `GET /api/analytics/summary` — KPIs, daily spend, per-model usage
- `POST /v1/chat/completions` — OpenAI-compatible; `"model": "auto"` routes
  via the recommender; supports `"stream": true` (SSE)

## Deploy to OpenShift

Requires an OpenShift 4.x cluster and the `oc` CLI, logged in.

```bash
# 1. Project (the manifests reference the 'llm-orchestrator' namespace)
oc new-project llm-orchestrator

# 2. Build both images on-cluster from this repo's Dockerfiles
oc new-build --name orchestrator-api --binary --strategy docker
oc start-build orchestrator-api --from-dir backend --follow

oc new-build --name orchestrator-ui --binary --strategy docker
oc start-build orchestrator-ui --from-dir frontend --follow

# 3. Deploy + expose
oc apply -f openshift/

# 4. Open the dashboard
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
