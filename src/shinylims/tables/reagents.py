'''
reagents.py - Table module containing UI and server logic for the Reagents tab
Allows batch entry of reagent lots for Illumina Clarity LIMS
'''

from shiny import ui, reactive, render
import pandas as pd
from datetime import date
import re

# Import the LIMS API module
from shinylims.data.lims_api import (
    LIMSConfig, 
    create_reagent_lot, 
    test_connection,
    ReagentLotResult,
    get_latest_prep_sequence_status
)

##############################
# REAGENT CONFIGURATION
##############################

REAGENT_TYPES = {
    "IDT-ILMN DNA/RNA UD Index Sets": {
        "short_name": "IDT-Index",
        "category": "Index",
        "naming_group": "index",
        "requires_set_letter": True
    },
    "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp": {
        "short_name": "IPB-Buffers",
        "category": "Buffers",
        "naming_group": "prep",
        "requires_set_letter": False
    },
    "Illumina DNA Prep – PCR + Buffers (EPM, TB1, RSB) 96sp": {
        "short_name": "PCR-Buffers",
        "category": "Buffers",
        "naming_group": "prep",
        "requires_set_letter": False
    },
    "Illumina DNA Prep – Tagmentation (M) Beads 96sp": {
        "short_name": "Tag-Beads",
        "category": "Beads",
        "naming_group": "prep",
        "requires_set_letter": False
    }
}

INDEX_SET_LETTERS = ["A", "B", "C", "D"]
PREP_REAGENT_TYPES = [
    "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp",
    "Illumina DNA Prep – PCR + Buffers (EPM, TB1, RSB) 96sp",
    "Illumina DNA Prep – Tagmentation (M) Beads 96sp",
]


##############################
# UI REAGENTS
##############################

def reagents_ui():
    return ui.div(
        ui.h4("📦 Reagent Lot Registration", class_="mb-3"),
        
        # Connection status indicator
        ui.output_ui("connection_status"),
        ui.output_ui("prep_sequence_status"),
        
        # Main layout
        ui.layout_columns(
            # LEFT PANEL - Quick Add Form
            ui.card(
                ui.card_header("Add New Lot"),
                ui.card_body(
                    ui.input_select(
                        "reagent_type",
                        "Reagent Type",
                        choices=list(REAGENT_TYPES.keys()),
                        width="100%"
                    ),
                    
                    ui.output_ui("set_letter_ui"),
                    
                    ui.input_text(
                        "lot_number",
                        "Lot Number",
                        placeholder="e.g., 20456789",
                        width="100%"
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
                        ui.output_ui("pending_lots_table"),
                        style="width: 100%; overflow-x: auto;"
                    ),
                    ui.hr(),
                    ui.layout_columns(
                        ui.input_action_button(
                            "clear_queue",
                            "🗑️ Clear All",
                            class_="btn-outline-danger"
                        ),
                        ui.input_action_button(
                            "submit_to_lims",
                            "🚀 Submit to LIMS",
                            class_="btn-success",
                            onclick="""
                            const originalText = this.innerHTML;
                            this.disabled = true;
                            this.innerHTML = 'Submitting...';
                            this.style.opacity = '0.65';
                            this.style.cursor = 'not-allowed';
                            setTimeout(() => {
                                if (document.body.contains(this)) {
                                    this.disabled = false;
                                    this.innerHTML = originalText;
                                    this.style.opacity = '';
                                    this.style.cursor = '';
                                }
                            }, 3000);
                            """
                        ),
                        col_widths=[6, 6]
                    )
                )
            ),
            col_widths=[5, 7]
        ),
        
        # Submission results (shows after submit)
        ui.output_ui("submission_results"),
        
        class_="p-3"
    )


##############################
# SERVER REAGENTS
##############################

def reagents_server(input, output, session):
    
    # LIMS auth/session state
    lims_config = reactive.Value(None)
    lims_connection_status = reactive.Value((False, "Not connected"))
    prep_sequence_state = reactive.Value((True, "Not checked"))
    
    # Reactive values
    pending_lots = reactive.Value(pd.DataFrame(columns=[
        "Reagent Type", "Short Name", "Lot Number",
        "Received Date", "Expiry Date", "Internal Name", "Set Letter"
    ]))
    
    last_expiry_date = reactive.Value(None)
    
    submission_results = reactive.Value([])
    
    # Sequence numbers (placeholder - should be fetched from LIMS)
    sequence_numbers = reactive.Value({
        "prep": 28,
        "index_A": 62,
        "index_B": 45,
        "index_C": 38,
        "index_D": 41
    })
    
    pending_sequence_offsets = reactive.Value({
        "prep": 0,
        "index_A": 0,
        "index_B": 0,
        "index_C": 0,
        "index_D": 0
    })

    def recalculate_index_offsets():
        """Recalculate index offsets from current pending queue."""
        df = pending_lots.get()
        offsets = {
            "prep": 0,
            "index_A": 0,
            "index_B": 0,
            "index_C": 0,
            "index_D": 0
        }

        if not df.empty and "Set Letter" in df.columns:
            index_type = "IDT-ILMN DNA/RNA UD Index Sets"
            for letter in INDEX_SET_LETTERS:
                count = int(((df["Reagent Type"] == index_type) & (df["Set Letter"] == letter)).sum())
                offsets[f"index_{letter}"] = count

        pending_sequence_offsets.set(offsets)

    def extract_internal_sequence(name: str) -> int | None:
        """Extract sequence number from internal name like '#12 (192)'."""
        if not isinstance(name, str):
            return None
        match = re.search(r"#(\d+)", name)
        return int(match.group(1)) if match else None
    
    default_lims_config = LIMSConfig.get_credentials()

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

    def show_lims_login_modal():
        existing = lims_config.get()
        config_for_defaults = existing or default_lims_config
        default_base_url = config_for_defaults.base_url if config_for_defaults else ""
        default_username = config_for_defaults.username if config_for_defaults else ""

        ui.modal_show(
            ui.modal(
                ui.p("Enter your Clarity LIMS credentials to continue."),
                ui.input_text("lims_base_url", "LIMS Base URL", value=default_base_url),
                ui.input_text("lims_username", "Username", value=default_username),
                ui.input_password("lims_password", "Password"),
                title="🔐 LIMS Login",
                easy_close=True,
                footer=ui.div(
                    ui.modal_button("Cancel", class_="btn-secondary"),
                    ui.input_action_button(
                        "save_lims_login",
                        "Connect",
                        class_="btn-primary ms-2",
                        onclick="""
                        this.disabled = true;
                        this.innerHTML = 'Connecting...';
                        this.style.opacity = '0.65';
                        this.style.cursor = 'not-allowed';
                        """
                    )
                )
            )
        )

    @reactive.Effect
    @reactive.event(input.open_lims_login)
    def open_lims_login():
        show_lims_login_modal()

    @reactive.Effect
    @reactive.event(input.save_lims_login)
    def save_lims_login():
        current_config = lims_config.get()
        base_url = (input.lims_base_url() or "").strip()
        username = (input.lims_username() or "").strip()
        password = input.lims_password() or ""

        if not base_url or not username or not password:
            ui.notification_show("Base URL, username, and password are required", type="warning")
            return

        config = LIMSConfig(base_url=base_url, username=username, password=password)
        success, message = test_connection(config)

        if success:
            lims_config.set(config)
            lims_connection_status.set((True, message))
            is_prep_valid = refresh_prep_sequence_state(config)
            ui.modal_remove()
            ui.notification_show("Connected to LIMS", type="message", duration=3)
            if not is_prep_valid:
                ui.notification_show(
                    "Prep reagent set in LIMS is incomplete/misaligned. Resolve before submitting.",
                    type="warning",
                    duration=8
                )
        else:
            if current_config is None:
                lims_connection_status.set((False, message))
            ui.notification_show(f"LIMS connection failed: {message}", type="error", duration=8)

    @reactive.Effect
    @reactive.event(input.refresh_prep_sequence)
    def refresh_prep_sequence():
        config = lims_config.get()
        if not config:
            ui.notification_show("Log in to LIMS first", type="warning")
            return

        if refresh_prep_sequence_state(config):
            ui.notification_show("Prep sequence status refreshed", type="message", duration=3)
        else:
            ui.notification_show(
                "Prep sequence check failed. Clean up LIMS prep lots before submitting.",
                type="warning",
                duration=8
            )

    # Connection status check
    @output
    @render.ui
    def connection_status():
        config = lims_config.get()

        if not config:
            return ui.div(
                ui.div(
                    ui.span("🔒 Not logged in to LIMS", class_="text-warning-emphasis"),
                    ui.input_action_button("open_lims_login", "Log in to LIMS", class_="btn-sm btn-outline-primary"),
                    style="display:flex; align-items:center; justify-content:space-between; gap:10px;"
                ),
                class_="mb-3 p-2 bg-warning-subtle rounded"
            )

        success, message = lims_connection_status.get()

        if success:
            return ui.div(
                ui.div(
                    ui.div(
                        ui.span("✅ Connected to LIMS", class_="text-success"),
                        ui.span(f" ({config.base_url})", class_="text-muted small"),
                    ),
                    ui.input_action_button("open_lims_login", "Change Login", class_="btn-sm btn-outline-secondary"),
                    style="display:flex; align-items:center; justify-content:space-between; gap:10px;"
                ),
                class_="mb-3 p-2 bg-success-subtle rounded"
            )

        return ui.div(
            ui.div(
                ui.div(
                    ui.span("❌ LIMS Connection Failed", class_="text-danger"),
                    ui.span(f" - {message}", class_="text-muted small"),
                ),
                ui.input_action_button("open_lims_login", "Try Again", class_="btn-sm btn-outline-primary"),
                style="display:flex; align-items:center; justify-content:space-between; gap:10px;"
            ),
            class_="mb-3 p-2 bg-warning-subtle rounded"
        )

    @output
    @render.ui
    def prep_sequence_status():
        config = lims_config.get()
        if not config:
            return None

        is_valid, message = prep_sequence_state.get()
        seq_num = sequence_numbers.get().get("prep", 0)

        if is_valid:
            return ui.div(
                ui.div(
                    ui.div(
                        ui.span("✅ Prep set check passed", class_="text-success"),
                        ui.span(f" - {message}. Next set number: #{seq_num + 1}", class_="text-muted small"),
                    ),
                    ui.input_action_button(
                        "refresh_prep_sequence",
                        "Refresh Prep Check",
                        class_="btn-sm btn-outline-secondary",
                        onclick="""
                        this.disabled = true;
                        this.innerHTML = 'Refreshing...';
                        this.style.opacity = '0.65';
                        this.style.cursor = 'not-allowed';
                        """
                    ),
                    style="display:flex; align-items:center; justify-content:space-between; gap:10px;"
                ),
                class_="mb-3 p-2 bg-success-subtle rounded"
            )

        return ui.div(
            ui.input_action_button(
                "refresh_prep_sequence",
                "Re-check Prep Set",
                class_="btn-sm btn-outline-danger",
                onclick="""
                this.disabled = true;
                this.innerHTML = 'Refreshing...';
                this.style.opacity = '0.65';
                this.style.cursor = 'not-allowed';
                """
            ),
            ui.div(ui.span("⚠️ Prep set check failed", class_="text-danger")),
            ui.p(message, class_="mb-1 small"),
            ui.p(
                "Please clean up prep reagent lots in Clarity LIMS before submitting new reagents.",
                class_="mb-0 small"
            ),
            class_="mb-3 p-2 bg-warning-subtle rounded"
        )

    # Set letter dropdown
    @output
    @render.ui
    def set_letter_ui():
        reagent_type = input.reagent_type()
        if reagent_type and REAGENT_TYPES[reagent_type].get("requires_set_letter"):
            return ui.input_select(
                "set_letter",
                "Index Set",
                choices=INDEX_SET_LETTERS,
                width="100%"
            )
        return None
    
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

        if naming_group == "index" and set_letter:
            key = f"index_{set_letter}"
        else:
            key = naming_group
            
        base_num = seq_nums.get(key, 0)
        offset = offsets.get(key, 0)
        return base_num + offset + 1
    
    def generate_internal_name(reagent_type, set_letter=None):
        reagent_info = REAGENT_TYPES.get(reagent_type, {})
        naming_group = reagent_info.get("naming_group", "unknown")
        
        next_num = get_next_sequence_number(naming_group, set_letter, reagent_type)
        
        if naming_group == "index" and set_letter:
            return f"{set_letter}#{next_num} (192)"
        else:
            return f"#{next_num} (192)"
    
    @output
    @render.text
    def preview_internal_name():
        reagent_type = input.reagent_type()
        if not reagent_type:
            return "Select a reagent type"
        
        reagent_info = REAGENT_TYPES.get(reagent_type, {})
        
        if reagent_info.get("requires_set_letter"):
            try:
                set_letter = input.set_letter()
            except:
                set_letter = "A"
            return generate_internal_name(reagent_type, set_letter)
        else:
            return generate_internal_name(reagent_type)
    
    @reactive.Effect
    def restore_expiry_date():
        stored_date = last_expiry_date.get()
        if stored_date:
            ui.update_date("expiry_date", value=stored_date)
    
    # Add lot to queue
    @reactive.Effect
    @reactive.event(input.add_lot)
    def add_lot_to_queue():
        if not input.lot_number():
            ui.notification_show("Please enter a lot number", type="warning")
            return
        
        if not input.expiry_date():
            ui.notification_show("Please enter an expiry date", type="warning")
            return
        
        reagent_type = input.reagent_type()
        reagent_info = REAGENT_TYPES[reagent_type]
        
        set_letter = None
        if reagent_info.get("requires_set_letter"):
            try:
                set_letter = input.set_letter()
            except:
                set_letter = "A"
        
        internal_name = generate_internal_name(reagent_type, set_letter)
        
        # Update offsets
        offsets = pending_sequence_offsets.get().copy()
        naming_group = reagent_info.get("naming_group")
        
        if naming_group == "index":
            if set_letter:
                key = f"index_{set_letter}"
            else:
                key = naming_group
            offsets[key] = offsets.get(key, 0) + 1
            pending_sequence_offsets.set(offsets)
        
        last_expiry_date.set(input.expiry_date())
        
        current_df = pending_lots.get().copy()
        new_row = pd.DataFrame([{
            "Reagent Type": reagent_type,
            "Short Name": reagent_info["short_name"],
            "Lot Number": input.lot_number(),
            "Received Date": str(input.received_date()),
            "Expiry Date": str(input.expiry_date()),
            "Internal Name": internal_name,
            "Set Letter": set_letter
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
            "Reagent Type", "Short Name", "Lot Number",
            "Received Date", "Expiry Date", "Internal Name", "Set Letter"
        ]))
        pending_sequence_offsets.set({
            "prep": 0,
            "index_A": 0,
            "index_B": 0,
            "index_C": 0,
            "index_D": 0
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
        
        display_df = df[["Internal Name", "Short Name", "Lot Number", "Expiry Date"]].copy()
        
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
            table_html += f"""
                <tr>
                    <td><strong>{row['Internal Name']}</strong></td>
                    <td>{row['Short Name']}</td>
                    <td>{row['Lot Number']}</td>
                    <td>{row['Expiry Date']}</td>
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
        
        return ui.HTML(f'<div style="max-height: 300px; overflow-y: auto;">{table_html}</div>')

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
        if reagent_type in PREP_REAGENT_TYPES:
            prep_rows = df[df["Reagent Type"].isin(PREP_REAGENT_TYPES)]
            prep_numbers = [
                extract_internal_sequence(name)
                for name in prep_rows["Internal Name"].tolist()
            ]
            prep_numbers = [n for n in prep_numbers if n is not None]
            if prep_numbers:
                latest_prep_num = max(prep_numbers)
                row_num = extract_internal_sequence(row["Internal Name"])
                if row_num != latest_prep_num:
                    ui.notification_show(
                        f"For prep kits, remove the latest number first (#{latest_prep_num}).",
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
        df = pending_lots.get()
        
        if df.empty:
            ui.notification_show("No lots to submit", type="warning")
            return

        prep_counts = {
            reagent_type: int((df["Reagent Type"] == reagent_type).sum())
            for reagent_type in PREP_REAGENT_TYPES
        }
        if len(set(prep_counts.values())) > 1:
            details = ", ".join(
                f"{REAGENT_TYPES[rt]['short_name']}: {count}"
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

        config = lims_config.get()
        if not config:
            show_lims_login_modal()
            ui.notification_show("Log in to LIMS before submitting", type="warning")
            return

        # Always re-check current LIMS state before allowing submission.
        refresh_prep_sequence_state(config)
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
        
        ui.modal_show(
            ui.modal(
                ui.div(
                    ui.p(f"Submit {len(df)} lot(s) to Clarity LIMS?"),
                    ui.HTML(df[["Internal Name", "Short Name", "Lot Number"]].to_html(
                        index=False, 
                        classes="table table-sm"
                    )),
                ),
                title="🚀 Confirm Submission",
                easy_close=True,
                footer=ui.div(
                    ui.modal_button("Cancel", class_="btn-secondary"),
                    ui.input_action_button(
                        "confirm_submit", 
                        "Submit to LIMS", 
                        class_="btn-success ms-2",
                        onclick="""
                        const originalText = this.innerHTML;
                        this.disabled = true;
                        this.innerHTML = 'Submitting...';
                        this.style.opacity = '0.65';
                        this.style.cursor = 'not-allowed';
                        setTimeout(() => {
                            if (document.body.contains(this)) {
                                this.disabled = false;
                                this.innerHTML = originalText;
                                this.style.opacity = '';
                                this.style.cursor = '';
                            }
                        }, 8000);
                        """
                    )
                )
            )
        )
    
    # Actual submission
    @reactive.Effect
    @reactive.event(input.confirm_submit)
    def do_submit():
        ui.modal_remove()
        
        df = pending_lots.get()
        config = lims_config.get()
        results = []
        
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
                    notes=f"Created via Shiny App on {date.today()}"
                )
                
                results.append(result)
            
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
                "Reagent Type", "Short Name", "Lot Number",
                "Received Date", "Expiry Date", "Internal Name", "Set Letter"
            ]))
        else:
            ui.notification_show(
                f"⚠️ {successes} succeeded, {failures} failed", 
                type="warning",
                duration=10
            )

        # Refresh prep state after submission so next number/status reflects LIMS.
        if config:
            refresh_prep_sequence_state(config)
    
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
                status = f'<span class="text-success">✅ {r.lims_id}</span>'
            else:
                status = f'<span class="text-danger">❌ {r.message}</span>'
            
            rows_html += f"<tr><td>{r.name}</td><td>{status}</td></tr>"
        
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
