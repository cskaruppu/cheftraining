"""Registry connectors — live model discovery from external sources.

Adapters pull public catalogs (Hugging Face Hub, OpenRouter), normalize
them into one schema, and mark entries that match curated models so the
UI can dedupe into "channels" instead of duplicate cards.

Each adapter tries the live API (no keys required for public lists) and
falls back to a bundled snapshot when egress is blocked or the API is
down — so the catalog works air-gapped and comes alive when it can.
Results are cached in-process for SYNC_TTL seconds.
Set REGISTRY_OFFLINE=1 to force snapshots (tests, air-gapped demos).
"""
import os
import time
from datetime import datetime, timezone

import httpx

from .catalog import MODELS

_CACHE: dict[str, dict] = {}


def _sync_ttl() -> float:
    from . import config  # late import to avoid a cycle at module load
    return config.get("cache_ttl_hours") * 3600

# fragments of registry model names -> curated model id (channel dedupe)
_CURATED_MATCH = {
    "llama-4-maverick": "llama-4-maverick",
    "llama-4-scout": "llama-4-scout",
    "mistral-small-3.2": "mistral-small-3.2",
    "phi-4": "phi-4",
    "qwen3-235b": "qwen3-235b",
    "deepseek-r1": "deepseek-r1",
    "deepseek-v3.2": "deepseek-v3.2",
    "llama-3.3-70b": "vllm-local-llama-3.3-70b",
    "gpt-5.1": "gpt-5.1",
    "gpt-5-mini": "gpt-5-mini",
    "claude-sonnet-4.5": "claude-sonnet-4.5",
    "claude-opus-4.5": "claude-opus-4.5",
    "claude-haiku-4.5": "claude-haiku-4.5",
    "gemini-2.5-pro": "gemini-2.5-pro",
    "gemini-2.5-flash": "gemini-2.5-flash",
    "grok-4": "grok-4",
    "command-a": "command-a",
    "nova-pro": "nova-pro",
    "mistral-large": "mistral-large-2.1",
}


def _match_curated(name: str) -> str | None:
    slug = name.lower().replace("_", "-").replace(" ", "-").replace("/", "-")
    for frag, curated_id in _CURATED_MATCH.items():
        if frag in slug:
            return curated_id
    return None


# ------------------------- snapshots (fallback) ------------------------

_HF_SNAPSHOT = [
    {"id": "meta-llama/Llama-4-Maverick-17B-128E-Instruct", "downloads": 2_840_000, "likes": 4100, "license": "llama-4-community"},
    {"id": "meta-llama/Llama-4-Scout-17B-16E-Instruct", "downloads": 3_950_000, "likes": 3600, "license": "llama-4-community"},
    {"id": "mistralai/Mistral-Small-3.2-24B-Instruct", "downloads": 1_720_000, "likes": 2900, "license": "apache-2.0"},
    {"id": "microsoft/phi-4", "downloads": 5_100_000, "likes": 5200, "license": "mit"},
    {"id": "Qwen/Qwen3-235B-A22B-Instruct", "downloads": 980_000, "likes": 2400, "license": "apache-2.0"},
    {"id": "Qwen/Qwen3-8B", "downloads": 6_400_000, "likes": 3100, "license": "apache-2.0"},
    {"id": "deepseek-ai/DeepSeek-R1", "downloads": 2_260_000, "likes": 12800, "license": "mit"},
    {"id": "deepseek-ai/DeepSeek-V3.2", "downloads": 1_540_000, "likes": 6200, "license": "mit"},
    {"id": "google/gemma-3-27b-it", "downloads": 3_300_000, "likes": 2800, "license": "gemma"},
    {"id": "ibm-granite/granite-3.3-8b-instruct", "downloads": 890_000, "likes": 740, "license": "apache-2.0"},
    {"id": "allenai/OLMo-2-32B-Instruct", "downloads": 310_000, "likes": 520, "license": "apache-2.0"},
    {"id": "openai/gpt-oss-20b", "downloads": 4_700_000, "likes": 3900, "license": "apache-2.0"},
]

_OR_SNAPSHOT = [
    {"id": "openai/gpt-5.1", "name": "GPT-5.1", "context_length": 400_000, "prompt": 1.25e-6, "completion": 1e-5},
    {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5", "context_length": 1_000_000, "prompt": 3e-6, "completion": 1.5e-5},
    {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash", "context_length": 1_000_000, "prompt": 3e-7, "completion": 2.5e-6},
    {"id": "meta-llama/llama-4-maverick", "name": "Llama 4 Maverick", "context_length": 1_000_000, "prompt": 2.2e-7, "completion": 8.5e-7},
    {"id": "qwen/qwen3-235b-a22b", "name": "Qwen3 235B A22B", "context_length": 256_000, "prompt": 2e-7, "completion": 6e-7},
    {"id": "x-ai/grok-4", "name": "Grok 4", "context_length": 256_000, "prompt": 3e-6, "completion": 1.5e-5},
    {"id": "moonshotai/kimi-k2", "name": "Kimi K2", "context_length": 262_144, "prompt": 5.5e-7, "completion": 2.2e-6},
    {"id": "minimax/minimax-m1", "name": "MiniMax M1", "context_length": 1_000_000, "prompt": 3e-7, "completion": 1.65e-6},
    {"id": "mistralai/mistral-small-3.2", "name": "Mistral Small 3.2", "context_length": 128_000, "prompt": 1e-7, "completion": 3e-7},
    {"id": "z-ai/glm-4.5", "name": "GLM 4.5", "context_length": 128_000, "prompt": 6e-7, "completion": 2.2e-6},
]


# ----------------------------- adapters --------------------------------

def _offline() -> bool:
    return os.environ.get("REGISTRY_OFFLINE") == "1"


def _fetch_huggingface() -> tuple[list[dict], str]:
    raw, mode = _HF_SNAPSHOT, "snapshot"
    if not _offline():
        try:
            r = httpx.get(
                "https://huggingface.co/api/models",
                params={"pipeline_tag": "text-generation", "sort": "downloads",
                        "limit": 25, "full": "false"},
                timeout=6)
            r.raise_for_status()
            live = []
            for m in r.json():
                license_tag = next((t.split(":", 1)[1] for t in m.get("tags", [])
                                    if t.startswith("license:")), None)
                live.append({"id": m.get("modelId") or m.get("id"),
                             "downloads": m.get("downloads", 0),
                             "likes": m.get("likes", 0),
                             "license": license_tag})
            if live:
                raw, mode = live, "live"
        except Exception:
            pass  # keep snapshot

    entries = []
    for m in raw:
        org, _, short = m["id"].partition("/")
        entries.append({
            "id": f"hf/{m['id']}",
            "name": short or m["id"],
            "org": org,
            "registry": "huggingface",
            "source": "open",
            "license": m.get("license"),
            "downloads": m.get("downloads"),
            "likes": m.get("likes"),
            "input_price": None, "output_price": None, "context_window": None,
            "rated": False,
            "url": f"https://huggingface.co/{m['id']}",
            "matches_curated": _match_curated(m["id"]),
        })
    return entries, mode


def _fetch_openrouter() -> tuple[list[dict], str]:
    raw, mode = _OR_SNAPSHOT, "snapshot"
    if not _offline():
        try:
            r = httpx.get("https://openrouter.ai/api/v1/models", timeout=6)
            r.raise_for_status()
            live = []
            for m in r.json().get("data", [])[:40]:
                pricing = m.get("pricing", {})
                live.append({"id": m["id"], "name": m.get("name", m["id"]),
                             "context_length": m.get("context_length"),
                             "prompt": float(pricing.get("prompt", 0) or 0),
                             "completion": float(pricing.get("completion", 0) or 0)})
            if live:
                raw, mode = live, "live"
        except Exception:
            pass

    entries = []
    for m in raw:
        org = m["id"].split("/")[0]
        entries.append({
            "id": f"or/{m['id']}",
            "name": m["name"],
            "org": org,
            "registry": "openrouter",
            "source": "open" if org in {"meta-llama", "mistralai", "qwen", "deepseek", "z-ai", "moonshotai"} else "closed",
            "license": None,
            "downloads": None, "likes": None,
            "input_price": round(m["prompt"] * 1e6, 3),
            "output_price": round(m["completion"] * 1e6, 3),
            "context_window": m.get("context_length"),
            "rated": False,
            "url": f"https://openrouter.ai/models/{m['id']}",
            "matches_curated": _match_curated(m["id"] + " " + m["name"]),
        })
    return entries, mode


_ADAPTERS = {"huggingface": _fetch_huggingface, "openrouter": _fetch_openrouter}


def get_entries(sources: list[str]) -> dict:
    entries, sync = [], []
    for source in sources:
        adapter = _ADAPTERS.get(source)
        if not adapter:
            continue
        cached = _CACHE.get(source)
        if cached and time.time() - cached["at"] < _sync_ttl():
            data, mode, at = cached["entries"], cached["mode"], cached["at"]
        else:
            data, mode = adapter()
            at = time.time()
            _CACHE[source] = {"entries": data, "mode": mode, "at": at}
        entries.extend(data)
        sync.append({
            "registry": source, "mode": mode, "count": len(data),
            "synced_at": datetime.fromtimestamp(at, timezone.utc).strftime("%H:%M UTC"),
        })
    curated_ids = {m["id"] for m in MODELS}
    return {"entries": entries, "sync": sync, "curated_count": len(curated_ids)}


def force_sync(sources: list[str]) -> dict:
    for source in sources:
        _CACHE.pop(source, None)
    return get_entries(sources)


def price_provenance() -> dict:
    """curated model id -> live/snapshot OpenRouter price info (if matched).

    Uses only what's already cached — never triggers a sync on the hot
    catalog path.
    """
    cached = _CACHE.get("openrouter")
    if not cached:
        return {}
    out = {}
    for e in cached["entries"]:
        cid = e.get("matches_curated")
        if cid and e.get("input_price") is not None:
            out[cid] = {
                "source": f"openrouter-{cached['mode']}",
                "input_price": e["input_price"],
                "output_price": e["output_price"],
            }
    return out
