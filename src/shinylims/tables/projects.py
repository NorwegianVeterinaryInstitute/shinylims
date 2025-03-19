'''
projects.py - Table module containing UI and server logic for the Projects table tab
'''

from shiny import render, ui, reactive
from faicons import icon_svg
from itables.shiny import DT
import pandas as pd
import datetime
import pytz


##############################
# UI PROJECT TABLE
##############################

def projects_ui():
    return ui.navset_tab(
        ui.nav_panel("Table  (Nov 2023 ->)",
            ui.div(
                ui.accordion(
                    ui.accordion_panel(
                        ui.output_text("filters_title_projects"),
                        ui.row(ui.column(3,
                            ui.input_date_range(
                                id="date_range_projects", 
                                label="Open Date Range",
                                start=None,
                                end=None,
                            ),
                            ui.input_action_button(
                                id="reset_date_projects", 
                                label="Reset Date Filter",
                            ),),
                            ui.column(3,
                                ui.input_checkbox(
                                    id="project_comment_filter",
                                    label="Show only projects with 'Comment'"
                                ))),
                            value="filters", icon=icon_svg("filter"),
                    ),
                    ui.accordion_panel(
                        ui.output_text("column_selection_title_projects"), 
                        ui.div(
                            ui.div(
                                ui.div(
                                    ui.input_checkbox_group(
                                        id="fields_to_display_projects",
                                        inline=False,
                                        label=ui.div("Field Selection", class_="fw-bold"),
                                        choices=[],
                                        selected=[],
                                    ),
                                ),
                            )
                        ),
                        open=False,
                        value="column_selection_projects",
                        icon=icon_svg("table-columns")
                    ),
                    class_="mb-3 mt-3",
                    open=False,
                    multiple=False
                ),
                class_="mb-3"
            ),
            
            ui.output_ui("data_projects")
        ),
        ui.nav_panel("Info", ui.card(ui.output_ui("projects_info")))
    )


##############################
# SERVER PROJECT TABLE
##############################

def projects_server(input, output, session, projects_df, project_date_created):
    # Define a reactive value to store the filtered dataframe
    projects_filtered_data = reactive.Value(projects_df)

    @render.ui
    def data_projects():
        # Filter data using selected date range filter
        start_date, end_date = input.date_range_projects()
        filtered_df = projects_df[
            (projects_df['Open Date'].isna()) |
            ((projects_df['Open Date'] >= pd.to_datetime(start_date)) &
            (projects_df['Open Date'] <= pd.to_datetime(end_date)))]
        
        # Filter data using the "show projects with comment only"-button
        project_comment_filter = input.project_comment_filter()
        if project_comment_filter == True:
            filtered_df = filtered_df[filtered_df['Comment'] != '']

        # Pandas will insert indexing, which we dont want
        dat = filtered_df.reset_index(drop=True)

        # Store selected columns in variable and set the filtered df in reactive value 
        selected_columns = list(input.fields_to_display_projects())
        projects_filtered_data.set(filtered_df)
        
        # Get index for the comment section (used for css styling in DT below)
        if 'Comment' in dat[selected_columns].columns:
            comment_index = dat[selected_columns].columns.get_loc('Comment')
        else:
            comment_index = "Dummy"

        # Return HTML tag with DT table element
        return ui.HTML(DT(dat[selected_columns], 
                         layout={"topEnd": "search"}, 
                         column_filters="footer", 
                         search={"smart": True},
                         lengthMenu=[[50, 100, 200, 500, -1], [50, 100, 200, 500, "All (NB: Slow)" ]], 
                         classes="compact hover order-column cell-border", 
                         scrollY="750px",
                         paging=True,
                         maxBytes=0, 
                         autoWidth=True,
                         keys=True,
                         buttons=["pageLength", 
                                  "copyHtml5",
                                 {"extend": "csvHtml5", "title": "WGS Sample Data"},
                                 {"extend": "excelHtml5", "title": "WGS Sample Data"},],
                         order=[[0, "desc"]],
                         columnDefs=[{'targets': comment_index, 'className': 'left-column'},{"className": "dt-center", "targets": "_all"}],))

    # Define default column checkbox selection
    @reactive.Effect
    def set_default_fields_to_display_projects():
        ui.update_checkbox_group(
            "fields_to_display_projects",
            choices=projects_df.columns.tolist(),
            selected=['Open Date', 'Status','Project Name', 'Samples', 'Species', 'Submitter', 'Submitting Lab', 'Comment']
        )    
    
    # Define default date range
    @reactive.Effect
    def set_default_date_range_projects():
        try:
            # Check if 'Open Date' exists and has valid values
            if 'Open Date' in projects_df.columns:
                min_date = pd.to_datetime(projects_df['Open Date'], errors='coerce').min()
                if pd.notna(min_date):
                    start_date = min_date.date()
                else:
                    start_date = datetime.date(2023, 1, 1)  # Fallback
            else:
                # Fallback date if column doesn't exist
                start_date = datetime.date(2023, 1, 1)
        
            ui.update_date_range(
                "date_range_projects",
                start=start_date,
                end=datetime.date.today()
            )
        except Exception as e:
            print(f"Error setting default date range for projects: {e}")
            # Use a reasonable fallback
            ui.update_date_range(
                "date_range_projects",
                start=datetime.date(2023, 1, 1),
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
    
    @render.ui
    def projects_info():
        text = f"<h3>Data in table is collected from pinned data generated by this script</h3> \
        <a href='https://github.com/NorwegianVeterinaryInstitute/nvi_lims_epps/blob/main/shiny_app/shiny_sample_table_projects.py'>shiny_sample_table_projects.py (link)</a> <br> \
        <h3>Data fields collection </h3> \
        <p>All fields in this table is collected from submitted sample UDFs directly except for the project sample number which is retrieved using a genologics function</p> \
        <h3>Last pinned data update</h3><br>\
        {(datetime.datetime.fromisoformat(project_date_created).astimezone(pytz.timezone('Europe/Berlin'))).strftime('%Y-%m-%d (kl %H:%M)')}"
        
        return ui.HTML(text)
    
    # Define outputs that need to be returned
    output.data_projects = data_projects
    output.filters_title_projects = filters_title_projects
    output.column_selection_title_projects = column_selection_title_projects
    output.projects_info = projects_info