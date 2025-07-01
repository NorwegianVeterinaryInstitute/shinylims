'''
samples.py - Table module containing UI and server logic for the Samples table tab
'''

from shiny import ui, reactive
from shinywidgets import output_widget, render_widget
from itables.widget import ITable
from itables.javascript import JavascriptFunction
import pandas as pd



##############################
# UI SAMPLES TABLE
##############################

def samples_ui():
    return ui.div(
        # Switch toggle with inline styling
        ui.div(
            ui.input_switch("include_hist", "Include historical samples", False)
        ),
        # Widget container
        ui.div(
            output_widget("data_samples", fillable=False),
        ),
        
    )


##############################
# SERVER SAMPLES TABLE
##############################

# Server logic for the Samples page
def samples_server(samples_df, samples_historical_df, input):
    
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


    @reactive.Effect
    def show_warning_modal():
        if input.include_hist():
            return ui.modal_show(
                ui.modal(
                    ui.div(
                        ui.p("⚠️ You are now including historical samples. The historical data was recorded before the current LIMS system was implemented. It may not be complete or accurate. It will also make searching more difficult since data isnt formatted consistently."),
                        ui.p("Please review the data carefully. Data can be filtered through the 'Custom Search Builder' by 'Current' or 'Historical' using the 'Data Source' column.")
                    ),
                    title="Historical Data Warning",
                    easy_close=True,
                    footer=ui.modal_button("OK")
                )
            )

    # Create a reactive expression for the combined dataframe
    @reactive.Calc
    def combined_samples():
        # Start with the regular samples
        dat = samples_df.copy()
        
        # If checkbox is checked and historical data exists, combine them
        if input.include_hist() and samples_historical_df is not None and not samples_historical_df.empty:
            # Add a column to distinguish data sources if needed
            dat['Data_Source'] = 'Current'
            hist_dat = samples_historical_df.copy()
            hist_dat['Data_Source'] = 'Historical'
            
            # Combine the dataframes
            dat = pd.concat([dat, hist_dat], ignore_index=True, sort=False)
        
        return dat.reset_index(drop=True)

    # Filter and render the filtered dataframe
    @render_widget
    def data_samples():
        dat = combined_samples()
        
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
        return ITable(
                dat,
                select=True, 
                layout={"topEnd": "search", "top1": "searchBuilder"},
                lengthMenu=[[200, 500, 1000, 2000, -1], [200, 500, 1000, 2000, "All"]], 
                column_filters="footer", 
                search={"smart": True},
                classes="nowrap compact hover order-column cell-border", 
                scrollY="75vh",
                scrollX=True,
                paging=True,
                autoWidth=True,
                maxBytes=0,
                allow_html=True,
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
                        # Button to select specific columns presets
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
                            {
                               
                            },
                            {
                                "text": "Minimal View",
                                "action": JavascriptFunction("""
                                    function(e, dt, node, config) {
                                        // Example: Show only specific columns by index
                                        dt.columns().visible(false);  // Hide all first
                                        dt.column(2).visible(true);
                                        dt.column(3).visible(true);
                                        dt.column(4).visible(true);
                                        dt.column(5).visible(true);
                                        dt.column(9).visible(true);
                                        dt.column(10).visible(true);
                                        dt.column(21).visible(true);
                                    }
                                """)
                            }
                        ]
                    },
                        {'extend': "spacer",
                         'style': 'bar',
                         'text': 'Row Settings'},
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
                    )