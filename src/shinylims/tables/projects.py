'''
projects.py - Table module containing UI and server logic for the Projects table tab
'''

from shiny import ui
from shinywidgets import output_widget, render_widget
from itables.widget import ITable
from itables.javascript import JavascriptFunction
import pandas as pd


##############################
# UI: PROJECT TABLE          #
##############################

def projects_ui():
    """Define UI for the Projects tab."""
    return ui.div(
        output_widget("projects_table", fillable=False) 
    )


##############################
# SERVER: PROJECT TABLE      #
##############################

def projects_server(projects_df):
    """Render the Projects table as an interactive ITable widget."""
    
    @render_widget
    def projects_table():
        dat = projects_df.copy().reset_index(drop=True)

        # Format the 'Open Date' column for display
        if "Open Date" in dat.columns:
            dat["Open Date"] = pd.to_datetime(dat["Open Date"], errors="coerce")
            dat["Open Date"] = dat["Open Date"].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ""
            )

        # Determine column indices for ordering and formatting
        comment_index = dat.columns.get_loc("Comment") if "Comment" in dat.columns else -1
        order_column_index = dat.columns.get_loc("Open Date") if "Open Date" in dat.columns else 0
        date_column_index = order_column_index if "Open Date" in dat.columns else -1

        return ITable(
            dat,
            select=True,
            layout={"topEnd": "search", "top1": "searchBuilder"},
            column_filters="footer",
            search={"smart": True, "regex": True, "caseInsensitive": True},
            lengthMenu=[[200, 500, 1000, 2000, -1], [200, 500, 1000, 2000, "All"]],
            classes="compact hover order-column cell-border",
            scrollY="80vh",
            scrollX=True,
            paging=True,
            maxBytes=0,
            allow_html=True,
            autoWidth=True,
            keys=True,
            buttons=[
                {"extend": "spacer", "style": "bar", "text": "Column Settings"},
                {"extend": "colvis", "text": "Selection"},
                {
                    "extend": "collection",
                    "text": "Presets",
                    "buttons": [
                        {
                            "text": "Select All",
                            "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    dt.columns().visible(true);
                                }
                            """)
                        },
                        {
                            "text": "Deselect All",
                            "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    dt.columns().visible(false);
                                }
                            """)
                        },
                    ],
                },
                {"extend": "spacer", "style": "bar", "text": "Row Settings"},
                "pageLength",
                {"extend": "spacer", "style": "bar", "text": "Export"},
                {
                    "extend": "collection",
                    "text": "Type",
                    "buttons": [
                        {
                            "extend": "copyHtml5",
                            "exportOptions": {"columns": ":visible"},
                            "text": "Copy to Clipboard",
                        },
                        {
                            "extend": "csvHtml5",
                            "exportOptions": {"columns": ":visible"},
                            "text": "Export to CSV",
                            "title": "Project Data Export - Full",
                        },
                        {
                            "extend": "excelHtml5",
                            "exportOptions": {"columns": ":visible"},
                            "text": "Export to Excel",
                            "title": "Project Data Export",
                        },
                    ],
                },
                {"extend": "spacer", "style": "bar"},
            ],
            order=[[order_column_index, "desc"]],
            columnDefs=[
                {"targets": comment_index, "className": "left-column"} if comment_index != -1 else {},
                {"className": "dt-center", "targets": "_all"},
                {
                    "targets": date_column_index,
                    "type": "date",
                    "render": JavascriptFunction("""
                        function(data, type, row) {
                            if (type === 'sort' || type === 'type' || type === 'filter') {
                                if (!data || data === '') {
                                    return null;
                                }
                                return data;
                            }
                            return data;
                        }
                    """),
                } if date_column_index != -1 else {},
            ],
        )

