'''
page.py - Table module containing UI and server logic for the Reagents tab
Allows batch entry of reagent lots for Illumina Clarity LIMS
'''

from shiny import ui, reactive, render
import pandas as pd
from datetime import date, datetime, UTC
from urllib.parse import urlparse

# Import the LIMS API module
from shinylims.integrations.lims_api import (
    LIMSConfig, 
    create_reagent_lot, 
    get_reagent_sequence_statuses,
    test_connection,
)
from shinylims.config.reagents import (
    PREP_REAGENT_TYPES,
    REAGENT_SELECTOR_CHOICES,
    REAGENT_TYPES,
)
from shinylims.features.reagents.domain import (
    can_generate_internal_names,
    empty_pending_lots_df,
    generate_internal_name,
    get_prep_queue_mismatch_details,
    get_queue_removal_error,
    increment_pending_offsets,
    recalculate_sequence_offsets,
    render_pending_lots_html,
    resolve_selected_miseq_kit_type,
    resolve_selected_reagent,
    submission_status_for_reagent,
    summarize_submission_entries,
)
from shinylims.security import (
    get_runtime_user,
    is_allowed_reagents_user,
    reagents_access_denied_message,
)


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
                    ui.output_ui("rgt_number_ui"),
                    
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
                          function resolveDateInput(id) {
                            const el = document.getElementById(id);
                            if (!el) return null;
                            if (el.tagName === 'INPUT') return el;
                            return el.querySelector('input') || el;
                          }

                          function getVisibleDatepicker() {
                            const pickers = Array.from(document.querySelectorAll('.datepicker-dropdown'));
                            return pickers.find((el) => el.offsetParent !== null) || pickers[pickers.length - 1] || null;
                          }

                          function positionDatepickerForInput(input) {
                            if (!input) return;
                            const picker = getVisibleDatepicker();
                            if (!picker) return;

                            const pickerHeight = picker.getBoundingClientRect().height || picker.offsetHeight || 270;
                            const rect = input.getBoundingClientRect();
                            const aboveTop = window.scrollY + rect.top - pickerHeight + 20;
                            const belowTop = window.scrollY + rect.bottom + 6;
                            const top = aboveTop >= window.scrollY ? aboveTop : belowTop;
                            const left = window.scrollX + rect.left;

                            picker.style.top = `${top}px`;
                            picker.style.left = `${left}px`;
                          }

                          const bind = () => {
                            const inputs = ["received_date", "expiry_date"]
                              .map((id) => resolveDateInput(id))
                              .filter(Boolean);
                            if (!inputs.length) return false;

                            inputs.forEach((input) => {
                              if (input._reagentDatepickerBound) return;
                              input._reagentDatepickerBound = true;
                              input.addEventListener('focus', () => setTimeout(() => positionDatepickerForInput(input), 0));
                              input.addEventListener('click', () => setTimeout(() => positionDatepickerForInput(input), 0));
                            });

                            if (!window._reagentDatepickerGlobalBound) {
                              window._reagentDatepickerGlobalBound = true;
                              window.addEventListener('scroll', () => {
                                const activeInput = inputs.find((input) => document.activeElement === input);
                                if (activeInput) positionDatepickerForInput(activeInput);
                              }, { passive: true });
                              window.addEventListener('resize', () => {
                                const activeInput = inputs.find((input) => document.activeElement === input);
                                if (activeInput) positionDatepickerForInput(activeInput);
                              });
                              document.addEventListener('click', () => {
                                const activeInput = inputs.find((input) => document.activeElement === input);
                                if (activeInput) setTimeout(() => positionDatepickerForInput(activeInput), 0);
                              }, true);
                            }

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
                        ui.div(
                            ui.strong("Internal Name: "),
                            ui.output_text("preview_internal_name", inline=True),
                            class_="mb-1",
                        ),
                        ui.div(
                            ui.strong("Submitting Status: "),
                            ui.output_text("preview_submission_status", inline=True),
                        ),
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
                            class_="flex-grow-1",
                            style="width: 100%; overflow-x: auto; min-height: 0;"
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
    pending_lots = reactive.Value(empty_pending_lots_df())
    
    last_reagent_type = reactive.Value(None)

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

    def _safe_base_url_for_logs(base_url: str) -> str:
        parsed = urlparse((base_url or "").strip())
        if parsed.scheme and parsed.hostname:
            host = parsed.hostname
            if parsed.port:
                host = f"{host}:{parsed.port}"
            path = (parsed.path or "").rstrip("/")
            return f"{parsed.scheme}://{host}{path}"
        return (base_url or "").strip()

    def _log_lims_ui_event(event: str, **fields: object) -> None:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        parts = [f"{key}={value}" for key, value in fields.items()]
        payload = " ".join(parts)
        if payload:
            print(f"[reagents-lims-ui] ts={ts} event={event} {payload}")
        else:
            print(f"[reagents-lims-ui] ts={ts} event={event}")

    def recalculate_index_offsets():
        """Recalculate index offsets from current pending queue."""
        pending_sequence_offsets.set(recalculate_sequence_offsets(pending_lots.get()))
    
    def current_runtime_username() -> str | None:
        username, _ = get_runtime_user(session)
        return username

    def show_unauthorized(action: str = "perform this action"):
        ui.notification_show(
            f"Unauthorized: {reagents_access_denied_message()}",
            type="error",
            duration=8
        )

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
        _log_lims_ui_event(
            "refresh_connection_start",
            base_url=_safe_base_url_for_logs(config.base_url),
            username_set=bool((config.username or "").strip()),
            password_set=bool(config.password),
            notify=notify,
        )
        if missing:
            lims_config.set(None)
            lims_connection_status.set(("missing", f"Missing credentials: {', '.join(missing)}"))
            prep_sequence_state.set((False, "Not checked"))
            index_sequence_state.set((False, "Not checked", None))
            _log_lims_ui_event(
                "refresh_connection_missing_credentials",
                missing_fields=",".join(missing),
            )
            if notify:
                ui.notification_show("Missing credentials in environment variables", type="warning", duration=6)
            return False

        lims_config.set(config)
        success, message = test_connection(config)
        if not success:
            lims_connection_status.set(("failed", "Connection failed (see logs)"))
            prep_sequence_state.set((False, "Not checked"))
            index_sequence_state.set((False, "Not checked", None))
            _log_lims_ui_event(
                "refresh_connection_failed",
                reason=message,
            )
            if notify:
                ui.notification_show("LIMS connection failed", type="error", duration=6)
            return False

        lims_connection_status.set(("connected", "Connected to LIMS"))
        _log_lims_ui_event("refresh_connection_success")
        return True

    def refresh_sequence_states(config):
        statuses = get_reagent_sequence_statuses(config, PREP_REAGENT_TYPES)

        seq_nums = sequence_numbers.get().copy()

        prep_status = statuses.prep
        if prep_status.success and prep_status.latest_complete_sequence is not None:
            seq_nums["prep"] = prep_status.latest_complete_sequence
            prep_sequence_state.set((True, prep_status.message))
            prep_ok = True
        else:
            prep_sequence_state.set((False, prep_status.message))
            prep_ok = False

        index_status = statuses.index
        if index_status.success:
            if index_status.latest_sequence is not None:
                seq_nums["index"] = index_status.latest_sequence
            index_sequence_state.set((True, index_status.message, index_status.latest_sequence))
            index_ok = True
        else:
            index_sequence_state.set((False, index_status.message, None))
            index_ok = False

        sequence_numbers.set(seq_nums)
        return prep_ok, index_ok, index_status.message

    @reactive.Effect
    @reactive.event(input.open_tool_reagents)
    def init_lims_from_env_on_reagents_open():
        if not is_allowed_reagents_user(session):
            return
        _log_lims_ui_event("reagents_open_init_start")
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
                prep_ok, index_ok, index_msg = refresh_sequence_states(config)
                _log_lims_ui_event(
                    "reagents_open_init_checks_complete",
                    prep_ok=prep_ok,
                    index_ok=index_ok,
                    index_message=index_msg,
                )
        finally:
            ui.modal_remove()
            _log_lims_ui_event("reagents_open_init_done")

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
            prep_ok, index_ok, index_message = refresh_sequence_states(config)
            if prep_ok:
                ui.notification_show("Prep sequence status refreshed", type="message", duration=3)
            else:
                ui.notification_show(
                    "Prep sequence check failed. Clean up LIMS prep lots before submitting.",
                    type="warning",
                    duration=8
                )

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
            "Refresh Reagent Check",
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
        return resolve_selected_reagent(input.reagent_selector())

    def get_selected_miseq_kit_type():
        return resolve_selected_miseq_kit_type(input.reagent_selector())

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

    def can_generate_internal_names_for_current_session(reagent_type):
        prep_ok, _ = prep_sequence_state.get()
        index_ok, _, _ = index_sequence_state.get()
        return can_generate_internal_names(
            reagent_type,
            is_authorized=is_allowed_reagents_user(session),
            is_lims_ready=_is_lims_ready(),
            prep_ok=prep_ok,
            index_ok=index_ok,
        )

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
    
    def generate_internal_name_for_current_session(
        reagent_type,
        set_letter=None,
        miseq_kit_type=None,
        rgt_number=None,
    ):
        return generate_internal_name(
            reagent_type,
            sequence_numbers=sequence_numbers.get(),
            pending_sequence_offsets=pending_sequence_offsets.get(),
            pending_lots=pending_lots.get(),
            set_letter=set_letter,
            miseq_kit_type=miseq_kit_type,
            rgt_number=rgt_number,
        )
    
    @output
    @render.text
    def preview_internal_name():
        reagent_type, set_letter = get_selected_reagent()
        if not reagent_type:
            return "Select a reagent type"
        if not can_generate_internal_names_for_current_session(reagent_type):
            return "Log in to LIMS and refresh checks to load latest numbering"

        reagent_info = REAGENT_TYPES.get(reagent_type, {})
        miseq_kit_type = None
        rgt_number = None
        if reagent_info.get("requires_miseq_kit_type"):
            miseq_kit_type = get_selected_miseq_kit_type()
        if reagent_info.get("requires_rgt_number"):
            rgt_number = input.rgt_number()

        return generate_internal_name_for_current_session(
            reagent_type,
            set_letter,
            miseq_kit_type,
            rgt_number,
        )

    @output
    @render.text
    def preview_submission_status():
        reagent_type, _ = get_selected_reagent()
        if not reagent_type:
            return "Select a reagent type"
        return submission_status_for_reagent(reagent_type)
    
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

        if not can_generate_internal_names_for_current_session(reagent_type):
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
        
        internal_name = generate_internal_name_for_current_session(
            reagent_type,
            set_letter,
            miseq_kit_type,
            rgt_number,
        )
        
        pending_sequence_offsets.set(
            increment_pending_offsets(
                pending_sequence_offsets.get(),
                reagent_type,
            )
        )
        
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
        ui.update_text("rgt_number", value="")
        ui.notification_show(f"Added: {internal_name}", type="message", duration=2)
    
    # Clear queue
    @reactive.Effect
    @reactive.event(input.clear_queue)
    def clear_queue():
        pending_lots.set(empty_pending_lots_df())
        pending_sequence_offsets.set(recalculate_sequence_offsets(empty_pending_lots_df()))
    
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
            return ui.HTML(
                """
                <div
                  id="pending_queue_printable"
                  style="height: 420px; overflow-y: auto; display: flex; align-items: center; justify-content: center;"
                >
                  <p class="text-muted text-center py-4 mb-0">No lots in queue. Add lots using the form.</p>
                </div>
                """
            )

        display_df = df[["Internal Name", "Reagent Type", "Lot Number", "Expiry Date"]].copy()

        return ui.HTML(
            f'<div id="pending_queue_printable" style="height: 420px; overflow-y: auto;">'
            f"{render_pending_lots_html(display_df)}"
            "</div>"
        )

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

        removal_error = get_queue_removal_error(df, idx)
        if removal_error:
            ui.notification_show(
                removal_error,
                type="warning",
                duration=4,
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

                details = get_prep_queue_mismatch_details(df)
                if details is not None:
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
                refresh_sequence_states(config)
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
                        notes=f"Created via Shiny App on {date.today()} by {requester}",
                        status=submission_status_for_reagent(row["Reagent Type"]),
                    )

                    submission_entries.append({
                        "row": row,
                        "result": result
                    })

                p.set(len(df), message="Done!")

            successes, failures, result_df, logs_text = summarize_submission_entries(
                submission_entries
            )

            if failures == 0:
                ui.notification_show(
                    f"✅ All {successes} lots created successfully!",
                    type="message",
                    duration=5
                )
                # Clear the queue on full success
                pending_lots.set(empty_pending_lots_df())
                pending_sequence_offsets.set(recalculate_sequence_offsets(empty_pending_lots_df()))
            else:
                ui.notification_show(
                    f"⚠️ {successes} succeeded, {failures} failed",
                    type="warning",
                    duration=10
                )
            result_table = result_df.to_html(
                index=False,
                escape=True,
                classes="table table-sm table-striped table-bordered submit-result-table",
                border=0
            )
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
            refresh_sequence_states(config)
        finally:
            submit_in_progress.set(False)
    
    return {
        "pending_lots": pending_lots,
        "sequence_numbers": sequence_numbers
    }
