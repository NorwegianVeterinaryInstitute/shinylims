'''
reagents.py - Table module containing UI and server logic for the Reagents tab
Allows batch entry of reagent lots for Illumina Clarity LIMS
'''

from shiny import ui, reactive, render
import pandas as pd
from datetime import date

# Import the LIMS API module
from shinylims.data.lims_api import (
    LIMSConfig, 
    create_reagent_lot, 
    test_connection,
    ReagentLotResult
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


##############################
# UI REAGENTS
##############################

def reagents_ui():
    return ui.div(
        ui.h4("📦 Reagent Lot Registration", class_="mb-3"),
        
        # Connection status indicator
        ui.output_ui("connection_status"),
        
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
                            class_="btn-success"
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
    
    # Initialize LIMS config
    # For local testing, use LIMSConfig.for_testing()
    # For production (Posit Connect), use LIMSConfig.from_environment()
    lims_config = reactive.Value(LIMSConfig.for_testing())
    
    # Reactive values
    pending_lots = reactive.Value(pd.DataFrame(columns=[
        "Reagent Type", "Short Name", "Lot Number",
        "Received Date", "Expiry Date", "Internal Name"
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
    
    # Connection status check
    @output
    @render.ui
    def connection_status():
        config = lims_config.get()
        success, message = test_connection(config)
        
        if success:
            return ui.div(
                ui.span("✅ Connected to LIMS", class_="text-success"),
                ui.span(f" ({config.base_url})", class_="text-muted small"),
                class_="mb-3"
            )
        else:
            return ui.div(
                ui.span("❌ LIMS Connection Failed", class_="text-danger"),
                ui.span(f" - {message}", class_="text-muted small"),
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
    def get_next_sequence_number(naming_group, set_letter=None):
        seq_nums = sequence_numbers.get()
        offsets = pending_sequence_offsets.get()
        
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
        
        next_num = get_next_sequence_number(naming_group, set_letter)
        
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
        
        if naming_group == "index" and set_letter:
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
            "Internal Name": internal_name
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
            "Received Date", "Expiry Date", "Internal Name"
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
                    <th style="width: 25%;">Internal Name</th>
                    <th style="width: 25%;">Type</th>
                    <th style="width: 25%;">Lot Number</th>
                    <th style="width: 25%;">Expiry</th>
                </tr>
            </thead>
            <tbody>
        """
        
        for _, row in display_df.iterrows():
            table_html += f"""
                <tr>
                    <td><strong>{row['Internal Name']}</strong></td>
                    <td>{row['Short Name']}</td>
                    <td>{row['Lot Number']}</td>
                    <td>{row['Expiry Date']}</td>
                </tr>
            """
        
        table_html += "</tbody></table>"
        
        return ui.HTML(f'<div style="max-height: 300px; overflow-y: auto;">{table_html}</div>')
    
    # Submit to LIMS
    @reactive.Effect
    @reactive.event(input.submit_to_lims)
    def submit_to_lims():
        df = pending_lots.get()
        
        if df.empty:
            ui.notification_show("No lots to submit", type="warning")
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
                        class_="btn-success ms-2"
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
                "Received Date", "Expiry Date", "Internal Name"
            ]))
        else:
            ui.notification_show(
                f"⚠️ {successes} succeeded, {failures} failed", 
                type="warning",
                duration=10
            )
    
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