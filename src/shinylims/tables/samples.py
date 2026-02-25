'''
samples.py - Table module containing UI and server logic for the Samples table tab
'''

from shiny import ui, reactive
from shinywidgets import output_widget, render_widget, reactive_read
from itables.widget import ITable
from itables.javascript import JavascriptFunction
import pandas as pd
from src.shinylims.data.db_utils import query_to_dataframe
import re
import io

# Base path on the remote cluster — full path is built dynamically using the username
SAGA_BASE_PATH = "/cluster/shared/vetinst/users/"


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
            ui.input_action_button(
                "send_to_server",
                "📤 Send Selected Samples to SAGA for ATLAS",
                class_="btn-primary btn-sm"
            ),
            ui.input_switch("include_hist", "Include historical samples", False),
            style="display: flex; align-items: baseline; gap: 20px; margin-bottom: 10px;"
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
            "Sample Name",
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
                    ascending=False
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
                    escape=False,
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


    # Step 1 — "Send to Server" button: validate selection, then show credentials modal
    @reactive.Effect
    @reactive.event(input.send_to_server)
    def handle_send_to_server():
        selected = reactive_read(data_samples.widget, "selected_rows")

        if not selected:
            ui.modal_show(
                ui.modal(
                    ui.p("⚠️ No rows selected. Please use 'Select Filtered Rows' first, then deselect any rows you don't want."),
                    title="No Rows Selected",
                    easy_close=True,
                    footer=ui.modal_button("OK")
                )
            )
            return

        dat = combined_samples()
        export_columns = [col for col in ["Sample Name", "NIRD Filename"] if col in dat.columns]

        if not export_columns:
            ui.modal_show(
                ui.modal(
                    ui.p("⚠️ Could not find 'Sample Name' or 'NIRD Filename' columns in the data."),
                    title="Export Error",
                    easy_close=True,
                    footer=ui.modal_button("OK")
                )
            )
            return

        # Show credentials modal
        ui.modal_show(
            ui.modal(
                ui.p(f"Uploading {len(selected)} rows with columns: {', '.join(export_columns)}",
                     style="margin-bottom: 15px; color: #555;"),
                ui.input_text("upload_username", "Username"),
                ui.input_text("upload_totp", "TOTP Token"),
                ui.input_password("upload_password", "Password"),
                title="📤 SAGA Credentials",
                easy_close=True,
                footer=ui.div(
                    ui.modal_button("Cancel"),
                    ui.input_action_button(
                        "confirm_upload",
                        "Upload",
                        class_="btn-primary",
                        style="margin-left: 10px;"
                    ),
                    style="display: flex; justify-content: flex-end; gap: 10px;"
                )
            )
        )

    # Step 2 — "Upload" button inside the modal: do the actual upload
    @reactive.Effect
    @reactive.event(input.confirm_upload)
    def do_upload():
        selected = reactive_read(data_samples.widget, "selected_rows")
        dat = combined_samples()
        export_columns = [col for col in ["Sample Name", "NIRD Filename"] if col in dat.columns]
        selected_df = dat.iloc[list(selected)][export_columns]

        username = input.upload_username()
        totp = input.upload_totp()
        password = input.upload_password()
        saga_location = SAGA_BASE_PATH + username
        print(f"Preparing to upload {len(selected_df)} rows to {saga_location} with username '{username}'")
        # --- FOR TESTING: write to local CSV ---
        test_output_path = "/tmp/server_export.csv"
        selected_df.to_csv(test_output_path, index=False)
        # --- END TESTING BLOCK (remove for production) ---

        # Build a file-like object in memory from the dataframe
        file_buffer = io.StringIO()
        selected_df.to_csv(file_buffer, index=False)
        file_buffer.seek(0)  # Rewind to the start so upload_csv can read it

        try:
            # WAITING FOR GEORGES FUNCTION TO BE READY (upload_csv)
            upload_csv(
                file=file_buffer,
                username=username,
                TOTP=totp,
                password=password,
                saga_location=saga_location
            )

            ui.modal_show(
                ui.modal(
                    ui.p(f"✅ Successfully uploaded {len(selected_df)} rows to {saga_location}."),
                    ui.p(f"(Test CSV also saved to: {test_output_path})", 
                         style="color: #888; font-size: 0.9em;"),  # remove for production
                    title="Upload Complete",
                    easy_close=True,
                    footer=ui.modal_button("OK")
                )
            )

        except Exception as e:
            ui.modal_show(
                ui.modal(
                    ui.p(f"⚠️ Upload failed: {str(e)}", style="color: red;"),
                    ui.p(f"(Test CSV was still saved to: {test_output_path})",
                         style="color: #888; font-size: 0.9em;"),  # remove for production
                    title="Upload Error",
                    easy_close=True,
                    footer=ui.modal_button("OK")
                )
            )


    # Filter and render the filtered dataframe
    @render_widget
    def data_samples():
        dat = combined_samples()
        
        # Properly format date columns for DataTables
        if "Received Date" in dat.columns:
            dat["Received Date"] = pd.to_datetime(dat["Received Date"], errors='coerce')
            dat["Received Date"] = dat["Received Date"].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ''
            )
        
        # Find index for order column
        column_to_sort = "Received Date"
        if column_to_sort in dat.columns:
            column_index = dat.columns.get_loc(column_to_sort)
            date_column_index = column_index
        else:
            column_index = 0
            date_column_index = -1

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
                        {
                            "extend": "colvis",
                            "text": "Selection"
                        },
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
                                        dt.columns().visible(false);
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
                        "pageLength",
                        # --- NEW: Select filtered rows button ---
                        {
                            "text": "☑️ Select Filtered Rows",
                            "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    dt.rows({search: 'applied'}).select();
                                }
                            """)
                        },
                        # Deselect all rows button
                        {
                            "text": "🔲 Deselect All Rows",
                            "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    dt.rows().deselect();
                                }
                            """)
                        },
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
                                    "text": "Export to CSV",
                                    "title": "Sample Data Export"
                                },
                                {
                                    "extend": "excelHtml5", 
                                    "exportOptions": {"columns": ":visible"},
                                    "text": "Export to Excel",
                                    "title": "Sample Data Export"
                                },
                                {
                                    "extend": "csvHtml5", 
                                    "exportOptions": {
                                        "columns": get_saga_columns(dat)
                                    },
                                    "text": "Export CSV for ATLAS", 
                                    "title": "atlas_export"
                                },
                            ]
                        },
                        {'extend': "spacer",
                         'style': 'bar'},
                     ],
                     order=[[column_index, "desc"]],
                     columnDefs=[
                        {"className": "dt-center", "targets": "_all"},
                        {"width": "200px", "targets": "_all"},
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
                            """)
                        }
                     ]
                    )