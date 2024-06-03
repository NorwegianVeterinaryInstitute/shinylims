###########
# IMPORTS #
###########

import seaborn as sns   # will be used for some plots on the Sequencing Runs page
from shiny import App, render, ui, reactive
import datetime 
import pytz # For fixing timezone differences
from faicons import icon_svg
from shinyswatch import theme

# App modules
from ui_pages import projects_page, wgs_samples_page, prepared_samples_page, seq_page
from ui_server import setup_projects_page, setup_wgs_samples_page, setup_prepared_samples_page, setup_seq_run_page
from data_utils import fetch_pinned_data


####################
# CONSTRUCT THE UI #
####################

app_ui = ui.page_navbar(
    
    # Select bootstrap theme
    theme.cerulean(),

    # Include the custom CSS file
    ui.head_content(ui.include_css("styles.css")),
    
    # Push the navbar items to the right
    ui.nav_spacer(),  

    # Kickstarts server side ui reactive functions using latest pin update
    ui.nav_control(ui.output_ui("render_updated_data")), 

    # Define ui panels
    ui.nav_panel("Projects", projects_page),
    ui.nav_panel("WGS Samples", wgs_samples_page),
    ui.nav_panel("Prepared Samples", prepared_samples_page), 
    ui.nav_panel("Sequencing Runs", seq_page),
    ui.nav_control(ui.tooltip(ui.input_action_button("update_button", "Update Data", class_="btn-success"), ui.output_ui("update_tooltip_output"), placement="right", id="update_tooltip" )), 
    
    # Title
    title=ui.tooltip(ui.span("Clarity LIMS Shiny App   ",icon_svg("circle-info")) ,ui.HTML("App for viewing status of projects and samples submitted for NGS through Clarity LIMS.<br><br> Automatic data transfer from Clarity every 2nd hour.<br><br> 'Update Data' button will collect latest transferred data"),placement="right",id="title_tooltip")
)



###################
# SERVER FUNCTION #
###################

def server(input, output, session):
    '''
    Fetching pinned data and all ui reactive rendering is done from this function

    Inital data is fetched and stored as reactive values. The reactive values are updated
    through the function update_pinned_data() which is triggered by an ui action button.
    
    Reactive metadata values are used to populate a information tooltip through the 
    function update_tooltip_output()
    '''

    # Fetch initial data
    with ui.Progress (min=1, max=10) as p:
        p.set(message="Loading datasets from pins...")
        
        projects_df, project_date_created = fetch_pinned_data("vi2172/projects_limsshiny")
        p.set(3, message="Projects data fetched")
        wgs_df, wgs_date_created = fetch_pinned_data("vi2172/wgs_samples_limsshiny")
        p.set(6, message="WGS samples data fetched")
        prepared_df, prepared_date_created = fetch_pinned_data("vi2172/wgs_prepared_limsshiny")
        p.set(7, message="Prepared data fetched")
        seq_df, seq_date_created = fetch_pinned_data("vi2172/seq_runs_limsshiny")
        p.set(8, message="Seq data fetched")
        historical_df, historical_date_created = fetch_pinned_data("vi2172/wgs_historical")
        p.set(9, message="Historical data fetched")

        # Initialize reactive values with the initial data
        projects_df = reactive.Value(projects_df)
        wgs_df = reactive.Value(wgs_df)
        prepared_df = reactive.Value(prepared_df)
        seq_df = reactive.Value(seq_df)
        p.set(9, message="Reactive dataframe values established")

        projects_df_created = reactive.Value(project_date_created)
        wgs_date_created = reactive.Value(wgs_date_created)
        prepared_date_created = reactive.Value(prepared_date_created)
        seq_date_created = reactive.Value(seq_date_created)
        p.set(10, message="Datasets loaded successfully")
    
    # Define a function to update the reactive values
    def update_pinned_data():
        with ui.Progress (min=1, max=6) as p:
            p.set(message="Loading updated datasets from pins...")

            updated_projects_df, updated_project_date_created = fetch_pinned_data("vi2172/projects_limsshiny")
            p.set(3, message="Projects data fetched")
            updated_wgs_df, updated_wgs_date_created = fetch_pinned_data("vi2172/wgs_samples_limsshiny")
            p.set(6, message="WGS samples data fetched")
            updated_prepared_df, updated_prepared_created = fetch_pinned_data("vi2172/wgs_prepared_limsshiny")
            p.set(8, message="Prepared data fetched")

            # Update reactive values
            projects_df.set(updated_projects_df)
            wgs_df.set(updated_wgs_df)
            prepared_df.set(updated_prepared_df)
            p.set(9, message="Reactive dataframe values updated")

            projects_df_created.set(updated_project_date_created)
            wgs_date_created.set(updated_wgs_date_created)
            prepared_date_created.set(updated_prepared_created)
            p.set(10, message="Datasets updated successfully")

    # Define an effect to handle the update button click event
    @reactive.Effect
    @reactive.event(input.update_button)
    def on_update_button_click():
        update_pinned_data()

    @render.text
    def update_tooltip_output():
        
        iso_date_projects_gmt = datetime.datetime.fromisoformat(projects_df_created.get())
        iso_date_wgs_gmt = datetime.datetime.fromisoformat(wgs_date_created.get())
        iso_date_prepared_gmt = datetime.datetime.fromisoformat(prepared_date_created.get())

        cet = pytz.timezone('Europe/Berlin')
    
        cet_date_wgs = iso_date_wgs_gmt.astimezone(cet)
        cet_date_projects = iso_date_projects_gmt.astimezone(cet)
        cet_date_prepared = iso_date_prepared_gmt.astimezone(cet)

        human_readable_date_wgs = cet_date_wgs.strftime("%Y-%m-%d (kl %H:%M)")
        human_readable_date_projects = cet_date_projects.strftime("%Y-%m-%d (kl %H:%M)") #%Z to add CEST
        human_readable_date_prepared = cet_date_prepared.strftime("%Y-%m-%d (kl %H:%M)")

        text = f"<strong>Connect pin status:<br>2h intervals<br><br>Projects:<br>{human_readable_date_projects}<br><br>WGS Samples:<br>{human_readable_date_wgs}<br><br>Prepared Samples:<br>{human_readable_date_prepared}<br><br>Sequencing Runs:<strong>"
        
        return ui.HTML(text)
    
    # Function to update UI with reactive functionality. UI is updated with the most recent data whenever the df`s change.
    @output
    @render.ui
    def render_updated_data():
        setup_projects_page(input, output, session, projects_df.get(), projects_df_created.get())
        setup_wgs_samples_page(input, output, session, wgs_df.get(), wgs_date_created.get(), historical_df)
        setup_prepared_samples_page(input, output, session, prepared_df.get(), prepared_date_created.get())
        setup_seq_run_page(input,output,session,seq_df.get(),seq_date_created.get())
        return ui.TagList()  # Return an empty UI element as setup_wgs_samples_page handles rendering
    


###########
# RUN APP #
###########

app = App(app_ui, server)
