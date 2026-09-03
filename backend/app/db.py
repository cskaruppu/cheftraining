"""Persistence layer — single source of truth for runtime state.

Defaults to SQLite in MODELECT_DATA_DIR (zero-dependency, survives pod
restarts when the dir is a volume); set DATABASE_URL to a PostgreSQL
DSN for production/multi-replica deployments. Same schema either way.
"""
import os

# Split-topology role: "gateway" pods serve only /v1 and never run the
# seeders (the control pod owns seeding, avoiding boot races between
# replicas). Default "combined" behaves exactly as before.
IS_GATEWAY_ROLE = os.environ.get("MODELECT_ROLE", "").lower() == "gateway"

from sqlalchemy import (Boolean, Column, Float, Integer, MetaData, String, Text,
                        Table, create_engine)

DATA_DIR = os.environ.get(
    "MODELECT_DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", f"sqlite:///{os.path.join(DATA_DIR, 'modelect.db')}")

_is_sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(
    DATABASE_URL, future=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {})

metadata = MetaData()

deployments_t = Table(
    "deployments", metadata,
    Column("id", String(16), primary_key=True),
    Column("name", String(120)),
    Column("model_id", String(80)),
    Column("model_name", String(120)),
    Column("profile_json", String(1000)),
    Column("cluster_id", String(80)),
    Column("cluster_name", String(120)),
    Column("api_key", String(80)),
    Column("created_at", Float),
    Column("serving_class", String(12)),   # reserved | on-demand
    Column("asleep", Boolean, default=False),
)

# GPU thin provisioning ledger: every sleep period of an on-demand
# deployment (woke_at NULL = still asleep). Sum -> GPU-hours reclaimed.
sleep_log_t = Table(
    "sleep_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("dep_id", String(16), index=True),
    Column("cluster_id", String(80)),
    Column("gpus", Integer),
    Column("slept_at", Float),
    Column("woke_at", Float, nullable=True),
)

events_t = Table(
    "analytics_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", String(40), index=True),
    Column("day", String(10), index=True),
    Column("model_id", String(80)),
    Column("model_name", String(120)),
    Column("tokens_in", Integer),
    Column("tokens_out", Integer),
    Column("latency_ms", Integer),
    Column("cached", Boolean),
    Column("cost", Float),
    Column("team_id", String(40), nullable=True, index=True),
    Column("policy", String(20), nullable=True),
    Column("backend", String(20), nullable=True),
    Column("agent_id", String(60), nullable=True, index=True),
    Column("task_id", String(80), nullable=True, index=True),
)

teams_t = Table(
    "teams", metadata,
    Column("id", String(40), primary_key=True),
    Column("name", String(120)),
    Column("api_key", String(80)),
    Column("budget_usd", Float),        # rolling 30-day budget
    Column("policy", String(20)),       # "alert" | "degrade"
    Column("enabled", Boolean, default=True),        # kill switch
    Column("rate_limit_tpm", Integer, nullable=True),  # tokens/minute
    Column("max_input_tokens", Integer, nullable=True),
    Column("max_output_tokens", Integer, nullable=True),
    Column("allowed_tiers", String(40), nullable=True),  # e.g. "slm,mid"
    Column("loop_policy", String(20), nullable=True),    # off|degrade — loop-breaker
    Column("max_delegation_depth", Integer, nullable=True),
)

# AI agents: sub-identities under a team — the agentic-era attribution
# unit. Each has its own key so spend/limits/anomalies work per agent.
ai_agents_t = Table(
    "ai_agents", metadata,
    Column("id", String(60), primary_key=True),
    Column("team_id", String(40), index=True),
    Column("name", String(120)),
    Column("api_key", String(80), index=True),
    Column("created_at", Float),
)

# Mission budgets: a task is a bounded unit of agent work ("this research
# job may spend $0.50") metered across every call that carries its id.
tasks_t = Table(
    "agent_tasks", metadata,
    Column("id", String(80), primary_key=True),
    Column("team_id", String(40), index=True),
    Column("agent_id", String(60), nullable=True),
    Column("budget_usd", Float, nullable=True),
    Column("created_at", Float),
    Column("completed", Boolean, default=False),
    Column("completed_at", Float, nullable=True),
)

agents_t = Table(
    "agent_clusters", metadata,
    Column("cluster_id", String(80), primary_key=True),
    Column("name", String(120)),
    Column("platform", String(20)),
    Column("version", String(40)),
    Column("region", String(40)),
    Column("residency", String(20)),
    Column("cost_factor", Float),
    Column("gpus_json", String(4000)),   # [{family,type,count}]
    Column("nodes", Integer),
    Column("last_seen", Float),
    Column("gpu_class", String(20)),     # gpu-ready | gpu-unmanaged | cpu-only
    Column("operator_detected", Boolean),
    Column("driver_version", String(40)),
    Column("cuda_version", String(20)),
    Column("agent_version", String(20)),
    Column("token", String(80), nullable=True),  # per-cluster enrollment token
)

work_t = Table(
    "agent_work", metadata,
    Column("id", String(16), primary_key=True),      # = deployment id
    Column("cluster_id", String(80), index=True),
    Column("model_id", String(80)),
    Column("hf_repo", String(200)),
    Column("gpu_count", Integer),
    Column("action", String(10)),    # deploy | delete
    Column("state", String(20)),     # pending|starting|pulling|ready|error|deleted
    Column("endpoint", String(300)),
    Column("message", String(300)),
    Column("updated", Float),
)

users_t = Table(
    "users", metadata,
    Column("username", String(80), primary_key=True),
    Column("password_hash", String(200)),
    Column("salt", String(64)),
    Column("role", String(20)),          # "admin" | "user"
    Column("team_id", String(40), nullable=True),
)

# immutable record of every model decision the platform makes — the
# routing/enforcement/failover/placement receipts, kept for governance
# (record-keeping for AI-governance audits; append-only by convention)
ledger_t = Table(
    "decision_ledger", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", String(40), index=True),
    Column("day", String(10), index=True),
    Column("kind", String(20), index=True),   # routing|enforcement|failover|placement
    Column("policy", String(20)),             # auto|cascade|route|direct
    Column("model_id", String(80)),
    Column("team_id", String(40), nullable=True),
    Column("summary", String(400)),
    Column("receipt_json", Text),
)

# per-cluster allocation history: sampled by the fleet snapshot (throttled),
# feeds the 24h sparkline on the GPU Fleet page; pruned after 48h
cluster_util_t = Table(
    "cluster_util_history", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cluster_id", String(80), index=True),
    Column("ts", Float, index=True),
    Column("util_pct", Integer),
)

# small string settings (webhook URL, drill state) — config_t is numeric
settings_kv_t = Table(
    "settings_kv", metadata,
    Column("key", String(60), primary_key=True),
    Column("value", Text),
)

enforcement_t = Table(
    "enforcement_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", String(40), index=True),
    Column("team_id", String(40)),
    Column("action", String(20)),       # BUDGET | DEGRADE | ANOMALY
    Column("detail", String(400)),
)

config_t = Table(
    "config", metadata,
    Column("key", String(80), primary_key=True),
    Column("value", Float),
    Column("label", String(120)),
    Column("description", String(300)),
    Column("min_value", Float),
    Column("max_value", Float),
)

metadata.create_all(engine)

# Migration for databases created before the tokenomics module:
# add the attribution column to existing event tables.
from sqlalchemy import inspect as _sa_inspect, text as _sa_text  # noqa: E402

_cols = {c["name"] for c in _sa_inspect(engine).get_columns("analytics_events")}
if "team_id" not in _cols:
    with engine.begin() as _conn:
        _conn.execute(_sa_text(
            "ALTER TABLE analytics_events ADD COLUMN team_id VARCHAR(40)"))
if "policy" not in _cols:
    with engine.begin() as _conn:
        _conn.execute(_sa_text(
            "ALTER TABLE analytics_events ADD COLUMN policy VARCHAR(20)"))
if "backend" not in _cols:
    with engine.begin() as _conn:
        _conn.execute(_sa_text(
            "ALTER TABLE analytics_events ADD COLUMN backend VARCHAR(20)"))
if "agent_id" not in _cols:
    with engine.begin() as _conn:
        _conn.execute(_sa_text(
            "ALTER TABLE analytics_events ADD COLUMN agent_id VARCHAR(60)"))
if "task_id" not in _cols:
    with engine.begin() as _conn:
        _conn.execute(_sa_text(
            "ALTER TABLE analytics_events ADD COLUMN task_id VARCHAR(80)"))

_team_cols = {c["name"] for c in _sa_inspect(engine).get_columns("teams")}
_TEAM_MIGRATIONS = {
    "enabled": "ALTER TABLE teams ADD COLUMN enabled BOOLEAN DEFAULT 1",
    "rate_limit_tpm": "ALTER TABLE teams ADD COLUMN rate_limit_tpm INTEGER",
    "max_input_tokens": "ALTER TABLE teams ADD COLUMN max_input_tokens INTEGER",
    "max_output_tokens": "ALTER TABLE teams ADD COLUMN max_output_tokens INTEGER",
    "allowed_tiers": "ALTER TABLE teams ADD COLUMN allowed_tiers VARCHAR(40)",
    "loop_policy": "ALTER TABLE teams ADD COLUMN loop_policy VARCHAR(20)",
    "max_delegation_depth": "ALTER TABLE teams ADD COLUMN max_delegation_depth INTEGER",
}
for _name, _ddl in _TEAM_MIGRATIONS.items():
    if _name not in _team_cols:
        with engine.begin() as _conn:
            _conn.execute(_sa_text(_ddl))

_dep_cols = {c["name"] for c in _sa_inspect(engine).get_columns("deployments")}
_DEP_MIGRATIONS = {
    "serving_class": "ALTER TABLE deployments ADD COLUMN serving_class VARCHAR(12)",
    "asleep": "ALTER TABLE deployments ADD COLUMN asleep BOOLEAN DEFAULT 0",
}
for _name, _ddl in _DEP_MIGRATIONS.items():
    if _name not in _dep_cols:
        with engine.begin() as _conn:
            _conn.execute(_sa_text(_ddl))

_agent_cols = {c["name"] for c in _sa_inspect(engine).get_columns("agent_clusters")}
_AGENT_MIGRATIONS = {
    "gpu_class": "ALTER TABLE agent_clusters ADD COLUMN gpu_class VARCHAR(20)",
    "operator_detected": "ALTER TABLE agent_clusters ADD COLUMN operator_detected BOOLEAN",
    "driver_version": "ALTER TABLE agent_clusters ADD COLUMN driver_version VARCHAR(40)",
    "cuda_version": "ALTER TABLE agent_clusters ADD COLUMN cuda_version VARCHAR(20)",
    "agent_version": "ALTER TABLE agent_clusters ADD COLUMN agent_version VARCHAR(20)",
    "token": "ALTER TABLE agent_clusters ADD COLUMN token VARCHAR(80)",
}
for _name, _ddl in _AGENT_MIGRATIONS.items():
    if _name not in _agent_cols:
        with engine.begin() as _conn:
            _conn.execute(_sa_text(_ddl))


def backend_name() -> str:
    return "postgresql" if not _is_sqlite else "sqlite"
