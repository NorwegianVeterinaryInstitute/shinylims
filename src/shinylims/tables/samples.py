'''
samples.py - Table module containing UI and server logic for the Samples table tab
'''

from shiny import render, ui
from itables.shiny import DT
import pandas as pd
from itables.javascript import JavascriptFunction

##############################
# UI SAMPLES TABLE
##############################

def samples_ui():
    return ui.div(
        ui.output_ui("data_samples")
    )

##############################
# SERVER SAMPLES TABLE
##############################

# Server logic for the Samples page
def samples_server(input, output, session, samples_df, samples_date_created):
    # Helper function to get indices of columns for saga export
    def get_saga_columns(dataframe):
        # Define the essential column names - customize this list as needed
        essential_columns = [
            "LIMS ID", 
            "Sample Name",
            "Species",
            "Project Account",
            "NIRD Filename"
        ]
        
        # Get the indices of these columns if they exist in the dataframe
        column_indices = []
        for column in essential_columns:
            if column in dataframe.columns:
                column_indices.append(dataframe.columns.get_loc(column))
        
        # If no essential columns were found, return all columns
        if not column_indices:
            return ":visible"
            
        return column_indices

    # Filter and render the filtered dataframe
    @render.ui
    def data_samples():
        dat = samples_df.copy().reset_index(drop=True)
        
        # Properly format date columns for DataTables
        if "Received Date" in dat.columns:
            # Convert to datetime type first
            dat["Received Date"] = pd.to_datetime(dat["Received Date"], errors='coerce')
            
            # Format dates as strings in a consistent format for display
            # Keep NaT values as empty strings
            dat["Received Date"] = dat["Received Date"].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ''
            )
        
        # Find index for order column
        column_to_sort = "Received Date"
        if column_to_sort in dat.columns:
            column_index = dat.columns.get_loc(column_to_sort)
            date_column_index = column_index  # Store for columnDefs
        else:
            column_index = 0  # Default to first column if Received Date not found
            date_column_index = -1  # Indicates no date column found

        # Return HTML tag with DT table element
        return ui.HTML(DT(dat,
                         select=True, 
                         layout={"topEnd": "search", "top1": "searchBuilder"},
                         lengthMenu=[[200, 500, 1000, 2000, -1], [200, 500, 1000, 2000, "All"]], 
                         column_filters="footer", 
                         search={"smart": True},
                         classes="nowrap compact hover order-column cell-border", 
                         scrollY="780px",
                         paging=True,
                         autoWidth=True,
                         maxBytes=0, 
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
                                        "exportOptions": {"columns": ":visible"},
                                        "text": "Copy to Clipboard"
                                    },

                                    # CSV export with all visible columns
                                    {
                                        "extend": "csvHtml5", 
                                        "exportOptions": {"columns": ":visible"},
                                        "text": "Export to CSV",
                                        "title": "Sample Data Export"
                                    },
                                    # Excel export with visible columns
                                    {
                                        "extend": "excelHtml5", 
                                        "exportOptions": {"columns": ":visible"},
                                        "text": "Export to Excel",
                                        "title": "Sample Data Export"
                                    },
                                    # CSV export with specific columns for Saga
                                    {
                                        "extend": "csvHtml5", 
                                        "exportOptions": {
                                            "columns": get_saga_columns(dat)
                                        },
                                        "text": "Export CSV for Saga", 
                                        "title": "saga_export"
                                    },
                                ]
                            },
                            {'extend': "spacer",
                             'style': 'bar'},
                         ],
                         order=[[column_index, "desc"]],
                         columnDefs=[
                            {"className": "dt-center", "targets": "_all"},
                            {"width": "200px", "targets": "_all"},  # Set a default width for all columns
                            
                            # Explicitly define the Received Date column as a date type for searchBuilder
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
                         ]
                        )) 

    # Define outputs that need to be returned
    output.data_samples = data_samples