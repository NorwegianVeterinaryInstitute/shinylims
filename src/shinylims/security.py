"""
security.py - Runtime user and authorization helpers for Connect/local execution.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

CONNECT_ALLOWED_GROUP = "116-Molekylærbiologi"
REAGENTS_ALLOWED_USERS_ENV = "REAGENTS_ALLOWED_USERS"


def is_running_on_connect() -> bool:
    """Return True when running on Posit Connect."""
    return (os.getenv("POSIT_PRODUCT") or "").strip().upper() == "CONNECT"


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        # Handle both comma-separated env style and JSON-ish list strings.
        tokens = [token.strip().strip("\"'") for token in raw.strip("[]").split(",")]
        return [token for token in tokens if token]
    return [str(value).strip()] if str(value).strip() else []


def _get_allowed_usernames() -> set[str]:
    raw = os.getenv(REAGENTS_ALLOWED_USERS_ENV, "")
    return {user for user in _as_string_list(raw)}


def get_runtime_user(session) -> tuple[str | None, list[str]]:
    """
    Resolve runtime user and groups from the Shiny session, with safe fallbacks.
    """
    username = None
    groups: list[str] = []

    if session is not None:
        username = getattr(session, "user", None) or getattr(session, "username", None)
        groups = _as_string_list(getattr(session, "groups", None))

        # Fallback to Connect-provided request headers when direct session attrs are missing.
        if (not username or not groups) and hasattr(session, "http_conn"):
            http_conn = getattr(session, "http_conn", None)
            headers = getattr(http_conn, "headers", {}) if http_conn is not None else {}
            if not username:
                username = (
                    headers.get("X-RSC-Username")
                    or headers.get("X-Connect-Username")
                    or headers.get("X-Auth-Request-User")
                )
            if not groups:
                groups_header = (
                    headers.get("X-RSC-Groups")
                    or headers.get("X-Connect-Groups")
                    or headers.get("X-Auth-Request-Groups")
                )
                groups = _as_string_list(groups_header)

    if username is not None:
        username = str(username).strip() or None

    return username, groups


def is_allowed_reagents_user(session) -> bool:
    """
    Authorization for Reagents functionality.

    On Connect:
    - Prefer group-based allow when groups are present.
    - Fallback to explicit user allow-list if groups are unavailable.

    Local dev:
    - Allow only when DEV_BYPASS_SECURITY=1.
    """
    if is_running_on_connect():
        allowed_users = _get_allowed_usernames()
        username, groups = get_runtime_user(session)
        if groups:
            return CONNECT_ALLOWED_GROUP in groups
        return bool(username and username in allowed_users)

    return os.getenv("DEV_BYPASS_SECURITY", "").strip() == "1"
