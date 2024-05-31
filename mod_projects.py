from shiny import module, ui, render


@module.ui
def modUI():
    return ui.TagList(
        ui.div(
            ui.accordion(
                ui.accordion_panel(
                    # Title handle by server function
                    ui.output_text("filters_title_projects"),
                    ui.row(ui.column(3,
                                     ui.input_date_range(
                                         id="date_range_projects",
                                         label="Open Date Range",
                                         start=None,  # Will be populated by the server function,
                                         end=None,  # Will be populated by the server function,
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
                                    label=ui.div("Field Selection",
                                                 class_="fw-bold"),
                                    choices=[],
                                    selected=[],
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
                class_="d-flex flex-column bd-highlight mb-3 mt-3",
                open=False,
                multiple=False
            ),
            class_="d-flex flex-column bd-highlight mb-3"
        ),

        ui.output_ui("data_projects")
    )


@module.server
def modServer(input, output, session):

    # Define a reactive value to store the filtered dataframe
    # projects_filtered_data = reactive.Value(projects_df)
    projects_df, project_date_created = fetch_pinned_data(
        "vi2172/projects_limsshiny")

    @render.ui
    def data_projects():
        # Filter data using selected date range filter
        start_date, end_date = input.date_range_projects()
        filtered_df = projects_df[(projects_df['Open Date'] >= pd.to_datetime(
            start_date)) & (projects_df['Open Date'] <= pd.to_datetime(end_date))]

        # Filter data using the "show projects with comment only"-button
        project_comment_filter = input.project_comment_filter()
        if project_comment_filter == True:
            filtered_df = filtered_df[filtered_df['Comment'].notna()]

        # Pandas will insert indexing, which we dont want
        dat = filtered_df.reset_index(drop=True)

        # Store selected columns in variable and set the filtered df in reactive value
        selected_columns = list(input.fields_to_display_projects())
        projects_filtered_data.set(filtered_df)

        # Return HTML tag with DT table element
        return ui.HTML(DT(dat[selected_columns],
                          layout={"topEnd": "search"},
                          column_filters="footer",
                          search={"smart": True},
                          # lengthMenu=[[20, 30, 50, 100, 200, -1], [20, 30, 50, 100, 200, "All"]],
                          classes="display compact order-column",
                          # scrollY=True,
                          scrollY="750px",
                          scrollCollapse=True,
                          paging=False,
                          scrollX=True,
                          maxBytes=0,
                          autoWidth=True,
                          keys=True,
                          buttons=[  # "pageLength",
            "copyHtml5",
                                  {"extend": "csvHtml5", "title": "WGS Sample Data"},
                                  {"extend": "excelHtml5", "title": "WGS Sample Data"},],
                          order=[[0, "desc"]],))

    # Define default column checkbox selection
    @reactive.Effect
    def set_default_fields_to_display_projects():
        ui.update_checkbox_group(
            "fields_to_display_projects",
            choices=projects_df.columns.tolist(),
            selected=['Open Date', 'Project Name', 'Samples',
                      'Submitter', 'Submitting Lab', 'Comment']
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
