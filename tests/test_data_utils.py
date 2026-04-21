from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shinylims.integrations.data_utils import (
    _env_flag_is_true,
    _format_samples_dataframe,
    _format_sequencing_dataframe,
    _get_clarity_pg_sequencing_type_ids,
    sanitize_dataframe_strings,
    transform_comments_to_html,
    transform_to_html,
)


# ── transform_to_html ────────────────────────────────────────────────────────

def test_transform_to_html_na_passthrough():
    assert pd.isna(transform_to_html(float("nan")))


def test_transform_to_html_empty_string_passthrough():
    assert transform_to_html("") == ""


def test_transform_to_html_valid_id_produces_link():
    result = transform_to_html("PRO-123")
    assert 'href=' in result
    assert "123" in result
    assert "PRO-123" in result


def test_transform_to_html_multiple_ids():
    result = transform_to_html("PRO-1,PRO-2")
    assert result.count('href=') == 2


def test_transform_to_html_invalid_format_not_a_link():
    result = transform_to_html("NOTANID")
    assert 'href=' not in result
    assert result == "NOTANID"


def test_transform_to_html_escapes_xss_in_label():
    result = transform_to_html("<script>-123")
    assert "<script>" not in result


def test_transform_to_html_whitespace_around_id_trimmed():
    result = transform_to_html("  PRO-42  ")
    assert 'href=' in result


def test_transform_to_html_whitespace_around_comma_separated_ids():
    result = transform_to_html("PRO-1 , PRO-2")
    assert result.count('href=') == 2


# ── transform_comments_to_html ───────────────────────────────────────────────

def test_transform_comments_na_passthrough():
    assert pd.isna(transform_comments_to_html(float("nan")))


def test_transform_comments_empty_passthrough():
    assert transform_comments_to_html("") == ""


def test_transform_comments_newlines_become_br():
    assert transform_comments_to_html("line1\nline2") == "line1<br>line2"


def test_transform_comments_escapes_html():
    result = transform_comments_to_html("<b>bold</b>")
    assert "<b>" not in result
    assert "&lt;b&gt;" in result


def test_transform_comments_escapes_and_converts_newlines():
    result = transform_comments_to_html("<em>note</em>\nsecond line")
    assert "<em>" not in result
    assert "<br>" in result


# ── sanitize_dataframe_strings ───────────────────────────────────────────────

def test_sanitize_escapes_html_in_string_columns():
    df = pd.DataFrame({"name": ["<script>alert(1)</script>"]})
    result = sanitize_dataframe_strings(df)
    assert "<script>" not in result["name"][0]
    assert "&lt;script&gt;" in result["name"][0]


def test_sanitize_skips_listed_columns():
    df = pd.DataFrame({"trusted": ["<b>html</b>"], "text": ["<b>unsafe</b>"]})
    result = sanitize_dataframe_strings(df, skip_columns={"trusted"})
    assert result["trusted"][0] == "<b>html</b>"
    assert "<b>" not in result["text"][0]


def test_sanitize_leaves_empty_strings_unchanged():
    df = pd.DataFrame({"name": ["", "normal"]})
    result = sanitize_dataframe_strings(df)
    assert result["name"][0] == ""


def test_sanitize_ignores_non_string_columns():
    df = pd.DataFrame({"num": [1, 2], "flag": [True, False]})
    result = sanitize_dataframe_strings(df)
    assert list(result["num"]) == [1, 2]


def test_sanitize_no_skip_columns_defaults_to_empty_set():
    df = pd.DataFrame({"col": ["<x>"]})
    result = sanitize_dataframe_strings(df, skip_columns=None)
    assert "<x>" not in result["col"][0]


# ── _env_flag_is_true ────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", "YES", "ON"])
def test_env_flag_true_variants(value, monkeypatch):
    monkeypatch.setenv("TEST_FLAG", value)
    assert _env_flag_is_true("TEST_FLAG") is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_env_flag_false_variants(value, monkeypatch):
    monkeypatch.setenv("TEST_FLAG", value)
    assert _env_flag_is_true("TEST_FLAG") is False


def test_env_flag_unset_is_false(monkeypatch):
    monkeypatch.delenv("TEST_FLAG", raising=False)
    assert _env_flag_is_true("TEST_FLAG") is False


# ── _get_clarity_pg_sequencing_type_ids ─────────────────────────────────────

def test_sequencing_type_ids_empty_env_returns_empty_list(monkeypatch):
    monkeypatch.delenv("CLARITY_PG_SEQUENCING_TYPE_IDS", raising=False)
    assert _get_clarity_pg_sequencing_type_ids() == []


def test_sequencing_type_ids_single_value(monkeypatch):
    monkeypatch.setenv("CLARITY_PG_SEQUENCING_TYPE_IDS", "42")
    assert _get_clarity_pg_sequencing_type_ids() == [42]


def test_sequencing_type_ids_multiple_values_with_spaces(monkeypatch):
    monkeypatch.setenv("CLARITY_PG_SEQUENCING_TYPE_IDS", "42, 99, 7")
    assert _get_clarity_pg_sequencing_type_ids() == [42, 99, 7]


def test_sequencing_type_ids_trailing_comma_ignored(monkeypatch):
    monkeypatch.setenv("CLARITY_PG_SEQUENCING_TYPE_IDS", "42,")
    assert _get_clarity_pg_sequencing_type_ids() == [42]


# ── _format_sequencing_dataframe ─────────────────────────────────────────────

def test_format_sequencing_converts_seq_date_to_datetime():
    df = pd.DataFrame({"seq_limsid": ["PRO-1"], "Seq Date": ["2024-03-15"]})
    result = _format_sequencing_dataframe(df)
    assert pd.api.types.is_datetime64_any_dtype(result["Seq Date"])


def test_format_sequencing_limsid_becomes_html_link():
    df = pd.DataFrame({"seq_limsid": ["PRO-123"]})
    result = _format_sequencing_dataframe(df)
    assert 'href=' in result["seq_limsid"][0]


def test_format_sequencing_nan_replaced_with_empty_string():
    df = pd.DataFrame({"seq_limsid": [float("nan")], "Run ID": [float("nan")]})
    result = _format_sequencing_dataframe(df)
    assert result["Run ID"][0] == ""


def test_format_sequencing_text_columns_are_escaped():
    df = pd.DataFrame({"Instrument": ["<MiSeq>"], "seq_limsid": ["PRO-1"]})
    result = _format_sequencing_dataframe(df)
    assert "<MiSeq>" not in result["Instrument"][0]


# ── _format_samples_dataframe ────────────────────────────────────────────────

def test_format_samples_storage_box_placed_immediately_before_storage_well():
    df = pd.DataFrame({
        "Sample Name": ["S1"],
        "Storage Well": ["A1"],
        "Storage Box": ["Box1"],
    })
    result_df, _ = _format_samples_dataframe(df, meta_created="2024-01-01")
    cols = list(result_df.columns)
    assert cols.index("Storage Box") == cols.index("Storage Well") - 1


def test_format_samples_comment_newlines_converted_to_br():
    df = pd.DataFrame({"comment": ["line1\nline2"]})
    result_df, _ = _format_samples_dataframe(df, meta_created="2024-01-01")
    assert "<br>" in result_df["comment"][0]


def test_format_samples_returns_meta_created_unchanged():
    df = pd.DataFrame({"Sample Name": ["S1"]})
    _, meta = _format_samples_dataframe(df, meta_created="2024-01-01T12:00:00")
    assert meta == "2024-01-01T12:00:00"


def test_format_samples_nan_replaced_with_empty_string():
    df = pd.DataFrame({"Species": [float("nan")]})
    result_df, _ = _format_samples_dataframe(df, meta_created="2024-01-01")
    assert result_df["Species"][0] == ""
