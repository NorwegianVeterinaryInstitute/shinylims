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

    @classmethod
    def from_env(cls) -> "ClarityPostgresConfig":
        return cls(
            database=os.getenv("CLARITY_PG_DB", ""),
            username=os.getenv("CLARITY_PG_USER", ""),
            password=os.getenv("CLARITY_PG_PASSWORD", ""),
            host=os.getenv("CLARITY_PG_HOST", "localhost"),
            port=int(os.getenv("CLARITY_PG_PORT", "5432")),
            url=os.getenv("CLARITY_PG_URL"),
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
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker:
    """Return a shared session factory for Clarity Postgres."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def create_session() -> Session:
    """Create a new SQLAlchemy session for Clarity Postgres."""
    return get_session_factory()()
