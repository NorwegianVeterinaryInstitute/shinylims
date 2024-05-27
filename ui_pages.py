'''
Module containing ui page definitions for the Clarity LIMS Shiny App
'''

from shiny import App, render, ui, req, reactive
from faicons import icon_svg


# Contents of the Projects page
projects_page = ui.page_fluid(
    ui.div(
        ui.accordion(
            ui.accordion_panel(
                ui.output_text("filters_title_projects"),# Title handle by server function
                ui.row(ui.column(3,
                    ui.input_date_range(
                        id="date_range_projects", 
                        label="Open Date Range",
                        start=None, # Will be populated by the server function,
                        end=None, # Will be populated by the server function,
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
                                selected= [], 
                            ),
                            style="flex: 2; margin-right: 20px;"
                        ),
                        style="display: flex; align-items: flex-start;"
                    )
                ),
                open=False,
                value="column_selection_projects",
                icon=icon_svg("table-columns")
            ),
            open = False,
            multiple=False
        ),
    ),
    
    ui.output_ui("data_projects")
)


# Contents of the WGS samples page
wgs_samples_page = ui.page_fluid(
    ui.div(
        ui.accordion(
            ui.accordion_panel(
                ui.output_text("filters_title"), # Dynamic title handled by the server function
                ui.row(ui.column(3,
                    ui.input_date_range(
                        id="date_range", 
                        label="Received Date Range",
                        start= None, # Will be populated by the server function,
                        end=None # Will be populated by the server function,
                    ),
                    ui.input_action_button(
                        id="reset_date", 
                        label="Reset Date Filter",
                    ),),
                    ui.column(3,
                    ui.input_selectize(
                        id="filter_progress", 
                        label="Progress", 
                        choices=[],  # Will be populated by the server function, 
                        multiple=True, 
                    ),),
                    ui.column(3,
                    ui.input_selectize(
                        id="filter_project_account", 
                        label="Project Account", 
                        choices=[],  # Will be populated by the server function, 
                        multiple=True, 
                    ),),
                    ui.column(3,   
                    ui.input_selectize(
                        id="filter_experiment_name", 
                        label="Experiment Name", 
                        choices=[],  # Will be populated by the server function
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
                                choices= [], # Will be populated by the server function
                                selected= [] # Will be populated by the server function
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
                value="column_selection",
                icon=icon_svg("table-columns")
            ),
            open = False,
            multiple=False
        ),
    ),

    ui.output_ui("data_wgs")

)


# Contents of the Prepared samples page
prepared_samples_page = ui.page_fluid(
    ui.div(
        ui.accordion(
            ui.accordion_panel(
                ui.output_text("filters_title_prepared"),  # Filter icon
                ui.row(ui.column(3,
                    ui.input_date_range(
                        id="date_range_prepared", 
                        label="Received Date Range",
                        start=None, # Will be populated by the server function,
                        end=None, # Will be populated by the server function,
                    ),
                    ui.input_action_button(
                        id="reset_date_prepared", 
                        label="Reset Date Filter",
                    ),),
                    ui.column(3,
                    ui.input_selectize(
                        id="filter_progress_prepared", 
                        label="Progress", 
                        choices=[],  # Will be populated in the server, 
                        multiple=True, 
                    ),),
                    ui.column(3,
                    ui.input_selectize(
                        id="filter_project_account_prepared", 
                        label="Project Account", 
                        choices=[],  # Will be populated in the server, 
                        multiple=True, 
                    ),),
                    ui.column(3,   
                    ui.input_selectize(
                        id="filter_experiment_name_prepared", 
                        label="Experiment Name", 
                        choices=[],  # Will be populated in the server
                        multiple=True
                    ),),),
                    value="filters", icon=icon_svg("filter"),
                    
            ),
            ui.accordion_panel(
                ui.output_text("column_selection_title_prepared"),  # Dynamic title for Column Selection
                ui.div(
                    ui.div(
                        ui.div(
                            ui.input_checkbox_group(
                                id="fields_to_display_prepared",
                                inline=False,
                                label=ui.div("Field Selection", class_="fw-bold"),
                                choices=[], # Will be populated by the server function
                                selected=[] # Will be populated by the server function
                            ),
                            style="flex: 2; margin-right: 20px;"
                        ),
                        style="display: flex; align-items: flex-start;"
                    )
                ),
                open=False,
                value="column_selection_prepared",  # Provide a unique value
                icon=icon_svg("table-columns")
            ),
            class_="d-flex-inline bd-highlight mb-3", 
            open = False,
            multiple=False
        ),
        class_="d-flex flex-column bd-highlight mb-3"
    ),
    
    ui.output_ui("data_prepared")
)