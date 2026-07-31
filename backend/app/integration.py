"""Integration test suite (step 6 of the customer journey).

Verifies a customer's integration target: connectivity, auth, streaming,
structured-output (JSON Schema) compliance rate, and grounded-answer
quality — reported as measured scores, never as a "no hallucination"
guarantee.

Demo mode simulates the checks deterministically from the model's
capability profile; production runs them against the live endpoint
(same report contract).
"""
import random
import zlib

from .catalog import MODELS_BY_ID

_FORMAT_ATTEMPTS = 20
_GROUNDEDNESS_PROBES = 6


def run_integration_test(model_id: str) -> dict:
    model = MODELS_BY_ID.get(model_id)
    if not model:
        raise ValueError("unknown model")
    rng = random.Random(zlib.crc32(f"itest|{model_id}".encode()))

    checks = []

    latency = max(60, int(rng.gauss(model["latency_ms"], model["latency_ms"] * 0.1)))
    checks.append({
        "id": "connectivity", "label": "Endpoint connectivity",
        "status": "pass", "detail": f"HTTP 200 · TLS ok · {latency} ms first token",
    })
    checks.append({
        "id": "auth", "label": "API key authentication",
        "status": "pass", "detail": "Bearer key accepted; rejected request without key (401)",
    })
    checks.append({
        "id": "streaming", "label": "Streaming (SSE)",
        "status": "pass", "detail": "chunked stream received, [DONE] terminator present",
    })

    if "structured_output" in model["capabilities"]:
        valid = _FORMAT_ATTEMPTS - rng.choice([0, 0, 0, 1])
    else:
        valid = rng.randint(14, 17)
    rate = valid / _FORMAT_ATTEMPTS * 100
    checks.append({
        "id": "json_schema", "label": "JSON Schema compliance",
        "status": "pass" if rate >= 95 else "warn",
        "detail": f"{valid}/{_FORMAT_ATTEMPTS} responses validated against your schema ({rate:.0f}%)"
                  + ("" if rate >= 95 else " — add retry-on-invalid or pick a structured-output model"),
    })

    grounded = round(max(0, min(100, rng.gauss(model["quality"]["rag"] + 4, 2.5))), 1)
    checks.append({
        "id": "groundedness", "label": "Groundedness (measured)",
        "status": "pass" if grounded >= 80 else "warn",
        "detail": f"score {grounded}/100 across {_GROUNDEDNESS_PROBES} probes with reference context "
                  "(judge-scored faithfulness — measured, not promised)",
    })

    overall = "pass" if all(c["status"] == "pass" for c in checks) else "warn"
    return {
        "mode": "simulated",  # production: "live"
        "model_id": model_id,
        "model_name": model["name"],
        "overall": overall,
        "checks": checks,
    }
