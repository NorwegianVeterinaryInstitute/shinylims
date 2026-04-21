"""
Tests for the Clarity Postgres query layer.

Pure-function helpers are tested directly. Row-builder functions that require
a SQLAlchemy Session are tested with a lightweight fake session that returns
controlled row data without any real database connection.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from shinylims.integrations.queries._shared import (
    PROJECT_IDS_EXCLUDED_FROM_APP,
    _container_state_label,
    _display_name,
    _load_artifact_udfs,
    _load_operator_initials,
    _load_process_udfs,
)
from shinylims.integrations.queries.projects import (
    PROJECT_COMMENT_PLACEHOLDERS,
    build_project_rows,
)
from shinylims.integrations.queries.storage import build_storage_container_rows


# ── Fake session infrastructure ──────────────────────────────────────────────

class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def execute(self, stmt: Any) -> _FakeResult:
        return _FakeResult(self._rows)

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NeverCalledSession:
    """Sentinel session that fails if execute() is ever called."""

    def execute(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("session.execute should not be called with empty input")


# ── _display_name ────────────────────────────────────────────────────────────

def test_display_name_both_parts():
    assert _display_name("John", "Doe") == "John Doe"


def test_display_name_only_first():
    assert _display_name("John", None) == "John"


def test_display_name_only_last():
    assert _display_name(None, "Doe") == "Doe"


def test_display_name_both_none_returns_none():
    assert _display_name(None, None) is None


def test_display_name_strips_whitespace():
    assert _display_name("  John  ", "  Doe  ") == "John Doe"


def test_display_name_empty_strings_returns_none():
    assert _display_name("", "") is None


# ── _container_state_label ───────────────────────────────────────────────────

def test_container_state_label_active():
    assert _container_state_label(2) == "Active"


def test_container_state_label_discarded():
    assert _container_state_label(4) == "Discarded"


def test_container_state_label_unknown_state_returns_none():
    assert _container_state_label(99) is None


def test_container_state_label_none_returns_none():
    assert _container_state_label(None) is None


# ── Empty-input short-circuits ───────────────────────────────────────────────

def test_load_process_udfs_empty_ids_returns_empty_dict():
    assert _load_process_udfs(_NeverCalledSession(), [], {"udf"}) == {}


def test_load_process_udfs_empty_udf_names_returns_empty_dict():
    assert _load_process_udfs(_NeverCalledSession(), [1], set()) == {}


def test_load_artifact_udfs_empty_ids_returns_empty_dict():
    assert _load_artifact_udfs(_NeverCalledSession(), [], {"udf"}) == {}


def test_load_artifact_udfs_empty_udf_names_returns_empty_dict():
    assert _load_artifact_udfs(_NeverCalledSession(), [1], set()) == {}


def test_load_operator_initials_empty_ids_returns_empty_dict():
    assert _load_operator_initials(_NeverCalledSession(), []) == {}


# ── build_project_rows helpers ───────────────────────────────────────────────

def _project_row(**overrides: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = dict(
        projectid=1,
        luid="LEI001",
        opendate=datetime(2024, 1, 1),
        closedate=None,
        project_name="Test Project",
        firstname="John",
        lastname="Doe",
        lab_name="Test Lab",
        sample_processid=101,
        species="E. coli",
        comment=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── build_project_rows ───────────────────────────────────────────────────────

def test_build_project_rows_open_project():
    rows = build_project_rows(_FakeSession([_project_row()]))
    assert len(rows) == 1
    assert rows[0]["Status"] == "OPEN"


def test_build_project_rows_closed_project():
    rows = build_project_rows(
        _FakeSession([_project_row(closedate=datetime(2024, 6, 1))])
    )
    assert rows[0]["Status"] == "CLOSED"


def test_build_project_rows_pending_project():
    rows = build_project_rows(
        _FakeSession([_project_row(opendate=None, closedate=None)])
    )
    assert rows[0]["Status"] == "PENDING"


def test_build_project_rows_counts_unique_samples():
    data = [
        _project_row(sample_processid=101),
        _project_row(sample_processid=101),  # duplicate – counted once
        _project_row(sample_processid=102),
    ]
    rows = build_project_rows(_FakeSession(data))
    assert rows[0]["Samples"] == 2


def test_build_project_rows_no_samples_when_processid_is_none():
    rows = build_project_rows(_FakeSession([_project_row(sample_processid=None)]))
    assert rows[0]["Samples"] == 0


def test_build_project_rows_aggregates_species_deduped():
    data = [
        _project_row(species="E. coli"),
        _project_row(species="S. aureus"),
        _project_row(species="E. coli"),  # duplicate
    ]
    rows = build_project_rows(_FakeSession(data))
    assert rows[0]["Species"] == "E. coli, S. aureus"


def test_build_project_rows_no_species_is_empty_string():
    rows = build_project_rows(_FakeSession([_project_row(species=None)]))
    assert rows[0]["Species"] == ""


def test_build_project_rows_filters_placeholder_comments():
    for placeholder in PROJECT_COMMENT_PLACEHOLDERS:
        rows = build_project_rows(_FakeSession([_project_row(comment=placeholder)]))
        assert rows[0]["Comment"] == ""


def test_build_project_rows_preserves_real_comment():
    rows = build_project_rows(_FakeSession([_project_row(comment="Rush order")]))
    assert rows[0]["Comment"] == "Rush order"


def test_build_project_rows_excludes_blocked_project_ids():
    blocked = next(iter(PROJECT_IDS_EXCLUDED_FROM_APP))
    rows = build_project_rows(_FakeSession([_project_row(luid=blocked)]))
    assert rows == []


def test_build_project_rows_includes_non_blocked_project():
    rows = build_project_rows(_FakeSession([_project_row(luid="LEI999")]))
    assert len(rows) == 1


def test_build_project_rows_empty_db_returns_empty_list():
    assert build_project_rows(_FakeSession([])) == []


def test_build_project_rows_submitter_display_name():
    rows = build_project_rows(_FakeSession([_project_row(firstname="Ada", lastname="Lovelace")]))
    assert rows[0]["Submitter"] == "Ada Lovelace"


# ── build_storage_container_rows ─────────────────────────────────────────────

def _storage_row(
    name: str = "Box-001",
    stateid: int = 2,
    createddate: datetime = datetime(2024, 1, 1),
    lastmodifieddate: datetime = datetime(2024, 6, 1),
) -> tuple:
    return (name, stateid, createddate, lastmodifieddate)


def test_build_storage_rows_active_state_label():
    rows = build_storage_container_rows(_FakeSession([_storage_row(stateid=2)]))
    assert rows[0]["Status"] == "Active"


def test_build_storage_rows_discarded_state_label():
    rows = build_storage_container_rows(_FakeSession([_storage_row(stateid=4)]))
    assert rows[0]["Status"] == "Discarded"


def test_build_storage_rows_unknown_state_uses_numeric_fallback():
    rows = build_storage_container_rows(_FakeSession([_storage_row(stateid=99)]))
    assert rows[0]["Status"] == "State 99"


def test_build_storage_rows_empty_db_returns_empty_list():
    assert build_storage_container_rows(_FakeSession([])) == []


def test_build_storage_rows_maps_column_names():
    rows = build_storage_container_rows(_FakeSession([_storage_row(name="MyBox")]))
    assert rows[0]["Box Name"] == "MyBox"
    assert "Created Date" in rows[0]
    assert "Last Modified" in rows[0]


def test_build_storage_rows_preserves_dates():
    created = datetime(2023, 3, 15)
    modified = datetime(2024, 7, 4)
    rows = build_storage_container_rows(
        _FakeSession([_storage_row(createddate=created, lastmodifieddate=modified)])
    )
    assert rows[0]["Created Date"] == created
    assert rows[0]["Last Modified"] == modified
