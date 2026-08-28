"""Shared DataTables toolbar controls used across metadata tables."""

import json

from shiny import ui
from itables.javascript import JavascriptFunction


FILTER_BUILDER_LANGUAGE = {
    "searchBuilder": {
        "button": {"0": "Filter Builder", "_": "Filter Builder (%d)"},
        "title": {"0": "Custom Filter Builder", "_": "Custom Filter Builder (%d)"},
    }
}


# With column_filters="header", itables replaces each column's title <span>
# with a filter <input>, so the default column.title() the colvis button
# reads from is that input's markup, not the column name -- leaving every
# entry in the "Selection" dropdown blank. Reconstruct the real name from
# the input's placeholder instead.
COLVIS_COLUMN_TEXT = JavascriptFunction(
    """
    function(dt, idx, title) {
        var th = dt.column(idx).header();
        var input = th ? th.querySelector('.dt-column-title input') : null;
        return input ? input.placeholder : title;
    }
    """
)


def searchbuilder_title_defs(columns):
    """With column_filters="header", SearchBuilder's "Data" field list hits
    the same broken title lookup COLVIS_COLUMN_TEXT works around above: it
    reads each column's derived title (now `<input placeholder=...>`
    markup) and strips HTML tags from it, leaving an empty string for a
    void element like <input> -- so every "Data" option renders with no
    text at all (still selectable, just blank). SearchBuilder honors a
    per-column `searchBuilderTitle` override ahead of that broken title,
    so set it explicitly to the real column name for every column.
    """
    return [
        {"targets": idx, "searchBuilderTitle": str(col)}
        for idx, col in enumerate(columns)
    ]


# The export buttons hit the same broken title lookup a third time: DataTables
# builds the exported header row from column().title(), which is the *inner
# HTML* of the header's .dt-column-title -- with column_filters="header" that
# is the filter <input> -- and the default header formatter strips the tags
# from it, so every exported column header comes out blank. Recover the real
# name from the input's placeholder, and fall back to the title's own text for
# columns that carry no filter input.
EXPORT_HEADER_FORMAT = JavascriptFunction(
    """
    function(data, columnIdx, node) {
        var input = node ? node.querySelector('.dt-column-title input') : null;
        if (input && input.placeholder) {
            return input.placeholder;
        }
        var div = document.createElement('div');
        div.innerHTML = data == null ? '' : String(data);
        return (div.textContent || div.innerText || '').trim();
    }
    """
)


def export_options(*, columns: str = ":visible") -> dict[str, object]:
    """Return the exportOptions for an export button (CSV/Excel/copy).

    Always go through this rather than a bare {"columns": ...} so exports keep
    their column headers -- see EXPORT_HEADER_FORMAT above.
    """
    return {
        "columns": columns,
        "format": {"header": EXPORT_HEADER_FORMAT},
    }


def _preset_storage_key_js(table_key: str) -> str:
    """The sessionStorage key holding a table's active preset name, as a JS literal.

    Kept in sessionStorage beside the table's own DataTables state (see
    ``stateSaveCallback`` at the call sites) so the two are always cleared
    together: a tab that has forgotten its column visibility must not still
    claim a preset is applied.
    """
    return json.dumps(f"shinylims_{table_key}_preset")


COLUMN_VISIBILITY_SELECT_ALL_ACTION = JavascriptFunction(
    """
    function(e, dt, node, config) {
        dt.columns().visible(true);
    }
    """
)


COLUMN_VISIBILITY_DESELECT_ALL_ACTION = JavascriptFunction(
    """
    function(e, dt, node, config) {
        dt.columns().visible(false);
    }
    """
)


DATE_VALUE_RENDERER = JavascriptFunction(
    """
    function(data, type, row) {
        if (type === 'sort' || type === 'type' || type === 'filter') {
            if (!data || data === '') {
                return null;
            }
            return data;
        }
        return data;
    }
    """
)


def truncated_text_renderer(*, max_chars: int = 120, max_width_px: int = 300) -> JavascriptFunction:
    """Return a render function that shows a single-line, ellipsis-truncated
    preview of a (possibly HTML-containing) cell value, with the full text
    available via a hover tooltip. Keeps sort/filter/search operating on the
    untruncated text."""
    return JavascriptFunction(f"""
        function(data, type, row) {{
            if (data == null || data === '') {{
                return '';
            }}

            const div = document.createElement('div');
            div.innerHTML = String(data);
            const fullText = (div.textContent || div.innerText || '')
                .replace(/\\s+/g, ' ')
                .trim();

            if (type === 'sort' || type === 'type' || type === 'filter') {{
                return fullText;
            }}

            const preview = fullText.length > {max_chars}
                ? fullText.slice(0, {max_chars - 3}) + '...'
                : fullText;

            const escapeHtml = (value) => String(value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');

            return (
                '<div title="' + escapeHtml(fullText) + '"' +
                ' style="max-width: {max_width_px}px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">' +
                escapeHtml(preview) +
                '</div>'
            );
        }}
    """)


def select_all_columns_button(*, text: str = "Select All") -> dict[str, object]:
    """Return a DataTables button config that shows every column."""
    return {
        "text": text,
        "action": COLUMN_VISIBILITY_SELECT_ALL_ACTION,
    }


def deselect_all_columns_button(*, text: str = "Deselect All") -> dict[str, object]:
    """Return a DataTables button config that hides every column."""
    return {
        "text": text,
        "action": COLUMN_VISIBILITY_DESELECT_ALL_ACTION,
    }


def visibility_preset_button(
    columns: list[int] | list[str],
    all_columns=None,
    *,
    text: str,
    table_key: str | None = None,
) -> dict[str, object]:
    """Return a DataTables button config that applies a column visibility preset.

    ``columns`` is either raw DataTables column indexes or, when ``all_columns``
    (the dataframe's column names, in table order) is passed, column *names*
    resolved against it. Prefer the name form: the indexes shift whenever a
    column is added to or removed from the query that builds the table, and a
    stale index silently reveals the wrong column. A name that isn't in
    ``all_columns`` is dropped from the preset instead.

    With ``table_key`` the button also records itself as that table's active
    preset, which ``filter_state_draw_callback`` reflects on the toolbar -- a
    preset hides most of the table, so it has to be visible that one is on.
    """
    visible_indexes = resolve_preset_columns(columns, all_columns)
    visible_columns_js = "\n".join(
        f"                    dt.column({column_index}).visible(true);"
        for column_index in visible_indexes
    )

    # Applying a preset moves every column at once, which fires as many
    # `column-visibility` events -- the same event the draw callback watches to
    # notice the user overriding a preset by hand. Flag the bulk change so it
    # doesn't immediately clear the preset it is applying.
    if table_key:
        track_js = f"""                try {{
                    sessionStorage.setItem({_preset_storage_key_js(table_key)}, {json.dumps(text)});
                }} catch (err) {{}}
                if (window.__{table_key}SyncPreset) window.__{table_key}SyncPreset();
"""
        flag = f"window.__{table_key}PresetApplying"
    else:
        track_js = ""
        flag = "window.__presetApplying"

    return {
        "text": text,
        "action": JavascriptFunction(
            f"""
            function(e, dt, node, config) {{
                {flag} = true;
                try {{
                    dt.columns().visible(false);
{visible_columns_js}
                }} finally {{
                    {flag} = false;
                }}
{track_js}            }}
            """
        ),
    }


def resolve_preset_columns(
    columns: list[int] | list[str],
    all_columns=None,
) -> list[int]:
    """Return the DataTables column indexes a preset covers (see
    ``visibility_preset_button`` for how ``columns`` is interpreted)."""
    if all_columns is None:
        return list(columns)

    name_to_index = {str(name): idx for idx, name in enumerate(all_columns)}
    resolved = [
        column if isinstance(column, int) else name_to_index.get(str(column))
        for column in columns
    ]
    return [idx for idx in resolved if idx is not None]


def preset_column_defs(
    columns: list[int] | list[str],
    all_columns,
) -> list[dict[str, object]]:
    """Return ``columnDefs`` entries that start the table on a preset, by hiding
    every column the preset doesn't list.

    Only applies on a first visit: ``stateSave`` restores the visitor's own
    column visibility over the init config, so this is the default rather than
    something that overrides a returning user's choice.
    """
    visible = set(resolve_preset_columns(columns, all_columns))
    hidden = [idx for idx in range(len(all_columns)) if idx not in visible]
    if not hidden:
        return []
    return [{"targets": hidden, "visible": False}]


def batch_filter_button(*, text: str = "Batch Filter") -> dict[str, object]:
    """Return a DataTables button that opens a Shiny-side batch filter modal."""
    return {
        "text": text,
        "action": JavascriptFunction("""
            function(e, dt, node, config) {
                Shiny.setInputValue('batch_filter_open', Math.random());
            }
        """),
    }


def filter_state_draw_callback(
    table_key: str,
    *,
    report_row_state: bool = False,
    default_preset: str | None = None,
) -> JavascriptFunction:
    """Return a drawCallback that stores the DT API on ``window``, reports
    the current filter state to the Shiny server via ``dt_filter_state_<table_key>``,
    and fits the table's scroll body to the remaining browser viewport height
    (instead of a fixed vh value) on first render and on window resize.

    With ``report_row_state`` the positional indices of the rows surviving the
    current filters are also reported, via ``dt_filtered_rows_<table_key>``, and
    the indices of the selected rows via ``dt_selected_rows_<table_key>`` (kept
    current by a ``select``/``deselect`` handler bound here). Both index the same
    dataframe handed to the widget, so the server can subset it directly. This is
    opt-in because the filtered report sends one index per row on every redraw.

    It also defines ``window.__<table_key>ReportSelection()``, so a button whose
    action changes the selection programmatically can push the new selection
    without waiting for a redraw.

    It keeps the column-preset indicator current too: the ``.dt-preset-menu``
    toolbar button is labelled with the active preset and marked
    ``.dt-preset-active``, and any hand-made column visibility change clears it,
    so the toolbar never claims a preset the columns no longer match.
    ``default_preset`` names the preset the table starts on (paired with
    ``preset_column_defs``), shown until the visitor picks another or overrides
    the columns themselves.
    """
    # Read straight off the raw settings object rather than through the DataTables
    # API, which may be unreachable via the page-level `$` (see the jQuery note in
    # the callback below). `aiDisplay` holds exactly the post-filter, pre-paging row
    # indices we want, with the API kept as a fallback in case a future DataTables
    # release renames it.
    row_state_js = (
        f"""
            var filteredIdx = null;
            if (settings && settings.aiDisplay) {{
                filteredIdx = Array.prototype.slice.call(settings.aiDisplay);
            }} else {{
                try {{
                    filteredIdx = new $.fn.dataTable.Api(settings)
                        .rows({{ search: 'applied' }}).indexes().toArray();
                }} catch (e) {{}}
            }}
            if (filteredIdx) {{
                Shiny.setInputValue(
                    'dt_filtered_rows_{table_key}',
                    JSON.stringify(filteredIdx)
                );
            }}
        """
        if report_row_state
        else ""
    )
    # Selection has to be reported by the table too: the widget's own
    # `selected_rows` trait only sees rows currently in the DOM, and with
    # deferRender + scroller most selected rows are scrolled out of it. Bound
    # here (rather than in a button's action) so plain row clicks report as well,
    # and guarded on `settings` rather than `window` so a remount of the widget
    # re-binds against the live table instead of keeping a closure over the
    # detached one.
    selection_js = (
        f"""
            window.__{table_key}ReportSelection = function() {{
                Shiny.setInputValue(
                    'dt_selected_rows_{table_key}',
                    JSON.stringify(dt.rows({{ selected: true }}).indexes().toArray())
                );
            }};
            if (!settings.__selectionBound) {{
                settings.__selectionBound = true;
                dt.on('select deselect', function() {{
                    window.__{table_key}ReportSelection();
                }});
                // Report once up front so an empty selection reads as "nothing
                // selected" on the server instead of "the table hasn't reported yet".
                window.__{table_key}ReportSelection();
            }}
        """
        if report_row_state
        else ""
    )
    # The preset buttons only change column visibility client-side, so nothing
    # else on the page knows one is applied. Paint the toolbar from the stored
    # name on every draw (covering a remount, which rebuilds the buttons), and
    # drop the label the moment the user changes a column by hand -- an
    # indicator that can go stale is worse than none.
    preset_js = f"""
            window.__{table_key}SyncPreset = function() {{
                if (!container) return;
                var menuBtn = container.querySelector('.dt-preset-menu');
                var selectionBtn = container.querySelector('.dt-selection-menu');
                if (!menuBtn && !selectionBtn) return;
                var active = null;
                try {{
                    active = sessionStorage.getItem({_preset_storage_key_js(table_key)});
                }} catch (err) {{}}
                // `null` is a first visit, which lands on the default preset via
                // preset_column_defs; `''` is the user having overridden it, i.e.
                // a column selection of their own.
                if (active === null) active = {json.dumps(default_preset or "")};
                if (menuBtn) {{
                    var label = menuBtn.querySelector('span') || menuBtn;
                    label.textContent = active ? 'Presets: ' + active : 'Presets';
                    menuBtn.classList.toggle('dt-preset-active', !!active);
                }}
                // The two menus are alternatives: whenever the columns are not
                // matching a preset, they are a hand-made selection, so the
                // Selection menu carries the indicator instead.
                if (selectionBtn) {{
                    var selLabel = selectionBtn.querySelector('span') || selectionBtn;
                    selLabel.textContent = active ? 'Selection' : 'Selection: Custom';
                    selectionBtn.classList.toggle('dt-selection-custom', !active);
                }}
            }};
            if (!settings.__presetBound) {{
                settings.__presetBound = true;
                dt.on('column-visibility', function() {{
                    if (window.__{table_key}PresetApplying) return;
                    // A table with neither menu has no indicator to keep honest.
                    if (!container) return;
                    if (!container.querySelector('.dt-preset-menu')
                        && !container.querySelector('.dt-selection-menu')) return;
                    try {{
                        sessionStorage.setItem({_preset_storage_key_js(table_key)}, '');
                    }} catch (err) {{}}
                    window.__{table_key}SyncPreset();
                }});
            }}
            window.__{table_key}SyncPreset();
    """
    return JavascriptFunction(f"""
        function(settings) {{
{row_state_js}
            // Everything below deliberately avoids the page-level `$`. Shiny loads
            // jQuery 3.6 while itables' bundle loads jQuery 4 with DataTables
            // registered on it, and whichever wins `window.$` is a load-order race.
            // When Shiny's copy wins there is no `$.fn.dataTable`, so reaching for
            // the API here used to throw and abandon the rest of this callback --
            // leaving the table at its raw `scrollY` (which the app's `zoom: 0.8`
            // then shrinks by a fifth) and never exposing the API below.
            var container = settings.nTableWrapper
                || (settings.nTable && settings.nTable.closest('.dt-container'));

            // Fit the scroll body to the remaining viewport height rather than a
            // fixed vh value. Bound to the DT `settings` object (not `window`) so a
            // remount of the widget (e.g. switching tabs and back) gets a fresh fit
            // instead of silently reusing a stale one.
            var MIN_HEIGHT = 240;
            function fitScrollHeight() {{
                var scrollBody = container && container.querySelector('.dt-scroll-body');
                if (!scrollBody) return;
                // getBoundingClientRect/innerHeight both reflect true screen pixels,
                // but style.height is set in the element's own local (pre-scale)
                // coordinate space, so divide out any ancestor CSS transform or zoom
                // (e.g. the desktop `zoom: 0.8` app-shell rule) to land on the
                // intended on-screen size.
                var scale = 1;
                var probe = scrollBody;
                while (probe) {{
                    var cs = getComputedStyle(probe);
                    var t = cs.transform;
                    if (t && t !== 'none') {{
                        var m = t.match(/matrix\\(([^,]+),/);
                        if (m) scale *= parseFloat(m[1]);
                    }}
                    var z = parseFloat(cs.zoom);
                    if (!isNaN(z) && z > 0) scale *= z;
                    probe = probe.parentElement;
                }}
                var top = scrollBody.getBoundingClientRect().top;
                // Measure how much true-screen space is actually used below the
                // scroll body (the info-text row, any container/shell padding
                // after it, etc.) directly from the live layout instead of
                // guessing a fixed pixel constant that silently goes stale
                // whenever the surrounding toolbar/chrome changes. Resizing the
                // scroll body shifts this trailing content in lockstep, so its
                // own height stays constant regardless of what we set below.
                var trailingSpace = document.body.getBoundingClientRect().bottom
                    - scrollBody.getBoundingClientRect().bottom;
                var available = (window.innerHeight - top - trailingSpace) / scale;
                var height = Math.max(available, MIN_HEIGHT);
                scrollBody.style.height = height + 'px';
                scrollBody.style.maxHeight = height + 'px';
            }}
            window.__{table_key}FitFn = fitScrollHeight;

            if (!settings.__fitInitDone) {{
                settings.__fitInitDone = true;
                fitScrollHeight();
                setTimeout(fitScrollHeight, 150);

                // The toolbar row (buttons/search) can wrap to a second line
                // depending on window width and button count, which changes how
                // much vertical space is left -- independent of any window
                // resize event. Watch it directly so the table stays correctly
                // sized instead of relying only on the resize listener below.
                var toolbarRow = container
                    && container.querySelector('.dt-layout-row:not(.dt-layout-table)');
                if (toolbarRow && window.ResizeObserver) {{
                    new ResizeObserver(function() {{ fitScrollHeight(); }}).observe(toolbarRow);
                }}
            }}

            if (!window.__{table_key}ResizeBound) {{
                window.__{table_key}ResizeBound = true;
                var resizeTimer;
                window.addEventListener('resize', function() {{
                    clearTimeout(resizeTimer);
                    resizeTimer = setTimeout(function() {{
                        if (window.__{table_key}FitFn) window.__{table_key}FitFn();
                    }}, 120);
                }});
            }}

            // `settings.oInstance` is a jQuery object built by whichever jQuery
            // DataTables actually registered itself on, so `.api()` resolves even when
            // the page-level `$` is the other copy. Kept last and non-fatal: if it ever
            // fails, the sizing above has already happened and a later draw retries.
            var dt = null;
            try {{
                if (settings.oInstance && typeof settings.oInstance.api === 'function') {{
                    dt = settings.oInstance.api();
                }} else if (window.$ && window.$.fn && window.$.fn.dataTable) {{
                    dt = new window.$.fn.dataTable.Api(settings);
                }}
            }} catch (e) {{}}
            if (!dt) return;

            window.__{table_key}DT = dt;

{selection_js}{preset_js}
            var globalSearch = dt.search() || '';
            var colFilterCount = 0;
            dt.columns().every(function() {{
                if (this.search()) colFilterCount++;
            }});
            var hasSB = false;
            try {{
                var groups = dt.searchBuilder.getDetails();
                if (groups && groups.criteria && groups.criteria.length > 0) hasSB = true;
            }} catch(e) {{}}
            var state = JSON.stringify({{
                global_search: globalSearch,
                column_filter_count: colFilterCount,
                has_search_builder: hasSB
            }});
            Shiny.setInputValue('dt_filter_state_{table_key}', state);
        }}
    """)


def clear_all_filters_script(table_key: str) -> ui.Tag:
    """Return a ``<script>`` tag defining a global JS function that clears all
    DataTables filters and the Python-side batch filter for the given table."""
    return ui.tags.script(f"""
        function clearAll_{table_key}_Filters() {{
            var dt = window.__{table_key}DT;
            if (dt) {{
                try {{
                    var container = dt.table().container();

                    dt.search('');
                    dt.columns().search('');

                    container.querySelectorAll('.dt-search input, .dataTables_filter input')
                        .forEach(function(el) {{ el.value = ''; }});
                    container.querySelectorAll('thead input, tfoot input, thead select, tfoot select')
                        .forEach(function(el) {{
                            if (el.tagName === 'SELECT') {{ el.selectedIndex = 0; return; }}
                            el.value = '';
                        }});

                    var sbCleared = false;
                    try {{
                        var clearBtn = dt.searchBuilder.container().find('button.dtsb-clearAll');
                        if (clearBtn.length) {{ clearBtn.trigger('click'); sbCleared = true; }}
                    }} catch(e) {{}}

                    if (!sbCleared) dt.draw();
                }} catch(e) {{}}
            }}

            Shiny.setInputValue('clear_all_filters_{table_key}', Math.random());
        }}
    """)


def build_filter_status_bar(
    table_key: str,
    dt_filter_state_raw: str | None,
    *,
    extra_lines: list[str] | None = None,
) -> ui.Tag | None:
    """Return a status bar div with badges for each active filter, or ``None``
    when no filters are active.  ``extra_lines`` allows the caller to prepend
    additional badges (e.g. for a batch filter)."""
    lines: list[str] = list(extra_lines or [])

    try:
        if dt_filter_state_raw:
            state = json.loads(dt_filter_state_raw)
            if state.get("global_search"):
                lines.append(f"Search: \"{state['global_search']}\"")
            n = state.get("column_filter_count", 0)
            if n > 0:
                lines.append(f"Column filters: {n} active")
            if state.get("has_search_builder"):
                lines.append("Filter Builder active")
    except Exception:
        pass

    if not lines:
        return None

    badges = [
        ui.span(line, class_="badge text-bg-info", style="font-size: 0.85rem;")
        for line in lines
    ]

    return ui.div(
        *badges,
        ui.tags.button(
            "Clear All Filters",
            class_="btn btn-outline-secondary btn-sm",
            onclick=f"clearAll_{table_key}_Filters();",
        ),
        style="padding: 6px 0; display: flex; align-items: center; flex-wrap: wrap; gap: 6px;",
    )
