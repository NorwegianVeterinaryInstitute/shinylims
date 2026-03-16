"""Lab Tool for visualizing Illumina index plate usage from reagent lot notes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, UTC

from shiny import reactive, render, ui

from shinylims.config.index_plate_maps import PLATE_COLUMNS, PLATE_ROWS, normalize_well
from shinylims.config.reagents import PREP_REAGENT_TYPES, REAGENT_TYPES
from shinylims.features.loading import build_tool_loading_modal
from shinylims.integrations.lims_api import (
    ActiveIndexLot,
    ActivePrepSetsResult,
    IndexPlateMap,
    IndexPlateMapsResult,
    LIMSConfig,
    PrepSetSummary,
    SequencingStockLot,
    SequencingStockResult,
    get_illumina_planning_data,
    update_reagent_lot_status,
)
from shinylims.security import is_allowed_reagents_user, reagents_access_denied_message

PREP_REAGENT_SHORT_LABELS = {
    PREP_REAGENT_TYPES[0]: "IPB",
    PREP_REAGENT_TYPES[1]: "PCR",
    PREP_REAGENT_TYPES[2]: "TAG",
}

EXPIRY_WARNING_WINDOW_DAYS = 30


@dataclass(frozen=True)
class ExpiryAssessment:
    """Normalized expiry interpretation for planner warnings and modal views."""
    display_date: str
    days_left: int | None
    state: str


def summarize_index_plate_maps(plate_maps: list[IndexPlateMap]) -> dict[str, int]:
    """Return overall status counts across all rendered plate maps."""
    return {
        "lot_count": len(plate_maps),
        "unused_wells": sum(plate_map.unused_wells for plate_map in plate_maps),
        "single_use_wells": sum(plate_map.single_use_wells for plate_map in plate_maps),
        "double_use_wells": sum(plate_map.double_use_wells for plate_map in plate_maps),
        "conflict_wells": sum(plate_map.conflict_wells for plate_map in plate_maps),
    }


def index_plate_conflict_count(plate_map: IndexPlateMap) -> int:
    """Return a user-facing unified conflict count for one index lot."""
    return plate_map.conflict_wells + len(plate_map.warnings)


def can_move_plate_map_to_pending(plate_map: IndexPlateMap) -> bool:
    """Return whether an active index lot can safely be moved back to pending."""
    return (
        not plate_map.warnings
        and plate_map.unused_wells == len(plate_map.cells)
        and plate_map.single_use_wells == 0
        and plate_map.double_use_wells == 0
        and plate_map.conflict_wells == 0
    )


def move_to_pending_tooltip(plate_map: IndexPlateMap) -> str:
    """Return an explanation when move-to-pending is unavailable."""
    if plate_map.warnings:
        return "Cannot move to pending because this lot has incomplete note history."
    if (
        plate_map.single_use_wells > 0
        or plate_map.double_use_wells > 0
        or plate_map.conflict_wells > 0
        or plate_map.unused_wells != len(plate_map.cells)
    ):
        return "Cannot move to pending because this lot has recorded usage."
    return "Move this unused lot back to pending."


def summarize_prep_sets(prep_sets: list[PrepSetSummary]) -> dict[str, int]:
    """Return compact prep-set counts for the toolbar."""
    return {
        "prep_set_count": len(prep_sets),
        "warning_count": sum(1 for prep_set in prep_sets if prep_set.warnings),
        "pending_count": sum(1 for prep_set in prep_sets if _prep_set_inventory_state(prep_set)[0] != "Active"),
    }


def summarize_sequencing_stock(result: SequencingStockResult | None) -> dict[str, int] | None:
    """Return compact sequencing counts for the toolbar details."""
    if result is None or not result.success:
        return None

    miseq_rows = [row for row in result.summary_rows if row.item.startswith("MiSeq ")]
    phix_row = next((row for row in result.summary_rows if row.item == "PhiX Control v3"), None)
    return {
        "miseq_kits": sum(row.kit_count for row in miseq_rows),
        "unmatched_boxes": sum(row.unmatched_count or 0 for row in miseq_rows),
        "phix_lots": phix_row.kit_count if phix_row is not None else 0,
    }


def _assess_expiry_date(
    expiry_date: str | None,
    *,
    today: date | None = None,
) -> ExpiryAssessment:
    """Classify one planner expiry date into display and warning states."""
    raw_value = (expiry_date or "").strip()
    if not raw_value:
        return ExpiryAssessment(display_date="Not set", days_left=None, state="missing")

    try:
        parsed_date = date.fromisoformat(raw_value)
    except ValueError:
        return ExpiryAssessment(display_date=raw_value, days_left=None, state="invalid")

    reference_date = today or date.today()
    days_left = (parsed_date - reference_date).days
    if days_left < 0:
        state = "expired"
    elif days_left == 0:
        state = "expires_today"
    elif days_left <= EXPIRY_WARNING_WINDOW_DAYS:
        state = "expiring_soon"
    else:
        state = "ok"
    return ExpiryAssessment(display_date=raw_value, days_left=days_left, state=state)


def _expiry_requires_attention(assessment: ExpiryAssessment) -> bool:
    """Return whether an expiry assessment should show warning attention."""
    return assessment.state in {"expired", "expires_today", "expiring_soon"}


def _format_days_left(assessment: ExpiryAssessment) -> str:
    """Render a compact days-left label for expiry modal tables."""
    return "—" if assessment.days_left is None else str(assessment.days_left)


def _sequencing_lot_item_label(lot: SequencingStockLot) -> str:
    """Return the sequencing item label used in planner warnings and modal rows."""
    naming_group = REAGENT_TYPES.get(lot.reagent_type, {}).get("naming_group")
    if naming_group == "miseq":
        return f"MiSeq {lot.miseq_kit_type}" if (lot.miseq_kit_type or "").strip() else "MiSeq Unknown"
    return lot.reagent_type


def _sequencing_lot_box_label(lot: SequencingStockLot) -> str:
    """Return a compact box-side label for one sequencing lot."""
    reagent_type = (lot.reagent_type or "").strip()
    if "(Box 1 of 2)" in reagent_type:
        return "Box 1 of 2"
    if "(Box 2 of 2)" in reagent_type:
        return "Box 2 of 2"
    return "—"


def _prep_set_earliest_expiry_assessment(prep_set: PrepSetSummary, *, today: date | None = None) -> ExpiryAssessment:
    """Return the earliest valid expiry across all lots in a prep set."""
    earliest_raw = min(
        (
            lot.expiry_date.strip()
            for lot in prep_set.lots_by_type.values()
            if _assess_expiry_date(lot.expiry_date, today=today).days_left is not None
        ),
        default="",
    )
    return _assess_expiry_date(earliest_raw, today=today)


def _planner_expiry_warning_items(
    prep_result: ActivePrepSetsResult | None,
    sequencing_result: SequencingStockResult | None,
    *,
    today: date | None = None,
) -> list[str]:
    """Return planner expiry warnings for prep and sequencing stock."""
    warning_items: list[str] = []

    if prep_result is not None and prep_result.success:
        for prep_set in prep_result.prep_sets:
            affected_boxes = []
            for reagent_type in PREP_REAGENT_TYPES:
                lot = prep_set.lots_by_type.get(reagent_type)
                if lot is None:
                    continue
                assessment = _assess_expiry_date(lot.expiry_date, today=today)
                if _expiry_requires_attention(assessment):
                    affected_boxes.append(
                        f"{PREP_REAGENT_SHORT_LABELS[reagent_type]} {assessment.display_date}"
                    )
            if affected_boxes:
                warning_items.append(
                    f"Prep set #{prep_set.sequence_number} expiry attention: {', '.join(affected_boxes)}"
                )

    if sequencing_result is not None and sequencing_result.success:
        for lot in sequencing_result.lots:
            assessment = _assess_expiry_date(lot.expiry_date, today=today)
            if not _expiry_requires_attention(assessment):
                continue
            warning_items.append(
                "Sequencing expiry attention: "
                f"{_sequencing_lot_item_label(lot)} | {lot.name or 'Unnamed lot'} | {assessment.display_date}"
            )

    return warning_items


def _planner_warning_items(
    index_warnings: list[str],
    prep_result: ActivePrepSetsResult | None,
    sequencing_result: SequencingStockResult | None,
    *,
    today: date | None = None,
) -> list[str]:
    """Return the full planner warning list shown in the top status card."""
    warnings = list(index_warnings)
    if prep_result is not None:
        warnings.extend(prep_result.warnings)
    warnings.extend(_sequencing_warning_items(sequencing_result))
    warnings.extend(_planner_expiry_warning_items(prep_result, sequencing_result, today=today))
    return warnings


def _expiry_cell_class(assessment: ExpiryAssessment) -> str:
    """Return modal table cell classes for one expiry assessment."""
    base_class = "index-planner-expiry-cell"
    if assessment.state == "expired":
        return f"{base_class} index-planner-expiry-cell--expired"
    if assessment.state in {"expires_today", "expiring_soon"}:
        return f"{base_class} index-planner-expiry-cell--soon"
    return base_class


def _render_prep_expiry_section(
    prep_result: ActivePrepSetsResult | None,
    *,
    today: date | None = None,
) -> ui.TagChild:
    """Render one modal section with prep-set expiry details."""
    if prep_result is None:
        return ui.div("Prep expiry dates are not loaded.", class_="alert alert-secondary mb-0")
    if not prep_result.success:
        return ui.div(prep_result.message, class_="alert alert-danger mb-0")
    if not prep_result.prep_sets:
        return ui.div("No active or pending prep sets were found.", class_="alert alert-secondary mb-0")

    rows: list[ui.TagChild] = []
    for prep_set in prep_result.prep_sets:
        inventory_label, inventory_class = _prep_set_inventory_state(prep_set)
        earliest = _prep_set_earliest_expiry_assessment(prep_set, today=today)
        expiry_cells: list[ui.TagChild] = []
        for reagent_type in PREP_REAGENT_TYPES:
            lot = prep_set.lots_by_type.get(reagent_type)
            assessment = _assess_expiry_date(lot.expiry_date if lot is not None else "", today=today)
            expiry_cells.append(
                ui.tags.td(
                    assessment.display_date,
                    class_=f"index-planner-cell {_expiry_cell_class(assessment)}",
                )
            )
        rows.append(
            ui.tags.tr(
                ui.tags.td(f"#{prep_set.sequence_number}", class_="index-planner-cell index-planner-cell--set"),
                ui.tags.td(
                    ui.span(inventory_label, class_=f"badge index-planner-status-badge {inventory_class}"),
                    class_="index-planner-cell",
                ),
                ui.tags.td(str(prep_set.usable_reactions_left), class_="index-planner-cell index-planner-cell--usable"),
                *expiry_cells,
                ui.tags.td(
                    earliest.display_date,
                    class_=f"index-planner-cell {_expiry_cell_class(earliest)}",
                ),
            )
        )

    return ui.div(
        ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("Set"),
                    ui.tags.th("Status"),
                    ui.tags.th("Usable"),
                    *(ui.tags.th(f"{PREP_REAGENT_SHORT_LABELS[reagent_type]} Expiry", title=reagent_type) for reagent_type in PREP_REAGENT_TYPES),
                    ui.tags.th("Earliest"),
                )
            ),
            ui.tags.tbody(*rows),
            class_="index-planner-table index-planner-expiry-table",
        ),
        class_="index-planner-expiry-table-wrap",
    )


def _render_sequencing_expiry_section(
    sequencing_result: SequencingStockResult | None,
    *,
    today: date | None = None,
) -> ui.TagChild:
    """Render one modal section with sequencing-lot expiry details."""
    if sequencing_result is None:
        return ui.div("Sequencing expiry dates are not loaded.", class_="alert alert-secondary mb-0")
    if not sequencing_result.success:
        return ui.div(sequencing_result.message, class_="alert alert-danger mb-0")
    if not sequencing_result.lots:
        return ui.div("No active or pending sequencing reagent lots were found.", class_="alert alert-secondary mb-0")

    rows: list[ui.TagChild] = []
    for lot in sequencing_result.lots:
        assessment = _assess_expiry_date(lot.expiry_date, today=today)
        rows.append(
            ui.tags.tr(
                ui.tags.td(_sequencing_lot_item_label(lot), class_="index-planner-cell"),
                ui.tags.td(_sequencing_lot_box_label(lot), class_="index-planner-cell"),
                ui.tags.td(lot.name or "Unnamed lot", class_="index-planner-cell"),
                ui.tags.td((lot.status or "").title() or "Unknown", class_="index-planner-cell"),
                ui.tags.td(assessment.display_date, class_=f"index-planner-cell {_expiry_cell_class(assessment)}"),
                ui.tags.td(_format_days_left(assessment), class_=f"index-planner-cell index-planner-cell--number {_expiry_cell_class(assessment)}"),
            )
        )

    return ui.div(
        ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("Item"),
                        ui.tags.th("Box"),
                        ui.tags.th("Lot Name"),
                        ui.tags.th("Status"),
                        ui.tags.th("Expiry"),
                        ui.tags.th("Days Left"),
                    )
            ),
            ui.tags.tbody(*rows),
            class_="index-planner-table index-planner-expiry-table",
        ),
        class_="index-planner-expiry-table-wrap",
    )


def _build_planner_expiry_modal(
    prep_result: ActivePrepSetsResult | None,
    sequencing_result: SequencingStockResult | None,
    *,
    today: date | None = None,
) -> ui.Tag:
    """Build the planner expiry review modal."""
    return ui.modal(
        ui.div(
            ui.p(
                f"Expired and next {EXPIRY_WARNING_WINDOW_DAYS} days are highlighted.",
                class_="text-muted small mb-3",
            ),
            ui.div(
                ui.h6("Prep", class_="mb-2"),
                _render_prep_expiry_section(prep_result, today=today),
                class_="index-planner-expiry-section",
            ),
            ui.div(
                ui.h6("Sequencing", class_="mb-2"),
                _render_sequencing_expiry_section(sequencing_result, today=today),
                class_="index-planner-expiry-section",
            ),
        ),
        title="Prep and Sequencing Expiry Dates",
        footer=ui.modal_button("Close", class_="btn-secondary"),
        size="l",
        easy_close=True,
        class_="index-planner-expiry-modal",
    )


def build_index_plate_maps_view_model(
    result: IndexPlateMapsResult | None,
    loaded_at: datetime | None,
    *,
    is_loading: bool,
) -> dict[str, object]:
    """Build a simple view model so UI states are easy to test."""
    if is_loading:
        return {
            "mode": "loading",
            "message": "Loading active index lots from Clarity...",
            "warnings": [],
            "summary": None,
            "cards": [],
            "pending_lot_count": 0,
            "loaded_at": None,
        }

    if result is None:
        return {
            "mode": "idle",
            "message": "Open the tool to load active index lots.",
            "warnings": [],
            "summary": None,
            "cards": [],
            "pending_lot_count": 0,
            "loaded_at": None,
        }

    loaded_label = loaded_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC") if loaded_at else None
    summary = summarize_index_plate_maps(result.plate_maps)
    cards = [
        {
            "title": plate_map.lot.name,
            "lot_number": plate_map.lot.lot_number,
            "expiry_date": plate_map.lot.expiry_date,
            "set_letter": plate_map.lot.set_letter,
            "unused_wells": plate_map.unused_wells,
            "single_use_wells": plate_map.single_use_wells,
            "double_use_wells": plate_map.double_use_wells,
            "conflict_wells": plate_map.conflict_wells,
            "cell_count": len(plate_map.cells),
        }
        for plate_map in result.plate_maps
    ]

    if not result.success:
        mode = "error"
    elif not result.plate_maps:
        mode = "empty"
    else:
        mode = "ready"

    return {
        "mode": mode,
        "message": result.message,
        "warnings": result.warnings,
        "summary": summary,
        "cards": cards,
        "pending_lot_count": len(result.pending_lots),
        "loaded_at": loaded_label,
    }


def build_index_lot_overview_rows(result: IndexPlateMapsResult) -> list[dict[str, str]]:
    """Return active and pending index lots for the manager overview panel."""
    rows = [
        {
            "lot_uri": plate_map.lot.lot_uri,
            "name": plate_map.lot.name,
            "set_letter": plate_map.lot.set_letter,
            "status": "Active",
            "expiry_date": plate_map.lot.expiry_date or "Not set",
        }
        for plate_map in result.plate_maps
    ]
    rows.extend(
        {
            "lot_uri": lot.lot_uri,
            "name": lot.name,
            "set_letter": lot.set_letter,
            "status": "Pending",
            "expiry_date": lot.expiry_date or "Not set",
        }
        for lot in result.pending_lots
    )

    def _sort_key(row: dict[str, str]) -> tuple[bool, str, str]:
        expiry_date = row["expiry_date"]
        return (row["status"] != "Active", expiry_date == "Not set", expiry_date, row["name"])

    return sorted(rows, key=_sort_key)


def _legend_tag() -> ui.Tag:
    return ui.div(
        ui.span(ui.span(class_="index-plate-legend-chip index-plate-cell--unused"), "Available", class_="index-plate-legend-item"),
        ui.span(ui.span(class_="index-plate-legend-chip index-plate-cell--single"), "Used once", class_="index-plate-legend-item"),
        ui.span(ui.span(class_="index-plate-legend-chip index-plate-cell--double"), "Used twice", class_="index-plate-legend-item"),
        ui.span(ui.span(class_="index-plate-legend-chip index-plate-cell--conflict"), ">2 uses", class_="index-plate-legend-item"),
        class_="index-plate-legend",
    )


def _render_plate_grid(plate_map: IndexPlateMap) -> ui.Tag:
    cell_lookup = {cell.well: cell for cell in plate_map.cells}
    grid_children: list[ui.TagChild] = [
        ui.div("", class_="index-plate-corner"),
    ]

    for column in PLATE_COLUMNS:
        grid_children.append(ui.div(str(column), class_="index-plate-col-header"))

    for row in PLATE_ROWS:
        grid_children.append(ui.div(row, class_="index-plate-row-header"))
        for column in PLATE_COLUMNS:
            well = normalize_well(row, column)
            cell = cell_lookup[well]
            label = str(cell.raw_count) if cell.raw_count else "0"
            grid_children.append(
                ui.div(
                    ui.div(
                        label,
                        class_=f"index-plate-cell index-plate-cell--{cell.state}",
                        title=f"{well}: {cell.raw_count} uses",
                    ),
                    class_="index-plate-cell-frame",
                )
            )

    return ui.div(*grid_children, class_="index-plate-grid-shell")


def format_index_plate_selector_label(plate_map: IndexPlateMap) -> str:
    """Format the lot selector label with warning visibility."""
    expiry_text = plate_map.lot.expiry_date or "No expiry"
    label = (
        f"{plate_map.lot.name} | "
        f"Set {plate_map.lot.set_letter} | "
        f"Exp {expiry_text}"
    )
    issue_count = index_plate_conflict_count(plate_map)
    if issue_count:
        return f"{label} | Conflicts {issue_count}"
    return label


def _format_prep_warning(warning: str) -> str:
    """Return compact prep-warning copy for the planner table."""
    if warning.startswith("Missing boxes:"):
        return "Missing boxes. Attention needed."
    return warning


def _sequencing_warning_items(sequencing_result: SequencingStockResult | None) -> list[str]:
    """Return user-facing sequencing warnings for planner status surfaces."""
    if sequencing_result is None or not sequencing_result.success:
        return []

    unknown_lots = sorted(
        [
            lot
            for lot in sequencing_result.lots
            if lot.reagent_type != "PhiX Control v3" and not (lot.miseq_kit_type or "").strip()
        ],
        key=lambda lot: (lot.reagent_type, lot.name.casefold(), lot.lot_uri),
    )
    if unknown_lots:
        warnings = [
            f"Unknown sequencing stock reagent: {lot.name or 'Unnamed lot'} ({lot.reagent_type})"
            for lot in unknown_lots
        ]
    else:
        warnings = [
            f"Unknown sequencing stock reagent: {row.item}"
            for row in sequencing_result.summary_rows
            if row.item.casefold() == "miseq unknown"
        ]

    warnings.extend(
        f"Unmatched sequencing stock boxes: {row.item} ({row.unmatched_count})"
        for row in sequencing_result.summary_rows
        if (row.unmatched_count or 0) > 0 and row.item.casefold() != "miseq unknown"
    )
    return warnings


def _has_sequencing_stock_attention(sequencing_result: SequencingStockResult | None) -> bool:
    """Return whether the sequencing summary contains warning-worthy stock issues."""
    return bool(_sequencing_warning_items(sequencing_result))


def _prep_set_inventory_state(prep_set: PrepSetSummary) -> tuple[str, str]:
    """Return lot-state label and badge class for one prep set."""
    statuses = {
        (lot.status or "").upper()
        for lot in prep_set.lots_by_type.values()
        if (lot.status or "").strip()
    }
    if statuses == {"ACTIVE"}:
        return ("Active", "index-planner-status-badge--active")
    if statuses == {"PENDING"}:
        return ("Pending", "index-planner-status-badge--pending")
    return ("Mixed", "index-planner-status-badge--mixed")


def _prep_set_is_unused(prep_set: PrepSetSummary) -> bool:
    """Return whether a prep set is still completely unused."""
    return prep_set.usable_reactions_left == 192


def _prep_set_action(prep_set: PrepSetSummary) -> tuple[str | None, str | None, str | None]:
    """Return action button id, label, and style suffix for a prep set."""
    inventory_label, _ = _prep_set_inventory_state(prep_set)
    if inventory_label == "Pending":
        return (f"prep_activate_{prep_set.sequence_number}", "Activate", "outline-success")
    if inventory_label == "Active":
        if _prep_set_is_unused(prep_set):
            return (f"prep_move_to_pending_{prep_set.sequence_number}", "Move to Pending", "outline-secondary")
        return (f"prep_archive_{prep_set.sequence_number}", "Archive", "outline-danger")
    return (None, None, None)


def _merge_action_clicks(previous_clicks: dict[str, int], current_clicks: dict[str, int]) -> dict[str, int]:
    """Preserve click counts for hidden action buttons across reactive rerenders."""
    merged_clicks = dict(previous_clicks)
    merged_clicks.update(current_clicks)
    return merged_clicks


def _render_prep_sets_section(prep_result: ActivePrepSetsResult | None) -> ui.Tag:
    if prep_result is None:
        section_body: ui.TagChild = ui.p(
            "Open the tool to load active prep sets.",
            class_="text-muted mb-0",
        )
    elif not prep_result.success:
        section_body = ui.div(prep_result.message, class_="alert alert-danger mb-0")
    elif not prep_result.prep_sets:
        section_body = ui.div("No active prep sets were found.", class_="alert alert-secondary mb-0")
    else:
        table_rows: list[ui.TagChild] = []
        for prep_set in prep_result.prep_sets:
            inventory_label, inventory_class = _prep_set_inventory_state(prep_set)
            action_id, action_label, action_style = _prep_set_action(prep_set)
            warning_items = None
            if prep_set.warnings:
                warning_items = ui.div(
                    *(ui.div(_format_prep_warning(warning), class_="index-planner-warning-line") for warning in prep_set.warnings),
                    class_="index-planner-warning-stack",
                )

            value_classes_by_type: dict[str, str] = {}
            if prep_set.warnings:
                expected_value = prep_set.usable_reactions_left
                for reagent_type in PREP_REAGENT_TYPES:
                    value = prep_set.reactions_by_type[reagent_type]
                    if value is None or value != expected_value:
                        value_classes_by_type[reagent_type] = "index-planner-cell index-planner-cell--issue"
                    else:
                        value_classes_by_type[reagent_type] = "index-planner-cell"
            else:
                value_classes_by_type = {reagent_type: "index-planner-cell" for reagent_type in PREP_REAGENT_TYPES}

            table_rows.append(
                ui.tags.tr(
                    ui.tags.td(f"#{prep_set.sequence_number}", class_="index-planner-cell index-planner-cell--set"),
                    ui.tags.td(str(prep_set.usable_reactions_left), class_="index-planner-cell index-planner-cell--usable"),
                    *[
                        ui.tags.td(
                            str(prep_set.reactions_by_type[reagent_type])
                            if prep_set.reactions_by_type[reagent_type] is not None
                            else "—",
                            class_=value_classes_by_type[reagent_type],
                            title=reagent_type,
                        )
                        for reagent_type in PREP_REAGENT_TYPES
                    ],
                    ui.tags.td(
                        ui.div(
                            ui.div(
                                ui.span(
                                    inventory_label,
                                    class_=f"badge index-planner-status-badge {inventory_class}",
                                ),
                                class_="index-planner-status-badge-row",
                            ),
                            warning_items,
                            class_="index-planner-status-cell",
                        ),
                        class_="index-planner-cell index-planner-cell--status",
                    ),
                    ui.tags.td(
                        ui.input_action_button(
                            action_id,
                            action_label,
                            class_=f"btn btn-{action_style} btn-sm",
                        ) if action_id and action_label and action_style else ui.span("Resolve mix", class_="text-muted small"),
                        class_="index-planner-cell index-planner-cell--actions",
                    ),
                    class_="index-planner-row index-planner-row--warn" if prep_set.warnings else "index-planner-row",
                )
            )

        section_body = ui.div(
            ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("Set"),
                        ui.tags.th("Usable"),
                        *(ui.tags.th(PREP_REAGENT_SHORT_LABELS[reagent_type], title=reagent_type) for reagent_type in PREP_REAGENT_TYPES),
                        ui.tags.th("Status"),
                        ui.tags.th("Actions"),
                    )
                ),
                ui.tags.tbody(*table_rows),
                class_="index-planner-table",
            ),
            class_="index-planner-table-wrap index-planner-table-wrap--prep",
        )

    return ui.div(
        ui.div(
            ui.div(
                ui.div(
                    ui.h6("Prep Sets", class_="mb-0 index-planner-section-title"),
                ),
                class_="index-planner-section-header",
            )
        ),
        section_body,
        class_="index-planner-side-section index-planner-side-section--prep",
    )


def _render_sequencing_stock_section(sequencing_result: SequencingStockResult | None) -> ui.Tag:
    has_attention = _has_sequencing_stock_attention(sequencing_result)

    if sequencing_result is None:
        section_body: ui.TagChild = ui.p(
            "Open the tool to load sequencing stock.",
            class_="text-muted mb-0",
        )
    elif not sequencing_result.success:
        section_body = ui.div(sequencing_result.message, class_="alert alert-danger mb-0")
    elif not sequencing_result.summary_rows:
        section_body = ui.div(
            "No active or pending sequencing reagent lots were found.",
            class_="alert alert-secondary mb-0",
        )
    else:
        table_rows = []
        for row in sequencing_result.summary_rows:
            is_unknown = row.item.casefold() == "miseq unknown"
            has_unmatched = (row.unmatched_count or 0) > 0
            table_rows.append(
                ui.tags.tr(
                    ui.tags.td(
                        row.item,
                        class_="index-planner-cell index-planner-cell--issue"
                        if is_unknown
                        else "index-planner-cell",
                    ),
                    ui.tags.td(str(row.kit_count), class_="index-planner-cell index-planner-cell--number"),
                    ui.tags.td(
                        "—" if row.unmatched_count is None else str(row.unmatched_count),
                        class_="index-planner-cell index-planner-cell--number index-planner-cell--issue"
                        if has_unmatched
                        else "index-planner-cell index-planner-cell--number",
                    ),
                    class_="index-planner-row--warn" if is_unknown or has_unmatched else None,
                )
            )
        section_body = ui.div(
            ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("Item"),
                        ui.tags.th("Kits"),
                        ui.tags.th("Unmatched"),
                    )
                ),
                ui.tags.tbody(*table_rows),
                class_="index-planner-table index-planner-table--sequencing",
            ),
            class_="index-planner-table-wrap index-planner-table-wrap--sequencing",
        )

    return ui.div(
        ui.div(
            ui.div(
                ui.h6("Sequencing Stock", class_="mb-0 index-planner-section-title"),
            ),
            class_="index-planner-section-header",
        ),
        section_body,
        class_="index-planner-side-section index-planner-side-section--sequencing index-planner-side-section--warn"
        if has_attention
        else "index-planner-side-section index-planner-side-section--sequencing",
    )


def _render_prep_sets_card(
    prep_result: ActivePrepSetsResult | None,
    sequencing_result: SequencingStockResult | None,
    *,
    today: date | None = None,
) -> ui.Tag:
    summary = summarize_prep_sets(prep_result.prep_sets) if prep_result and prep_result.success else None
    sequencing_has_attention = _has_sequencing_stock_attention(sequencing_result)
    expiry_warning_items = _planner_expiry_warning_items(prep_result, sequencing_result, today=today)

    return ui.card(
        ui.card_header(
            ui.div(
                ui.div(
                    ui.h5("Prep and Sequencing", class_="mb-0"),
                    ui.p(
                        "Manage prep sets above and review sequencing stock below.",
                        class_="mb-0 index-planner-card-meta",
                    ),
                    ui.p("Highlighted prep sets need attention.", class_="mb-0 index-planner-card-alert") if summary and summary["warning_count"] else None,
                    ui.p("Sequencing stock needs attention.", class_="mb-0 index-planner-card-alert") if sequencing_has_attention else None,
                    ui.p("Expiry dates need attention.", class_="mb-0 index-planner-card-alert") if expiry_warning_items else None,
                ),
                ui.div(
                    ui.input_action_button(
                        "view_planner_expiry_dates",
                        "View expiry dates",
                        class_="btn btn-sm index-planner-expiry-trigger",
                    ),
                    class_="index-card-header-actions",
                ),
                class_="index-card-header-layout d-flex justify-content-between align-items-start gap-3",
            )
        ),
        ui.card_body(
            ui.div(
                _render_prep_sets_section(prep_result),
                _render_sequencing_stock_section(sequencing_result),
                class_="index-planner-side-sections",
            )
        ),
        class_="index-planner-side-card",
    )


def _render_plate_map_card(plate_map: IndexPlateMap, selector: ui.TagChild | None = None) -> ui.Tag:
    expiry_text = plate_map.lot.expiry_date or "Not set"
    lot_number_text = plate_map.lot.lot_number or "Not set"
    has_parse_warnings = bool(plate_map.warnings)
    issue_count = index_plate_conflict_count(plate_map)
    summary_text = (
        (
            f"Parsed wells only | Available: {plate_map.unused_wells} | "
            f"1 use: {plate_map.single_use_wells} | "
            f"2 uses: {plate_map.double_use_wells} | "
            f">2 uses: {plate_map.conflict_wells}"
        )
        if has_parse_warnings
        else (
            f"Available: {plate_map.unused_wells} | "
            f"1 use: {plate_map.single_use_wells} | "
            f"2 uses: {plate_map.double_use_wells} | "
            f">2 uses: {plate_map.conflict_wells}"
        )
    )
    archive_button = ui.input_action_button(
        "archive_active_index_lot",
        "Archive Lot",
        class_="btn btn-outline-danger btn-sm",
    )
    can_move_to_pending = can_move_plate_map_to_pending(plate_map)
    move_to_pending_button = ui.tags.span(
        ui.input_action_button(
            "move_active_index_lot_to_pending",
            "Move to Pending",
            class_="btn btn-outline-secondary btn-sm",
            disabled=not can_move_to_pending,
        ),
        title=move_to_pending_tooltip(plate_map),
        class_="index-plate-action-tooltip-wrap",
    )
    footer_actions = ui.div(
        move_to_pending_button,
        archive_button,
        class_="index-plate-footer-actions",
    )

    if has_parse_warnings:
        body_children: list[ui.TagChild] = []
        body_children.append(
            ui.div(
                ui.div(
                    "This plate has incomplete note history. The rendered grid below is only a partial preview and should not be used as a reliable source of truth.",
                    class_="index-plate-invalid-banner-title",
                ),
                ui.p(
                    "Older note lines record only reaction counts for some columns, so the exact wells cannot be reconstructed.",
                    class_="mb-2 index-plate-invalid-banner-text",
                ),
                ui.tags.details(
                    ui.tags.summary(
                        f"Show plate-specific warnings ({len(plate_map.warnings)})",
                        class_="index-plate-warning-summary",
                    ),
                    ui.tags.ul(
                        *(ui.tags.li(warning) for warning in plate_map.warnings),
                        class_="mb-0 mt-2",
                    ),
                    class_="index-plate-invalid-details",
                ),
                class_="index-plate-invalid-banner mb-3",
            )
        )
        body_children.append(
            ui.tags.details(
                ui.tags.summary(
                    "Show incomplete parsed preview",
                    class_="index-plate-preview-summary",
                ),
                ui.div(_render_plate_grid(plate_map)),
                class_="index-plate-preview-details",
            )
        )
        body_children.append(
            ui.div(
                footer_actions,
                class_="index-plate-summary-row index-plate-summary-row--footer",
            )
        )
    else:
        body_children = [
            _render_plate_grid(plate_map),
            ui.div(
                footer_actions,
                class_="index-plate-summary-row index-plate-summary-row--footer",
            ),
        ]

    return ui.card(
        ui.card_header(
            ui.div(
                ui.div(
                    ui.h5(plate_map.lot.name, class_="mb-1 index-plate-card-title"),
                    ui.div(
                        ui.span(
                            f"Set {plate_map.lot.set_letter} | Lot Number: {lot_number_text} | Expiry: {expiry_text}",
                            class_="index-plate-card-meta",
                        ),
                        ui.span(
                            f"Conflicts: {issue_count}",
                            class_=(
                                "badge index-plate-status-badge index-plate-status-badge--conflict"
                                if issue_count
                                else "badge index-plate-status-badge index-plate-status-badge--neutral"
                            ),
                        ),
                        class_="d-flex align-items-center gap-2 flex-wrap",
                    ),
                    ui.p(summary_text, class_="mb-0 mt-1 index-plate-card-summary"),
                ),
                ui.div(
                    ui.div(selector, class_="index-plate-card-selector") if selector is not None else None,
                    class_="index-card-header-actions d-flex align-items-start justify-content-end",
                ),
                class_="index-card-header-layout d-flex justify-content-between align-items-start gap-3",
            )
        ),
        ui.card_body(*body_children),
        class_=(
            "mb-4 index-plate-card index-plate-card--invalid"
            if has_parse_warnings
            else "mb-4 index-plate-card"
        ),
    )


def _render_empty_plate_map_card(
    selector: ui.TagChild | None = None,
    *,
    active_count: int = 0,
    pending_count: int = 0,
) -> ui.Tag:
    return ui.card(
        ui.card_header(
            ui.div(
                ui.div(
                    ui.h5("Index Plate Map", class_="mb-1 index-plate-card-title"),
                    ui.p(
                        "Use the drop-down menu above to view active lots, activate pending lots, and load a plate map.",
                        class_="mb-0 index-plate-card-meta",
                    ),
                ),
                ui.div(
                    ui.div(selector, class_="index-plate-card-selector") if selector is not None else None,
                    class_="index-card-header-actions d-flex align-items-start justify-content-end",
                ),
                class_="index-card-header-layout d-flex justify-content-between align-items-start gap-3",
            )
        ),
        ui.card_body(
            ui.div(
                ui.div(
                    "Select an active lot to review plate usage.",
                    class_="index-plate-empty-title",
                ),
                ui.div(
                    ui.span(f"Active kits: {active_count}", class_="index-plate-empty-pill"),
                    ui.span(f"Pending kits: {pending_count}", class_="index-plate-empty-pill index-plate-empty-pill--pending"),
                    class_="d-flex align-items-center justify-content-center gap-2 flex-wrap",
                ),
                ui.p(
                    "Choose a lot from the drop-down menu above to load the plate map and review availability.",
                    class_="mb-0 index-plate-empty-text",
                ),
                class_="index-plate-empty-state",
            )
        ),
        class_="mb-4 index-plate-card index-plate-card--empty",
    )


def _render_index_lot_overview_header(result: IndexPlateMapsResult) -> ui.Tag:
    overview_rows = build_index_lot_overview_rows(result)
    active_rows = [row for row in overview_rows if row["status"] == "Active"]
    pending_rows = [row for row in overview_rows if row["status"] == "Pending"]

    def _overview_section_rows(rows: list[dict[str, str]], *, section_label: str, action_label: str, action_prefix: str, action_style: str) -> list[ui.Tag]:
        if not rows:
            return []
        return [
            ui.tags.tr(
                ui.tags.td(section_label, colspan="5", class_="index-plate-overview-divider-cell"),
                class_="index-plate-overview-divider-row",
            ),
            ui.tags.tr(
                ui.tags.th("Lot"),
                ui.tags.th("Set"),
                ui.tags.th("Status"),
                ui.tags.th("Expiry"),
                ui.tags.th("Action"),
                class_="index-plate-overview-section-header",
            ),
            *[
                ui.tags.tr(
                    ui.tags.td(row["name"]),
                    ui.tags.td(f"Set {row['set_letter']}"),
                    ui.tags.td(
                        ui.span(
                            row["status"],
                            class_=(
                                "badge index-planner-status-badge index-planner-status-badge--active"
                                if row["status"] == "Active"
                                else "badge index-planner-status-badge index-planner-status-badge--pending"
                            ),
                        )
                    ),
                    ui.tags.td(row["expiry_date"]),
                    ui.tags.td(
                        ui.input_action_button(
                            f"{action_prefix}_{index}",
                            action_label,
                            class_=f"btn btn-{action_style} btn-sm",
                        ),
                        class_="index-plate-overview-action-cell",
                    ),
                )
                for index, row in enumerate(rows)
            ],
        ]

    if overview_rows:
        overview_body: ui.TagChild = ui.div(
            ui.div(
                ui.span(
                    f"{len(active_rows)} active, {len(pending_rows)} pending",
                    class_="index-plate-stock-meta",
                ),
                class_="d-flex align-items-center justify-content-between gap-2 flex-wrap",
            ),
            ui.div(
                ui.tags.table(
                    ui.tags.tbody(
                        *_overview_section_rows(
                            active_rows,
                            section_label="Active Lots",
                            action_label="View Plate",
                            action_prefix="overview_select",
                            action_style="outline-primary",
                        ),
                        *_overview_section_rows(
                            pending_rows,
                            section_label="Pending Lots",
                            action_label="Activate",
                            action_prefix="overview_activate",
                            action_style="outline-success",
                        ),
                    ),
                    class_="index-plate-stock-table",
                ),
                class_="index-plate-stock-table-wrap",
            ),
            class_="index-plate-header-overview-panel",
        )
    else:
        overview_body = ui.p("No active or pending index lots.", class_="mb-0 index-plate-header-empty")

    return ui.tags.details(
        ui.tags.summary(
            ui.span(
                ui.span("Select a plate here", class_="index-plate-header-summary-label"),
                ui.span(str(len(overview_rows)), class_="index-plate-header-summary-count"),
                class_="index-plate-header-summary-main",
            ),
            ui.span("", class_="index-plate-header-summary-chevron", aria_hidden="true"),
            class_="index-plate-header-summary",
        ),
        ui.div(overview_body, class_="index-plate-header-overview-popover"),
        class_="index-plate-header-overview-details index-plate-header-menu",
    )


def index_plate_maps_ui(*, show_title: bool = True) -> ui.Tag:
    return ui.div(
        ui.h4("🧬 Reagent Overview", class_="mb-0") if show_title else None,
        ui.output_ui("index_plate_maps_toolbar"),
        ui.output_ui("index_plate_maps_content"),
        ui.tags.script(
            """
            document.addEventListener("toggle", function(event) {
              const target = event.target;
              if (!(target instanceof HTMLDetailsElement)) return;
              if (!target.classList.contains("index-plate-header-menu")) return;
              if (!target.open) return;

              const menuGroup = target.closest(".index-plate-card-header-controls");
              if (!menuGroup) return;

              menuGroup
                .querySelectorAll("details.index-plate-header-menu[open]")
                .forEach(function(detailsEl) {
                  if (detailsEl !== target) {
                    detailsEl.open = false;
                  }
                });
            });

            document.addEventListener("click", function(event) {
              document
                .querySelectorAll("details.index-plate-header-menu[open]")
                .forEach(function(detailsEl) {
                  if (!detailsEl.contains(event.target)) {
                    detailsEl.open = false;
                  }
                });
            });
            """
        ),
        class_="tool-comfort-scale",
    )


def index_plate_maps_server(input, output, session):
    prep_sets_state = reactive.Value(None)
    sequencing_stock_state = reactive.Value(None)
    plate_maps_state = reactive.Value(None)
    loaded_at_state = reactive.Value(None)
    is_loading_state = reactive.Value(False)
    pending_prep_set_action_state = reactive.Value(None)
    pending_index_lot_action_state = reactive.Value(None)
    active_lot_selection_state = reactive.Value("")
    prep_action_clicks: dict[str, int] = {}
    overview_action_clicks: dict[str, int] = {}

    def refresh_plate_maps() -> None:
        if not is_allowed_reagents_user(session):
            prep_sets_state.set(None)
            sequencing_stock_state.set(None)
            plate_maps_state.set(None)
            loaded_at_state.set(None)
            is_loading_state.set(False)
            ui.notification_show(reagents_access_denied_message(), type="warning", duration=6)
            return

        config = LIMSConfig.get_credentials()
        is_loading_state.set(True)
        active_lot_selection_state.set("")
        pending_index_lot_action_state.set(None)
        ui.modal_show(
            build_tool_loading_modal(
                title="Loading Reagent Overview",
                message="Loading Illumina planning data from Clarity.",
                detail="Please wait while prep sets, sequencing stock, and index lots are checked.",
            )
        )
        try:
            planning_data = get_illumina_planning_data(config)
            prep_sets_state.set(planning_data.prep_sets)
            sequencing_stock_state.set(planning_data.sequencing_stock)
            plate_maps_state.set(planning_data.plate_maps)
            loaded_at_state.set(datetime.now(UTC))
        finally:
            ui.modal_remove()
            is_loading_state.set(False)

    def _find_prep_set(sequence_number: int) -> PrepSetSummary | None:
        prep_result = prep_sets_state.get()
        if prep_result is None:
            return None
        for prep_set in prep_result.prep_sets:
            if prep_set.sequence_number == sequence_number:
                return prep_set
        return None

    def _find_index_lot_by_uri(lot_uri: str) -> ActiveIndexLot | None:
        result = plate_maps_state.get()
        if result is None:
            return None
        for plate_map in result.plate_maps:
            if plate_map.lot.lot_uri == lot_uri:
                return plate_map.lot
        for lot in result.pending_lots:
            if lot.lot_uri == lot_uri:
                return lot
        return None

    def _show_status_change_modal(*, lot: ActiveIndexLot, new_status: str, confirm_id: str, action_label: str) -> None:
        ui.modal_show(
            ui.modal(
                ui.p(f"{action_label} {lot.name}?"),
                ui.p(f"Set {lot.set_letter} | Expiry {lot.expiry_date or 'Not set'}", class_="text-muted mb-0"),
                title=f"{action_label} Index Lot",
                footer=ui.div(
                    ui.modal_button("Cancel", class_="btn-secondary"),
                    ui.input_action_button(confirm_id, action_label, class_="btn-primary"),
                    class_="d-flex justify-content-end gap-2",
                ),
            )
        )

    def _show_prep_set_status_change_modal(*, prep_set: PrepSetSummary, new_status: str, action_label: str) -> None:
        set_lot_names = ", ".join(lot.name for lot in prep_set.lots_by_type.values())
        ui.modal_show(
            ui.modal(
                ui.p(f"{action_label} prep set #{prep_set.sequence_number}?"),
                ui.p(set_lot_names, class_="text-muted mb-0"),
                title=f"{action_label} Prep Set",
                footer=ui.div(
                    ui.modal_button("Cancel", class_="btn-secondary"),
                    ui.input_action_button("confirm_prep_set_status_change", action_label, class_="btn-primary"),
                    class_="d-flex justify-content-end gap-2",
                ),
            )
        )
        pending_prep_set_action_state.set(
            {
                "sequence_number": prep_set.sequence_number,
                "new_status": new_status,
                "action_label": action_label,
            }
        )

    def _selected_lot(plate_maps: list[IndexPlateMap]) -> IndexPlateMap | None:
        if not plate_maps:
            return None

        selected_uri = active_lot_selection_state.get() or None

        if selected_uri:
            for plate_map in plate_maps:
                if plate_map.lot.lot_uri == selected_uri:
                    return plate_map

        return None

    @reactive.Effect
    @reactive.event(input.open_tool_index_plate_maps)
    def _load_on_open():
        refresh_plate_maps()

    @reactive.Effect
    @reactive.event(input.refresh_index_plate_maps)
    def _refresh_on_click():
        refresh_plate_maps()

    @reactive.Effect
    @reactive.event(input.view_planner_expiry_dates)
    def _show_planner_expiry_dates():
        ui.modal_show(
            _build_planner_expiry_modal(
                prep_sets_state.get(),
                sequencing_stock_state.get(),
            )
        )

    @reactive.Effect
    def _watch_prep_set_actions():
        nonlocal prep_action_clicks
        prep_result = prep_sets_state.get()
        if prep_result is None:
            return

        previous_clicks = dict(prep_action_clicks)
        current_clicks: dict[str, int] = {}
        triggered_action: tuple[PrepSetSummary, str, str] | None = None

        for prep_set in prep_result.prep_sets:
            action_id, action_label, _ = _prep_set_action(prep_set)
            if not action_id or not action_label:
                continue

            value = 0
            try:
                value = int((getattr(input, action_id)() or 0))
            except Exception:
                value = 0
            current_clicks[action_id] = value
            if value > previous_clicks.get(action_id, 0):
                if action_label == "Activate":
                    new_status = "ACTIVE"
                    confirm_label = "Activate"
                elif action_label == "Move to Pending":
                    new_status = "PENDING"
                    confirm_label = "Move to Pending"
                else:
                    new_status = "ARCHIVED"
                    confirm_label = "Archive"
                triggered_action = (prep_set, new_status, confirm_label)

        prep_action_clicks = _merge_action_clicks(prep_action_clicks, current_clicks)

        if triggered_action is not None:
            prep_set, new_status, action_label = triggered_action
            _show_prep_set_status_change_modal(
                prep_set=prep_set,
                new_status=new_status,
                action_label=action_label,
            )

    @reactive.Effect
    def _watch_overview_actions():
        nonlocal overview_action_clicks
        result = plate_maps_state.get()
        if result is None:
            return

        overview_rows = build_index_lot_overview_rows(result)
        active_rows = [row for row in overview_rows if row["status"] == "Active"]
        pending_rows = [row for row in overview_rows if row["status"] == "Pending"]

        previous_clicks = dict(overview_action_clicks)
        current_clicks: dict[str, int] = {}
        selected_active_lot_uri: str | None = None
        pending_activate_lot_uri: str | None = None

        for index, row in enumerate(active_rows):
            action_id = f"overview_select_{index}"
            value = 0
            try:
                value = int((getattr(input, action_id)() or 0))
            except Exception:
                value = 0
            current_clicks[action_id] = value
            if value > previous_clicks.get(action_id, 0):
                selected_active_lot_uri = row["lot_uri"]

        for index, row in enumerate(pending_rows):
            action_id = f"overview_activate_{index}"
            value = 0
            try:
                value = int((getattr(input, action_id)() or 0))
            except Exception:
                value = 0
            current_clicks[action_id] = value
            if value > previous_clicks.get(action_id, 0):
                pending_activate_lot_uri = row["lot_uri"]

        overview_action_clicks = _merge_action_clicks(overview_action_clicks, current_clicks)

        if selected_active_lot_uri is not None:
            active_lot_selection_state.set(selected_active_lot_uri)
            return

        if pending_activate_lot_uri is not None:
            lot = _find_index_lot_by_uri(pending_activate_lot_uri)
            if lot is not None:
                pending_index_lot_action_state.set(pending_activate_lot_uri)
                _show_status_change_modal(
                    lot=lot,
                    new_status="ACTIVE",
                    confirm_id="confirm_activate_pending_index_lot",
                    action_label="Activate",
                )

    @output
    @render.ui
    def index_plate_maps_toolbar():
        config = LIMSConfig.get_credentials()
        result = plate_maps_state.get()
        prep_result = prep_sets_state.get()
        sequencing_result = sequencing_stock_state.get()
        is_loading = bool(is_loading_state.get())
        loaded_at = loaded_at_state.get()
        view_model = build_index_plate_maps_view_model(result, loaded_at, is_loading=is_loading)

        loaded_at_text = view_model["loaded_at"]
        warnings = _planner_warning_items(
            list(view_model["warnings"]),
            prep_result,
            sequencing_result,
        )
        warning_count = len(warnings)
        prep_summary = summarize_prep_sets(prep_result.prep_sets) if prep_result and prep_result.success else None
        sequencing_summary = summarize_sequencing_stock(sequencing_result)
        base_url_text = (config.base_url or "").strip() if config else ""

        if is_loading:
            lims_badge = ui.span("LIMS Check Pending", class_="badge text-bg-secondary")
            lims_summary = "Loading planning data from Clarity..."
        elif result is not None and result.success:
            lims_badge = ui.span("Connected to LIMS", class_="badge text-bg-success")
            lims_summary = result.message
        else:
            lims_badge = ui.span("Connection Failed", class_="badge text-bg-danger")
            lims_summary = view_model["message"]

        warnings_badge = (
            ui.span(f"Warnings {warning_count}", class_="badge text-bg-warning")
            if warning_count
            else ui.span("Warnings 0", class_="badge text-bg-success")
        )

        details_body = ui.div(
            ui.div(
                ui.p(ui.strong("LIMS: "), str(lims_summary), class_="mb-0 small tool-status-details-line"),
                ui.p(
                    ui.strong("Base URL: "),
                    base_url_text or "Not configured.",
                    class_="mb-0 small tool-status-details-line",
                ),
                class_="tool-status-details-group",
            ),
            ui.div(
                ui.p(
                    ui.strong("Prep: "),
                    (
                        f"Sets {prep_summary['prep_set_count']}, pending {prep_summary['pending_count']}, warnings {prep_summary['warning_count']}"
                        if prep_summary is not None
                        else "Not loaded."
                    ),
                    class_="mb-0 small tool-status-details-line",
                ),
                ui.p(
                    ui.strong("Index: "),
                    (
                        f"Active {len(result.plate_maps)}, pending {len(result.pending_lots)}"
                        if result is not None and result.success
                        else "Not loaded."
                    ),
                    class_="mb-0 small tool-status-details-line",
                ),
                ui.p(
                    ui.strong("Sequencing: "),
                    (
                        f"MiSeq kits {sequencing_summary['miseq_kits']}, unmatched boxes {sequencing_summary['unmatched_boxes']}, PhiX {sequencing_summary['phix_lots']}"
                        if sequencing_summary is not None
                        else "Not loaded."
                    ),
                    class_="mb-0 small tool-status-details-line",
                ),
                class_="tool-status-details-group",
            ),
            ui.div(
                ui.p(
                    ui.strong("Ignored: "),
                    "Prep lots named Resteboks and index lots named Rester are excluded.",
                    class_="mb-0 small tool-status-details-line",
                ),
                ui.p(
                    ui.strong("Loaded: "),
                    loaded_at_text or "Not loaded yet",
                    class_="mb-0 small tool-status-details-line",
                ),
                class_="tool-status-details-group",
            ),
            ui.div(
                ui.strong("Warnings: "),
                (
                    ui.tags.ul(*(ui.tags.li(warning) for warning in warnings), class_="mb-0 mt-1")
                    if warnings
                    else ui.span("None")
                ),
                class_="mb-0 small tool-status-details-group",
            ),
            class_="mt-2 tool-status-details",
        )

        return ui.div(
            ui.div(
                ui.div(
                    ui.div(
                        lims_badge,
                        warnings_badge,
                        class_="d-flex align-items-center gap-2 flex-wrap",
                    ),
                    class_="d-flex align-items-center gap-3 flex-wrap justify-content-between",
                ),
                ui.div(
                    ui.input_action_button(
                        "refresh_index_plate_maps",
                        "Refresh",
                        class_="btn btn-primary btn-sm",
                    ),
                    class_="d-flex align-items-center gap-2 flex-wrap",
                ),
                style="display:flex; align-items:center; justify-content:space-between; gap:10px;",
            ),
            ui.tags.details(
                ui.tags.summary("Details", class_="small text-muted"),
                details_body,
            ),
            class_="tool-status-card",
        )

    @output
    @render.ui
    def index_plate_maps_content():
        result = plate_maps_state.get()
        prep_result = prep_sets_state.get()
        sequencing_result = sequencing_stock_state.get()
        is_loading = bool(is_loading_state.get())
        loaded_at = loaded_at_state.get()
        view_model = build_index_plate_maps_view_model(result, loaded_at, is_loading=is_loading)

        mode = view_model["mode"]
        if mode in {"idle", "loading"}:
            state_class = "alert-info"
            return ui.div(
                ui.div(str(view_model["message"]), class_=f"alert {state_class}"),
            )

        selected_plate_map = _selected_lot(result.plate_maps) if result is not None else None
        pending_lots = result.pending_lots if result is not None else []
        right_pane: ui.TagChild
        if mode == "error":
            right_pane = ui.div(
                ui.div(str(view_model["message"]), class_="alert alert-danger mb-0"),
                class_="index-planner-map-pane",
            )
        elif mode == "empty":
            right_pane = ui.div(
                ui.div(
                    _render_pending_index_lots_header(
                        pending_lots,
                        ui.output_ui("pending_index_lot_selector_ui"),
                    ) if pending_lots else None,
                    ui.div(str(view_model["message"]), class_="alert alert-secondary mb-0"),
                ),
                class_="index-planner-map-pane",
            )
        else:
            right_pane = ui.div(
                (
                    _render_plate_map_card(
                        selected_plate_map,
                        ui.div(
                            _render_index_lot_overview_header(result),
                            class_="index-plate-card-header-controls",
                        ),
                    )
                    if selected_plate_map is not None
                    else _render_empty_plate_map_card(
                        ui.div(
                            _render_index_lot_overview_header(result),
                            class_="index-plate-card-header-controls",
                        ),
                        active_count=len(result.plate_maps),
                        pending_count=len(result.pending_lots),
                    )
                ),
                class_="index-planner-map-pane",
            )

        return ui.div(
            ui.div(
                ui.div(
                    _render_prep_sets_card(prep_result, sequencing_result),
                    class_="index-planner-side-pane",
                ),
                right_pane,
                class_="index-planner-layout",
            ),
        )

    @reactive.Effect
    @reactive.event(input.archive_active_index_lot)
    def _prompt_archive_active_index_lot():
        result = plate_maps_state.get()
        if result is None:
            return
        selected_lot = _selected_lot(result.plate_maps)
        if selected_lot is None:
            ui.notification_show("No active index lot selected.", type="warning", duration=4)
            return
        _show_status_change_modal(
            lot=selected_lot.lot,
            new_status="ARCHIVED",
            confirm_id="confirm_archive_active_index_lot",
            action_label="Archive",
        )

    @reactive.Effect
    @reactive.event(input.move_active_index_lot_to_pending)
    def _prompt_move_active_index_lot_to_pending():
        result = plate_maps_state.get()
        if result is None:
            return
        selected_lot = _selected_lot(result.plate_maps)
        if selected_lot is None:
            ui.notification_show("No active index lot selected.", type="warning", duration=4)
            return
        if not can_move_plate_map_to_pending(selected_lot):
            ui.notification_show(
                "Only completely unused index lots can be moved back to pending.",
                type="warning",
                duration=5,
            )
            return
        _show_status_change_modal(
            lot=selected_lot.lot,
            new_status="PENDING",
            confirm_id="confirm_move_active_index_lot_to_pending",
            action_label="Move to Pending",
        )

    @reactive.Effect
    @reactive.event(input.confirm_archive_active_index_lot)
    def _archive_active_index_lot():
        result = plate_maps_state.get()
        if result is None:
            return
        selected_lot = _selected_lot(result.plate_maps)
        if selected_lot is None:
            ui.modal_remove()
            ui.notification_show("No active index lot selected.", type="warning", duration=4)
            return
        ui.modal_remove()
        config = LIMSConfig.get_credentials()
        update_result = update_reagent_lot_status(config, selected_lot.lot.lot_uri, "ARCHIVED")
        if update_result.success:
            ui.notification_show(f"Archived {update_result.name}.", type="message", duration=4)
            refresh_plate_maps()
        else:
            ui.notification_show(update_result.message, type="error", duration=6)

    @reactive.Effect
    @reactive.event(input.confirm_move_active_index_lot_to_pending)
    def _move_active_index_lot_to_pending():
        result = plate_maps_state.get()
        if result is None:
            return
        selected_lot = _selected_lot(result.plate_maps)
        if selected_lot is None:
            ui.modal_remove()
            ui.notification_show("No active index lot selected.", type="warning", duration=4)
            return
        if not can_move_plate_map_to_pending(selected_lot):
            ui.modal_remove()
            ui.notification_show(
                "Only completely unused index lots can be moved back to pending.",
                type="warning",
                duration=5,
            )
            return
        ui.modal_remove()
        config = LIMSConfig.get_credentials()
        update_result = update_reagent_lot_status(config, selected_lot.lot.lot_uri, "PENDING")
        if update_result.success:
            ui.notification_show(f"Moved {update_result.name} to pending.", type="message", duration=4)
            refresh_plate_maps()
        else:
            ui.notification_show(update_result.message, type="error", duration=6)

    @reactive.Effect
    @reactive.event(input.confirm_activate_pending_index_lot)
    def _activate_pending_index_lot():
        selected_lot_uri = pending_index_lot_action_state.get()
        selected_lot = _find_index_lot_by_uri(selected_lot_uri) if selected_lot_uri else None
        if selected_lot is None:
            ui.modal_remove()
            ui.notification_show("No pending index lot selected.", type="warning", duration=4)
            pending_index_lot_action_state.set(None)
            return
        ui.modal_remove()
        config = LIMSConfig.get_credentials()
        update_result = update_reagent_lot_status(config, selected_lot.lot_uri, "ACTIVE")
        pending_index_lot_action_state.set(None)
        if update_result.success:
            ui.notification_show(f"Activated {update_result.name}.", type="message", duration=4)
            refresh_plate_maps()
        else:
            ui.notification_show(update_result.message, type="error", duration=6)

    @reactive.Effect
    @reactive.event(input.confirm_prep_set_status_change)
    def _update_prep_set_status():
        pending_action = pending_prep_set_action_state.get()
        if not pending_action:
            ui.modal_remove()
            return

        sequence_number = int(pending_action["sequence_number"])
        new_status = str(pending_action["new_status"])
        prep_set = _find_prep_set(sequence_number)
        if prep_set is None:
            ui.modal_remove()
            ui.notification_show("Prep set no longer exists.", type="warning", duration=4)
            pending_prep_set_action_state.set(None)
            return

        ui.modal_remove()
        config = LIMSConfig.get_credentials()
        failures: list[str] = []
        updated_names: list[str] = []
        for lot in prep_set.lots_by_type.values():
            update_result = update_reagent_lot_status(config, lot.lot_uri, new_status)
            if update_result.success:
                updated_names.append(update_result.name or lot.name)
            else:
                failures.append(update_result.message)

        pending_prep_set_action_state.set(None)
        if failures:
            ui.notification_show("; ".join(failures[:2]), type="error", duration=8)
            return

        if new_status == "ACTIVE":
            action_word = "Activated"
        elif new_status == "PENDING":
            action_word = "Moved to pending"
        else:
            action_word = "Archived"
        ui.notification_show(f"{action_word} prep set #{sequence_number}.", type="message", duration=4)
        refresh_plate_maps()
