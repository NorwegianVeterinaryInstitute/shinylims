import seaborn as sns
#from shared import wgs_df, wgs_date_created
from shiny import App, render, ui, req, reactive
from itables.shiny import DT
import pandas as pd
from htmltools import HTML, div
import datetime
import pytz
from faicons import icon_svg
from shinyswatch import theme, theme_picker_ui, theme_picker_server
from pins import board_connect

# The contents of the WGS samples page
wgs_samples_page = ui.page_fluid(
    ui.div(
        ui.accordion(
            ui.accordion_panel(
                ui.output_text("filters_title"),  # Filter icon
                ui.row(ui.column(3,
                    ui.input_date_range(
                        id="date_range", 
                        label="Received Date Range",
                        start=pd.to_datetime(wgs_df['Received Date']).min().date(),
                        end=datetime.date.today(),
                    ),
                    ui.input_action_button(
                        id="reset_date", 
                        label="Reset Date Filter",
                    ),),
                    ui.column(3,
                    ui.input_selectize(
                        id="filter_progress", 
                        label="Progress", 
                        choices=[],  # Will be populated in the server, 
                        multiple=True, 
                    ),),
                    ui.column(3,
                    ui.input_selectize(
                        id="filter_project_account", 
                        label="Project Account", 
                        choices=[],  # Will be populated in the server, 
                        multiple=True, 
                    ),),
                    ui.column(3,   
                    ui.input_selectize(
                        id="filter_experiment_name", 
                        label="Experiment Name", 
                        choices=[],  # Will be populated in the server
                        multiple=True
                    ),),),
                    value="filters", icon=icon_svg("filter"),
                    
            ),
            ui.accordion_panel(
                ui.output_text("column_selection_title"),  # Dynamic title for Column Selection
                ui.div(
                    ui.div(
                        ui.div(
                            ui.input_checkbox_group(
                                id="fields_to_display",
                                inline=False,
                                label=ui.div("Field Selection", class_="fw-bold"),
                                choices=column_names,
                                selected=[x for x in column_names if x not in ["Reagent Label", "nd_limsid", "qubit_limsid", "prep_limsid", "seq_limsid", "billed_limsid", "Increased Pooling (%)", "Billing Description", "Price"]]
                            ),
                            style="flex: 2; margin-right: 20px;"
                        ),
                        ui.div(
                            ui.input_radio_buttons(
                                id="presets",
                                label=ui.div("Presets", class_="fw-bold"),
                                choices=["All", "All (-IDs,Labels & billinginfo)", "Billing info only", "Custom"],
                                selected="All (-IDs,Labels & billinginfo)"
                            ),
                            style="flex: 1; margin-left: 20px;"
                        ),
                        style="display: flex; align-items: flex-start;"
                    )
                ),
                open=False,
                value="column_selection",  # Provide a unique value
                icon=icon_svg("table-columns")
            ),
            class_="d-flex-inline bd-highlight mb-3", 
            open = False,
            multiple=False
        ),
        class_="d-flex flex-column bd-highlight mb-3"
    ),
    ui.output_ui("data")
)




# The contents of the Prepared samples page
prepared_samples_page = ui.page_fluid("Prepared Samples dataframe goes here")

#Construct the UI
app_ui = ui.page_navbar(
    theme.cerulean(),
    ui.nav_spacer(),  # Push the navbar items to the right
    ui.nav_panel("Projects Page", "Projects dataframe goes here"),
    ui.nav_panel(ui.tooltip(ui.span("WGS Samples  ", icon_svg("circle-question")), ui.output_ui("metadata_info"),placement="right",id="wgs_tooltip"),  wgs_samples_page),
    ui.nav_panel("Prepared Samples", prepared_samples_page), #"Prepared samples dataframe goes here"
    ui.nav_panel("Sequencing Runs", "Sequencing Run dataframe goes here"),
    title="Clarity LIMS Shiny App",
)


# Server function
def server(input, output, session):
    board = board_connect()
    wgs_df = board.pin_read("vi2172/wgs_samples_limsshiny")
    meta = board.pin_meta("vi2172/wgs_samples_limsshiny")
    wgs_date_created = meta.created
    # Ensure 'Received Date' is in datetime format
    wgs_df['Received Date'] = pd.to_datetime(wgs_df['Received Date'])

    # Hardcode the column order
    wgs_desired_order = [
    'Received Date', 'Progress', 'Species','Name',  'Project Name', 'Submitter', 
    'Submitting Lab','Project Account', 'Experiment Name', 'Extraction Number', 
    'Reagent Label', 'Concentration Absorbance (ng/µl)', 'A260/280 ratio', 
    'A260/230 ratio', 'Concentration Fluorescence (ng/µl)', 'Storage (Box)', 
    'Storage (Well)', 'Billing Description', 'Price', 'Invoice ID', 'Sample Type', 
    'nd_limsid', 'qubit_limsid', 'prep_limsid', 'seq_limsid', 'billed_limsid', 
    'Increased Pooling (%)', 
    'Gram Stain', 'LIMSID', 'Project LIMSID' 
    ]

    # Reorder the columns in the DataFrame
    wgs_df = wgs_df[[col for col in wgs_desired_order if col in wgs_df.columns] + [col for col in wgs_df.columns if col not in wgs_desired_order]]
   
    # Get column names from the dataframe
    column_names = wgs_df.columns.tolist()




    # Define a reactive value to store the filtered dataframe
    filtered_data = reactive.Value(wgs_df)

    @reactive.Effect
    def update_project_account_choices():
        unique_project_accounts = sorted(wgs_df['Project Account'].unique().tolist())
        ui.update_selectize("filter_project_account", choices=unique_project_accounts)

    @reactive.Effect
    def update_experiment_name_choices():
        unique_experiment_names = wgs_df['Experiment Name'].unique().tolist()
        ui.update_selectize("filter_experiment_name", choices=unique_experiment_names)
    
    @reactive.Effect
    def update_progress_choices():
        unique_progress = wgs_df['Progress'].unique().tolist()
        ui.update_selectize("filter_progress", choices=unique_progress)

    def get_selected_columns(preset, custom_columns, all_columns):
        if preset == "All":
            return all_columns
        elif preset == "All (-IDs,Labels & billinginfo)":
            return [col for col in all_columns if col not in ["Reagent Label", "nd_limsid", "qubit_limsid", "prep_limsid", "seq_limsid", "billed_limsid", "Increased Pooling (%)", "Billing Description", "Price"]]
        elif preset == "Billing info only":
            return ["Received Date", "LIMSID", "Name", "billed_limsid", "Invoice ID"]
        elif preset == "Custom":
            return custom_columns
        return []

    @render.ui
    def data():

        # Date filtering
        start_date, end_date = input.date_range()
        filtered_df = wgs_df[(wgs_df['Received Date'] >= pd.to_datetime(start_date)) & (wgs_df['Received Date'] <= pd.to_datetime(end_date))]

        # Project Account filtering
        selected_project_accounts = input.filter_project_account()
        if selected_project_accounts:
            filtered_df = filtered_df[filtered_df['Project Account'].isin(selected_project_accounts)]
        
        # Experiment Name filtering
        selected_experiment_names = input.filter_experiment_name()
        if selected_experiment_names:
            filtered_df = filtered_df[filtered_df['Experiment Name'].isin(selected_experiment_names)]

        #Progress filtering
        selected_progress = input.filter_progress()
        if selected_progress:
            filtered_df = filtered_df[filtered_df['Progress'].isin(selected_progress)]

        selected_columns = get_selected_columns(input.presets(), list(input.fields_to_display()), column_names)

        dat = filtered_df.reset_index(drop=True)

        # Update the reactive value with the filtered dataframe
        filtered_data.set(filtered_df)

        return ui.HTML(DT(dat[selected_columns], 
                          layout={"topEnd": "search"}, 
                          column_filters="footer", 
                          search={"smart": True},
                          lengthMenu=[20, 30, 50, 100, 200],
                          classes="display nowrap compact order-column", 
                          #scrollX=True,
                          scrollY=True,
                          maxBytes=0, 
                          autoWidth=True,
                          keys= True,
                          buttons=["pageLength", 
                                   "copyHtml5",
                                  {"extend": "csvHtml5", "title": "WGS Sample Data"},
                                  {"extend": "excelHtml5", "title": "WGS Sample Data"},],
                          order=[[0, "desc"]]))

    
    # Update checkbox group to ensure "Received Date" is always checked
    @reactive.Effect
    @reactive.event(input.fields_to_display)
    def ensure_received_date_selected():
        selected = list(input.fields_to_display())
        if "Received Date" not in selected:
            selected.append("Received Date")
            ui.update_checkbox_group("fields_to_display", selected=selected)


    # Automatically switch to "Custom" preset when fields are changed
    @reactive.Effect
    @reactive.event(input.fields_to_display)
    def switch_to_custom_preset():
        current_selected_fields = set(input.fields_to_display())
        all_fields = set(column_names)
        preset_all = all_fields
        preset_no_ids_labels_billing = {x for x in column_names if x not in ["Reagent Label", "nd_limsid", "qubit_limsid", "prep_limsid", "seq_limsid", "billed_limsid", "Increased Pooling (%)", "Billing Description", "Price"]}
        preset_billing_info_only = {"Received Date", "LIMSID", "Name", "billed_limsid", "Invoice ID"}

        if current_selected_fields == preset_all:
            ui.update_radio_buttons("presets", selected="All")
        elif current_selected_fields == preset_no_ids_labels_billing:
            ui.update_radio_buttons("presets", selected="All (-IDs,Labels & billinginfo)")
        elif current_selected_fields == preset_billing_info_only:
            ui.update_radio_buttons("presets", selected="Billing info only")
        else:
            ui.update_radio_buttons("presets", selected="Custom")

    # Update fields_to_display checkbox group based on the selected preset
    @reactive.Effect
    @reactive.event(input.presets)
    def update_fields_to_display():
        selected_preset = input.presets()
        selected_columns = get_selected_columns(selected_preset, list(input.fields_to_display()), column_names)
        ui.update_checkbox_group("fields_to_display", selected=selected_columns)
        
    @reactive.Effect
    @reactive.event(input.reset_date)
    def reset_date_range():
        ui.update_date_range(
            "date_range",
            start=pd.to_datetime(wgs_df['Received Date']).min().date(),
            end=datetime.date.today()
        )

    @render.text
    def settings_info():
        return ui.div(
            ui.span("WGS Samples,", class_='fw-bold fs-5'),
            ui.span("  ", style='margin-right: 10px;'),
            ui.span("Column selection:"),
            ui.span(f"'{input.presets()}'", class_='text-success fst-italic')
        )

    @render.text
    def filters_title():
        # Count the number of active filters
        start_date, end_date = input.date_range()
        project_account = input.filter_project_account()
        experiment_name = input.filter_experiment_name()
        progress = input.filter_progress()

        num_filters = 0
        if start_date != pd.to_datetime(wgs_df['Received Date']).min().date() or end_date != datetime.date.today():
            num_filters += 1
        if project_account:
            num_filters += 1
        if experiment_name:
            num_filters += 1
        if progress:
            num_filters += 1

        # Calculate the number of entries filtered out
        total_entries = len(wgs_df)
        filtered_entries = len(filtered_data())
        filtered_out = total_entries - filtered_entries
        
        if num_filters > 0:
            return f'Filters ({num_filters} filters applied, {filtered_entries} of {total_entries} samples)'
        else:
            return f"Filters (All {total_entries} samples shown)"

    @render.text
    def column_selection_title():
        selected_columns = list(input.fields_to_display())
        total_columns = len(column_names)
        num_selected = len(selected_columns)
        return f"Column Selection ({num_selected} of {total_columns} columns selected)"

    @render.text
    def metadata_info():
        # Convert ISO format to datetime object
        iso_date = datetime.datetime.fromisoformat(wgs_date_created)
    
        # Define the CEST/CET time zone
        cet = pytz.timezone('Europe/Berlin')  # CEST/CET time zone

        # Convert the ISO date to CEST/CET
        if iso_date.tzinfo is None:
            # If iso_date is naive (no tzinfo), assume it's in GMT and localize it
            gmt = pytz.timezone('GMT')
            gmt_date = gmt.localize(iso_date)
        else:
            # If iso_date is already timezone-aware, assume it's in GMT
            gmt_date = iso_date
    
        # Convert GMT date to CEST/CET
        cet_date = gmt_date.astimezone(cet)

        # Format the datetime object into a human-readable string
        human_readable_date = cet_date.strftime("%Y-%m-%d (kl %H:%M:%S %Z)")

        # Access the filtered dataframe from the reactive value
        current_filtered_df = filtered_data()

        return ui.p(f"Last update from Clarity: {human_readable_date}")
    

app = App(app_ui, server)