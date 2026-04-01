'''
storage.py - UI and server logic for the Storage Box Status view.
'''

import re

import pandas as pd
from shiny import render, ui

from shinylims.integrations.data_utils import fetch_storage_containers_data


def storage_ui():
    return ui.output_ui("storage_status_tool")


def storage_server():
    @render.ui
    def storage_status_tool():
        try:
            containers_df = fetch_storage_containers_data()

            if containers_df.empty:
                return ui.p("No storage container data available.")

            def extract_number(name):
                if pd.isna(name):
                    return 0
                match = re.search(r"(\d+)", str(name))
                return int(match.group(1)) if match else 0

            containers_df["sort_num"] = containers_df["Box Name"].apply(extract_number)
            containers_df = containers_df.sort_values(by="sort_num", ascending=False)

            for col in ["Created Date", "Last Modified"]:
                if col in containers_df.columns:
                    containers_df[col] = pd.to_datetime(
                        containers_df[col], errors="coerce"
                    ).dt.strftime("%Y-%m-%d")

            def format_status(status):
                if status == "Discarded":
                    return f"🗑️ {status}"
                if status in {"Populated", "Active"}:
                    return f"✅ {status}"
                return status

            containers_df["Status"] = containers_df["Status"].apply(format_status)

            active_count = containers_df["Status"].str.contains(
                "Active|Populated", case=False, regex=True
            ).sum()
            discarded_count = containers_df["Status"].str.contains(
                "Discarded", case=False
            ).sum()
            total_count = len(containers_df)

            summary = ui.p(
                f"📦 Total: {total_count} | ✅ Active: {active_count} | 🗑️ Discarded: {discarded_count}",
                style="font-weight: bold; margin-bottom: 15px;",
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
                    max-height: 90vh;
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

            return ui.div(summary, ui.HTML(styled_table))
        except Exception as e:
            return ui.p(
                f"⚠️ Error loading storage container data: {str(e)}",
                style="color: red;",
            )
