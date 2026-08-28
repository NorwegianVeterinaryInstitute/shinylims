from __future__ import annotations

import pandas as pd

from shinylims.features.storage import (
    build_storage_status_ui,
    drop_test_boxes,
    filter_by_status,
)


def _boxes(names: list) -> pd.DataFrame:
    return pd.DataFrame({"Box Name": names, "Status": ["Active"] * len(names)})


def _statuses(statuses: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"Box Name": [f"Box {i}" for i in range(len(statuses))], "Status": statuses}
    )


# ── drop_test_boxes ──────────────────────────────────────────────────────────

def test_drop_test_boxes_removes_test_prefixed_names():
    df = drop_test_boxes(_boxes(["Box 1", "TEST-3", "Box 2"]))
    assert list(df["Box Name"]) == ["Box 1", "Box 2"]


def test_drop_test_boxes_is_case_insensitive():
    df = drop_test_boxes(_boxes(["test box", "Testing 1", "Box 9"]))
    assert list(df["Box Name"]) == ["Box 9"]


def test_drop_test_boxes_ignores_leading_whitespace():
    df = drop_test_boxes(_boxes(["  TESTBOX", "Box 9"]))
    assert list(df["Box Name"]) == ["Box 9"]


def test_drop_test_boxes_keeps_names_with_test_elsewhere():
    df = drop_test_boxes(_boxes(["Box TEST 4", "Latest box"]))
    assert list(df["Box Name"]) == ["Box TEST 4", "Latest box"]


def test_drop_test_boxes_keeps_missing_names():
    df = drop_test_boxes(_boxes([None, "Box 1"]))
    assert len(df) == 2


def test_drop_test_boxes_handles_empty_frame():
    assert drop_test_boxes(pd.DataFrame()).empty


# ── filter_by_status ─────────────────────────────────────────────────────────

def test_filter_by_status_both_selected_keeps_everything():
    df = _statuses(["✅ Active", "🗑️ Discarded"])
    assert len(filter_by_status(df, True, True)) == 2


def test_filter_by_status_hides_discarded_when_deselected():
    df = _statuses(["✅ Active", "🗑️ Discarded"])
    assert list(filter_by_status(df, True, False)["Status"]) == ["✅ Active"]


def test_filter_by_status_hides_active_when_deselected():
    df = _statuses(["✅ Active", "🗑️ Discarded"])
    assert list(filter_by_status(df, False, True)["Status"]) == ["🗑️ Discarded"]


def test_filter_by_status_treats_populated_as_active():
    df = _statuses(["✅ Populated", "🗑️ Discarded"])
    assert filter_by_status(df, False, True)["Status"].tolist() == ["🗑️ Discarded"]


def test_filter_by_status_keeps_unknown_status_visible():
    df = _statuses(["✅ Active", "State 7"])
    assert list(filter_by_status(df, False, True)["Status"]) == ["State 7"]


def test_filter_by_status_nothing_selected_drops_known_statuses():
    df = _statuses(["✅ Active", "🗑️ Discarded"])
    assert filter_by_status(df, False, False).empty


def test_filter_by_status_handles_empty_frame():
    assert filter_by_status(pd.DataFrame(), True, False).empty


# ── build_storage_status_ui ──────────────────────────────────────────────────

def _containers() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Box Name": ["Box 1", "Box 2", "TEST Box 3", "Box 4"],
            "Status": ["Active", "Discarded", "Active", "Discarded"],
            "Created Date": pd.to_datetime(["2026-01-01"] * 4),
            "Last Modified": pd.to_datetime(["2026-02-02"] * 4),
        }
    )


def _rendered(show_active: bool = True, show_discarded: bool = True) -> str:
    return str(build_storage_status_ui(_containers(), show_active, show_discarded))


def test_build_ui_hides_test_boxes():
    assert "TEST Box 3" not in _rendered()


def test_build_ui_shows_both_statuses_by_default():
    html = _rendered()
    assert "Box 1" in html and "Box 2" in html


def test_build_ui_summary_counts_all_shown_boxes():
    assert "Total: 3 | ✅ Active: 1 | 🗑️ Discarded: 2" in _rendered()


def test_build_ui_active_only_hides_discarded_rows():
    html = _rendered(show_active=True, show_discarded=False)
    assert "Box 1" in html
    assert "Box 2" not in html
    assert "Total: 1 | ✅ Active: 1 | 🗑️ Discarded: 0" in html


def test_build_ui_discarded_only_hides_active_rows():
    html = _rendered(show_active=False, show_discarded=True)
    assert "Box 1" not in html
    assert "Box 2" in html
    assert "Total: 2 | ✅ Active: 0 | 🗑️ Discarded: 2" in html


def test_build_ui_neither_status_selected_reports_no_match():
    assert "No storage boxes match" in _rendered(False, False)


def test_build_ui_empty_frame_reports_no_data():
    assert "No storage container data available." in str(
        build_storage_status_ui(pd.DataFrame())
    )


def test_build_ui_formats_dates_as_iso_days():
    html = _rendered()
    assert "2026-01-01" in html
    assert "00:00:00" not in html


def test_build_ui_sorts_boxes_by_trailing_number_descending():
    html = _rendered()
    assert html.index("Box 4") < html.index("Box 2") < html.index("Box 1")


def test_build_ui_does_not_mutate_the_input_frame():
    df = _containers()
    build_storage_status_ui(df, True, False)
    assert "sort_num" not in df.columns
    assert list(df["Status"]) == ["Active", "Discarded", "Active", "Discarded"]
