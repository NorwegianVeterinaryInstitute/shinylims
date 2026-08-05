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
    visible_indexes: list[int],
    *,
    text: str = "Minimal View",
) -> dict[str, object]:
    """Return a DataTables button config that applies a column visibility preset."""
    visible_columns_js = "\n".join(
        f"        dt.column({column_index}).visible(true);"
        for column_index in visible_indexes
    )
    return {
        "text": text,
        "action": JavascriptFunction(
            f"""
            function(e, dt, node, config) {{
                dt.columns().visible(false);
{visible_columns_js}
            }}
            """
        ),
    }


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


def filter_state_draw_callback(table_key: str) -> JavascriptFunction:
    """Return a drawCallback that stores the DT API on ``window``, reports
    the current filter state to the Shiny server via ``dt_filter_state_<table_key>``,
    and fits the table's scroll body to the remaining browser viewport height
    (instead of a fixed vh value) on first render and on window resize."""
    return JavascriptFunction(f"""
        function(settings) {{
            var dt = new $.fn.dataTable.Api(settings);
            window.__{table_key}DT = dt;
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

            // Fit the scroll body to the remaining viewport height rather than a
            // fixed vh value. Bound to the DT `settings` object (not `window`) so a
            // remount of the widget (e.g. switching tabs and back) gets a fresh fit
            // instead of silently reusing a stale one.
            var MIN_HEIGHT = 240;
            function fitScrollHeight() {{
                var scrollBody = dt.table().container().querySelector('.dt-scroll-body');
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
                var toolbarRow = dt.table().container().querySelector('.dt-layout-row:not(.dt-layout-table)');
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
