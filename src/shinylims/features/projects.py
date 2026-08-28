'''
projects.py - Table module containing UI and server logic for the Projects table tab
'''

import json

from shiny import ui, reactive, render
from shinywidgets import output_widget, render_widget, reactive_read
from itables.widget import ITable
from itables.javascript import JavascriptFunction
import pandas as pd

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
    select_all_columns_button,
)


##############################
# UI: PROJECT TABLE          #
##############################

def projects_ui():
    """Define UI for the Projects tab."""
    return ui.div(
        clear_all_filters_script("projects"),
        ui.output_ui("filter_status_bar_projects"),
        output_widget("projects_table", fillable=False),
    )


##############################
# SERVER: PROJECT TABLE      #
##############################

def projects_server(projects_df, input):
    """Render the Projects table as an interactive ITable widget."""

    project_filter_ids = reactive.Value(None)
    project_filter_label = reactive.Value(None)
    project_filter_source = reactive.Value("run")

    @reactive.Calc
    def filtered_projects():
        df = projects_df().copy().reset_index(drop=True)
        ids = project_filter_ids.get()
        if ids and "Project LIMS ID" in df.columns:
            df = df[df["Project LIMS ID"].astype(str).isin(ids)].reset_index(drop=True)
        return df

    @render.ui
    def filter_status_bar_projects():
        extra = []
        ids = project_filter_ids.get()
        if ids:
            df = projects_df()
            matched = (
                df["Project LIMS ID"].astype(str).isin(ids).sum()
                if "Project LIMS ID" in df.columns
                else 0
            )
            label = project_filter_label.get()
            source = project_filter_source.get()
            source_label = {
                "run": "runs",
                "sample": "samples",
            }.get(source, source)
            selection_desc = f" ({label})" if label else ""
            extra.append(
                f"Related projects from selected {source_label}{selection_desc}: "
                f"{matched} projects"
            )

        try:
            raw = input.dt_filter_state_projects()
        except Exception:
            raw = None
        return build_filter_status_bar("projects", raw, extra_lines=extra)

    @reactive.Effect
    @reactive.event(input.clear_all_filters_projects)
    def _clear_all_filters():
        project_filter_ids.set(None)
        project_filter_label.set(None)
        project_filter_source.set("run")

    def set_project_filter(
        project_ids,
        label: str | None = None,
        source: str = "run",
    ) -> None:
        """Filter the Projects table to selected project LIMS IDs."""
        project_filter_ids.set(
            {
                str(project_id).strip()
                for project_id in project_ids
                if str(project_id).strip()
            }
            or None
        )
        project_filter_label.set(label)
        project_filter_source.set(source)

    def get_selected_projects(raw_selection):
        """Return project IDs and labels for the selected project rows."""
        selected = None
        payload_valid = False
        try:
            payload = json.loads(raw_selection) if raw_selection else None
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            selected = [
                index for index in payload["rows"]
                if isinstance(index, int)
            ]
            payload_valid = True

        if not payload_valid:
            try:
                selected = list(
                    reactive_read(projects_table.widget, "selected_rows")
                )
            except Exception:
                selected = None
        if not selected:
            return None

        dat = filtered_projects().reset_index(drop=True)
        valid = [index for index in selected if 0 <= index < len(dat)]
        if not valid:
            return None
        rows = dat.iloc[valid]
        if "Project LIMS ID" not in rows.columns:
            return None

        project_ids = {
            str(value).strip()
            for value in rows["Project LIMS ID"].dropna()
            if str(value).strip()
        }
        labels = [
            str(value).strip()
            for value in rows.get("Project Name", pd.Series(dtype=object)).dropna()
            if str(value).strip()
        ]
        return (project_ids, labels) if project_ids else None

    @render_widget
    def projects_table():
        dat = filtered_projects()

        # Format date column for DataTables display
        if "Open Date" in dat.columns:
            dat["Open Date"] = dat["Open Date"].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ""
            )

        # Determine column indices for ordering and formatting
        comment_index = dat.columns.get_loc("Comment") if "Comment" in dat.columns else -1
        project_name_index = dat.columns.get_loc("Project Name") if "Project Name" in dat.columns else -1
        samples_index = dat.columns.get_loc("Samples") if "Samples" in dat.columns else -1
        species_index = dat.columns.get_loc("Species") if "Species" in dat.columns else -1
        status_index = dat.columns.get_loc("Status") if "Status" in dat.columns else -1
        order_column_index = dat.columns.get_loc("Open Date") if "Open Date" in dat.columns else 0
        date_column_index = order_column_index if "Open Date" in dat.columns else -1

        return ITable(
            dat,
            select=True,
            layout={"topStart": "buttons", "topEnd": "search", "bottomEnd": None},
            column_filters="header",
            search={"smart": True, "regex": True, "caseInsensitive": True},
            lengthMenu=[[200, 500, 1000, 2000, -1], [200, 500, 1000, 2000, "All"]],
            classes="compact hover order-column cell-border",
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
                {"extend": "spacer", "style": "bar", "text": "Columns"},
                {
                    "extend": "colvis",
                    "text": "Selection",
                    "collectionLayout": "two-column",
                    "columnText": COLVIS_COLUMN_TEXT,
                },
                {
                    "extend": "collection",
                    "text": "Presets",
                    "buttons": [
                        select_all_columns_button(),
                        deselect_all_columns_button(),
                    ],
                },
                {"extend": "spacer", "style": "bar", "text": "Filter"},
                {"extend": "searchBuilder"},
                {
                    "text": "☑️ Select All Filtered Rows",
                    "action": JavascriptFunction("""
                        function(e, dt, node, config) {
                            // Replace selection (don't accumulate)
                            dt.rows().deselect();
                            dt.rows({ search: 'applied' }).select();
                        }
                    """)
                },
                {
                    "text": "🔲 Deselect All Rows",
                    "action": JavascriptFunction("""
                        function(e, dt, node, config) {
                            dt.rows().deselect();
                        }
                    """)
                },
                {"extend": "spacer", "style": "bar", "text": "View"},
                {
                    "extend": "collection",
                    "text": "View selected",
                    "buttons": [
                        {
                            "text": "🔬 Samples",
                            "titleAttr": "View samples for the selected project rows.",
                            "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    Shiny.setInputValue(
                                        'view_project_samples',
                                        JSON.stringify({
                                            rows: dt.rows({selected: true}).indexes().toArray(),
                                            nonce: Math.random()
                                        }),
                                        {priority: 'event'}
                                    );
                                }
                            """)
                        },
                        {
                            "text": "🧬 Sequencing runs",
                            "titleAttr": "View sequencing runs for the selected project rows.",
                            "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    Shiny.setInputValue(
                                        'view_project_runs',
                                        JSON.stringify({
                                            rows: dt.rows({selected: true}).indexes().toArray(),
                                            nonce: Math.random()
                                        }),
                                        {priority: 'event'}
                                    );
                                }
                            """)
                        }
                    ]
                },
                {"extend": "spacer", "style": "bar", "text": "Export"},
                {
                    "extend": "collection",
                    "text": "Type",
                    "buttons": [
                        {
                            "extend": "copyHtml5",
                            "exportOptions": export_options(),
                            "text": "Copy to Clipboard",
                        },
                        {
                            "extend": "csvHtml5",
                            "exportOptions": export_options(),
                            "text": "Export to CSV",
                            "title": "Project Data Export - Full",
                        },
                        {
                            "extend": "excelHtml5",
                            "exportOptions": export_options(),
                            "text": "Export to Excel",
                            "title": "Project Data Export",
                        },
                    ],
                },
                {"extend": "spacer", "style": "bar"},
            ],
            order=[[order_column_index, "desc"]],
            drawCallback=filter_state_draw_callback("projects"),
            columnDefs=[
                {
                    "targets": comment_index,
                    "className": "left-column",
                    "width": "420px",
                    "render": JavascriptFunction("""
                        function(data, type, row) {
                            if (data == null || data === '') {
                                return '';
                            }

                            const div = document.createElement('div');
                            div.innerHTML = String(data);
                            const fullText = (div.textContent || div.innerText || '')
                                .replace(/\\s+/g, ' ')
                                .trim();

                            if (type === 'sort' || type === 'type' || type === 'filter') {
                                return fullText;
                            }

                            const preview = fullText.length > 120
                                ? fullText.slice(0, 117) + '...'
                                : fullText;

                            const escapeHtml = (value) => String(value)
                                .replace(/&/g, '&amp;')
                                .replace(/</g, '&lt;')
                                .replace(/>/g, '&gt;')
                                .replace(/"/g, '&quot;')
                                .replace(/'/g, '&#39;');

                            return (
                                '<div title="' + escapeHtml(fullText) + '"' +
                                ' style="max-width: 420px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">' +
                                escapeHtml(preview) +
                                '</div>'
                            );
                        }
                    """),
                } if comment_index != -1 else {},
                {"targets": project_name_index, "width": "360px"} if project_name_index != -1 else {},
                {"targets": samples_index, "width": "50px"} if samples_index != -1 else {},
                {"targets": species_index, "width": "180px"} if species_index != -1 else {},
                {"targets": status_index, "width": "110px"} if status_index != -1 else {},
                {"className": "dt-center", "targets": "_all"},
                {
                    "targets": date_column_index,
                    "type": "date",
                    "render": DATE_VALUE_RENDERER,
                } if date_column_index != -1 else {},
            ] + searchbuilder_title_defs(dat.columns),
        )

    return {
        "set_project_filter": set_project_filter,
        "get_selected_projects": get_selected_projects,
    }
