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


def backend_name() -> str:
    return "postgresql" if not _is_sqlite else "sqlite"
