"""
Lightweight SQLAlchemy connection helpers for the Clarity Postgres prototype.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()


@dataclass(frozen=True)
class ClarityPostgresConfig:
    """Configuration for direct read-only access to the Clarity Postgres database."""

    database: str
    username: str
    password: str
    host: str = "localhost"
    port: int = 5432
    url: str | None = None
    connect_timeout_seconds: int = 5

    @classmethod
    def from_env(cls) -> "ClarityPostgresConfig":
        return cls(
            database=os.getenv("CLARITY_PG_DB", ""),
            username=os.getenv("CLARITY_PG_USER", ""),
            password=os.getenv("CLARITY_PG_PASSWORD", ""),
            host=os.getenv("CLARITY_PG_HOST", "localhost"),
            port=int(os.getenv("CLARITY_PG_PORT", "5432")),
            url=os.getenv("CLARITY_PG_URL"),
            connect_timeout_seconds=int(os.getenv("CLARITY_PG_CONNECT_TIMEOUT_SECONDS", "5")),
        )

    def sqlalchemy_url(self) -> str | URL:
        if self.url:
            return self.url
        return URL.create(
            "postgresql+psycopg",
            username=self.username or None,
            password=self.password or None,
            host=self.host,
            port=self.port,
            database=self.database or None,
        )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return a shared SQLAlchemy engine for Clarity Postgres."""
    config = ClarityPostgresConfig.from_env()
    return create_engine(
        config.sqlalchemy_url(),
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={"connect_timeout": config.connect_timeout_seconds},
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker:
    """Return a shared session factory for Clarity Postgres."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def create_session() -> Session:
    """Create a new SQLAlchemy session for Clarity Postgres."""
    return get_session_factory()()


def get_clarity_pg_env_diagnostics() -> dict[str, object]:
    """Return safe startup diagnostics for required Clarity Postgres env vars."""
    raw_url = (os.getenv("CLARITY_PG_URL") or "").strip()
    raw_host = (os.getenv("CLARITY_PG_HOST") or "").strip()
    raw_db = (os.getenv("CLARITY_PG_DB") or "").strip()
    raw_user = (os.getenv("CLARITY_PG_USER") or "").strip()
    raw_password = (os.getenv("CLARITY_PG_PASSWORD") or "").strip()
    raw_port = (os.getenv("CLARITY_PG_PORT") or "").strip()
    raw_timeout = (os.getenv("CLARITY_PG_CONNECT_TIMEOUT_SECONDS") or "").strip()
    raw_seq_type_ids = (os.getenv("CLARITY_PG_SEQUENCING_TYPE_IDS") or "").strip()

    return {
        "using_url": bool(raw_url),
        "host_present": bool(raw_host),
        "db_present": bool(raw_db),
        "user_present": bool(raw_user),
        "password_present": bool(raw_password),
        "port_present": bool(raw_port),
        "connect_timeout_present": bool(raw_timeout),
        "sequencing_type_ids_present": bool(raw_seq_type_ids),
        "sequencing_type_ids_value": raw_seq_type_ids or "<missing>",
    }
