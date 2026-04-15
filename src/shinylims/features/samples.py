'''
samples.py - Table module containing UI and server logic for the Samples table tab
'''

from shiny import ui, reactive, render
from shinywidgets import output_widget, render_widget, reactive_read
from itables.widget import ITable
from itables.javascript import JavascriptFunction
import pandas as pd
import io
from shinylims.ui_helpers.table_controls import (
    DATE_VALUE_RENDERER,
    batch_filter_button,
    build_filter_status_bar,
    clear_all_filters_script,
    deselect_all_columns_button,
    filter_state_draw_callback,
    select_all_columns_button,
    visibility_preset_button,
)
import re
from shinylims.integrations.upload_atlas_file_to_saga import _upload_csv_to_saga
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
        clear_all_filters_script("samples"),
        # Unified filter status bar (visible when any filter is active)
        ui.output_ui("filter_status_bar"),
        # Widget container
        ui.div(
            output_widget("data_samples", fillable=False),
            style="position: relative;"
        ),
    )


##############################
# SERVER SAMPLES TABLE
##############################

# Server logic for the Samples page
def samples_server(samples_df, input):

    # ── Batch filter state ────────────────────────────────────────────────
    batch_filter_ids = reactive.Value(None)      # set[str] | None
    batch_filter_column = reactive.Value("Sample Name")

    @reactive.Calc
    def combined_samples():
        df = samples_df().reset_index(drop=True)
        ids = batch_filter_ids.get()
        if ids is not None:
            col = batch_filter_column.get()
            if col in df.columns:
                df = df[df[col].isin(ids)].reset_index(drop=True)
        return df

    # ── Unified filter status bar ────────────────────────────────────────
    @render.ui
    def filter_status_bar():
        extra = []
        ids = batch_filter_ids.get()
        if ids is not None:
            col = batch_filter_column.get()
            df = samples_df()
            matched = df[col].isin(ids).sum() if col in df.columns else 0
            extra.append(f"Batch filter: {matched} of {len(ids)} matched in \"{col}\"")

        try:
            raw = input.dt_filter_state_samples()
        except Exception:
            raw = None

        return build_filter_status_bar("samples", raw, extra_lines=extra)

    # ── Batch filter modal ───────────────────────────────────────────────
    @reactive.Effect
    @reactive.event(input.batch_filter_open)
    def _show_batch_filter_modal():
        ui.modal_show(
            ui.modal(
                ui.input_text_area(
                    "batch_filter_text",
                    "Paste sample names or IDs (one per line, or separated by commas/tabs):",
                    rows=10,
                    width="100%",
                ),
                ui.input_select(
                    "batch_filter_col",
                    "Match column:",
                    choices=["Sample Name", "LIMS ID"],
                    selected=batch_filter_column.get(),
                ),
                ui.div(
                    ui.span(
                        "Note: ",
                        style="font-weight: 600;",
                    ),
                    "Applying a batch filter will reset any active search and column filters.",
                    class_="alert alert-warning",
                    style="font-size: 0.85rem; margin-top: 10px; padding: 8px 12px; margin-bottom: 0;",
                ),
                title="Batch Filter",
                easy_close=True,
                footer=ui.div(
                    ui.modal_button("Cancel"),
                    ui.input_action_button(
                        "batch_filter_apply",
                        "Apply",
                        class_="btn-primary",
                        style="margin-left: 10px;",
                    ),
                    style="display: flex; justify-content: flex-end; gap: 10px;",
                ),
            )
        )

    @reactive.Effect
    @reactive.event(input.batch_filter_apply)
    def _apply_batch_filter():
        raw = input.batch_filter_text() or ""
        col = input.batch_filter_col() or "Sample Name"

        # Split on newlines, commas, or tabs and strip whitespace
        ids = {v.strip() for v in re.split(r"[\n,\t]+", raw) if v.strip()}

        if not ids:
            ui.notification_show("No IDs entered.", type="warning")
            return

        # Check how many match
        df = samples_df()
        if col in df.columns:
            found = ids & set(df[col].astype(str))
            not_found = ids - found
        else:
            found = set()
            not_found = ids

        batch_filter_ids.set(ids)
        batch_filter_column.set(col)

        # Show results in a modal so the user can review before dismissing
        body_children = [
            ui.p(f"Matched {len(found)} of {len(ids)} IDs in \"{col}\"."),
        ]
        if not_found:
            body_children.append(
                ui.p(
                    ui.tags.strong(f"{len(not_found)} not found: "),
                    ", ".join(sorted(not_found)),
                )
            )

        ui.modal_show(
            ui.modal(
                *body_children,
                title="Batch Filter Applied",
                easy_close=True,
                footer=ui.modal_button("OK"),
            )
        )

    @reactive.Effect
    @reactive.event(input.batch_filter_clear)
    def _clear_batch_filter():
        batch_filter_ids.set(None)

    @reactive.Effect
    @reactive.event(input.clear_all_filters_samples)
    def _clear_all_filters():
        batch_filter_ids.set(None)

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

        # Format date column for DataTables display
        if "Received Date" in dat.columns:
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
                layout={"topStart": "buttons", "topEnd": "search"},
                lengthMenu=[[200, 500, 1000, 2000, -1], [200, 500, 1000, 2000, "All"]],
                column_filters="footer",
                search={"smart": True},
                classes="nowrap compact hover order-column cell-border",
                scrollY="84vh",
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
                     'text': 'Columns'},
                    {
                        "extend": "colvis",
                        "text": "Selection",
                        "collectionLayout": "two-column",
                    },
                    {
                        "extend": "collection",
                        "text": "Presets",
                        "buttons": [
                            select_all_columns_button(),
                            deselect_all_columns_button(),
                            visibility_preset_button([2, 3, 4, 5, 9, 10, 21]),
                        ]
                    },
                    # ── Row settings ──────────────────────────────────────────
                    {'extend': "spacer",
                     'style': 'bar',
                     'text': 'Rows'},
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
                     'style': 'bar',
                     'text': 'Filter'},
                    batch_filter_button(),
                    {"extend": "searchBuilder"},
                    {'extend': "spacer",
                     'style': 'bar'},
                ],
                order=[[column_index, "desc"]],
                drawCallback=filter_state_draw_callback("samples"),
                columnDefs=[
                    {"className": "dt-center", "targets": "_all"},
                    {"width": "200px", "targets": "_all"},
                    {
                        "targets": date_column_index,
                        "type": "date",
                        "render": DATE_VALUE_RENDERER
                    }
                ]
            )
