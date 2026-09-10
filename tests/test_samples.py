from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd

from shinylims.features.samples import (
    COLUMN_PRESETS,
    SAMPLES_TABLE_STATE_KEY,
    DEFAULT_COLUMN_PRESET,
    DEFAULT_PRESET_COLUMNS,
    _batch_filter_non_matches_csv,
    _find_batch_filter_matches,
    _split_seq_limsids,
    project_limsids_for_seq_limsids,
    seq_limsids_for_project_limsids,
)


def test_find_batch_filter_matches_returns_sorted_non_matches():
    df = pd.DataFrame(
        {
            "Sample Name": ["alpha", "beta", "gamma"],
            "LIMS ID": ["L1", "L2", "L3"],
        }
    )

    found, not_found = _find_batch_filter_matches(
        df, "Sample Name", {"gamma", "missing-b", "alpha", "missing-a"}
    )

    assert found == {"alpha", "gamma"}
    assert not_found == ["missing-a", "missing-b"]


def test_batch_filter_non_matches_csv_uses_selected_column_header():
    csv_text = _batch_filter_non_matches_csv(["L9", "L10"], "LIMS ID")

    assert csv_text == "LIMS ID\nL9\nL10\n"



def test_split_seq_limsids_extracts_ids_from_linked_values():
    html_links = (
        '<a href="https://nvi-prod.claritylims.com/clarity/work-complete/29302" '
        'target="_blank">24-29302</a>, '
        '<a href="https://nvi-prod.claritylims.com/clarity/work-complete/29316" '
        'target="_blank">24-29316</a>'
    )
    markdown_links = (
        "[24-29302](https://nvi-prod.claritylims.com/clarity/work-complete/29302), "
        "[24-29316](https://nvi-prod.claritylims.com/clarity/work-complete/29316)"
    )

    assert _split_seq_limsids(html_links) == {"24-29302", "24-29316"}
    assert _split_seq_limsids(markdown_links) == {"24-29302", "24-29316"}

def test_project_limsids_for_seq_limsids_matches_comma_separated_run_ids():
    df = pd.DataFrame(
        {
            "Project LIMS ID": ["LEI001", "LEI002", "LEI001", "LEI003"],
            "seq_limsid": ["SEQ1", "SEQ2, SEQ3", "SEQ3", "SEQ4"],
        }
    )

    project_ids = project_limsids_for_seq_limsids(df, {"SEQ3"})

    assert project_ids == ["LEI002", "LEI001"]


def test_project_limsids_for_seq_limsids_returns_empty_when_columns_missing():
    df = pd.DataFrame({"Project LIMS ID": ["LEI001"]})

    assert project_limsids_for_seq_limsids(df, {"SEQ1"}) == []


def test_seq_limsids_for_project_limsids_uses_samples_as_bridge():
    df = pd.DataFrame(
        {
            "Project LIMS ID": ["LEI001", "LEI002", "LEI001", "LEI003"],
            "seq_limsid": [
                '<a href="/work-complete/29302">24-29302</a>, '
                '<a href="/work-complete/29316">24-29316</a>',
                '<a href="/work-complete/29999">24-29999</a>',
                '<a href="/work-complete/29302">24-29302</a>',
                None,
            ],
        }
    )

    seq_ids = seq_limsids_for_project_limsids(df, {"LEI001"})

    assert seq_ids == ["24-29302", "24-29316"]


def test_seq_limsids_for_project_limsids_returns_empty_when_columns_missing():
    df = pd.DataFrame({"Project LIMS ID": ["LEI001"]})

    assert seq_limsids_for_project_limsids(df, {"LEI001"}) == []


def _sample_row_keys() -> list[str]:
    """The column names build_sample_rows emits, read from its source.

    Calling it needs a live Clarity session, so the row dict it appends is
    located in the AST instead -- enough to catch a rename drifting away from
    the presets.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "src" / "shinylims" / "integrations" / "queries" / "samples.py"
    ).read_text()

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
        if "LIMS ID" in keys and "Received Date" in keys:
            return keys
    raise AssertionError("could not find the sample row dict")


def test_column_presets_only_name_columns_the_sample_query_produces():
    """The presets are resolved by name at render time, so a column renamed in
    the query would silently drop out of every preset that lists it rather than
    failing anywhere visible."""
    available = set(_sample_row_keys())

    for label, columns in COLUMN_PRESETS:
        unknown = [column for column in columns if column not in available]
        assert not unknown, f"{label} names columns the query does not build: {unknown}"


def test_every_column_preset_shows_the_sample_identifier():
    """A preset that hides LIMS ID leaves rows the user cannot tell apart."""
    for label, columns in COLUMN_PRESETS:
        assert "LIMS ID" in columns, f"{label} has no sample identifier"


def test_default_preset_is_one_of_the_presets_on_the_menu():
    """The toolbar labels the default by name, so a default that no button can
    re-apply would leave the visitor unable to get back to it."""
    assert DEFAULT_COLUMN_PRESET in dict(COLUMN_PRESETS)
    assert DEFAULT_PRESET_COLUMNS == dict(COLUMN_PRESETS)[DEFAULT_COLUMN_PRESET]


def test_table_state_key_is_not_shared_with_the_sequencing_table():
    """Both tables key their saved state off a fixed string rather than the
    widget's regenerated id; the same string would have them overwrite each
    other's columns and filters on every view switch."""
    from shinylims.features.sequencing import SEQ_TABLE_STATE_KEY

    assert SAMPLES_TABLE_STATE_KEY != SEQ_TABLE_STATE_KEY
