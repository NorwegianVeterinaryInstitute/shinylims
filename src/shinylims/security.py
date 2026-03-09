"""
security.py - Runtime user and authorization helpers for Connect/local execution.
"""

from __future__ import annotations

import os
from typing import Any
import unicodedata

# Connect authorization config (code-defined)
CONNECT_ALLOWED_GROUP = "116-Molekylærbiologi"
CONNECT_ALLOWED_USERS: set[str] = set() #example {"vi2172", "other_user_id"}

# Local authorization config (code-defined)
LOCAL_DEV_ALLOW_ALL = False

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
        tokens = [token.strip() for token in raw.split(",")]
        return [token for token in tokens if token]
    return [str(value).strip()] if str(value).strip() else []


def _normalize_identity(value: str) -> str:
    raw = str(value or "").strip()
    # Connect/headers can occasionally surface UTF-8 bytes decoded as latin-1
    # (e.g. "MolekylÃ¦rbiologi"). Try to repair before matching.
    try:
        repaired = raw.encode("latin-1").decode("utf-8")
        if repaired:
            raw = repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return unicodedata.normalize("NFKC", raw).strip().casefold()


def _normalized_allowed_users(users: set[str]) -> set[str]:
    return {_normalize_identity(user) for user in users if _normalize_identity(user)}


def reagents_access_policy_summary() -> str:
    """Short human-readable summary of who may access Reagents."""
    if CONNECT_ALLOWED_USERS:
        sorted_users = ", ".join(sorted(CONNECT_ALLOWED_USERS))
        return f"group '{CONNECT_ALLOWED_GROUP}' or individual user(s): {sorted_users}"
    return f"group '{CONNECT_ALLOWED_GROUP}'"


def reagents_access_denied_message() -> str:
    """User-facing access denied message for Reagents actions/UI."""
    return (
        f"Access denied. Allowed access is {reagents_access_policy_summary()}. "
        "Contact admin to be added as an individual user if needed."
    )


def get_runtime_user(session) -> tuple[str | None, list[str]]:
    """
    Resolve runtime user and groups from the Shiny session.
    """
    username = None
    groups: list[str] = []

    if session is not None:
        username = getattr(session, "user", None) or getattr(session, "username", None)
        groups = _as_string_list(getattr(session, "groups", None))

    if username is not None:
        username = str(username).strip() or None

    return username, groups


def is_allowed_reagents_user(session) -> bool:
    """
    Authorization for Reagents functionality.

    On Connect:
    - Allow if user is in CONNECT_ALLOWED_GROUP.
    - Allow if username is in CONNECT_ALLOWED_USERS.

    Local dev:
    - Allow all when LOCAL_DEV_ALLOW_ALL is True.
    - Deny when LOCAL_DEV_ALLOW_ALL is False.
    """
    username, groups = get_runtime_user(session)

    if is_running_on_connect():
        if groups:
            normalized_groups = {_normalize_identity(g) for g in groups if g}
            if _normalize_identity(CONNECT_ALLOWED_GROUP) in normalized_groups:
                return True

        return bool(username and _normalize_identity(username) in _normalized_allowed_users(CONNECT_ALLOWED_USERS))

    if LOCAL_DEV_ALLOW_ALL:
        return True

    return False
