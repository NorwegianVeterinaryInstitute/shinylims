'''
samples.py - Table module containing UI and server logic for the Samples table tab
'''

import html
import json

from shiny import ui, reactive, render
from shinywidgets import output_widget, render_widget, reactive_read
from itables.widget import ITable
from itables.javascript import JavascriptFunction
import pandas as pd
import io
from shinylims.ui_helpers.table_controls import (
    COLVIS_COLUMN_TEXT,
    searchbuilder_title_defs,
    DATE_VALUE_RENDERER,
    FILTER_BUILDER_LANGUAGE,
    batch_filter_button,
    build_filter_status_bar,
    clear_all_filters_script,
    deselect_all_columns_button,
    export_options,
    filter_state_draw_callback,
    preset_column_defs,
    select_all_columns_button,
    truncated_text_renderer,
    visibility_preset_button,
)
import re
from shinylims.integrations.upload_atlas_file_to_saga import _upload_csv_to_saga
from datetime import datetime


# Base path on the remote cluster — full path is built dynamically using the username
SAGA_BASE_PATH = "/cluster/shared/vetinst/users/"

# Fixed sessionStorage key so the table's setup survives a view switch, which
# unmounts it (app_content renders one view at a time). DataTables' own state
# storage keys off the table's id, and the widget gets a fresh auto-generated one
# on every mount, so the key would never match -- hence the explicit one here.
SAMPLES_TABLE_STATE_KEY = "shinylims_samples_dt_state"

# Column visibility presets for the "Presets" menu, as column names rather than
# positions -- see visibility_preset_button. Each one is a task the table gets
# used for, not a slice of the schema. The per-step *_limsid links belong to the
# step they record, so they sit with it rather than in a preset of their own.
COLUMN_PRESETS = [
    # What the sample is, who it belongs to, and how far it has got.
    ("🧫 Sample Overview", [
        "LIMS ID", "Received Date", "progress", "Species",
        "Sample Name", "Project Name", "Experiment Name",
    ]),
    # Nanodrop and Qubit readings, with the steps that produced them.
    ("🔬 QC Metrics", [
        "LIMS ID", "Sample Name", "Species", "Extraction Number",
        "Absorbance", "A260/280 ratio", "A260/230 ratio", "Fluorescence",
        "nd_limsid", "qubit_limsid",
    ]),
    # Finding the physical sample, and knowing what it is before you handle it.
    ("📦 Storage & Handling", [
        "LIMS ID", "Sample Name", "Species", "sample_type", "gram_stain",
        "Storage Box", "Storage Well", "Received Date",
    ]),
    # Library prep through to delivered data.
    ("🧬 Prep & Sequencing", [
        "LIMS ID", "Sample Name", "Experiment Name", "Increased Pooling (%)",
        "Reagent Label", "prep_limsid", "seq_limsid", "NIRD Filename",
    ]),
    # What gets invoiced, and against which account.
    ("💰 Billing", [
        "LIMS ID", "Project Name", "Project Account", "Invoice ID",
        "Billing Description", "price", "billed_limsid",
    ]),
    # Who sent the samples in, and under what project.
    ("👤 Project & Submitter", [
        "LIMS ID", "Project LIMS ID", "Project Name", "submitter",
        "submitting_lab", "Project Account", "Received Date",
    ]),
]

# The table opens on this one rather than all 31 columns: a first-time visitor
# gets a readable sample list instead of a wall of horizontal scroll. Only a
# default -- stateSave restores a returning visitor's own columns over it.
DEFAULT_COLUMN_PRESET = "🧫 Sample Overview"
DEFAULT_PRESET_COLUMNS = dict(COLUMN_PRESETS)[DEFAULT_COLUMN_PRESET]


def _find_batch_filter_matches(
    df: pd.DataFrame, col: str, ids: set[str]
) -> tuple[set[str], list[str]]:
    """Return the matched IDs and sorted non-matches for the selected column."""
    if col not in df.columns:
        return set(), sorted(ids)

    found = ids & set(df[col].astype(str))
    return found, sorted(ids - found)


def _batch_filter_non_matches_csv(non_matches: list[str], col: str) -> str:
    """Serialize batch-filter non-matches for download."""
    return pd.DataFrame({col: non_matches}).to_csv(index=False)


def _split_seq_limsids(cell) -> set[str]:
    """Extract plain LUIDs from comma-separated plain, HTML, or Markdown links."""
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return set()

    seq_ids = set()
    for raw_part in str(cell).split(","):
        part = raw_part.strip()
        if not part:
            continue

        html_link = re.fullmatch(
            r"<a\b[^>]*>([^<]+)</a>",
            part,
            flags=re.IGNORECASE,
        )
        markdown_link = re.fullmatch(r"\[([^]]+)]\([^)]+\)", part)
        if html_link:
            part = html.unescape(html_link.group(1)).strip()
        elif markdown_link:
            part = markdown_link.group(1).strip()

        if part:
            seq_ids.add(part)
    return seq_ids

def _seq_limsid_matches(cell, wanted: set[str]) -> bool:
    """True when any LUID in ``cell`` is one of the wanted sequencing LUIDs."""
    return bool(_split_seq_limsids(cell) & wanted)


def project_limsids_for_seq_limsids(df: pd.DataFrame, seq_ids) -> list[str]:
    """Return project LIMS IDs for samples linked to any selected sequencing LUID."""
    wanted = set()
    for seq_id in seq_ids:
        wanted.update(_split_seq_limsids(seq_id))
    if not wanted or "seq_limsid" not in df.columns or "Project LIMS ID" not in df.columns:
        return []

    rows = df[df["seq_limsid"].apply(lambda cell: _seq_limsid_matches(cell, wanted))]
    project_ids = [
        str(value).strip()
        for value in rows["Project LIMS ID"].dropna()
        if str(value).strip()
    ]
    return list(dict.fromkeys(project_ids))


def seq_limsids_for_project_limsids(df: pd.DataFrame, project_ids) -> list[str]:
    """Return sequencing LIMS IDs for samples belonging to selected projects."""
    wanted = {
        str(project_id).strip()
        for project_id in project_ids
        if str(project_id).strip()
    }
    if (
        not wanted
        or "Project LIMS ID" not in df.columns
        or "seq_limsid" not in df.columns
    ):
        return []

    rows = df[df["Project LIMS ID"].astype(str).isin(wanted)]
    seq_ids = []
    for value in rows["seq_limsid"]:
        seq_ids.extend(_split_seq_limsids(value))
    return sorted(set(seq_ids))


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
    batch_filter_non_matches = reactive.Value(None)  # dict[str, str | list[str]] | None

    # ── Run filter state (set from the Sequencing tab) ────────────────────
    run_filter_seq_ids = reactive.Value(None)    # set[str] | None
    run_filter_label = reactive.Value(None)      # str | None (run IDs, for display)

    # Project filter state (set from the Projects tab)
    project_filter_ids = reactive.Value(None)    # set[str] | None
    project_filter_label = reactive.Value(None)  # str | None

    @reactive.Calc
    def combined_samples():
        df = samples_df().reset_index(drop=True)
        ids = batch_filter_ids.get()
        if ids is not None:
            col = batch_filter_column.get()
            if col in df.columns:
                df = df[df[col].isin(ids)].reset_index(drop=True)
        seq_ids = run_filter_seq_ids.get()
        if seq_ids and "seq_limsid" in df.columns:
            mask = df["seq_limsid"].apply(lambda cell: _seq_limsid_matches(cell, seq_ids))
            df = df[mask].reset_index(drop=True)
        project_ids = project_filter_ids.get()
        if project_ids and "Project LIMS ID" in df.columns:
            df = df[
                df["Project LIMS ID"].astype(str).isin(project_ids)
            ].reset_index(drop=True)
        return df

    # ── Unified filter status bar ────────────────────────────────────────
    @render.ui
    def filter_status_bar():
        extra = []
        seq_ids = run_filter_seq_ids.get()
        if seq_ids:
            df = samples_df()
            if "seq_limsid" in df.columns:
                matched = df["seq_limsid"].apply(
                    lambda cell: _seq_limsid_matches(cell, seq_ids)
                ).sum()
            else:
                matched = 0
            label = run_filter_label.get()
            run_desc = f" (run {label})" if label else ""
            extra.append(f"Run filter{run_desc}: {matched} samples")

        project_ids = project_filter_ids.get()
        if project_ids:
            df = samples_df()
            matched = (
                df["Project LIMS ID"].astype(str).isin(project_ids).sum()
                if "Project LIMS ID" in df.columns
                else 0
            )
            label = project_filter_label.get()
            project_desc = f" ({label})" if label else ""
            extra.append(
                f"Related samples from selected projects{project_desc}: "
                f"{matched} samples"
            )

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
        found, not_found = _find_batch_filter_matches(df, col, ids)

        batch_filter_ids.set(ids)
        batch_filter_column.set(col)
        batch_filter_non_matches.set(
            {"column": col, "values": not_found} if not_found else None
        )

        # Show results in a modal so the user can review before dismissing
        body_children = [
            ui.p(f"Matched {len(found)} of {len(ids)} IDs in \"{col}\"."),
        ]
        if not_found:
            body_children.append(
                ui.p(
                    ui.tags.strong(f"{len(not_found)} not found: "),
                    ", ".join(not_found),
                )
            )

        footer_children = []
        if not_found:
            footer_children.append(
                ui.download_button(
                    "batch_filter_non_matches_download",
                    "Download non-matches CSV",
                    class_="btn-outline-secondary",
                )
            )
        footer_children.append(ui.modal_button("OK"))

        ui.modal_show(
            ui.modal(
                *body_children,
                title="Batch Filter Applied",
                easy_close=True,
                footer=ui.div(
                    *footer_children,
                    style="display: flex; justify-content: flex-end; gap: 10px;",
                ),
            )
        )

    @render.download(
        filename=lambda: (
            f"batch_filter_non_matches_"
            f"{(batch_filter_non_matches.get() or {'column': 'samples'})['column'].lower().replace(' ', '_')}.csv"
        ),
        media_type="text/csv",
    )
    def batch_filter_non_matches_download():
        non_matches = batch_filter_non_matches.get()
        if non_matches is None:
            yield _batch_filter_non_matches_csv([], "Sample Name")
            return

        yield _batch_filter_non_matches_csv(
            non_matches["values"], non_matches["column"]
        )

    @reactive.Effect
    @reactive.event(input.batch_filter_clear)
    def _clear_batch_filter():
        batch_filter_ids.set(None)
        batch_filter_non_matches.set(None)

    @reactive.Effect
    @reactive.event(input.clear_all_filters_samples)
    def _clear_all_filters():
        batch_filter_ids.set(None)
        batch_filter_non_matches.set(None)
        run_filter_seq_ids.set(None)
        run_filter_label.set(None)
        project_filter_ids.set(None)
        project_filter_label.set(None)

    def set_run_filter(seq_ids, label: str | None = None) -> None:
        """Filter the samples table to rows whose seq_limsid is in ``seq_ids``.

        Called from the Sequencing tab. Clears any active batch filter so the
        run view starts clean; DataTables search/column filters are reset by
        the shared clear-all script when the user dismisses the status bar.
        """
        batch_filter_ids.set(None)
        batch_filter_non_matches.set(None)
        project_filter_ids.set(None)
        project_filter_label.set(None)
        normalized_seq_ids = set()
        for seq_id in seq_ids:
            normalized_seq_ids.update(_split_seq_limsids(seq_id))
        run_filter_seq_ids.set(normalized_seq_ids or None)
        run_filter_label.set(label)

    def set_project_filter(project_ids, label: str | None = None) -> None:
        """Filter Samples to rows belonging to selected projects."""
        batch_filter_ids.set(None)
        batch_filter_non_matches.set(None)
        run_filter_seq_ids.set(None)
        run_filter_label.set(None)
        project_filter_ids.set(
            {
                str(project_id).strip()
                for project_id in project_ids
                if str(project_id).strip()
            }
            or None
        )
        project_filter_label.set(label)

    def get_selected_sample_links(raw_selection):
        """Return project IDs, sequencing IDs, and labels for selected sample rows."""
        selected = None
        payload_valid = False
        try:
            payload = json.loads(raw_selection) if raw_selection else None
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            selected = [
                index for index in payload["rows"]
                if isinstance(index, int)
            ]
            payload_valid = True

        if not payload_valid:
            try:
                selected = list(reactive_read(data_samples.widget, "selected_rows"))
            except Exception:
                selected = None
        if not selected:
            return None

        dat = combined_samples().reset_index(drop=True)
        valid = [index for index in selected if 0 <= index < len(dat)]
        if not valid:
            return None
        rows = dat.iloc[valid]

        project_ids = {
            str(value).strip()
            for value in rows.get("Project LIMS ID", pd.Series(dtype=object)).dropna()
            if str(value).strip()
        }
        seq_ids = set()
        if "seq_limsid" in rows.columns:
            for value in rows["seq_limsid"]:
                seq_ids.update(_split_seq_limsids(value))
        labels = [
            str(value).strip()
            for value in rows.get("Sample Name", pd.Series(dtype=object)).dropna()
            if str(value).strip()
        ]
        return project_ids, seq_ids, labels

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

        # Indices for columns whose content is truncated with a hover tooltip
        nird_filename_index = dat.columns.get_loc("NIRD Filename") if "NIRD Filename" in dat.columns else -1
        experiment_name_index = dat.columns.get_loc("Experiment Name") if "Experiment Name" in dat.columns else -1
        billing_description_index = dat.columns.get_loc("Billing Description") if "Billing Description" in dat.columns else -1
        reagent_label_index = dat.columns.get_loc("Reagent Label") if "Reagent Label" in dat.columns else -1

        return ITable(
                dat,
                select=True,
                layout={"topStart": "buttons", "topEnd": "search", "bottomEnd": None},
                lengthMenu=[[200, 500, 1000, 2000, -1], [200, 500, 1000, 2000, "All"]],
                column_filters="header",
                search={"smart": True},
                # Navigating to another view unmounts this table (app_content renders one
                # view at a time), which would otherwise drop the user's search, column
                # filters, Filter Builder rules and column choices. sessionStorage means
                # it survives navigation but not a new tab. The server-side batch filter
                # is separate state and is not restored with it -- the status bar above
                # the table stays the source of truth for what the server is filtering.
                stateSave=True,
                stateSaveCallback=JavascriptFunction(f"""
                    function(settings, data) {{
                        try {{
                            sessionStorage.setItem('{SAMPLES_TABLE_STATE_KEY}', JSON.stringify(data));
                        }} catch (e) {{}}
                    }}
                """),
                stateLoadCallback=JavascriptFunction(f"""
                    function(settings) {{
                        try {{
                            return JSON.parse(sessionStorage.getItem('{SAMPLES_TABLE_STATE_KEY}'));
                        }} catch (e) {{ return null; }}
                    }}
                """),
                # stateSaveCallback/stateLoadCallback are valid DataTables options that
                # itables just doesn't list in its own TypedDict; it forwards them fine.
                warn_on_undocumented_option=False,
                classes="nowrap compact hover order-column cell-border",
                scrollY="84vh",
                scrollX=True,
                paging=True,
                scroller=True,
                deferRender=True,
                colReorder=True,
                language=FILTER_BUILDER_LANGUAGE,
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
                        # Relabelled "Selection: Custom" by the draw callback
                        # whenever the visible columns are the user's own pick
                        # rather than one of the presets below.
                        "className": "dt-selection-menu",
                        "collectionLayout": "two-column",
                        "columnText": COLVIS_COLUMN_TEXT,
                    },
                    {
                        "extend": "collection",
                        "text": "Presets",
                        # Relabelled with the active preset by the draw callback.
                        "className": "dt-preset-menu",
                        "buttons": [
                            select_all_columns_button(),
                            deselect_all_columns_button(),
                            *(
                                visibility_preset_button(
                                    preset_columns,
                                    dat.columns,
                                    text=preset_text,
                                    table_key="samples",
                                )
                                for preset_text, preset_columns in COLUMN_PRESETS
                            ),
                        ]
                    },
                    {'extend': "spacer",
                     'style': 'bar',
                     'text': 'Filter'},
                    batch_filter_button(),
                    {"extend": "searchBuilder"},
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
                    {'extend': "spacer",
                     'style': 'bar',
                     'text': 'View'},
                    {
                        "extend": "collection",
                        "text": "View selected",
                        "buttons": [
                            {
                                "text": "📁 Projects",
                                "titleAttr": "View projects for the selected sample rows.",
                                "action": JavascriptFunction("""
                                    function(e, dt, node, config) {
                                        Shiny.setInputValue(
                                            'view_sample_projects',
                                            JSON.stringify({
                                                rows: dt.rows({selected: true}).indexes().toArray(),
                                                nonce: Math.random()
                                            }),
                                            {priority: 'event'}
                                        );
                                    }
                                """)
                            },
                            {
                                "text": "🧬 Sequencing runs",
                                "titleAttr": "View sequencing runs for the selected sample rows.",
                                "action": JavascriptFunction("""
                                    function(e, dt, node, config) {
                                        Shiny.setInputValue(
                                            'view_sample_runs',
                                            JSON.stringify({
                                                rows: dt.rows({selected: true}).indexes().toArray(),
                                                nonce: Math.random()
                                            }),
                                            {priority: 'event'}
                                        );
                                    }
                                """)
                            }
                        ]
                    },
                    {'extend': "spacer",
                     'style': 'bar',
                     'text': 'Export'},
                    {
                        "extend": "collection",
                        "text": "📤 Export",
                        "buttons": [
                            {
                                "extend": "csvHtml5",
                                "exportOptions": export_options(),
                                "text": "📄 Export to CSV",
                                "title": "Sample Data Export"
                            },
                            {
                                "extend": "excelHtml5",
                                "exportOptions": export_options(),
                                "text": "📊 Export to Excel",
                                "title": "Sample Data Export"
                            },
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
                drawCallback=filter_state_draw_callback(
                    "samples",
                    default_preset=DEFAULT_COLUMN_PRESET,
                ),
                columnDefs=preset_column_defs(DEFAULT_PRESET_COLUMNS, dat.columns) + [
                    {"className": "dt-center", "targets": "_all"},
                    {"width": "200px", "targets": "_all"},
                    {
                        "targets": date_column_index,
                        "type": "date",
                        "render": DATE_VALUE_RENDERER
                    },
                    {
                        "targets": nird_filename_index,
                        "className": "left-column",
                        "width": "805px",
                        "render": truncated_text_renderer(max_chars=172, max_width_px=805),
                    } if nird_filename_index != -1 else {},
                    {
                        "targets": experiment_name_index,
                        "className": "left-column",
                        "width": "260px",
                        "render": truncated_text_renderer(max_chars=60, max_width_px=260),
                    } if experiment_name_index != -1 else {},
                    {
                        "targets": billing_description_index,
                        "className": "left-column",
                        "width": "320px",
                        "render": truncated_text_renderer(max_chars=100, max_width_px=320),
                    } if billing_description_index != -1 else {},
                    {
                        "targets": reagent_label_index,
                        "className": "left-column",
                        "width": "690px",
                        "render": truncated_text_renderer(max_chars=156, max_width_px=690),
                    } if reagent_label_index != -1 else {},
                ] + searchbuilder_title_defs(dat.columns)
            )

    return {
        "set_run_filter": set_run_filter,
        "set_project_filter": set_project_filter,
        "get_selected_sample_links": get_selected_sample_links,
    }
