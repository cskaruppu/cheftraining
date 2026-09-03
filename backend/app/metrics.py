"""Prometheus metrics — hand-rolled exposition, zero dependencies.

Per-process counters (each replica exposes its own /metrics, which is
exactly what Prometheus expects). The gateway's request/token/latency
series are the HPA and SLO signals; enforcement counters make
governance observable. Text exposition format 0.0.4.
"""
import threading

_lock = threading.Lock()
_counters: dict[tuple[str, tuple], float] = {}

# latency histogram buckets (seconds) for gateway requests
_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_hist: dict[float, int] = {b: 0 for b in _BUCKETS}
_hist_inf = 0
_hist_sum = 0.0
_hist_count = 0

_HELP = {
    "modelect_http_requests_total":
        "HTTP requests by surface (gateway/portal/other), method and status",
    "modelect_gateway_tokens_total": "Tokens metered through the gateway by direction",
    "modelect_gateway_cost_usd_total": "Estimated USD cost metered through the gateway",
    "modelect_enforcement_total": "Guardrail enforcement actions by action type",
    "modelect_gateway_request_seconds": "Gateway request latency",
}


def inc(name: str, labels: dict | None = None, value: float = 1.0) -> None:
    key = (name, tuple(sorted((labels or {}).items())))
    with _lock:
        _counters[key] = _counters.get(key, 0.0) + value


def observe_gateway_seconds(seconds: float) -> None:
    global _hist_inf, _hist_sum, _hist_count
    with _lock:
        for b in _BUCKETS:
            if seconds <= b:
                _hist[b] += 1
        _hist_inf += 1
        _hist_sum += seconds
        _hist_count += 1


def _fmt_labels(labels: tuple) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}"


def render() -> str:
    lines = []
    with _lock:
        seen = set()
        for (name, labels), value in sorted(_counters.items()):
            if name not in seen:
                seen.add(name)
                lines.append(f"# HELP {name} {_HELP.get(name, name)}")
                lines.append(f"# TYPE {name} counter")
            lines.append(f"{name}{_fmt_labels(labels)} {value}")
        h = "modelect_gateway_request_seconds"
        lines.append(f"# HELP {h} {_HELP[h]}")
        lines.append(f"# TYPE {h} histogram")
        cumulative = 0
        for b in _BUCKETS:
            cumulative = _hist[b]
            lines.append(f'{h}_bucket{{le="{b}"}} {cumulative}')
        lines.append(f'{h}_bucket{{le="+Inf"}} {_hist_inf}')
        lines.append(f"{h}_sum {round(_hist_sum, 4)}")
        lines.append(f"{h}_count {_hist_count}")
    return "\n".join(lines) + "\n"
