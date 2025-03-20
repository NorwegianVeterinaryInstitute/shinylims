'''
samples.py - Table module containing UI and server logic for the Samples table tab
'''

from shiny import render, ui, reactive
from faicons import icon_svg
from itables.shiny import DT
import pandas as pd
import datetime
import pytz

# UI definition for the Samples page
def samples_ui():
    return ui.div(
        ui.tags.style("""
            /* Custom styling for the samples nav tabs */
            #samples_navset .nav-link.active { 
                font-size: 1.5rem !important; 
            }
        """),

        ui.h2("\u00A0", class_="mb-3 text-center"),
        ui.navset_tab(
        ui.nav_panel("Table (Nov 2023 ->)",
            ui.div(
                ui.accordion(
                    ui.accordion_panel(
                        ui.output_text("filters_title"), # Dynamic title handled by the server function
                        ui.row(ui.column(3,
                            ui.input_date_range(
                                id="date_range", 
                                label="Received Date Range",
                                start=None,
                                end=None
                            ),
                            ui.input_action_button(
                                id="reset_date", 
                                label="Reset Date Filter",
                            ),),
                            ui.column(3,
                                ui.input_selectize(
                                    id="filter_progress", 
                                    label="Progress", 
                                    choices=[],
                                    multiple=True, 
                                ),),
                            ui.column(3,
                                ui.input_selectize(
                                    id="filter_sample_type", 
                                    label="Sample Type", 
                                    choices=[], 
                                    multiple=True, 
                                ),),
                            ui.column(3,
                                ui.input_selectize(
                                    id="filter_project_account", 
                                    label="Project Account", 
                                    choices=[],
                                    multiple=True, 
                                ),),
                            ui.column(3,   
                                ui.input_selectize(
                                    id="filter_experiment_name", 
                                    label="Experiment Name", 
                                    choices=[],
                                    multiple=True
                                ),),),
                            value="filters", icon=icon_svg("filter"),
                    ),
                    ui.accordion_panel(
                        ui.output_text("column_selection_title"), # Dynamic title handled by the server function
                        ui.div(
                            ui.div(
                                ui.div(
                                    ui.input_checkbox_group(
                                        id="fields_to_display",
                                        inline=False,
                                        label=ui.div("Field Selection", class_="fw-bold"),
                                        choices=[],
                                        selected=[]
                                    ),
                                ),
                                ui.div(
                                    ui.input_radio_buttons(
                                        id="presets",
                                        label=ui.div("Presets", class_="fw-bold"),
                                        choices=["All", "All (-IDs,Labels & billinginfo)", "Billing info only", "Custom"],
                                        selected="All (-IDs,Labels & billinginfo)"
                                    ),
                                ),
                                style="display: flex; align-items: flex-start;" # Places the preset list to the right of checkbox group
                            )
                        ),
                        open=False,
                        value="column_selection",
                        icon=icon_svg("table-columns")
                    ),
                    class_="mb-3 mt-3",
                    open=False,
                    multiple=False
                ),
                class_="d-flex flex-column mb-3"
            ),
            ui.output_ui("data_samples"),
        ),
        ui.nav_panel("Info", ui.card(ui.output_ui("samples_info"))),
        id="samples_navset"
    ))

# Server logic for the Samples page
def samples_server(input, output, session, samples_df, samples_date_created):
    def get_column_safe(df, column_names, default_value=None):
        """
        Safely get a column from a dataframe, trying multiple possible names.
        Returns default_value if none of the column names exist.
        """
        if not isinstance(column_names, list):
            column_names = [column_names]
    
        for col in column_names:
            if col in df.columns:
                return df[col]
    
        # If we get here, none of the columns exist
        return pd.Series([default_value] * len(df))

    # Define reactive values
    filtered_data = reactive.Value(samples_df)

    # Add sample type filter population
    @reactive.Effect
    def update_sample_type_choices():
        # Get unique sample types from the database
        unique_sample_types = sorted(samples_df['sample_type'].unique().tolist())
        ui.update_selectize("filter_sample_type", choices=unique_sample_types)

    # Populate the selectize field for project account filter
    @reactive.Effect
    def update_project_account_choices():
        unique_project_accounts = sorted(samples_df['Project Account'].unique().tolist())
        ui.update_selectize("filter_project_account", choices=unique_project_accounts)

    # Populate the selectize field for Experiment Name filter
    @reactive.Effect
    def update_experiment_name_choices():
        unique_experiment_names = samples_df['Experiment Name'].unique().tolist()
        ui.update_selectize("filter_experiment_name", choices=unique_experiment_names)
    
    # Populate the selectize filed for Progress filter
    @reactive.Effect
    def update_progress_choices():
        # Try multiple possible column names
        progress_column = get_column_safe(samples_df, ['Progress', 'progress'])
        if not progress_column.empty:
            unique_progress = progress_column.unique().tolist()
            ui.update_selectize("filter_progress", choices=unique_progress)
        else:
            ui.update_selectize("filter_progress", choices=["No Progress Data"])

    def get_selected_columns(preset, custom_columns, all_columns):
        if preset == "All":
            return all_columns
        elif preset == "All (-IDs,Labels & billinginfo)":
            # These columns might have different names in SQLite
            exclude_patterns = [
                "limsid", "reagent_label", "label", "billing", "price", "pooling", "invoice"
            ]
            return [col for col in all_columns if not any(pattern in col.lower() for pattern in exclude_patterns)]
        elif preset == "Billing info only":
            # Try to identify relevant billing columns
            billing_patterns = ["date", "limsid", "name", "invoice", "bill"]
            return [col for col in all_columns if any(pattern in col.lower() for pattern in billing_patterns)]
        elif preset == "Custom":
            # Make sure all custom columns exist
            return [col for col in custom_columns if col in all_columns]
        return []

    # Filter and render the filtered dataframe
    @render.ui
    def data_samples():
        filtered_df = samples_df.copy()

        # Date filter
        start_date, end_date = input.date_range()
        if start_date is not None and end_date is not None:
            date_col = 'Received Date' if 'Received Date' in filtered_df.columns else 'received_date'
            if date_col in filtered_df.columns:
                filtered_df = filtered_df[
                    (filtered_df[date_col].isna()) | 
                    ((filtered_df[date_col] >= pd.to_datetime(start_date)) & 
                    (filtered_df[date_col] <= pd.to_datetime(end_date)))
                ]
        # Sample type filter (new)
        selected_sample_types = input.filter_sample_type()
        if selected_sample_types:
            filtered_df = filtered_df[filtered_df['sample_type'].isin(selected_sample_types)]

        selected_project_accounts = input.filter_project_account()
        if selected_project_accounts:
            filtered_df = filtered_df[filtered_df['Project Account'].isin(selected_project_accounts)]
        
        selected_experiment_names = input.filter_experiment_name()
        if selected_experiment_names:
            filtered_df = filtered_df[filtered_df['Experiment Name'].isin(selected_experiment_names)]
        
        selected_progress = input.filter_progress()
        if selected_progress:
            filtered_df = filtered_df[filtered_df['progress'].isin(selected_progress)]

        # Get selected columns
        try:
            selected_columns = get_selected_columns(input.presets(), list(input.fields_to_display()), filtered_df.columns.tolist())
            
            # Check if any selected columns don't exist in the dataframe
            missing_columns = [col for col in selected_columns if col not in filtered_df.columns]
            if missing_columns:
                print(f"Warning: These selected columns do not exist in the dataframe: {missing_columns}")
                # Remove missing columns
                selected_columns = [col for col in selected_columns if col in filtered_df.columns]
            
            if not selected_columns:
                # If no valid columns, use all columns
                selected_columns = filtered_df.columns.tolist()
            
        except Exception as e:
            print(f"Error getting selected columns: {e}")
            # Fall back to all columns
            selected_columns = filtered_df.columns.tolist()

        # Reset index and update reactive value
        dat = filtered_df.reset_index(drop=True)
        filtered_data.set(filtered_df)
        
        # Print info for debugging
        print(f"Table will display {len(dat)} rows and {len(selected_columns)} columns")
        print(f"Sample of column names: {selected_columns[:5]}")

        #Find index for order column
        column_to_sort = "Received Date"
        column_index = selected_columns.index(column_to_sort)

        # Return HTML tag with DT table element
        return ui.HTML(DT(dat[selected_columns], 
                         layout={"topEnd": "search"},
                         lengthMenu=[[200, 500, 1000, 2000, -1], [200, 500, 1000, 2000, "All" ]], 
                         column_filters="footer", 
                         search={"smart": True},
                         classes="nowrap compact hover order-column cell-border", 
                         scrollY="750px",
                         paging=True,
                         autoWidth=True,
                         maxBytes=0, 
                         keys=True,
                         buttons=["pageLength", 
                                  "copyHtml5",
                                 {"extend": "csvHtml5", "title": "Sample Data"},
                                 {"extend": "excelHtml5", "title": "Sample Data"},],
                         order=[[column_index, "desc"]],
                         columnDefs=[
                         {"className": "dt-center", "targets": "_all"},
                         {"width": "200px", "targets": "_all"}]  # Set a default width for all columns
                         )) 

    # Define default column checkbox selection
    @reactive.Effect
    def set_default_fields_to_display():
        # Get all columns that would be displayed by default
        exclude_patterns = [
            "limsid", "reagent_label", "label", "billing", "price", "pooling", "invoice"
        ]
        default_columns = [col for col in samples_df.columns if not any(pattern in col.lower() for pattern in exclude_patterns)]
    
        ui.update_checkbox_group(
            "fields_to_display",
            choices=samples_df.columns.tolist(),
            selected=default_columns
        )
    
    # Make sure "Received Date" column isnt deselected
    @reactive.Effect
    @reactive.event(input.fields_to_display)
    def ensure_received_date_selected():
        selected = list(input.fields_to_display())
        if "Received Date" not in selected:
            selected.append("Received Date")
            ui.update_checkbox_group("fields_to_display", selected=selected)

    # If changing the column selection manually, make sure preset radio buttons updates as well
    @reactive.Effect
    @reactive.event(input.fields_to_display)
    def switch_to_custom_preset():
        current_selected_fields = set(input.fields_to_display())
        all_fields = set(samples_df.columns.tolist())
        preset_all = all_fields
        preset_no_ids_labels_billing = {x for x in samples_df.columns if x not in ["Reagent Label", "nd_limsid", "qubit_limsid", "prep_limsid", "seq_limsid", "billed_limsid", "Increased Pooling (%)", "Billing Description", "Price"]}
        preset_billing_info_only = {"Received Date", "LIMSID", "Name", "billed_limsid", "Invoice ID"}

        if current_selected_fields == preset_all:
            ui.update_radio_buttons("presets", selected="All")
        elif current_selected_fields == preset_no_ids_labels_billing:
            ui.update_radio_buttons("presets", selected="All (-IDs,Labels & billinginfo)")
        elif current_selected_fields == preset_billing_info_only:
            ui.update_radio_buttons("presets", selected="Billing info only")
        else:
            ui.update_radio_buttons("presets", selected="Custom")

    # Update the column selection according to selected radio button preset
    @reactive.Effect
    @reactive.event(input.presets)
    def update_fields_to_display():
        selected_preset = input.presets()
        selected_columns = get_selected_columns(selected_preset, list(input.fields_to_display()), samples_df.columns.tolist())
        ui.update_checkbox_group("fields_to_display", selected=selected_columns)
    
    # Set default date range when the app starts
    @reactive.Effect
    def set_default_date_range():
        ui.update_date_range(
            "date_range",
            start=pd.to_datetime(samples_df['Received Date']).min().date(),
            end=datetime.date.today()
        )
    
    # Update date range to default when pressing the reset-button
    @reactive.Effect
    @reactive.event(input.reset_date)
    def reset_date_range():
        ui.update_date_range(
            "date_range",
            start=pd.to_datetime(samples_df['Received Date']).min().date(),
            end=datetime.date.today()
        )

    # Render title on filter accordian
    @render.text
    def filters_title():
        start_date, end_date = input.date_range()
        project_account = input.filter_project_account()
        experiment_name = input.filter_experiment_name()
        progress = input.filter_progress()
        sample_type = input.filter_sample_type()

        num_filters = 0
        if start_date != pd.to_datetime(samples_df['Received Date']).min().date() or end_date != datetime.date.today():
            num_filters += 1
        if project_account:
            num_filters += 1
        if experiment_name:
            num_filters += 1
        if progress:
            num_filters += 1
        if sample_type:
            num_filters += 1

        total_entries = len(samples_df)
        filtered_entries = len(filtered_data())
        filtered_out = total_entries - filtered_entries
        
        if num_filters > 0:
            return f'Filters ({num_filters} filters applied, {filtered_entries} of {total_entries} samples)'
        else:
            return f"Filters (All {total_entries} samples shown)"
    
    # Render title on column selection accordian
    @render.text
    def column_selection_title():
        selected_columns = list(input.fields_to_display())
        total_columns = len(samples_df.columns)
        num_selected = len(selected_columns)
        return f"Column Selection ({num_selected} of {total_columns} columns selected)"

    @render.ui
    def samples_info():
        text = f"<h3>Data in table is collected from pinned data generated by this script</h3> \
        <a href='https://github.com/NorwegianVeterinaryInstitute/nvi_lims_epps/blob/main/shiny_app/shiny_sample_table_WGS.py'>shiny_sample_table_WGS.py (link)</a> <br> \
        <h3>Data fields are collected from the following LIMS steps</h3> <br> \
        <p><strong>Extraction step</strong>: Extraction Number</p> \
        <p><strong>Fluorescence step</strong>: Absorbance, A260/280 ratio, A260/230 ratio, Fluorescence, Storage Box Name, Storage Well</p> \
        <p><strong>Prep Step</strong>: Experiment Name, Reagent Labels</p> \
        <p><strong>Billing Step</strong>: Invoice ID, Price, Billing Description</p> <br><br> \
        Note that the step must be completed in lims before the data fields are updated in the Shiny App <br><br>\
        <h3>Last pinned data update</h3><br>\
        {(datetime.datetime.fromisoformat(samples_date_created).astimezone(pytz.timezone('Europe/Berlin'))).strftime('%Y-%m-%d (kl %H:%M)')} \
        "

        return ui.HTML(text)
        
    # Define outputs that need to be returned

    output.data_samples = data_samples
    output.filters_title = filters_title
    output.column_selection_title = column_selection_title
    output.samples_info = samples_info