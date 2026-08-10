'''
sequencing.py - table module containing UI and server logic for the Sequencing table tab
'''

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
    filter_state_draw_callback,
    select_all_columns_button,
    truncated_text_renderer,
    visibility_preset_button,
)


##############################
# UI ILMN SEQ TABLE
##############################

def seq_ui():
    return ui.div(
        clear_all_filters_script("sequencing"),
        ui.div(
            ui.input_action_button(
                "view_run_samples",
                "View samples for selected run",
                class_="btn btn-outline-primary btn-sm",
            ),
            ui.span(
                "Select one or more run rows, then view their samples.",
                class_="text-muted",
                style="margin-left: 10px; font-size: 0.85rem;",
            ),
            class_="mb-2 d-flex align-items-center",
        ),
        ui.output_ui("filter_status_bar_sequencing"),
        output_widget("data_seq", fillable=False),
    )

##############################
# SERVER ILMN SEQ TABLE
##############################

# Server logic for the Sequencing page
def seq_server(seq_df, input):

    @render.ui
    def filter_status_bar_sequencing():
        try:
            raw = input.dt_filter_state_sequencing()
        except Exception:
            raw = None
        return build_filter_status_bar("sequencing", raw)

    # Return HTML tag with DT table element
    @render_widget
    def data_seq():
        dat = seq_df().copy().reset_index(drop=True)

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
                            "collectionLayout": "two-column",
                            "columnText": COLVIS_COLUMN_TEXT,
                        },
                        # Button to select specific columns presets
                        {
                        "extend": "collection",
                        "text": "Presets",
                        "buttons": [
                            select_all_columns_button(),
                            deselect_all_columns_button(),
                            visibility_preset_button([2, 3, 4, 5, 9, 10, 21])
                        ]
                    },
                        {'extend': "spacer",
                         'style': 'bar',
                         'text': 'Filter'},
                        {"extend": "searchBuilder"},
                        {'extend': "spacer",
                         'style': 'bar',
                         'text': 'Export'},
                        {
                            "extend": "collection",
                            "text": "Type",
                            "buttons": [
                                {
                                    "extend": "copyHtml5",
                                    "exportOptions": {"columns": ":visible"},
                                    "text": "Copy to Clipboard"
                                },
                                {
                                    "extend": "csvHtml5",
                                    "exportOptions": {"columns": ":visible"},
                                    "title": "Sequencing Data Export",
                                    "text": "Export to CSV"
                                },
                                {
                                    "extend": "excelHtml5",
                                    "exportOptions": {"columns": ":visible"},
                                    "title": "Sequencing Data Export",
                                    "text": "Export to Excel"
                                }
                            ]
                        },
                        {'extend': "spacer",
                         'style': 'bar'},
                      ],
                      order=[[column_index, "desc"]],
                      drawCallback=filter_state_draw_callback("sequencing"),
                      columnDefs=[
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

    def get_selected_runs():
        """Return (seq_limsids, run_labels) for the currently selected run rows,
        or None when nothing is selected. Row indices are positional into the
        same dataframe passed to the widget (reset_index in ``data_seq``)."""
        try:
            selected = reactive_read(data_seq.widget, "selected_rows")
        except Exception:
            selected = None
        if not selected:
            return None

        dat = seq_df().reset_index(drop=True)
        if "seq_limsid" not in dat.columns:
            return None

        rows = dat.iloc[list(selected)]
        seq_ids = {
            str(v).strip() for v in rows["seq_limsid"].dropna() if str(v).strip()
        }
        if not seq_ids:
            return None

        run_labels = []
        if "Run ID" in rows.columns:
            run_labels = [
                str(v).strip() for v in rows["Run ID"].dropna() if str(v).strip()
            ]
        return seq_ids, run_labels

    return {"get_selected_runs": get_selected_runs}
