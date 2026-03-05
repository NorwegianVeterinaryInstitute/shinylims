'''
reagents.py - Table module containing UI and server logic for the Reagents tab
Allows batch entry of reagent lots for Illumina Clarity LIMS
'''

from shiny import ui, reactive, render
import pandas as pd
from datetime import date
import html
import re

# Import the LIMS API module
from shinylims.data.lims_api import (
    LIMSConfig, 
    create_reagent_lot, 
    test_connection,
    ReagentLotResult,
    get_latest_prep_sequence_status,
    get_latest_index_sequence_status
)
from shinylims.security import get_runtime_user, is_allowed_reagents_user

##############################
# REAGENT CONFIGURATION
##############################

REAGENT_TYPES = {
    "IDT-ILMN DNA/RNA UD Index Sets": {
        "naming_group": "index",
    },
    "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp": {
        "naming_group": "prep",
    },
    "Illumina DNA Prep – PCR + Buffers (EPM, TB1, RSB) 96sp": {
        "naming_group": "prep",
    },
    "Illumina DNA Prep – Tagmentation (M) Beads 96sp": {
        "naming_group": "prep",
    },
    "MiSeq Reagent Kit (Box 1 of 2)": {
        "naming_group": "miseq",
        "requires_rgt_number": True,
        "requires_miseq_kit_type": True
    },
    "MiSeq Reagent Kit (Box 2 of 2)": {
        "naming_group": "miseq",
        "requires_rgt_number": True,
        "requires_miseq_kit_type": True
    },
    "PhiX Control v3": {
        "naming_group": "phix",
        "requires_rgt_number": True
    }
}

PREP_REAGENT_TYPES = [
    reagent_type
    for reagent_type, reagent_info in REAGENT_TYPES.items()
    if reagent_info.get("naming_group") == "prep"
]

# Single source of truth for scanner/dropdown options.
# Add new reagents by adding rows here; selector maps are generated below.
SCANNABLE_REAGENTS = [
    {
        "ref": "20049006",
        "label": "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp (Ref: 20049006)",
        "reagent_type": "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp",
    },
    {
        "ref": "20015829",
        "label": "Illumina DNA Prep – PCR + Buffers (EPM, TB1, RSB) 96sp (Ref: 20015829)",
        "reagent_type": "Illumina DNA Prep – PCR + Buffers (EPM, TB1, RSB) 96sp",
    },
    {
        "ref": "20015880",
        "label": "Illumina DNA Prep – Tagmentation (M) Beads 96sp (Ref: 20015880)",
        "reagent_type": "Illumina DNA Prep – Tagmentation (M) Beads 96sp",
    },
    {
        "ref": "20091646",
        "label": "IDT-ILMN DNA/RNA UD Index Sets - Set A (Ref: 20091646)",
        "reagent_type": "IDT-ILMN DNA/RNA UD Index Sets",
        "set_letter": "A",
    },
    {
        "ref": "20091647",
        "label": "IDT-ILMN DNA/RNA UD Index Sets - Set B (Ref: 20091647)",
        "reagent_type": "IDT-ILMN DNA/RNA UD Index Sets",
        "set_letter": "B",
    },
    {
        "ref": "20091648",
        "label": "IDT-ILMN DNA/RNA UD Index Sets - Set C (Ref: 20091648)",
        "reagent_type": "IDT-ILMN DNA/RNA UD Index Sets",
        "set_letter": "C",
    },
    {
        "ref": "20091649",
        "label": "IDT-ILMN DNA/RNA UD Index Sets - Set D (Ref: 20091649)",
        "reagent_type": "IDT-ILMN DNA/RNA UD Index Sets",
        "set_letter": "D",
    },
    {
        "ref": "15043895",
        "label": "MiSeq Reagent Kit v3 (Box 1 of 2) (Ref: 15043895)",
        "reagent_type": "MiSeq Reagent Kit (Box 1 of 2)",
        "miseq_kit_type": "v3",
    },
    {
        "ref": "15043894",
        "label": "MiSeq Reagent Kit v3 (Box 2 of 2) (Ref: 15043894)",
        "reagent_type": "MiSeq Reagent Kit (Box 2 of 2)",
        "miseq_kit_type": "v3",
    },
    {
        "ref": "11111111",
        "label": "MiSeq Reagent Kit v2 nano (Box 1 of 2) (Ref: 11111111)",
        "reagent_type": "MiSeq Reagent Kit (Box 1 of 2)",
        "miseq_kit_type": "v2 nano",
    },
    {
        "ref": "15036714",
        "label": "MiSeq Reagent Kit v2 nano (Box 2 of 2) (Ref: 15036714)",
        "reagent_type": "MiSeq Reagent Kit (Box 2 of 2)",
        "miseq_kit_type": "v2 nano",
    },
    {
        "ref": "22222222",
        "label": "MiSeq Reagent Kit v2 micro (Box 1 of 2) (Ref: 22222222)",
        "reagent_type": "MiSeq Reagent Kit (Box 1 of 2)",
        "miseq_kit_type": "v2 micro",
    },
    {
        "ref": "33333333",
        "label": "MiSeq Reagent Kit v2 micro (Box 2 of 2) (Ref: 33333333)",
        "reagent_type": "MiSeq Reagent Kit (Box 2 of 2)",
        "miseq_kit_type": "v2 micro",
    },
    {
        "ref": "15017666",
        "label": "PhiX Control v3 (Ref: 15017666)",
        "reagent_type": "PhiX Control v3",
    },
]


def _build_reagent_selector_maps():
    choices = {"": ""}
    selector_to_reagent = {}
    selector_to_miseq_kit_type = {}

    for item in SCANNABLE_REAGENTS:
        ref = item["ref"]
        choices[ref] = item["label"]
        selector_to_reagent[ref] = (item["reagent_type"], item.get("set_letter"))
        miseq_kit_type = item.get("miseq_kit_type")
        if miseq_kit_type:
            selector_to_miseq_kit_type[ref] = miseq_kit_type

    return choices, selector_to_reagent, selector_to_miseq_kit_type


REAGENT_SELECTOR_CHOICES, SELECTOR_TO_REAGENT, SELECTOR_TO_MISEQ_KIT_TYPE = _build_reagent_selector_maps()


##############################
# UI REAGENTS
##############################

def reagents_ui():
    return ui.div(
        ui.h4("📦 Reagent Lot Registration", class_="mb-3"),
        
        # Compact system status
        ui.output_ui("system_status_panel"),
        
        # Main layout
        ui.layout_columns(
            # LEFT PANEL - Quick Add Form
            ui.card(
                ui.card_header("Add New Lot"),
                ui.card_body(
                    ui.input_selectize(
                        "reagent_selector",
                        "Reagent Type / Scan Ref Barcode",
                        choices=REAGENT_SELECTOR_CHOICES,
                        selected="",
                        width="100%",
                        options={
                            "create": True,
                            "persist": False,
                            "allowEmptyOption": True,
                            "placeholder": "Select reagent or scan ref barcode"
                        }
                    ),
                    ui.tags.script(
                        """
                        (function() {
                          const bindClearOnOpen = () => {
                            const el = document.getElementById('reagent_selector');
                            if (!el || !el.selectize) return false;
                            const sel = el.selectize;
                            if (sel._clearOnOpenBound) return true;

                            sel._clearOnOpenBound = true;
                            // Mitigate password-manager/autofill heuristics on this scanner field.
                            sel.$control_input.attr('autocomplete', 'off');
                            sel.$control_input.attr('autocorrect', 'off');
                            sel.$control_input.attr('autocapitalize', 'none');
                            sel.$control_input.attr('spellcheck', 'false');
                            sel.$control_input.attr('name', 'reagent_scan_input');
                            sel.$control_input.attr('data-lpignore', 'true');
                            sel.$control_input.attr('data-1p-ignore', 'true');
                            sel.on('dropdown_open', function() {
                              if (sel.getValue()) {
                                sel.clear(true);
                              }
                            });
                            return true;
                          };

                          if (!bindClearOnOpen()) {
                            const iv = setInterval(() => {
                              if (bindClearOnOpen()) clearInterval(iv);
                            }, 200);
                            setTimeout(() => clearInterval(iv), 5000);
                          }
                        })();
                        """
                    ),
                    ui.output_ui("rgt_number_ui"),
                    
                    ui.input_text(
                        "lot_number",
                        "Lot Number",
                        placeholder="Scan Lot Number",
                        width="100%"
                    ),
                    ui.tags.style(
                        """
                        #lot_number::placeholder {
                          color: #6c757d;
                          opacity: 1;
                        }
                        #lot_number::-webkit-input-placeholder {
                          color: #6c757d;
                        }
                        #lot_number::-moz-placeholder {
                          color: #6c757d;
                          opacity: 1;
                        }
                        #lot_number:-ms-input-placeholder {
                          color: #6c757d;
                        }
                        """
                    ),
                    
                    ui.layout_columns(
                        ui.input_date(
                            "received_date",
                            "Received Date",
                            value=date.today()
                        ),
                        ui.input_date(
                            "expiry_date",
                            "Expiry Date",
                            value=None
                        ),
                        col_widths=[6, 6]
                    ),
                    ui.tags.script(
                        """
                        (function() {
                          function positionExpiryDatepicker() {
                            const input = document.getElementById('expiry_date');
                            if (!input) return;

                            const pickers = Array.from(document.querySelectorAll('.datepicker-dropdown'));
                            if (!pickers.length) return;

                            // Bootstrap datepicker appends to body; grab currently visible popup.
                            const picker = pickers.find((el) => el.offsetParent !== null) || pickers[pickers.length - 1];
                            if (!picker) return;

                            const rect = input.getBoundingClientRect();
                            const top = window.scrollY + rect.bottom + 6;
                            const left = window.scrollX + rect.left;

                            picker.style.top = `${top}px`;
                            picker.style.left = `${left}px`;
                          }

                          const bind = () => {
                            const input = document.getElementById('expiry_date');
                            if (!input) return false;
                            if (input._expiryDatepickerBound) return true;
                            input._expiryDatepickerBound = true;

                            input.addEventListener('focus', () => setTimeout(positionExpiryDatepicker, 0));
                            input.addEventListener('click', () => setTimeout(positionExpiryDatepicker, 0));
                            window.addEventListener('scroll', positionExpiryDatepicker, { passive: true });
                            window.addEventListener('resize', positionExpiryDatepicker);

                            document.addEventListener('click', () => setTimeout(positionExpiryDatepicker, 0), true);
                            return true;
                          };

                          if (!bind()) {
                            const iv = setInterval(() => {
                              if (bind()) clearInterval(iv);
                            }, 200);
                            setTimeout(() => clearInterval(iv), 6000);
                          }
                        })();
                        """
                    ),
                    
                    ui.div(
                        ui.strong("Internal Name: "),
                        ui.output_text("preview_internal_name", inline=True),
                        class_="mt-3 p-2 bg-light rounded"
                    ),
                    
                    ui.div(
                        ui.input_action_button(
                            "add_lot",
                            "➕ Add to Queue",
                            class_="btn-primary w-100 mt-3"
                        ),
                        class_="d-grid"
                    )
                )
            ),
            
            # RIGHT PANEL - Pending Lots Queue
            ui.card(
                ui.card_header(
                    ui.div(
                        ui.span("Pending Lots Queue "),
                        ui.output_text("queue_count", inline=True),
                        style="display: flex; justify-content: space-between; align-items: center;"
                    )
                ),
                ui.card_body(
                    ui.div(
                        ui.div(
                            ui.output_ui("pending_lots_table"),
                            style="width: 100%; overflow-x: auto;"
                        ),
                        ui.div(
                            ui.hr(),
                            ui.output_ui("submit_progress_indicator"),
                            ui.layout_columns(
                                ui.input_action_button(
                                    "print_queue",
                                    "🖨️ Print Queue",
                                    class_="btn-outline-secondary",
                                    onclick="""
                                    const container = document.getElementById('pending_queue_printable');
                                    if (!container) return;
                                    const sourceTable = container.querySelector('table');
                                    if (!sourceTable) return;
                                    const table = sourceTable.cloneNode(true);

                                    // Remove Action column from print view.
                                    table.querySelectorAll('thead tr').forEach((tr) => {
                                      if (tr.cells.length > 0) tr.deleteCell(tr.cells.length - 1);
                                    });
                                    table.querySelectorAll('tbody tr').forEach((tr) => {
                                      if (tr.cells.length > 0) tr.deleteCell(tr.cells.length - 1);
                                    });

                                    const userMeta = document.getElementById('lims_user_meta');
                                    const limsUser = userMeta ? userMeta.textContent.trim() : 'Unknown';
                                    const printDate = new Date().toLocaleString();
                                    const esc = (s) => String(s)
                                      .replace(/&/g, '&amp;')
                                      .replace(/</g, '&lt;')
                                      .replace(/>/g, '&gt;')
                                      .replace(/"/g, '&quot;')
                                      .replace(/'/g, '&#39;');
                                    const win = window.open('', '_blank');
                                    if (!win) return;
                                    win.document.write(`
                                      <html>
                                      <head>
                                        <title>Pending Reagent Lots Queue</title>
                                        <style>
                                          body { font-family: Arial, sans-serif; margin: 20px; }
                                          h2 { margin-bottom: 12px; }
                                          table { width: 100%; border-collapse: collapse; table-layout: fixed; }
                                          th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
                                          th { background: #f2f2f2; }
                                        </style>
                                      </head>
                                      <body>
                                        <h2>Pending Reagent Lots Queue</h2>
                                        <p><strong>Printed:</strong> ${esc(printDate)}</p>
                                        <p><strong>LIMS User:</strong> ${esc(limsUser)}</p>
                                        ${table.outerHTML}
                                      </body>
                                      </html>
                                    `);
                                    win.document.close();
                                    win.focus();
                                    win.print();
                                    win.close();
                                    """
                                ),
                                ui.input_action_button(
                                    "clear_queue",
                                    "🗑️ Clear All",
                                    class_="btn-outline-danger"
                                ),
                                ui.output_ui("submit_button_ui"),
                                col_widths=[4, 4, 4]
                            ),
                            class_="mt-auto",
                            style="margin-top: 28px;"
                        ),
                        class_="d-flex flex-column",
                        style="min-height: 500px;"
                    ),
                )
            ),
            col_widths=[5, 7]
        ),
        
        # Submission results (shows after submit)
        ui.output_ui("submission_results_ui"),
        
        class_="p-3"
    )


##############################
# SERVER REAGENTS
##############################

def reagents_server(input, output, session):
    
    # LIMS/auth state
    lims_config = reactive.Value(None)
    # (status_code, details) where status_code is "connected" | "missing" | "failed"
    lims_connection_status = reactive.Value(("missing", "Missing credentials"))
    prep_sequence_state = reactive.Value((False, "Not checked"))
    index_sequence_state = reactive.Value((False, "Not checked", None))
    
    # Reactive values
    pending_lots = reactive.Value(pd.DataFrame(columns=[
        "Reagent Type", "Lot Number",
        "Received Date", "Expiry Date", "Internal Name", "Set Letter",
        "MiSeq Kit Type", "RGT Number"
    ]))
    
    last_reagent_type = reactive.Value(None)

    submission_results = reactive.Value([])
    submit_check_in_progress = reactive.Value(False)
    submit_in_progress = reactive.Value(False)
    
    # Latest sequence numbers loaded from LIMS after login/check.
    sequence_numbers = reactive.Value({
        "prep": 0,
        "index": 0
    })
    
    pending_sequence_offsets = reactive.Value({
        "prep": 0,
        "index": 0
    })

    def recalculate_index_offsets():
        """Recalculate index offsets from current pending queue."""
        df = pending_lots.get()
        offsets = {
            "prep": 0,
            "index": 0
        }

        if not df.empty and "Set Letter" in df.columns:
            index_type = "IDT-ILMN DNA/RNA UD Index Sets"
            count = int((df["Reagent Type"] == index_type).sum())
            offsets["index"] = count

        pending_sequence_offsets.set(offsets)

    def extract_internal_sequence(name: str) -> int | None:
        """Extract sequence number from internal name like '#12 (192)'."""
        if not isinstance(name, str):
            return None
        match = re.search(r"#(\d+)", name)
        return int(match.group(1)) if match else None
    
    def current_runtime_username() -> str | None:
        username, _ = get_runtime_user(session)
        return username

    def show_unauthorized(action: str = "perform this action"):
        ui.notification_show(f"Unauthorized: you are not allowed to {action}.", type="error", duration=6)

    def ensure_authorized(action: str) -> bool:
        if is_allowed_reagents_user(session):
            return True
        show_unauthorized(action)
        return False

    def _missing_env_fields(config: LIMSConfig) -> list[str]:
        missing = []
        if not (config.base_url or "").strip():
            missing.append("LIMS_BASE_URL")
        if not (config.username or "").strip():
            missing.append("LIMS_API_USER")
        if not (config.password or ""):
            missing.append("LIMS_API_PASS")
        return missing

    def _is_lims_ready() -> bool:
        status_code, _ = lims_connection_status.get()
        return bool(lims_config.get() is not None and status_code == "connected")

    def refresh_lims_connection(notify: bool = False) -> bool:
        config = LIMSConfig.get_credentials()
        missing = _missing_env_fields(config)
        if missing:
            lims_config.set(None)
            lims_connection_status.set(("missing", f"Missing credentials: {', '.join(missing)}"))
            prep_sequence_state.set((False, "Not checked"))
            index_sequence_state.set((False, "Not checked", None))
            if notify:
                ui.notification_show("Missing credentials in environment variables", type="warning", duration=6)
            return False

        lims_config.set(config)
        success, message = test_connection(config)
        if not success:
            lims_connection_status.set(("failed", "Connection failed"))
            prep_sequence_state.set((False, "Not checked"))
            index_sequence_state.set((False, "Not checked", None))
            if notify:
                ui.notification_show("LIMS connection failed", type="error", duration=6)
            return False

        lims_connection_status.set(("connected", "Connected to LIMS"))
        return True

    def refresh_prep_sequence_state(config):
        status = get_latest_prep_sequence_status(config, PREP_REAGENT_TYPES)

        if status.success and status.latest_complete_sequence is not None:
            seq_nums = sequence_numbers.get().copy()
            seq_nums["prep"] = status.latest_complete_sequence
            sequence_numbers.set(seq_nums)
            prep_sequence_state.set((True, status.message))
            return True

        prep_sequence_state.set((False, status.message))
        return False

    def refresh_index_sequence_state(config):
        status = get_latest_index_sequence_status(config)
        if not status.success:
            index_sequence_state.set((False, status.message, None))
            return False, status.message

        seq_nums = sequence_numbers.get().copy()
        if status.latest_sequence is not None:
            seq_nums["index"] = status.latest_sequence
        sequence_numbers.set(seq_nums)
        index_sequence_state.set((True, status.message, status.latest_sequence))
        return True, status.message

    @reactive.Effect
    @reactive.event(input.open_tool_reagents)
    def init_lims_from_env_on_reagents_open():
        if not is_allowed_reagents_user(session):
            return
        ui.modal_show(
            ui.modal(
                ui.div(
                    ui.tags.div(class_="spinner-border text-primary me-2", role="status", aria_hidden="true"),
                    ui.span("Please wait... logging into LIMS API and doing reagents status checks."),
                    class_="d-flex align-items-center"
                ),
                title="Loading Reagents",
                easy_close=False,
                footer=None
            )
        )
        try:
            if refresh_lims_connection(notify=False):
                config = lims_config.get()
                refresh_prep_sequence_state(config)
                refresh_index_sequence_state(config)
        finally:
            ui.modal_remove()

    @reactive.Effect
    @reactive.event(input.refresh_prep_sequence)
    def refresh_prep_sequence():
        if not ensure_authorized("refresh LIMS checks"):
            return
        if submit_in_progress.get():
            ui.notification_show("Submission is in progress; wait before refreshing checks.", type="warning")
            return
        if submit_check_in_progress.get():
            ui.notification_show("A check is already in progress.", type="warning")
            return

        submit_check_in_progress.set(True)
        config = lims_config.get()
        try:
            if not refresh_lims_connection(notify=True):
                return

            config = lims_config.get()
            if refresh_prep_sequence_state(config):
                ui.notification_show("Prep sequence status refreshed", type="message", duration=3)
            else:
                ui.notification_show(
                    "Prep sequence check failed. Clean up LIMS prep lots before submitting.",
                    type="warning",
                    duration=8
                )

            index_ok, index_message = refresh_index_sequence_state(config)
            if not index_ok:
                ui.notification_show(
                    f"Index sequence refresh failed: {index_message}",
                    type="warning",
                    duration=8
                )
        finally:
            submit_check_in_progress.set(False)

    @reactive.Effect
    def reset_expiry_on_reagent_type_change():
        reagent_type, _ = get_selected_reagent()
        previous = last_reagent_type.get()

        if previous is None:
            last_reagent_type.set(reagent_type)
            return

        if reagent_type != previous:
            ui.update_date("expiry_date", value=date.today())
            last_reagent_type.set(reagent_type)

    @output
    @render.ui
    def system_status_panel():
        config = lims_config.get()
        lims_status, lims_message = lims_connection_status.get()
        prep_ok, prep_message = prep_sequence_state.get()
        seq_num = sequence_numbers.get().get("prep", 0)
        index_ok, index_message, index_latest = index_sequence_state.get()

        if lims_status == "connected":
            lims_badge = ui.span("Connected to LIMS", class_="badge text-bg-success")
            lims_summary = config.base_url if config else "Configured"
        elif lims_status == "missing":
            lims_badge = ui.span("Missing credentials", class_="badge text-bg-warning")
            lims_summary = lims_message
        else:
            lims_badge = ui.span("Connection failed", class_="badge text-bg-danger")
            lims_summary = lims_message

        if _is_lims_ready():
            if prep_ok:
                prep_badge = ui.span("Prep Check Passed", class_="badge text-bg-success")
                prep_summary = f"Latest full set: #{seq_num}. Next: #{seq_num + 1}"
            else:
                prep_badge = ui.span("Prep Check Failed", class_="badge text-bg-danger")
                prep_summary = prep_message
        else:
            prep_badge = ui.span("Prep Check Pending", class_="badge text-bg-secondary")
            prep_summary = "Available after LIMS connection."

        if _is_lims_ready():
            if index_ok and index_latest is not None:
                index_badge = ui.span("Index Ready", class_="badge text-bg-success")
                index_summary = f"Latest: #{index_latest}. Next: #{index_latest + 1}"
            elif index_ok:
                index_badge = ui.span("Index Ready", class_="badge text-bg-success")
                index_summary = index_message
            else:
                index_badge = ui.span("Index Check Failed", class_="badge text-bg-danger")
                index_summary = index_message
        else:
            index_badge = ui.span("Index Check Pending", class_="badge text-bg-secondary")
            index_summary = "Available after LIMS connection."

        refresh_button = ui.input_action_button(
            "refresh_prep_sequence",
            "Refresh Prep Check",
            class_="btn-sm btn-outline-secondary",
            disabled=submit_check_in_progress.get() or submit_in_progress.get()
        )

        details_body = ui.div(
            ui.p(ui.strong("LIMS: "), lims_summary, class_="mb-1 small"),
            ui.p(ui.strong("Prep: "), prep_summary, class_="mb-1 small"),
            ui.p(ui.strong("Index: "), index_summary, class_="mb-0 small"),
            class_="mt-2"
        )

        return ui.div(
            ui.div(
                ui.div(
                    lims_badge,
                    prep_badge,
                    index_badge,
                    class_="d-flex flex-wrap align-items-center gap-2"
                ),
                ui.div(
                    refresh_button,
                    class_="d-flex align-items-center gap-2"
                ),
                style="display:flex; align-items:center; justify-content:space-between; gap:10px;"
            ),
            ui.tags.details(
                ui.tags.summary("Details", class_="small text-muted"),
                details_body
            ),
            ui.tags.span(current_runtime_username() or "unknown", id="lims_user_meta", style="display:none;"),
            class_="mb-3 p-2 border rounded bg-light-subtle"
        )

    def get_selected_reagent():
        selector_value = (input.reagent_selector() or "").strip()
        if not selector_value:
            return (None, None)

        if selector_value in SELECTOR_TO_REAGENT:
            return SELECTOR_TO_REAGENT[selector_value]

        # Fallback for scanner inputs that may include extra text around the ref id.
        match = re.search(r"(\d{8})", selector_value)
        if match:
            barcode = match.group(1)
            return SELECTOR_TO_REAGENT.get(barcode, (None, None))

        return (None, None)

    def get_selected_miseq_kit_type():
        selector_value = (input.reagent_selector() or "").strip()
        if not selector_value:
            return None

        if selector_value in SELECTOR_TO_MISEQ_KIT_TYPE:
            return SELECTOR_TO_MISEQ_KIT_TYPE[selector_value]

        match = re.search(r"(\d{8})", selector_value)
        if not match:
            return None
        return SELECTOR_TO_MISEQ_KIT_TYPE.get(match.group(1))

    @output
    @render.ui
    def rgt_number_ui():
        reagent_type, _ = get_selected_reagent()
        if not reagent_type:
            return None

        reagent_info = REAGENT_TYPES.get(reagent_type, {})
        if reagent_info.get("requires_rgt_number"):
            field = ui.input_text(
                "rgt_number",
                "RGT Number",
                placeholder="Scan RGT Number (e.g., RGT36182951)",
                width="100%"
            )
            return ui.TagList(
                field,
                ui.tags.style(
                    """
                    #rgt_number::placeholder {
                      color: #6c757d;
                      opacity: 1;
                    }
                    #rgt_number::-webkit-input-placeholder {
                      color: #6c757d;
                    }
                    #rgt_number::-moz-placeholder {
                      color: #6c757d;
                      opacity: 1;
                    }
                    #rgt_number:-ms-input-placeholder {
                      color: #6c757d;
                    }
                    """
                )
            )
        return None

    def can_generate_internal_names(reagent_type):
        if not is_allowed_reagents_user(session):
            return False
        if not _is_lims_ready():
            return False

        reagent_info = REAGENT_TYPES.get(reagent_type, {})
        naming_group = reagent_info.get("naming_group")
        if naming_group in {"prep", "index"}:
            prep_ok, _ = prep_sequence_state.get()
            index_ok, _, _ = index_sequence_state.get()
            return prep_ok and index_ok

        return True

    @output
    @render.ui
    def submit_button_ui():
        if not is_allowed_reagents_user(session):
            return ui.input_action_button(
                "submit_to_lims",
                "Unauthorized",
                class_="btn-secondary disabled",
                disabled=True
            )

        if not _is_lims_ready():
            return ui.input_action_button(
                "submit_to_lims",
                "LIMS unavailable",
                class_="btn-secondary disabled",
                disabled=True
            )

        if submit_check_in_progress.get() or submit_in_progress.get():
            return ui.input_action_button(
                "submit_to_lims",
                "Working...",
                class_="btn-secondary disabled",
                disabled=True
            )

        return ui.input_action_button(
            "submit_to_lims",
            "Next",
            class_="btn-success"
        )

    @output
    @render.ui
    def confirm_submit_button_ui():
        return ui.input_action_button(
            "confirm_submit",
            "Submit to LIMS",
            class_="btn-success ms-2",
            disabled=submit_check_in_progress.get() or submit_in_progress.get()
        )

    @output
    @render.ui
    def submit_progress_indicator():
        if not submit_check_in_progress.get():
            return None
        return ui.div(
            ui.tags.span(
                class_="spinner-border spinner-border-sm me-2",
                role="status",
                aria_hidden="true"
            ),
            ui.span("Checking LIMS status before confirmation..."),
            class_="d-flex align-items-center text-muted small mb-2"
        )
    
    # Naming logic
    def get_next_prep_sequence_number(reagent_type: str):
        """Prep numbering is based on count per prep reagent type in queue."""
        seq_nums = sequence_numbers.get()
        base_num = seq_nums.get("prep", 0)
        df = pending_lots.get()
        type_count = int((df["Reagent Type"] == reagent_type).sum())
        return base_num + type_count + 1

    def get_next_sequence_number(naming_group, set_letter=None, reagent_type=None):
        seq_nums = sequence_numbers.get()
        offsets = pending_sequence_offsets.get()
        
        if naming_group == "prep":
            return get_next_prep_sequence_number(reagent_type)

        if naming_group == "index":
            key = "index"
        else:
            key = naming_group
            
        base_num = seq_nums.get(key, 0)
        offset = offsets.get(key, 0)
        return base_num + offset + 1
    
    def generate_internal_name(reagent_type, set_letter=None, miseq_kit_type=None, rgt_number=None):
        reagent_info = REAGENT_TYPES.get(reagent_type, {})
        naming_group = reagent_info.get("naming_group", "unknown")

        if naming_group == "miseq":
            rgt = (rgt_number or "").strip()
            kit_type = (miseq_kit_type or "").strip()
            if not rgt or not kit_type:
                return "Provide RGT Number and MiSeq Kit Type"
            return f"{rgt} {kit_type}"
        if naming_group == "phix":
            rgt = (rgt_number or "").strip()
            if not rgt:
                return "Provide RGT Number"
            return rgt

        next_num = get_next_sequence_number(naming_group, set_letter, reagent_type)
        
        if naming_group == "index" and set_letter:
            return f"{set_letter}#{next_num} (192)"
        else:
            return f"#{next_num} (192)"
    
    @output
    @render.text
    def preview_internal_name():
        reagent_type, set_letter = get_selected_reagent()
        if not reagent_type:
            return "Select a reagent type"
        if not can_generate_internal_names(reagent_type):
            return "Log in to LIMS and refresh checks to load latest numbering"

        reagent_info = REAGENT_TYPES.get(reagent_type, {})
        miseq_kit_type = None
        rgt_number = None
        if reagent_info.get("requires_miseq_kit_type"):
            miseq_kit_type = get_selected_miseq_kit_type()
        if reagent_info.get("requires_rgt_number"):
            rgt_number = input.rgt_number()

        return generate_internal_name(reagent_type, set_letter, miseq_kit_type, rgt_number)
    
    # Add lot to queue
    @reactive.Effect
    @reactive.event(input.add_lot)
    def add_lot_to_queue():
        if not ensure_authorized("add lots to the queue"):
            return
        if submit_in_progress.get():
            ui.notification_show("Submission in progress; wait before editing the queue.", type="warning")
            return

        if not input.lot_number():
            ui.notification_show("Please enter a lot number", type="warning")
            return
        
        if not input.expiry_date():
            ui.notification_show("Please enter an expiry date", type="warning")
            return
        if str(input.expiry_date()) == str(date.today()):
            ui.notification_show(
                "Expiry Date cannot be today's date. Please choose the actual reagent expiry date.",
                type="warning",
                duration=5
            )
            return
        
        reagent_type, set_letter = get_selected_reagent()
        if not reagent_type:
            ui.notification_show("Please select a reagent type or scan a valid ref barcode", type="warning")
            return

        if not can_generate_internal_names(reagent_type):
            ui.notification_show(
                "Log in to LIMS and refresh checks before assigning Internal Names",
                type="warning",
                duration=5
            )
            return
        reagent_info = REAGENT_TYPES[reagent_type]

        miseq_kit_type = None
        rgt_number = None
        if reagent_info.get("requires_miseq_kit_type"):
            miseq_kit_type = (get_selected_miseq_kit_type() or "").strip()
            if not miseq_kit_type:
                ui.notification_show("Could not resolve MiSeq kit type from selected/scanned reagent ref", type="warning")
                return
        if reagent_info.get("requires_rgt_number"):
            rgt_number = (input.rgt_number() or "").strip()
            if not rgt_number:
                ui.notification_show("Please scan RGT number for MiSeq kit", type="warning")
                return
            if not rgt_number.upper().startswith("RGT"):
                ui.notification_show("RGT number must start with 'RGT'", type="warning")
                return
            rgt_number = rgt_number.upper()
        
        internal_name = generate_internal_name(reagent_type, set_letter, miseq_kit_type, rgt_number)
        
        # Update offsets
        offsets = pending_sequence_offsets.get().copy()
        naming_group = reagent_info.get("naming_group")
        
        if naming_group == "index":
            key = "index"
            offsets[key] = offsets.get(key, 0) + 1
            pending_sequence_offsets.set(offsets)
        
        current_df = pending_lots.get().copy()
        new_row = pd.DataFrame([{
            "Reagent Type": reagent_type,
            "Lot Number": input.lot_number(),
            "Received Date": str(input.received_date()),
            "Expiry Date": str(input.expiry_date()),
            "Internal Name": internal_name,
            "Set Letter": set_letter,
            "MiSeq Kit Type": miseq_kit_type,
            "RGT Number": rgt_number
        }])
        
        updated_df = pd.concat([current_df, new_row], ignore_index=True)
        pending_lots.set(updated_df)
        
        ui.update_text("lot_number", value="")
        ui.notification_show(f"Added: {internal_name}", type="message", duration=2)
    
    # Clear queue
    @reactive.Effect
    @reactive.event(input.clear_queue)
    def clear_queue():
        pending_lots.set(pd.DataFrame(columns=[
            "Reagent Type", "Lot Number",
            "Received Date", "Expiry Date", "Internal Name", "Set Letter",
            "MiSeq Kit Type", "RGT Number"
        ]))
        pending_sequence_offsets.set({
            "prep": 0,
            "index": 0
        })
        submission_results.set([])
    
    @output
    @render.text
    def queue_count():
        count = len(pending_lots.get())
        return f"({count} lots)"
    
    @output
    @render.ui
    def pending_lots_table():
        df = pending_lots.get()
        
        if df.empty:
            return ui.p(
                "No lots in queue. Add lots using the form.",
                class_="text-muted text-center py-4"
            )
        
        display_df = df[["Internal Name", "Reagent Type", "Lot Number", "Expiry Date"]].copy()
        
        table_html = """
        <table class="table table-sm table-striped table-hover" style="width: 100%; table-layout: fixed;">
            <thead>
                <tr>
                    <th style="width: 22%;">Internal Name</th>
                    <th style="width: 24%;">Type</th>
                    <th style="width: 22%;">Lot Number</th>
                    <th style="width: 20%;">Expiry</th>
                    <th style="width: 12%;">Action</th>
                </tr>
            </thead>
            <tbody>
        """
        
        for idx, row in display_df.iterrows():
            internal_name = html.escape(str(row["Internal Name"]))
            reagent_type = html.escape(str(row["Reagent Type"]))
            lot_number = html.escape(str(row["Lot Number"]))
            expiry_date = html.escape(str(row["Expiry Date"]))
            table_html += f"""
                <tr>
                    <td><strong>{internal_name}</strong></td>
                    <td>{reagent_type}</td>
                    <td>{lot_number}</td>
                    <td>{expiry_date}</td>
                    <td>
                        <button
                            type="button"
                            class="btn btn-sm btn-outline-danger"
                            onclick="Shiny.setInputValue('remove_lot_idx', {idx}, {{priority: 'event'}})">
                            Remove
                        </button>
                    </td>
                </tr>
            """
        
        table_html += "</tbody></table>"
        
        return ui.HTML(f'<div id="pending_queue_printable" style="max-height: 300px; overflow-y: auto;">{table_html}</div>')

    @reactive.Effect
    @reactive.event(input.remove_lot_idx)
    def remove_lot_from_queue():
        idx = input.remove_lot_idx()
        df = pending_lots.get().copy()

        if df.empty:
            return

        try:
            idx = int(idx)
        except (TypeError, ValueError):
            return

        if idx < 0 or idx >= len(df):
            return

        row = df.iloc[idx]
        reagent_type = row["Reagent Type"]
        reagent_info = REAGENT_TYPES.get(reagent_type, {})
        naming_group = reagent_info.get("naming_group")
        if naming_group in {"prep", "index"}:
            group_types = [
                rtype for rtype, rinfo in REAGENT_TYPES.items()
                if rinfo.get("naming_group") == naming_group
            ]
            group_rows = df[df["Reagent Type"].isin(group_types)]
            group_numbers = [
                extract_internal_sequence(name)
                for name in group_rows["Internal Name"].tolist()
            ]
            group_numbers = [n for n in group_numbers if n is not None]

            if group_numbers:
                latest_group_num = max(group_numbers)
                row_num = extract_internal_sequence(row["Internal Name"])
                if row_num != latest_group_num:
                    label = "prep" if naming_group == "prep" else "index"
                    ui.notification_show(
                        f"For {label} lots, remove the latest number first (#{latest_group_num}).",
                        type="warning",
                        duration=4
                    )
                    return

        removed_name = df.iloc[idx]["Internal Name"]
        df = df.drop(df.index[idx]).reset_index(drop=True)
        pending_lots.set(df)
        recalculate_index_offsets()
        ui.notification_show(f"Removed: {removed_name}", type="message", duration=2)
    
    # Submit to LIMS
    @reactive.Effect
    @reactive.event(input.submit_to_lims)
    def submit_to_lims():
        if not ensure_authorized("submit to LIMS"):
            return
        if submit_in_progress.get():
            ui.notification_show("Submission is already in progress.", type="warning")
            return
        if submit_check_in_progress.get():
            ui.notification_show("Submission check is already in progress.", type="warning")
            return

        df = pending_lots.get()
        
        if df.empty:
            ui.notification_show("No lots to submit", type="warning")
            return
        
        submit_check_in_progress.set(True)

        try:
            with ui.Progress(min=0, max=3) as p:
                p.set(0, message="Preparing submission checks...")

                prep_counts = {
                    reagent_type: int((df["Reagent Type"] == reagent_type).sum())
                    for reagent_type in PREP_REAGENT_TYPES
                }
                if len(set(prep_counts.values())) > 1:
                    details = ", ".join(
                        f"{rt}: {count}"
                        for rt, count in prep_counts.items()
                    )
                    ui.modal_show(
                        ui.modal(
                            ui.p("Pending prep reagents must be submitted as full sets."),
                            ui.p(f"Current queue counts: {details}"),
                            ui.p("Add missing prep reagent types or remove extras before submitting."),
                            title="⚠️ Incomplete Prep Set In Queue",
                            easy_close=True,
                            footer=ui.modal_button("OK")
                        )
                    )
                    return

                p.set(1, message="Validating LIMS login...")
                config = lims_config.get()
                if not refresh_lims_connection(notify=True):
                    ui.notification_show("LIMS is unavailable. Set env credentials and retry.", type="warning")
                    return

                config = lims_config.get()
                if not config:
                    return

                p.set(2, message="Checking current prep/index status in LIMS...")
                # Always re-check current LIMS state before allowing submission.
                refresh_prep_sequence_state(config)
                refresh_index_sequence_state(config)
                prep_ok, prep_message = prep_sequence_state.get()
                if not prep_ok:
                    ui.modal_show(
                        ui.modal(
                            ui.p("Cannot submit new reagents while Illumina DNA Prep reagents are incomplete/misaligned."),
                            ui.p(prep_message),
                            ui.p("Please clean up the prep reagents in Clarity LIMS, then re-check."),
                            title="⚠️ Prep Reagent Set Incomplete",
                            easy_close=True,
                            footer=ui.modal_button("OK")
                        )
                    )
                    return

                p.set(3, message="Opening confirmation...")

            confirm_df = df[["Internal Name", "Reagent Type", "Lot Number"]].copy()
            confirm_table = confirm_df.to_html(
                index=False,
                escape=True,
                classes="table table-sm table-striped table-bordered confirm-submit-table",
                border=0
            )

            ui.modal_show(
                ui.modal(
                    ui.div(
                        ui.p(f"Submit {len(df)} lot(s) to Clarity LIMS?"),
                        ui.div(
                            ui.strong("⚠️ Remember: "),
                            "Label your physical reagent boxes with the Internal Names before submitting.",
                            class_="alert alert-warning py-2 px-3 mb-3"
                        ),
                        ui.HTML(f"""
                            <style>
                                .confirm-submit-wrap {{
                                    max-height: 45vh;
                                    overflow-y: auto;
                                    overflow-x: auto;
                                }}
                                .confirm-submit-table {{
                                    width: 100%;
                                    table-layout: fixed;
                                    margin-bottom: 0;
                                }}
                                .confirm-submit-table th,
                                .confirm-submit-table td {{
                                    text-align: left !important;
                                    vertical-align: middle;
                                }}
                                .confirm-submit-table th {{
                                    position: sticky;
                                    top: 0;
                                    background: #f8f9fa;
                                    z-index: 2;
                                }}
                            </style>
                            <div class="confirm-submit-wrap">{confirm_table}</div>
                        """),
                    )
                    ,
                title="🚀 Confirm Submission",
                easy_close=True,
                size="xl",
                footer=ui.div(
                    ui.modal_button("Cancel", class_="btn-secondary"),
                    ui.output_ui("confirm_submit_button_ui")
                    )
                )
            )
        finally:
            submit_check_in_progress.set(False)
    
    # Actual submission
    @reactive.Effect
    @reactive.event(input.confirm_submit)
    def do_submit():
        if not ensure_authorized("confirm LIMS submission"):
            return
        if submit_in_progress.get():
            ui.notification_show("Submission is already in progress.", type="warning")
            return

        submit_in_progress.set(True)
        ui.modal_remove()
        try:
            if not refresh_lims_connection(notify=True):
                ui.notification_show("LIMS is unavailable. Submission aborted.", type="error")
                return

            df = pending_lots.get()
            config = lims_config.get()
            if df.empty or config is None:
                return

            results = []
            submission_entries = []
            requester = current_runtime_username() or "unknown"

            with ui.Progress(min=0, max=len(df)) as p:
                p.set(message="Submitting to LIMS...")

                for idx, row in df.iterrows():
                    p.set(idx, message=f"Creating {row['Internal Name']}...")

                    result = create_reagent_lot(
                        config=config,
                        name=row["Internal Name"],
                        lot_number=row["Lot Number"],
                        reagent_type=row["Reagent Type"],
                        expiry_date=row["Expiry Date"],
                        storage_location="",
                        notes=f"Created via Shiny App on {date.today()} by {requester}"
                    )

                    results.append(result)
                    submission_entries.append({
                        "row": row,
                        "result": result
                    })

                p.set(len(df), message="Done!")

            submission_results.set(results)

            # Count successes/failures
            successes = sum(1 for r in results if r.success)
            failures = len(results) - successes

            if failures == 0:
                ui.notification_show(
                    f"✅ All {successes} lots created successfully!",
                    type="message",
                    duration=5
                )
                # Clear the queue on full success
                pending_lots.set(pd.DataFrame(columns=[
                    "Reagent Type", "Lot Number",
                    "Received Date", "Expiry Date", "Internal Name", "Set Letter",
                    "MiSeq Kit Type", "RGT Number"
                ]))
            else:
                ui.notification_show(
                    f"⚠️ {successes} succeeded, {failures} failed",
                    type="warning",
                    duration=10
                )

            result_rows = []
            failed_log_lines = []
            for entry in submission_entries:
                row = entry["row"]
                result = entry["result"]
                status_text = "Success" if result.success else "Failed"
                lims_id = result.lims_id or "-"
                message_text = result.message or "-"
                result_rows.append({
                    "Internal Name": row["Internal Name"],
                    "Type": row["Reagent Type"],
                    "Lot Number": row["Lot Number"],
                    "Status": status_text,
                    "LIMS ID": lims_id,
                    "Message": message_text,
                })
                if not result.success:
                    failed_log_lines.append(
                        f"- {row['Internal Name']} | {row['Reagent Type']} | lot={row['Lot Number']} | {message_text}"
                    )

            result_df = pd.DataFrame(result_rows)
            result_table = result_df.to_html(
                index=False,
                escape=True,
                classes="table table-sm table-striped table-bordered submit-result-table",
                border=0
            )
            logs_text = "\n".join(failed_log_lines) if failed_log_lines else "No errors."
            modal_title = "✅ Submission Complete" if failures == 0 else "⚠️ Submission Completed With Errors"
            summary_class = "alert alert-success py-2 px-3 mb-3" if failures == 0 else "alert alert-warning py-2 px-3 mb-3"
            summary_text = f"{successes} succeeded, {failures} failed."
            print_reminder = (
                "Please print this result now so errors can be reviewed and resolved."
                if failures > 0
                else "Optional: print this result for your records."
            )

            ui.modal_show(
                ui.modal(
                    ui.div(
                        ui.div(summary_text, class_=summary_class),
                        ui.div(print_reminder, class_="alert alert-info py-2 px-3 mb-3"),
                        ui.HTML(f"""
                            <style>
                                .submit-result-wrap {{
                                    max-height: 42vh;
                                    overflow-y: auto;
                                    overflow-x: auto;
                                }}
                                .submit-result-table {{
                                    width: 100%;
                                    table-layout: fixed;
                                    margin-bottom: 0;
                                }}
                                .submit-result-table th,
                                .submit-result-table td {{
                                    text-align: left !important;
                                    vertical-align: middle;
                                }}
                                .submit-result-table th {{
                                    position: sticky;
                                    top: 0;
                                    background: #f8f9fa;
                                    z-index: 2;
                                }}
                            </style>
                            <div id="submit_result_printable" class="submit-result-wrap">{result_table}</div>
                        """),
                        ui.h6("Admin Error Log", class_="mt-3"),
                        ui.tags.pre(
                            logs_text,
                            id="submit_result_error_log",
                            class_="p-2 bg-light border rounded small",
                            style="max-height: 180px; overflow:auto; white-space: pre-wrap;"
                        ),
                    ),
                    title=modal_title,
                    easy_close=True,
                    size="l",
                    footer=ui.div(
                        ui.input_action_button(
                            "print_submit_result",
                            "🖨️ Print Result",
                            class_="btn-outline-secondary",
                            onclick="""
                            const tableWrap = document.getElementById('submit_result_printable');
                            if (!tableWrap) return;
                            const table = tableWrap.querySelector('table');
                            if (!table) return;
                            const logEl = document.getElementById('submit_result_error_log');
                            const logText = logEl ? logEl.textContent : 'No errors.';
                            const summary = tableWrap.parentElement?.querySelector('.alert')?.textContent?.trim() || '';
                            const printDate = new Date().toLocaleString();
                            const esc = (s) => String(s)
                              .replace(/&/g, '&amp;')
                              .replace(/</g, '&lt;')
                              .replace(/>/g, '&gt;')
                              .replace(/"/g, '&quot;')
                              .replace(/'/g, '&#39;');

                            const win = window.open('', '_blank');
                            if (!win) return;
                            win.document.write(`
                              <html>
                              <head>
                                <title>LIMS Submission Result</title>
                                <style>
                                  body { font-family: Arial, sans-serif; margin: 20px; }
                                  h2 { margin-bottom: 10px; }
                                  table { width: 100%; border-collapse: collapse; table-layout: fixed; margin-top: 10px; }
                                  th, td { border: 1px solid #ccc; padding: 8px; text-align: left; word-break: break-word; }
                                  th { background: #f2f2f2; }
                                  pre { white-space: pre-wrap; border: 1px solid #ccc; padding: 8px; background: #fafafa; }
                                </style>
                              </head>
                              <body>
                                <h2>LIMS Submission Result</h2>
                                <p><strong>Printed:</strong> ${esc(printDate)}</p>
                                <p><strong>Summary:</strong> ${esc(summary)}</p>
                                ${table.outerHTML}
                                <h3 style="margin-top: 16px;">Admin Error Log</h3>
                                <pre>${esc(logText)}</pre>
                              </body>
                              </html>
                            `);
                            win.document.close();
                            win.focus();
                            win.print();
                            win.close();
                            """
                        ),
                        ui.modal_button("Close", class_="btn-secondary ms-2")
                    )
                )
            )

            # Refresh prep/index state after submission so next number/status reflects LIMS.
            refresh_prep_sequence_state(config)
            refresh_index_sequence_state(config)
        finally:
            submit_in_progress.set(False)
    
    # Show submission results
    @output
    @render.ui
    def submission_results_ui():
        results = submission_results.get()
        
        if not results:
            return None
        
        rows_html = ""
        for r in results:
            if r.success:
                status_value = html.escape(str(r.lims_id or ""))
                status = f'<span class="text-success">✅ {status_value}</span>'
            else:
                status_value = html.escape(str(r.message or ""))
                status = f'<span class="text-danger">❌ {status_value}</span>'
            
            name_value = html.escape(str(r.name or ""))
            rows_html += f"<tr><td>{name_value}</td><td>{status}</td></tr>"
        
        return ui.card(
            ui.card_header("Submission Results"),
            ui.card_body(
                ui.HTML(f"""
                    <table class="table table-sm">
                        <thead><tr><th>Name</th><th>Status</th></tr></thead>
                        <tbody>{rows_html}</tbody>
                    </table>
                """)
            ),
            class_="mt-3"
        )
    
    return {
        "pending_lots": pending_lots,
        "sequence_numbers": sequence_numbers
    }
