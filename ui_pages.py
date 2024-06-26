'''
Module containing ui page definitions for the Clarity LIMS Shiny App
'''

from shiny import App, render, ui, req, reactive
from faicons import icon_svg


# Contents of the Projects page
projects_page = ui.navset_tab(
    ui.nav_panel("Table  (Nov 2023 ->)",
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
                        ),
                    )
                ),
                open=False,
                value="column_selection_projects",
                icon=icon_svg("table-columns")
            ),
            class_="mb-3 mt-3",
            open = False,
            multiple=False
        ),
        class_="mb-3"
    ),
    
    ui.output_ui("data_projects")
),
ui.nav_panel("Info",ui.card(ui.output_ui("projects_info"))))


# Contents of the WGS samples page
wgs_samples_page = ui.navset_tab(
    ui.nav_panel("Table (Nov 2023 ->)",
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
            open = False,
            multiple=False
        ),
        class_="d-flex flex-column mb-3"
    ),
    ui.output_ui("data_wgs"),

),
ui.nav_panel("Table Historical Data (Nov 2019 - Nov 2023)", 
    ui.div(
        ui.accordion(
            ui.accordion_panel(
                ui.output_text("filters_title_historical"), # Dynamic title handled by the server function
                ui.row(ui.column(3,
                    ui.input_slider(
                        id="slider_historical", 
                        label="Løpende nr",
                        min= 0, # Will be populated by the server function,
                        max=5073, # Will be populated by the server function,
                        value=[0, 5073]
                    ),),),
                    value="filters_historical", icon=icon_svg("filter"),),
            ui.accordion_panel(
                ui.output_text("column_selection_title_historical"), # Dynamic title handled by the server function
                    ui.div(
                        ui.input_checkbox_group(
                            id="fields_to_display_historical",
                            inline=False,
                            label=ui.div("Field Selection", class_="fw-bold"),
                            choices= [], # Will be populated by the server function
                            selected= [] # Will be populated by the server function
                                ),
                        ),
                open=False,
                value="column_selection_historical",
                icon=icon_svg("table-columns")
            ),
            class_="mb-3 mt-3",
            open = False,
            multiple=False
        ),
        class_="d-flex flex-column mb-3"
    ),
    ui.output_ui("historical_wgs")),

ui.nav_panel("Info",ui.card(ui.output_ui("wgs_info"))))


# Contents of the Prepared samples page
prepared_samples_page = ui.navset_tab(
    ui.nav_panel("Table (Nov 2023 ->)",
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
                        style="display: flex; align-items: flex-start; width: 100%;"
                    )
                ),
                open=False,
                value="column_selection_prepared",  # Provide a unique value
                icon=icon_svg("table-columns")
            ),
            class_="mb-3 mt-3",
            open = False,
            multiple=False
        ),
        class_="mb-3"
    ),
    
    ui.output_ui("data_prepared"),
),
ui.nav_panel("Info",ui.card(ui.output_ui("prepared_info"))))

# Contents of the Sequencing page
seq_page = ui.navset_tab(
    ui.nav_panel("Table (Nov 2023 ->)",
    ui.div(
        ui.accordion(
            ui.accordion_panel(
                ui.output_text("filters_title_seq"),  # Filter icon
                ui.row(ui.column(3,
                    ui.input_date_range(
                        id="date_range_seq", 
                        label="Date Range",
                        start=None, # Will be populated by the server function,
                        end=None, # Will be populated by the server function,
                    ),
                    ui.input_action_button(
                        id="reset_date_seq", 
                        label="Reset Date Filter",
                    ),),
                    ui.column(3,
                    ui.input_selectize(
                        id="filter_cassette_seq", 
                        label="Casette Type", 
                        choices=[],  # Will be populated in the server, 
                        multiple=True, 
                    ),),
                    ui.column(3,
                    ui.input_selectize(
                        id="filter_reads_seq", 
                        label="Read Length", 
                        choices=[],  # Will be populated in the server, 
                        multiple=True, 
                    ),),),
                    value="filters", icon=icon_svg("filter"),
                    
            ),
            ui.accordion_panel(
                ui.output_text("column_selection_title_seq"),  # Dynamic title for Column Selection
                ui.div(
                    ui.div(
                        ui.div(
                            ui.input_checkbox_group(
                                id="fields_to_display_seq",
                                inline=False,
                                label=ui.div("Field Selection", class_="fw-bold"),
                                choices=[], # Will be populated by the server function
                                selected=[] # Will be populated by the server function
                            ),
                        ),
                        #style="display: flex; align-items: flex-start; width: 100%;"
                    )
                ),
                open=False,
                value="column_selection_seq",  # Provide a unique value
                icon=icon_svg("table-columns")
            ),
            class_="mb-3 mt-3", 
            open = False,
            multiple=False
        ),
        class_="mb-3"
    ),
    ui.output_ui("data_seq"),
),
ui.nav_panel("Table Historical Data (Sept 2019 - Nov 2023)", 
        ui.div(
        ui.accordion(
            ui.accordion_panel(
                ui.output_text("filters_title_SeqHistorical"), # Dynamic title handled by the server function
                ui.row(ui.column(3,
                    ui.code("No filters yet defined"
                    ),),),
                    value="filters_SeqHistorical", icon=icon_svg("filter"),),
            ui.accordion_panel(
                ui.output_text("column_selection_title_SeqHistorical"), # Dynamic title handled by the server function
                    ui.input_checkbox_group(
                        id="fields_to_display_SeqHistorical",
                        inline=False,
                        label=ui.div("Field Selection", class_="fw-bold"),
                        choices= [], # Will be populated by the server function
                        selected= [] # Will be populated by the server function
                            ),
                open=False,
                value="column_selection_SeqHistorical",
                icon=icon_svg("table-columns")
            ),
            class_="mb-3 mt-3",
            open = False,
            multiple=False
        ),
        class_="d-flex flex-column mb-3"
    ),
    ui.output_ui("SeqHistorical")),

ui.nav_panel("Plots", ui.code("Plots will be displayed here. Waiting for iTables support for selecting data from the table: https://github.com/mwouts/itables/issues/250")),
ui.nav_panel("Info",ui.div(ui.code("NB!! Waiting for instrument integration for getting certain QC values. The data collection cron script will also be rewritten after instrument integration is in order NB!!"),
    ui.card(ui.output_ui("seqRun_info"),))))

