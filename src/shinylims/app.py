'''
app.py - Main UI and server logic for the Shiny LIMS Metadata App 
Ties together the different table modules and defines the main UI layout.

Specifically, this module defines the app_ui variable and server function to run App(app_ui, server)
'''

###########
# IMPORTS #
###########

from shiny import App, render, ui, reactive
import datetime 
import pytz # For fixing timezone differences
from faicons import icon_svg  #https://faicons.dev/
from shinyswatch import theme
import os
from pathlib import Path

# Import table modules
from shinylims.tables.projects import projects_ui, projects_server
from shinylims.tables.samples import samples_ui, samples_server
from shinylims.tables.sequencing import seq_ui, seq_server  # Make sure these function names match what's in your file

# Import database utilities
from src.shinylims.data.db_utils import get_db_update_info, refresh_db_connection
#from src.shinylims.data.db_utils import refresh_db_connection

# Import data utilities
from src.shinylims.data.data_utils import (
    fetch_projects_data, 
    fetch_all_samples_data, 
    fetch_sequencing_data
)

# Add assets
from pathlib import Path
css_path = Path(__file__).parent / "assets" / "styles.css"
from shinylims.data.brand_utils import load_brand_config, generate_comprehensive_brand_css, get_logo_path
brand = load_brand_config()

# Logo file to use
logo_file = "assets/vetinst-logo.png"
logo_path = f"/{logo_file}" 

####################
# CONSTRUCT THE UI #
####################

app_ui = ui.page_navbar(
    
    # Select bootstrap theme
    #theme.cerulean(),

    # Add Google Fonts and custom CSS that overrides the theme
    ui.head_content(
        ui.tags.link(
            rel="stylesheet",
            href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:ital,wght@0,400;0,500;0,600;1,400;1,500;1,600&display=swap"
        ),
        ui.tags.style(generate_comprehensive_brand_css(brand)),
        ui.include_css(css_path)
    ),

    
    # Push the navbar items to the right
    #ui.nav_spacer(),  
    # Add a spacer before the nav panels to push them toward center
    ui.nav_spacer(),

    # Kickstart server side ui reactive functions using latest database update
    ui.nav_control(ui.output_ui("render_updated_data")), 

    # Define ui panels
    ui.nav_panel("Projects", projects_ui()),
    ui.nav_panel("Samples", samples_ui()),  
    ui.nav_panel("Illumina Sequencing", seq_ui()),
    # Add another spacer after panels to push the button to the far right
    ui.nav_spacer(),
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

        # Get database update information        
        update_info = db_update_info_reactive.get()
    
        # Convert timestamps to CET
        cet = pytz.timezone('Europe/Oslo')
    
        # Current time for app refresh
        now = datetime.datetime.now(cet)
        app_refresh_time = now.strftime("%Y-%m-%d %H:%M")
    
        # Get last update timestamps for each table
        proj_time = seq_time = samples_time = "Not available"
    
        if update_info.get('table_updates'):
            if 'projects' in update_info['table_updates']:
                proj_update = update_info['table_updates']['projects']
                try:
                    proj_time = datetime.datetime.fromisoformat(proj_update['timestamp']).strftime("%Y-%m-%d %H:%M")
                except:
                    proj_time = proj_update['timestamp']
                
            if 'samples' in update_info['table_updates']:
                samples_update = update_info['table_updates']['samples']
                try:
                    samples_time = datetime.datetime.fromisoformat(samples_update['timestamp']).strftime("%Y-%m-%d %H:%M")
                except:
                    samples_time = samples_update['timestamp']
                
            if 'ilmn_sequencing' in update_info['table_updates']:
                seq_update = update_info['table_updates']['ilmn_sequencing']
                try:
                    seq_time = datetime.datetime.fromisoformat(seq_update['timestamp']).strftime("%Y-%m-%d %H:%M")
                except:
                    seq_time = seq_update['timestamp']
    
        # Build a very minimal tooltip
        text = f"""<strong>SQL db last updated:</strong><br>
        ➡️ Projects:<br>{proj_time}<br>
        ➡️ Samples:<br>{samples_time}<br>
        ➡️ Sequencing:<br>{seq_time}<br><br>
        <strong>App last refreshed:</strong><br>
        🔄 {app_refresh_time}"""
    
        return ui.HTML(text)
    
    
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

# Get the absolute path to the www directory
www_dir = Path(__file__).parent / "www"

app = App(app_ui, server, static_assets=www_dir)