'''
storage.py - UI and server logic for the Storage Box Status view.
'''

import re

import pandas as pd
from shiny import render, ui
from shiny.types import SilentException

from shinylims.integrations.data_utils import fetch_storage_containers_data

# Boxes named TEST... are scratch containers people make while trying things
# out in Clarity. They are never real storage, so they never belong in this view.
TEST_BOX_PREFIX = "TEST"

# "Populated" is the label older containers carry; both mean the box is in use.
ACTIVE_STATUS_PATTERN = r"Active|Populated"
DISCARDED_STATUS_PATTERN = r"Discarded"


def _is_test_box(name) -> bool:
    if pd.isna(name):
        return False
    return str(name).strip().upper().startswith(TEST_BOX_PREFIX)


def drop_test_boxes(containers_df: pd.DataFrame) -> pd.DataFrame:
    """Drop the scratch TEST* containers from a storage container frame."""
    if containers_df.empty or "Box Name" not in containers_df.columns:
        return containers_df
    return containers_df[~containers_df["Box Name"].apply(_is_test_box)]


def filter_by_status(
    containers_df: pd.DataFrame,
    show_active: bool,
    show_discarded: bool,
) -> pd.DataFrame:
    """Keep the statuses the user asked for.

    Only what is explicitly deselected gets hidden, so a container with an
    unrecognised status stays visible rather than vanishing without a trace.
    """
    if containers_df.empty or "Status" not in containers_df.columns:
        return containers_df

    status = containers_df["Status"].fillna("")
    keep = pd.Series(True, index=containers_df.index)
    if not show_active:
        keep &= ~status.str.contains(ACTIVE_STATUS_PATTERN, case=False, regex=True)
    if not show_discarded:
        keep &= ~status.str.contains(DISCARDED_STATUS_PATTERN, case=False, regex=True)
    return containers_df[keep]


def _extract_number(name) -> int:
    if pd.isna(name):
        return 0
    match = re.search(r"(\d+)", str(name))
    return int(match.group(1)) if match else 0


def _format_status(status) -> str:
    if status == "Discarded":
        return f"🗑️ {status}"
    if status in {"Populated", "Active"}:
        return f"✅ {status}"
    return status


TABLE_STYLE = """
<style>
    .storage-status-table {
        width: 100%;
        max-height: 90vh;
        overflow-y: auto;
        overflow-x: auto;
    }
    .storage-status-table table {
        width: 100%;
        table-layout: fixed;
        margin: 0;
    }
    .storage-status-table th,
    .storage-status-table td {
        text-align: left;
        vertical-align: middle;
        white-space: nowrap;
    }
    .storage-status-table th {
        position: sticky;
        top: 0;
        z-index: 2;
        background: #f8f9fa;
    }
</style>
"""


def build_storage_status_ui(
    containers_df: pd.DataFrame,
    show_active: bool = True,
    show_discarded: bool = True,
):
    """Render the summary line and table for the boxes the user asked to see."""
    if containers_df.empty:
        return ui.p("No storage container data available.")

    containers_df = drop_test_boxes(containers_df).copy()

    containers_df["sort_num"] = containers_df["Box Name"].apply(_extract_number)
    containers_df = containers_df.sort_values(by="sort_num", ascending=False)

    for col in ["Created Date", "Last Modified"]:
        if col in containers_df.columns:
            containers_df[col] = pd.to_datetime(
                containers_df[col], errors="coerce"
            ).dt.strftime("%Y-%m-%d")

    containers_df["Status"] = containers_df["Status"].apply(_format_status)

    containers_df = filter_by_status(containers_df, show_active, show_discarded)

    if containers_df.empty:
        return ui.p("No storage boxes match the selected statuses.")

    # Counted after filtering, so the summary always describes the table below it.
    active_count = containers_df["Status"].str.contains(
        ACTIVE_STATUS_PATTERN, case=False, regex=True
    ).sum()
    discarded_count = containers_df["Status"].str.contains(
        DISCARDED_STATUS_PATTERN, case=False, regex=True
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
    {TABLE_STYLE}
    <div class="storage-status-table">
        {table_html}
    </div>
    """

    return ui.div(summary, ui.HTML(styled_table))


def _checkbox_value(getter, default: bool = True) -> bool:
    """Read a checkbox that may not have registered with the browser yet."""
    try:
        value = getter()
    except SilentException:
        return default
    return default if value is None else bool(value)


def storage_ui():
    return ui.TagList(
        ui.div(
            ui.span("Show:", class_="storage-status-filters-label"),
            ui.input_checkbox("storage_show_active", "Active", True),
            ui.input_checkbox("storage_show_discarded", "Discarded", True),
            class_="storage-status-filters",
        ),
        ui.output_ui("storage_status_tool"),
    )


def storage_server(input):
    @render.ui
    def storage_status_tool():
        # Read outside the try: a missing input raises SilentException, which the
        # error handler below would otherwise report as a data-loading failure.
        show_active = _checkbox_value(input.storage_show_active)
        show_discarded = _checkbox_value(input.storage_show_discarded)

        try:
            return build_storage_status_ui(
                fetch_storage_containers_data(),
                show_active,
                show_discarded,
            )
        except Exception as e:
            return ui.p(
                f"⚠️ Error loading storage container data: {str(e)}",
                style="color: red;",
            )
