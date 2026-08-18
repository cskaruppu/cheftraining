"""Persistence layer — single source of truth for runtime state.

Defaults to SQLite in MODELECT_DATA_DIR (zero-dependency, survives pod
restarts when the dir is a volume); set DATABASE_URL to a PostgreSQL
DSN for production/multi-replica deployments. Same schema either way.
"""
import os

from sqlalchemy import (Boolean, Column, Float, Integer, MetaData, String,
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
)

users_t = Table(
    "users", metadata,
    Column("username", String(80), primary_key=True),
    Column("password_hash", String(200)),
    Column("salt", String(64)),
    Column("role", String(20)),          # "admin" | "user"
    Column("team_id", String(40), nullable=True),
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

_team_cols = {c["name"] for c in _sa_inspect(engine).get_columns("teams")}
_TEAM_MIGRATIONS = {
    "enabled": "ALTER TABLE teams ADD COLUMN enabled BOOLEAN DEFAULT 1",
    "rate_limit_tpm": "ALTER TABLE teams ADD COLUMN rate_limit_tpm INTEGER",
    "max_input_tokens": "ALTER TABLE teams ADD COLUMN max_input_tokens INTEGER",
    "max_output_tokens": "ALTER TABLE teams ADD COLUMN max_output_tokens INTEGER",
    "allowed_tiers": "ALTER TABLE teams ADD COLUMN allowed_tiers VARCHAR(40)",
}
for _name, _ddl in _TEAM_MIGRATIONS.items():
    if _name not in _team_cols:
        with engine.begin() as _conn:
            _conn.execute(_sa_text(_ddl))


def backend_name() -> str:
    return "postgresql" if not _is_sqlite else "sqlite"
