"""Shared DataTables toolbar controls used across metadata tables."""

import json

from shiny import ui
from itables.javascript import JavascriptFunction


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
    """Return a drawCallback that stores the DT API on ``window`` and reports
    the current filter state to the Shiny server via ``dt_filter_state_<table_key>``."""
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
                lines.append("SearchBuilder active")
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
