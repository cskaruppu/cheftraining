"""Smart pre-router — classifies a request BEFORE any model is called.

Unlike cascade (try the SLM first, escalate when the reply looks weak —
escalated requests pay latency and tokens twice), the smart router
scores the request itself and makes exactly one model call. The score
is a weighted sum of observable request features; every decision ships
a receipt listing each signal's contribution, so routing is auditable
rather than a black box.

Maturity ladder: this heuristic router is rung 1. Its decisions —
together with cascade escalation history — become labeled training
data for an embedding classifier (rung 2) or a fine-tuned router
(rung 4) trained on the customer's own traffic. No fine-tuning is
needed to start.
"""
import re

from . import config
from .catalog import MODELS
from .recommender import recommend

# Neutral prompts with no signals land below the threshold: default to
# the small model, escalate only on positive evidence of complexity —
# that is what produces the 80–95% small-model share.
_BASE_SCORE = 0.35

_REASONING_KW = ("analyze", "architecture", "design", "legal", "contract",
                 "prove", "math", "step by step", "step-by-step", "plan",
                 "strategy", "debug", "reason", "trade-off", "tradeoff",
                 "optimize", "refactor")
_SIMPLE_KW = ("extract", "classify", "summarize", "translate", "list",
              "what is", "define", "rephrase", "reformat", "convert",
              "lookup", "spell")
_CODE_RE = re.compile(r"```|\bdef |\bclass |\bfunction\b|\bSELECT\b|=>|\{.*\}", re.S)


def classify(messages: list[dict]) -> dict:
    """Score request complexity in [0, 1] from observable features.

    Returns the verdict plus every signal that was evaluated — fired or
    not — with its weight, so the receipt shows the full decision."""
    prompt = next((m.get("content", "") for m in reversed(messages)
                   if m.get("role") == "user"), "")
    full_text = " ".join(m.get("content", "") for m in messages)
    words = len(prompt.split())
    lower = prompt.lower()

    kw_hits = [k for k in _REASONING_KW if k in lower]
    simple_hits = [k for k in _SIMPLE_KW if k in lower]
    checks = [
        ("long_prompt", "prompt length", 0.20, words > 120,
         f"{words} words"),
        ("very_long_prompt", "very long prompt", 0.15, words > 400,
         f"{words} words"),
        ("deep_conversation", "conversation depth", 0.10, len(messages) > 6,
         f"{len(messages)} turns"),
        ("code_present", "code in request", 0.20,
         bool(_CODE_RE.search(full_text)), "code block or code-like syntax"),
        ("reasoning_keywords", "reasoning keywords", 0.25, bool(kw_hits),
         ", ".join(kw_hits[:4]) or "none"),
        ("extraction_shaped", "extraction-shaped task", -0.20,
         bool(simple_hits), ", ".join(simple_hits[:4]) or "none"),
        ("short_question", "short question", -0.15,
         words < 30 and prompt.rstrip().endswith("?"), f"{words} words"),
    ]

    score = _BASE_SCORE
    signals = []
    for sid, label, weight, fired, detail in checks:
        if fired:
            score += weight
        signals.append({"signal": sid, "label": label, "weight": weight,
                        "fired": fired, "detail": detail if fired else None})
    score = round(min(1.0, max(0.0, score)), 3)

    threshold = float(config.get("router_threshold"))
    return {
        "verdict": "complex" if score >= threshold else "simple",
        "score": score,
        "threshold": threshold,
        "base_score": _BASE_SCORE,
        "signals": signals,
    }


def strong_model() -> dict:
    return max(MODELS, key=lambda m: m["quality"]["chat"])


def small_model() -> dict:
    return recommend("chatbot", {"quality": 30, "cost": 50, "speed": 20},
                     mode="smallest_capable", quality_floor=75)["results"][0]["model"]


def route(messages: list[dict]) -> dict:
    """Full routing decision: classification + the chosen model."""
    decision = classify(messages)
    small, strong = small_model(), strong_model()
    chosen = strong if decision["verdict"] == "complex" else small
    decision.update({
        "policy": "smart-router",
        "small": small["id"],
        "strong": strong["id"],
        "served_by": chosen["id"],
        "reason": ("classified complex before sending — routed to strongest model"
                   if decision["verdict"] == "complex" else
                   "classified simple before sending — one call to the small model"),
    })
    return {"decision": decision, "model": chosen, "strong": strong}
