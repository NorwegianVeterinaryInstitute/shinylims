"""
Lightweight SQLAlchemy connection helpers for the Clarity Postgres prototype.
"""

from __future__ import annotations

import os
import socket
import time
from urllib import request
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
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
    sslmode: str | None = None
    sslrootcert: str | None = None
    sslcert: str | None = None
    sslkey: str | None = None

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
            sslmode=(os.getenv("CLARITY_PG_SSLMODE") or "").strip() or None,
            sslrootcert=(os.getenv("CLARITY_PG_SSLROOTCERT") or "").strip() or None,
            sslcert=(os.getenv("CLARITY_PG_SSLCERT") or "").strip() or None,
            sslkey=(os.getenv("CLARITY_PG_SSLKEY") or "").strip() or None,
        )

    def sqlalchemy_url(self) -> str | URL:
        ssl_query = {
            key: value
            for key, value in {
                "sslmode": self.sslmode,
                "sslrootcert": self.sslrootcert,
                "sslcert": self.sslcert,
                "sslkey": self.sslkey,
            }.items()
            if value
        }
        if self.url:
            parsed_url = make_url(self.url)
            url_ssl_query = {key: value for key, value in parsed_url.query.items() if key in ssl_query}
            ssl_query = {key: value for key, value in ssl_query.items() if key not in url_ssl_query}
            if ssl_query:
                return parsed_url.update_query_dict(ssl_query)
            return parsed_url
        return URL.create(
            "postgresql+psycopg",
            username=self.username or None,
            password=self.password or None,
            host=self.host,
            port=self.port,
            database=self.database or None,
            query=ssl_query or None,
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
    raw_sslmode = (os.getenv("CLARITY_PG_SSLMODE") or "").strip()
    raw_sslrootcert = (os.getenv("CLARITY_PG_SSLROOTCERT") or "").strip()
    raw_sslcert = (os.getenv("CLARITY_PG_SSLCERT") or "").strip()
    raw_sslkey = (os.getenv("CLARITY_PG_SSLKEY") or "").strip()
    raw_seq_type_ids = (os.getenv("CLARITY_PG_SEQUENCING_TYPE_IDS") or "").strip()

    return {
        "using_url": bool(raw_url),
        "host_present": bool(raw_host),
        "db_present": bool(raw_db),
        "user_present": bool(raw_user),
        "password_present": bool(raw_password),
        "port_present": bool(raw_port),
        "connect_timeout_present": bool(raw_timeout),
        "sslmode_present": bool(raw_sslmode),
        "sslmode_value": raw_sslmode or "<missing>",
        "sslrootcert_present": bool(raw_sslrootcert),
        "sslcert_present": bool(raw_sslcert),
        "sslkey_present": bool(raw_sslkey),
        "sequencing_type_ids_present": bool(raw_seq_type_ids),
        "sequencing_type_ids_value": raw_seq_type_ids or "<missing>",
    }


def get_clarity_pg_ssl_diagnostics() -> dict[str, object]:
    """Return configured and live SSL details for the current Postgres session."""
    config = ClarityPostgresConfig.from_env()
    result: dict[str, object] = {
        "configured_sslmode": config.sslmode or "<driver-default>",
        "sslrootcert_present": bool(config.sslrootcert),
        "sslcert_present": bool(config.sslcert),
        "sslkey_present": bool(config.sslkey),
        "connection_ok": False,
        "ssl_status_available": False,
    }

    try:
        with create_session() as session:
            row = (
                session.execute(
                    text(
                        """
                        select ssl, version, cipher, bits, client_dn
                        from pg_stat_ssl
                        where pid = pg_backend_pid()
                        """
                    )
                )
                .mappings()
                .first()
            )
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        return result

    result["connection_ok"] = True
    if row is None:
        result["error"] = "pg_stat_ssl returned no row for the current backend session"
        return result

    ssl_details = dict(row)
    result["ssl_status_available"] = True
    result["ssl_in_use"] = bool(ssl_details.get("ssl"))
    result["ssl_version"] = ssl_details.get("version")
    result["ssl_cipher"] = ssl_details.get("cipher")
    result["ssl_bits"] = ssl_details.get("bits")
    result["ssl_client_dn"] = ssl_details.get("client_dn")
    return result


def _detect_public_egress_ip(timeout_seconds: float = 3.0) -> tuple[str | None, str | None, str | None]:
    """Return (ip, source, error) for the current public egress IP."""
    services = (
        ("https://api.ipify.org", "api.ipify.org"),
        ("https://ifconfig.me/ip", "ifconfig.me"),
    )
    last_error = "No response from public IP lookup services"

    for url, source in services:
        try:
            with request.urlopen(url, timeout=timeout_seconds) as response:
                ip = response.read().decode("utf-8").strip()
            if ip:
                return ip, source, None
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue

    return None, None, last_error


def get_clarity_pg_network_diagnostics() -> dict[str, object]:
    """Return DNS and TCP connectivity diagnostics for the configured Postgres host."""
    config = ClarityPostgresConfig.from_env()
    host = config.host
    port = config.port
    public_ip, public_ip_source, public_ip_error = _detect_public_egress_ip()

    if config.url:
        try:
            parsed_url = make_url(config.url)
            host = parsed_url.host or host
            port = parsed_url.port or port
        except Exception as exc:
            return {
                "host": host,
                "port": port,
                "dns_ok": False,
                "tcp_connect_ok": False,
                "error_type": type(exc).__name__,
                "error": f"Could not parse CLARITY_PG_URL: {exc}",
            }

    result: dict[str, object] = {
        "host": host,
        "port": port,
        "dns_ok": False,
        "tcp_connect_ok": False,
        "resolved_addresses": [],
        "public_egress_ip": public_ip or "<unavailable>",
        "public_ip_source": public_ip_source or "<unavailable>",
    }
    if public_ip_error:
        result["public_ip_error"] = public_ip_error

    try:
        addrinfo = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = []
        for family, _, _, _, sockaddr in addrinfo:
            family_name = "AF_INET6" if family == socket.AF_INET6 else "AF_INET"
            address = sockaddr[0]
            entry = f"{family_name}:{address}"
            if entry not in addresses:
                addresses.append(entry)
        result["dns_ok"] = True
        result["resolved_addresses"] = addresses
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        return result

    started_at = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=config.connect_timeout_seconds):
            pass
        result["tcp_connect_ok"] = True
        result["tcp_elapsed_s"] = round(time.perf_counter() - started_at, 3)
        return result
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        result["tcp_elapsed_s"] = round(time.perf_counter() - started_at, 3)
        return result
