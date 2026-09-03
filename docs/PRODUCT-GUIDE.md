# Modelect — Complete Product Guide

**Modelect** (Model + Select) is a multi-LLM orchestrator: one control plane to
**decide** which model fits each workload, **deploy** open models onto your own
GPU clusters, **integrate** through one OpenAI-compatible gateway, and
**govern** the whole estate with enforced budgets and auditable decisions.

Think *vSphere for LLMs*: instead of procuring a GPU server per team and
hand-wiring API keys, users come to a portal, describe their requirement, get a
transparent recommendation, deploy (or connect to) the right model, and leave
with a working endpoint — while the platform meters, enforces, and records
every decision.

**Positioning in one line:** *Others report; Modelect decides, enforces, and
proves it — with receipts.*

---

## 1. Differentiators

| Theme | What Modelect does | Why competitors don't |
|---|---|---|
| **Receipts everywhere** | Every routing choice, enforcement, failover and placement ships a machine-readable receipt and is stored in the Decision Ledger | Gateways log *requests*; nobody logs *justifications* |
| **Enforced tokenomics** | Budgets degrade traffic to smaller models instead of failing; tier allowlists, shape limits, token-rate limits, kill switch — all at the gateway | Observability tools report overspend after the fact |
| **Hybrid estate** | API providers and private GPU-hosted models in one statement, one gateway, one dashboard | Provider consoles see only themselves |
| **Pre-classification router** | `model:"route"` classifies each request *before* sending — one call, per-signal receipt | Cascades pay twice on escalation; managed routers are black boxes |
| **Measured, not promised** | Latency switches from catalog estimates to live telemetry at ≥20 samples; savings computed from recorded traffic; simulated paths labeled | Marketing numbers are easier |
| **What-If Replay** | Re-prices *your* recorded token shapes under any hypothetical | Price calculators use made-up volumes |
| **vSphere operations** | Cordon/maintenance mode, admission preview ("fits up to…"), idle-GPU reclamation hints, resilience drills | Fleet consoles stop at inventory |

---

## 2. Architecture

```
┌─────────────────────────────  Control plane  ─────────────────────────────┐
│  React UI (dark, four nav groups)     FastAPI backend                     │
│   /dashboard /clusters /models ...     ├─ OpenAI-compatible gateway /v1   │
│                                        ├─ Engines: recommender, router,   │
│                                        │  placement, tokenomics, replay,  │
│                                        │  insights, ledger, resilience    │
│                                        └─ SQLite on PVC  or  PostgreSQL   │
└──────────────▲────────────────────────────────▲──────────────────────────┘
               │ HTTPS (session cookie / team    │ outbound-only HTTPS
               │ API key / agent token)          │ (report + work polling)
        Users & apps                     Modelect agent (per GPU cluster)
                                          ├─ reads nodes via ServiceAccount
                                          ├─ GPU Operator labels → inventory
                                          │  (MIG slices & time-sliced vGPU)
                                          └─ executes work orders → vLLM
                                             Deployment/Service/Route
```

Components:

- **Backend** — Python 3.12 / FastAPI. Serves the portal APIs, the gateway,
  and (in single-container mode) the built UI with SPA deep-link support.
- **Frontend** — React 18 + TypeScript + Vite + Tailwind + Recharts.
- **Agent** — stdlib-only Python process installed on any OpenShift/Kubernetes
  cluster. Outbound-only: it reports inventory and polls for work; the control
  plane never needs to reach into the cluster.
- **Database** — SQLite on a PVC by default (survives restarts; `Recreate`
  strategy guarantees a single writer), or PostgreSQL via `DATABASE_URL`
  (sclorg image, restricted-SCC friendly). All tables auto-migrate.

### Authentication & roles

- Local auth: PBKDF2 password hashes, HMAC-signed HttpOnly session cookies
  (signing key persisted in the data dir). Production swap: Keycloak/OIDC.
- **admin** — sees everything (Overview, Govern, fleet operations).
- **team user** — limited to Decide / Deploy / Integrate plus **My Usage**;
  admin surfaces are enforced **server-side** (`ADMIN_RULES` prefix table),
  not just hidden in the UI.
- Demo accounts: `admin` / `modelect-admin`; team users (e.g. `support-bot`,
  `doc-pipeline`) / `modelect-user`. Override via `ADMIN_PASSWORD`,
  `USER_PASSWORD`.
- Three surfaces bypass the session: `/healthz`, the gateway `/v1/*`
  (authenticated by team API keys), and `/api/agent/*` (agent enrollment
  token, shown on GPU Fleet).

---

## 3. Navigation map

| Group | Tabs (admin) | Tabs (team user) |
|---|---|---|
| **Overview** | Dashboard, GPU Fleet | — |
| **Decide** | Model Catalog, Recommend, Evals, Compare, What-If Replay | Catalog, Recommend, Evals, Compare |
| **Deploy** | Migrate from Cloud, Deployments | same |
| **Integrate** | Integrate & Verify, Playground | same |
| **Govern** | Tokenomics, Decision Ledger, Settings | My Usage |

The sticky header shows breadcrumb (group › page), a live-data/demo-data
provenance chip, the role chip, and session controls. The footer carries the
gateway identity (`/v1 · OpenAI-compatible`) and API docs link (`/docs`).

---

## 4. Tab-by-tab reference

### 4.1 Dashboard (admin)

**What it does:** the operator's front page — traffic, economics, and "what
needs my action" in one view, all following a **time-range selector**
(24h / 7d / 14d / 30d; hourly buckets on 24h, complete days otherwise).

**KPI row**
- *Requests* — completed gateway calls, with tokens, sparkline, and
  period-over-period delta.
- *Spend* — with **budget runway** ("~148d at current burn"): remaining team
  budgets ÷ average daily spend of the last 7 days.
- *Latency p50 / p95* — percentiles of non-cached completion latency
  (averages hide outliers; p95 is what SLOs are written on).
- *Success rate* — guardrail BLOCK/KILLSWITCH rejections count as failures:
  `completed / (completed + blocks)`.
- *Cache hit rate* — semantic-cache share, served at $0.

Deltas compare against the previous window of equal length and are
**suppressed when the baseline is too sparse** (fewer than 20 requests or
under 5 % of current volume) — a delta against nothing would mislead.

**Counterfactual banner** — "*$X left on the table*": prices the window's
*direct* (unrouted) traffic as if it had used `model:"route"`, using the
**measured** small-model share of actual routed traffic as the mix. Appears
only when ≥5 routed requests exist to measure; labeled an estimate.

**Signature row** — Routing savings (measured, from receipts) · Hybrid estate
(API vs private-GPU token split) · Enforcement pulse (24h guardrail actions +
anomalies) · GPU fleet health. Each card links to its page.

**Needs attention** — the operator inbox, ranked crit → warn → info: failed or
still-rolling deployments, stale agents, teams past 80 % of budget (with
per-team runway), usage anomalies, and **idle GPU deployments** (running vLLM
pods whose model served nothing for 48h — reclaimable capacity). New critical
items can push to a Slack-compatible webhook (Settings), deduped per condition.

**Router health & efficiency** — escalation-rate trend with drift (rising =
the small model no longer suffices), prompt-bloat trend (average input tokens
per request — the classic silent cost leak), provider concentration with
catalog failover alternatives.

**Charts & log** — spend and token-throughput series, requests by model
("top 6 of N"), spend by provider, and a recent-requests table where every row
carries its routing chip (`route`/`cascade`/`auto`/direct) and backend chip
(`real vLLM`/`simulated`/`cache hit`).

### 4.2 GPU Fleet (admin)

**What it does:** every registered cluster with live GPU inventory — the
"hosts view" of the platform.

- **KPIs:** clusters (by class), total GPUs (+free), **Fleet allocation** with
  the *hottest* cluster called out and the honesty note "allocated ≠ busy"
  (the number counts scheduled slices, not measured GPU load), models deployed.
- **Cluster cards:** platform + version, region, **NVIDIA driver + CUDA
  versions** (from GPU Operator node labels), heartbeat chip, live-agent vs
  simulated provenance, GPU-class badge, residency/cost/labels chips,
  **carbon estimate** (~0.4 kW per allocated GPU × 24 h × 0.35 kg CO₂e/kWh —
  labeled an estimate), per-family utilization bars (blue <70 %, amber 70–90 %,
  red ≥90 %) with **VRAM** and **vGPU** chips, a **24h allocation sparkline**
  (sampled every 10 minutes), deployments colored by status, and:
- **"Fits up to" admission preview** — the placement engine answers "what is
  the largest self-hostable model this cluster can still schedule?" with the
  profile and quantization, before anyone tries.
- **Maintenance mode (cordon)** — a cordoned cluster stays visible but dimmed;
  the placement engine skips it (reason in every placement receipt), explicit
  deploys are refused, and cordon/uncordon actions are ledgered.
- **Connect a cluster** — 3-step wizard: cluster details → download the agent
  manifest with your control-plane URL + enrollment token (`ma-…`) filled in →
  verify the heartbeat. GPU classes: **gpu-ready** (Operator running, GPUs
  schedulable), **gpu-unmanaged** (NVIDIA hardware present via NFD PCI-10de
  labels but no Operator), **cpu-only**.

### 4.3 Model Catalog (Decide)

**What it does:** the unified model registry — 20 curated frontier + open
models with quality dimensions, pricing, capabilities, context windows, size
class (SLM / mid / large), plus models synced from **Hugging Face Hub** and
**OpenRouter** connectors (live public APIs with a bundled snapshot fallback;
`REGISTRY_OFFLINE=1` forces snapshot mode; duplicates against the curated set
are de-duplicated). Source chips distinguish curated / HF / OpenRouter; open
models are flagged self-hostable. When live telemetry reaches ≥20 samples for
a model, its latency shows a **measured** chip and overrides the estimate
everywhere (catalog, recommender, replay).

### 4.4 Recommend (Decide)

**What it does:** requirement in → ranked, *explained* recommendation out.

**Logic** (`recommender.py`):
- The use case maps to a quality dimension (chat, coding, reasoning, …).
- Hard constraints filter first (open-source only, context window, residency…)
  — exclusions are returned *with reasons*.
- Each candidate scores on three normalized axes:
  - *quality* = the model's score on the use-case dimension;
  - *cost* = log-scaled blended price ($0.10 vs $1 matters as much as $1 vs
    $10);
  - *speed* = 60 % latency (measured telemetry if ≥20 samples, else catalog) +
    40 % throughput.
- Final score = the user's quality/cost/speed weights applied to those axes.
- **`smallest_capable` mode** (SLM-first): keep only models clearing the
  quality floor (default 80, configurable) on the dimension, then rank by
  *size* ascending — the smallest model that is good enough wins. This mode
  powers cascade tier-1, budget degrade, and the smart router's small side.
- If the user names the model they *would have* chosen, the response includes
  a chosen-vs-suggested delta comparison.

### 4.5 Evals (Decide)

**What it does:** run your own prompts across up to three models and score
them, turning the recommendation into evidence. Deterministic simulation in
demo mode (seeded per model+prompt: judge score ≈ the model's real dimension
strength ± variance, honest cost/latency); the **value pick** highlights the
best judge-score-per-dollar among models within 8 points of the winner.
Production swap: real provider calls + LLM-as-judge.

### 4.6 Compare (Decide)

**What it does:** side-by-side model comparison — quality dimensions, pricing,
context, capabilities — with a similarity engine (`/api/models/{id}/similar`)
that finds the nearest alternatives in feature space (used by failover too).

### 4.7 What-If Replay (Decide, admin)

**What it does:** replays your recorded traffic under a hypothetical — *exact
re-pricing of the token shapes this install actually served*, not a generic
calculator.

**Logic** (`replay.py`):
- Scenario `model`: every recorded request re-priced on one model. Requests
  whose recorded input exceeds the candidate's context window are counted as
  **would-not-fit warnings** rather than silently priced; a quality-floor
  warning fires if the candidate scores <75 on chat.
- Scenario `route`: the smart router applied to all traffic, using the
  **measured** small/strong mix of your actual routed requests (refuses to
  guess if fewer than 5 exist).
- Latency is measured (telemetry) when available, else estimated (catalog) —
  and the result *says which*. Quality is never simulated; the page tells you
  to check Evals before switching.

### 4.8 Migrate from Cloud (Deploy)

**What it does:** the economics of moving a cloud API workload onto your own
GPUs. For a given model + monthly token volume it compares API cost vs the
best self-hosted profile (flat GPU cost × replicas needed at the configured
utilization target), shows the break-even volume, and is deliberately honest
when self-hosting **doesn't** pay off at low volume ("cost-competitive;
self-hosting pays off at higher volume").

### 4.9 Deployments (Deploy)

**What it does:** deploy open models onto the fleet and manage them.

**Flow:**
1. Pick a self-hostable model → **serving profiles** are generated by size
   class (econ / balanced / perf: GPUs, quantization, est. $/hr and
   throughput).
2. **Auto-placement** ranks the fleet transparently:
   `score = (free/count)·40 + (100−util)·0.3 + (1/cost_factor)·20`, with hard
   filters first — residency mismatch, stale agent, wrong GPU class, cordoned,
   insufficient free capacity — each exclusion *with its reason*. (Preview via
   `POST /api/placement`.)
3. Create → GPUs are allocated; on an **agent cluster** a work order is queued
   and the agent actually creates the vLLM Deployment/Service/Route; states
   flow `pending → starting → pulling → ready` (or `error`) back into the UI.
   On simulated clusters a deterministic timeline plays instead.
4. Each deployment gets an API key and an OpenAI-compatible endpoint path;
   placement decisions are ledgered.

### 4.10 Integrate & Verify (Integrate)

**What it does:** working client code + proof the endpoint works.

- **Snippet generator:** target (a model, or gateway policies `auto` /
  `cascade` / `route`) × language (curl, Python, JavaScript, Go, Java) ×
  format (Chat JSON, structured output, streaming SSE). Everything is
  OpenAI-compatible: existing SDKs, LangChain, LlamaIndex work by changing the
  base URL.
- **Integration test suite:** connectivity, auth, schema compliance
  (N/20 responses validated), latency, and **groundedness (measured, not
  promised)** — deterministic simulation in demo mode, real checks in
  production.

### 4.11 Playground (Integrate)

**What it does:** one prompt across up to three models side-by-side with
latency and cost per response — plus the **live smart-router preview**: as you
type, a strip shows where `model:"route"` *would* send this prompt, the
complexity score vs threshold, and every fired signal chip (a dry-run via
`/api/router/preview`; no tokens spent).

### 4.12 Tokenomics (Govern, admin)

**What it does:** metering, budgets and **enforcement** across the estate.

- **KPIs:** 30d tokens, true blended $/1M (API + private together), budget
  health, estimated CO₂e from token telemetry.
- **Teams table:** rolling 30-day budgets with spend bars, guardrail chips
  (allowed tiers, token-rate limit, max input), per-team API keys
  (copy to test attribution live), pause/resume kill switch.
- **Guardrails, enforced at the gateway in this order:**
  1. **Kill switch** — paused key → 403;
  2. **Tier allowlist** — e.g. an intern sandbox limited to `slm,mid` cannot
     call a large model → 403;
  3. **Shape limits** — max input/output tokens → 400;
  4. **Token-rate limit** — tokens/minute in a rolling 60 s window → 429;
  5. **Budget policy `degrade`** — at 100 % of budget, requests for larger
     models are served by the *smallest capable* model instead of failing (no
     outage), and the receipt records the enforcement.
- **Hybrid statement:** cost per source — API providers and private GPU rows
  (flagged) — "the number observability-only tools can't produce".
- **Anomalies:** each team's recent output-token volume vs its own baseline
  (a 6× burst → "possible agent loop or leaked key") — token shapes change
  before anything shows up in billing.
- **Routing savings card:** measured per policy (route / cascade / auto):
  requests, small-model share, actual vs counterfactual-strong cost.
- Every enforcement lands in both the enforcement log and the Decision Ledger.

**Agentic tokenomics (the agentic-era layer).** Agents spend at machine
speed, so attribution and control go one level deeper than teams:

- **Agent identities** — sub-keys under a team (`ak-…`, minted via
  `POST /api/teams/{id}/agents`). Spend under an agent key is attributed to
  the agent *and* governed by its team's budget and guardrails. The
  "Agentic spend — team → agent" card shows the tree.
- **Mission budgets** — a task ("this research job may spend $0.50") is
  declared with gateway headers `X-Task-Id` + `X-Task-Budget` and metered
  across every call carrying the id. At 100 % of the task budget requests
  degrade to the smallest capable model; past 150 % they are refused (402).
  Degrade-before-block keeps an agent mid-task working, cheaply.
- **Cost per outcome** — `POST /v1/tasks/{id}/complete` marks a mission done;
  spend ÷ completed tasks prices agent work in outcomes, not tokens.
- **Loop-breaker** — set a team's `loop_policy` to `degrade` and anomalous
  output volume is auto-contained on the smallest capable model (logged as
  `LOOPBREAK`, receipted) until behavior normalizes.
- **Delegation-depth guard** — `X-Delegation-Depth` beyond the team's
  `max_delegation_depth` is refused: the agentic fork-bomb brake.
- **Router as the agent default** — point any OpenAI-compatible agent
  framework at the gateway with `model:"route"` and every sub-step is
  classified small-vs-strong automatically (snippet on Integrate & Verify).

### 4.13 Decision Ledger (Govern, admin)

**What it does:** the governance record — an append-only ledger of **every
model decision with its receipt**: kind (`routing` / `enforcement` /
`failover` / `placement`), policy, model, team, one-line justification, full
receipt JSON (expandable), filterable by kind and window, **CSV export** for
auditors. This is the record-keeping AI-governance frameworks (e.g. EU AI Act
traceability) ask for. *Prompt contents are never stored — only decisions
about them.*

### 4.14 Settings (Govern, admin)

**What it does:** runtime configuration — no redeploy needed.

- **Platform configuration:** GPU utilization target, assumed monthly volume,
  default quality floor, registry sync TTL, **smart-router threshold**
  (lower = quality-cautious, higher = cost-aggressive). All admin-editable,
  live immediately.
- **System:** database backend, event counts, version — plus the privacy
  posture statement (no prompt storage).
- **Resilience drill:** declare a provider down; the gateway fails its
  traffic over to the closest comparable model from another provider —
  receipted and ledgered. Prove failover before an outage proves it for you.
- **Alert webhook:** Slack-compatible `{"text": …}` POST on new critical
  attention items, deduped; best-effort so a dead webhook never breaks the
  dashboard.
- **Data sources:** registry connector status (live vs snapshot) + manual
  sync.

### 4.15 My Usage (Govern, team user)

**What it does:** the team user's own slice — their team's API key, spend vs
budget, guardrails that apply to them, and recent usage. No visibility into
other teams (enforced server-side).

---

## 5. The gateway (`POST /v1/chat/completions`)

OpenAI-compatible: any SDK works by changing the base URL. `stream: true`
gives SSE. The `model` field selects a policy:

| `model` | Behavior |
|---|---|
| `"auto"` | Recommender routes each call (quality 40 / cost 40 / speed 20) |
| `"cascade"` | SLM-first: try the smallest capable model; classify complex (>80 words or reasoning keywords) → escalate to the strongest model. Escalations pay twice — that's the trade-off `route` removes |
| `"route"` | **Smart pre-router**: classify *before* sending — exactly one model call (see §6) |
| a model id | Pinned — served exactly what was asked (subject to guardrails) |

**Order of operations per request:** resolve policy → **resilience failover**
(provider declared down → closest comparable substitute) → **tokenomics
guardrails** (kill switch → tiers → shape → rate → budget degrade) → serve:
if an agent-deployed vLLM endpoint is **ready** for the chosen model, proxy to
it (`backend: real`); on failure fall back honestly (`simulated-fallback`);
otherwise simulate (`simulated`). Every response carries
`modelect.receipt` — model, reason, cost, cheapest-comparable, backend, and
any `enforcement` / `cascade` / `router` / `failover` blocks — and every
decision is ledgered.

---

## 6. The smart router (rung 1 of the maturity ladder)

`router.py` scores observable request features — **no model call, no prompt
storage**:

| Signal | Weight | Fires when |
|---|---|---|
| long_prompt | +0.20 | > 120 words |
| very_long_prompt | +0.15 | > 400 words |
| deep_conversation | +0.10 | > 6 messages |
| code_present | +0.20 | code fences / code-like syntax |
| reasoning_keywords | +0.25 | analyze, architecture, prove, step-by-step, plan, debug, trade-off, … |
| extraction_shaped | −0.20 | extract, classify, summarize, translate, define, … |
| short_question | −0.15 | < 30 words ending in "?" |

`score = 0.35 (base) + Σ fired weights`, clamped to [0, 1]. Score ≥ threshold
(config `router_threshold`, default 0.5) → **strongest model** (highest chat
quality); below → **smallest capable model** (quality floor 75). Neutral
prompts land *below* the threshold — that default-to-small is what produces
the 80–95 % small-model share.

Every decision lists *all* signals (fired or not) with weights in the receipt
— auditable, not a black box. The recorded decisions (plus cascade escalation
history) are labeled training data for rung 2 (embedding classifier) and
rung 4 (fine-tuned router) — trained on *your* traffic, no fine-tuning needed
to start.

---

## 7. The agent

Installed from a single manifest (GPU Fleet → Connect). Outbound-only.

- **Inventory:** reads nodes via a read-only ClusterRole; NVIDIA GPU Operator
  labels give product, **VRAM** (`gpu.memory`), **driver/CUDA versions**;
  **MIG slices** (`nvidia.com/mig-*`) and **time-sliced replicas**
  (`gpu.replicas > 1`) are reported as **virtual GPUs** — deployments consume
  vGPU slices, not dedicated cards, so several models share physical GPUs.
- **Classification:** `gpu-ready` (Operator schedulable) / `gpu-unmanaged`
  (NFD sees NVIDIA PCI hardware, no Operator) / `cpu-only`.
- **Heartbeats** every 30 s (stale after 90 s → excluded from placement,
  flagged in the attention queue).
- **Work orders:** the agent polls for orders and executes real serving —
  creates a vLLM Deployment (`--served-model-name`, HF repo, optional
  `hf-token` secret, `SERVING_IMAGE` override), Service, and Route (OpenShift)
  — reporting `pending → starting → pulling → ready / error`. Deletion is a
  work order too. RBAC confines serving to the agent's own namespace.

---

## 8. Engine formulas (quick reference)

| Engine | Formula |
|---|---|
| Recommender score | `(w_q·quality + w_c·(1−norm(log price)) + w_s·(0.6·(1−norm latency)+0.4·norm tps)) / Σw` |
| Placement score | `(free/count)·40 + (100−util)·0.3 + (1/cost_factor)·20` after hard filters |
| Router score | `0.35 + Σ fired signal weights`, threshold = `router_threshold` |
| Cascade trigger | > 80 words or reasoning keyword → strongest model |
| Success rate | `completed / (completed + guardrail blocks)` |
| Budget runway | `(Σ budgets − Σ 30d spend) / (7d spend ÷ 7)` |
| Counterfactual | `share·price_small(shapes) + (1−share)·price_strong(shapes)` with **measured** share |
| Delta suppression | previous window < max(20, 5 % of current) → no delta |
| Anomaly | team output tokens vs own baseline (≈6× burst flags) |
| Carbon (cluster) | `used_GPUs × 0.4 kW × 24 h × 0.35 kg CO₂e/kWh` (labeled estimate) |
| Measured latency | ≥ 20 samples → telemetry overrides catalog estimate everywhere |

---

## 9. Deployment & operations

**One-file deploy** (clones the repo itself if needed):

```bash
./modelect-deploy.sh <quay-namespace>          # build+push+deploy, tag=latest
SKIP_BUILD=1 ./modelect-deploy.sh <ns>         # redeploy without rebuilding
WITH_POSTGRES=1 ./modelect-deploy.sh <ns>      # PostgreSQL instead of SQLite/PVC
INGRESS_HOST=host ./modelect-deploy.sh <ns>    # vanilla Kubernetes
./modelect-deploy.sh <ns> latest undeploy      # remove everything
```

Re-running is a full upgrade with the *same* tag: `imagePullPolicy: Always` +
an automatic `rollout restart` on redeploys. Alternatives: Helm chart
(`helm/modelect`), pre-rendered `bundle/*.yaml`, `scripts/one-shot-deploy.sh`.

**Key environment variables**

| Variable | Effect |
|---|---|
| `DATABASE_URL` | PostgreSQL instead of SQLite |
| `MODELECT_DATA_DIR` | data directory (PVC mount) |
| `DEMO_SEED=0` | no seeded history — every number grows from real traffic |
| `SIM_CLUSTERS=0` | hide the simulated fleet (real agents only) |
| `REGISTRY_OFFLINE=1` | registry connectors use the bundled snapshot |
| `ADMIN_PASSWORD` / `USER_PASSWORD` | override demo credentials |
| Agent: `MODELECT_URL`, `MODELECT_AGENT_TOKEN`, `CLUSTER_ID`, `SERVING_IMAGE`, `INSECURE_TLS` | control plane, enrollment, identity, vLLM image, lab TLS |

**API quick reference**

| Endpoint | Purpose |
|---|---|
| `POST /v1/chat/completions` | gateway (policies + receipts + SSE) |
| `GET /api/models`, `/api/models/{id}/similar` | catalog |
| `POST /api/recommend`, `/api/evals`, `/api/compare` | decide |
| `POST /api/whatif` | replay recorded traffic |
| `POST /api/migrate-plan` | cloud→GPU economics |
| `GET/POST /api/deployments`, `POST /api/placement` | deploy |
| `POST /api/integration-test`, `/api/playground`, `/api/router/preview` | integrate |
| `GET /api/tokenomics`, `PUT /api/teams/{id}` | govern |
| `GET /api/ledger` (+`/export`) | decision ledger |
| `GET /api/analytics/summary?days=`, `/api/router/summary`, `/api/dashboard/admin` | dashboards |
| `GET /api/clusters`, `PUT /api/clusters/{id}/cordon`, `GET /api/agents/token`, `POST /api/agents/clusters/{id}/token`, `POST /api/agent/v1/report` | fleet |
| `PUT /api/admin/outage`, `PUT /api/admin/webhook`, `GET/PUT /api/config` | settings |
| `GET /metrics`, `GET /healthz` | Prometheus scrape, probes (no session) |

**Observability — `GET /metrics`**

Prometheus text exposition (0.0.4), per replica, no extra dependency:

| Series | Type | Use |
|---|---|---|
| `modelect_http_requests_total{surface,method,status}` | counter | RPS and error rate, gateway split from portal |
| `modelect_gateway_request_seconds` | histogram | latency SLO / HPA signal (buckets 0.1s→10s) |
| `modelect_gateway_tokens_total{direction}` | counter | token throughput in/out |
| `modelect_gateway_cost_usd_total` | counter | spend rate — alert on the derivative, not the total |
| `modelect_enforcement_total{action}` | counter | guardrails firing (BUDGET/DEGRADE/BLOCK/LOOPBREAK/ANOMALY) |

`/metrics` carries no keys, tokens or prompt text, so it stays session-free
for scrapers. Counters are per-process: `sum()` across replicas in PromQL.

**Enrollment tokens — fleet-wide vs per-cluster**

The install-wide bootstrap token (GPU Fleet → Connect a cluster) still
enrolls anything, which is convenient and blast-radius-wide. Each live
cluster card therefore has **rotate token**: it mints a token bound to that
cluster only (`POST /api/agents/clusters/{id}/token`, admin-only, receipted
in the Decision Ledger). A leaked per-cluster token costs you one cluster,
not the fleet. Re-minting *is* the rotation — the previous value stops
working immediately, so update the agent's `MODELECT_AGENT_TOKEN` secret in
the same maintenance window. Reports never overwrite a stored token, and a
minted-but-not-yet-enrolled cluster shows no fleet card until its first
heartbeat.

**Hardening the namespace (Helm)**

`networkPolicies.enabled=true` writes a default-deny ingress policy plus the
only edges the product needs: `ui:8080` and `gateway:8000` open to the
router, `api:8000` reachable only from UI/gateway pods, and — when
`networkPolicies.postgresSelector` points at an in-namespace database —
`5432` only from API/gateway. It ships off, because a wrong policy looks
exactly like an outage; enable it once your topology is settled
(`allowApiFromIngress` if a Route targets the API directly,
`extraApiIngressSelectors` for your Prometheus). The split gateway also gets
a `PodDisruptionBudget` (`minAvailable: 1`, only above one replica) and a
*preferred* pod anti-affinity, so drains and upgrades can't take the request
path down while a single-node lab still schedules both replicas.

---

## 10. Honesty principles (the product's spine)

1. **Measured beats estimated** — and the UI always says which one you're
   looking at (latency chips, replay basis, savings cards).
2. **Simulated is labeled** — demo responses, simulated clusters, and
   fallbacks are marked (`backend: simulated / simulated-fallback`), never
   passed off as real.
3. **No silent numbers** — deltas are suppressed without a fair baseline;
   counterfactuals state their basis; carbon and allocation say they are
   estimates; "allocated ≠ busy".
4. **No prompt storage** — the platform records token counts, latency, cost
   and decisions; never prompt or response contents.
5. **Receipts, not assertions** — every decision can be replayed from the
   Ledger, exported, and audited.

---

## 11. Suggested demo walk-through

1. **Dashboard** — 14d view; click **24h** live to show hourly re-anchoring;
   point at runway, the attention queue, and the counterfactual banner.
2. **Playground** — type a simple question, watch the router preview say
   *simple → Phi-4*; paste an architecture prompt, watch it flip to
   *complex → strongest model* with signal chips.
3. **Tokenomics** — copy a team key, hit the gateway with it, watch spend
   attribute live; show a degrade receipt.
4. **GPU Fleet** — cordon a cluster, show placement skip it with the reason;
   show "fits up to" and the connect wizard.
5. **What-If Replay** — "what if everything ran on the router?" — savings from
   *their own* traffic.
6. **Settings** — declare a provider down, replay a pinned request, show the
   failover receipt; then open the **Decision Ledger** and export the CSV.
