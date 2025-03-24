'''
app.py - Main UI and server logic for the Shiny LIMS Metadata App 
Ties together the different table modules and defines the main UI layout.

Specifically, this module defines the app_ui variable and server function to run App(app_ui, server)
'''

###########
# IMPORTS #
###########

# Import the shiny App class and other necessary shiny functions
from shiny import App, render, ui, reactive
from faicons import icon_svg

# Import table modules
from shinylims.tables.projects import projects_ui, projects_server
from shinylims.tables.samples import samples_ui, samples_server
from shinylims.tables.sequencing import seq_ui, seq_server

# Import database utilities
from src.shinylims.data.db_utils import get_db_update_info, refresh_db_connection, get_formatted_update_info

# Import data utilities for fetching data
from src.shinylims.data.data_utils import (
    fetch_projects_data, 
    fetch_all_samples_data, 
    fetch_sequencing_data,
    get_app_version
)

# Add custom CSS
from pathlib import Path
import tomli  # For reading pyproject.toml

css_path = Path(__file__).parent / "assets" / "styles.css"
from shinylims.data.brand_utils import load_brand_config, generate_comprehensive_brand_css
brand = load_brand_config()

####################
# APP CONFIGURATION #
####################

# Logo file to use
logo_path = "logos/vetinst-logo.png"  

# Get the absolute path to the www directory
www_dir = Path(__file__).parent.parent.parent / "www"

app_version = get_app_version()

####################
# CONSTRUCT THE UI #
####################

app_ui = ui.page_navbar(
    
    # Add Google Fonts and custom CSS
    ui.head_content(
        # Viewport meta tag for mobile responsiveness
        ui.tags.meta(
            name="viewport",
            content="width=device-width, initial-scale=1.0, maximum-scale=1.0"
        ),
        # Google Fonts
        ui.tags.link(
            rel="stylesheet",
            href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:ital,wght@0,400;0,500;0,600;1,400;1,500;1,600&display=swap"
        ),
        # Brand CSS (Vetinst branding)
        ui.tags.style(generate_comprehensive_brand_css(brand)),
        # Include CSS file (specific component behaviors)
        ui.include_css(css_path),
        
    ),

    # Add a spacer before the nav panels to push them toward center
    ui.nav_spacer(),

    # Kickstart server side ui reactive functions using latest database update
    ui.nav_control(ui.output_ui("render_updated_data")), 

    # Define ui panels
    ui.nav_panel("Projects", projects_ui(), value="projects"),
    ui.nav_panel("Samples", samples_ui()),  
    ui.nav_panel("Illumina Sequencing", seq_ui()),
    # Add another spacer after panels to push the button to the far right
    ui.nav_spacer(),
    # Add info button next to refresh button
    ui.nav_control(
        ui.div(
            ui.input_action_button(
                "info_button", 
                icon_svg("info"), 
                class_="btn-info",
            ),
            style="display: flex; align-items: center; height: 100%;"
        )
    ),
    ui.nav_control(ui.tooltip(
        ui.input_action_button("update_button", "Refresh SQL db connection", class_="btn-success"), 
        ui.output_ui("update_tooltip_output"), 
        placement="right", 
        id="update_tooltip",
        style="display: flex; align-items: center; height: 100%;"
    )),
    
    # Title
    title=ui.div(
        ui.tags.img(
            src=logo_path,
            alt="NVI",
            height="55px",
            style="margin-right: 10px; vertical-align: middle;"
        ),
        #ui.span("LIMS Metadata App", style="vertical-align: middle;"),
        style="display: flex; align-items: center;"
    ),
    
    # Set Projects as the default selected panel
    selected="projects"
)


###################
# SERVER FUNCTION #
###################

def server(input, output, session):
    """
    Fetching data from SQLite database and all ui reactive rendering is done from this function.

    Inital data is fetched and stored as reactive values. The reactive values are updated
    through the function update_database_data() which is triggered by an ui action button.
    
    Reactive metadata values are used to populate a information tooltip through the 
    function update_tooltip_output()
    """
    # Create a reactive value for database update info
    db_update_info_reactive = reactive.Value(get_db_update_info())

    # Fetch initial data
    with ui.Progress(min=1, max=12) as p:
        p.set(message="Loading datasets from SQLite database...")
        
        projects_df, project_date_created = fetch_projects_data()
        p.set(3, message="Projects data fetched")
        
        samples_df, samples_date_created = fetch_all_samples_data()
        p.set(6, message="Samples data fetched")
        
        seq_df, seq_date_created = fetch_sequencing_data()
        p.set(8, message="Seq data fetched")
        
        # Initialize reactive values with the initial data
        projects_df_reactive = reactive.Value(projects_df)
        samples_df_reactive = reactive.Value(samples_df)
        seq_df_reactive = reactive.Value(seq_df)
        p.set(11, message="Reactive dataframe values established")

        projects_date_created_reactive = reactive.Value(project_date_created)
        samples_date_created_reactive = reactive.Value(samples_date_created)
        seq_date_created_reactive = reactive.Value(seq_date_created)
        p.set(12, message="Datasets loaded successfully")
    
    # Define a function to update the reactive values
    def update_database_data():
        '''Update the reactive values with the latest data from the database'''

        with ui.Progress(min=1, max=10) as p:
            p.set(message="Refreshing database connection...")
            
            # Force database refresh
            refresh_db_connection()
            
            # Fetch updated data
            updated_projects_df, updated_project_date_created = fetch_projects_data()
            p.set(3, message="Projects data fetched")
            
            updated_samples_df, updated_samples_date_created = fetch_all_samples_data()
            p.set(6, message="Samples data fetched")
            
            updated_seq_df, updated_seq_date_created = fetch_sequencing_data()
            p.set(8, message="Seq data fetched")

            # Update reactive values
            projects_df_reactive.set(updated_projects_df)
            samples_df_reactive.set(updated_samples_df)
            seq_df_reactive.set(updated_seq_df)
            p.set(9, message="Reactive dataframe values updated")

            projects_date_created_reactive.set(updated_project_date_created)
            samples_date_created_reactive.set(updated_samples_date_created)
            seq_date_created_reactive.set(updated_seq_date_created)

            # Update the database update info
            db_update_info_reactive.set(get_db_update_info())  # Update tooltip info

            p.set(10, message="Datasets updated successfully")

    # Define an effect to handle the update button click event
    @reactive.Effect
    @reactive.event(input.update_button)
    def on_update_button_click():
        '''Handle the update button click event'''
        update_database_data()
    

    @render.ui
    def update_tooltip_output():
        '''Render the update tooltip with updated data information'''
        # Get formatted info 
        formatted_info = get_formatted_update_info()
    
        # Build a very minimal tooltip
        text = f"""<strong>SQL db last updated:</strong><br>
        ➡️ Projects:<br>{formatted_info['projects']['formatted']}<br>
        ➡️ Samples:<br>{formatted_info['samples']['formatted']}<br>
        ➡️ Sequencing:<br>{formatted_info['ilmn_sequencing']['formatted']}<br><br>
        <strong>App last refreshed:</strong><br>
        🔄 {formatted_info['app_refresh']}"""

        return ui.HTML(text)
    
    # Define an effect to handle the info button click event
    @reactive.Effect
    @reactive.event(input.info_button)
    def on_info_button_click():
        '''Handle the info button click event'''
        ui.modal_show(
            ui.modal(
                ui.h2("LIMS Metadata App Information", class_="mb-4"),
                ui.div(
                    ui.h3("About"),
                    ui.p("""This app provides a user-friendly interface to explore and filter LIMS metadata. 
                         It connects to the LIMS database and displays information about projects, samples, 
                         and sequencing runs."""),
                    ui.h3("Database Information"),
                    ui.p("The database is updated hourly on the LIMS server and synced to the app every 30 minutes past the hour."),
                    ui.h4("Last Database Updates:"),
                    ui.tags.dl(
                        ui.tags.dt("Projects"),
                        ui.tags.dd(get_formatted_update_info()['projects']['formatted']),
                        ui.tags.dt("Samples"),
                        ui.tags.dd(get_formatted_update_info()['samples']['formatted']),
                        ui.tags.dt("Sequencing"),
                        ui.tags.dd(get_formatted_update_info()['ilmn_sequencing']['formatted']),
                        ui.tags.dt("App Last Refreshed"),
                        ui.tags.dd(get_formatted_update_info()['app_refresh']),
                        class_="row"
                    ),
                    ui.h3("SQL Database Update Scripts"),
                    ui.p(ui.tags.a("update_sqlite.py", href="https://github.com/NorwegianVeterinaryInstitute/nvi_lims_epps/blob/main/shiny_app/update_sqlite.py", target="_blank"),
                       " and ",
                       ui.tags.a("update_sqlite_ilmn_seq.py", href="https://github.com/NorwegianVeterinaryInstitute/nvi_lims_epps/blob/main/shiny_app/update_sqlite_ilmn_seq.py", target="_blank")),
                    ui.h3("Data Fields Collection"),
                    ui.h4("Projects"),
                    ui.p("All fields in this table are collected from submitted sample UDFs directly except for the project sample number which is retrieved using a genologics API-batch function."),
                    ui.h4("Samples"),
                    ui.p(ui.tags.strong("Extraction step"), ": Extraction Number"),
                    ui.p(ui.tags.strong("Fluorescence step"), ": Absorbance, A260/280 ratio, A260/230 ratio, Fluorescence, Storage Box Name, Storage Well"),
                    ui.p(ui.tags.strong("Prep Step"), ": Experiment Name, Reagent Labels"),
                    ui.p(ui.tags.strong("Billing Step"), ": Invoice ID, Price, Billing Description"),
                    ui.p("Note that the step must be completed in LIMS before the data fields are updated in the Shiny App."),
                    ui.h4("Sequencing"),
                    ui.p(ui.tags.strong("Step 8 (NS/MS Run)"), ": Technician Name, Species, Experiment Name, Comment, Run ID, Flow Cell ID, Reagent Cartridge ID, Date"),
                    ui.p(ui.tags.strong("Step 7 (Generate SampleSheet)"), ": Read 1 Cycles, Read 2 Cycles, Index Cycles"),
                    ui.p(ui.tags.strong("Step 6 (Make Final Loading Dilution)"), ": Final Library Loading (pM), Volume 20pM Denat Sample (µl), PhiX / library spike-in (%), Average Size - bp"),
                    ui.p("Table will not be updated until the sequencing step has been completed."),
                    ui.h3("App Version"),
                    ui.p(f"Version: {app_version}"),
                    class_="p-4",
                    style="max-height: 70vh; overflow-y: auto;"
                ),
                ui.div(
                    ui.input_action_button("close_info", "Close", class_="btn-secondary"),
                    class_="mt-3 text-center"
                ),
                size="xl",
                easy_close=True,
                id="info_modal"
            )
        )

    # Define an effect to handle the close button in the modal
    @reactive.Effect
    @reactive.event(input.close_info)
    def close_info_modal():
        ui.modal_remove()
    
    @render.ui
    def render_updated_data():
        '''Render the updated data to the UI'''

        projects_server(input, output, session, 
                   projects_df_reactive.get(),
                   projects_date_created_reactive.get())
    
        samples_server(input, output, session,
                 samples_df_reactive.get(),
                 samples_date_created_reactive.get())
    
        seq_server(input, output, session,
             seq_df_reactive.get(),
             seq_date_created_reactive.get())
    
        return ui.TagList()  # Return an empty UI element
    


###########
# RUN APP #
###########

app = App(app_ui, server, static_assets=www_dir)