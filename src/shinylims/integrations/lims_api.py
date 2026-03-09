"""
lims_api.py - Clarity LIMS API functions for reagent lot management
Location: src/shinylims/integrations/lims_api.py
"""

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, UTC
from xml.sax.saxutils import escape as xml_escape
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import requests
from requests.auth import HTTPBasicAuth
from dataclasses import dataclass
from shinylims.config.reagents import INDEX_REAGENT_TYPE, REAGENT_KIT_IDS
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

# Load environment variables
if load_dotenv is not None:
    load_dotenv()


def _safe_base_url_for_logs(base_url: str) -> str:
    """Return a sanitized URL for logs (never includes credentials)."""
    parsed = urlparse((base_url or "").strip())
    if parsed.scheme and parsed.hostname:
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        path = (parsed.path or "").rstrip("/")
        return f"{parsed.scheme}://{host}{path}"
    return (base_url or "").strip()


def _log_lims_event(event: str, **fields: object) -> None:
    """Emit one-line log events that render cleanly in Connect logs."""
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [f"{key}={value}" for key, value in fields.items()]
    payload = " ".join(parts)
    if payload:
        print(f"[reagents-lims] ts={ts} event={event} {payload}")
    else:
        print(f"[reagents-lims] ts={ts} event={event}")


@dataclass
class LIMSConfig:
    """LIMS API configuration."""
    base_url: str
    username: str
    password: str
    
    @classmethod
    def get_credentials(cls):
        """Load LIMS API config from environment variables."""
        return cls(
            base_url=(os.getenv("LIMS_BASE_URL") or "").strip(),
            username=(os.getenv("LIMS_API_USER") or "").strip(),
            password=os.getenv("LIMS_API_PASS") or "",
        )

# Reagent kit URIs - these map our reagent types to LIMS kit URIs
def get_reagent_kit_uris(base_url: str) -> dict:
    """Get reagent kit URI mapping for a given base URL."""
    return {
        reagent_type: f"{base_url}/reagentkits/{kit_id}"
        for reagent_type, kit_id in REAGENT_KIT_IDS.items()
    }


@dataclass
class ReagentLotResult:
    """Result of a reagent lot creation attempt."""
    success: bool
    lims_id: str | None
    message: str
    name: str


@dataclass
class PrepSequenceStatus:
    """Latest Illumina DNA Prep sequence status."""
    success: bool
    latest_complete_sequence: int | None
    message: str
    latest_by_reagent_type: dict[str, int | None]


@dataclass
class IndexSequenceStatus:
    """Latest IDT index sequence status."""
    success: bool
    latest_sequence: int | None
    message: str


@dataclass
class ActiveReagentOverviewResult:
    """Result for active reagent overview fetch."""
    success: bool
    rows: list[dict[str, str]]
    message: str


@dataclass
class ReagentLotSnapshotEntry:
    """Normalized reagent-lot fields used for sequence checks."""
    lot_uri: str
    name: str
    reagent_kit_uri: str
    status: str


@dataclass
class ReagentLotSnapshotResult:
    """Result of one shared reagent-lot snapshot fetch."""
    success: bool
    lots: list[ReagentLotSnapshotEntry]
    message: str


@dataclass
class ReagentSequenceStatuses:
    """Combined prep and index sequence statuses from one LIMS snapshot."""
    prep: PrepSequenceStatus
    index: IndexSequenceStatus


def _local_name(tag: str) -> str:
    """Return XML local tag name without namespace."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find_child(element: ET.Element, child_name: str) -> ET.Element | None:
    """Find first direct child by local tag name."""
    for child in element:
        if _local_name(child.tag) == child_name:
            return child
    return None


def _find_descendant(element: ET.Element, child_name: str) -> ET.Element | None:
    """Find first descendant by local tag name."""
    for child in element.iter():
        if child is element:
            continue
        if _local_name(child.tag) == child_name:
            return child
    return None


def _extract_reagentkit_id(uri: str | None) -> str | None:
    """Extract reagent kit numeric ID from a URI."""
    if not uri:
        return None
    match = re.search(r"/reagentkits/(\d+)", uri)
    return match.group(1) if match else None


def _extract_reagentlot_sort_key(uri: str | None) -> tuple[int, int] | None:
    """Extract a sortable reagent-lot ID tuple from a reagent-lot URI."""
    if not uri:
        return None
    match = re.search(r"/reagentlots/(\d+)(?:-(\d+))?", uri)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2)) if match.group(2) is not None else -1
    return (major, minor)


def _select_recent_lot_candidates(
    detail_candidates: list[str],
    max_detail_fetches: int,
) -> tuple[list[str], int]:
    """Return up to max_detail_fetches lot URIs, preferring the highest lot IDs."""
    sorted_candidates = sorted(
        detail_candidates,
        key=lambda uri: (
            _extract_reagentlot_sort_key(uri) is not None,
            _extract_reagentlot_sort_key(uri) or (-1, -1),
        ),
        reverse=True,
    )
    return sorted_candidates[:max_detail_fetches], len(sorted_candidates)


def _parse_lot_name_and_kit_from_xml(xml_content: bytes) -> tuple[str, str, str]:
    """Parse lot name, reagent-kit URI, and status from a reagent lot XML payload."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return "", "", ""

    name = ""
    reagent_kit_uri = ""
    status = ""

    name_child = _find_child(root, "name")
    if name_child is None:
        name_child = _find_descendant(root, "name")
    if name_child is not None and name_child.text:
        name = name_child.text.strip()
    elif root.attrib.get("name"):
        name = root.attrib["name"].strip()

    kit_child = _find_child(root, "reagent-kit")
    if kit_child is None:
        kit_child = _find_descendant(root, "reagent-kit")
    if kit_child is not None:
        reagent_kit_uri = (kit_child.attrib.get("uri") or "").strip()
    elif root.attrib.get("reagent-kit"):
        reagent_kit_uri = str(root.attrib.get("reagent-kit") or "").strip()
    if not reagent_kit_uri:
        for element in root.iter():
            for attr_name, attr_value in element.attrib.items():
                if "reagent" in attr_name and "kit" in attr_name and "/reagentkits/" in str(attr_value):
                    reagent_kit_uri = str(attr_value).strip()
                    break
            if reagent_kit_uri:
                break

    status_child = _find_child(root, "status")
    if status_child is None:
        status_child = _find_descendant(root, "status")
    if status_child is not None and status_child.text:
        status = status_child.text.strip()
    elif root.attrib.get("status"):
        status = str(root.attrib.get("status") or "").strip()

    return name, reagent_kit_uri, status


def _parse_lot_fields_from_xml(xml_content: bytes) -> dict[str, str]:
    """Parse common lot fields from a reagent lot XML payload."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return {}

    def child_text(child_name: str) -> str:
        child = _find_child(root, child_name)
        if child is None:
            child = _find_descendant(root, child_name)
        if child is not None and child.text:
            return child.text.strip()
        return str(root.attrib.get(child_name, "") or "").strip()

    kit_uri = ""
    kit_child = _find_child(root, "reagent-kit")
    if kit_child is None:
        kit_child = _find_descendant(root, "reagent-kit")
    if kit_child is not None:
        kit_uri = (kit_child.attrib.get("uri") or "").strip()
    elif root.attrib.get("reagent-kit"):
        kit_uri = str(root.attrib.get("reagent-kit") or "").strip()
    if not kit_uri:
        for element in root.iter():
            for attr_name, attr_value in element.attrib.items():
                if "reagent" in attr_name and "kit" in attr_name and "/reagentkits/" in str(attr_value):
                    kit_uri = str(attr_value).strip()
                    break
            if kit_uri:
                break

    return {
        "name": child_text("name"),
        "lot_number": child_text("lot-number"),
        "expiry_date": child_text("expiry-date"),
        "status": child_text("status"),
        "storage_location": child_text("storage-location"),
        "reagent_kit_uri": kit_uri,
    }


def _fetch_lot_detail(
    lot_uri: str,
    username: str,
    password: str,
    timeout: int = 5
) -> tuple[str, str, str, str]:
    """Fetch lot detail endpoint and return (lot_uri, name, reagent_kit_uri, status)."""
    try:
        detail_resp = requests.get(
            lot_uri,
            auth=HTTPBasicAuth(username, password),
            headers={"Accept": "application/xml"},
            timeout=timeout
        )
        if detail_resp.status_code != 200:
            return lot_uri, "", "", ""
        name, reagent_kit_uri, status = _parse_lot_name_and_kit_from_xml(detail_resp.content)
        return lot_uri, name, reagent_kit_uri, status
    except requests.exceptions.RequestException:
        return lot_uri, "", "", ""


def _fetch_lot_detail_fields(
    lot_uri: str,
    username: str,
    password: str,
    timeout: int = 5
) -> tuple[str, dict[str, str]]:
    """Fetch lot detail endpoint and return parsed lot fields."""
    try:
        detail_resp = requests.get(
            lot_uri,
            auth=HTTPBasicAuth(username, password),
            headers={"Accept": "application/xml"},
            timeout=timeout
        )
        if detail_resp.status_code != 200:
            return lot_uri, {}
        return lot_uri, _parse_lot_fields_from_xml(detail_resp.content)
    except requests.exceptions.RequestException:
        return lot_uri, {}


def _extract_lot_snapshot_entry(element: ET.Element) -> ReagentLotSnapshotEntry:
    """Extract normalized lot fields from a reagent-lot list element."""
    name = ""
    reagent_kit_uri = ""
    status = ""
    lot_uri = (element.attrib.get("uri") or "").strip()

    name_child = _find_child(element, "name")
    if name_child is not None and name_child.text:
        name = name_child.text.strip()
    elif element.attrib.get("name"):
        name = element.attrib["name"].strip()

    kit_child = _find_child(element, "reagent-kit")
    if kit_child is not None:
        reagent_kit_uri = (kit_child.attrib.get("uri") or "").strip()
    else:
        for attr_name, attr_value in element.attrib.items():
            if "reagent" in attr_name and "kit" in attr_name and "/reagentkits/" in str(attr_value):
                reagent_kit_uri = str(attr_value).strip()
                break
        if not reagent_kit_uri:
            for child in element.iter():
                if _local_name(child.tag) == "reagent-kit":
                    reagent_kit_uri = (child.attrib.get("uri") or "").strip()
                    if reagent_kit_uri:
                        break

    status_child = _find_child(element, "status")
    if status_child is not None and status_child.text:
        status = status_child.text.strip()
    elif element.attrib.get("status"):
        status = str(element.attrib.get("status") or "").strip()

    return ReagentLotSnapshotEntry(
        lot_uri=lot_uri,
        name=name,
        reagent_kit_uri=reagent_kit_uri,
        status=status,
    )


def _fetch_reagent_lot_snapshot(
    config: LIMSConfig,
    max_detail_fetches: int = 250,
) -> ReagentLotSnapshotResult:
    """Fetch one shared reagent-lot snapshot for sequence checks."""
    _log_lims_event(
        "reagent_lot_snapshot_start",
        endpoint=f"{_safe_base_url_for_logs(config.base_url)}/reagentlots",
        max_detail_fetches=max_detail_fetches,
    )

    try:
        response = requests.get(
            f"{config.base_url}/reagentlots",
            auth=HTTPBasicAuth(config.username, config.password),
            headers={"Accept": "application/xml"},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        return ReagentLotSnapshotResult(
            success=False,
            lots=[],
            message=f"Connection error while reading reagent lots: {str(e)}",
        )

    if response.status_code != 200:
        return ReagentLotSnapshotResult(
            success=False,
            lots=[],
            message=f"Unable to read reagent lots (HTTP {response.status_code})",
        )

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        return ReagentLotSnapshotResult(
            success=False,
            lots=[],
            message=f"Could not parse reagent lots XML: {str(e)}",
        )

    lots: list[ReagentLotSnapshotEntry] = []
    detail_candidates: list[str] = []
    detail_seen: set[str] = set()

    for element in root.iter():
        if _local_name(element.tag) not in {"reagent-lot", "reagentlot"}:
            continue

        entry = _extract_lot_snapshot_entry(element)
        if entry.name and entry.reagent_kit_uri:
            lots.append(entry)
            continue
        if entry.lot_uri and entry.lot_uri not in detail_seen:
            detail_candidates.append(entry.lot_uri)
            detail_seen.add(entry.lot_uri)

    limited_candidates, total_candidates = _select_recent_lot_candidates(
        detail_candidates,
        max_detail_fetches,
    )
    if total_candidates > max_detail_fetches:
        _log_lims_event(
            "reagent_lot_snapshot_candidates_limited",
            limit=max_detail_fetches,
            total_candidates=total_candidates,
            selection="highest_reagentlot_ids",
        )

    if limited_candidates:
        max_workers = min(16, len(limited_candidates))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    _fetch_lot_detail,
                    lot_uri,
                    config.username,
                    config.password,
                    5,
                )
                for lot_uri in limited_candidates
            ]
            for future in as_completed(futures):
                lot_uri, name, reagent_kit_uri, status = future.result()
                if not name or not reagent_kit_uri:
                    continue
                lots.append(
                    ReagentLotSnapshotEntry(
                        lot_uri=lot_uri,
                        name=name,
                        reagent_kit_uri=reagent_kit_uri,
                        status=status,
                    )
                )

    return ReagentLotSnapshotResult(
        success=True,
        lots=lots,
        message="Loaded reagent lot snapshot.",
    )


def _compute_prep_sequence_status_from_lots(
    lots: list[ReagentLotSnapshotEntry],
    prep_reagent_types: list[str],
    base_url: str,
) -> PrepSequenceStatus:
    """Compute prep sequence status from a shared lot snapshot."""
    kit_uris = get_reagent_kit_uris(base_url)
    prep_kit_uris = {reagent_type: kit_uris.get(reagent_type) for reagent_type in prep_reagent_types}
    latest_by_type = {rt: None for rt in prep_reagent_types}
    missing_types = [rt for rt, uri in prep_kit_uris.items() if not uri]
    if missing_types:
        return PrepSequenceStatus(
            success=False,
            latest_complete_sequence=None,
            message=f"Missing reagent kit URI mapping for: {', '.join(missing_types)}",
            latest_by_reagent_type=latest_by_type,
        )

    seq_pattern = re.compile(r"#(\d+)\s*\(192\)")
    prep_counted_statuses = {"ACTIVE", "PENDING"}
    kit_id_to_type = {
        _extract_reagentkit_id(uri): reagent_type
        for reagent_type, uri in prep_kit_uris.items()
        if _extract_reagentkit_id(uri)
    }
    outcome_counts = {
        "matched": 0,
        "status_filtered": 0,
        "unknown_kit": 0,
        "name_pattern_miss": 0,
    }

    for lot in lots:
        status = (lot.status or "").upper()
        if status and status not in prep_counted_statuses:
            outcome_counts["status_filtered"] += 1
            continue

        reagent_kit_id = _extract_reagentkit_id(lot.reagent_kit_uri)
        reagent_type = kit_id_to_type.get(reagent_kit_id or "")
        if not reagent_type:
            outcome_counts["unknown_kit"] += 1
            continue

        match = seq_pattern.search(lot.name)
        if not match:
            outcome_counts["name_pattern_miss"] += 1
            continue

        seq_num = int(match.group(1))
        outcome_counts["matched"] += 1
        current_max = latest_by_type[reagent_type]
        if current_max is None or seq_num > current_max:
            latest_by_type[reagent_type] = seq_num

    missing_sequences = [rt for rt, seq in latest_by_type.items() if seq is None]
    if missing_sequences:
        print(f"[prep-check] Outcome counts: {outcome_counts}")
        print(f"[prep-check] Latest sequence by type: {latest_by_type}")
        print(f"[prep-check] Missing sequences for: {missing_sequences}")
        return PrepSequenceStatus(
            success=False,
            latest_complete_sequence=None,
            message=(
                "Could not determine latest sequence for: "
                + ", ".join(missing_sequences)
                + ". Ensure reagent lots use names like '#NN (192)'."
            ),
            latest_by_reagent_type=latest_by_type,
        )

    unique_latest = sorted(set(seq for seq in latest_by_type.values() if seq is not None))
    if len(unique_latest) != 1:
        print(f"[prep-check] Outcome counts: {outcome_counts}")
        print(f"[prep-check] Latest sequence by type: {latest_by_type}")
        print(f"[prep-check] Mismatch detected. unique_latest={unique_latest}")
        mismatch = ", ".join(f"{rt}: #{seq}" for rt, seq in latest_by_type.items())
        return PrepSequenceStatus(
            success=False,
            latest_complete_sequence=None,
            message=(
                "Prep reagent set is incomplete/misaligned. Latest numbers are "
                f"{mismatch}. Clean up Clarity LIMS so all three prep reagents "
                "share the same latest number before submitting new lots."
            ),
            latest_by_reagent_type=latest_by_type,
        )

    latest_complete = unique_latest[0]
    print(f"[prep-check] Latest sequence by type: {latest_by_type}")
    print(f"[prep-check] Success. latest_complete_sequence={latest_complete}")
    return PrepSequenceStatus(
        success=True,
        latest_complete_sequence=latest_complete,
        message=f"Latest complete prep set is #{latest_complete}",
        latest_by_reagent_type=latest_by_type,
    )


def _compute_index_sequence_status_from_lots(
    lots: list[ReagentLotSnapshotEntry],
    base_url: str,
) -> IndexSequenceStatus:
    """Compute index sequence status from a shared lot snapshot."""
    latest_sequence = None
    index_kit_uri = get_reagent_kit_uris(base_url).get(INDEX_REAGENT_TYPE)
    index_kit_id = _extract_reagentkit_id(index_kit_uri)
    if not index_kit_id:
        return IndexSequenceStatus(
            success=False,
            latest_sequence=None,
            message=f"Missing reagent kit URI mapping for index kit: {INDEX_REAGENT_TYPE}.",
        )

    seq_pattern = re.compile(r"#(\d+)\s*\(192\)")
    counted_statuses = {"ACTIVE", "PENDING"}
    outcome_counts = {
        "matched": 0,
        "status_filtered": 0,
        "unknown_kit": 0,
        "name_pattern_miss": 0,
    }

    for lot in lots:
        status = (lot.status or "").upper()
        if status and status not in counted_statuses:
            outcome_counts["status_filtered"] += 1
            continue

        kit_id = _extract_reagentkit_id(lot.reagent_kit_uri)
        if kit_id != index_kit_id:
            outcome_counts["unknown_kit"] += 1
            continue

        match = seq_pattern.search(lot.name or "")
        if not match:
            outcome_counts["name_pattern_miss"] += 1
            continue

        seq_num = int(match.group(1))
        outcome_counts["matched"] += 1
        if latest_sequence is None or seq_num > latest_sequence:
            latest_sequence = seq_num

    if latest_sequence is None:
        _log_lims_event("index_sequence_outcomes", **outcome_counts)
        return IndexSequenceStatus(
            success=False,
            latest_sequence=None,
            message="Could not determine latest index sequence from ACTIVE or PENDING IDT index lots.",
        )

    return IndexSequenceStatus(
        success=True,
        latest_sequence=latest_sequence,
        message=f"Loaded latest index number #{latest_sequence} from LIMS.",
    )


def get_reagent_sequence_statuses(
    config: LIMSConfig,
    prep_reagent_types: list[str],
    max_detail_fetches: int = 250,
) -> ReagentSequenceStatuses:
    """Return prep and index sequence statuses from one shared LIMS lot snapshot."""
    snapshot = _fetch_reagent_lot_snapshot(config, max_detail_fetches=max_detail_fetches)
    if not snapshot.success:
        failure_message = snapshot.message
        return ReagentSequenceStatuses(
            prep=PrepSequenceStatus(
                success=False,
                latest_complete_sequence=None,
                message=failure_message,
                latest_by_reagent_type={rt: None for rt in prep_reagent_types},
            ),
            index=IndexSequenceStatus(
                success=False,
                latest_sequence=None,
                message=failure_message,
            ),
        )

    if prep_reagent_types:
        prep_status = _compute_prep_sequence_status_from_lots(
            snapshot.lots,
            prep_reagent_types,
            config.base_url,
        )
    else:
        prep_status = PrepSequenceStatus(
            success=False,
            latest_complete_sequence=None,
            message="Prep reagent types not requested.",
            latest_by_reagent_type={},
        )

    return ReagentSequenceStatuses(
        prep=prep_status,
        index=_compute_index_sequence_status_from_lots(
            snapshot.lots,
            config.base_url,
        ),
    )


def get_latest_prep_sequence_status(
    config: LIMSConfig,
    prep_reagent_types: list[str],
    max_detail_fetches: int = 250
) -> PrepSequenceStatus:
    """Get latest complete sequence number for Illumina DNA Prep reagent sets."""
    return get_reagent_sequence_statuses(
        config,
        prep_reagent_types,
        max_detail_fetches=max_detail_fetches,
    ).prep


def get_latest_index_sequence_status(
    config: LIMSConfig,
    max_detail_fetches: int = 250
) -> IndexSequenceStatus:
    """Get latest shared IDT index sequence number."""
    return get_reagent_sequence_statuses(
        config,
        prep_reagent_types=[],
        max_detail_fetches=max_detail_fetches,
    ).index


def get_active_reagent_overview(
    config: LIMSConfig,
    max_detail_fetches: int = 400
) -> ActiveReagentOverviewResult:
    """Fetch overview rows for ACTIVE reagent lots."""
    try:
        response = requests.get(
            f"{config.base_url}/reagentlots",
            auth=HTTPBasicAuth(config.username, config.password),
            headers={"Accept": "application/xml"},
            timeout=30
        )
    except requests.exceptions.RequestException as e:
        return ActiveReagentOverviewResult(
            success=False,
            rows=[],
            message=f"Connection error while reading reagent lots: {str(e)}",
        )

    if response.status_code != 200:
        return ActiveReagentOverviewResult(
            success=False,
            rows=[],
            message=f"Unable to read reagent lots (HTTP {response.status_code})",
        )

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        return ActiveReagentOverviewResult(
            success=False,
            rows=[],
            message=f"Could not parse reagent lots XML: {str(e)}",
        )

    kit_uri_to_type = get_reagent_kit_uris(config.base_url)
    kit_id_to_type = {
        _extract_reagentkit_id(uri): reagent_type
        for reagent_type, uri in kit_uri_to_type.items()
        if _extract_reagentkit_id(uri)
    }

    rows: list[dict[str, str]] = []
    detail_candidates: list[str] = []
    detail_seen: set[str] = set()

    def append_if_active(fields: dict[str, str]):
        if not fields:
            return
        status = (fields.get("status") or "").upper()
        if status != "ACTIVE":
            return

        kit_uri = fields.get("reagent_kit_uri") or ""
        kit_id = _extract_reagentkit_id(kit_uri)
        reagent_type = kit_id_to_type.get(kit_id, f"Unknown kit {kit_id}" if kit_id else "Unknown")

        rows.append({
            "Reagent Type": reagent_type,
            "Internal Name": fields.get("name") or "",
            "Lot Number": fields.get("lot_number") or "",
            "Expiry Date": fields.get("expiry_date") or "",
            "Status": fields.get("status") or "",
            "Storage": fields.get("storage_location") or "",
        })

    for element in root.iter():
        if _local_name(element.tag) not in {"reagent-lot", "reagentlot"}:
            continue

        lot_uri = (element.attrib.get("uri") or "").strip()
        name = ""
        lot_number = ""
        expiry_date = ""
        status = ""
        reagent_kit_uri = ""

        name_child = _find_child(element, "name")
        if name_child is not None and name_child.text:
            name = name_child.text.strip()
        elif element.attrib.get("name"):
            name = str(element.attrib.get("name") or "").strip()

        lot_number_child = _find_child(element, "lot-number")
        if lot_number_child is not None and lot_number_child.text:
            lot_number = lot_number_child.text.strip()

        expiry_child = _find_child(element, "expiry-date")
        if expiry_child is not None and expiry_child.text:
            expiry_date = expiry_child.text.strip()

        status_child = _find_child(element, "status")
        if status_child is not None and status_child.text:
            status = status_child.text.strip()
        elif element.attrib.get("status"):
            status = str(element.attrib.get("status") or "").strip()

        kit_child = _find_child(element, "reagent-kit")
        if kit_child is not None:
            reagent_kit_uri = (kit_child.attrib.get("uri") or "").strip()

        if (not name or not lot_number or not reagent_kit_uri) and lot_uri:
            if lot_uri not in detail_seen:
                detail_candidates.append(lot_uri)
                detail_seen.add(lot_uri)
            continue

        append_if_active({
            "name": name,
            "lot_number": lot_number,
            "expiry_date": expiry_date,
            "status": status,
            "storage_location": "",
            "reagent_kit_uri": reagent_kit_uri,
        })

    limited_candidates, total_candidates = _select_recent_lot_candidates(
        detail_candidates,
        max_detail_fetches,
    )
    if total_candidates > max_detail_fetches:
        _log_lims_event(
            "active_reagent_overview_candidates_limited",
            limit=max_detail_fetches,
            total_candidates=total_candidates,
            selection="highest_reagentlot_ids",
        )
    if limited_candidates:
        max_workers = min(16, len(limited_candidates))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    _fetch_lot_detail_fields,
                    lot_uri,
                    config.username,
                    config.password,
                    5
                )
                for lot_uri in limited_candidates
            ]
            for future in as_completed(futures):
                _, fields = future.result()
                append_if_active(fields)

    rows.sort(key=lambda r: (r.get("Reagent Type", ""), r.get("Internal Name", "")))
    return ActiveReagentOverviewResult(
        success=True,
        rows=rows,
        message=f"Loaded {len(rows)} active reagent lots.",
    )


def create_reagent_lot(
    config: LIMSConfig,
    name: str,
    lot_number: str,
    reagent_type: str,
    expiry_date: str,
    storage_location: str = "",
    notes: str = "",
    status: str = "ACTIVE",
) -> ReagentLotResult:
    """
    Create a new reagent lot in Clarity LIMS.
    
    Args:
        config: LIMS API configuration
        name: Internal name (e.g., "#29 (192)")
        lot_number: Manufacturer lot number
        reagent_type: One of the keys from REAGENT_KIT_URIS
        expiry_date: Format YYYY-MM-DD
        storage_location: Optional storage location
        notes: Optional notes
        status: LIMS lot status, e.g. ACTIVE or PENDING
    
    Returns:
        ReagentLotResult with success status and details
    """
    
    kit_uris = get_reagent_kit_uris(config.base_url)
    reagent_kit_uri = kit_uris.get(reagent_type)
    
    if not reagent_kit_uri:
        return ReagentLotResult(
            success=False,
            lims_id=None,
            message=f"Unknown reagent type: {reagent_type}",
            name=name
        )
    
    url = f"{config.base_url}/reagentlots"

    safe_name = xml_escape(str(name or ""))
    safe_lot_number = xml_escape(str(lot_number or ""))
    safe_expiry_date = xml_escape(str(expiry_date or ""))
    safe_storage_location = xml_escape(str(storage_location or ""))
    safe_notes = xml_escape(str(notes or ""))
    safe_status = xml_escape(str(status or "ACTIVE"))
    
    xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<lot:reagent-lot xmlns:lot="http://genologics.com/ri/reagentlot">
    <reagent-kit uri="{reagent_kit_uri}"/>
    <name>{safe_name}</name>
    <lot-number>{safe_lot_number}</lot-number>
    <expiry-date>{safe_expiry_date}</expiry-date>
    <storage-location>{safe_storage_location}</storage-location>
    <notes>{safe_notes}</notes>
    <status>{safe_status}</status>
</lot:reagent-lot>"""
    
    try:
        response = requests.post(
            url,
            auth=HTTPBasicAuth(config.username, config.password),
            headers={
                "Content-Type": "application/xml",
                "Accept": "application/xml"
            },
            data=xml_payload.encode('utf-8'),
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            # Extract LIMS ID from response
            # Response contains: limsid="124-902"
            import re
            match = re.search(r'limsid="([^"]+)"', response.text)
            lims_id = match.group(1) if match else "unknown"
            
            return ReagentLotResult(
                success=True,
                lims_id=lims_id,
                message=f"Created successfully",
                name=name
            )
        else:
            # Extract error message from XML response
            import re
            match = re.search(r'<message>([^<]+)</message>', response.text)
            error_msg = match.group(1) if match else response.text[:200]
            
            return ReagentLotResult(
                success=False,
                lims_id=None,
                message=f"API error ({response.status_code}): {error_msg}",
                name=name
            )
            
    except requests.exceptions.RequestException as e:
        return ReagentLotResult(
            success=False,
            lims_id=None,
            message=f"Connection error: {str(e)}",
            name=name
        )


def test_connection(config: LIMSConfig) -> tuple[bool, str]:
    """
    Test API connectivity.
    
    Returns:
        Tuple of (success, message)
    """
    endpoint = f"{config.base_url}/reagentkits"
    _log_lims_event(
        "test_connection_start",
        endpoint=_safe_base_url_for_logs(endpoint),
        username_set=bool((config.username or "").strip()),
        password_set=bool(config.password),
    )

    try:
        response = requests.get(
            endpoint,
            auth=HTTPBasicAuth(config.username, config.password),
            headers={"Accept": "application/xml"},
            timeout=10
        )
        
        if response.status_code == 200:
            _log_lims_event(
                "test_connection_result",
                outcome="success",
                status=response.status_code,
            )
            return True, "Connection successful"
        else:
            response_excerpt = re.sub(r"\s+", " ", (response.text or "")).strip()[:160]
            _log_lims_event(
                "test_connection_result",
                outcome="failed",
                status=response.status_code,
                response_excerpt=response_excerpt or "-",
            )
            return False, f"HTTP {response.status_code}: {response_excerpt or 'Connection failed'}"
            
    except requests.exceptions.RequestException as e:
        _log_lims_event(
            "test_connection_result",
            outcome="error",
            error_type=type(e).__name__,
            error_message=str(e),
        )
        return False, f"Connection failed: {str(e)}"
