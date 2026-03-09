from shiny import ui, reactive, render

from shinylims.features.projects import projects_ui
from shinylims.features.samples import samples_ui
from shinylims.features.sequencing import seq_ui


def metadata_tables_ui():
    return ui.div(
        ui.output_ui("metadata_tables_content"),
        class_="p-3"
    )


def metadata_tables_server(input, output, session):
    current_table = reactive.Value("landing")

    @reactive.Effect
    @reactive.event(input.main_nav)
    def reset_metadata_on_tab_select():
        if input.main_nav() == "metadata_tables":
            current_table.set("landing")

    @reactive.Effect
    @reactive.event(input.main_nav_header_click)
    def reset_metadata_on_tab_header_click():
        if (input.main_nav_header_click() or "") == "metadata_tables":
            current_table.set("landing")

    @reactive.Effect
    @reactive.event(input.open_table_projects)
    def open_table_projects():
        current_table.set("projects")

    @reactive.Effect
    @reactive.event(input.open_table_samples)
    def open_table_samples():
        current_table.set("samples")

    @reactive.Effect
    @reactive.event(input.open_table_sequencing)
    def open_table_sequencing():
        current_table.set("sequencing")

    @reactive.Effect
    @reactive.event(input.back_to_metadata_tables)
    def back_to_metadata_tables():
        current_table.set("landing")

    @output
    @render.ui
    def metadata_tables_content():
        page = current_table.get()

        if page == "landing":
            return ui.div(
                ui.h3("Metadata Tables", class_="mb-3"),
                ui.p("Choose a table to continue.", class_="text-muted mb-4"),
                ui.layout_columns(
                    ui.card(
                        ui.card_body(
                            ui.h5("📁 Projects"),
                            ui.p("Browse project-level metadata from Clarity LIMS.", class_="text-muted mb-3"),
                            ui.input_action_button("open_table_projects", "Open Table", class_="btn-primary")
                        ),
                        class_="h-100"
                    ),
                    ui.card(
                        ui.card_body(
                            ui.h5("🧪 Samples"),
                            ui.p("Explore sample metadata and exports.", class_="text-muted mb-3"),
                            ui.input_action_button("open_table_samples", "Open Table", class_="btn-primary")
                        ),
                        class_="h-100"
                    ),
                    ui.card(
                        ui.card_body(
                            ui.h5("🧬 Illumina Sequencing"),
                            ui.p("Inspect sequencing run metadata and metrics.", class_="text-muted mb-3"),
                            ui.input_action_button("open_table_sequencing", "Open Table", class_="btn-primary")
                        ),
                        class_="h-100"
                    ),
                    col_widths=[4, 4, 4]
                )
            )

        if page == "projects":
            return ui.div(
                ui.div(
                    ui.input_action_button(
                        "back_to_metadata_tables",
                        "← Back to Metadata Tables",
                        class_="btn btn-outline-secondary btn-sm",
                    ),
                    ui.h4("📁 Projects", class_="mb-0"),
                    class_="d-flex align-items-center gap-3 mb-3",
                ),
                projects_ui(),
            )

        if page == "samples":
            return ui.div(
                ui.div(
                    ui.input_action_button(
                        "back_to_metadata_tables",
                        "← Back to Metadata Tables",
                        class_="btn btn-outline-secondary btn-sm",
                    ),
                    ui.h4("🧪 Samples", class_="mb-0"),
                    ui.div(
                        ui.input_switch("include_hist", "Include historical samples", False),
                        class_="ms-auto",
                    ),
                    class_="d-flex align-items-center gap-3 mb-3",
                ),
                samples_ui(),
            )

        return ui.div(
            ui.div(
                ui.input_action_button(
                    "back_to_metadata_tables",
                    "← Back to Metadata Tables",
                    class_="btn btn-outline-secondary btn-sm",
                ),
                ui.h4("🧬 Illumina Sequencing", class_="mb-0"),
                class_="d-flex align-items-center gap-3 mb-3",
            ),
            seq_ui(),
        )
