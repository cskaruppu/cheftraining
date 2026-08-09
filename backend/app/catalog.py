"""Model Registry — demo seed data.

In production this registry is populated by sync jobs (provider APIs,
OpenRouter's public model list, Hugging Face Hub, local vLLM endpoints)
and enriched with live telemetry observed through the gateway.
For the demo it ships as a static seed so the platform runs with no
external dependencies or API keys.

Prices are USD per 1M tokens. Quality scores are 0-100 per task
category (seeded from public benchmark aggregates; replace with your
own eval pipeline in production).
"""

MODELS = [
    {
        "id": "gpt-5.1", "name": "GPT-5.1", "provider": "OpenAI", "source": "closed",
        "context_window": 400_000, "max_output": 128_000,
        "input_price": 1.25, "output_price": 10.00,
        "latency_ms": 520, "throughput_tps": 105,
        "quality": {"coding": 93, "reasoning": 94, "summarization": 91, "translation": 89, "math": 94, "chat": 92, "rag": 91},
        "capabilities": ["function_calling", "structured_output", "vision", "reasoning"],
        "license": "proprietary", "regions": ["us", "eu"], "knowledge_cutoff": "2025-09", "self_hostable": False,
    },
    {
        "id": "gpt-5-mini", "name": "GPT-5 mini", "provider": "OpenAI", "source": "closed",
        "context_window": 400_000, "max_output": 128_000,
        "input_price": 0.25, "output_price": 2.00,
        "latency_ms": 320, "throughput_tps": 170,
        "quality": {"coding": 84, "reasoning": 85, "summarization": 86, "translation": 84, "math": 85, "chat": 87, "rag": 85},
        "capabilities": ["function_calling", "structured_output", "vision"],
        "license": "proprietary", "regions": ["us", "eu"], "knowledge_cutoff": "2025-09", "self_hostable": False,
    },
    {
        "id": "o4-mini", "name": "o4-mini", "provider": "OpenAI", "source": "closed",
        "context_window": 200_000, "max_output": 100_000,
        "input_price": 1.10, "output_price": 4.40,
        "latency_ms": 900, "throughput_tps": 90,
        "quality": {"coding": 90, "reasoning": 92, "summarization": 84, "translation": 80, "math": 93, "chat": 82, "rag": 86},
        "capabilities": ["function_calling", "structured_output", "reasoning"],
        "license": "proprietary", "regions": ["us", "eu"], "knowledge_cutoff": "2025-06", "self_hostable": False,
    },
    {
        "id": "claude-opus-4.5", "name": "Claude Opus 4.5", "provider": "Anthropic", "source": "closed",
        "context_window": 200_000, "max_output": 64_000,
        "input_price": 5.00, "output_price": 25.00,
        "latency_ms": 650, "throughput_tps": 85,
        "quality": {"coding": 95, "reasoning": 95, "summarization": 93, "translation": 90, "math": 92, "chat": 93, "rag": 93},
        "capabilities": ["function_calling", "structured_output", "vision", "reasoning"],
        "license": "proprietary", "regions": ["us", "eu"], "knowledge_cutoff": "2025-08", "self_hostable": False,
    },
    {
        "id": "claude-sonnet-4.5", "name": "Claude Sonnet 4.5", "provider": "Anthropic", "source": "closed",
        "context_window": 1_000_000, "max_output": 64_000,
        "input_price": 3.00, "output_price": 15.00,
        "latency_ms": 480, "throughput_tps": 120,
        "quality": {"coding": 92, "reasoning": 91, "summarization": 91, "translation": 88, "math": 89, "chat": 92, "rag": 92},
        "capabilities": ["function_calling", "structured_output", "vision", "reasoning"],
        "license": "proprietary", "regions": ["us", "eu"], "knowledge_cutoff": "2025-07", "self_hostable": False,
    },
    {
        "id": "claude-haiku-4.5", "name": "Claude Haiku 4.5", "provider": "Anthropic", "source": "closed",
        "context_window": 200_000, "max_output": 64_000,
        "input_price": 1.00, "output_price": 5.00,
        "latency_ms": 280, "throughput_tps": 190,
        "quality": {"coding": 86, "reasoning": 84, "summarization": 87, "translation": 85, "math": 82, "chat": 89, "rag": 87},
        "capabilities": ["function_calling", "structured_output", "vision"],
        "license": "proprietary", "regions": ["us", "eu"], "knowledge_cutoff": "2025-07", "self_hostable": False,
    },
    {
        "id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "provider": "Google", "source": "closed",
        "context_window": 1_000_000, "max_output": 65_000,
        "input_price": 1.25, "output_price": 10.00,
        "latency_ms": 560, "throughput_tps": 115,
        "quality": {"coding": 91, "reasoning": 92, "summarization": 92, "translation": 92, "math": 91, "chat": 90, "rag": 92},
        "capabilities": ["function_calling", "structured_output", "vision", "audio", "reasoning"],
        "license": "proprietary", "regions": ["us", "eu", "asia"], "knowledge_cutoff": "2025-06", "self_hostable": False,
    },
    {
        "id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "provider": "Google", "source": "closed",
        "context_window": 1_000_000, "max_output": 65_000,
        "input_price": 0.30, "output_price": 2.50,
        "latency_ms": 250, "throughput_tps": 210,
        "quality": {"coding": 83, "reasoning": 84, "summarization": 87, "translation": 88, "math": 83, "chat": 87, "rag": 88},
        "capabilities": ["function_calling", "structured_output", "vision", "audio"],
        "license": "proprietary", "regions": ["us", "eu", "asia"], "knowledge_cutoff": "2025-06", "self_hostable": False,
    },
    {
        "id": "llama-4-maverick", "name": "Llama 4 Maverick", "provider": "Meta", "source": "open",
        "context_window": 1_000_000, "max_output": 32_000,
        "input_price": 0.22, "output_price": 0.85,
        "latency_ms": 380, "throughput_tps": 140,
        "quality": {"coding": 84, "reasoning": 85, "summarization": 86, "translation": 86, "math": 83, "chat": 87, "rag": 86},
        "capabilities": ["function_calling", "structured_output", "vision"],
        "license": "llama-4-community", "regions": ["self-hosted", "us", "eu"], "knowledge_cutoff": "2025-03", "self_hostable": True,
    },
    {
        "id": "llama-4-scout", "name": "Llama 4 Scout", "provider": "Meta", "source": "open",
        "context_window": 10_000_000, "max_output": 32_000,
        "input_price": 0.11, "output_price": 0.34,
        "latency_ms": 300, "throughput_tps": 180,
        "quality": {"coding": 78, "reasoning": 79, "summarization": 82, "translation": 82, "math": 76, "chat": 83, "rag": 84},
        "capabilities": ["function_calling", "structured_output", "vision"],
        "license": "llama-4-community", "regions": ["self-hosted", "us", "eu"], "knowledge_cutoff": "2025-03", "self_hostable": True,
    },
    {
        "id": "mistral-large-2.1", "name": "Mistral Large 2.1", "provider": "Mistral AI", "source": "closed",
        "context_window": 128_000, "max_output": 32_000,
        "input_price": 2.00, "output_price": 6.00,
        "latency_ms": 450, "throughput_tps": 120,
        "quality": {"coding": 87, "reasoning": 87, "summarization": 87, "translation": 90, "math": 86, "chat": 88, "rag": 88},
        "capabilities": ["function_calling", "structured_output"],
        "license": "proprietary", "regions": ["eu", "us"], "knowledge_cutoff": "2025-05", "self_hostable": False,
    },
    {
        "id": "mistral-small-3.2", "name": "Mistral Small 3.2", "provider": "Mistral AI", "source": "open",
        "context_window": 128_000, "max_output": 32_000,
        "input_price": 0.10, "output_price": 0.30,
        "latency_ms": 260, "throughput_tps": 200,
        "quality": {"coding": 79, "reasoning": 78, "summarization": 82, "translation": 86, "math": 76, "chat": 84, "rag": 83},
        "capabilities": ["function_calling", "structured_output", "vision"],
        "license": "apache-2.0", "regions": ["self-hosted", "eu", "us"], "knowledge_cutoff": "2025-04", "self_hostable": True,
    },
    {
        "id": "deepseek-v3.2", "name": "DeepSeek-V3.2", "provider": "DeepSeek", "source": "open",
        "context_window": 128_000, "max_output": 32_000,
        "input_price": 0.27, "output_price": 1.10,
        "latency_ms": 520, "throughput_tps": 100,
        "quality": {"coding": 89, "reasoning": 88, "summarization": 86, "translation": 85, "math": 90, "chat": 86, "rag": 86},
        "capabilities": ["function_calling", "structured_output"],
        "license": "mit", "regions": ["self-hosted", "asia", "us"], "knowledge_cutoff": "2025-04", "self_hostable": True,
    },
    {
        "id": "deepseek-r1", "name": "DeepSeek-R1", "provider": "DeepSeek", "source": "open",
        "context_window": 128_000, "max_output": 64_000,
        "input_price": 0.55, "output_price": 2.19,
        "latency_ms": 1100, "throughput_tps": 70,
        "quality": {"coding": 90, "reasoning": 92, "summarization": 83, "translation": 82, "math": 94, "chat": 80, "rag": 84},
        "capabilities": ["structured_output", "reasoning"],
        "license": "mit", "regions": ["self-hosted", "asia", "us"], "knowledge_cutoff": "2025-01", "self_hostable": True,
    },
    {
        "id": "qwen3-235b", "name": "Qwen3 235B", "provider": "Alibaba", "source": "open",
        "context_window": 256_000, "max_output": 32_000,
        "input_price": 0.20, "output_price": 0.60,
        "latency_ms": 430, "throughput_tps": 130,
        "quality": {"coding": 87, "reasoning": 88, "summarization": 85, "translation": 89, "math": 89, "chat": 85, "rag": 85},
        "capabilities": ["function_calling", "structured_output", "reasoning"],
        "license": "apache-2.0", "regions": ["self-hosted", "asia"], "knowledge_cutoff": "2025-02", "self_hostable": True,
    },
    {
        "id": "command-a", "name": "Command A", "provider": "Cohere", "source": "closed",
        "context_window": 256_000, "max_output": 8_000,
        "input_price": 2.50, "output_price": 10.00,
        "latency_ms": 400, "throughput_tps": 130,
        "quality": {"coding": 82, "reasoning": 83, "summarization": 88, "translation": 87, "math": 79, "chat": 87, "rag": 91},
        "capabilities": ["function_calling", "structured_output"],
        "license": "proprietary", "regions": ["us", "eu"], "knowledge_cutoff": "2025-03", "self_hostable": False,
    },
    {
        "id": "grok-4", "name": "Grok 4", "provider": "xAI", "source": "closed",
        "context_window": 256_000, "max_output": 64_000,
        "input_price": 3.00, "output_price": 15.00,
        "latency_ms": 700, "throughput_tps": 95,
        "quality": {"coding": 90, "reasoning": 92, "summarization": 87, "translation": 85, "math": 93, "chat": 88, "rag": 87},
        "capabilities": ["function_calling", "structured_output", "vision", "reasoning"],
        "license": "proprietary", "regions": ["us"], "knowledge_cutoff": "2025-11", "self_hostable": False,
    },
    {
        "id": "nova-pro", "name": "Nova Pro", "provider": "Amazon", "source": "closed",
        "context_window": 300_000, "max_output": 10_000,
        "input_price": 0.80, "output_price": 3.20,
        "latency_ms": 420, "throughput_tps": 125,
        "quality": {"coding": 81, "reasoning": 82, "summarization": 85, "translation": 84, "math": 80, "chat": 85, "rag": 86},
        "capabilities": ["function_calling", "structured_output", "vision"],
        "license": "proprietary", "regions": ["us", "eu"], "knowledge_cutoff": "2024-12", "self_hostable": False,
    },
    {
        "id": "phi-4", "name": "Phi-4 14B", "provider": "Microsoft", "source": "open",
        "context_window": 16_000, "max_output": 16_000,
        "input_price": 0.07, "output_price": 0.14,
        "latency_ms": 180, "throughput_tps": 240,
        "quality": {"coding": 76, "reasoning": 78, "summarization": 78, "translation": 75, "math": 81, "chat": 79, "rag": 76},
        "capabilities": ["structured_output"],
        "license": "mit", "regions": ["self-hosted"], "knowledge_cutoff": "2024-10", "self_hostable": True,
    },
    {
        "id": "vllm-local-llama-3.3-70b", "name": "Llama 3.3 70B (local vLLM)", "provider": "Self-hosted / vLLM", "source": "open",
        "context_window": 128_000, "max_output": 32_000,
        "input_price": 0.05, "output_price": 0.08,
        "latency_ms": 350, "throughput_tps": 90,
        "quality": {"coding": 80, "reasoning": 81, "summarization": 83, "translation": 83, "math": 78, "chat": 84, "rag": 83},
        "capabilities": ["function_calling", "structured_output"],
        "license": "llama-3.3-community", "regions": ["self-hosted"], "knowledge_cutoff": "2024-12", "self_hostable": True,
    },
]

# Size metadata: (known parameter count in billions or None for
# undisclosed closed models, size class). "slm" = small language model
# (~<=30B), the tier the market's SLM conversation is about.
_SIZING = {
    "gpt-5.1": (None, "large"),
    "gpt-5-mini": (None, "mid"),
    "o4-mini": (None, "mid"),
    "claude-opus-4.5": (None, "large"),
    "claude-sonnet-4.5": (None, "large"),
    "claude-haiku-4.5": (None, "mid"),
    "gemini-2.5-pro": (None, "large"),
    "gemini-2.5-flash": (None, "mid"),
    "llama-4-maverick": (400, "large"),
    "llama-4-scout": (109, "mid"),
    "mistral-large-2.1": (123, "mid"),
    "mistral-small-3.2": (24, "slm"),
    "deepseek-v3.2": (671, "large"),
    "deepseek-r1": (671, "large"),
    "qwen3-235b": (235, "large"),
    "command-a": (111, "mid"),
    "grok-4": (None, "large"),
    "nova-pro": (None, "mid"),
    "phi-4": (14, "slm"),
    "vllm-local-llama-3.3-70b": (70, "mid"),
}
_SIZE_RANK = {"slm": 0, "mid": 1, "large": 2}

for _m in MODELS:
    _params, _cls = _SIZING[_m["id"]]
    _m["params_b"] = _params
    _m["size_class"] = _cls

MODELS_BY_ID = {m["id"]: m for m in MODELS}


def size_rank(model: dict) -> tuple:
    """Sort key: smaller class first, then known params, then price."""
    return (_SIZE_RANK[model["size_class"]],
            model["params_b"] if model["params_b"] is not None else 9999,
            blended_price(model))

USE_CASES = [
    {"id": "chatbot", "label": "Chatbot / assistant", "dimension": "chat"},
    {"id": "coding", "label": "Code generation & review", "dimension": "coding"},
    {"id": "rag", "label": "RAG / knowledge search", "dimension": "rag"},
    {"id": "summarization", "label": "Summarization", "dimension": "summarization"},
    {"id": "translation", "label": "Translation", "dimension": "translation"},
    {"id": "reasoning", "label": "Agents / complex reasoning", "dimension": "reasoning"},
    {"id": "math", "label": "Math & data analysis", "dimension": "math"},
]

QUALITY_DIMS = ["coding", "reasoning", "summarization", "translation", "math", "chat", "rag"]


def blended_price(model: dict) -> float:
    """$ per 1M tokens assuming a typical 3:1 input:output token ratio."""
    return (3 * model["input_price"] + model["output_price"]) / 4


def avg_quality(model: dict) -> float:
    q = model["quality"]
    return sum(q.values()) / len(q)
