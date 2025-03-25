'''
sequencing.py - table module containing UI and server logic for the Sequencing table tab
'''

from shiny import render, ui
from itables.shiny import DT
import pandas as pd
from itables.javascript import JavascriptFunction

##############################
# UI ILMN SEQ TABLE
##############################

def seq_ui():
    return ui.div(
        #ui.h2("\u00A0", class_="mb-3 text-center"),
        ui.output_ui("data_seq")
    )

##############################
# SERVER ILMN SEQ TABLE
##############################

# Server logic for the Sequencing page
def seq_server(input, output, session, seq_df, seq_date_created):
    
    # Return HTML tag with DT table element
    @render.ui
    def data_seq():
        dat = seq_df.copy().reset_index(drop=True)
        
        # Properly format date columns for DataTables
        if "Seq Date" in dat.columns:
            # Convert to datetime type first
            dat["Seq Date"] = pd.to_datetime(dat["Seq Date"], errors='coerce')
            
            # Format dates as strings in a consistent format for display
            # Keep NaT values as empty strings
            dat["Seq Date"] = dat["Seq Date"].apply(
                lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else ''
            )
        
        # Determine indices for special column handling
        if 'Comment' in dat.columns:
            comment_index = dat.columns.get_loc('Comment')
        else:
            comment_index = "Dummy"

        if 'Run Number' in dat.columns:
            run_number_index = dat.columns.get_loc('Run Number')
        else:
            run_number_index = "Dummy"

        if 'Cluster density (K/mm2)' in dat.columns:
            cluster_density_index = dat.columns.get_loc('Cluster density (K/mm2)')
        else:
            cluster_density_index = "Dummy"
        
        # Find index for order column
        column_to_sort = "Seq Date"
        if column_to_sort in dat.columns:
            column_index = dat.columns.get_loc(column_to_sort)
            date_column_index = column_index  # Store for columnDefs
        else:
            column_index = 0  # Default to first column if Seq Date not found
            date_column_index = -1  # Indicates no date column found

        return ui.HTML(DT(dat, 
                          layout={"topEnd": "search", "top1": "searchBuilder"},
                          lengthMenu=[[200, 500, 1000, 2000, -1], [200, 500, 1000, 2000, "All"]],
                          select=True,  
                          column_filters="footer", 
                          search={"smart": True},
                          classes="compact nowrap hover order-column cell-border",  
                          scrollY="780px",
                          paging=True,
                          maxBytes=0, 
                          autoWidth=True,
                          keys=True,
                          buttons=[
                            {'extend': "spacer",
                             'style': 'bar',
                             'text': 'Column Settings'},
                            # Column visibility toggle
                            {
                                "extend": "colvis",
                                "text": "Selection"
                            },
                            {'extend': "spacer"},
                            # Button to deselect all columns
                            {
                                "text": "Deselect All",
                                "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    dt.columns().visible(false);
                                }
                                """)
                            },
                            # Button to select all columns
                            {
                                "text": "Select All",
                                "action": JavascriptFunction("""
                                function(e, dt, node, config) {
                                    dt.columns().visible(true);
                                }
                                """)
                            },
                            {'extend': "spacer",
                             'style': 'bar',
                             'text': 'Page Length'},
                             "pageLength",
                            {'extend': "spacer",
                             'style': 'bar',
                             'text': 'Export'},
                            # Collection of export options
                            {
                                "extend": "collection", 
                                "text": "Type",
                                "buttons": [
                                    # Copy to clipboard
                                    {
                                        "extend": "copyHtml5",
                                        "exportOptions": {"columns": ":visible"},
                                        "text": "Copy to Clipboard"
                                    },
                                    # CSV export with visible columns
                                    {
                                        "extend": "csvHtml5", 
                                        "exportOptions": {"columns": ":visible"},
                                        "title": "Sequencing Data Export",
                                        "text": "Export to CSV"
                                    },
                                    # Excel export with visible columns
                                    {
                                        "extend": "excelHtml5", 
                                        "exportOptions": {"columns": ":visible"},
                                        "title": "Sequencing Data Export",
                                        "text": "Export to Excel"
                                    }
                                ]
                            },
                            {'extend': "spacer",
                             'style': 'bar'},
                          ],
                          order=[[column_index, "desc"]],
                          columnDefs=[
                              {'targets': comment_index, 'className': 'left-column'},
                              {"className": "dt-center", "targets": "_all"},
                              {"targets": run_number_index, "render": JavascriptFunction("function(data, type, row) { return type === 'display' ? Math.round(data).toString() : data; }")},
                              {"targets": cluster_density_index, "render": JavascriptFunction("function(data, type, row) { return type === 'display' ? Math.round(data).toString() : data; }")},
                              # Explicitly define the Seq Date column as a date type for searchBuilder
                              {
                                  "targets": date_column_index,
                                  "type": "date",
                                  "render": JavascriptFunction("""
                                  function(data, type, row) {
                                      // For sorting and filtering
                                      if (type === 'sort' || type === 'type' || type === 'filter') {
                                          if (!data || data === '') {
                                              return null;
                                          }
                                          return data;
                                      }
                                      // For display
                                      return data;
                                  }
                                  """)
                              }
                          ]))
    

    # Define outputs that need to be returned
    output.data_seq = data_seq