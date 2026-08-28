from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

from shinylims.features.sequencing import (
    COLUMN_PRESETS,
    DEFAULT_COLUMN_PRESET,
    DEFAULT_PRESET_COLUMNS,
    PLOT_HEIGHT_DEFAULT,
    PLOT_HEIGHT_MAX,
    PLOT_HEIGHT_MIN,
    clamp_plot_height,
    empty_plot_figure,
    seq_ui,
    PLOT_COLOR_CHOICES,
    PLOT_METRICS,
    PHIX_CONTROL_APPLICATION,
    _numeric_avg_fragment_size,
    _plot_axis_series,
    _plot_color_series,
    apply_reported_rows,
    exclude_phix_control_runs,
    linear_trendline,
    supports_trendline,
    trendline_equation_text,
)


def test_numeric_avg_fragment_size_parses_single_value():
    assert _numeric_avg_fragment_size("506") == 506.0


def test_numeric_avg_fragment_size_averages_plus_joined_values():
    assert _numeric_avg_fragment_size("500 + 512") == 506.0


def test_numeric_avg_fragment_size_ignores_unparsable_parts():
    assert _numeric_avg_fragment_size("500 + garbage") == 500.0


def test_numeric_avg_fragment_size_returns_none_for_empty_or_garbage():
    assert _numeric_avg_fragment_size(None) is None
    assert _numeric_avg_fragment_size("") is None
    assert _numeric_avg_fragment_size("not a number") is None
    assert _numeric_avg_fragment_size(float("nan")) is None


def test_plot_axis_series_coerces_avg_fragment_size_column():
    dat = pd.DataFrame({"Avg Fragment Size": ["500 + 512", None, "480"]})
    series = _plot_axis_series(dat, "Avg Fragment Size")
    assert series.iloc[0] == 506.0
    assert pd.isna(series.iloc[1])
    assert series.iloc[2] == 480.0


def test_plot_axis_series_parses_date_column():
    dat = pd.DataFrame({"Seq Date": ["2026-08-01", "not-a-date", None]})
    series = _plot_axis_series(dat, "Seq Date")
    assert series.iloc[0] == "2026-08-01"
    assert pd.isna(series.iloc[1])
    assert pd.isna(series.iloc[2])


def test_plot_axis_series_coerces_plain_numeric_column():
    dat = pd.DataFrame({"Cluster Density": [100.5, None, "not-a-number"]})
    series = _plot_axis_series(dat, "Cluster Density")
    assert series.iloc[0] == 100.5
    assert pd.isna(series.iloc[1])
    assert pd.isna(series.iloc[2])


def test_plot_metrics_registry_covers_expected_labels():
    assert "Seq Date" in PLOT_METRICS
    assert "Cluster Density" in PLOT_METRICS
    assert PLOT_METRICS["Seq Date"]["kind"] == "date"
    assert PLOT_METRICS["Cluster Density"]["kind"] == "numeric"


def test_plot_metrics_registry_includes_categorical_run_metadata():
    assert PLOT_METRICS["Application"]["kind"] == "categorical"
    assert PLOT_METRICS["Instrument"]["kind"] == "categorical"
    assert PLOT_METRICS["Operator"]["kind"] == "categorical"


def test_plot_color_choices_offer_none_plus_every_metric():
    assert PLOT_COLOR_CHOICES[""] == "None"
    for label in PLOT_METRICS:
        assert PLOT_COLOR_CHOICES[label] == label


def test_exclude_phix_control_runs_removes_only_exact_control_application():
    dat = pd.DataFrame({
        "Application": [PHIX_CONTROL_APPLICATION, "WGS (MiSeq v3)", "Unknown"],
        "Run ID": ["control", "wgs", "older"],
    })

    result = exclude_phix_control_runs(dat)

    assert result["Run ID"].tolist() == ["wgs", "older"]


def test_exclude_phix_control_runs_leaves_frames_without_application_unchanged():
    dat = pd.DataFrame({"Run ID": ["run-1"]})
    assert exclude_phix_control_runs(dat).equals(dat)


def test_plot_axis_series_labels_blank_categoricals_as_unknown():
    dat = pd.DataFrame({"Operator": ["ML", "  ", None, "WG"]})
    series = _plot_axis_series(dat, "Operator")
    assert series.tolist() == ["ML", "Unknown", "Unknown", "WG"]


def test_plot_color_series_passes_categoricals_through_for_a_discrete_legend():
    dat = pd.DataFrame({"Instrument": ["M09180", "M06578"]})
    values, overrides = _plot_color_series(dat, "Instrument")
    # Trailing NBSPs pad the legend's clip box (see comment at the call site) - strip
    # them for the comparison since the visible content is what matters here.
    assert [v.strip() for v in values.tolist()] == ["M09180", "M06578"]
    assert all(v.endswith("\xa0\xa0") for v in values.tolist())
    assert overrides is None


def test_plot_color_series_passes_numerics_through_for_a_continuous_colorbar():
    dat = pd.DataFrame({"Cluster Density": [1000.0, 1200.0]})
    values, overrides = _plot_color_series(dat, "Cluster Density")
    assert values.tolist() == [1000.0, 1200.0]
    assert overrides is None


def test_plot_color_series_converts_dates_to_ordinals_with_date_ticks():
    dat = pd.DataFrame({"Seq Date": ["2026-01-01", "2026-04-01"]})
    values, overrides = _plot_color_series(dat, "Seq Date")

    # Ordinals keep the colour scale continuous instead of one legend entry per run.
    assert values.iloc[0] == pd.Timestamp("2026-01-01").toordinal()
    assert overrides is not None
    assert overrides["title"] == "Seq Date"
    assert overrides["ticktext"][0] == "2026-01-01"
    assert overrides["ticktext"][-1] == "2026-04-01"
    assert len(overrides["tickvals"]) == len(overrides["ticktext"])


def test_plot_color_series_handles_all_missing_dates():
    dat = pd.DataFrame({"Seq Date": [None, "not-a-date"]})
    values, overrides = _plot_color_series(dat, "Seq Date")
    assert values.isna().all()
    assert overrides is None


def test_supports_trendline_requires_continuous_axes():
    assert supports_trendline("Loading pM", "Cluster Density") is True
    assert supports_trendline("Seq Date", "Cluster Density") is True
    assert supports_trendline("Instrument", "Cluster Density") is False
    assert supports_trendline("Loading pM", "Operator") is False


def test_linear_trendline_fits_a_perfect_numeric_line():
    x = pd.Series([1.0, 2.0, 3.0, 4.0])
    y = pd.Series([10.0, 20.0, 30.0, 40.0])

    x_ends, y_ends, r_squared, slope = linear_trendline(x, y, "numeric")

    assert x_ends == [1.0, 4.0]
    assert y_ends == pytest.approx([10.0, 40.0])
    assert r_squared == pytest.approx(1.0)
    assert slope == pytest.approx(10.0)


def test_linear_trendline_ignores_rows_missing_either_value():
    x = pd.Series([1.0, 2.0, None, 4.0])
    y = pd.Series([10.0, None, 30.0, 40.0])

    x_ends, y_ends, r_squared, slope = linear_trendline(x, y, "numeric")

    assert x_ends == [1.0, 4.0]
    assert y_ends == pytest.approx([10.0, 40.0])
    assert r_squared == pytest.approx(1.0)
    assert slope == pytest.approx(10.0)


def test_linear_trendline_returns_iso_dates_for_a_date_axis():
    x = pd.Series(["2026-01-01", "2026-02-01", "2026-03-01"])
    y = pd.Series([100.0, 200.0, 300.0])

    x_ends, y_ends, r_squared, slope = linear_trendline(x, y, "date")

    assert x_ends == ["2026-01-01", "2026-03-01"]
    assert y_ends[0] < y_ends[1]
    assert r_squared == pytest.approx(1.0, abs=1e-3)
    assert slope > 0


def test_linear_trendline_returns_none_without_enough_distinct_points():
    assert linear_trendline(pd.Series([1.0]), pd.Series([2.0]), "numeric") is None
    assert linear_trendline(pd.Series([]), pd.Series([]), "numeric") is None
    # Every point shares one x value, so no line can be fitted.
    assert linear_trendline(pd.Series([5.0, 5.0]), pd.Series([1.0, 9.0]), "numeric") is None


def test_linear_trendline_reports_zero_fit_for_a_flat_series():
    x = pd.Series([1.0, 2.0, 3.0])
    y = pd.Series([7.0, 7.0, 7.0])

    x_ends, y_ends, r_squared, slope = linear_trendline(x, y, "numeric")

    assert y_ends == pytest.approx([7.0, 7.0])
    assert r_squared == 0.0
    assert slope == pytest.approx(0.0)


def test_trendline_equation_text_for_numeric_axis():
    # y = 2x + 3, sampled between x=1 and x=5
    text = trendline_equation_text([1.0, 5.0], [5.0, 13.0], slope=2.0, x_kind="numeric")
    assert text == "y = 2x + 3"


def test_trendline_equation_text_handles_negative_intercept():
    # y = 2x - 3
    text = trendline_equation_text([1.0, 5.0], [-1.0, 7.0], slope=2.0, x_kind="numeric")
    assert text == "y = 2x - 3"


def test_trendline_equation_text_for_date_axis_anchors_to_first_point():
    text = trendline_equation_text(["2026-01-01", "2026-03-01"], [100.0, 160.0], slope=1.0, x_kind="date")
    assert text == "y = 1·days + 100 (day 0 = 2026-01-01)"


def make_runs(count: int) -> pd.DataFrame:
    return pd.DataFrame({"Run ID": [f"run-{i}" for i in range(count)]})


def test_apply_reported_rows_keeps_only_the_reported_rows():
    dat = make_runs(5)
    result = apply_reported_rows(dat, "[0, 2, 4]")
    assert result["Run ID"].tolist() == ["run-0", "run-2", "run-4"]


def test_apply_reported_rows_can_narrow_to_a_single_row():
    dat = make_runs(5)
    assert apply_reported_rows(dat, "[3]")["Run ID"].tolist() == ["run-3"]


def test_apply_reported_rows_returns_empty_when_filters_match_nothing():
    dat = make_runs(5)
    assert apply_reported_rows(dat, "[]").empty


def test_apply_reported_rows_keeps_all_rows_before_the_table_reports():
    # No draw callback has fired yet, so plotting everything beats plotting nothing.
    dat = make_runs(3)
    assert len(apply_reported_rows(dat, None)) == 3
    assert len(apply_reported_rows(dat, "")) == 3


def test_apply_reported_rows_ignores_unparsable_or_wrongly_shaped_payloads():
    dat = make_runs(3)
    assert len(apply_reported_rows(dat, "not json")) == 3
    assert len(apply_reported_rows(dat, '{"a": 1}')) == 3


def test_apply_reported_rows_drops_out_of_range_indices():
    # A stale report from a previous, larger dataset must not raise.
    dat = make_runs(3)
    result = apply_reported_rows(dat, "[0, 2, 99, -1]")
    assert result["Run ID"].tolist() == ["run-0", "run-2"]


def _sequencing_row_keys() -> list[str]:
    """The column names build_sequencing_run_rows emits, read from its source.

    Calling it needs a live Clarity session, so the row dict it appends is
    located in the AST instead -- enough to catch a rename drifting away from
    the presets.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "src" / "shinylims" / "integrations" / "queries" / "sequencing.py"
    ).read_text()

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
        if "Run ID" in keys and "Seq Date" in keys:
            return keys
    raise AssertionError("could not find the sequencing row dict")


def test_column_presets_only_name_columns_the_run_query_produces():
    """The presets are resolved by name at render time, so a column renamed in
    the query would silently drop out of every preset that lists it rather than
    failing anywhere visible."""
    available = set(_sequencing_row_keys())

    for label, columns in COLUMN_PRESETS:
        unknown = [column for column in columns if column not in available]
        assert not unknown, f"{label} names columns the query does not build: {unknown}"


def test_every_column_preset_shows_a_run_identifier():
    """A preset that hides both the LIMS id and the Run ID leaves rows the user
    cannot tell apart -- the flaw in the preset originally copied from samples.py."""
    for label, columns in COLUMN_PRESETS:
        assert {"Run ID", "seq_limsid"} & set(columns), f"{label} has no run identifier"


def test_default_preset_is_one_of_the_presets_on_the_menu():
    """The toolbar labels the default by name, so a default that no button can
    re-apply would leave the visitor unable to get back to it."""
    assert DEFAULT_COLUMN_PRESET in dict(COLUMN_PRESETS)
    assert DEFAULT_PRESET_COLUMNS == dict(COLUMN_PRESETS)[DEFAULT_COLUMN_PRESET]


def test_clamp_plot_height_keeps_the_split_usable():
    assert clamp_plot_height(640) == 640
    assert clamp_plot_height(10) == PLOT_HEIGHT_MIN
    assert clamp_plot_height(99999) == PLOT_HEIGHT_MAX


def test_clamp_plot_height_falls_back_for_unusable_values():
    """The height round-trips through sessionStorage and a Shiny input, so it can
    come back as anything -- unset, empty, or hand-edited."""
    for value in (None, "", "tall", {}):
        assert clamp_plot_height(value) == PLOT_HEIGHT_DEFAULT
    # It arrives from JS, where every number is a float.
    assert clamp_plot_height(640.7) == 640


def test_empty_plot_figure_matches_the_current_height():
    """The placeholder shares the panel with the real figure; a fixed height here
    would make the panel jump whenever a plot falls back to it."""
    assert empty_plot_figure("no data", 700).layout.height == 700
    assert empty_plot_figure("no data").layout.height == PLOT_HEIGHT_DEFAULT


def test_plot_panel_offers_a_keyboard_reachable_resize_handle():
    markup = str(seq_ui())

    assert "seq-plot-resizer" in markup
    assert 'role="separator"' in markup
    assert 'tabindex="0"' in markup


def test_resizer_script_is_bounded_by_the_python_limits():
    """The bounds are enforced twice -- in the browser as you drag, and in
    clamp_plot_height when the value comes back -- so they have to agree."""
    markup = str(seq_ui())

    assert f"var MIN_H = {PLOT_HEIGHT_MIN};" in markup
    assert f"var MAX_H = {PLOT_HEIGHT_MAX};" in markup
    assert f"var DEF_H = {PLOT_HEIGHT_DEFAULT};" in markup
