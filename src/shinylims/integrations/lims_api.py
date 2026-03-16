"""
lims_api.py - Clarity LIMS API functions for reagent lot management
Location: src/shinylims/integrations/lims_api.py
"""

import os
import re
import threading
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, UTC
from time import perf_counter
from xml.sax.saxutils import escape as xml_escape
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import requests
from requests.auth import HTTPBasicAuth
from requests.adapters import HTTPAdapter
from dataclasses import dataclass
from shinylims.config.index_plate_maps import (
    INDEX_NOTE_PREFIX_PATTERNS,
    INDEX_NOTE_SEGMENT_PATTERN,
    INDEX_NOTE_WELL_PATTERN,
    INDEX_SET_PATTERNS,
    PLATE_COLUMNS,
    SUPPORTED_INDEX_SET_LETTERS,
    normalize_well,
    wells_for_column,
)
from shinylims.config.reagents import (
    INDEX_REAGENT_TYPE,
    PREP_REAGENT_TYPES,
    REAGENT_KIT_IDS,
    REAGENT_TYPES,
    SCANNABLE_REAGENTS,
)
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


def _get_lims_session(
    *,
    base_url: str = "",
    username: str = "",
    password: str = "",
) -> requests.Session:
    """Return a thread-local pooled session for repeated LIMS requests."""
    now = perf_counter()
    session_cache = getattr(_LIMS_SESSION_LOCAL, "session_cache", None)
    if session_cache is None:
        session_cache = {}
        _LIMS_SESSION_LOCAL.session_cache = session_cache
    else:
        expired_keys = [
            cache_key
            for cache_key, cache_entry in session_cache.items()
            if now - cache_entry.last_used_at > LIMS_SESSION_IDLE_TTL_SECONDS
        ]
        for cache_key in expired_keys:
            cache_entry = session_cache.pop(cache_key, None)
            if cache_entry is not None:
                cache_entry.session.close()

    cache_key = (
        _safe_base_url_for_logs(base_url),
        (username or "").strip(),
        password or "",
    )
    cache_entry = session_cache.get(cache_key)
    if cache_entry is not None:
        cache_entry.last_used_at = now
        return cache_entry.session

    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=LIMS_SESSION_POOL_SIZE,
        pool_maxsize=LIMS_SESSION_POOL_SIZE,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.auth = HTTPBasicAuth((username or "").strip(), password or "")
    session.headers.update({"Accept": "application/xml"})
    session_cache[cache_key] = LimsSessionCacheEntry(
        session=session,
        last_used_at=now,
    )
    return session


def _lims_get(
    url: str,
    *,
    config=None,
    username: str | None = None,
    password: str | None = None,
    **kwargs,
):
    """Execute a pooled GET request against Clarity LIMS."""
    resolved_username = (config.username if config is not None else username) or ""
    resolved_password = (config.password if config is not None else password) or ""
    resolved_base_url = config.base_url if config is not None else ""
    session = _get_lims_session(
        base_url=resolved_base_url,
        username=resolved_username,
        password=resolved_password,
    )
    return session.get(url, **kwargs)


def _lims_post(
    url: str,
    *,
    config=None,
    username: str | None = None,
    password: str | None = None,
    **kwargs,
):
    """Execute a pooled POST request against Clarity LIMS."""
    resolved_username = (config.username if config is not None else username) or ""
    resolved_password = (config.password if config is not None else password) or ""
    resolved_base_url = config.base_url if config is not None else ""
    session = _get_lims_session(
        base_url=resolved_base_url,
        username=resolved_username,
        password=resolved_password,
    )
    return session.post(url, **kwargs)


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
class ActivePrepLot:
    """Normalized active prep reagent lot."""
    lot_uri: str
    reagent_type: str
    name: str
    lot_number: str
    expiry_date: str
    status: str
    sequence_number: int
    reactions_left: int


@dataclass
class PrepSetSummary:
    """One grouped Illumina prep set across the three prep boxes."""
    sequence_number: int
    usable_reactions_left: int
    reactions_by_type: dict[str, int | None]
    lots_by_type: dict[str, ActivePrepLot]
    warnings: list[str]
    is_balanced: bool


@dataclass
class ActivePrepSetsResult:
    """Result of loading grouped active prep sets from Clarity."""
    success: bool
    prep_sets: list[PrepSetSummary]
    warnings: list[str]
    message: str


@dataclass
class SequencingStockLot:
    """Normalized sequencing reagent lot used for manager stock summaries."""
    lot_uri: str
    reagent_type: str
    name: str
    expiry_date: str
    status: str
    miseq_kit_type: str | None


@dataclass
class SequencingStockSummaryRow:
    """One read-only stock summary row for the planner side card."""
    item: str
    kit_count: int
    unmatched_count: int | None


@dataclass
class SequencingStockResult:
    """Result of loading MiSeq/PhiX sequencing stock for the planner."""
    success: bool
    lots: list[SequencingStockLot]
    summary_rows: list[SequencingStockSummaryRow]
    message: str


@dataclass
class ActiveIndexLot:
    """Normalized active index lot with notes and parsed set letter."""
    lot_uri: str
    name: str
    lot_number: str
    expiry_date: str
    status: str
    set_letter: str
    notes: str


@dataclass
class IndexUsageRecord:
    """One parsed well usage entry from an index lot note."""
    lot_name: str
    set_letter: str
    well: str
    source_line: str


@dataclass
class IndexPlateCell:
    """One cell in a rendered 96-well index plate."""
    well: str
    row: str
    column: int
    raw_count: int
    state: str


@dataclass
class IndexPlateMap:
    """Aggregated well usage summary for one active index lot."""
    lot: ActiveIndexLot
    cells: list[IndexPlateCell]
    usage_records: list[IndexUsageRecord]
    warnings: list[str]
    unused_wells: int
    single_use_wells: int
    double_use_wells: int
    conflict_wells: int


@dataclass
class IndexPlateMapsResult:
    """Result of loading active index plate maps from Clarity notes."""
    success: bool
    plate_maps: list[IndexPlateMap]
    pending_lots: list[ActiveIndexLot]
    warnings: list[str]
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


@dataclass
class PlannerReagentLotSnapshotEntry:
    """Normalized planner lot fields shared across prep, sequencing, and index views."""
    lot_uri: str
    reagent_type: str
    name: str
    lot_number: str
    expiry_date: str
    status: str
    notes: str


@dataclass
class PlannerReagentLotSnapshotResult:
    """Result of one shared reagent-lot snapshot for the planner."""
    success: bool
    lots: list[PlannerReagentLotSnapshotEntry]
    warnings: list[str]
    message: str


@dataclass
class IlluminaPlanningDataResult:
    """Planner data derived from one shared reagent-lot snapshot."""
    prep_sets: ActivePrepSetsResult
    sequencing_stock: SequencingStockResult
    plate_maps: IndexPlateMapsResult


@dataclass
class PlannerSnapshotListingScanResult:
    """Intermediate scan result from one planner reagent-lot listing response."""
    lots: list[PlannerReagentLotSnapshotEntry]
    detail_candidates: list[str]
    detail_labels: dict[str, str]
    listed_lot_count: int
    direct_lot_count: int
    index_active_detail_candidates: int
    index_pending_detail_candidates: int


@dataclass
class LimsSessionCacheEntry:
    """One cached pooled LIMS session and its last-use timestamp."""
    session: requests.Session
    last_used_at: float


def _configured_sequencing_reagent_types() -> list[str]:
    """Return the configured read-only sequencing reagent types."""
    return [
        reagent_type
        for reagent_type, reagent_info in REAGENT_TYPES.items()
        if reagent_info.get("naming_group") in {"miseq", "phix"}
    ]


def _configured_miseq_kit_types() -> list[str]:
    """Return configured MiSeq kit subtypes in UI order."""
    ordered_types: list[str] = []
    seen: set[str] = set()
    for item in SCANNABLE_REAGENTS:
        reagent_type = str(item.get("reagent_type") or "")
        if REAGENT_TYPES.get(reagent_type, {}).get("naming_group") != "miseq":
            continue
        kit_type = str(item.get("miseq_kit_type") or "").strip()
        if not kit_type or kit_type in seen:
            continue
        ordered_types.append(kit_type)
        seen.add(kit_type)
    return ordered_types


SEQUENCING_REAGENT_TYPES = _configured_sequencing_reagent_types()
MISEQ_KIT_TYPES = _configured_miseq_kit_types()
PLANNER_REAGENT_TYPES = list(
    dict.fromkeys([*PREP_REAGENT_TYPES, *SEQUENCING_REAGENT_TYPES, INDEX_REAGENT_TYPE])
)
PLANNER_DETAIL_FETCH_MAX_WORKERS = 32
PLANNER_COMBINED_LISTING_FALLBACK_THRESHOLD = 100
LIMS_SESSION_POOL_SIZE = 100
LIMS_SESSION_IDLE_TTL_SECONDS = 900
_LIMS_SESSION_LOCAL = threading.local()
PREP_LOT_NAME_PATTERN = re.compile(r"#\s*(\d+)\b.*?\(\s*(\d+)\s*\)")
PREP_FULL_SET_PATTERN = re.compile(r"#\s*(\d+)\b.*?\(\s*192\s*\)")


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


def _chunked(items: list[str], size: int) -> list[list[str]]:
    """Split a flat list into fixed-size chunks."""
    return [items[index:index + size] for index in range(0, len(items), size)]


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


def _fetch_reagent_lot_listing_roots(
    config: LIMSConfig,
    *,
    kitnames: list[str] | None = None,
) -> tuple[bool, list[ET.Element], str]:
    """Fetch one or more reagent-lot listing roots, optionally filtered by kitname."""
    filter_values = list(dict.fromkeys(kitnames or []))
    if not filter_values:
        filter_values = [None]

    roots: list[ET.Element] = []
    for kitname in filter_values:
        try:
            response = _lims_get(
                f"{config.base_url}/reagentlots",
                config=config,
                params={"kitname": kitname} if kitname else None,
                headers={"Accept": "application/xml"},
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            return (False, [], f"Connection error while reading reagent lots: {str(e)}")

        if response.status_code != 200:
            return (False, [], f"Unable to read reagent lots (HTTP {response.status_code})")

        try:
            roots.append(ET.fromstring(response.content))
        except ET.ParseError as e:
            return (False, [], f"Could not parse reagent lots XML: {str(e)}")

    return (True, roots, "")


def _fetch_reagent_lot_listing_roots_combined(
    config: LIMSConfig,
    *,
    kitnames: list[str] | None = None,
) -> tuple[bool, list[ET.Element], str]:
    """Fetch one reagent-lot listing root using repeated kitname filters."""
    filter_values = list(dict.fromkeys(kitnames or []))

    try:
        response = _lims_get(
            f"{config.base_url}/reagentlots",
            config=config,
            params={"kitname": filter_values} if filter_values else None,
            headers={"Accept": "application/xml"},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        return (False, [], f"Connection error while reading reagent lots: {str(e)}")

    if response.status_code != 200:
        return (False, [], f"Unable to read reagent lots (HTTP {response.status_code})")

    try:
        return (True, [ET.fromstring(response.content)], "")
    except ET.ParseError as e:
        return (False, [], f"Could not parse reagent lots XML: {str(e)}")


def _parse_lot_fields_from_element(root: ET.Element) -> dict[str, str]:
    """Parse common lot fields from one reagent lot XML element."""
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
        "notes": child_text("notes"),
        "reagent_kit_uri": kit_uri,
    }


def _parse_lot_fields_from_xml(xml_content: bytes) -> dict[str, str]:
    """Parse common lot fields from a reagent lot XML payload."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return {}
    return _parse_lot_fields_from_element(root)


def _fetch_lot_detail_fields(
    lot_uri: str,
    username: str,
    password: str,
    timeout: int = 5
) -> tuple[str, dict[str, str]]:
    """Fetch lot detail endpoint and return parsed lot fields."""
    try:
        detail_resp = _lims_get(
            lot_uri,
            username=username,
            password=password,
            headers={"Accept": "application/xml"},
            timeout=timeout
        )
        if detail_resp.status_code != 200:
            return lot_uri, {}
        return lot_uri, _parse_lot_fields_from_xml(detail_resp.content)
    except requests.exceptions.RequestException:
        return lot_uri, {}


def _fetch_lot_detail_fields_batch(
    config: LIMSConfig,
    lot_uris: list[str],
    *,
    timeout: int = 30,
    batch_size: int = 100,
) -> dict[str, dict[str, str]]:
    """Fetch reagent-lot details in Clarity batch/retrieve chunks when supported."""
    if not lot_uris:
        return {}

    batch_uri = f"{config.base_url}/reagentlots/batch/retrieve"
    fields_by_uri: dict[str, dict[str, str]] = {}

    for chunk in _chunked(lot_uris, batch_size):
        root = ET.Element("ri:links", {"xmlns:ri": "http://genologics.com/ri"})
        for lot_uri in chunk:
            ET.SubElement(root, "link", {"uri": lot_uri, "rel": "reagentlots"})
        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)

        try:
            response = _lims_post(
                batch_uri,
                config=config,
                data=payload,
                headers={
                    "Accept": "application/xml",
                    "Content-Type": "application/xml",
                },
                timeout=timeout,
            )
        except requests.exceptions.RequestException as exc:
            _log_lims_event(
                "reagent_lot_batch_retrieve_failed",
                reason="request_exception",
                chunk_size=len(chunk),
                error=exc.__class__.__name__,
            )
            return {}

        if response.status_code != 200:
            _log_lims_event(
                "reagent_lot_batch_retrieve_failed",
                reason="http_status",
                status_code=response.status_code,
                chunk_size=len(chunk),
            )
            return {}

        try:
            response_root = ET.fromstring(response.content)
        except ET.ParseError:
            _log_lims_event(
                "reagent_lot_batch_retrieve_failed",
                reason="parse_error",
                chunk_size=len(chunk),
            )
            return {}

        parsed_count = 0
        for element in response_root.iter():
            if _local_name(element.tag) not in {"reagent-lot", "reagentlot"}:
                continue
            lot_uri = (element.attrib.get("uri") or "").strip()
            if not lot_uri:
                continue
            fields = _parse_lot_fields_from_element(element)
            if fields:
                fields_by_uri[lot_uri] = fields
                parsed_count += 1

        _log_lims_event(
            "reagent_lot_batch_retrieve_chunk",
            requested=len(chunk),
            returned=parsed_count,
        )

    return fields_by_uri


def _resolve_lot_detail_fields(
    config: LIMSConfig,
    lot_uris: list[str],
    *,
    timeout: int = 5,
    max_workers: int | None = None,
    log_context: str | None = None,
) -> dict[str, dict[str, str]]:
    """Resolve reagent-lot detail fields via batch retrieve with per-lot fallback."""
    if not lot_uris:
        return {}

    requested_max_workers = max_workers if max_workers is not None else 16
    unique_lot_uris = list(dict.fromkeys(lot_uris))
    resolve_started_at = perf_counter()
    if log_context:
        _log_lims_event(
            "reagent_lot_detail_resolve_start",
            context=log_context,
            requested=len(unique_lot_uris),
            timeout=timeout,
            max_workers=requested_max_workers,
        )

    batch_started_at = perf_counter()
    fields_by_uri = _fetch_lot_detail_fields_batch(
        config,
        unique_lot_uris,
        timeout=max(timeout, 15),
    )
    batch_elapsed_ms = int((perf_counter() - batch_started_at) * 1000)
    missing_uris = [lot_uri for lot_uri in unique_lot_uris if lot_uri not in fields_by_uri]
    if log_context:
        _log_lims_event(
            "reagent_lot_detail_resolve_batch",
            context=log_context,
            requested=len(unique_lot_uris),
            returned=len(fields_by_uri),
            missing=len(missing_uris),
            elapsed_ms=batch_elapsed_ms,
        )
    if not missing_uris:
        if log_context:
            _log_lims_event(
                "reagent_lot_detail_resolve_complete",
                context=log_context,
                requested=len(unique_lot_uris),
                resolved=len(fields_by_uri),
                missing=0,
                elapsed_ms=int((perf_counter() - resolve_started_at) * 1000),
            )
        return fields_by_uri

    worker_count = max(1, min(requested_max_workers, len(missing_uris)))
    fallback_started_at = perf_counter()
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                _fetch_lot_detail_fields,
                lot_uri,
                config.username,
                config.password,
                timeout,
            )
            for lot_uri in missing_uris
        ]
        for future in as_completed(futures):
            lot_uri, fields = future.result()
            if fields:
                fields_by_uri[lot_uri] = fields
    if log_context:
        _log_lims_event(
            "reagent_lot_detail_resolve_fallback",
            context=log_context,
            requested=len(missing_uris),
            returned=len(fields_by_uri),
            newly_resolved=len(fields_by_uri) - (len(unique_lot_uris) - len(missing_uris)),
            still_missing=len([lot_uri for lot_uri in unique_lot_uris if lot_uri not in fields_by_uri]),
            max_workers=worker_count,
            elapsed_ms=int((perf_counter() - fallback_started_at) * 1000),
        )
        _log_lims_event(
            "reagent_lot_detail_resolve_complete",
            context=log_context,
            requested=len(unique_lot_uris),
            resolved=len(fields_by_uri),
            missing=len([lot_uri for lot_uri in unique_lot_uris if lot_uri not in fields_by_uri]),
            elapsed_ms=int((perf_counter() - resolve_started_at) * 1000),
        )

    return fields_by_uri


def _planner_snapshot_entry_from_fields(
    *,
    lot_uri: str,
    reagent_type: str,
    fields: dict[str, str],
) -> PlannerReagentLotSnapshotEntry:
    """Build one planner snapshot entry from parsed lot fields."""
    return PlannerReagentLotSnapshotEntry(
        lot_uri=lot_uri,
        reagent_type=reagent_type,
        name=(fields.get("name") or "").strip(),
        lot_number=(fields.get("lot_number") or "").strip(),
        expiry_date=(fields.get("expiry_date") or "").strip(),
        status=(fields.get("status") or "").strip(),
        notes=(fields.get("notes") or "").strip(),
    )


def _scan_planner_listing_roots(
    roots: list[ET.Element],
    *,
    relevant_kit_id_to_type: dict[str | None, str],
) -> PlannerSnapshotListingScanResult:
    """Scan planner listing roots into direct snapshot entries and detail candidates."""
    allowed_statuses = {"ACTIVE", "PENDING"}
    lots: list[PlannerReagentLotSnapshotEntry] = []
    seen_lot_uris: set[str] = set()
    detail_candidates: list[str] = []
    detail_seen: set[str] = set()
    detail_labels: dict[str, str] = {}
    listed_lot_count = 0
    direct_lot_count = 0
    index_active_detail_candidates = 0
    index_pending_detail_candidates = 0

    for root in roots:
        for element in root.iter():
            if _local_name(element.tag) not in {"reagent-lot", "reagentlot"}:
                continue

            listed_lot_count += 1
            lot_uri = (element.attrib.get("uri") or "").strip()
            if not lot_uri:
                continue

            fields = _parse_lot_fields_from_element(element)
            status_upper = (fields.get("status") or "").upper()
            if status_upper and status_upper not in allowed_statuses:
                continue

            reagent_kit_id = _extract_reagentkit_id(fields.get("reagent_kit_uri"))
            reagent_type = relevant_kit_id_to_type.get(reagent_kit_id)
            needs_detail = (
                reagent_type is None
                or not (fields.get("name") or "").strip()
                or not status_upper
                or (
                    reagent_type == INDEX_REAGENT_TYPE
                    and status_upper == "ACTIVE"
                    and not (fields.get("notes") or "").strip()
                )
            )

            if needs_detail:
                if lot_uri not in detail_seen:
                    detail_candidates.append(lot_uri)
                    detail_seen.add(lot_uri)
                    detail_labels[lot_uri] = (fields.get("name") or "").strip() or lot_uri
                    if reagent_type == INDEX_REAGENT_TYPE and status_upper == "ACTIVE":
                        index_active_detail_candidates += 1
                    elif reagent_type == INDEX_REAGENT_TYPE and status_upper == "PENDING":
                        index_pending_detail_candidates += 1
                continue

            if reagent_type is None or lot_uri in seen_lot_uris:
                continue

            lots.append(
                _planner_snapshot_entry_from_fields(
                    lot_uri=lot_uri,
                    reagent_type=reagent_type,
                    fields=fields,
                )
            )
            seen_lot_uris.add(lot_uri)
            direct_lot_count += 1

    return PlannerSnapshotListingScanResult(
        lots=lots,
        detail_candidates=detail_candidates,
        detail_labels=detail_labels,
        listed_lot_count=listed_lot_count,
        direct_lot_count=direct_lot_count,
        index_active_detail_candidates=index_active_detail_candidates,
        index_pending_detail_candidates=index_pending_detail_candidates,
    )


def _fetch_planner_reagent_lot_snapshot(
    config: LIMSConfig,
) -> PlannerReagentLotSnapshotResult:
    """Fetch one shared planner reagent-lot snapshot across prep, sequencing, and index stock."""
    if not config.base_url or not config.username or not config.password:
        return PlannerReagentLotSnapshotResult(
            success=False,
            lots=[],
            warnings=[],
            message="Missing LIMS credentials. Set LIMS_BASE_URL, LIMS_API_USER, and LIMS_API_PASS.",
        )

    requested_kitnames = list(PLANNER_REAGENT_TYPES)
    snapshot_started_at = perf_counter()
    listing_started_at = perf_counter()
    ok, roots, message = _fetch_reagent_lot_listing_roots_combined(
        config,
        kitnames=requested_kitnames,
    )
    listing_elapsed_ms = int((perf_counter() - listing_started_at) * 1000)
    if ok:
        _log_lims_event(
            "planner_snapshot_listing_strategy",
            strategy="combined_kitname_filter",
            kitname_count=len(requested_kitnames),
            elapsed_ms=listing_elapsed_ms,
        )
    else:
        _log_lims_event(
            "planner_snapshot_listing_strategy",
            strategy="per_kitname_fallback",
            reason=message,
            kitname_count=len(requested_kitnames),
            combined_elapsed_ms=listing_elapsed_ms,
        )
        listing_started_at = perf_counter()
        ok, roots, message = _fetch_reagent_lot_listing_roots(
            config,
            kitnames=requested_kitnames,
        )
        listing_elapsed_ms = int((perf_counter() - listing_started_at) * 1000)
        if ok:
            _log_lims_event(
                "planner_snapshot_listing_complete",
                strategy="per_kitname_fallback",
                kitname_count=len(requested_kitnames),
                root_count=len(roots),
                elapsed_ms=listing_elapsed_ms,
            )
    if not ok:
        return PlannerReagentLotSnapshotResult(
            success=False,
            lots=[],
            warnings=[],
            message=message,
        )

    kit_uri_to_type = get_reagent_kit_uris(config.base_url)
    relevant_kit_id_to_type = {
        _extract_reagentkit_id(kit_uri_to_type[reagent_type]): reagent_type
        for reagent_type in requested_kitnames
        if kit_uri_to_type.get(reagent_type)
    }
    allowed_statuses = {"ACTIVE", "PENDING"}
    warnings: list[str] = []
    scan_result = _scan_planner_listing_roots(
        roots,
        relevant_kit_id_to_type=relevant_kit_id_to_type,
    )
    selected_listing_strategy = "combined_kitname_filter"

    if (
        len(requested_kitnames) > 1
        and scan_result.direct_lot_count == 0
        and len(scan_result.detail_candidates) >= PLANNER_COMBINED_LISTING_FALLBACK_THRESHOLD
    ):
        retry_started_at = perf_counter()
        retry_ok, retry_roots, retry_message = _fetch_reagent_lot_listing_roots(
            config,
            kitnames=requested_kitnames,
        )
        retry_elapsed_ms = int((perf_counter() - retry_started_at) * 1000)
        if retry_ok:
            retry_scan_result = _scan_planner_listing_roots(
                retry_roots,
                relevant_kit_id_to_type=relevant_kit_id_to_type,
            )
            _log_lims_event(
                "planner_snapshot_listing_compare",
                combined_listed_lots=scan_result.listed_lot_count,
                combined_direct_lots=scan_result.direct_lot_count,
                combined_detail_candidates=len(scan_result.detail_candidates),
                per_kit_listed_lots=retry_scan_result.listed_lot_count,
                per_kit_direct_lots=retry_scan_result.direct_lot_count,
                per_kit_detail_candidates=len(retry_scan_result.detail_candidates),
                elapsed_ms=retry_elapsed_ms,
            )
            if len(retry_scan_result.detail_candidates) < len(scan_result.detail_candidates):
                scan_result = retry_scan_result
                selected_listing_strategy = "per_kit_fallback_after_compare"
                _log_lims_event(
                    "planner_snapshot_listing_selected",
                    strategy=selected_listing_strategy,
                    listed_lots=scan_result.listed_lot_count,
                    direct_lots=scan_result.direct_lot_count,
                    detail_candidates=len(scan_result.detail_candidates),
                )
        else:
            _log_lims_event(
                "planner_snapshot_listing_compare_failed",
                reason=retry_message,
                elapsed_ms=retry_elapsed_ms,
            )

    lots = list(scan_result.lots)
    seen_lot_uris = {lot.lot_uri for lot in lots}

    _log_lims_event(
        "planner_snapshot_scan_complete",
        listing_strategy=selected_listing_strategy,
        listed_lots=scan_result.listed_lot_count,
        direct_lots=scan_result.direct_lot_count,
        detail_candidates=len(scan_result.detail_candidates),
        index_active_detail_candidates=scan_result.index_active_detail_candidates,
        index_pending_detail_candidates=scan_result.index_pending_detail_candidates,
    )

    detailed_lot_count = 0
    if scan_result.detail_candidates:
        fields_by_uri = _resolve_lot_detail_fields(
            config,
            scan_result.detail_candidates,
            timeout=5,
            max_workers=PLANNER_DETAIL_FETCH_MAX_WORKERS,
            log_context="planner_snapshot",
        )
        for lot_uri in scan_result.detail_candidates:
            fields = fields_by_uri.get(lot_uri) or {}
            if not fields:
                warnings.append(
                    f"Could not load planner reagent lot details for {scan_result.detail_labels[lot_uri]}."
                )
                continue

            status_upper = (fields.get("status") or "").upper()
            if status_upper and status_upper not in allowed_statuses:
                continue

            reagent_kit_id = _extract_reagentkit_id(fields.get("reagent_kit_uri"))
            reagent_type = relevant_kit_id_to_type.get(reagent_kit_id)
            if not reagent_type or not (fields.get("name") or "").strip() or not status_upper:
                warnings.append(
                    f"Could not load planner reagent lot details for {scan_result.detail_labels[lot_uri]}."
                )
                continue

            if lot_uri in seen_lot_uris:
                continue

            lots.append(
                _planner_snapshot_entry_from_fields(
                    lot_uri=lot_uri,
                    reagent_type=reagent_type,
                    fields=fields,
                )
            )
            seen_lot_uris.add(lot_uri)
            detailed_lot_count += 1

    _log_lims_event(
        "planner_snapshot_complete",
        listing_strategy=selected_listing_strategy,
        listed_lots=scan_result.listed_lot_count,
        direct_lots=scan_result.direct_lot_count,
        detailed_lots=detailed_lot_count,
        total_lots=len(lots),
        warnings=len(warnings),
        elapsed_ms=int((perf_counter() - snapshot_started_at) * 1000),
    )
    return PlannerReagentLotSnapshotResult(
        success=True,
        lots=lots,
        warnings=warnings,
        message=f"Loaded {len(lots)} active or pending planner reagent lots.",
    )


def extract_index_set_letter(name: str | None) -> str | None:
    """Extract the configured index set letter from a reagent lot name."""
    raw_name = (name or "").strip()
    if not raw_name:
        return None

    for pattern in INDEX_SET_PATTERNS:
        match = pattern.search(raw_name)
        if match:
            set_letter = match.group(1).upper()
            if set_letter in SUPPORTED_INDEX_SET_LETTERS:
                return set_letter
    return None


def parse_prep_lot_name(name: str | None) -> tuple[int | None, int | None]:
    """Extract prep sequence number and reactions left from a lot name like '#65 TEST (45)'."""
    raw_name = (name or "").strip()
    if not raw_name:
        return (None, None)

    match = PREP_LOT_NAME_PATTERN.search(raw_name)
    if not match:
        return (None, None)

    return (int(match.group(1)), int(match.group(2)))


def parse_index_note_line(line: str) -> tuple[list[str], str | None]:
    """Parse one note line into canonical well labels, or return a warning."""
    raw_line = (line or "").strip()
    if not raw_line:
        return ([], None)

    body = None
    for pattern in INDEX_NOTE_PREFIX_PATTERNS:
        match = pattern.match(raw_line)
        if match:
            body = (match.group("body") or "").strip()
            break

    if body is None:
        return ([], None)
    if not body:
        return ([], f"Missing usage details in note line '{raw_line}'.")

    wells: list[str] = []
    matches = list(INDEX_NOTE_SEGMENT_PATTERN.finditer(body))
    if not matches:
        return ([], f"Could not parse any columns from note line '{raw_line}'.")

    leftovers = INDEX_NOTE_SEGMENT_PATTERN.sub("", body)
    leftovers = re.sub(r"(?i)\b(?:og|and)\b", "", leftovers)
    leftovers = re.sub(r"[\s,;:.-]+", "", leftovers)
    if leftovers:
        return ([], f"Unsupported note syntax in line '{raw_line}'.")

    for match in matches:
        column = int(match.group("column"))
        if column not in PLATE_COLUMNS:
            return ([], f"Invalid plate column {column} in note line '{raw_line}'.")

        wells_blob = (match.group("wells") or "").strip()
        if not wells_blob:
            wells.extend(wells_for_column(column))
            continue

        explicit_matches = list(INDEX_NOTE_WELL_PATTERN.finditer(wells_blob))
        if not explicit_matches:
            return ([], f"Missing explicit wells for column {column} in line '{raw_line}'.")

        wells_leftovers = INDEX_NOTE_WELL_PATTERN.sub("", wells_blob)
        wells_leftovers = re.sub(r"(?i)\b(?:og|and)\b", "", wells_leftovers)
        wells_leftovers = re.sub(r"[\s,;:.-]+", "", wells_leftovers)
        if wells_leftovers:
            return ([], f"Unsupported well list syntax in line '{raw_line}'.")

        for well_match in explicit_matches:
            row = well_match.group("row").upper()
            explicit_column = int(well_match.group("column"))
            if explicit_column != column:
                return (
                    [],
                    f"Well/column mismatch in note line '{raw_line}' for column {column}.",
                )
            wells.append(normalize_well(row, explicit_column))

    return (wells, None)


def parse_index_lot_notes(
    lot: ActiveIndexLot,
) -> tuple[list[IndexUsageRecord], list[str]]:
    """Parse one active index lot note field into well usage records."""
    usage_records: list[IndexUsageRecord] = []
    warnings: list[str] = []

    for raw_line in str(lot.notes or "").splitlines():
        wells, warning = parse_index_note_line(raw_line)
        if warning:
            warnings.append(f"{lot.name}: {warning}")
            continue
        for well in wells:
            usage_records.append(
                IndexUsageRecord(
                    lot_name=lot.name,
                    set_letter=lot.set_letter,
                    well=well,
                    source_line=raw_line.strip(),
                )
            )

    return usage_records, warnings


def build_index_plate_map(
    lot: ActiveIndexLot,
    usage_records: list[IndexUsageRecord],
    warnings: list[str] | None = None,
) -> IndexPlateMap:
    """Build a lot-level 96-well usage map from note-derived usage records."""
    counts = Counter(record.well for record in usage_records)
    cells: list[IndexPlateCell] = []
    unused_wells = 0
    single_use_wells = 0
    double_use_wells = 0
    conflict_wells = 0

    for column in PLATE_COLUMNS:
        for row in "ABCDEFGH":
            well = normalize_well(row, column)
            raw_count = counts.get(well, 0)
            if raw_count <= 0:
                state = "unused"
                unused_wells += 1
            elif raw_count == 1:
                state = "single"
                single_use_wells += 1
            elif raw_count == 2:
                state = "double"
                double_use_wells += 1
            else:
                state = "conflict"
                conflict_wells += 1

            cells.append(
                IndexPlateCell(
                    well=well,
                    row=row,
                    column=column,
                    raw_count=raw_count,
                    state=state,
                )
            )

    return IndexPlateMap(
        lot=lot,
        cells=cells,
        usage_records=usage_records,
        warnings=list(warnings or []),
        unused_wells=unused_wells,
        single_use_wells=single_use_wells,
        double_use_wells=double_use_wells,
        conflict_wells=conflict_wells,
    )


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
    kitnames: list[str] | None = None,
    max_detail_fetches: int = 250,
) -> ReagentLotSnapshotResult:
    """Fetch one shared reagent-lot snapshot for sequence checks."""
    _log_lims_event(
        "reagent_lot_snapshot_start",
        endpoint=f"{_safe_base_url_for_logs(config.base_url)}/reagentlots",
        max_detail_fetches=max_detail_fetches,
    )
    success, roots, error_message = _fetch_reagent_lot_listing_roots(
        config,
        kitnames=kitnames,
    )
    if not success:
        return ReagentLotSnapshotResult(
            success=False,
            lots=[],
            message=error_message,
        )

    lots: list[ReagentLotSnapshotEntry] = []
    detail_candidates: list[str] = []
    detail_seen: set[str] = set()

    for root in roots:
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
        fields_by_uri = _resolve_lot_detail_fields(config, limited_candidates, timeout=5)
        for lot_uri in limited_candidates:
            fields = fields_by_uri.get(lot_uri) or {}
            name = (fields.get("name") or "").strip()
            reagent_kit_uri = (fields.get("reagent_kit_uri") or "").strip()
            status = (fields.get("status") or "").strip()
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

        match = PREP_FULL_SET_PATTERN.search(lot.name)
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
                + ". Ensure reagent lots use names like '#NN (192)' or '#NN TEST (192)'."
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
    requested_kitnames = list(dict.fromkeys([*prep_reagent_types, INDEX_REAGENT_TYPE]))
    snapshot = _fetch_reagent_lot_snapshot(
        config,
        kitnames=requested_kitnames,
        max_detail_fetches=max_detail_fetches,
    )
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
        response = _lims_get(
            f"{config.base_url}/reagentlots",
            config=config,
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
        fields_by_uri = _resolve_lot_detail_fields(config, limited_candidates, timeout=5)
        for lot_uri in limited_candidates:
            append_if_active(fields_by_uri.get(lot_uri) or {})

    rows.sort(key=lambda r: (r.get("Reagent Type", ""), r.get("Internal Name", "")))
    return ActiveReagentOverviewResult(
        success=True,
        rows=rows,
        message=f"Loaded {len(rows)} active reagent lots.",
    )


def _extract_miseq_kit_type_from_internal_name(name: str | None) -> str | None:
    """Resolve a MiSeq subtype from the configured internal-name suffix."""
    raw_name = (name or "").strip().lower()
    if not raw_name:
        return None

    for kit_type in sorted(MISEQ_KIT_TYPES, key=len, reverse=True):
        lowered_kit_type = kit_type.lower()
        if raw_name == lowered_kit_type or raw_name.endswith(f" {lowered_kit_type}"):
            return kit_type
    return None


def _should_ignore_sequencing_lot_name(name: str | None) -> bool:
    """Return whether a sequencing lot name should be ignored for planner stock."""
    return (name or "").strip().lower().startswith("dummy")


def _should_ignore_prep_lot_name(name: str | None) -> bool:
    """Return whether a prep lot name should be ignored for planner prep sets."""
    return (name or "").strip().casefold() == "resteboks"


def _should_ignore_index_lot_name(name: str | None) -> bool:
    """Return whether an index lot name should be ignored for planner plate maps."""
    return (name or "").strip().casefold() == "rester"


def _miseq_box_key(reagent_type: str) -> str | None:
    """Return the logical MiSeq box key for one configured reagent type."""
    if "Box 1 of 2" in reagent_type:
        return "box_1"
    if "Box 2 of 2" in reagent_type:
        return "box_2"
    return None


def _build_sequencing_stock_summary_rows(
    lots: list[SequencingStockLot],
) -> list[SequencingStockSummaryRow]:
    """Aggregate raw sequencing lots into read-only planner summary rows."""
    miseq_counts: dict[str, dict[str, int]] = {
        kit_type: {"box_1": 0, "box_2": 0}
        for kit_type in MISEQ_KIT_TYPES
    }
    extra_kit_types: list[str] = []
    unknown_box_counts_by_name: dict[str, dict[str, int]] = {}
    phix_count = 0

    for lot in lots:
        naming_group = REAGENT_TYPES.get(lot.reagent_type, {}).get("naming_group")
        if naming_group == "phix":
            phix_count += 1
            continue
        if naming_group != "miseq":
            continue

        box_key = _miseq_box_key(lot.reagent_type)
        kit_type = (lot.miseq_kit_type or "").strip()
        if not kit_type:
            if "Unknown" not in extra_kit_types:
                extra_kit_types.append("Unknown")
            if box_key is None:
                continue
            unknown_name_key = (lot.name or "").strip().casefold() or lot.lot_uri
            unknown_box_counts = unknown_box_counts_by_name.setdefault(
                unknown_name_key,
                {"box_1": 0, "box_2": 0},
            )
            unknown_box_counts[box_key] += 1
            continue

        if kit_type not in miseq_counts:
            miseq_counts[kit_type] = {"box_1": 0, "box_2": 0}
            extra_kit_types.append(kit_type)

        if box_key is None:
            continue
        miseq_counts[kit_type][box_key] += 1

    rows = []
    for kit_type in [*MISEQ_KIT_TYPES, *extra_kit_types]:
        if kit_type == "Unknown":
            kit_count = sum(
                min(box_counts["box_1"], box_counts["box_2"])
                for box_counts in unknown_box_counts_by_name.values()
            )
            unmatched_count = sum(
                abs(box_counts["box_1"] - box_counts["box_2"])
                for box_counts in unknown_box_counts_by_name.values()
            )
        else:
            box_counts = miseq_counts[kit_type]
            kit_count = min(box_counts["box_1"], box_counts["box_2"])
            unmatched_count = abs(box_counts["box_1"] - box_counts["box_2"])
        rows.append(
            SequencingStockSummaryRow(
                item=f"MiSeq {kit_type}",
                kit_count=kit_count,
                unmatched_count=unmatched_count,
            )
        )

    rows.append(
        SequencingStockSummaryRow(
            item="PhiX Control v3",
            kit_count=phix_count,
            unmatched_count=None,
        )
    )
    return rows


def _build_active_prep_sets_result_from_snapshot_lots(
    snapshot_lots: list[PlannerReagentLotSnapshotEntry],
) -> ActivePrepSetsResult:
    """Build prep-set planner data from one shared planner snapshot."""
    warnings: list[str] = []
    prep_lots: list[ActivePrepLot] = []

    for lot in snapshot_lots:
        if lot.reagent_type not in PREP_REAGENT_TYPES:
            continue

        status = (lot.status or "").upper()
        if status not in {"ACTIVE", "PENDING"}:
            continue
        if _should_ignore_prep_lot_name(lot.name):
            continue

        sequence_number, reactions_left = parse_prep_lot_name(lot.name)
        if sequence_number is None or reactions_left is None:
            warnings.append(
                f"Skipped {status.lower()} prep lot '{lot.name or lot.lot_uri}' because its name does not contain '#NN ... (reactions_left)'."
            )
            continue

        prep_lots.append(
            ActivePrepLot(
                lot_uri=lot.lot_uri,
                reagent_type=lot.reagent_type,
                name=lot.name,
                lot_number=lot.lot_number,
                expiry_date=lot.expiry_date,
                status=lot.status,
                sequence_number=sequence_number,
                reactions_left=reactions_left,
            )
        )

    grouped_lots: dict[int, dict[str, ActivePrepLot]] = {}
    for lot in prep_lots:
        grouped_lots.setdefault(lot.sequence_number, {})[lot.reagent_type] = lot

    prep_sets: list[PrepSetSummary] = []
    for sequence_number in sorted(grouped_lots.keys()):
        lots_by_type = grouped_lots[sequence_number]
        reactions_by_type = {
            reagent_type: lots_by_type[reagent_type].reactions_left if reagent_type in lots_by_type else None
            for reagent_type in PREP_REAGENT_TYPES
        }
        available_reactions = [value for value in reactions_by_type.values() if value is not None]
        usable_reactions_left = min(available_reactions) if available_reactions else 0

        set_warnings: list[str] = []
        missing_types = [reagent_type for reagent_type in PREP_REAGENT_TYPES if reagent_type not in lots_by_type]
        if missing_types:
            set_warnings.append("Missing boxes: " + ", ".join(missing_types))
        if len(set(available_reactions)) > 1:
            set_warnings.append("Unequal reactions left across boxes")

        prep_sets.append(
            PrepSetSummary(
                sequence_number=sequence_number,
                usable_reactions_left=usable_reactions_left,
                reactions_by_type=reactions_by_type,
                lots_by_type=lots_by_type,
                warnings=set_warnings,
                is_balanced=not set_warnings,
            )
        )

    prep_sets.sort(
        key=lambda prep_set: (
            0
            if {
                (lot.status or "").upper()
                for lot in prep_set.lots_by_type.values()
                if (lot.status or "").strip()
            }
            == {"ACTIVE"}
            else 1,
            prep_set.sequence_number,
        )
    )

    if not prep_sets:
        message = "No active or pending prep sets were found."
    else:
        message = f"Loaded {len(prep_sets)} active or pending prep sets."

    return ActivePrepSetsResult(
        success=True,
        prep_sets=prep_sets,
        warnings=warnings,
        message=message,
    )


def _build_sequencing_stock_result_from_snapshot_lots(
    snapshot_lots: list[PlannerReagentLotSnapshotEntry],
) -> SequencingStockResult:
    """Build sequencing stock planner data from one shared planner snapshot."""
    lots: list[SequencingStockLot] = []

    for lot in snapshot_lots:
        if lot.reagent_type not in SEQUENCING_REAGENT_TYPES:
            continue

        status = (lot.status or "").upper()
        if status not in {"ACTIVE", "PENDING"}:
            continue

        name = (lot.name or "").strip()
        if _should_ignore_sequencing_lot_name(name):
            continue

        naming_group = REAGENT_TYPES.get(lot.reagent_type, {}).get("naming_group")
        miseq_kit_type = (
            _extract_miseq_kit_type_from_internal_name(name)
            if naming_group == "miseq"
            else None
        )

        lots.append(
            SequencingStockLot(
                lot_uri=lot.lot_uri,
                reagent_type=lot.reagent_type,
                name=name,
                expiry_date=lot.expiry_date,
                status=status,
                miseq_kit_type=miseq_kit_type,
            )
        )

    lots.sort(
        key=lambda lot: (
            REAGENT_TYPES.get(lot.reagent_type, {}).get("naming_group") != "miseq",
            lot.miseq_kit_type or "",
            lot.reagent_type,
            lot.name,
        )
    )
    summary_rows = _build_sequencing_stock_summary_rows(lots)
    if not lots:
        message = "No active or pending sequencing reagent lots were found."
    else:
        message = f"Loaded {len(lots)} active or pending sequencing reagent lots."

    return SequencingStockResult(
        success=True,
        lots=lots,
        summary_rows=summary_rows,
        message=message,
    )


def _build_index_plate_maps_result_from_snapshot_lots(
    snapshot_lots: list[PlannerReagentLotSnapshotEntry],
    *,
    snapshot_warnings: list[str] | None = None,
) -> IndexPlateMapsResult:
    """Build index plate-map planner data from one shared planner snapshot."""
    warnings = list(snapshot_warnings or [])
    index_lots: list[ActiveIndexLot] = []

    for lot in snapshot_lots:
        if lot.reagent_type != INDEX_REAGENT_TYPE:
            continue

        status = (lot.status or "").upper()
        if status not in {"ACTIVE", "PENDING"}:
            continue
        if _should_ignore_index_lot_name(lot.name):
            continue

        set_letter = extract_index_set_letter(lot.name)
        if not set_letter:
            warnings.append(
                f"Skipped index lot '{lot.name or lot.lot_uri}' because no supported set letter (A-D) was found."
            )
            continue

        index_lots.append(
            ActiveIndexLot(
                lot_uri=lot.lot_uri,
                name=lot.name,
                lot_number=lot.lot_number,
                expiry_date=lot.expiry_date,
                status=lot.status,
                set_letter=set_letter,
                notes=lot.notes,
            )
        )

    index_lots.sort(
        key=lambda lot: (
            1 if not (lot.expiry_date or "").strip() else 0,
            (lot.expiry_date or "").strip() or "9999-12-31",
            lot.name,
        )
    )

    active_lots = [lot for lot in index_lots if (lot.status or "").upper() == "ACTIVE"]
    pending_lots = [lot for lot in index_lots if (lot.status or "").upper() == "PENDING"]

    plate_maps: list[IndexPlateMap] = []
    for lot in active_lots:
        usage_records, parse_warnings = parse_index_lot_notes(lot)
        warnings.extend(parse_warnings)
        plate_maps.append(build_index_plate_map(lot, usage_records, warnings=parse_warnings))

    if not plate_maps and not pending_lots:
        message = "No active or pending index lots were found."
    else:
        message = f"Loaded {len(plate_maps)} active index plate maps and {len(pending_lots)} pending index lots."

    return IndexPlateMapsResult(
        success=True,
        plate_maps=plate_maps,
        pending_lots=pending_lots,
        warnings=warnings,
        message=message,
    )


def get_sequencing_stock_summary(config: LIMSConfig) -> SequencingStockResult:
    """Fetch ACTIVE/PENDING MiSeq and PhiX lots for the planner side card."""
    if not config.base_url or not config.username or not config.password:
        return SequencingStockResult(
            success=False,
            lots=[],
            summary_rows=[],
            message="Missing LIMS credentials. Set LIMS_BASE_URL, LIMS_API_USER, and LIMS_API_PASS.",
        )

    ok, roots, message = _fetch_reagent_lot_listing_roots(config, kitnames=SEQUENCING_REAGENT_TYPES)
    if not ok:
        return SequencingStockResult(
            success=False,
            lots=[],
            summary_rows=[],
            message=message,
        )

    kit_uri_to_type = get_reagent_kit_uris(config.base_url)
    sequencing_kit_id_to_type = {
        _extract_reagentkit_id(kit_uri_to_type[reagent_type]): reagent_type
        for reagent_type in SEQUENCING_REAGENT_TYPES
        if kit_uri_to_type.get(reagent_type)
    }
    allowed_statuses = {"ACTIVE", "PENDING"}

    lots: list[SequencingStockLot] = []
    detail_candidates: list[str] = []
    detail_seen: set[str] = set()

    def append_if_relevant(lot_uri: str, fields: dict[str, str]) -> None:
        if not fields:
            return

        status = (fields.get("status") or "").upper()
        if status not in allowed_statuses:
            return

        reagent_kit_id = _extract_reagentkit_id(fields.get("reagent_kit_uri"))
        reagent_type = sequencing_kit_id_to_type.get(reagent_kit_id)
        if not reagent_type:
            return

        name = (fields.get("name") or "").strip()
        if _should_ignore_sequencing_lot_name(name):
            return
        naming_group = REAGENT_TYPES.get(reagent_type, {}).get("naming_group")
        miseq_kit_type = (
            _extract_miseq_kit_type_from_internal_name(name)
            if naming_group == "miseq"
            else None
        )

        lots.append(
            SequencingStockLot(
                lot_uri=lot_uri,
                reagent_type=reagent_type,
                name=name,
                expiry_date=(fields.get("expiry_date") or "").strip(),
                status=status,
                miseq_kit_type=miseq_kit_type,
            )
        )

    for root in roots:
        for element in root.iter():
            if _local_name(element.tag) not in {"reagent-lot", "reagentlot"}:
                continue

            lot_uri = (element.attrib.get("uri") or "").strip()
            name = ""
            status = ""
            reagent_kit_uri = ""

            name_child = _find_child(element, "name")
            if name_child is not None and name_child.text:
                name = name_child.text.strip()
            elif element.attrib.get("name"):
                name = str(element.attrib.get("name") or "").strip()

            status_child = _find_child(element, "status")
            if status_child is not None and status_child.text:
                status = status_child.text.strip()
            elif element.attrib.get("status"):
                status = str(element.attrib.get("status") or "").strip()

            kit_child = _find_child(element, "reagent-kit")
            if kit_child is not None:
                reagent_kit_uri = (kit_child.attrib.get("uri") or "").strip()
            elif element.attrib.get("reagent-kit"):
                reagent_kit_uri = str(element.attrib.get("reagent-kit") or "").strip()

            if (not name or not reagent_kit_uri) and lot_uri:
                if lot_uri not in detail_seen:
                    detail_candidates.append(lot_uri)
                    detail_seen.add(lot_uri)
                continue

            append_if_relevant(
                lot_uri,
                {
                    "name": name,
                    "expiry_date": (
                        (_find_child(element, "expiry-date").text or "").strip()
                        if _find_child(element, "expiry-date") is not None
                        and _find_child(element, "expiry-date").text
                        else ""
                    ),
                    "status": status,
                    "reagent_kit_uri": reagent_kit_uri,
                },
            )

    if detail_candidates:
        fields_by_uri = _resolve_lot_detail_fields(config, detail_candidates, timeout=5)
        for lot_uri in detail_candidates:
            append_if_relevant(lot_uri, fields_by_uri.get(lot_uri) or {})

    lots.sort(
        key=lambda lot: (
            REAGENT_TYPES.get(lot.reagent_type, {}).get("naming_group") != "miseq",
            lot.miseq_kit_type or "",
            lot.reagent_type,
            lot.name,
        )
    )
    summary_rows = _build_sequencing_stock_summary_rows(lots)
    if not lots:
        message = "No active or pending sequencing reagent lots were found."
    else:
        message = f"Loaded {len(lots)} active or pending sequencing reagent lots."

    return SequencingStockResult(
        success=True,
        lots=lots,
        summary_rows=summary_rows,
        message=message,
    )


def get_active_prep_sets(config: LIMSConfig) -> ActivePrepSetsResult:
    """Fetch active or pending prep lots and group them by shared set number."""
    if not config.base_url or not config.username or not config.password:
        return ActivePrepSetsResult(
            success=False,
            prep_sets=[],
            warnings=[],
            message="Missing LIMS credentials. Set LIMS_BASE_URL, LIMS_API_USER, and LIMS_API_PASS.",
        )

    ok, roots, message = _fetch_reagent_lot_listing_roots(config, kitnames=PREP_REAGENT_TYPES)
    if not ok:
        return ActivePrepSetsResult(
            success=False,
            prep_sets=[],
            warnings=[],
            message=message,
        )

    kit_uri_to_type = get_reagent_kit_uris(config.base_url)
    prep_kit_id_to_type = {
        _extract_reagentkit_id(kit_uri_to_type[reagent_type]): reagent_type
        for reagent_type in PREP_REAGENT_TYPES
        if kit_uri_to_type.get(reagent_type)
    }

    warnings: list[str] = []
    prep_lots: list[ActivePrepLot] = []
    detail_candidates: list[str] = []
    detail_seen: set[str] = set()

    def append_if_relevant(lot_uri: str, fields: dict[str, str]) -> None:
        if not fields:
            return

        status = (fields.get("status") or "").upper()
        if status not in {"ACTIVE", "PENDING"}:
            return

        reagent_kit_id = _extract_reagentkit_id(fields.get("reagent_kit_uri"))
        reagent_type = prep_kit_id_to_type.get(reagent_kit_id)
        if not reagent_type:
            return

        name = (fields.get("name") or "").strip()
        if _should_ignore_prep_lot_name(name):
            return
        sequence_number, reactions_left = parse_prep_lot_name(name)
        if sequence_number is None or reactions_left is None:
            warnings.append(
                f"Skipped {status.lower()} prep lot '{name or lot_uri}' because its name does not contain '#NN ... (reactions_left)'."
            )
            return

        prep_lots.append(
            ActivePrepLot(
                lot_uri=lot_uri,
                reagent_type=reagent_type,
                name=name,
                lot_number=(fields.get("lot_number") or "").strip(),
                expiry_date=(fields.get("expiry_date") or "").strip(),
                status=(fields.get("status") or "").strip(),
                sequence_number=sequence_number,
                reactions_left=reactions_left,
            )
        )

    for root in roots:
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
            elif element.attrib.get("reagent-kit"):
                reagent_kit_uri = str(element.attrib.get("reagent-kit") or "").strip()

            if (not name or not lot_number or not reagent_kit_uri) and lot_uri:
                if lot_uri not in detail_seen:
                    detail_candidates.append(lot_uri)
                    detail_seen.add(lot_uri)
                continue

            append_if_relevant(
                lot_uri,
                {
                    "name": name,
                    "lot_number": lot_number,
                    "expiry_date": expiry_date,
                    "status": status,
                    "reagent_kit_uri": reagent_kit_uri,
                },
            )

    if detail_candidates:
        fields_by_uri = _resolve_lot_detail_fields(config, detail_candidates, timeout=5)
        for lot_uri in detail_candidates:
            fields = fields_by_uri.get(lot_uri) or {}
            if not fields:
                warnings.append(f"Could not load prep lot details for {lot_uri}.")
                continue
            append_if_relevant(lot_uri, fields)

    grouped_lots: dict[int, dict[str, ActivePrepLot]] = {}
    for lot in prep_lots:
        grouped_lots.setdefault(lot.sequence_number, {})[lot.reagent_type] = lot

    prep_sets: list[PrepSetSummary] = []
    for sequence_number in sorted(grouped_lots.keys()):
        lots_by_type = grouped_lots[sequence_number]
        reactions_by_type = {
            reagent_type: lots_by_type[reagent_type].reactions_left if reagent_type in lots_by_type else None
            for reagent_type in PREP_REAGENT_TYPES
        }
        available_reactions = [value for value in reactions_by_type.values() if value is not None]
        usable_reactions_left = min(available_reactions) if available_reactions else 0

        set_warnings: list[str] = []
        missing_types = [reagent_type for reagent_type in PREP_REAGENT_TYPES if reagent_type not in lots_by_type]
        if missing_types:
            set_warnings.append("Missing boxes: " + ", ".join(missing_types))
        if len(set(available_reactions)) > 1:
            set_warnings.append("Unequal reactions left across boxes")

        prep_sets.append(
            PrepSetSummary(
                sequence_number=sequence_number,
                usable_reactions_left=usable_reactions_left,
                reactions_by_type=reactions_by_type,
                lots_by_type=lots_by_type,
                warnings=set_warnings,
                is_balanced=not set_warnings,
            )
        )

    prep_sets.sort(
        key=lambda prep_set: (
            0
            if {
                (lot.status or "").upper()
                for lot in prep_set.lots_by_type.values()
                if (lot.status or "").strip()
            }
            == {"ACTIVE"}
            else 1,
            prep_set.sequence_number,
        )
    )

    if not prep_sets:
        message = "No active or pending prep sets were found."
    else:
        message = f"Loaded {len(prep_sets)} active or pending prep sets."

    return ActivePrepSetsResult(
        success=True,
        prep_sets=prep_sets,
        warnings=warnings,
        message=message,
    )


def get_index_lots(
    config: LIMSConfig,
    *,
    allowed_statuses: set[str] | None = None,
    max_detail_fetches: int | None = None,
) -> tuple[bool, list[ActiveIndexLot], list[str], str]:
    """Fetch index lots with notes from Clarity reagent lots."""
    if not config.base_url or not config.username or not config.password:
        return (
            False,
            [],
            [],
            "Missing LIMS credentials. Set LIMS_BASE_URL, LIMS_API_USER, and LIMS_API_PASS.",
        )

    try:
        response = _lims_get(
            f"{config.base_url}/reagentlots",
            config=config,
            params={"kitname": INDEX_REAGENT_TYPE},
            headers={"Accept": "application/xml"},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        return (False, [], [], f"Connection error while reading reagent lots: {str(e)}")

    if response.status_code != 200:
        return (False, [], [], f"Unable to read reagent lots (HTTP {response.status_code})")

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        return (False, [], [], f"Could not parse reagent lots XML: {str(e)}")

    index_kit_uri = get_reagent_kit_uris(config.base_url).get(INDEX_REAGENT_TYPE)
    index_kit_id = _extract_reagentkit_id(index_kit_uri)
    if not index_kit_id:
        return (False, [], [], f"Missing reagent kit URI mapping for index kit: {INDEX_REAGENT_TYPE}.")

    allowed_status_set = {status.upper() for status in (allowed_statuses or {"ACTIVE"})}
    detail_candidates: list[str] = []
    detail_seen: set[str] = set()
    warnings: list[str] = []

    for element in root.iter():
        if _local_name(element.tag) not in {"reagent-lot", "reagentlot"}:
            continue

        lot_uri = (element.attrib.get("uri") or "").strip()
        status = ""
        reagent_kit_uri = ""

        status_child = _find_child(element, "status")
        if status_child is not None and status_child.text:
            status = status_child.text.strip()
        elif element.attrib.get("status"):
            status = str(element.attrib.get("status") or "").strip()

        kit_child = _find_child(element, "reagent-kit")
        if kit_child is not None:
            reagent_kit_uri = (kit_child.attrib.get("uri") or "").strip()
        elif element.attrib.get("reagent-kit"):
            reagent_kit_uri = str(element.attrib.get("reagent-kit") or "").strip()

        status_upper = status.upper()
        kit_id = _extract_reagentkit_id(reagent_kit_uri)
        if status_upper and status_upper not in allowed_status_set:
            continue
        if kit_id and kit_id != index_kit_id:
            continue
        if lot_uri and lot_uri not in detail_seen:
            detail_candidates.append(lot_uri)
            detail_seen.add(lot_uri)

    total_candidates = len(detail_candidates)
    if max_detail_fetches is not None:
        limited_candidates, total_candidates = _select_recent_lot_candidates(
            detail_candidates,
            max_detail_fetches,
        )
        if total_candidates > max_detail_fetches:
            _log_lims_event(
                "active_index_lot_candidates_limited",
                limit=max_detail_fetches,
                total_candidates=total_candidates,
                selection="highest_reagentlot_ids",
            )
    else:
        limited_candidates = detail_candidates

    active_lots: list[ActiveIndexLot] = []
    if limited_candidates:
        fields_by_uri = _resolve_lot_detail_fields(config, limited_candidates, timeout=5)
        for lot_uri in limited_candidates:
            fields = fields_by_uri.get(lot_uri) or {}
            if not fields:
                warnings.append(f"Could not load index lot details for {lot_uri}.")
                continue

            status = (fields.get("status") or "").upper()
            reagent_kit_id = _extract_reagentkit_id(fields.get("reagent_kit_uri"))
            if status not in allowed_status_set or reagent_kit_id != index_kit_id:
                continue

            name = (fields.get("name") or "").strip()
            if _should_ignore_index_lot_name(name):
                continue
            set_letter = extract_index_set_letter(name)
            if not set_letter:
                warnings.append(
                    f"Skipped index lot '{name or lot_uri}' because no supported set letter (A-D) was found."
                )
                continue

            active_lots.append(
                ActiveIndexLot(
                    lot_uri=lot_uri,
                    name=name,
                    lot_number=(fields.get("lot_number") or "").strip(),
                    expiry_date=(fields.get("expiry_date") or "").strip(),
                    status=(fields.get("status") or "").strip(),
                    set_letter=set_letter,
                    notes=(fields.get("notes") or "").strip(),
                )
            )

    active_lots.sort(
        key=lambda lot: (
            1 if not (lot.expiry_date or "").strip() else 0,
            (lot.expiry_date or "").strip() or "9999-12-31",
            lot.name,
        )
    )
    status_label = "/".join(sorted(allowed_status_set))
    return (True, active_lots, warnings, f"Loaded {len(active_lots)} index lots with status {status_label}.")


def get_active_index_lots(
    config: LIMSConfig,
    max_detail_fetches: int | None = None,
) -> tuple[bool, list[ActiveIndexLot], list[str], str]:
    """Fetch active index lots with notes from Clarity reagent lots."""
    success, active_lots, warnings, message = get_index_lots(
        config,
        allowed_statuses={"ACTIVE"},
        max_detail_fetches=max_detail_fetches,
    )
    if success:
        message = f"Loaded {len(active_lots)} active index lots."
    return success, active_lots, warnings, message


def get_index_plate_maps_from_notes(
    config: LIMSConfig,
    max_detail_fetches: int | None = None,
) -> IndexPlateMapsResult:
    """Build lot-level index plate maps from active lot notes and collect pending lots."""
    success, index_lots, warnings, message = get_index_lots(
        config,
        allowed_statuses={"ACTIVE", "PENDING"},
        max_detail_fetches=max_detail_fetches,
    )
    if not success:
        return IndexPlateMapsResult(
            success=False,
            plate_maps=[],
            pending_lots=[],
            warnings=warnings,
            message=message,
        )

    active_lots = [lot for lot in index_lots if (lot.status or "").upper() == "ACTIVE"]
    pending_lots = [lot for lot in index_lots if (lot.status or "").upper() == "PENDING"]

    plate_maps: list[IndexPlateMap] = []
    for lot in active_lots:
        usage_records, parse_warnings = parse_index_lot_notes(lot)
        warnings.extend(parse_warnings)
        plate_maps.append(build_index_plate_map(lot, usage_records, warnings=parse_warnings))

    if not plate_maps and not pending_lots:
        message = "No active or pending index lots were found."
    else:
        message = f"Loaded {len(plate_maps)} active index plate maps and {len(pending_lots)} pending index lots."

    return IndexPlateMapsResult(
        success=True,
        plate_maps=plate_maps,
        pending_lots=pending_lots,
        warnings=warnings,
        message=message,
    )


def get_illumina_planning_data(config: LIMSConfig) -> IlluminaPlanningDataResult:
    """Load planner prep, sequencing, and index data from one shared lot snapshot."""
    snapshot = _fetch_planner_reagent_lot_snapshot(config)
    if not snapshot.success:
        failure_message = snapshot.message
        return IlluminaPlanningDataResult(
            prep_sets=ActivePrepSetsResult(
                success=False,
                prep_sets=[],
                warnings=[],
                message=failure_message,
            ),
            sequencing_stock=SequencingStockResult(
                success=False,
                lots=[],
                summary_rows=[],
                message=failure_message,
            ),
            plate_maps=IndexPlateMapsResult(
                success=False,
                plate_maps=[],
                pending_lots=[],
                warnings=[],
                message=failure_message,
            ),
        )

    return IlluminaPlanningDataResult(
        prep_sets=_build_active_prep_sets_result_from_snapshot_lots(snapshot.lots),
        sequencing_stock=_build_sequencing_stock_result_from_snapshot_lots(snapshot.lots),
        plate_maps=_build_index_plate_maps_result_from_snapshot_lots(
            snapshot.lots,
            snapshot_warnings=snapshot.warnings,
        ),
    )


def update_reagent_lot_status(
    config: LIMSConfig,
    lot_uri: str,
    new_status: str,
) -> ReagentLotResult:
    """Update an existing reagent lot status in Clarity."""
    if not config.base_url or not config.username or not config.password:
        return ReagentLotResult(
            success=False,
            lims_id=None,
            message="Missing LIMS credentials. Set LIMS_BASE_URL, LIMS_API_USER, and LIMS_API_PASS.",
            name="",
        )

    try:
        detail_response = _lims_get(
            lot_uri,
            config=config,
            headers={"Accept": "application/xml"},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        return ReagentLotResult(
            success=False,
            lims_id=None,
            message=f"Connection error while reading reagent lot: {str(e)}",
            name="",
        )

    if detail_response.status_code != 200:
        return ReagentLotResult(
            success=False,
            lims_id=None,
            message=f"Unable to read reagent lot (HTTP {detail_response.status_code})",
            name="",
        )

    fields = _parse_lot_fields_from_xml(detail_response.content)
    if not fields:
        return ReagentLotResult(
            success=False,
            lims_id=None,
            message="Could not parse reagent lot XML.",
            name="",
        )

    reagent_kit_uri = fields.get("reagent_kit_uri") or ""
    if not reagent_kit_uri:
        return ReagentLotResult(
            success=False,
            lims_id=None,
            message="Reagent lot is missing reagent-kit URI.",
            name=fields.get("name") or "",
        )

    safe_name = xml_escape(str(fields.get("name") or ""))
    safe_lot_number = xml_escape(str(fields.get("lot_number") or ""))
    safe_expiry_date = xml_escape(str(fields.get("expiry_date") or ""))
    safe_storage_location = xml_escape(str(fields.get("storage_location") or ""))
    safe_notes = xml_escape(str(fields.get("notes") or ""))
    safe_status = xml_escape(str(new_status or "").upper())

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
        response = requests.put(
            lot_uri,
            auth=HTTPBasicAuth(config.username, config.password),
            headers={
                "Content-Type": "application/xml",
                "Accept": "application/xml",
            },
            data=xml_payload.encode("utf-8"),
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        return ReagentLotResult(
            success=False,
            lims_id=None,
            message=f"Connection error while updating reagent lot: {str(e)}",
            name=fields.get("name") or "",
        )

    if response.status_code not in [200, 204]:
        match = re.search(r"<message>([^<]+)</message>", response.text)
        error_msg = match.group(1) if match else response.text[:200]
        return ReagentLotResult(
            success=False,
            lims_id=None,
            message=f"API error ({response.status_code}): {error_msg}",
            name=fields.get("name") or "",
        )

    return ReagentLotResult(
        success=True,
        lims_id=None,
        message=f"Updated status to {safe_status}",
        name=fields.get("name") or "",
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
        response = _lims_post(
            url,
            config=config,
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
        response = _lims_get(
            endpoint,
            config=config,
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
