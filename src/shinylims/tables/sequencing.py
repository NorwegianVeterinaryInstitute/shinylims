'''
sequencing.py - table module containing UI and server logic for the Sequencing table tab
'''

from shiny import render, ui, reactive
from faicons import icon_svg
from itables.shiny import DT
import pandas as pd
import datetime
import pytz
from itables.javascript import JavascriptFunction

# UI definition for the Sequencing page
def seq_ui():
    return ui.navset_tab(
        ui.nav_panel("Table (Nov 2023 ->)",
            ui.div(
                ui.accordion(
                    ui.accordion_panel(
                        ui.output_text("filters_title_seq"),  # Filter icon
                        ui.row(ui.column(3,
                            ui.input_date_range(
                                id="date_range_seq", 
                                label="Date Range",
                                start=None,
                                end=None,
                            ),
                            ui.input_action_button(
                                id="reset_date_seq", 
                                label="Reset Date Filter",
                            ),),
                            ui.column(3,
                                ui.input_selectize(
                                    id="filter_cassette_seq", 
                                    label="Casette Type", 
                                    choices=[],
                                    multiple=True, 
                                ),),
                            ui.column(3,
                                ui.input_selectize(
                                    id="filter_reads_seq", 
                                    label="Read Length", 
                                    choices=[],
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
                                        choices=[],
                                        selected=[]
                                    ),
                                ),
                            )
                        ),
                        open=False,
                        value="column_selection_seq",  # Provide a unique value
                        icon=icon_svg("table-columns")
                    ),
                    class_="mb-3 mt-3", 
                    open=False,
                    multiple=False
                ),
                class_="mb-3"
            ),
            ui.output_ui("data_seq"),
        ),
        ui.nav_panel("Plots", ui.code("Plots will be displayed here. Waiting for iTables support for selecting data from the table: https://github.com/mwouts/itables/issues/250")),
        ui.nav_panel("Info",ui.div(
            ui.code("NB!! Waiting for instrument integration for getting certain QC values. The data collection cron script will also be rewritten after instrument integration is in order NB!!"),
            ui.card(ui.output_ui("seqRun_info"),)))
    )

# Server logic for the Sequencing page
def seq_server(input, output, session, seq_df, seq_date_created):
    # Define a reactive value to store the filtered dataframe
    seq_filtered_data = reactive.Value(seq_df)

    # Helper function for safely getting columns with different possible names
    def get_column_safe(df, column_names, default_value=None):
        """
        Safely get a column from a dataframe, trying multiple possible names.
        Returns default_value if none of the column names exist.
        """
        if not isinstance(column_names, list):
            column_names = [column_names]
        
        for col in column_names:
            if col in df.columns:
                return df[col]
        
        # If we get here, none of the columns exist
        return pd.Series([default_value] * len(df))
    
    @reactive.Effect
    def update_project_account_choices_seq():
        read_length_column = get_column_safe(seq_df, ['Read Length', 'read_length'])
        if not read_length_column.empty:
            unique_read_lengths = sorted(read_length_column.unique().tolist())
            ui.update_selectize("filter_reads_seq", choices=unique_read_lengths)
        else:
            ui.update_selectize("filter_reads_seq", choices=["No Read Length Data"])
    
    # Update cassette type filter
    @reactive.Effect
    def update_cassette_choices_seq():
        cassette_column = get_column_safe(seq_df, ['Casette Type', 'casette_type'])
        if not cassette_column.empty:
            unique_cassettes = cassette_column.unique().tolist()
            ui.update_selectize("filter_cassette_seq", choices=unique_cassettes)
        else:
            ui.update_selectize("filter_cassette_seq", choices=["No Cassette Type Data"])

    # Return HTML tag with DT table element
    @render.ui
    def data_seq():
        filtered_df = seq_df.copy()

        # Date filter
        start_date, end_date = input.date_range_seq()

        if start_date is not None and end_date is not None:
            date_col = 'Seq Date' if 'Seq Date' in filtered_df.columns else 'seq_date'
            if date_col in filtered_df.columns:
                # Convert the date column to datetime format first
                filtered_df[date_col] = pd.to_datetime(filtered_df[date_col], errors='coerce')
            
                # Now perform the filtering
                filtered_df = filtered_df[
                    (filtered_df[date_col].isna()) | 
                    ((filtered_df[date_col] >= pd.to_datetime(start_date)) & 
                    (filtered_df[date_col] <= pd.to_datetime(end_date)))
                ]
                
        selected_casette_type = input.filter_cassette_seq()
        
        if selected_casette_type:
            filtered_df = filtered_df[filtered_df['Casette Type'].isin(selected_casette_type)]
        
        selected_filter_reads_seq = input.filter_reads_seq()
        if selected_filter_reads_seq:
            filtered_df = filtered_df[filtered_df['Read Length'].isin(selected_filter_reads_seq)]

        selected_columns = list(input.fields_to_display_seq())
        dat = filtered_df.reset_index(drop=True)
        seq_filtered_data.set(filtered_df)
        
        if 'Comment' in dat[selected_columns].columns:
            comment_index = dat[selected_columns].columns.get_loc('Comment')
        else:
            comment_index = "Dummy"

        if 'Run Number' in dat[selected_columns].columns:
            run_number_index = dat[selected_columns].columns.get_loc('Run Number')
        else:
            run_number_index = "Dummy"

        if 'Cluster density (K/mm2)' in dat[selected_columns].columns:
            cluster_density_index = dat[selected_columns].columns.get_loc('Cluster density (K/mm2)')
        else:
            cluster_density_index = "Dummy"
        
        #Find index for order column
        column_to_sort = "Seq Date"
        column_index = selected_columns.index(column_to_sort)

        return ui.HTML(DT(dat[selected_columns], 
                          layout={"topEnd": "search"}, 
                          column_filters="footer", 
                          search={"smart": True},
                          classes="compact nowrap hover order-column cell-border",  
                          scrollY="750px",
                          paging=False,
                          maxBytes=0, 
                          autoWidth=True,
                          keys=True,
                          buttons=["copyHtml5",
                                  {"extend": "csvHtml5", "title": "WGS Sample Data"},
                                  {"extend": "excelHtml5", "title": "WGS Sample Data"},],
                          order=[[column_index, "desc"]],
                          columnDefs=[
                              {'targets': comment_index, 'className': 'left-column'},
                              {"className": "dt-center", "targets": "_all"},
                              {"targets": run_number_index, "render": JavascriptFunction("function(data, type, row) { return type === 'display' ? Math.round(data).toString() : data; }")},
                              {"targets": cluster_density_index, "render": JavascriptFunction("function(data, type, row) { return type === 'display' ? Math.round(data).toString() : data; }")}
                              ]))

    @reactive.Effect
    def set_default_date_range_seq():
        try:
            date_column = get_column_safe(seq_df, ['Seq Date', 'seq_date'])
            if not date_column.empty:
                min_date = pd.to_datetime(date_column, errors='coerce').min()
                if pd.notna(min_date):
                    start_date = min_date.date()
                else:
                    start_date = datetime.date(2023, 1, 1)  # Fallback
            else:
                start_date = datetime.date(2023, 1, 1)  # Fallback
        
            ui.update_date_range(
                "date_range_seq",
                start=start_date,
                end=datetime.date.today()
            )
        except Exception as e:
            print(f"Error setting default date range for sequencing: {e}")
            ui.update_date_range(
                "date_range_seq",
                start=datetime.date(2023, 1, 1),
                end=datetime.date.today()
            )
    
    # Define default column checkbox selection
    @reactive.Effect
    def set_default_fields_to_display_seq():
        ui.update_checkbox_group(
            "fields_to_display_seq",
            choices=seq_df.columns.tolist(),
            selected=seq_df.columns.tolist()
        )

    # Reset date filter to default with action button
    @reactive.Effect
    @reactive.event(input.reset_date_seq)
    def reset_date_range_seq():
        try:
            date_column = get_column_safe(seq_df, ['Seq Date', 'seq_date'])
            if not date_column.empty:
                min_date = pd.to_datetime(date_column, errors='coerce').min()
                if pd.notna(min_date):
                    start_date = min_date.date()
                else:
                    start_date = datetime.date(2023, 1, 1)  # Fallback
            else:
                start_date = datetime.date(2023, 1, 1)  # Fallback
                
            ui.update_date_range(
                "date_range_seq",
                start=start_date,
                end=datetime.date.today()
            )
        except Exception as e:
            print(f"Error resetting date range for sequencing: {e}")
            ui.update_date_range(
                "date_range_seq",
                start=datetime.date(2023, 1, 1),
                end=datetime.date.today()
            )

    # Render title on filter accordian
    @render.text
    def filters_title_seq():
        start_date, end_date = input.date_range_seq()
        casette = input.filter_cassette_seq()
        reads = input.filter_reads_seq()

        num_filters = 0
        try:
            date_column = get_column_safe(seq_df, ['Seq Date', 'seq_date'])
            if not date_column.empty:
                min_date = pd.to_datetime(date_column, errors='coerce').min()
                if pd.notna(min_date) and (start_date != min_date.date() or end_date != datetime.date.today()):
                    num_filters += 1
        except:
            pass
            
        if casette:
            num_filters += 1
        if reads:
            num_filters += 1

        total_entries = len(seq_df)
        filtered_entries = len(seq_filtered_data())
        
        if num_filters > 0:
            return f'Filters ({num_filters} filters applied, {filtered_entries} of {total_entries} sequencing runs)'
        else:
            return f"Filters (All {total_entries} sequencing runs shown)"
    
    # Render title on column selection accordian
    @render.text
    def column_selection_title_seq():
        selected_columns = list(input.fields_to_display_seq())
        total_columns = len(seq_df.columns)
        num_selected = len(selected_columns)
        return f"Column Selection ({num_selected} of {total_columns} columns selected)"
    
    @render.ui
    def seqRun_info():
        text = f"<h3>Data in table is collected from pinned data generated by this script</h3> \
        <a href='https://github.com/NorwegianVeterinaryInstitute/nvi_lims_epps/blob/main/shiny_app/shiny_sequencing_runs.py'>shiny_sequencing_runs.py (link)</a> <br> \
        <h3>Data fields collection </h3> \
        <p>This table is created by using the sequencing steps as starting point and traversing back to step 7 (Generate SampleSheet) and step 6 (Make Final Loading Dilution) to retrieve data</p> \
        <p><strong>Step 8 (NS/MS Run):</strong> Technician Name, Species, Experiment Name, Comment, Run ID, Flow Cell ID, Reagent Cartridge ID, Date </p>\
        <p><strong>Step 7 (Generate SampleSheet):</strong> Read 1 Cycles, Read 2 Cycles, Index Cycles </p>\
        <p><strong>Step 6 (Make Final Loading Dilution):</strong> Final Library Loading (pM), Volume 20pM Denat Sample (µl), PhiX / library spike-in (%), Average Size - bp  </p>\
        <p>Table will not be updated until the sequencing step has been completed<p>\
        <h3>Last pinned data update</h3><br>\
        {(datetime.datetime.fromisoformat(seq_date_created).astimezone(pytz.timezone('Europe/Berlin'))).strftime('%Y-%m-%d (kl %H:%M)')}"
        
        return ui.HTML(text)
        
    # Define outputs that need to be returned
    output.data_seq = data_seq
    output.filters_title_seq = filters_title_seq
    output.column_selection_title_seq = column_selection_title_seq
    output.seqRun_info = seqRun_info