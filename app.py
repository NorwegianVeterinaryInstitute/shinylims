###########
# IMPORTS #
###########

import seaborn as sns   # will be used for some plots on the Sequencing Runs page
from shiny import App, render, ui, reactive
import datetime
import pytz  # For fixing timezone differences
from faicons import icon_svg
from shinyswatch import theme

# App modules
from ui_pages import projects_page, wgs_samples_page, prepared_samples_page
from ui_server import setup_projects_page, setup_wgs_samples_page, setup_prepared_samples_page
from data_utils import fetch_pinned_data
from mod_projects import modUI, modServer

####################
####################

app_ui = ui.page_fluid(

    ui.page_navbar(

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
        ui.nav_panel("Sequencing Runs", "Sequencing Run dataframe goes here"),
        ui.nav_control(ui.tooltip(ui.input_action_button("update_button", "Update Data", class_="btn-success"),
                       ui.output_ui("update_tooltip_output"), placement="right", id="update_tooltip")),

        # Title
        title=ui.tooltip(ui.span("Clarity LIMS Shiny App   ", icon_svg("circle-info")), ui.HTML(
            "App for viewing status of projects and samples submitted for NGS through Clarity LIMS.<br><br> Automatic data transfer from Clarity every 2nd hour.<br><br> 'Update Data' button will collect latest transferred data"), placement="right", id="title_tooltip")
    ),
    modUI=(id='mod_projects')
)


###################
# SERVER FUNCTION #
###################

def server(input, output, session):
    modServer = (id='mod_projects')

    ###########
    # RUN APP #
    ###########


app = App(app_ui, server)
