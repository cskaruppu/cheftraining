# Modelect — Product Vision

*One page. Draft for team feedback.*

## Positioning

> **Modelect is the intelligence and governance control plane for an
> enterprise's entire model estate — private and public — where teams
> choose, right-size, deploy, route, and continuously optimize LLMs
> with evidence, the way they manage VMs today.**

Don't build the hypervisor — build the vCenter. Serving stacks (vLLM,
KServe, NVIDIA NIM, cloud provider APIs) are becoming commodity "hosts."
The lasting value is the management brain on top: the layer that decides
*which* model, *what size*, *where it runs*, *who may use it*, and
*whether it is still the right choice next month*.

## The problem

- Choosing an LLM is guesswork: hundreds of models, weekly releases,
  opaque trade-offs between quality, cost, latency and privacy.
- Hosting an LLM means procuring GPU servers and hand-tuning serving
  stacks — weeks of work before the first token.
- Enterprises end up with a split estate — some private models, many
  public APIs — with no single pane for catalog, cost, routing or
  governance across both.

## What Modelect does (three pillars)

1. **Decide** — requirement in (wizard, natural language, or sample
   prompts) → transparent, scored recommendation out: which model, which
   serving profile (GPU + quantization), projected monthly cost, and the
   reasoning shown. Never a black box.
2. **Deploy & Route** — one catalog spanning *hosted* models (open
   weights from public registries such as Hugging Face, or the
   customer's own fine-tuned models, provisioned VM-style onto their
   GPUs via vLLM/KServe) and *consumed* models (OpenAI, Anthropic,
   Google, …) — all behind one OpenAI-compatible gateway with failover,
   caching and data-sensitivity routing policies (e.g. "PII stays on
   the private model; generic traffic takes the cheapest capable API").
3. **Govern** — budgets and quotas per team/agent, approval gates for
   consequential changes, trust graduation (proven optimizations become
   automatic), verified-outcome reports ("the switch delivered the
   predicted 3.1x savings"), audit logs.

## Differentiation (vs. today's market)

Not claiming the pieces are unprecedented — the *combination* and the
transparency are the difference:

| Competitor class | They have | They lack |
|---|---|---|
| Gateways (LiteLLM, OpenRouter, Portkey) | unified API, failover | recommendation brain, provisioning, sizing |
| Routers (Not Diamond, Martian) | smart routing | transparency, hybrid estate, governance |
| Serving platforms (OpenShift AI, NIM, Baseten, Together) | deploy + endpoint | "which model & size for my requirement?", cross-estate routing/cost governance |
| Observability (Helicone, Langfuse) | tracing, cost views | acting on it: routing, provisioning, optimization loop |

Modelect's signature moves: **recommendation-driven sizing** (nobody
helps users pick GPU/quantization from a requirement), **hybrid catalog**
(hosted + API models in one pane), **accountable optimization**
(recommend → approve → apply → verify → report), and — as the market
matures — **agent-aware governance** (per-agent identity, budgets and
model policies for agentic workloads that make thousands of calls).

## Who it's for

Platform/infra teams standing up "AI as a service" for their company;
app teams building agentic AI who want an endpoint, not a GPU project;
CFO/compliance stakeholders who need cost and data-residency control.

## Business model

Software-first (the VMware play): customers run Modelect on their own
OpenShift/Kubernetes and bring their own GPUs or cloud accounts — no
capex for us, fits sovereign/private-AI demand. Hosted control plane and
a managed offering can follow. Open-source core + paid
governance/optimization tier is the proven route in this space.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Demo portal: catalog, recommend, compare, playground, analytics, simulated VM-style deploy, OpenAI-compatible gateway | **shipped (this repo)** |
| 2 | Real provisioning on one cluster (KServe/vLLM), real provider adapters, registry sync (HF Hub + provider APIs), bring-your-own fine-tuned models | next |
| 3 | Multi-tenancy: API keys, quotas, metering, per-team cost dashboards; data-sensitivity routing policies | |
| 4 | Optimization loop with approval gates, trust graduation, verified savings; agent-aware budgets & policies; Go data-plane gateway, ClickHouse analytics | |

## Non-goals (for focus)

Building our own serving engine (integrate vLLM/KServe/NIM instead);
training or fine-tuning infrastructure (import the results instead);
competing as a GPU cloud.
