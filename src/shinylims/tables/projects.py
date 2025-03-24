'''
projects.py - Table module containing UI and server logic for the Projects table tab
'''

from shiny import render, ui
from itables.shiny import DT
import pandas as pd
from itables.javascript import JavascriptFunction

##############################
# UI PROJECT TABLE
##############################

def projects_ui():
    return ui.div(
        ui.output_ui("data_projects")
    )

##############################
# SERVER PROJECT TABLE
##############################

def projects_server(input, output, session, projects_df, project_date_created):

    @render.ui
    def data_projects():
        dat = projects_df.copy().reset_index(drop=True)
        
        # Properly format date columns for DataTables
        if "Open Date" in dat.columns:
            # Convert to datetime type first
            dat["Open Date"] = pd.to_datetime(dat["Open Date"], errors='coerce')
            
            # Format dates as strings in a consistent format for display
            # Keep NaT values as empty strings
            dat["Open Date"] = dat["Open Date"].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ''
            )
        
        # Get index for the comment section (used for css styling)
        if 'Comment' in dat.columns:
            comment_index = dat.columns.get_loc('Comment')
        else:
            comment_index = "Dummy"
        
        # Find index for order column (typically Open Date)
        if 'Open Date' in dat.columns:
            order_column_index = dat.columns.get_loc('Open Date')
            date_column_index = order_column_index  # Store for columnDefs
        else:
            order_column_index = 0  # Default to first column if Open Date not found
            date_column_index = -1  # Indicates no date column found

        # Return HTML tag with DT table element
        return ui.HTML(DT(dat, 
                         select=True, 
                         layout={"topEnd": "search", "top1": "searchBuilder"}, 
                         column_filters="footer", 
                         search={"smart": True, "regex": True, "caseInsensitive": True},
                         lengthMenu=[[200, 500, 1000, 2000, -1], [200, 500, 1000, 2000, "All"]],  
                         classes="compact hover order-column cell-border", 
                         scrollY="750px",
                         paging=True,
                         maxBytes=0, 
                         autoWidth=True,
                         keys=True,
                         buttons=[
                            {'extend': "spacer",
                             'style': 'bar',
                             'text': 'Column Settings'},
                            # Column visibility toggle
                            {
                                "extend": "colvis",
                                "text": "Selection"
                            },
                            {'extend': "spacer"},
                            # Button to deselect all columns
                            {
                                "text": "Deselect All",
                                "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    dt.columns().visible(false);
                                }
                                """)
                            },
                            # Button to select all columns
                            {
                                "text": "Select All",
                                "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    dt.columns().visible(true);
                                }
                                """)
                            },
                            {'extend': "spacer",
                             'style': 'bar',
                             'text': 'Page Length'},
                            # Page length selector
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
                                        "exportOptions": {"columns": ":visible"}
                                    },
                                    # CSV export with all visible columns
                                    {
                                        "extend": "csvHtml5", 
                                        "exportOptions": {"columns": ":visible"},
                                        "text": "CSV (All Visible)",
                                        "title": "Project Data Export - Full"
                                    },
                                    # Excel export with visible columns
                                    {
                                        "extend": "excelHtml5", 
                                        "exportOptions": {"columns": ":visible"},
                                        "title": "Project Data Export"
                                    }
                                ]
                            },
                            {'extend': "spacer",
                             'style': 'bar'},
                         ],
                         order=[[order_column_index, "desc"]],
                         columnDefs=[
                            {'targets': comment_index, 'className': 'left-column'},
                            {"className": "dt-center", "targets": "_all"},
                            # Explicitly define the Open Date column as a date type for searchBuilder
                            {
                                "targets": date_column_index,
                                "type": "date",
                                "render": JavascriptFunction("""
                                function(data, type, row) {
                                    // For sorting and filtering
                                    if (type === 'sort' || type === 'type' || type === 'filter') {
                                        if (!data || data === '') {
                                            return null;
                                        }
                                        return data;
                                    }
                                    // For display
                                    return data;
                                }
                                """)
                            }
                         ]))

    # Define outputs that need to be returned
    output.data_projects = data_projects