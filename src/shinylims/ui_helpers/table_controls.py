"""Shared DataTables toolbar controls used across metadata tables."""

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


CLEAR_ALL_FILTERS_ACTION = JavascriptFunction(
    """
    function(e, dt, node, config) {
        const tableContainer = dt.table().container();

        dt.search('');
        dt.columns().search('');

        tableContainer
            .querySelectorAll('.dt-search input, .dataTables_filter input')
            .forEach(function(input) {
                input.value = '';
            });

        tableContainer
            .querySelectorAll('thead input, tfoot input, thead select, tfoot select')
            .forEach(function(input) {
                if (input.tagName === 'SELECT') {
                    input.selectedIndex = 0;
                    return;
                }

                input.value = '';
            });

        try {
            const builderContainer = dt.searchBuilder.container();
            const clearButton = builderContainer.find('button.dtsb-clearAll');

            if (clearButton.length) {
                clearButton.trigger('click');
                return;
            }
        } catch (error) {
            // SearchBuilder may not be initialized yet; ignore and keep clearing basic searches.
        }

        dt.draw();
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


def clear_all_filters_button(*, text: str = "Clear Search & Filters") -> dict[str, object]:
    """Return a DataTables button config that clears all active filtering UI."""
    return {
        "text": text,
        "action": CLEAR_ALL_FILTERS_ACTION,
    }
