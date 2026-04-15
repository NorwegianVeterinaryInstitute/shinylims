'''
sequencing.py - table module containing UI and server logic for the Sequencing table tab
'''

from shiny import ui, reactive, render
from shinywidgets import output_widget, render_widget
from itables.widget import ITable
from itables.javascript import JavascriptFunction
import pandas as pd

from shinylims.ui_helpers.table_controls import (
    DATE_VALUE_RENDERER,
    build_filter_status_bar,
    clear_all_filters_script,
    deselect_all_columns_button,
    filter_state_draw_callback,
    select_all_columns_button,
    visibility_preset_button,
)


##############################
# UI ILMN SEQ TABLE
##############################

def seq_ui():
    return ui.div(
        clear_all_filters_script("sequencing"),
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
                layout={"topStart": "buttons", "topEnd": "search"},
                lengthMenu=[[200, 500, 1000, 2000, -1], [200, 500, 1000, 2000, "All"]],
                select=True,  
                column_filters="footer", 
                search={"smart": True},
                classes="nowrap compact hover order-column cell-border",
                scrollY="84vh",
                scrollX=True,
                paging=True,
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
                         'text': 'Rows'},
                         "pageLength",
                        {'extend': "spacer",
                         'style': 'bar',
                         'text': 'Export'},
                        # Collection of export options
                        {
                            "extend": "collection", 
                            "text": "Type",
                            "buttons": [
                                # Copy to clipboard
                                {
                                    "extend": "copyHtml5",
                                    "exportOptions": {"columns": ":visible"},
                                    "text": "Copy to Clipboard"
                                },
                                # CSV export with visible columns
                                {
                                    "extend": "csvHtml5", 
                                    "exportOptions": {"columns": ":visible"},
                                    "title": "Sequencing Data Export",
                                    "text": "Export to CSV"
                                },
                                # Excel export with visible columns
                                {
                                    "extend": "excelHtml5", 
                                    "exportOptions": {"columns": ":visible"},
                                    "title": "Sequencing Data Export",
                                    "text": "Export to Excel"
                                }
                            ]
                        },
                        {'extend': "spacer",
                         'style': 'bar',
                         'text': 'Filter'},
                        {"extend": "searchBuilder"},
                        {'extend': "spacer",
                         'style': 'bar'},
                      ],
                      order=[[column_index, "desc"]],
                      drawCallback=filter_state_draw_callback("sequencing"),
                      columnDefs=[
                          {'targets': comment_index, 'className': 'left-column', 'width': '200px'} if comment_index != -1 else {},
                          {"className": "dt-center", "targets": "_all"},
                          {"targets": run_number_index, "render": JavascriptFunction("function(data, type, row) { return type === 'display' ? Math.round(data).toString() : data; }")} if run_number_index != -1 else {},
                          {"targets": cluster_density_index, "render": JavascriptFunction("function(data, type, row) { return type === 'display' ? Math.round(data).toString() : data; }")} if cluster_density_index != -1 else {},
                          # Explicitly define the Seq Date column as a date type for searchBuilder
                          {
                              "targets": date_column_index,
                              "type": "date",
                              "render": DATE_VALUE_RENDERER
                          }
                      ])
