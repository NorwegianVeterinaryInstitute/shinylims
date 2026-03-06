'''
samples.py - Table module containing UI and server logic for the Samples table tab
'''

from shiny import ui, reactive, render
from shinywidgets import output_widget, render_widget, reactive_read
from itables.widget import ITable
from itables.javascript import JavascriptFunction
import pandas as pd
import io
from shinylims.helpers.upload_atlas_file_to_saga import _upload_csv_to_saga
from datetime import datetime


# Base path on the remote cluster — full path is built dynamically using the username
SAGA_BASE_PATH = "/cluster/shared/vetinst/users/"


##############################
# UI SAMPLES TABLE
##############################

def samples_ui():
    return ui.div(
        # CSS for upload button disabled state and dropdown menus
        ui.tags.style("""
            #confirm_upload:disabled {
                opacity: 0.65;
                cursor: not-allowed;
                pointer-events: all !important;
            }
            div.dt-button-collection .dt-button {
                white-space: normal !important;
                min-width: 280px;
            }
        """),
        # Widget container
        ui.div(
            ui.output_ui("hist_mode_indicator"),
            output_widget("data_samples", fillable=False),
            style="position: relative;"
        ),
    )


##############################
# SERVER SAMPLES TABLE
##############################

# Server logic for the Samples page
def samples_server(samples_df, samples_historical_df, input):
    has_shown_hist_warning = reactive.Value(False)

    @render.ui
    def hist_mode_indicator():
        if not input.include_hist():
            return None
        return ui.div(
            "Historical data: ON",
            class_="badge text-bg-warning",
            style="position: absolute; top: 8px; right: 10px; z-index: 20;"
        )

    @reactive.Effect
    def show_warning_modal():
        if not input.include_hist() or has_shown_hist_warning.get():
            return

        has_shown_hist_warning.set(True)
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


    # Step 1 — "Send to SAGA" button (triggered via Shiny.setInputValue from the export dropdown):
    # validate selection, then show credentials modal
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
        # Password/autofill mitigation:
        # - add hidden decoy username/password fields (Chrome/Edge tends to fill those instead)
        # - rename the real inputs away from upload_username/upload_password to avoid login heuristics
        ui.modal_show(
            ui.modal(
                ui.tags.form(
                    ui.tags.input(type="text", name="username", tabindex="-1",
                                  autocomplete="username",
                                  style="position:absolute; left:-9999px; height:0; width:0;"),
                    ui.tags.input(type="password", name="password", tabindex="-1",
                                  autocomplete="current-password",
                                  style="position:absolute; left:-9999px; height:0; width:0;"),

                    ui.p(f"Uploading {len(selected)} rows with columns: {', '.join(export_columns)}",
                         style="margin-bottom: 15px; color: #555;"),
                    ui.input_text("saga_user", "Username"),
                    ui.input_password("saga_password", "Password"),
                    ui.input_text("saga_totp", "TOTP Token (2FA)"),
                ),
                title="📤 SAGA Credentials",
                easy_close=True,
                footer=ui.div(
                    ui.modal_button("Cancel"),
                    ui.input_action_button(
                        "confirm_upload",
                        "Upload",
                        class_="btn-primary",
                        style="margin-left: 10px;",
                        onclick="""
                        this.disabled = true;
                        this.innerHTML = '⏳ Uploading...';
                        this.style.opacity = '0.65';
                        this.style.cursor = 'not-allowed';
                    """
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

        username = input.saga_user()
        totp = input.saga_totp()
        password = input.saga_password()
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        saga_location = SAGA_BASE_PATH + username + f"/atlas_export_{timestamp}.csv"

        # Build a bytes file-like object in memory from the dataframe
        file_buffer = io.StringIO(selected_df.to_csv(index=False))

        try:
            _upload_csv_to_saga(
                file=file_buffer,
                username=username,
                totp=totp,
                password=password,
                saga_location=saga_location
            )

            ui.modal_show(
                ui.modal(
                    ui.p(f"✅ Successfully uploaded {len(selected_df)} rows to {saga_location}."),
                    ui.p("This csv can be used with the activate_data.sh script from ATLAS. See documentation at ",
                        ui.tags.a(
                            "https://github.com/NorwegianVeterinaryInstitute/ATLAS",
                            href="https://github.com/NorwegianVeterinaryInstitute/ATLAS",
                            target="_blank"
                        )
                    ),
                    title="Upload Complete",
                    easy_close=True,
                    footer=ui.modal_button("OK")
                )
            )

        except Exception as e:
            lines = str(e).split("\n")

            ui.modal_show(
                ui.modal(
                    ui.div(
                        ui.p("⚠️ Upload failed", style="font-weight: bold;"),
                        *[ui.p(line) for line in lines],
                        style="color: red;"
                    ),
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
                    # ── Column visibility ─────────────────────────────────────
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
                            {},
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
                    # ── Row settings ──────────────────────────────────────────
                    {'extend': "spacer",
                     'style': 'bar',
                     'text': 'Row Settings'},
                    "pageLength",
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
                    # ── Export ────────────────────────────────────────────────
                    {'extend': "spacer",
                     'style': 'bar',
                     'text': 'Export'},
                    {
                        "extend": "collection",
                        "text": "📤 Export",
                        "buttons": [
                            # Export to CSV — selected rows, visible columns
                            {
                                "extend": "csvHtml5",
                                "exportOptions": {"columns": ":visible"},
                                "text": "📄 Export to CSV",
                                "title": "Sample Data Export"
                            },
                            # Export to Excel — selected rows, visible columns
                            {
                                "extend": "excelHtml5",
                                "exportOptions": {"columns": ":visible"},
                                "text": "📊 Export to Excel",
                                "title": "Sample Data Export"
                            },
                            # Send selected rows to SAGA via FTP — triggers Shiny server logic
                            {
                                "text": "🖥️ Send to SAGA for ATLAS",
                                "action": JavascriptFunction("""
                                    function(e, dt, node, config) {
                                    if (dt.rows({selected: true}).count() === 0) {
                                            alert('No rows selected. Please select rows first.');
                                            return;
                                        }
                                        // Close the dropdown collection before opening the modal
                                        $('div.dt-button-collection').fadeOut();
                                        $('body').trigger('click');
                                        Shiny.setInputValue('send_to_server', Math.random());
                                    }
                                """)
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
