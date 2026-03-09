"""Domain logic for reagent naming, queue rules, and submission summaries."""

from __future__ import annotations

import html
import re
from typing import Any

import pandas as pd

from shinylims.config.reagents import (
    INDEX_REAGENT_TYPE,
    PREP_REAGENT_TYPES,
    REAGENT_TYPES,
    SELECTOR_TO_MISEQ_KIT_TYPE,
    SELECTOR_TO_REAGENT,
)

QUEUE_COLUMNS = [
    "Reagent Type",
    "Lot Number",
    "Received Date",
    "Expiry Date",
    "Internal Name",
    "Set Letter",
    "MiSeq Kit Type",
    "RGT Number",
]


def empty_pending_lots_df() -> pd.DataFrame:
    """Return an empty pending-lots DataFrame with the expected columns."""
    return pd.DataFrame(columns=QUEUE_COLUMNS)


def resolve_selected_reagent(selector_value: str | None) -> tuple[str | None, str | None]:
    """Resolve a selector or scanned barcode value to a reagent type and set letter."""
    value = (selector_value or "").strip()
    if not value:
        return (None, None)

    if value in SELECTOR_TO_REAGENT:
        return SELECTOR_TO_REAGENT[value]

    match = re.search(r"(\d{8})", value)
    if match:
        return SELECTOR_TO_REAGENT.get(match.group(1), (None, None))

    return (None, None)


def resolve_selected_miseq_kit_type(selector_value: str | None) -> str | None:
    """Resolve a selector or scanned barcode value to a MiSeq kit type."""
    value = (selector_value or "").strip()
    if not value:
        return None

    if value in SELECTOR_TO_MISEQ_KIT_TYPE:
        return SELECTOR_TO_MISEQ_KIT_TYPE[value]

    match = re.search(r"(\d{8})", value)
    if not match:
        return None
    return SELECTOR_TO_MISEQ_KIT_TYPE.get(match.group(1))


def extract_internal_sequence(name: str) -> int | None:
    """Extract the numeric sequence from an internal reagent name."""
    if not isinstance(name, str):
        return None
    match = re.search(r"#(\d+)", name)
    return int(match.group(1)) if match else None


def recalculate_sequence_offsets(pending_lots: pd.DataFrame) -> dict[str, int]:
    """Rebuild local sequence offsets from the current pending queue."""
    offsets = {
        "prep": 0,
        "index": 0,
    }
    if not pending_lots.empty and "Reagent Type" in pending_lots.columns:
        offsets["index"] = int((pending_lots["Reagent Type"] == INDEX_REAGENT_TYPE).sum())
    return offsets


def can_generate_internal_names(
    reagent_type: str,
    *,
    is_authorized: bool,
    is_lims_ready: bool,
    prep_ok: bool,
    index_ok: bool,
) -> bool:
    """Return whether numbering prerequisites are satisfied for this reagent."""
    if not is_authorized or not is_lims_ready:
        return False

    reagent_info = REAGENT_TYPES.get(reagent_type, {})
    if reagent_info.get("naming_group") in {"prep", "index"}:
        return prep_ok and index_ok
    return True


def get_next_prep_sequence_number(
    sequence_numbers: dict[str, int],
    pending_lots: pd.DataFrame,
    reagent_type: str,
) -> int:
    """Compute the next shared prep sequence number for a reagent type."""
    base_num = sequence_numbers.get("prep", 0)
    type_count = int((pending_lots["Reagent Type"] == reagent_type).sum())
    return base_num + type_count + 1


def get_next_sequence_number(
    sequence_numbers: dict[str, int],
    pending_sequence_offsets: dict[str, int],
    naming_group: str,
) -> int:
    """Compute the next sequence number for a non-prep naming group."""
    key = "index" if naming_group == "index" else naming_group
    base_num = sequence_numbers.get(key, 0)
    offset = pending_sequence_offsets.get(key, 0)
    return base_num + offset + 1


def generate_internal_name(
    reagent_type: str,
    *,
    sequence_numbers: dict[str, int],
    pending_sequence_offsets: dict[str, int],
    pending_lots: pd.DataFrame,
    set_letter: str | None = None,
    miseq_kit_type: str | None = None,
    rgt_number: str | None = None,
) -> str:
    """Generate the internal reagent name from the configured naming rules."""
    reagent_info = REAGENT_TYPES.get(reagent_type, {})
    naming_group = reagent_info.get("naming_group", "unknown")

    if naming_group == "miseq":
        rgt = (rgt_number or "").strip()
        kit_type = (miseq_kit_type or "").strip()
        if not rgt or not kit_type:
            return "Provide RGT Number and MiSeq Kit Type"
        return f"{rgt} {kit_type}"

    if naming_group == "phix":
        rgt = (rgt_number or "").strip()
        if not rgt:
            return "Provide RGT Number"
        return rgt

    if naming_group == "prep":
        next_num = get_next_prep_sequence_number(
            sequence_numbers,
            pending_lots,
            reagent_type,
        )
    else:
        next_num = get_next_sequence_number(
            sequence_numbers,
            pending_sequence_offsets,
            naming_group,
        )

    if naming_group == "index" and set_letter:
        return f"{set_letter}#{next_num} (192)"
    return f"#{next_num} (192)"


def increment_pending_offsets(
    pending_sequence_offsets: dict[str, int],
    reagent_type: str,
) -> dict[str, int]:
    """Return updated sequence offsets after adding one queued reagent."""
    reagent_info = REAGENT_TYPES.get(reagent_type, {})
    naming_group = reagent_info.get("naming_group")
    next_offsets = pending_sequence_offsets.copy()
    if naming_group == "index":
        next_offsets["index"] = next_offsets.get("index", 0) + 1
    return next_offsets


def get_queue_removal_error(pending_lots: pd.DataFrame, idx: int) -> str | None:
    """Return a user-facing error when removing a queued lot would break ordering."""
    if pending_lots.empty or idx < 0 or idx >= len(pending_lots):
        return None

    row = pending_lots.iloc[idx]
    reagent_type = row["Reagent Type"]
    reagent_info = REAGENT_TYPES.get(reagent_type, {})
    naming_group = reagent_info.get("naming_group")
    if naming_group not in {"prep", "index"}:
        return None

    group_types = [
        rtype
        for rtype, rinfo in REAGENT_TYPES.items()
        if rinfo.get("naming_group") == naming_group
    ]
    group_rows = pending_lots[pending_lots["Reagent Type"].isin(group_types)]
    group_numbers = [
        extract_internal_sequence(name)
        for name in group_rows["Internal Name"].tolist()
    ]
    group_numbers = [num for num in group_numbers if num is not None]
    if not group_numbers:
        return None

    latest_group_num = max(group_numbers)
    row_num = extract_internal_sequence(row["Internal Name"])
    if row_num == latest_group_num:
        return None

    label = "prep" if naming_group == "prep" else "index"
    return f"For {label} lots, remove the latest number first (#{latest_group_num})."


def get_prep_queue_mismatch_details(pending_lots: pd.DataFrame) -> str | None:
    """Return prep queue count details when the pending set is unbalanced."""
    prep_counts = {
        reagent_type: int((pending_lots["Reagent Type"] == reagent_type).sum())
        for reagent_type in PREP_REAGENT_TYPES
    }
    if len(set(prep_counts.values())) <= 1:
        return None
    return ", ".join(f"{reagent_type}: {count}" for reagent_type, count in prep_counts.items())


def submission_status_for_reagent(reagent_type: str) -> str:
    """Return the LIMS status to use when submitting this reagent type."""
    reagent_info = REAGENT_TYPES.get(reagent_type, {})
    naming_group = reagent_info.get("naming_group")
    return "PENDING" if naming_group in {"prep", "index"} else "ACTIVE"


def summarize_submission_entries(
    submission_entries: list[dict[str, Any]],
) -> tuple[int, int, pd.DataFrame, str]:
    """Build success counts, result rows, and error-log text from submission results."""
    successes = sum(1 for entry in submission_entries if entry["result"].success)
    failures = len(submission_entries) - successes

    result_rows = []
    failed_log_lines = []
    for entry in submission_entries:
        row = entry["row"]
        result = entry["result"]
        status_text = "Success" if result.success else "Failed"
        lims_id = result.lims_id or "-"
        message_text = result.message or "-"
        result_rows.append(
            {
                "Internal Name": row["Internal Name"],
                "Type": row["Reagent Type"],
                "Lot Number": row["Lot Number"],
                "Status": status_text,
                "LIMS ID": lims_id,
                "Message": message_text,
            }
        )
        if not result.success:
            failed_log_lines.append(
                f"- {row['Internal Name']} | {row['Reagent Type']} | lot={row['Lot Number']} | {message_text}"
            )

    logs_text = "\n".join(failed_log_lines) if failed_log_lines else "No errors."
    return successes, failures, pd.DataFrame(result_rows), logs_text


def render_pending_lots_html(pending_lots: pd.DataFrame) -> str:
    """Render the pending-lots table body as HTML for the Shiny page."""
    table_html = """
    <table class="table table-sm table-striped table-hover" style="width: 100%; table-layout: fixed;">
        <thead>
            <tr>
                <th style="width: 20%;">Internal Name</th>
                <th style="width: 24%;">Type</th>
                <th style="width: 16%;">Lot Number</th>
                <th style="width: 14%;">Expiry</th>
                <th style="width: 14%;">Status</th>
                <th style="width: 12%;">Action</th>
            </tr>
        </thead>
        <tbody>
    """
    for idx, row in pending_lots.iterrows():
        internal_name = html.escape(str(row["Internal Name"]))
        reagent_type = html.escape(str(row["Reagent Type"]))
        lot_number = html.escape(str(row["Lot Number"]))
        expiry_date = html.escape(str(row["Expiry Date"]))
        submission_status = html.escape(submission_status_for_reagent(str(row["Reagent Type"])))
        table_html += f"""
            <tr>
                <td><strong>{internal_name}</strong></td>
                <td>{reagent_type}</td>
                <td>{lot_number}</td>
                <td>{expiry_date}</td>
                <td>{submission_status}</td>
                <td>
                    <button
                        type="button"
                        class="btn btn-sm btn-outline-danger"
                        onclick="Shiny.setInputValue('remove_lot_idx', {idx}, {{priority: 'event'}})">
                        Remove
                    </button>
                </td>
            </tr>
        """
    table_html += "</tbody></table>"
    return table_html
