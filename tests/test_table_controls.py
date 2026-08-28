from __future__ import annotations

from pathlib import Path

from itables.javascript import JavascriptFunction, get_keys_to_be_evaluated

from shinylims.ui_helpers.table_controls import (
    EXPORT_HEADER_FORMAT,
    export_options,
    filter_state_draw_callback,
    preset_column_defs,
    visibility_preset_button,
)


FEATURE_MODULES = [
    Path(__file__).resolve().parents[1] / "src" / "shinylims" / "features" / name
    for name in ("projects.py", "samples.py", "sequencing.py")
]


def test_export_options_carries_a_header_formatter():
    options = export_options()

    assert options["columns"] == ":visible"
    assert options["format"]["header"] is EXPORT_HEADER_FORMAT
    assert isinstance(EXPORT_HEADER_FORMAT, JavascriptFunction)


def test_export_options_accepts_a_custom_column_selector():
    assert export_options(columns=":all")["columns"] == ":all"


def test_header_formatter_is_evaluated_as_javascript_when_nested_in_a_collection():
    """itables only turns a JavascriptFunction into a real JS function if it
    finds it while walking the args, so guard the nesting depth the export
    buttons actually sit at: buttons -> collection -> exportOptions -> format.
    A formatter left as a string would silently blank the headers again.
    """
    buttons = [
        {
            "extend": "collection",
            "text": "Type",
            "buttons": [
                {"extend": "csvHtml5", "exportOptions": export_options()},
            ],
        },
    ]

    assert get_keys_to_be_evaluated({"buttons": buttons}) == [
        ["buttons", 0, "buttons", 0, "exportOptions", "format", "header"]
    ]


def test_feature_tables_do_not_build_export_options_by_hand():
    """With column_filters="header" a bare {"columns": ...} exports blank
    column headers, so every export button must go through export_options().
    """
    offenders = [
        module.name
        for module in FEATURE_MODULES
        if '"exportOptions": {' in module.read_text()
    ]

    assert offenders == []


def test_row_state_callback_reports_selection_on_plain_row_clicks():
    """The plot's "Selected runs" scope reads dt_selected_rows_<key>, so the
    callback must bind select/deselect itself -- binding it inside a button's
    action (as it once did) left manually clicked rows unreported.
    """
    js = str(filter_state_draw_callback("sequencing", report_row_state=True))

    assert "dt.on('select deselect'" in js
    assert "'dt_selected_rows_sequencing'" in js
    # Per-instance guard: a window flag would survive a remount of the widget
    # and leave the new table with no handler at all.
    assert "settings.__selectionBound" in js
    assert "window.__selectionBound" not in js


def test_row_state_callback_exposes_a_reporter_for_bulk_selection_buttons():
    """"Select All Filtered Rows" selects rows without firing select events,
    so it pushes the new selection through this shared reporter."""
    js = str(filter_state_draw_callback("sequencing", report_row_state=True))

    assert "window.__sequencingReportSelection = function()" in js


def test_selection_reporting_is_opt_in_with_the_rest_of_the_row_state():
    js = str(filter_state_draw_callback("samples"))

    assert "dt_selected_rows_samples" not in js
    assert "dt_filtered_rows_samples" not in js


def test_visibility_preset_button_resolves_column_names_to_indexes():
    js = str(visibility_preset_button(["b", "d"], ["a", "b", "c", "d"], text="Preset")["action"])

    assert "dt.columns().visible(false)" in js
    assert "dt.column(1).visible(true)" in js
    assert "dt.column(3).visible(true)" in js
    assert "dt.column(0).visible(true)" not in js


def test_visibility_preset_button_drops_names_the_table_does_not_have():
    """A renamed or removed column should shrink its preset, not shift the rest
    of it onto the wrong columns."""
    js = str(visibility_preset_button(["a", "gone", "c"], ["a", "b", "c"], text="Preset")["action"])

    assert "dt.column(0).visible(true)" in js
    assert "dt.column(2).visible(true)" in js
    assert "dt.column(1).visible(true)" not in js


def test_visibility_preset_button_still_accepts_raw_indexes():
    """Both call sites resolve by name now, but the positional form stays supported
    for a table whose column names aren't to hand when the buttons are built."""
    js = str(visibility_preset_button([2, 5], text="Minimal View")["action"])

    assert "dt.column(2).visible(true)" in js
    assert "dt.column(5).visible(true)" in js


def test_preset_column_defs_hide_everything_outside_the_preset():
    defs = preset_column_defs(["a", "d"], ["a", "b", "c", "d"])

    assert defs == [{"targets": [1, 2], "visible": False}]


def test_preset_column_defs_are_empty_when_the_preset_covers_every_column():
    """An empty list keeps `columnDefs` free of a `visible: True` entry that would
    fight the visitor's restored state on a later mount."""
    assert preset_column_defs(["a", "b"], ["a", "b"]) == []


def test_preset_button_records_itself_as_the_active_preset():
    js = str(
        visibility_preset_button(["b"], ["a", "b"], text="Run QC", table_key="sequencing")["action"]
    )

    assert 'sessionStorage.setItem("shinylims_sequencing_preset", "Run QC")' in js
    assert "window.__sequencingSyncPreset()" in js


def test_preset_button_suppresses_the_override_watcher_while_it_applies():
    """Applying a preset fires one column-visibility event per column -- the same
    event that clears the indicator -- so a preset would immediately clear itself."""
    js = str(
        visibility_preset_button(["b"], ["a", "b"], text="Run QC", table_key="sequencing")["action"]
    )

    assert "window.__sequencingPresetApplying = true;" in js
    assert "} finally {" in js
    assert "window.__sequencingPresetApplying = false;" in js


def test_preset_button_without_a_table_key_records_nothing():
    js = str(visibility_preset_button([1], text="Minimal View")["action"])

    assert "sessionStorage" not in js
    assert "SyncPreset" not in js


def test_draw_callback_labels_the_preset_menu_and_falls_back_to_the_default():
    js = str(filter_state_draw_callback("sequencing", default_preset="Run Overview"))

    assert "container.querySelector('.dt-preset-menu')" in js
    assert "'Presets: ' + active" in js
    assert "classList.toggle('dt-preset-active'" in js
    # Never stored means a first visit, which columnDefs started on the default.
    assert 'if (active === null) active = "Run Overview";' in js


def test_draw_callback_clears_the_preset_when_columns_are_changed_by_hand():
    js = str(filter_state_draw_callback("sequencing", default_preset="Run Overview"))

    assert "dt.on('column-visibility'" in js
    assert "if (window.__sequencingPresetApplying) return;" in js
    assert "sessionStorage.setItem(\"shinylims_sequencing_preset\", '')" in js
    # Per-instance, like the selection binding: a window flag would survive a
    # remount and leave the new table unwatched.
    assert "settings.__presetBound" in js


def test_draw_callback_shows_no_preset_when_the_table_has_no_default():
    js = str(filter_state_draw_callback("samples"))

    assert 'if (active === null) active = "";' in js


def test_draw_callback_labels_a_hand_made_column_selection_as_custom():
    js = str(filter_state_draw_callback("samples", default_preset="Sample Overview"))

    # Same stored value the preset indicator reads: `''` is set by the
    # column-visibility watcher above, i.e. the user picking columns themselves.
    assert "container.querySelector('.dt-selection-menu')" in js
    assert "active ? 'Selection' : 'Selection: Custom'" in js
    assert "classList.toggle('dt-selection-custom', !active)" in js


def test_every_table_with_a_preset_menu_also_marks_its_selection_menu():
    """The two indicators are a pair: the Presets menu is highlighted while a
    preset is applied and the Selection menu while the columns are the user's
    own pick. A tab that classed only the Presets menu (as sequencing.py once
    did) shows nothing at all once the user picks columns by hand.
    """
    missing = [
        module.name
        for module in FEATURE_MODULES
        if '"dt-preset-menu"' in (source := module.read_text())
        and '"dt-selection-menu"' not in source
    ]

    assert missing == []
