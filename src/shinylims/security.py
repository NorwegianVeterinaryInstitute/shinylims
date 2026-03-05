"""
security.py - Runtime user and authorization helpers for Connect/local execution.
"""

from __future__ import annotations

import os
from typing import Any
import unicodedata
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

CONNECT_ALLOWED_GROUP = "116-Molekylærbiologi"
CONNECT_ALLOWED_GROUPS_ENV = "CONNECT_ALLOWED_GROUPS"
REAGENTS_ALLOWED_USERS_ENV = "REAGENTS_ALLOWED_USERS"
REAGENTS_AUTH_DEBUG_ENV = "REAGENTS_AUTH_DEBUG"


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


def _auth_debug_enabled() -> bool:
    return (os.getenv(REAGENTS_AUTH_DEBUG_ENV) or "").strip() == "1"


def _auth_log(event: str, **fields: Any) -> None:
    """Emit compact auth debug lines to stdout (visible in Connect logs)."""
    if not _auth_debug_enabled():
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [f"{k}={v}" for k, v in fields.items()]
    print(f"[reagents-auth] ts={ts} event={event} " + " ".join(parts), flush=True)


def _normalize_identity(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _get_allowed_connect_groups() -> set[str]:
    configured = _as_string_list(os.getenv(CONNECT_ALLOWED_GROUPS_ENV, ""))
    if not configured:
        configured = [CONNECT_ALLOWED_GROUP]
    return {_normalize_identity(group) for group in configured if _normalize_identity(group)}


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

    _auth_log(
        "runtime_user_resolved",
        username=username or "-",
        groups="|".join(groups) if groups else "-",
    )
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
        matched_group = False
        if groups:
            normalized_groups = {_normalize_identity(g) for g in groups if g}
            matched_group = bool(normalized_groups.intersection(_get_allowed_connect_groups()))
            if matched_group:
                _auth_log(
                    "connect_auth_decision",
                    decision="allow",
                    reason="group_match",
                    username=username or "-",
                    groups="|".join(groups),
                )
                return True

        user_allowed = bool(username and username in allowed_users)
        _auth_log(
            "connect_auth_decision",
            decision="allow" if user_allowed else "deny",
            reason="user_fallback" if user_allowed else "no_group_or_user_match",
            username=username or "-",
            groups="|".join(groups) if groups else "-",
            allowed_groups="|".join(sorted(_get_allowed_connect_groups())),
            user_in_allowlist=user_allowed,
            matched_group=matched_group,
        )
        return user_allowed

    local_allowed = os.getenv("DEV_BYPASS_SECURITY", "").strip() == "1"
    _auth_log(
        "local_auth_decision",
        decision="allow" if local_allowed else "deny",
        reason="dev_bypass_security",
        dev_bypass=os.getenv("DEV_BYPASS_SECURITY", ""),
    )
    return local_allowed
