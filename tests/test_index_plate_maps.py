from __future__ import annotations

from datetime import date, datetime, timedelta, UTC
import xml.etree.ElementTree as ET

from shinylims.features.reagent_overview import (
    _assess_expiry_date,
    _build_planner_expiry_modal,
    _merge_action_clicks,
    _planner_expiry_warning_items,
    _planner_warning_items,
    _prep_set_action,
    _render_empty_plate_map_card,
    _render_index_lot_overview_header,
    _render_prep_sets_card,
    _sequencing_warning_items,
    build_index_lot_overview_rows,
    build_index_plate_maps_view_model,
    can_move_plate_map_to_pending,
    format_index_plate_selector_label,
    index_plate_conflict_count,
    move_to_pending_tooltip,
)
from shinylims.config.reagents import INDEX_REAGENT_TYPE, PREP_REAGENT_TYPES
from shinylims.integrations.lims_api import (
    _build_sequencing_stock_summary_rows,
    ActiveIndexLot,
    ActivePrepLot,
    ActivePrepSetsResult,
    IndexPlateMapsResult,
    LIMSConfig,
    PrepSetSummary,
    SequencingStockLot,
    SequencingStockResult,
    SequencingStockSummaryRow,
    build_index_plate_map,
    extract_index_set_letter,
    get_active_index_lots,
    get_active_prep_sets,
    get_illumina_planning_data,
    get_index_plate_maps_from_notes,
    get_reagent_sequence_statuses,
    get_sequencing_stock_summary,
    parse_prep_lot_name,
    parse_index_lot_notes,
    parse_index_note_line,
    update_reagent_lot_status,
)


class FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")


def make_active_lot(
    *,
    name: str = "A#15 (192)",
    notes: str = "",
    set_letter: str = "A",
) -> ActiveIndexLot:
    return ActiveIndexLot(
        lot_uri="https://lims/reagentlots/1",
        name=name,
        lot_number="LOT-001",
        expiry_date="2026-12-31",
        status="ACTIVE",
        set_letter=set_letter,
        notes=notes,
    )


def make_sequencing_result(
    *rows: SequencingStockSummaryRow,
    lots: list[SequencingStockLot] | None = None,
) -> SequencingStockResult:
    return SequencingStockResult(
        success=True,
        lots=lots or [],
        summary_rows=list(rows),
        message="Loaded sequencing stock.",
    )


def make_sequencing_lot(
    reagent_type: str,
    *,
    name: str,
    expiry_date: str = "",
    status: str = "ACTIVE",
    miseq_kit_type: str | None = None,
) -> SequencingStockLot:
    lot_slug = f"{reagent_type}-{name}".replace(" ", "_").replace("/", "_")
    return SequencingStockLot(
        lot_uri=f"https://lims/reagentlots/{lot_slug}",
        reagent_type=reagent_type,
        name=name,
        expiry_date=expiry_date,
        status=status,
        miseq_kit_type=miseq_kit_type,
    )


def make_prep_lot(
    reagent_type: str,
    *,
    expiry_date: str = "2026-12-31",
    status: str = "ACTIVE",
    sequence_number: int = 65,
    reactions_left: int = 45,
) -> ActivePrepLot:
    return ActivePrepLot(
        lot_uri=f"https://lims/reagentlots/{reagent_type}",
        reagent_type=reagent_type,
        name=f"#{sequence_number} ({reactions_left})",
        lot_number="LOT-001",
        expiry_date=expiry_date,
        status=status,
        sequence_number=sequence_number,
        reactions_left=reactions_left,
    )


def make_prep_set(
    *,
    sequence_number: int = 65,
    usable_reactions_left: int = 45,
    reactions_by_type: dict[str, int | None] | None = None,
    expiry_dates_by_type: dict[str, str] | None = None,
    warnings: list[str] | None = None,
    status: str = "ACTIVE",
    is_balanced: bool = True,
) -> PrepSetSummary:
    lot_reactions = usable_reactions_left if usable_reactions_left >= 0 else 0
    return PrepSetSummary(
        sequence_number=sequence_number,
        usable_reactions_left=usable_reactions_left,
        reactions_by_type=reactions_by_type or {
            reagent_type: usable_reactions_left for reagent_type in PREP_REAGENT_TYPES
        },
        lots_by_type={
            reagent_type: make_prep_lot(
                reagent_type,
                expiry_date=(expiry_dates_by_type or {}).get(reagent_type, "2026-12-31"),
                status=status,
                sequence_number=sequence_number,
                reactions_left=lot_reactions,
            )
            for reagent_type in PREP_REAGENT_TYPES
        },
        warnings=warnings or [],
        is_balanced=is_balanced,
    )


def test_extract_index_set_letter_supports_internal_name_and_set_label():
    assert extract_index_set_letter("A#15 (192)") == "A"
    assert extract_index_set_letter("B# 67 (192)") == "B"
    assert extract_index_set_letter("IDT Index Set C #12") == "C"
    assert extract_index_set_letter("Set D") == "D"
    assert extract_index_set_letter("E#15 (192)") is None


def test_parse_prep_lot_name_extracts_sequence_and_reactions_left():
    assert parse_prep_lot_name("#65 (45)") == (65, 45)
    assert parse_prep_lot_name("  #54 (4)  ") == (54, 4)
    assert parse_prep_lot_name("#29 TEST (192)") == (29, 192)
    assert parse_prep_lot_name("bad name") == (None, None)


def test_assess_expiry_date_classifies_threshold_states():
    today = date(2026, 3, 16)

    assert _assess_expiry_date("2026-03-15", today=today).state == "expired"
    assert _assess_expiry_date("2026-03-16", today=today).state == "expires_today"
    assert _assess_expiry_date("2026-04-15", today=today).state == "expiring_soon"
    assert _assess_expiry_date("2026-04-16", today=today).state == "ok"
    assert _assess_expiry_date("", today=today).state == "missing"
    assert _assess_expiry_date("not-a-date", today=today).state == "invalid"


def test_parse_index_note_line_expands_full_and_partial_columns():
    wells, warning = parse_index_note_line("Kolonne 1, 3 (A3, B03) og 12")

    assert warning is None
    assert len(wells) == 18
    assert "A01" in wells
    assert "H01" in wells
    assert "A03" in wells
    assert "B03" in wells
    assert "H12" in wells


def test_parse_index_note_line_rejects_invalid_column_well_mix():
    wells, warning = parse_index_note_line("Kolonne 2 (A03)")

    assert wells == []
    assert warning == "Well/column mismatch in note line 'Kolonne 2 (A03)' for column 2."


def test_parse_index_lot_notes_and_aggregation_count_repeated_usage():
    lot = make_active_lot(
        notes=(
            "Run 1:\n"
            "Kolonne 1, 2 (A02, B02) og 12\n"
            "Run 2:\n"
            "Kolonne 1 (A01, B01, C01)\n"
            "Manual note without usage data\n"
        )
    )

    usage_records, warnings = parse_index_lot_notes(lot)
    plate_map = build_index_plate_map(lot, usage_records)
    cell_by_well = {cell.well: cell for cell in plate_map.cells}

    assert warnings == []
    assert len(usage_records) == 21
    assert cell_by_well["A01"].raw_count == 2
    assert cell_by_well["A01"].state == "double"
    assert cell_by_well["D01"].raw_count == 1
    assert cell_by_well["D01"].state == "single"
    assert cell_by_well["A02"].raw_count == 1
    assert cell_by_well["A02"].state == "single"
    assert cell_by_well["A03"].raw_count == 0
    assert cell_by_well["A03"].state == "unused"


def test_build_index_plate_map_marks_conflicts_above_two_uses():
    lot = make_active_lot(notes="Run 1:\nKolonne 1 (A01)\nRun 2:\nKolonne 1 (A01)\nRun 3:\nKolonne 1 (A01)")

    usage_records, _ = parse_index_lot_notes(lot)
    plate_map = build_index_plate_map(lot, usage_records)
    cell_by_well = {cell.well: cell for cell in plate_map.cells}

    assert cell_by_well["A01"].raw_count == 3
    assert cell_by_well["A01"].state == "conflict"
    assert plate_map.conflict_wells == 1


def test_build_index_plate_map_preserves_plate_specific_warnings():
    lot = make_active_lot(notes="Run 1:\nKolonne 12 (1rx)")

    usage_records, warnings = parse_index_lot_notes(lot)
    plate_map = build_index_plate_map(lot, usage_records, warnings=warnings)

    assert usage_records == []
    assert len(plate_map.warnings) == 1
    assert "Missing explicit wells for column 12" in plate_map.warnings[0]


def test_format_index_plate_selector_label_marks_incomplete_lots():
    clean_lot = make_active_lot()
    clean_map = build_index_plate_map(clean_lot, [])
    warning_lot = make_active_lot(name="A#54 (4)")
    warning_map = build_index_plate_map(
        warning_lot,
        [],
        warnings=["A#54 (4): Missing explicit wells for column 12 in line 'Kolonne 12 (1rx)'."],
    )

    assert format_index_plate_selector_label(clean_map) == "A#15 (192) | Set A | Exp 2026-12-31"
    assert format_index_plate_selector_label(warning_map) == "A#54 (4) | Set A | Exp 2026-12-31 | Conflicts 1"


def test_index_plate_conflict_count_includes_incomplete_note_warnings():
    clean_map = build_index_plate_map(make_active_lot(), [])
    warning_map = build_index_plate_map(
        make_active_lot(name="A#54 (4)"),
        [],
        warnings=["A#54 (4): Missing explicit wells for column 12 in line 'Kolonne 12 (1rx)'."],
    )

    assert index_plate_conflict_count(clean_map) == 0
    assert index_plate_conflict_count(warning_map) == 1


def test_can_move_plate_map_to_pending_only_when_plate_is_completely_unused():
    unused_map = build_index_plate_map(make_active_lot(), [])
    used_map = build_index_plate_map(
        make_active_lot(notes="Run 1:\nKolonne 1 (A01)"),
        parse_index_lot_notes(make_active_lot(notes="Run 1:\nKolonne 1 (A01)"))[0],
    )
    warning_map = build_index_plate_map(
        make_active_lot(name="A#54 (4)"),
        [],
        warnings=["A#54 (4): Missing explicit wells for column 12 in line 'Kolonne 12 (1rx)'."],
    )

    assert can_move_plate_map_to_pending(unused_map) is True
    assert can_move_plate_map_to_pending(used_map) is False
    assert can_move_plate_map_to_pending(warning_map) is False


def test_move_to_pending_tooltip_explains_why_action_is_disabled():
    unused_map = build_index_plate_map(make_active_lot(), [])
    used_lot = make_active_lot(notes="Run 1:\nKolonne 1 (A01)")
    used_map = build_index_plate_map(used_lot, parse_index_lot_notes(used_lot)[0])
    warning_map = build_index_plate_map(
        make_active_lot(name="A#54 (4)"),
        [],
        warnings=["A#54 (4): Missing explicit wells for column 12 in line 'Kolonne 12 (1rx)'."],
    )

    assert move_to_pending_tooltip(unused_map) == "Move this unused lot back to pending."
    assert move_to_pending_tooltip(used_map) == "Cannot move to pending because this lot has recorded usage."
    assert move_to_pending_tooltip(warning_map) == "Cannot move to pending because this lot has incomplete note history."


def test_get_index_plate_maps_from_notes_reads_active_lots_and_warnings(monkeypatch):
    listing_xml = """
    <reagent-lots>
      <reagent-lot uri="https://lims/reagentlots/1">
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/3" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/2">
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/3" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/3">
        <status>INACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/3" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/4">
        <status>PENDING</status>
        <reagent-kit uri="https://lims/reagentkits/3" />
      </reagent-lot>
    </reagent-lots>
    """
    detail_xml = {
        "https://lims/reagentlots/1": """
        <reagent-lot>
          <name>A#15 (192)</name>
          <lot-number>LOT-001</lot-number>
          <expiry-date>2026-12-31</expiry-date>
          <status>ACTIVE</status>
          <notes>Run 1:
Kolonne 1, 2 (A02, B02) og 12</notes>
          <reagent-kit uri="https://lims/reagentkits/3" />
        </reagent-lot>
        """,
        "https://lims/reagentlots/2": """
        <reagent-lot>
          <name>E#15 (192)</name>
          <lot-number>LOT-002</lot-number>
          <expiry-date>2026-12-31</expiry-date>
          <status>ACTIVE</status>
          <notes>Run 1:
Kolonne 1</notes>
          <reagent-kit uri="https://lims/reagentkits/3" />
        </reagent-lot>
        """,
        "https://lims/reagentlots/4": """
        <reagent-lot>
          <name>D#65 (45)</name>
          <lot-number>LOT-004</lot-number>
          <expiry-date>2027-01-09</expiry-date>
          <status>PENDING</status>
          <notes></notes>
          <reagent-kit uri="https://lims/reagentkits/3" />
        </reagent-lot>
        """,
    }
    captured_reagentlot_params = []

    def fake_get(url, **kwargs):
        if url == "https://lims/reagentlots":
            captured_reagentlot_params.append(kwargs.get("params"))
            return FakeResponse(200, listing_xml)
        if url in detail_xml:
            return FakeResponse(200, detail_xml[url])
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)

    result = get_index_plate_maps_from_notes(
        LIMSConfig(base_url="https://lims", username="user", password="pass")
    )

    assert result.success is True
    assert captured_reagentlot_params == [{"kitname": INDEX_REAGENT_TYPE}]
    assert len(result.plate_maps) == 1
    assert len(result.pending_lots) == 1
    assert result.pending_lots[0].name == "D#65 (45)"
    assert result.plate_maps[0].lot.name == "A#15 (192)"
    assert result.plate_maps[0].single_use_wells == 18
    assert any("Skipped index lot 'E#15 (192)'" in warning for warning in result.warnings)


def test_get_active_index_lots_sorts_by_expiry_date(monkeypatch):
    listing_xml = """
    <reagent-lots>
      <reagent-lot uri="https://lims/reagentlots/1">
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/3" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/2">
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/3" />
      </reagent-lot>
    </reagent-lots>
    """
    detail_xml = {
        "https://lims/reagentlots/1": """
        <reagent-lot>
          <name>D#65 (45)</name>
          <lot-number>LOT-D</lot-number>
          <expiry-date>2027-01-09</expiry-date>
          <status>ACTIVE</status>
          <notes></notes>
          <reagent-kit uri="https://lims/reagentkits/3" />
        </reagent-lot>
        """,
        "https://lims/reagentlots/2": """
        <reagent-lot>
          <name>A#54 (4)</name>
          <lot-number>LOT-A</lot-number>
          <expiry-date>2026-07-25</expiry-date>
          <status>ACTIVE</status>
          <notes></notes>
          <reagent-kit uri="https://lims/reagentkits/3" />
        </reagent-lot>
        """,
    }

    def fake_get(url, **kwargs):
        if url == "https://lims/reagentlots":
            return FakeResponse(200, listing_xml)
        if url in detail_xml:
            return FakeResponse(200, detail_xml[url])
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)

    success, active_lots, warnings, message = get_active_index_lots(
        LIMSConfig(base_url="https://lims", username="user", password="pass")
    )

    assert success is True
    assert warnings == []
    assert message == "Loaded 2 active index lots."
    assert [lot.name for lot in active_lots] == ["A#54 (4)", "D#65 (45)"]


def test_get_index_plate_maps_from_notes_ignores_rester_without_warning(monkeypatch):
    listing_xml = """
    <reagent-lots>
      <reagent-lot uri="https://lims/reagentlots/11">
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/3" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/12">
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/3" />
      </reagent-lot>
    </reagent-lots>
    """
    detail_xml = {
        "https://lims/reagentlots/11": """
        <reagent-lot>
          <name>Rester</name>
          <lot-number>IDX-R</lot-number>
          <expiry-date>2027-01-09</expiry-date>
          <status>ACTIVE</status>
          <notes></notes>
          <reagent-kit uri="https://lims/reagentkits/3" />
        </reagent-lot>
        """,
        "https://lims/reagentlots/12": """
        <reagent-lot>
          <name>A#15 (192)</name>
          <lot-number>IDX-15</lot-number>
          <expiry-date>2026-12-31</expiry-date>
          <status>ACTIVE</status>
          <notes>Run 1:
Kolonne 1</notes>
          <reagent-kit uri="https://lims/reagentkits/3" />
        </reagent-lot>
        """,
    }

    def fake_get(url, **kwargs):
        if url == "https://lims/reagentlots":
            return FakeResponse(200, listing_xml)
        if url in detail_xml:
            return FakeResponse(200, detail_xml[url])
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)

    result = get_index_plate_maps_from_notes(
        LIMSConfig(base_url="https://lims", username="user", password="pass")
    )

    assert result.success is True
    assert len(result.plate_maps) == 1
    assert result.plate_maps[0].lot.name == "A#15 (192)"
    assert not any("Skipped index lot 'Rester'" in warning for warning in result.warnings)


def test_get_illumina_planning_data_uses_one_combined_listing_request(monkeypatch):
    listing_xml = """
    <reagent-lots>
      <reagent-lot uri="https://lims/reagentlots/401">
        <name>#65 (192)</name>
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/4" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/402">
        <name>#65 (192)</name>
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/5" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/403">
        <name>#65 (192)</name>
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/6" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/404">
        <name>RGT12345678 v3</name>
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/7" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/405">
        <name>RGT12345678 v3</name>
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/8" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/406">
        <name>A#15 (192)</name>
        <lot-number>IDX-15</lot-number>
        <expiry-date>2026-12-31</expiry-date>
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/3" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/407">
        <name>D#65 (45)</name>
        <lot-number>IDX-65</lot-number>
        <expiry-date>2027-01-09</expiry-date>
        <status>PENDING</status>
        <reagent-kit uri="https://lims/reagentkits/3" />
      </reagent-lot>
    </reagent-lots>
    """
    batch_response_xml = """
    <details>
      <reagent-lot uri="https://lims/reagentlots/406">
        <name>A#15 (192)</name>
        <lot-number>IDX-15</lot-number>
        <expiry-date>2026-12-31</expiry-date>
        <status>ACTIVE</status>
        <notes>Run 1:
Kolonne 1</notes>
        <reagent-kit uri="https://lims/reagentkits/3" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/407">
        <name>D#65 (45)</name>
        <lot-number>IDX-65</lot-number>
        <expiry-date>2027-01-09</expiry-date>
        <status>PENDING</status>
        <notes></notes>
        <reagent-kit uri="https://lims/reagentkits/3" />
      </reagent-lot>
    </details>
    """
    captured_params = []
    batch_calls = []
    detail_request_uris = []

    def fake_get(url, **kwargs):
        if url == "https://lims/reagentlots":
            captured_params.append(kwargs.get("params"))
            return FakeResponse(200, listing_xml)
        raise AssertionError(f"Unexpected URL: {url}")

    def fake_post(url, **kwargs):
        batch_calls.append(url)
        assert url == "https://lims/reagentlots/batch/retrieve"
        payload_root = ET.fromstring(kwargs["data"])
        detail_request_uris.append(
            sorted(
                (element.attrib.get("uri") or "").strip()
                for element in payload_root.iter()
                if element.attrib.get("uri")
            )
        )
        return FakeResponse(200, batch_response_xml)

    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)
    monkeypatch.setattr("shinylims.integrations.lims_api._lims_post", fake_post)

    result = get_illumina_planning_data(
        LIMSConfig(base_url="https://lims", username="user", password="pass")
    )

    assert len(captured_params) == 1
    assert captured_params[0] == {
        "kitname": [
            *PREP_REAGENT_TYPES,
            "MiSeq Reagent Kit (Box 1 of 2)",
            "MiSeq Reagent Kit (Box 2 of 2)",
            "PhiX Control v3",
            INDEX_REAGENT_TYPE,
        ]
    }
    assert batch_calls == ["https://lims/reagentlots/batch/retrieve"]
    assert detail_request_uris == [["https://lims/reagentlots/406"]]
    assert result.prep_sets.success is True
    assert [prep_set.sequence_number for prep_set in result.prep_sets.prep_sets] == [65]
    assert result.sequencing_stock.success is True
    assert [row.kit_count for row in result.sequencing_stock.summary_rows] == [1, 0, 0, 0]
    assert result.plate_maps.success is True
    assert len(result.plate_maps.plate_maps) == 1
    assert len(result.plate_maps.pending_lots) == 1
    assert result.plate_maps.plate_maps[0].lot.name == "A#15 (192)"


def test_get_illumina_planning_data_falls_back_to_per_kit_listing_when_combined_is_overbroad(monkeypatch):
    combined_listing_xml = """
    <reagent-lots>
      <reagent-lot uri="https://lims/reagentlots/901" />
      <reagent-lot uri="https://lims/reagentlots/902" />
      <reagent-lot uri="https://lims/reagentlots/903" />
    </reagent-lots>
    """
    per_kit_listing_by_name = {
        PREP_REAGENT_TYPES[0]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/101">
            <name>#65 (192)</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/4" />
          </reagent-lot>
        </reagent-lots>
        """,
        PREP_REAGENT_TYPES[1]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/102">
            <name>#65 (192)</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/5" />
          </reagent-lot>
        </reagent-lots>
        """,
        PREP_REAGENT_TYPES[2]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/103">
            <name>#65 (192)</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/6" />
          </reagent-lot>
        </reagent-lots>
        """,
        "MiSeq Reagent Kit (Box 1 of 2)": "<reagent-lots />",
        "MiSeq Reagent Kit (Box 2 of 2)": "<reagent-lots />",
        "PhiX Control v3": "<reagent-lots />",
        INDEX_REAGENT_TYPE: "<reagent-lots />",
    }
    captured_params = []

    def fake_get(url, **kwargs):
        if url != "https://lims/reagentlots":
            raise AssertionError(f"Unexpected URL: {url}")

        params = kwargs.get("params") or {}
        captured_params.append(params)
        kitname = params.get("kitname")
        if isinstance(kitname, list):
            return FakeResponse(200, combined_listing_xml)
        return FakeResponse(200, per_kit_listing_by_name[kitname])

    def fake_post(url, **kwargs):
        raise AssertionError(f"Batch retrieve should not be reached after fallback selection: {url}")

    monkeypatch.setattr("shinylims.integrations.lims_api.PLANNER_COMBINED_LISTING_FALLBACK_THRESHOLD", 2)
    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)
    monkeypatch.setattr("shinylims.integrations.lims_api._lims_post", fake_post)

    result = get_illumina_planning_data(
        LIMSConfig(base_url="https://lims", username="user", password="pass")
    )

    assert isinstance(captured_params[0]["kitname"], list)
    assert [params["kitname"] for params in captured_params[1:]] == [
        *PREP_REAGENT_TYPES,
        "MiSeq Reagent Kit (Box 1 of 2)",
        "MiSeq Reagent Kit (Box 2 of 2)",
        "PhiX Control v3",
        INDEX_REAGENT_TYPE,
    ]
    assert result.prep_sets.success is True
    assert [prep_set.sequence_number for prep_set in result.prep_sets.prep_sets] == [65]
    assert result.sequencing_stock.summary_rows[0].kit_count == 0
    assert result.plate_maps.plate_maps == []


def test_get_active_prep_sets_groups_rows_and_flags_uneven_counts(monkeypatch):
    listing_by_kitname = {
        PREP_REAGENT_TYPES[0]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/101">
            <name>#65 TEST (45)</name>
            <lot-number>IPB-65</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/4" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/111">
            <name>#64 (20)</name>
            <lot-number>IPB-64</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/4" />
          </reagent-lot>
        </reagent-lots>
        """,
        PREP_REAGENT_TYPES[1]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/102">
            <name>#65 (37)</name>
            <lot-number>PCR-65</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/5" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/112">
            <name>#64 (20)</name>
            <lot-number>PCR-64</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/5" />
          </reagent-lot>
        </reagent-lots>
        """,
        PREP_REAGENT_TYPES[2]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/103">
            <name>#65 (45)</name>
            <lot-number>TAG-65</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/6" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/113">
            <name>#64 (20)</name>
            <lot-number>TAG-64</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>PENDING</status>
            <reagent-kit uri="https://lims/reagentkits/6" />
          </reagent-lot>
        </reagent-lots>
        """,
    }
    captured_params = []

    def fake_get(url, **kwargs):
        if url == "https://lims/reagentlots":
            params = kwargs.get("params") or {}
            captured_params.append(params)
            return FakeResponse(200, listing_by_kitname[params["kitname"]])
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)

    result = get_active_prep_sets(
        LIMSConfig(base_url="https://lims", username="user", password="pass")
    )

    assert result.success is True
    assert captured_params == [{"kitname": reagent_type} for reagent_type in PREP_REAGENT_TYPES]
    assert [prep_set.sequence_number for prep_set in result.prep_sets] == [65, 64]
    assert result.prep_sets[0].usable_reactions_left == 37
    assert result.prep_sets[0].is_balanced is False
    assert "Unequal reactions left across boxes" in result.prep_sets[0].warnings[0]
    assert result.prep_sets[1].usable_reactions_left == 20
    assert result.prep_sets[1].is_balanced is True
    assert result.prep_sets[1].lots_by_type[PREP_REAGENT_TYPES[2]].status == "PENDING"


def test_get_active_prep_sets_sorts_active_first_then_increasing_sequence(monkeypatch):
    listing_by_kitname = {
        PREP_REAGENT_TYPES[0]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/201">
            <name>#65 (20)</name>
            <lot-number>IPB-65</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/4" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/202">
            <name>#63 (20)</name>
            <lot-number>IPB-63</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/4" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/203">
            <name>#64 (20)</name>
            <lot-number>IPB-64</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/4" />
          </reagent-lot>
        </reagent-lots>
        """,
        PREP_REAGENT_TYPES[1]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/211">
            <name>#65 (20)</name>
            <lot-number>PCR-65</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/5" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/212">
            <name>#63 (20)</name>
            <lot-number>PCR-63</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/5" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/213">
            <name>#64 (20)</name>
            <lot-number>PCR-64</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/5" />
          </reagent-lot>
        </reagent-lots>
        """,
        PREP_REAGENT_TYPES[2]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/221">
            <name>#65 (20)</name>
            <lot-number>TAG-65</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/6" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/222">
            <name>#63 (20)</name>
            <lot-number>TAG-63</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/6" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/223">
            <name>#64 (20)</name>
            <lot-number>TAG-64</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>PENDING</status>
            <reagent-kit uri="https://lims/reagentkits/6" />
          </reagent-lot>
        </reagent-lots>
        """,
    }

    def fake_get(url, **kwargs):
        if url == "https://lims/reagentlots":
            params = kwargs.get("params") or {}
            return FakeResponse(200, listing_by_kitname[params["kitname"]])
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)

    result = get_active_prep_sets(
        LIMSConfig(base_url="https://lims", username="user", password="pass")
    )

    assert [prep_set.sequence_number for prep_set in result.prep_sets] == [63, 65, 64]


def test_get_active_prep_sets_ignores_resteboks_without_warning(monkeypatch):
    listing_by_kitname = {
        PREP_REAGENT_TYPES[0]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/241">
            <name>Resteboks</name>
            <lot-number>IPB-R</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/4" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/242">
            <name>#65 (20)</name>
            <lot-number>IPB-65</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/4" />
          </reagent-lot>
        </reagent-lots>
        """,
        PREP_REAGENT_TYPES[1]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/251">
            <name>#65 (20)</name>
            <lot-number>PCR-65</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/5" />
          </reagent-lot>
        </reagent-lots>
        """,
        PREP_REAGENT_TYPES[2]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/261">
            <name>#65 (20)</name>
            <lot-number>TAG-65</lot-number>
            <expiry-date>2026-12-31</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/6" />
          </reagent-lot>
        </reagent-lots>
        """,
    }

    def fake_get(url, **kwargs):
        if url == "https://lims/reagentlots":
            params = kwargs.get("params") or {}
            return FakeResponse(200, listing_by_kitname[params["kitname"]])
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)

    result = get_active_prep_sets(
        LIMSConfig(base_url="https://lims", username="user", password="pass")
    )

    assert result.success is True
    assert result.warnings == []
    assert [prep_set.sequence_number for prep_set in result.prep_sets] == [65]


def test_get_active_prep_sets_uses_batch_retrieve_for_missing_lot_fields(monkeypatch):
    listing_by_kitname = {
        PREP_REAGENT_TYPES[0]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/301">
            <name>#65 (192)</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/4" />
          </reagent-lot>
        </reagent-lots>
        """,
        PREP_REAGENT_TYPES[1]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/302">
            <name>#65 (192)</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/5" />
          </reagent-lot>
        </reagent-lots>
        """,
        PREP_REAGENT_TYPES[2]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/303">
            <name>#65 (192)</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/6" />
          </reagent-lot>
        </reagent-lots>
        """,
    }
    batch_response_xml = """
    <details>
      <reagent-lot uri="https://lims/reagentlots/301">
        <name>#65 (192)</name>
        <lot-number>IPB-65</lot-number>
        <expiry-date>2026-12-31</expiry-date>
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/4" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/302">
        <name>#65 (192)</name>
        <lot-number>PCR-65</lot-number>
        <expiry-date>2026-12-31</expiry-date>
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/5" />
      </reagent-lot>
      <reagent-lot uri="https://lims/reagentlots/303">
        <name>#65 (192)</name>
        <lot-number>TAG-65</lot-number>
        <expiry-date>2026-12-31</expiry-date>
        <status>ACTIVE</status>
        <reagent-kit uri="https://lims/reagentkits/6" />
      </reagent-lot>
    </details>
    """
    batch_calls: list[str] = []

    def fake_get(url, **kwargs):
        if url == "https://lims/reagentlots":
            params = kwargs.get("params") or {}
            return FakeResponse(200, listing_by_kitname[params["kitname"]])
        raise AssertionError(f"Unexpected per-lot GET: {url}")

    def fake_post(url, **kwargs):
        batch_calls.append(url)
        assert url == "https://lims/reagentlots/batch/retrieve"
        return FakeResponse(200, batch_response_xml)

    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)
    monkeypatch.setattr("shinylims.integrations.lims_api._lims_post", fake_post)

    result = get_active_prep_sets(
        LIMSConfig(base_url="https://lims", username="user", password="pass")
    )

    assert result.success is True
    assert batch_calls == ["https://lims/reagentlots/batch/retrieve"]
    assert [prep_set.sequence_number for prep_set in result.prep_sets] == [65]


def test_get_active_prep_sets_falls_back_when_batch_retrieve_is_unavailable(monkeypatch):
    listing_by_kitname = {
        PREP_REAGENT_TYPES[0]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/311">
            <name>#65 (192)</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/4" />
          </reagent-lot>
        </reagent-lots>
        """,
        PREP_REAGENT_TYPES[1]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/312">
            <name>#65 (192)</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/5" />
          </reagent-lot>
        </reagent-lots>
        """,
        PREP_REAGENT_TYPES[2]: """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/313">
            <name>#65 (192)</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/6" />
          </reagent-lot>
        </reagent-lots>
        """,
    }
    detail_by_uri = {
        "https://lims/reagentlots/311": """
        <reagent-lot uri="https://lims/reagentlots/311">
          <name>#65 (192)</name>
          <lot-number>IPB-65</lot-number>
          <expiry-date>2026-12-31</expiry-date>
          <status>ACTIVE</status>
          <reagent-kit uri="https://lims/reagentkits/4" />
        </reagent-lot>
        """,
        "https://lims/reagentlots/312": """
        <reagent-lot uri="https://lims/reagentlots/312">
          <name>#65 (192)</name>
          <lot-number>PCR-65</lot-number>
          <expiry-date>2026-12-31</expiry-date>
          <status>ACTIVE</status>
          <reagent-kit uri="https://lims/reagentkits/5" />
        </reagent-lot>
        """,
        "https://lims/reagentlots/313": """
        <reagent-lot uri="https://lims/reagentlots/313">
          <name>#65 (192)</name>
          <lot-number>TAG-65</lot-number>
          <expiry-date>2026-12-31</expiry-date>
          <status>ACTIVE</status>
          <reagent-kit uri="https://lims/reagentkits/6" />
        </reagent-lot>
        """,
    }
    per_lot_gets: list[str] = []

    def fake_get(url, **kwargs):
        if url == "https://lims/reagentlots":
            params = kwargs.get("params") or {}
            return FakeResponse(200, listing_by_kitname[params["kitname"]])
        if url in detail_by_uri:
            per_lot_gets.append(url)
            return FakeResponse(200, detail_by_uri[url])
        raise AssertionError(f"Unexpected URL: {url}")

    def fake_post(url, **kwargs):
        assert url == "https://lims/reagentlots/batch/retrieve"
        return FakeResponse(404, "<error />")

    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)
    monkeypatch.setattr("shinylims.integrations.lims_api._lims_post", fake_post)

    result = get_active_prep_sets(
        LIMSConfig(base_url="https://lims", username="user", password="pass")
    )

    assert result.success is True
    assert sorted(per_lot_gets) == sorted(detail_by_uri)
    assert [prep_set.sequence_number for prep_set in result.prep_sets] == [65]


def test_build_index_plate_maps_view_model_handles_empty_warning_and_ready_states():
    empty_result = IndexPlateMapsResult(
        success=True,
        plate_maps=[],
        pending_lots=[],
        warnings=[],
        message="No active index lots were found.",
    )
    empty_view = build_index_plate_maps_view_model(
        empty_result,
        datetime(2026, 3, 12, 10, 0, tzinfo=UTC),
        is_loading=False,
    )

    lot_a = make_active_lot(name="A#15 (192)", notes="Run 1:\nKolonne 1")
    lot_b = make_active_lot(name="B#16 (192)", notes="Run 1:\nKolonne 2", set_letter="B")
    plate_map_a = build_index_plate_map(lot_a, parse_index_lot_notes(lot_a)[0])
    plate_map_b = build_index_plate_map(lot_b, parse_index_lot_notes(lot_b)[0])
    ready_result = IndexPlateMapsResult(
        success=True,
        plate_maps=[plate_map_a, plate_map_b],
        pending_lots=[make_active_lot(name="D#65 (45)", set_letter="D")],
        warnings=["Example warning"],
        message="Loaded 2 active index plate maps.",
    )
    ready_view = build_index_plate_maps_view_model(
        ready_result,
        datetime(2026, 3, 12, 10, 0, tzinfo=UTC),
        is_loading=False,
    )

    assert empty_view["mode"] == "empty"
    assert ready_view["mode"] == "ready"
    assert ready_view["warnings"] == ["Example warning"]
    assert ready_view["pending_lot_count"] == 1
    assert ready_view["summary"] == {
        "lot_count": 2,
        "unused_wells": 176,
        "single_use_wells": 16,
        "double_use_wells": 0,
        "conflict_wells": 0,
    }
    assert len(ready_view["cards"]) == 2


def test_build_index_lot_overview_rows_sorts_active_and_pending_by_expiry():
    active_earlier = build_index_plate_map(
        make_active_lot(name="A#54 (4)", set_letter="A"),
        [],
    )
    active_later = build_index_plate_map(
        ActiveIndexLot(
            lot_uri="https://lims/reagentlots/2",
            name="C#68 (192)",
            lot_number="LOT-002",
            expiry_date="2027-05-13",
            status="ACTIVE",
            set_letter="C",
            notes="",
        ),
        [],
    )
    pending_earlier = ActiveIndexLot(
        lot_uri="https://lims/reagentlots/3",
        name="D#65 (45)",
        lot_number="LOT-003",
        expiry_date="2027-01-09",
        status="PENDING",
        set_letter="D",
        notes="",
    )
    pending_no_expiry = ActiveIndexLot(
        lot_uri="https://lims/reagentlots/4",
        name="B#67 (192)",
        lot_number="LOT-004",
        expiry_date="",
        status="PENDING",
        set_letter="B",
        notes="",
    )
    result = IndexPlateMapsResult(
        success=True,
        plate_maps=[active_later, active_earlier],
        pending_lots=[pending_no_expiry, pending_earlier],
        warnings=[],
        message="Loaded 2 active index plate maps.",
    )

    overview_rows = build_index_lot_overview_rows(result)

    assert [row["name"] for row in overview_rows] == [
        "A#54 (4)",
        "C#68 (192)",
        "D#65 (45)",
        "B#67 (192)",
    ]
    assert [row["status"] for row in overview_rows] == ["Active", "Active", "Pending", "Pending"]
    assert overview_rows[0]["lot_uri"] == "https://lims/reagentlots/1"


def test_render_empty_plate_map_card_no_longer_embeds_stock_overview():
    rendered = str(_render_empty_plate_map_card(active_count=5, pending_count=3))

    assert "Use the drop-down menu above to view active lots, activate pending lots, and load a plate map." in rendered
    assert "Select an active lot to review plate usage." in rendered
    assert "Active kits: 5" in rendered
    assert "Pending kits: 3" in rendered
    assert "Choose a lot from the drop-down menu above to load the plate map and review availability." in rendered
    assert "View active lots and activate pending lots from the menu." not in rendered
    assert "Select an active lot to review its plate map." not in rendered
    assert "Index Reagents In Stock" not in rendered


def test_render_index_lot_overview_header_lists_active_and_pending_lots():
    active_map = build_index_plate_map(make_active_lot(name="A#54 (4)", set_letter="A"), [])
    pending_lot = ActiveIndexLot(
        lot_uri="https://lims/reagentlots/4",
        name="D#65 (45)",
        lot_number="LOT-004",
        expiry_date="2027-01-09",
        status="PENDING",
        set_letter="D",
        notes="",
    )
    result = IndexPlateMapsResult(
        success=True,
        plate_maps=[active_map],
        pending_lots=[pending_lot],
        warnings=[],
        message="Loaded 1 active index plate map.",
    )

    rendered = str(_render_index_lot_overview_header(result))

    assert "Select a plate here" in rendered
    assert ">2<" in rendered
    assert "Active Lots" in rendered
    assert "Pending Lots" in rendered
    assert rendered.count("Lot") >= 2
    assert rendered.count("Status") >= 2
    assert "A#54 (4)" in rendered
    assert "D#65 (45)" in rendered
    assert "View Plate" in rendered
    assert "Activate" in rendered


def test_update_reagent_lot_status_puts_full_xml(monkeypatch):
    detail_xml = """
    <reagent-lot>
      <name>D#65 (45)</name>
      <lot-number>LOT-004</lot-number>
      <expiry-date>2027-01-09</expiry-date>
      <status>PENDING</status>
      <notes>Some note</notes>
      <storage-location>Cold room</storage-location>
      <reagent-kit uri="https://lims/reagentkits/3" />
    </reagent-lot>
    """
    put_calls = []

    def fake_get(url, **kwargs):
        assert url == "https://lims/reagentlots/4"
        return FakeResponse(200, detail_xml)

    def fake_put(url, **kwargs):
        put_calls.append((url, kwargs))
        return FakeResponse(200, "<ok />")

    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)
    monkeypatch.setattr("shinylims.integrations.lims_api.requests.put", fake_put)

    result = update_reagent_lot_status(
        LIMSConfig(base_url="https://lims", username="user", password="pass"),
        "https://lims/reagentlots/4",
        "ACTIVE",
    )

    assert result.success is True
    assert put_calls[0][0] == "https://lims/reagentlots/4"
    payload = put_calls[0][1]["data"].decode("utf-8")
    assert "<status>ACTIVE</status>" in payload
    assert "<name>D#65 (45)</name>" in payload
    assert "<notes>Some note</notes>" in payload


def test_get_reagent_sequence_statuses_filters_listing_by_requested_kitnames(monkeypatch):
    listing_by_kitname = {
        "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp": """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/11">
            <name>#41 TEST (192)</name>
            <status>PENDING</status>
            <reagent-kit uri="https://lims/reagentkits/4" />
          </reagent-lot>
        </reagent-lots>
        """,
        "IDT-ILMN DNA/RNA UD Index Sets": """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/12">
            <name>A#67 (192)</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/3" />
          </reagent-lot>
        </reagent-lots>
        """,
    }
    captured_reagentlot_params = []

    def fake_get(url, **kwargs):
        if url == "https://lims/reagentlots":
            params = kwargs.get("params") or {}
            captured_reagentlot_params.append(params)
            return FakeResponse(200, listing_by_kitname[params["kitname"]])
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)

    statuses = get_reagent_sequence_statuses(
        LIMSConfig(base_url="https://lims", username="user", password="pass"),
        prep_reagent_types=["Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp"],
    )

    assert statuses.prep.success is True
    assert statuses.prep.latest_complete_sequence == 41
    assert statuses.index.success is True
    assert statuses.index.latest_sequence == 67
    assert captured_reagentlot_params == [
        {"kitname": "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp"},
        {"kitname": INDEX_REAGENT_TYPE},
    ]


def test_get_sequencing_stock_summary_counts_miseq_pairs_and_phix(monkeypatch):
    listing_by_kitname = {
        "MiSeq Reagent Kit (Box 1 of 2)": """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/21">
            <name>RGT11111111 v3</name>
            <expiry-date>2026-05-01</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/7" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/22">
            <name>RGT22222222 v2 nano</name>
            <expiry-date>2026-05-15</expiry-date>
            <status>PENDING</status>
            <reagent-kit uri="https://lims/reagentkits/7" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/23">
            <name>RGT33333333 v2 micro</name>
            <status>ARCHIVED</status>
            <reagent-kit uri="https://lims/reagentkits/7" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/29">
            <name>Dummy lot</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/7" />
          </reagent-lot>
        </reagent-lots>
        """,
        "MiSeq Reagent Kit (Box 2 of 2)": """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/24">
            <name>RGT11111111 v3</name>
            <expiry-date>2026-05-02</expiry-date>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/8" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/25">
            <name>RGT22222222 v2 nano</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/8" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/26">
            <name>RGT44444444 v2 nano</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/8" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/30">
            <name>dummy kit</name>
            <status>ACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/8" />
          </reagent-lot>
        </reagent-lots>
        """,
        "PhiX Control v3": """
        <reagent-lots>
          <reagent-lot uri="https://lims/reagentlots/27">
            <name>RGT55555555</name>
            <expiry-date>2026-06-01</expiry-date>
            <status>PENDING</status>
            <reagent-kit uri="https://lims/reagentkits/12" />
          </reagent-lot>
          <reagent-lot uri="https://lims/reagentlots/28">
            <name>RGT66666666</name>
            <status>INACTIVE</status>
            <reagent-kit uri="https://lims/reagentkits/12" />
          </reagent-lot>
        </reagent-lots>
        """,
    }
    captured_reagentlot_params = []

    def fake_get(url, **kwargs):
        if url == "https://lims/reagentlots":
            params = kwargs.get("params") or {}
            captured_reagentlot_params.append(params)
            return FakeResponse(200, listing_by_kitname[params["kitname"]])
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("shinylims.integrations.lims_api._lims_get", fake_get)

    result = get_sequencing_stock_summary(
        LIMSConfig(base_url="https://lims", username="user", password="pass"),
    )

    assert result.success is True
    assert [row.item for row in result.summary_rows] == [
        "MiSeq v3",
        "MiSeq v2 nano",
        "MiSeq v2 micro",
        "PhiX Control v3",
    ]
    assert [row.kit_count for row in result.summary_rows] == [1, 1, 0, 1]
    assert [row.unmatched_count for row in result.summary_rows] == [0, 1, 0, None]
    assert len(result.lots) == 6
    assert all(not lot.name.lower().startswith("dummy") for lot in result.lots)
    assert next(lot for lot in result.lots if lot.name == "RGT11111111 v3").expiry_date == "2026-05-01"
    assert not hasattr(result.lots[0], "notes")
    assert captured_reagentlot_params == [
        {"kitname": "MiSeq Reagent Kit (Box 1 of 2)"},
        {"kitname": "MiSeq Reagent Kit (Box 2 of 2)"},
        {"kitname": "PhiX Control v3"},
    ]


def test_render_prep_sets_card_includes_read_only_sequencing_stock():
    prep_result = ActivePrepSetsResult(
        success=True,
        prep_sets=[],
        warnings=[],
        message="No active or pending prep sets were found.",
    )
    sequencing_result = make_sequencing_result(
        SequencingStockSummaryRow(item="MiSeq v3", kit_count=2, unmatched_count=1),
        SequencingStockSummaryRow(item="PhiX Control v3", kit_count=4, unmatched_count=None),
    )

    rendered = str(_render_prep_sets_card(prep_result, sequencing_result))

    assert "Prep and Sequencing" in rendered
    assert "Prep Sets" in rendered
    assert "Sequencing Stock" in rendered
    assert "MiSeq v3" in rendered
    assert "PhiX Control v3" in rendered
    assert "Unmatched" in rendered
    assert "View expiry dates" in rendered
    assert "index-planner-expiry-trigger" in rendered
    assert "notes" not in rendered.lower()


def test_render_prep_sets_card_keeps_prep_warning_in_card_header_only():
    prep_result = ActivePrepSetsResult(
        success=True,
        prep_sets=[
            make_prep_set(
                usable_reactions_left=12,
                reactions_by_type={
                    PREP_REAGENT_TYPES[0]: 12,
                    PREP_REAGENT_TYPES[1]: None,
                    PREP_REAGENT_TYPES[2]: None,
                },
                warnings=["Missing boxes: PCR box, TAG box"],
                is_balanced=False,
            )
        ],
        warnings=[],
        message="Loaded prep sets.",
    )

    rendered = str(_render_prep_sets_card(prep_result, make_sequencing_result()))

    assert rendered.count("Highlighted prep sets need attention.") == 1
    assert "Highlighted sets need attention." not in rendered
    assert "Missing boxes. Attention needed." in rendered
    assert "Missing boxes: PCR box, TAG box" not in rendered


def test_prep_set_action_uses_activate_move_to_pending_and_archive_states():
    pending_set = make_prep_set(status="PENDING", usable_reactions_left=192)
    active_unused_set = make_prep_set(status="ACTIVE", usable_reactions_left=192)
    active_in_use_set = make_prep_set(status="ACTIVE", usable_reactions_left=191)

    assert _prep_set_action(pending_set) == ("prep_activate_65", "Activate", "outline-success")
    assert _prep_set_action(active_unused_set) == ("prep_move_to_pending_65", "Move to Pending", "outline-secondary")
    assert _prep_set_action(active_in_use_set) == ("prep_archive_65", "Archive", "outline-danger")


def test_merge_action_clicks_preserves_hidden_button_counts():
    click_state = _merge_action_clicks(
        {"prep_activate_65": 1},
        {"prep_move_to_pending_65": 1},
    )
    click_state = _merge_action_clicks(
        click_state,
        {"prep_activate_65": 1},
    )

    assert click_state["prep_activate_65"] == 1
    assert click_state["prep_move_to_pending_65"] == 1


def test_render_prep_sets_card_shows_move_to_pending_for_unused_active_set():
    prep_result = ActivePrepSetsResult(
        success=True,
        prep_sets=[make_prep_set(status="ACTIVE", usable_reactions_left=192)],
        warnings=[],
        message="Loaded prep sets.",
    )

    rendered = str(_render_prep_sets_card(prep_result, make_sequencing_result()))

    assert "Move to Pending" in rendered
    assert "Archive" not in rendered


def test_render_prep_sets_card_flags_unknown_sequencing_stock():
    prep_result = ActivePrepSetsResult(
        success=True,
        prep_sets=[],
        warnings=[],
        message="No active or pending prep sets were found.",
    )
    sequencing_result = make_sequencing_result(
        SequencingStockSummaryRow(item="MiSeq Unknown", kit_count=1, unmatched_count=1),
        SequencingStockSummaryRow(item="PhiX Control v3", kit_count=2, unmatched_count=None),
    )

    rendered = str(_render_prep_sets_card(prep_result, sequencing_result))

    assert "Sequencing stock needs attention." in rendered
    assert "index-planner-side-section--warn" in rendered
    assert "index-planner-row--warn" in rendered


def test_render_prep_sets_card_flags_unmatched_sequencing_stock():
    prep_result = ActivePrepSetsResult(
        success=True,
        prep_sets=[],
        warnings=[],
        message="No active or pending prep sets were found.",
    )
    sequencing_result = make_sequencing_result(
        SequencingStockSummaryRow(item="MiSeq v3", kit_count=2, unmatched_count=1),
        SequencingStockSummaryRow(item="PhiX Control v3", kit_count=2, unmatched_count=None),
    )

    rendered = str(_render_prep_sets_card(prep_result, sequencing_result))

    assert "Sequencing stock needs attention." in rendered
    assert "index-planner-side-section--warn" in rendered
    assert "index-planner-row--warn" in rendered
    assert '<td class="index-planner-cell">MiSeq v3</td>' in rendered
    assert '<td class="index-planner-cell index-planner-cell--number index-planner-cell--issue">1</td>' in rendered


def test_render_prep_sets_card_flags_expiry_attention():
    prep_result = ActivePrepSetsResult(
        success=True,
        prep_sets=[
            make_prep_set(
                sequence_number=27,
                expiry_dates_by_type={
                    PREP_REAGENT_TYPES[0]: "2026-03-20",
                    PREP_REAGENT_TYPES[1]: "2026-05-20",
                    PREP_REAGENT_TYPES[2]: "2026-05-20",
                },
            )
        ],
        warnings=[],
        message="Loaded prep sets.",
    )

    rendered = str(
        _render_prep_sets_card(
            prep_result,
            make_sequencing_result(),
            today=date(2026, 3, 16),
        )
    )

    assert "Expiry dates need attention." in rendered
    assert "Highlighted prep sets need attention." not in rendered


def test_build_sequencing_stock_summary_rows_keeps_unknown_summary_but_does_not_pair_different_names():
    rows = _build_sequencing_stock_summary_rows(
        [
            make_sequencing_lot("MiSeq Reagent Kit (Box 1 of 2)", name="Dummy lot"),
            make_sequencing_lot("MiSeq Reagent Kit (Box 2 of 2)", name="dummy kit"),
        ]
    )

    unknown_row = next(row for row in rows if row.item == "MiSeq Unknown")

    assert unknown_row.kit_count == 0
    assert unknown_row.unmatched_count == 2


def test_sequencing_warning_items_include_unknown_lot_details():
    unknown_lots = [
        make_sequencing_lot("MiSeq Reagent Kit (Box 1 of 2)", name="Dummy lot"),
        make_sequencing_lot("MiSeq Reagent Kit (Box 2 of 2)", name="dummy kit"),
    ]
    warnings = _sequencing_warning_items(
        make_sequencing_result(
            SequencingStockSummaryRow(item="MiSeq Unknown", kit_count=0, unmatched_count=2),
            SequencingStockSummaryRow(item="PhiX Control v3", kit_count=2, unmatched_count=None),
            lots=unknown_lots,
        )
    )

    assert warnings == [
        "Unknown sequencing stock reagent: Dummy lot (MiSeq Reagent Kit (Box 1 of 2))",
        "Unknown sequencing stock reagent: dummy kit (MiSeq Reagent Kit (Box 2 of 2))",
    ]


def test_sequencing_warning_items_include_unmatched_boxes():
    warnings = _sequencing_warning_items(
        make_sequencing_result(
            SequencingStockSummaryRow(item="MiSeq v3", kit_count=2, unmatched_count=1),
            SequencingStockSummaryRow(item="PhiX Control v3", kit_count=2, unmatched_count=None),
        )
    )

    assert warnings == ["Unmatched sequencing stock boxes: MiSeq v3 (1)"]


def test_planner_expiry_warning_items_include_prep_and_sequencing_details():
    today = date(2026, 3, 16)
    prep_result = ActivePrepSetsResult(
        success=True,
        prep_sets=[
            make_prep_set(
                sequence_number=27,
                expiry_dates_by_type={
                    PREP_REAGENT_TYPES[0]: "2026-03-20",
                    PREP_REAGENT_TYPES[1]: "2026-03-25",
                    PREP_REAGENT_TYPES[2]: "2026-05-20",
                },
            )
        ],
        warnings=[],
        message="Loaded prep sets.",
    )
    sequencing_result = make_sequencing_result(
        SequencingStockSummaryRow(item="MiSeq v3", kit_count=1, unmatched_count=0),
        lots=[
            make_sequencing_lot(
                "MiSeq Reagent Kit (Box 1 of 2)",
                name="RGT12345678 v3",
                expiry_date="2026-04-02",
                miseq_kit_type="v3",
            )
        ],
    )

    warnings = _planner_expiry_warning_items(prep_result, sequencing_result, today=today)

    assert warnings == [
        "Prep set #27 expiry attention: IPB 2026-03-20, PCR 2026-03-25",
        "Sequencing expiry attention: MiSeq v3 | RGT12345678 v3 | 2026-04-02",
    ]


def test_planner_warning_items_include_expiry_attention():
    today = date(2026, 3, 16)
    prep_result = ActivePrepSetsResult(
        success=True,
        prep_sets=[
            make_prep_set(
                sequence_number=27,
                expiry_dates_by_type={PREP_REAGENT_TYPES[0]: "2026-03-20"},
            )
        ],
        warnings=["Prep mismatch"],
        message="Loaded prep sets.",
    )
    sequencing_result = make_sequencing_result(
        SequencingStockSummaryRow(item="MiSeq v3", kit_count=1, unmatched_count=1),
        lots=[
            make_sequencing_lot(
                "MiSeq Reagent Kit (Box 1 of 2)",
                name="RGT12345678 v3",
                expiry_date="2026-04-02",
                miseq_kit_type="v3",
            )
        ],
    )

    warnings = _planner_warning_items(
        ["Index warning"],
        prep_result,
        sequencing_result,
        today=today,
    )

    assert warnings == [
        "Index warning",
        "Prep mismatch",
        "Unmatched sequencing stock boxes: MiSeq v3 (1)",
        "Prep set #27 expiry attention: IPB 2026-03-20",
        "Sequencing expiry attention: MiSeq v3 | RGT12345678 v3 | 2026-04-02",
    ]


def test_planner_expiry_warning_items_ignore_missing_invalid_and_far_dates():
    today = date(2026, 3, 16)
    prep_result = ActivePrepSetsResult(
        success=True,
        prep_sets=[
            make_prep_set(
                expiry_dates_by_type={
                    PREP_REAGENT_TYPES[0]: "",
                    PREP_REAGENT_TYPES[1]: "invalid-date",
                    PREP_REAGENT_TYPES[2]: "2026-05-20",
                },
            )
        ],
        warnings=[],
        message="Loaded prep sets.",
    )
    sequencing_result = make_sequencing_result(
        lots=[
            make_sequencing_lot(
                "PhiX Control v3",
                name="RGT55555555",
                expiry_date="",
            ),
            make_sequencing_lot(
                "MiSeq Reagent Kit (Box 1 of 2)",
                name="RGT12345678 v3",
                expiry_date="invalid-date",
                miseq_kit_type="v3",
            ),
            make_sequencing_lot(
                "MiSeq Reagent Kit (Box 2 of 2)",
                name="RGT87654321 v3",
                expiry_date="2026-05-20",
                miseq_kit_type="v3",
            ),
        ]
    )

    warnings = _planner_expiry_warning_items(prep_result, sequencing_result, today=today)

    assert warnings == []


def test_build_planner_expiry_modal_renders_prep_and_sequencing_tables():
    today = date(2026, 3, 16)
    prep_result = ActivePrepSetsResult(
        success=True,
        prep_sets=[
            make_prep_set(
                sequence_number=27,
                usable_reactions_left=192,
                status="ACTIVE",
                expiry_dates_by_type={
                    PREP_REAGENT_TYPES[0]: "2026-03-20",
                    PREP_REAGENT_TYPES[1]: "2026-04-18",
                    PREP_REAGENT_TYPES[2]: "",
                },
            )
        ],
        warnings=[],
        message="Loaded prep sets.",
    )
    sequencing_result = make_sequencing_result(
        lots=[
            make_sequencing_lot(
                "MiSeq Reagent Kit (Box 1 of 2)",
                name="RGT12345678 v3",
                expiry_date="2026-04-02",
                miseq_kit_type="v3",
            ),
            make_sequencing_lot(
                "PhiX Control v3",
                name="RGT55555555",
                expiry_date="",
            ),
        ]
    )

    rendered = str(_build_planner_expiry_modal(prep_result, sequencing_result, today=today))

    assert "Prep and Sequencing Expiry Dates" in rendered
    assert "Expired and next 30 days are highlighted." in rendered
    assert "IPB Expiry" in rendered
    assert "Earliest" in rendered
    assert "Box" in rendered
    assert "Lot Name" in rendered
    assert "Days Left" in rendered
    assert "#27" in rendered
    assert "Box 1 of 2" in rendered
    assert "RGT12345678 v3" in rendered
    assert "Not set" in rendered
