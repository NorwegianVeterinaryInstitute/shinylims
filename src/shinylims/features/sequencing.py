'''
sequencing.py - table module containing UI and server logic for the Sequencing table tab
'''

import json

from shiny import ui, reactive, render
from shinywidgets import output_widget, render_widget, reactive_read
from itables.widget import ITable
from itables.javascript import JavascriptFunction
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from shinylims.features.samples import _seq_limsid_matches, _split_seq_limsids
from shinylims.ui_helpers.table_controls import (
    COLVIS_COLUMN_TEXT,
    searchbuilder_title_defs,
    DATE_VALUE_RENDERER,
    FILTER_BUILDER_LANGUAGE,
    build_filter_status_bar,
    clear_all_filters_script,
    deselect_all_columns_button,
    export_options,
    filter_state_draw_callback,
    preset_column_defs,
    select_all_columns_button,
    truncated_text_renderer,
    visibility_preset_button,
)


##############################
# RUN PLOT METRICS
##############################

PHIX_CONTROL_APPLICATION = "PhiX Control Run"


def _numeric_avg_fragment_size(raw):
    """Coerce Avg Fragment Size (may be a '+'-joined multi-value string) to one float."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    values = []
    for part in str(raw).split("+"):
        try:
            values.append(float(part.strip()))
        except ValueError:
            continue
    return sum(values) / len(values) if values else None


PLOT_METRICS = {
    "Seq Date": {"col": "Seq Date", "kind": "date"},
    "Loading pM": {"col": "Loading pM", "kind": "numeric"},
    "Cluster Density": {"col": "Cluster Density", "kind": "numeric"},
    "Phix Loaded (%)": {"col": "Phix Loaded (%)", "kind": "numeric"},
    "Phix Aligned (%)": {"col": "Phix Aligned (%)", "kind": "numeric"},
    "Avg Fragment Size": {"col": "Avg Fragment Size", "kind": "numeric", "coerce": _numeric_avg_fragment_size},
    "Yield Total": {"col": "Yield Total", "kind": "numeric"},
    "QV30 R1": {"col": "QV30 R1", "kind": "numeric"},
    "PF Reads": {"col": "PF Reads", "kind": "numeric"},
    "Application": {"col": "Application", "kind": "categorical"},
    "Instrument": {"col": "Instrument", "kind": "categorical"},
    "Operator": {"col": "Operator", "kind": "categorical"},
}

PLOT_METRIC_LABELS = list(PLOT_METRICS.keys())

# Column visibility presets for the run table's "Presets" menu, as column names
# rather than positions -- see visibility_preset_button. Each one is a task the
# table gets used for, not a slice of the schema.
COLUMN_PRESETS = [
    # What ran, when, who, how big.
    ("🏃 Run Overview", [
        "seq_limsid", "Run ID", "Instrument", "Seq Date",
        "Operator", "Application", "Sample Count",
    ]),
    # Every output metric, matching what the run plots draw from.
    ("📊 Run QC", [
        "Run ID", "Seq Date", "Application", "Cluster Density",
        "Phix Loaded (%)", "Phix Aligned (%)", "Yield Total",
        "QV30 R1", "QV30 R2", "PF Reads",
    ]),
    # The input side of a run against the one metric it drives (cluster
    # density) -- what to look at when a run under- or over-clusters.
    ("⚗️ Loading & Library", [
        "Run ID", "Seq Date", "Application", "Loading pM",
        "Diluted Denatured (uL)", "Avg Fragment Size", "Combined Pool",
        "Phix Loaded (%)", "Cluster Density",
    ]),
    # Kit and cycle configuration, for reagent planning.
    ("🧰 Run Setup", [
        "Run ID", "Instrument", "Seq Date", "Application",
        "Casette Type", "Read Length", "Index Cycles", "Sample Count",
    ]),
    # Finding a run by experiment or species, and reading the operator's notes.
    ("🔍 Sample Context", [
        "seq_limsid", "Run ID", "Seq Date", "Species", "Experiment Name",
        "Application", "Sample Count", "Comment",
    ]),
]

# The table opens on this one rather than all 25 columns: a first-time visitor
# gets a readable run list instead of a wall of horizontal scroll. Only a
# default -- stateSave restores a returning visitor's own columns over it.
DEFAULT_COLUMN_PRESET = "🏃 Run Overview"
DEFAULT_PRESET_COLUMNS = dict(COLUMN_PRESETS)[DEFAULT_COLUMN_PRESET]


# Fixed sessionStorage keys so the page's setup survives a view switch, which
# unmounts this whole page (app_content renders one view at a time).
SEQ_TABLE_STATE_KEY = "shinylims_sequencing_dt_state"
SEQ_PLOT_STATE_KEY = "shinylims_sequencing_plot_settings"

# "" is the no-colour choice; Shiny returns it as an empty string.
PLOT_COLOR_CHOICES = {"": "None", **{label: label for label in PLOT_METRIC_LABELS}}

# The plot and the table split one screen: the table sizes itself to whatever is
# left below it (see fitScrollHeight in filter_state_draw_callback), so dragging
# the plot taller hands the difference straight to the table and back. Bounds
# keep either side from being dragged away to nothing.
# ~25% taller than plotly's 400px default: the plot reads as over-wide on a 16:9
# screen otherwise.
PLOT_HEIGHT_DEFAULT = 500
PLOT_HEIGHT_MIN = 240
PLOT_HEIGHT_MAX = 1200


def clamp_plot_height(value, default: int = PLOT_HEIGHT_DEFAULT) -> int:
    """Return a usable figure height, falling back to the default for anything
    unset or unparsable (a hand-edited sessionStorage entry, say)."""
    try:
        height = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(PLOT_HEIGHT_MIN, min(PLOT_HEIGHT_MAX, height))


def exclude_phix_control_runs(dat: pd.DataFrame) -> pd.DataFrame:
    """Return the rows the run plots are drawn from.

    PhiX control runs carry no library of their own, so their metrics sit well
    outside the range of real runs and stretch every axis they appear on.
    """
    if "Application" not in dat.columns:
        return dat
    return dat[dat["Application"] != PHIX_CONTROL_APPLICATION]


def _plot_axis_series(dat: pd.DataFrame, label: str) -> pd.Series:
    """Return one plot-ready axis series for a PLOT_METRICS label."""
    meta = PLOT_METRICS[label]
    series = dat[meta["col"]]
    if meta["kind"] == "date":
        # ISO date strings, not datetime64, survive the FigureWidget round-trip to the
        # browser intact; a raw datetime64 column gets serialized as epoch-nanosecond
        # ints and renders as a linear axis instead of a date axis.
        return pd.to_datetime(series, errors="coerce").dt.strftime("%Y-%m-%d")
    if meta["kind"] == "categorical":
        text = series.astype("string").str.strip()
        return text.replace("", pd.NA).fillna("Unknown")
    coerce = meta.get("coerce")
    if coerce is not None:
        series = series.apply(coerce)
    return pd.to_numeric(series, errors="coerce")


def _plot_color_series(dat: pd.DataFrame, label: str) -> tuple[pd.Series, dict | None]:
    """Return (values, colorbar_overrides) for the colour dimension.

    Plotly treats a datetime column as *discrete*, which would emit one legend
    entry per run, so dates become ordinal numbers plus date-formatted colourbar
    ticks. Numeric columns get a continuous colourbar and categorical ones a
    discrete legend, both handled natively by plotly express.
    """
    if PLOT_METRICS[label]["kind"] == "categorical":
        # Legend entry width is sized from a measurement that plotly.js takes outside
        # the DOM subtree the app's page-wide CSS zoom scales, so it comes out slightly
        # smaller than the text actually renders at and clips the last character or
        # two. A couple of trailing non-breaking spaces (invisible) pad the margin
        # plotly reserves without changing what's visibly displayed.
        return _plot_axis_series(dat, label) + "  ", None
    if PLOT_METRICS[label]["kind"] != "date":
        return _plot_axis_series(dat, label), None

    parsed = pd.to_datetime(dat[PLOT_METRICS[label]["col"]], errors="coerce")
    ordinals = parsed.map(lambda value: value.toordinal() if pd.notna(value) else None)
    ordinals = pd.to_numeric(ordinals, errors="coerce")

    valid = ordinals.dropna()
    if valid.empty:
        return ordinals, None

    ticks = np.linspace(valid.min(), valid.max(), min(5, max(2, valid.nunique())))
    overrides = {
        "title": label,
        "tickvals": [float(tick) for tick in ticks],
        "ticktext": [pd.Timestamp.fromordinal(int(round(tick))).strftime("%Y-%m-%d") for tick in ticks],
    }
    return ordinals, overrides


def _fit_values(series: pd.Series, kind: str) -> pd.Series:
    """Return a numeric view of an axis series for curve fitting."""
    if kind == "date":
        parsed = pd.to_datetime(series, errors="coerce")
        return pd.to_numeric(
            parsed.map(lambda value: value.toordinal() if pd.notna(value) else None),
            errors="coerce",
        )
    return pd.to_numeric(series, errors="coerce")


def apply_reported_rows(dat: pd.DataFrame, raw_indices: str | None) -> pd.DataFrame:
    """Return the subset of rows the table reported, by positional index.

    ``raw_indices`` is one of the JSON arrays the table reports for its filtered
    or selected rows; indices are positional into the same frame handed to the
    widget. A missing or unparsable value means the table hasn't reported yet, so
    every row is kept rather than silently plotting nothing. An empty array is a
    real answer ("nothing matches") and does narrow to no rows.
    """
    if not raw_indices:
        return dat
    try:
        indices = json.loads(raw_indices)
    except (TypeError, ValueError):
        return dat
    if not isinstance(indices, list):
        return dat

    valid = [i for i in indices if isinstance(i, int) and 0 <= i < len(dat)]
    return dat.iloc[valid]


def empty_plot_figure(title: str, height: int = PLOT_HEIGHT_DEFAULT):
    """Return a blank scatter figure carrying an explanatory title."""
    fig = px.scatter(title=title)
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=height)
    return fig


def supports_trendline(x_label: str, y_label: str) -> bool:
    """Return whether a linear trendline is meaningful for this axis pair."""
    return (
        PLOT_METRICS[x_label]["kind"] in {"date", "numeric"}
        and PLOT_METRICS[y_label]["kind"] == "numeric"
    )


def linear_trendline(
    x_values: pd.Series,
    y_values: pd.Series,
    x_kind: str,
) -> tuple[list, list[float], float, float] | None:
    """Return ([x_start, x_end], [y_start, y_end], r_squared, slope) for a least-squares fit.

    `slope` is in y-units per raw fit-x-unit — per day for a date axis (its fit
    values are ordinals, so this is directly meaningful), per axis unit otherwise.
    Returns None when the data cannot support a line (fewer than two points, or
    every point sharing one x value).
    """
    x_numeric = _fit_values(x_values, x_kind)
    y_numeric = pd.to_numeric(y_values, errors="coerce")

    usable = x_numeric.notna() & y_numeric.notna()
    if int(usable.sum()) < 2:
        return None

    x_fit = x_numeric[usable].to_numpy(dtype=float)
    y_fit = y_numeric[usable].to_numpy(dtype=float)
    if np.unique(x_fit).size < 2:
        return None

    slope, intercept = np.polyfit(x_fit, y_fit, 1)
    ends = [float(x_fit.min()), float(x_fit.max())]
    y_ends = [float(slope * end + intercept) for end in ends]

    if np.unique(y_fit).size < 2:
        r_squared = 0.0
    else:
        r_squared = float(np.corrcoef(x_fit, y_fit)[0, 1] ** 2)

    if x_kind == "date":
        x_ends = [pd.Timestamp.fromordinal(int(round(end))).strftime("%Y-%m-%d") for end in ends]
    else:
        x_ends = ends
    return x_ends, y_ends, r_squared, float(slope)


def trendline_equation_text(x_ends: list, y_ends: list[float], slope: float, x_kind: str) -> str:
    """Return a compact "y = ..." label for a fitted trendline.

    A date axis is fit in ordinal days, so a raw intercept would be the (meaningless)
    value at year 1 CE; anchoring it to the first plotted date instead keeps both
    terms readable while leaving the slope - already in per-day units - untouched.
    """
    if x_kind == "date":
        return f"y = {slope:.3g}·days + {y_ends[0]:.3g} (day 0 = {x_ends[0]})"
    intercept = y_ends[0] - slope * x_ends[0]
    return f"y = {slope:.3g}x {'+' if intercept >= 0 else '-'} {abs(intercept):.3g}"


##############################
# UI ILMN SEQ TABLE
##############################

def seq_ui():
    return ui.div(
        clear_all_filters_script("sequencing"),
        # A <details> rather than a CSS-hidden div: Shiny suspends outputs it considers
        # hidden, and a `display: none` panel means the figure never renders at all.
        # Its <summary> is hidden (the toolbar's "Run Plots" button is the trigger), so
        # the panel carries its own header below.
        ui.tags.details(
            ui.tags.summary("Run Plots"),
            ui.div(
                ui.span("Run Plots", class_="seq-plot-panel-title"),
                ui.tags.button(
                    "Hide",
                    type="button",
                    class_="btn btn-sm btn-link seq-plot-hide",
                    # The toolbar button scrolls out of reach once the panel pushes the
                    # table down, so the panel carries its own way to close.
                    onclick=(
                        "var p=document.getElementById('seq-plot-panel');"
                        "if(p)p.open=false;"
                        "var b=document.querySelector('.seq-plot-toolbar-btn');"
                        "if(b)b.classList.remove('active');"
                        # Reclaim the space the panel gave back (see the toolbar button).
                        "if(window.__sequencingFitFn)window.__sequencingFitFn();"
                        "setTimeout(function(){if(window.__sequencingFitFn)window.__sequencingFitFn();},250);"
                    ),
                ),
                class_="card-header seq-plot-panel-header",
            ),
            ui.div(
                ui.div(
                    ui.div(output_widget("seq_plot"), class_="seq-plot-figure"),
                    ui.div(
                        ui.input_select("seq_plot_x", "X-axis", choices=PLOT_METRIC_LABELS, selected="Seq Date"),
                        ui.input_select("seq_plot_y", "Y-axis", choices=PLOT_METRIC_LABELS, selected="Cluster Density"),
                        ui.input_select("seq_plot_color", "Colour by", choices=PLOT_COLOR_CHOICES, selected=""),
                        ui.input_radio_buttons(
                            "seq_plot_scope",
                            "Runs to plot",
                            choices={
                                "all": "All runs",
                                "filtered": "Filtered runs",
                                "selected": "Selected runs",
                            },
                            selected="all",
                        ),
                        ui.input_checkbox("seq_plot_trendline", "Show trendline", False),
                        ui.span(
                            "Trendline needs a numeric or date X-axis and a numeric Y-axis.",
                            class_="text-muted seq-plot-controls-hint",
                        ),
                        class_="seq-plot-controls",
                    ),
                    class_="seq-plot-layout",
                ),
                class_="card-body",
            ),
            # The split between plot and table is a drag away: the table sizes
            # itself to the space left below it, so whatever this takes from one
            # it gives to the other. A separator role (rather than a bare div)
            # is what carries the arrow-key resizing to keyboard users.
            ui.div(
                role="separator",
                tabindex="0",
                aria_orientation="horizontal",
                aria_label="Resize plot; drag or use the arrow keys",
                title="Drag to resize the plot (double-click to reset)",
                class_="seq-plot-resizer",
            ),
            id="seq-plot-panel",
            # No `mb-3`: the spacing belongs only to the open state (see styles.css),
            # otherwise a collapsed panel leaves a gap above the toolbar.
            class_="card seq-plot-panel",
        ),
        ui.output_ui("filter_status_bar_sequencing"),
        output_widget("data_seq", fillable=False),
        # The plot controls are unmounted along with the rest of the page on a view
        # switch, so they'd come back at their declared defaults. Mirror them to
        # sessionStorage the same way the table's own state is kept (see stateSave
        # above), which keeps the whole page's setup consistent across navigation
        # without needing the server to referee who wins on remount.
        ui.tags.script(
            f"""
            (function() {{
                var KEY = '{SEQ_PLOT_STATE_KEY}';
                var SELECTS = ['seq_plot_x', 'seq_plot_y', 'seq_plot_color'];

                function scopeInputs() {{
                    return document.querySelectorAll('input[name="seq_plot_scope"]');
                }}

                var restoring = false;

                var MIN_H = {PLOT_HEIGHT_MIN};
                var MAX_H = {PLOT_HEIGHT_MAX};
                var DEF_H = {PLOT_HEIGHT_DEFAULT};

                function clampHeight(px) {{
                    return Math.max(MIN_H, Math.min(MAX_H, Math.round(px)));
                }}

                function plotEl() {{
                    return document.querySelector('.seq-plot-figure .js-plotly-plot');
                }}

                function currentPlotHeight() {{
                    // offsetHeight is in the figure's own pre-zoom pixels -- the same
                    // space plotly's layout height is expressed in.
                    var plot = plotEl();
                    return plot && plot.offsetHeight ? plot.offsetHeight : DEF_H;
                }}

                function applyPlotHeight(px) {{
                    px = clampHeight(px);
                    var plot = plotEl();
                    // Width stays on plotly's own responsive sizing; only height is ours.
                    if (plot && window.Plotly) window.Plotly.relayout(plot, {{ height: px }});
                    // Whatever the plot takes is the table's to lose, and vice versa:
                    // the table refits to the space left below it.
                    if (window.__sequencingFitFn) window.__sequencingFitFn();
                    return px;
                }}

                function reportPlotHeight(px) {{
                    // The server reads this without taking a dependency on it, so this
                    // doesn't redraw anything now -- it keeps the *next* render (an axis
                    // change, say) from snapping back to the default height.
                    if (window.Shiny && window.Shiny.setInputValue) {{
                        window.Shiny.setInputValue('seq_plot_height', px);
                    }}
                }}

                function save() {{
                    if (restoring) return;
                    var state = {{}};
                    SELECTS.forEach(function(id) {{
                        var el = document.getElementById(id);
                        if (el) state[id] = el.value;
                    }});
                    var checked = document.querySelector('input[name="seq_plot_scope"]:checked');
                    if (checked) state.seq_plot_scope = checked.value;
                    var trend = document.getElementById('seq_plot_trendline');
                    if (trend) state.seq_plot_trendline = trend.checked;
                    var panel = document.getElementById('seq-plot-panel');
                    if (panel) state.panel_open = panel.open;
                    // Skipped while the figure is unmounted or mid-render: a zero
                    // height there would overwrite a real one with the default.
                    var plot = plotEl();
                    if (plot && plot.offsetHeight) state.plot_height = plot.offsetHeight;
                    try {{ sessionStorage.setItem(KEY, JSON.stringify(state)); }} catch (e) {{}}
                }}

                function fire(el) {{
                    // Shiny's input bindings listen for change; a native bubbling event
                    // reaches their jQuery handlers just fine.
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}

                function restore() {{
                    var raw = null;
                    try {{ raw = sessionStorage.getItem(KEY); }} catch (e) {{ return true; }}
                    if (!raw) return true;
                    var state;
                    try {{ state = JSON.parse(raw); }} catch (e) {{ return true; }}

                    SELECTS.forEach(function(id) {{
                        var el = document.getElementById(id);
                        if (el && state[id] != null && el.value !== state[id]) {{
                            el.value = state[id];
                            fire(el);
                        }}
                    }});
                    if (state.seq_plot_scope != null) {{
                        scopeInputs().forEach(function(el) {{
                            if (el.value === state.seq_plot_scope && !el.checked) {{
                                el.checked = true;
                                fire(el);
                            }}
                        }});
                    }}
                    var trend = document.getElementById('seq_plot_trendline');
                    if (trend && state.seq_plot_trendline != null
                        && trend.checked !== state.seq_plot_trendline) {{
                        trend.checked = state.seq_plot_trendline;
                        fire(trend);
                    }}
                    if (state.plot_height != null) {{
                        var height = clampHeight(state.plot_height);
                        // Tell the server first: if the figure hasn't rendered yet, it
                        // comes back at this height and needs no relayout at all.
                        reportPlotHeight(height);
                        var plotTries = 0;
                        (function waitForPlot() {{
                            if (plotEl()) {{ applyPlotHeight(height); return; }}
                            if (++plotTries < 300) setTimeout(waitForPlot, 100);
                        }})();
                    }}
                    return true;
                }}

                // Dragging the bar under the plot moves the split between plot and
                // table. Bound to the handle itself rather than the document so it
                // goes away with the panel on a view switch.
                function setupResizer() {{
                    var handle = document.querySelector('.seq-plot-resizer');
                    if (!handle || handle.__resizerBound) return;
                    handle.__resizerBound = true;

                    var startY = 0, startHeight = 0, scale = 1, pending = null, frame = 0;

                    function commit() {{
                        var px = currentPlotHeight();
                        reportPlotHeight(px);
                        save();
                    }}

                    function flush() {{
                        frame = 0;
                        if (pending === null) return;
                        applyPlotHeight(pending);
                        pending = null;
                    }}

                    handle.addEventListener('pointerdown', function(event) {{
                        var plot = plotEl();
                        if (!plot) return;
                        event.preventDefault();
                        startY = event.clientY;
                        startHeight = currentPlotHeight();
                        // The figure subtree carries its own `zoom` (see styles.css), so
                        // a pointer delta in screen pixels is not a delta in the layout
                        // pixels the height is set in. Measure the ratio off the element
                        // instead of tracking which zoom rules are in play.
                        var rect = plot.getBoundingClientRect();
                        scale = plot.offsetHeight ? rect.height / plot.offsetHeight : 1;
                        if (!scale) scale = 1;
                        handle.setPointerCapture(event.pointerId);
                        handle.classList.add('dragging');
                    }});

                    handle.addEventListener('pointermove', function(event) {{
                        if (!handle.hasPointerCapture(event.pointerId)) return;
                        pending = startHeight + (event.clientY - startY) / scale;
                        // One relayout per frame: plotly redraws on every call, and a
                        // move event can fire several times a frame.
                        if (!frame) frame = requestAnimationFrame(flush);
                    }});

                    function endDrag(event) {{
                        if (!handle.hasPointerCapture(event.pointerId)) return;
                        handle.releasePointerCapture(event.pointerId);
                        handle.classList.remove('dragging');
                        if (frame) {{ cancelAnimationFrame(frame); flush(); }}
                        commit();
                    }}
                    handle.addEventListener('pointerup', endDrag);
                    handle.addEventListener('pointercancel', endDrag);

                    handle.addEventListener('keydown', function(event) {{
                        var step = event.key === 'ArrowUp' ? -24
                            : event.key === 'ArrowDown' ? 24 : 0;
                        if (!step) return;
                        event.preventDefault();
                        applyPlotHeight(currentPlotHeight() + step);
                        commit();
                    }});

                    handle.addEventListener('dblclick', function() {{
                        applyPlotHeight(DEF_H);
                        commit();
                    }});
                }}

                function restorePanel() {{
                    var raw = null;
                    try {{ raw = sessionStorage.getItem(KEY); }} catch (e) {{ return; }}
                    if (!raw) return;
                    var state;
                    try {{ state = JSON.parse(raw); }} catch (e) {{ return; }}
                    if (!state.panel_open) return;

                    var panel = document.getElementById('seq-plot-panel');
                    if (!panel || panel.open) return;
                    panel.open = true;

                    // Same follow-up work the toolbar button does: the figure was laid
                    // out while hidden, and the table has less room now.
                    var settle = function() {{
                        var plot = panel.querySelector('.js-plotly-plot');
                        if (plot && window.Plotly) window.Plotly.Plots.resize(plot);
                        if (window.__sequencingFitFn) window.__sequencingFitFn();
                    }};
                    settle();
                    setTimeout(settle, 250);

                    // The toolbar button belongs to the table widget, which mounts on its
                    // own schedule, so chase it separately rather than making the panel's
                    // restore wait on (and be lost to) a slow table load.
                    var btnTries = 0;
                    (function syncToolbarButton() {{
                        var btn = document.querySelector('.seq-plot-toolbar-btn');
                        if (btn) {{
                            btn.classList.add('active');
                            settle();
                            return;
                        }}
                        if (++btnTries < 300) setTimeout(syncToolbarButton, 100);
                    }})();
                }}

                // The controls live inside the panel and are part of the same render, so
                // they may not be in the DOM yet when this runs; poll briefly instead of
                // guessing a delay. `restoring` suppresses save() for the duration:
                // re-applying a control fires a change event, and saving mid-restore
                // would write back a panel state that hasn't been re-applied yet.
                var tries = 0;
                (function waitForControls() {{
                    if (document.getElementById('seq_plot_x')) {{
                        restoring = true;
                        try {{
                            setupResizer();
                            restorePanel();
                            restore();
                        }} finally {{
                            restoring = false;
                        }}
                        return;
                    }}
                    if (++tries < 40) setTimeout(waitForControls, 50);
                }})();

                if (!window.__seqPlotStateBound) {{
                    window.__seqPlotStateBound = true;
                    document.addEventListener('change', function(event) {{
                        var t = event.target;
                        if (!t || !t.id && t.name !== 'seq_plot_scope') return;
                        if (t.name === 'seq_plot_scope' || t.id === 'seq_plot_trendline'
                            || SELECTS.indexOf(t.id) !== -1) {{
                            save();
                        }}
                    }});
                    // `toggle` doesn't bubble, so listen in the capture phase.
                    document.addEventListener('toggle', function(event) {{
                        if (event.target && event.target.id === 'seq-plot-panel') save();
                    }}, true);
                }}
            }})();
            """
        ),
    )

##############################
# SERVER ILMN SEQ TABLE
##############################

# Server logic for the Sequencing page
def seq_server(seq_df, input):

    related_seq_ids = reactive.Value(None)
    related_filter_label = reactive.Value(None)
    related_filter_source = reactive.Value("samples")

    @reactive.Calc
    def filtered_seq():
        df = seq_df().copy().reset_index(drop=True)
        seq_ids = related_seq_ids.get()
        if seq_ids and "seq_limsid" in df.columns:
            mask = df["seq_limsid"].apply(
                lambda cell: _seq_limsid_matches(cell, seq_ids)
            )
            df = df[mask].reset_index(drop=True)
        return df

    @render.ui
    def filter_status_bar_sequencing():
        extra = []
        seq_ids = related_seq_ids.get()
        if seq_ids:
            df = seq_df()
            matched = (
                df["seq_limsid"].apply(
                    lambda cell: _seq_limsid_matches(cell, seq_ids)
                ).sum()
                if "seq_limsid" in df.columns
                else 0
            )
            label = related_filter_label.get()
            source = related_filter_source.get()
            selection_desc = f" ({label})" if label else ""
            extra.append(
                f"Related runs from selected {source}{selection_desc}: "
                f"{matched} runs"
            )
        try:
            raw = input.dt_filter_state_sequencing()
        except Exception:
            raw = None
        return build_filter_status_bar(
            "sequencing",
            raw,
            extra_lines=extra,
        )

    @reactive.Effect
    @reactive.event(input.clear_all_filters_sequencing)
    def _clear_all_filters():
        related_seq_ids.set(None)
        related_filter_label.set(None)
        related_filter_source.set("samples")

    def set_seq_filter(
        seq_ids,
        label: str | None = None,
        source: str = "samples",
    ) -> None:
        """Filter Sequencing to runs related to selected samples or projects."""
        normalized_seq_ids = set()
        for seq_id in seq_ids:
            normalized_seq_ids.update(_split_seq_limsids(seq_id))
        related_seq_ids.set(normalized_seq_ids or None)
        related_filter_label.set(label)
        related_filter_source.set(source)

    # Return HTML tag with DT table element
    @render_widget
    def data_seq():
        dat = filtered_seq()

        # Format date column for DataTables display
        if "Seq Date" in dat.columns:
            dat["Seq Date"] = dat["Seq Date"].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ''
            )

        # Determine indices for special column handling
        comment_index = dat.columns.get_loc('Comment') if 'Comment' in dat.columns else -1
        run_number_index = dat.columns.get_loc('Run Number') if 'Run Number' in dat.columns else -1
        cluster_density_index = dat.columns.get_loc('Cluster Density') if 'Cluster Density' in dat.columns else -1
        species_index = dat.columns.get_loc('Species') if 'Species' in dat.columns else -1
        experiment_name_index = dat.columns.get_loc('Experiment Name') if 'Experiment Name' in dat.columns else -1
        
        # Find index for order column
        column_to_sort = "Seq Date"
        if column_to_sort in dat.columns:
            column_index = dat.columns.get_loc(column_to_sort)
            date_column_index = column_index  # Store for columnDefs
        else:
            column_index = 0  # Default to first column if Seq Date not found
            date_column_index = -1  # Indicates no date column found

        return ITable(
                dat, 
                layout={"topStart": "buttons", "topEnd": "search", "bottomEnd": None},
                lengthMenu=[[200, 500, 1000, 2000, -1], [200, 500, 1000, 2000, "All"]],
                select=True,
                column_filters="header",
                search={"smart": True},
                # Navigating to another view unmounts this table (app_content renders one
                # view at a time), which would otherwise drop the user's search, column
                # filters and Filter Builder rules. DataTables' own state storage keys off
                # the table's id, and the widget gets a fresh auto-generated one on every
                # mount, so the key would never match -- hence the explicit fixed key
                # below. sessionStorage means it survives navigation but not a new tab.
                stateSave=True,
                stateSaveCallback=JavascriptFunction(f"""
                    function(settings, data) {{
                        try {{
                            sessionStorage.setItem('{SEQ_TABLE_STATE_KEY}', JSON.stringify(data));
                        }} catch (e) {{}}
                    }}
                """),
                stateLoadCallback=JavascriptFunction(f"""
                    function(settings) {{
                        try {{
                            return JSON.parse(sessionStorage.getItem('{SEQ_TABLE_STATE_KEY}'));
                        }} catch (e) {{ return null; }}
                    }}
                """),
                # stateSaveCallback/stateLoadCallback are valid DataTables options that
                # itables just doesn't list in its own TypedDict; it forwards them fine.
                warn_on_undocumented_option=False,
                classes="nowrap compact hover order-column cell-border",
                scrollY="84vh",
                scrollX=True,
                paging=True,
                scroller=True,
                deferRender=True,
                colReorder=True,
                language=FILTER_BUILDER_LANGUAGE,
                maxBytes=0,
                allow_html=True,
                autoWidth=True,
                keys=True,
                buttons=[
                        {'extend': "spacer",
                         'style': 'bar',
                         'text': 'Columns'},
                        # Column visibility toggle
                        {
                            "extend": "colvis",
                            "text": "Selection",
                            # Relabelled "Selection: Custom" by the draw callback
                            # whenever the visible columns are the user's own pick
                            # rather than one of the presets below.
                            "className": "dt-selection-menu",
                            "collectionLayout": "two-column",
                            "columnText": COLVIS_COLUMN_TEXT,
                        },
                        # Button to select specific columns presets
                        {
                        "extend": "collection",
                        "text": "Presets",
                        # Relabelled with the active preset by the draw callback.
                        "className": "dt-preset-menu",
                        "buttons": [
                            select_all_columns_button(),
                            deselect_all_columns_button(),
                            *(
                                visibility_preset_button(
                                    preset_columns,
                                    dat.columns,
                                    text=preset_text,
                                    table_key="sequencing",
                                )
                                for preset_text, preset_columns in COLUMN_PRESETS
                            ),
                        ]
                    },
                        {'extend': "spacer",
                         'style': 'bar',
                         'text': 'Filter'},
                        {"extend": "searchBuilder"},
                        {
                            "text": "☑️ Select All Filtered Rows",
                            # `select`/`deselect` events (and so the report to the
                            # server) don't fire for rows DataTables selects in bulk
                            # here, hence the explicit report afterwards -- see
                            # __sequencingReportSelection in filter_state_draw_callback.
                            "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    // Replace selection (don't accumulate)
                                    dt.rows().deselect();
                                    dt.rows({ search: 'applied' }).select();
                                    if (window.__sequencingReportSelection) {
                                        window.__sequencingReportSelection();
                                    }
                                }
                            """)
                        },
                        {
                            "text": "🔲 Deselect All Rows",
                            "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    dt.rows().deselect();
                                    Shiny.setInputValue('dt_selected_rows_sequencing', '[]');
                                }
                            """)
                        },
                        {'extend': "spacer",
                         'style': 'bar',
                         'text': 'View'},
                        {
                            "extend": "collection",
                            "text": "View selected",
                            "buttons": [
                                {
                                    "text": "🔬 Samples",
                                    "titleAttr": "View samples for the selected run rows.",
                                    "action": JavascriptFunction("""
                                        function(e, dt, node, config) {
                                            Shiny.setInputValue('view_run_samples', Math.random());
                                        }
                                    """)
                                },
                                {
                                    "text": "📁 Projects",
                                    "titleAttr": "View projects for the selected run rows.",
                                    "action": JavascriptFunction("""
                                        function(e, dt, node, config) {
                                            Shiny.setInputValue('view_run_projects', Math.random());
                                        }
                                    """)
                                }
                            ]
                        },
                        {'extend': "spacer",
                         'style': 'bar',
                         'text': 'Plots'},
                        {
                            "text": "📊 Run Plots",
                            "className": "seq-plot-toolbar-btn",
                            # Pure client-side show/hide: no Shiny round-trip, so the
                            # already-mounted figure keeps its state and toggling is instant.
                            "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    var panel = document.getElementById('seq-plot-panel');
                                    if (!panel) return;
                                    var open = !panel.open;
                                    panel.open = open;
                                    // `node` is a jQuery object here, not a DOM element.
                                    var btn = node && node.nodeType ? node : (node && node[0]);
                                    if (btn) btn.classList.toggle('active', open);

                                    // Opening/closing changes how much viewport is left
                                    // below, and nothing else tells the table to re-measure
                                    // (a class toggle fires no draw or resize event). Use
                                    // the table's own fit helper, which is zoom-aware.
                                    var refit = function() {
                                        if (window.__sequencingFitFn) window.__sequencingFitFn();
                                    };
                                    refit();
                                    setTimeout(refit, 250);

                                    if (!open) return;
                                    // Plotly lays out to zero size while hidden, so give it
                                    // a nudge once the panel actually has dimensions.
                                    var relayout = function() {
                                        var plot = panel.querySelector('.js-plotly-plot');
                                        if (plot && window.Plotly) window.Plotly.Plots.resize(plot);
                                    };
                                    relayout();
                                    setTimeout(relayout, 250);
                                }
                            """)
                        },
                        {'extend': "spacer",
                         'style': 'bar',
                         'text': 'Export'},
                        {
                            "extend": "collection",
                            "text": "Type",
                            "buttons": [
                                {
                                    "extend": "copyHtml5",
                                    "exportOptions": export_options(),
                                    "text": "Copy to Clipboard"
                                },
                                {
                                    "extend": "csvHtml5",
                                    "exportOptions": export_options(),
                                    "title": "Sequencing Data Export",
                                    "text": "Export to CSV"
                                },
                                {
                                    "extend": "excelHtml5",
                                    "exportOptions": export_options(),
                                    "title": "Sequencing Data Export",
                                    "text": "Export to Excel"
                                }
                            ]
                        },
                        {'extend': "spacer",
                         'style': 'bar'},
                      ],
                      order=[[column_index, "desc"]],
                      drawCallback=filter_state_draw_callback(
                          "sequencing",
                          report_row_state=True,
                          default_preset=DEFAULT_COLUMN_PRESET,
                      ),
                      columnDefs=preset_column_defs(DEFAULT_PRESET_COLUMNS, dat.columns) + [
                          {
                              'targets': comment_index,
                              'className': 'left-column',
                              'width': '800px',
                              'render': truncated_text_renderer(max_chars=250, max_width_px=800),
                          } if comment_index != -1 else {},
                          {"className": "dt-center", "targets": "_all"},
                          {"targets": run_number_index, "render": JavascriptFunction("function(data, type, row) { return type === 'display' ? Math.round(data).toString() : data; }")} if run_number_index != -1 else {},
                          {"targets": cluster_density_index, "render": JavascriptFunction("function(data, type, row) { return type === 'display' ? Math.round(data).toString() : data; }")} if cluster_density_index != -1 else {},
                          # Explicitly define the Seq Date column as a date type for searchBuilder
                          {
                              "targets": date_column_index,
                              "type": "date",
                              "render": DATE_VALUE_RENDERER
                          },
                          {
                              "targets": species_index,
                              "className": "left-column",
                              "width": "220px",
                              "render": truncated_text_renderer(max_chars=50, max_width_px=220),
                          } if species_index != -1 else {},
                          {
                              "targets": experiment_name_index,
                              "className": "left-column",
                              "width": "260px",
                              "render": truncated_text_renderer(max_chars=60, max_width_px=260),
                          } if experiment_name_index != -1 else {},
                      ] + searchbuilder_title_defs(dat.columns))

    def plot_height() -> int:
        """The figure height the user has dragged the panel to.

        Read non-reactively on purpose: the drag already relayouts the live
        figure client-side, so re-rendering here would rebuild the whole plot on
        every release for a result the browser has drawn. Isolated, the value is
        simply picked up by the next render the user actually asks for.
        """
        with reactive.isolate():
            try:
                raw = input.seq_plot_height()
            except Exception:
                raw = None
        return clamp_plot_height(raw)

    def _row_state_input(name: str) -> str | None:
        """Read one of the table's reported row-state inputs, or None if unset."""
        try:
            return getattr(input, name)()
        except Exception:
            return None

    def selected_row_indices() -> list[int] | None:
        """Return positional indices of the selected rows, or None if nothing is selected.

        Prefers the table's own report over the widget's ``selected_rows`` trait: the
        trait only covers rows currently in the DOM, so with deferRender + scroller it
        misses rows selected while scrolled out of view (e.g. by the
        "select all filtered rows" button).
        """
        reported = _row_state_input("dt_selected_rows_sequencing")
        if reported:
            try:
                indices = json.loads(reported)
            except (TypeError, ValueError):
                indices = None
            if isinstance(indices, list):
                return [i for i in indices if isinstance(i, int)] or None

        try:
            trait_selected = reactive_read(data_seq.widget, "selected_rows")
        except Exception:
            trait_selected = None
        return list(trait_selected) if trait_selected else None

    def get_selected_runs():
        """Return (seq_limsids, run_labels) for the currently selected run rows,
        or None when nothing is selected. Row indices are positional into the
        same dataframe passed to the widget (reset_index in ``data_seq``)."""
        selected = selected_row_indices()
        if not selected:
            return None

        dat = filtered_seq().reset_index(drop=True)
        if "seq_limsid" not in dat.columns:
            return None

        # Guard against a stale report referring to a since-shrunk dataset.
        rows = dat.iloc[[i for i in selected if 0 <= i < len(dat)]]
        seq_ids = set()
        for value in rows["seq_limsid"].dropna():
            seq_ids.update(_split_seq_limsids(value))
        if not seq_ids:
            return None

        run_labels = []
        if "Run ID" in rows.columns:
            run_labels = [
                str(v).strip() for v in rows["Run ID"].dropna() if str(v).strip()
            ]
        return seq_ids, run_labels

    @render_widget
    def seq_plot():
        dat = filtered_seq().copy().reset_index(drop=True)

        scope = input.seq_plot_scope()
        if scope == "selected":
            # Same source of truth as the "View selected" buttons: the table's own
            # report (the widget's selected_rows trait can't see rows scrolled out
            # of the DOM under deferRender + scroller), with the trait as fallback.
            # An empty selection says so rather than quietly plotting every run.
            selected = selected_row_indices()
            if not selected:
                return empty_plot_figure("Select runs in the table to plot them", plot_height())
            dat = dat.iloc[[i for i in selected if 0 <= i < len(dat)]]
        elif scope == "filtered":
            dat = apply_reported_rows(dat, _row_state_input("dt_filtered_rows_sequencing"))
        dat = exclude_phix_control_runs(dat)
        dat = dat.reset_index(drop=True)

        x_label = input.seq_plot_x()
        y_label = input.seq_plot_y()
        color_label = input.seq_plot_color() or None

        # Internal column names keep the frame valid when the same metric is picked
        # for more than one dimension; `labels` restores the display names.
        plot_df = pd.DataFrame({
            "_x": _plot_axis_series(dat, x_label),
            "_y": _plot_axis_series(dat, y_label),
        })
        axis_labels = {"_x": x_label, "_y": y_label}

        colorbar_overrides = None
        if color_label is not None:
            plot_df["_color"], colorbar_overrides = _plot_color_series(dat, color_label)
            axis_labels["_color"] = color_label
        if "Run ID" in dat.columns:
            plot_df["Run ID"] = dat["Run ID"]
        plot_df = plot_df.dropna(subset=["_x", "_y"])

        if plot_df.empty:
            return empty_plot_figure("No data available for the selected axes", plot_height())

        fig = px.scatter(
            plot_df,
            x="_x",
            y="_y",
            color="_color" if color_label is not None else None,
            labels=axis_labels,
            hover_data=["Run ID"] if "Run ID" in plot_df.columns else None,
        )
        if PLOT_METRICS[x_label]["kind"] == "date":
            fig.update_xaxes(type="date")
        if PLOT_METRICS[y_label]["kind"] == "date":
            fig.update_yaxes(type="date")
        if colorbar_overrides is not None:
            fig.update_layout(coloraxis_colorbar=colorbar_overrides)

        # The page applies a CSS zoom to counteract the app-wide zoom that otherwise
        # desyncs plotly's hit-testing from what's on screen (see .seq-plot-figure in
        # styles.css). That fixes hover accuracy, but plotly.js measures the x-axis
        # title's standoff via a DOM path outside the zoomed subtree, so the title
        # itself still renders using the *unzoomed* offset and lands inside the plot
        # area. A plain paper-relative annotation avoids that measurement path
        # entirely; the y-axis title doesn't share the bug, so it's left alone.
        fig.update_xaxes(title=None)
        fig.add_annotation(
            text=x_label,
            xref="paper",
            yref="paper",
            x=0.5,
            # Anchored to the plot area's bottom edge (paper y=0) and pushed clear of the
            # tick labels in absolute pixels. A fractional offset would scale with the
            # plot's height and fall outside the figure as the height grows.
            y=0,
            yshift=-32,
            xanchor="center",
            yanchor="top",
            showarrow=False,
            font=dict(size=12, color="#2a3f5f"),  # matches plotly's default axis-title color
        )

        if input.seq_plot_trendline() and supports_trendline(x_label, y_label):
            x_kind = PLOT_METRICS[x_label]["kind"]
            trend = linear_trendline(plot_df["_x"], plot_df["_y"], x_kind)
            if trend is not None:
                x_ends, y_ends, r_squared, slope = trend
                # Kept out of the legend: it would otherwise sit on top of a continuous
                # colourbar, which occupies the same top-right corner.
                fig.add_trace(
                    go.Scatter(
                        x=x_ends,
                        y=y_ends,
                        mode="lines",
                        name="Trend",
                        line=dict(color="#123a63", width=2, dash="dash"),
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )
                equation = trendline_equation_text(x_ends, y_ends, slope, x_kind)
                fig.add_annotation(
                    text=f"Trend R²={r_squared:.2f}<br>{equation}",
                    xref="paper",
                    yref="paper",
                    x=0.01,
                    y=0.99,
                    xanchor="left",
                    yanchor="top",
                    showarrow=False,
                    align="left",
                    font=dict(size=11, color="#123a63"),
                    bgcolor="rgba(255, 255, 255, 0.75)",
                    borderpad=3,
                )

        fig.update_layout(
            # Left/bottom margins must fit the tick labels *and* the axis titles (the
            # x-axis title is the annotation added above). The right margin has to clear
            # the legend or colourbar, which sit just outside the plot area.
            margin=dict(l=70, r=190 if color_label is not None else 20, t=30, b=70),
            legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
            # namelength=-1 keeps long Run IDs from being truncated in the hover label.
            hoverlabel=dict(namelength=-1),
            # Width is left to the widget's responsive sizing, so autosize stays on --
            # turning it off pins width to plotly's 700px default too.
            height=plot_height(),
        )
        return fig

    return {
        "get_selected_runs": get_selected_runs,
        "set_seq_filter": set_seq_filter,
    }
