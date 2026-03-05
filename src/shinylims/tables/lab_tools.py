from shiny import ui, reactive, render
import pandas as pd
import re

from src.shinylims.data.db_utils import query_to_dataframe
from shinylims.tables.reagents import reagents_ui, reagents_server
from shinylims.security import is_allowed_reagents_user, reagents_access_policy_summary


def lab_tools_ui():
    return ui.div(
        ui.output_ui("lab_tools_content"),
        class_="p-3"
    )


def lab_tools_server(input, output, session):
    current_tool = reactive.Value("landing")

    @reactive.Effect
    @reactive.event(input.main_nav)
    def reset_lab_tools_on_tab_select():
        if input.main_nav() == "lab_tools":
            current_tool.set("landing")

    @reactive.Effect
    @reactive.event(input.main_nav_header_click)
    def reset_lab_tools_on_tab_header_click():
        if (input.main_nav_header_click() or "") == "lab_tools":
            current_tool.set("landing")

    @reactive.Effect
    @reactive.event(input.open_tool_reagents)
    def open_tool_reagents():
        current_tool.set("reagents")

    @reactive.Effect
    @reactive.event(input.open_tool_storage)
    def open_tool_storage():
        current_tool.set("storage")

    @reactive.Effect
    @reactive.event(input.back_to_tools)
    def back_to_tools():
        current_tool.set("landing")

    @output
    @render.ui
    def lab_tools_content():
        page = current_tool.get()

        if page == "landing":
            return ui.div(
                ui.h3("Lab Tools", class_="mb-3"),
                ui.p("Choose a tool to continue.", class_="text-muted mb-4"),
                ui.layout_columns(
                    ui.card(
                        ui.card_body(
                            ui.h5("📦 Reagent Lot Registration"),
                            ui.p("Create and submit reagent lots to Clarity LIMS.", class_="text-muted mb-3"),
                            ui.input_action_button("open_tool_reagents", "Open Tool", class_="btn-primary")
                        ),
                        class_="h-100"
                    ),
                    ui.card(
                        ui.card_body(
                            ui.h5("🧰 Storage Box Status"),
                            ui.p("View populated/discarded storage containers.", class_="text-muted mb-3"),
                            ui.input_action_button("open_tool_storage", "Open Tool", class_="btn-primary")
                        ),
                        class_="h-100"
                    ),
                    col_widths=[6, 6]
                )
            )

        if page == "reagents":
            if not is_allowed_reagents_user(session):
                return ui.div(
                    ui.div(
                        ui.input_action_button("back_to_tools", "← Back to Tools", class_="btn btn-outline-secondary btn-sm mb-3")
                    ),
                    ui.card(
                        ui.card_header("📦 Reagent Lot Registration"),
                        ui.card_body(
                            ui.h5("You do not have access"),
                            ui.p(
                                f"Allowed access is {reagents_access_policy_summary()}.",
                                class_="text-muted mb-1"
                            ),
                            ui.p("Contact admin to be added as an individual user if needed.", class_="text-muted mb-0"),
                        ),
                        class_="border-danger"
                    )
                )
            return ui.div(
                ui.div(
                    ui.input_action_button("back_to_tools", "← Back to Tools", class_="btn btn-outline-secondary btn-sm mb-3")
                ),
                reagents_ui()
            )

        return ui.div(
            ui.div(
                ui.input_action_button("back_to_tools", "← Back to Tools", class_="btn btn-outline-secondary btn-sm mb-3")
            ),
            ui.h4("📦 Storage Box Status", class_="mb-3"),
            ui.output_ui("storage_status_tool")
        )

    @output
    @render.ui
    def storage_status_tool():
        try:
            query = """
            SELECT 
                container_name,
                state,
                last_checked,
                last_updated
            FROM storage_containers
            """
            containers_df = query_to_dataframe(query)

            if containers_df.empty:
                return ui.p("No storage container data available.")

            def extract_number(name):
                if pd.isna(name):
                    return 0
                match = re.search(r"(\d+)", str(name))
                return int(match.group(1)) if match else 0

            containers_df["sort_num"] = containers_df["container_name"].apply(extract_number)
            containers_df = containers_df.sort_values(by="sort_num", ascending=False)

            containers_df = containers_df.rename(columns={
                "container_name": "Box Name",
                "state": "Status",
                "last_checked": "Last Checked",
                "last_updated": "Last Updated",
            })

            for col in ["Last Checked", "Last Updated"]:
                if col in containers_df.columns:
                    containers_df[col] = pd.to_datetime(containers_df[col], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")

            def format_status(status):
                if status == "Discarded":
                    return f"🗑️ {status}"
                if status == "Populated":
                    return f"✅ {status}"
                return status

            containers_df["Status"] = containers_df["Status"].apply(format_status)

            populated_count = containers_df["Status"].str.contains("Populated", case=False).sum()
            discarded_count = containers_df["Status"].str.contains("Discarded", case=False).sum()
            total_count = len(containers_df)

            summary = ui.p(
                f"📦 Total: {total_count} | ✅ Populated: {populated_count} | 🗑️ Discarded: {discarded_count}",
                style="font-weight: bold; margin-bottom: 15px;"
            )

            display_df = containers_df.drop("sort_num", axis=1)
            table_html = display_df.to_html(
                index=False,
                escape=True,
                classes="table table-striped table-bordered table-sm",
                border=0,
            )

            styled_table = f"""
            <style>
                .storage-status-table {{
                    width: 100%;
                    max-height: 70vh;
                    overflow-y: auto;
                    overflow-x: auto;
                }}
                .storage-status-table table {{
                    width: 100%;
                    table-layout: fixed;
                    margin: 0;
                }}
                .storage-status-table th,
                .storage-status-table td {{
                    text-align: left;
                    vertical-align: middle;
                    white-space: nowrap;
                }}
                .storage-status-table th {{
                    position: sticky;
                    top: 0;
                    z-index: 2;
                    background: #f8f9fa;
                }}
            </style>
            <div class="storage-status-table">
                {table_html}
            </div>
            """

            return ui.div(
                summary,
                ui.HTML(styled_table)
            )
        except Exception as e:
            return ui.p(f"⚠️ Error loading storage container data: {str(e)}", style="color: red;")

    reagents_server(input, output, session)
