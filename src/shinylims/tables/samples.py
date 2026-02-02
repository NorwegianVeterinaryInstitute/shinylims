'''
samples.py - Table module containing UI and server logic for the Samples table tab
'''

from shiny import ui, reactive
from shinywidgets import output_widget, render_widget
from itables.widget import ITable
from itables.javascript import JavascriptFunction
import pandas as pd
from src.shinylims.data.db_utils import query_to_dataframe
import pandas as pd
import re


##############################
# UI SAMPLES TABLE
##############################

def samples_ui():
    return ui.div(
        # Switches and buttons row
        ui.div(
            ui.input_action_button(
                "show_storage_status", 
                "📦 Storage Box Status",
                class_="btn-secondary btn-sm"
            ),
            ui.input_switch("include_hist", "Include historical samples", False),
            style="display: flex; align-items: baseline; gap: 20px; margin-bottom: 10px;"
            #                    ^^^^^^^^ Changed from 'center' to 'baseline'
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
                        ui.p("⚠️ You are now including historical samples. The historical data was recorded before Clarity LIMS was implemented. It may not be complete or accurate. It will also make searching more difficult since data isnt formatted consistently."),
                        ui.p("Please review the data carefully. Data can be filtered through the 'Custom Search Builder' by 'Clarity LIMS' or 'Historical' using the 'Data Source' column.")
                    ),
                    title="Historical Data Warning",
                    easy_close=True,
                    footer=ui.modal_button("OK")
                )
            )
        
    @reactive.Effect
    def show_warning_modal():
        # ... existing code ...
        pass
    
    # Modal for storage box status
    @reactive.Effect
    @reactive.event(input.show_storage_status)
    def show_storage_status_modal():
        
        
        try:
            # Fetch all storage containers with their states
            query = """
            SELECT 
                container_name,
                state,
                last_checked,
                last_updated
            FROM storage_containers
            """
            containers_df = query_to_dataframe(query)
            
            if containers_df.empty:
                content = ui.p("No storage container data available.")
            else:
                # Extract numeric part for sorting
                def extract_number(name):
                    """Extract the numeric part from container name like 'NGS45' -> 45"""
                    if pd.isna(name):
                        return 0
                    match = re.search(r'(\d+)', str(name))
                    return int(match.group(1)) if match else 0
                
                # Add a numeric sort column
                containers_df['sort_num'] = containers_df['container_name'].apply(extract_number)
                
                # Sort by number only (descending - highest first)
                containers_df = containers_df.sort_values(
                    by='sort_num',
                    ascending=False  # Highest number first
                )
                
                # Rename columns for display (after sorting)
                containers_df = containers_df.rename(columns={
                    'container_name': 'Box Name',
                    'state': 'Status',
                    'last_checked': 'Last Checked',
                    'last_updated': 'Last Updated'
                })
                
                # Format dates
                for col in ['Last Checked', 'Last Updated']:
                    if col in containers_df.columns:
                        containers_df[col] = pd.to_datetime(
                            containers_df[col], 
                            errors='coerce'
                        ).dt.strftime('%Y-%m-%d %H:%M')
                
                # Add colored status column
                def format_status(status):
                    if status == 'Discarded':
                        return f'<span style="color: red; font-weight: bold;">🗑️ {status}</span>'
                    elif status == 'Populated':
                        return f'<span style="color: green; font-weight: bold;">✅ {status}</span>'
                    else:
                        return status
                
                containers_df['Status'] = containers_df['Status'].apply(format_status)
                
                # Count boxes
                populated_count = containers_df['Status'].str.contains('Populated', case=False).sum()
                discarded_count = containers_df['Status'].str.contains('Discarded').sum()
                total_count = len(containers_df)
                
                # Create summary text
                summary = ui.p(
                    f"📦 Total: {total_count} | ✅ Populated: {populated_count} | 🗑️ Discarded: {discarded_count}",
                    style="font-weight: bold; margin-bottom: 15px; font-size: 16px;"
                )
                
                # Drop the sort_num column before display
                display_df = containers_df.drop('sort_num', axis=1)
                
                # Create properly aligned HTML table
                table_html = display_df.to_html(
                    index=False,
                    escape=False,  # Allow HTML in Status column
                    classes='table table-striped table-bordered table-sm',
                    border=0
                )
                
                # Add inline CSS for proper alignment
                styled_table = f"""
                <style>
                    .storage-table {{
                        width: 100%;
                        max-height: 400px;
                        overflow-y: auto;
                        overflow-x: auto;
                    }}
                    .storage-table table {{
                        width: 100%;
                        margin: 0;
                    }}
                    .storage-table th {{
                        position: sticky;
                        top: 0;
                        background-color: #f8f9fa;
                        z-index: 10;
                        padding: 8px;
                        text-align: left;
                        border-bottom: 2px solid #dee2e6;
                    }}
                    .storage-table td {{
                        padding: 8px;
                        text-align: left;
                    }}
                </style>
                <div class="storage-table">
                    {table_html}
                </div>
                """
                
                content = ui.div(
                    summary,
                    ui.HTML(styled_table)
                )
        
        except Exception as e:
            content = ui.div(
                ui.p(f"⚠️ Error loading storage container data: {str(e)}", 
                     style="color: red;")
            )
        
        # Show modal
        ui.modal_show(
            ui.modal(
                content,
                title="📦 Storage Box Status",
                size="l",
                easy_close=True,
                footer=ui.modal_button("Close")
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
            dat['Data_Source'] = 'Clarity LIMS'
            hist_dat = samples_historical_df.copy()
            hist_dat['Data_Source'] = 'Historical'
            
            # Remove the 'data_source' column if it exists
            if 'data_source' in hist_dat.columns:
                hist_dat = hist_dat.drop('data_source', axis=1)

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