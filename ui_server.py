import seaborn as sns   # will be used for some plots on the Sequencing Runs page
from shiny import  render, ui, reactive
from itables.shiny import DT
import pandas as pd
import datetime


####################
# SERVER FUNCTIONS #
####################


def setup_projects_page(input, output, session, projects_df, project_date_created):

    # Define a reactive value to store the filtered dataframe
    projects_filtered_data = reactive.Value(projects_df)

    @render.ui
    def data_projects():
        # Filter data using selected date range filter
        start_date, end_date = input.date_range_projects()
        filtered_df = projects_df[(projects_df['Open Date'] >= pd.to_datetime(start_date)) & (projects_df['Open Date'] <= pd.to_datetime(end_date))]
        
        # Filter data using the "show projects with comment only"-button
        project_comment_filter = input.project_comment_filter()
        if project_comment_filter == True:
            filtered_df = filtered_df[filtered_df['Comment'].notna()]

        # Pandas will insert indexing, which we dont want
        dat = filtered_df.reset_index(drop=True)

        # Store selected columns in variable and set the filtered df in reactive value 
        selected_columns =  list(input.fields_to_display_projects())
        projects_filtered_data.set(filtered_df)
        
        # Return HTML tag with DT table element
        return ui.HTML(DT(dat[selected_columns], 
                          layout={"topEnd": "search"}, 
                          column_filters="footer", 
                          search={"smart": True},
                          #lengthMenu=[[20, 30, 50, 100, 200, -1], [20, 30, 50, 100, 200, "All"]],
                          classes="display compact order-column", 
                          #scrollY=True,
                          scrollY = "750px",
                          scrollCollapse=True,
                          paging=False,
                          scrollX = True,
                          maxBytes=0, 
                          autoWidth=True,
                          keys= True,
                          buttons=[#"pageLength", 
                                   "copyHtml5",
                                  {"extend": "csvHtml5", "title": "WGS Sample Data"},
                                  {"extend": "excelHtml5", "title": "WGS Sample Data"},],
                          order=[[0, "desc"]],))
    
    # Define default column checkbox selection
    @reactive.Effect
    def set_default_fields_to_display_projects():
        ui.update_checkbox_group(
            "fields_to_display_projects",
            choices= projects_df.columns.tolist(),
            selected= ['Open Date', 'Project Name', 'Samples', 'Submitter', 'Submitting Lab', 'Comment']
        )    
    
    # Define default date range
    @reactive.Effect
    def set_default_date_range_projects():
        ui.update_date_range(
            "date_range_projects",
            start=pd.to_datetime(projects_df['Open Date']).min().date(),
            end=datetime.date.today()
        )

    # Update date range to default when pressing the reset-button
    @reactive.Effect
    @reactive.event(input.reset_date_projects)
    def reset_date_range_projects():
        ui.update_date_range(
            "date_range_projects",
            start=pd.to_datetime(projects_df['Open Date']).min().date(),
            end=datetime.date.today()
        )

    # Render title on filter accordian
    @render.text
    def filters_title_projects():
        start_date, end_date = input.date_range_projects()
        project_comment_filter = input.project_comment_filter()


        num_filters = 0
        if start_date != pd.to_datetime(projects_df['Open Date']).min().date() or end_date != datetime.date.today():
            num_filters += 1
        if project_comment_filter:
            num_filters += 1

        total_entries = len(projects_df)
        filtered_entries = len(projects_filtered_data())
        filtered_out = total_entries - filtered_entries
        
        if num_filters > 0:
            return f'Filters ({num_filters} filters applied, {filtered_entries} of {total_entries} projects)'
        else:
            return f"Filters (All {total_entries} projects shown)"

    # Render title on column selection accordian
    @render.text
    def column_selection_title_projects():
        selected_columns = list(input.fields_to_display_projects())
        total_columns = len(projects_df.columns)
        num_selected = len(selected_columns)
        return f"Column Selection ({num_selected} of {total_columns} columns selected)"
    
    
def setup_wgs_samples_page(input, output, session, wgs_df, wgs_date_created):
    
    # Define a reactive value to store the filtered dataframe
    filtered_data = reactive.Value(wgs_df)

    # Populate the selectize field for project account filter
    @reactive.Effect
    def update_project_account_choices():
        unique_project_accounts = sorted(wgs_df['Project Account'].unique().tolist())
        ui.update_selectize("filter_project_account", choices=unique_project_accounts)

    # Populate the selectize field for Experiment Name filter
    @reactive.Effect
    def update_experiment_name_choices():
        unique_experiment_names = wgs_df['Experiment Name'].unique().tolist()
        ui.update_selectize("filter_experiment_name", choices=unique_experiment_names)
    
    # Populate the selectize filed for Progress filter
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

    # Filter and render the filtered dataframe
    @render.ui
    def data_wgs():

        # Filter data using selected date range filter
        start_date, end_date = input.date_range()
        filtered_df = wgs_df[(wgs_df['Received Date'] >= pd.to_datetime(start_date)) & (wgs_df['Received Date'] <= pd.to_datetime(end_date))]

        selected_project_accounts = input.filter_project_account()
        if selected_project_accounts:
            filtered_df = filtered_df[filtered_df['Project Account'].isin(selected_project_accounts)]
        
        selected_experiment_names = input.filter_experiment_name()
        if selected_experiment_names:
            filtered_df = filtered_df[filtered_df['Experiment Name'].isin(selected_experiment_names)]

        selected_progress = input.filter_progress()
        if selected_progress:
            filtered_df = filtered_df[filtered_df['Progress'].isin(selected_progress)]

        # Pandas will insert indexing, which we dont want
        dat = filtered_df.reset_index(drop=True)

        # Store selected columns in variable and set the filtered df in reactive value
        selected_columns = get_selected_columns(input.presets(), list(input.fields_to_display()), wgs_df.columns.tolist())
        filtered_data.set(filtered_df)
        
        # Return HTML tag with DT table element
        return ui.HTML(DT(dat[selected_columns], 
                          layout={"topEnd": "search"}, 
                          column_filters="footer", 
                          search={"smart": True},
                          #lengthMenu=[[20, 30, 50, 100, 200, -1], [20, 30, 50, 100, 200, "All"]],
                          classes="display nowrap compact order-column", 
                          #scrollY=True,
                          scrollY = "750px",
                          scrollCollapse=True,
                          paging=False,
                          maxBytes=0, 
                          autoWidth=True,
                          keys= True,
                          buttons=[#"pageLength", 
                                   "copyHtml5",
                                  {"extend": "csvHtml5", "title": "WGS Sample Data"},
                                  {"extend": "excelHtml5", "title": "WGS Sample Data"},],
                          order=[[0, "desc"]],
                          columnDefs=[{"width": "200px", "targets": "_all"}],))
    
    # Define default column checkbox selection
    @reactive.Effect
    def set_default_fields_to_display():
        ui.update_checkbox_group(
            "fields_to_display",
            choices= wgs_df.columns.tolist(),
            selected= [x for x in wgs_df.columns.tolist() if x not in ["Reagent Label", "nd_limsid", "qubit_limsid", "prep_limsid", "seq_limsid", "billed_limsid", "Increased Pooling (%)", "Billing Description", "Price"]]
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
        all_fields = set(wgs_df.columns.tolist())
        preset_all = all_fields
        preset_no_ids_labels_billing = {x for x in wgs_df.columns if x not in ["Reagent Label", "nd_limsid", "qubit_limsid", "prep_limsid", "seq_limsid", "billed_limsid", "Increased Pooling (%)", "Billing Description", "Price"]}
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
        selected_columns = get_selected_columns(selected_preset, list(input.fields_to_display()), wgs_df.columns.tolist())
        ui.update_checkbox_group("fields_to_display", selected=selected_columns)
    
    # Set default date range when the app starts
    @reactive.Effect
    def set_default_date_range():
        ui.update_date_range(
            "date_range",
            start=pd.to_datetime(wgs_df['Received Date']).min().date(),
            end=datetime.date.today()
        )
    
    # Update date range to default when pressing the reset-button
    @reactive.Effect
    @reactive.event(input.reset_date)
    def reset_date_range():
        ui.update_date_range(
            "date_range",
            start=pd.to_datetime(wgs_df['Received Date']).min().date(),
            end=datetime.date.today()
        )

    # Render title on filter accordian
    @render.text
    def filters_title():
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

        total_entries = len(wgs_df)
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
        total_columns = len(wgs_df.columns)
        num_selected = len(selected_columns)
        return f"Column Selection ({num_selected} of {total_columns} columns selected)"


def setup_prepared_samples_page(input, output, session, prepared_df, prepared_date_created):
    
    # Define a reactive value to store the filtered dataframe
    prepared_filtered_data = reactive.Value(prepared_df)
    
    # Populate the selectize field for project account filter
    @reactive.Effect
    def update_project_account_choices_prepared():
        unique_project_accounts = sorted(prepared_df['Project Account'].unique().tolist())
        ui.update_selectize("filter_project_account_prepared", choices=unique_project_accounts)

    # Populate the selectize field for Experiment Name filter
    @reactive.Effect
    def update_experiment_name_choices_prepared():
        unique_experiment_names = prepared_df['Experiment Name (history not shown)'].unique().tolist()
        ui.update_selectize("filter_experiment_name_prepared", choices=unique_experiment_names)
    
    # Populate the selectize field for Progress filter
    @reactive.Effect
    def update_progress_choices_prepared():
        unique_progress = prepared_df['Progress'].unique().tolist()
        ui.update_selectize("filter_progress_prepared", choices=unique_progress)

    # Return HTML tag with DT table element
    @render.ui
    def data_prepared():

        start_date, end_date = input.date_range_prepared()
        filtered_df = prepared_df[(prepared_df['Received Date'] >= pd.to_datetime(start_date)) & (prepared_df['Received Date'] <= pd.to_datetime(end_date))]

        selected_project_accounts = input.filter_project_account_prepared()
        if selected_project_accounts:
            filtered_df = filtered_df[filtered_df['Project Account'].isin(selected_project_accounts)]
        
        selected_experiment_names = input.filter_experiment_name_prepared()
        if selected_experiment_names:
            filtered_df = filtered_df[filtered_df['Experiment Name (history not shown)'].isin(selected_experiment_names)]

        selected_progress = input.filter_progress_prepared()
        if selected_progress:
            filtered_df = filtered_df[filtered_df['Progress'].isin(selected_progress)]

        selected_columns = list(input.fields_to_display_prepared())

        dat = filtered_df.reset_index(drop=True)
        prepared_filtered_data.set(filtered_df)
        
        return ui.HTML(DT(dat[selected_columns], 
                          layout={"topEnd": "search"}, 
                          column_filters="footer", 
                          search={"smart": True},
                          #lengthMenu=[[20, 30, 50, 100, 200, -1], [20, 30, 50, 100, 200, "All"]],
                          classes="display nowrap compact order-column", 
                          #scrollY=True,
                          scrollY = "750px",
                          scrollCollapse=True,
                          paging=False,
                          maxBytes=0, 
                          autoWidth=True,
                          keys= True,
                          buttons=[#"pageLength", 
                                   "copyHtml5",
                                  {"extend": "csvHtml5", "title": "WGS Sample Data"},
                                  {"extend": "excelHtml5", "title": "WGS Sample Data"},],
                          order=[[0, "desc"]]))

    # Define default date range (filter)
    @reactive.Effect
    def set_default_date_range_prepared():
        ui.update_date_range(
            "date_range_prepared",
            start=pd.to_datetime(prepared_df['Received Date']).min().date(),
            end=datetime.date.today()
        )

    # Define default column checkbox selection
    @reactive.Effect
    def set_default_fields_to_display_prepared():
        ui.update_checkbox_group(
            "fields_to_display_prepared",
            choices= prepared_df.columns.tolist(),
            selected= prepared_df.columns.tolist()
        )    

    # Reset date filter to default with action button
    @reactive.Effect
    @reactive.event(input.reset_date_prepared)
    def reset_date_range_prepared():
        ui.update_date_range(
            "date_range_prepared",
            start=pd.to_datetime(prepared_df['Received Date']).min().date(),
            end=datetime.date.today()
        )

    # Render title on filter accordian
    @render.text
    def filters_title_prepared():
        start_date, end_date = input.date_range_prepared()
        project_account = input.filter_project_account_prepared()
        experiment_name = input.filter_experiment_name_prepared()
        progress = input.filter_progress_prepared()

        num_filters = 0
        if start_date != pd.to_datetime(prepared_df['Received Date']).min().date() or end_date != datetime.date.today():
            num_filters += 1
        if project_account:
            num_filters += 1
        if experiment_name:
            num_filters += 1
        if progress:
            num_filters += 1

        total_entries = len(prepared_df)
        filtered_entries = len(prepared_filtered_data())
        filtered_out = total_entries - filtered_entries
        
        if num_filters > 0:
            return f'Filters ({num_filters} filters applied, {filtered_entries} of {total_entries} samples)'
        else:
            return f"Filters (All {total_entries} samples shown)"

    # Render title on column selection accordian
    @render.text
    def column_selection_title_prepared():
        selected_columns = list(input.fields_to_display_prepared())
        total_columns = len(prepared_df.columns)
        num_selected = len(selected_columns)
        return f"Column Selection ({num_selected} of {total_columns} columns selected)"