"""
lims_api.py - Clarity LIMS API functions for reagent lot management
Location: src/shinylims/data/lims_api.py
"""

import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.auth import HTTPBasicAuth
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


@dataclass
class LIMSConfig:
    """LIMS API configuration."""
    base_url: str
    username: str
    password: str
    
    @classmethod
    def get_credentials(cls):
        """Load config for local testing - replace with your values."""
        return cls(
            base_url=os.getenv('CLARITY_API_BASE_URL'),
            username= os.getenv('CLARITY_APIUSER_USERNAME'),
            password=os.getenv('CLARITY_APIUSER_PASSWORD')
        )

# Reagent kit URIs - these map our reagent types to LIMS kit URIs
def get_reagent_kit_uris(base_url: str) -> dict:
    """Get reagent kit URI mapping for a given base URL."""
    return {
        "IDT-ILMN DNA/RNA UD Index Sets": f"{base_url}/reagentkits/302",
        "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp": f"{base_url}/reagentkits/203",
        "Illumina DNA Prep – PCR + Buffers (EPM, TB1, RSB) 96sp": f"{base_url}/reagentkits/202",
        "Illumina DNA Prep – Tagmentation (M) Beads 96sp": f"{base_url}/reagentkits/102",
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


def _local_name(tag: str) -> str:
    """Return XML local tag name without namespace."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find_child(element: ET.Element, child_name: str) -> ET.Element | None:
    """Find first direct child by local tag name."""
    for child in element:
        if _local_name(child.tag) == child_name:
            return child
    return None


def _extract_reagentkit_id(uri: str | None) -> str | None:
    """Extract reagent kit numeric ID from a URI."""
    if not uri:
        return None
    match = re.search(r"/reagentkits/(\d+)", uri)
    return match.group(1) if match else None


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
    if name_child is not None and name_child.text:
        name = name_child.text.strip()
    elif root.attrib.get("name"):
        name = root.attrib["name"].strip()

    kit_child = _find_child(root, "reagent-kit")
    if kit_child is not None:
        reagent_kit_uri = (kit_child.attrib.get("uri") or "").strip()
    elif root.attrib.get("reagent-kit"):
        reagent_kit_uri = str(root.attrib.get("reagent-kit") or "").strip()

    status_child = _find_child(root, "status")
    if status_child is not None and status_child.text:
        status = status_child.text.strip()
    elif root.attrib.get("status"):
        status = str(root.attrib.get("status") or "").strip()

    return name, reagent_kit_uri, status


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


def get_latest_prep_sequence_status(
    config: LIMSConfig,
    prep_reagent_types: list[str],
    max_detail_fetches: int = 250
) -> PrepSequenceStatus:
    """
    Get latest complete sequence number for Illumina DNA Prep reagent sets.

    A valid state requires all three prep reagent types to share the same
    latest sequence number (e.g., all at #29).
    """
    kit_uris = get_reagent_kit_uris(config.base_url)
    prep_kit_uris = {rt: kit_uris.get(rt) for rt in prep_reagent_types}
    latest_by_type = {rt: None for rt in prep_reagent_types}
    print("[prep-check] Starting prep sequence check")
    print(f"[prep-check] Prep kit URI map: {prep_kit_uris}")

    missing_types = [rt for rt, uri in prep_kit_uris.items() if not uri]
    if missing_types:
        return PrepSequenceStatus(
            success=False,
            latest_complete_sequence=None,
            message=f"Missing reagent kit URI mapping for: {', '.join(missing_types)}",
            latest_by_reagent_type=latest_by_type
        )

    try:
        response = requests.get(
            f"{config.base_url}/reagentlots",
            auth=HTTPBasicAuth(config.username, config.password),
            headers={"Accept": "application/xml"},
            timeout=30
        )
        print(f"[prep-check] GET /reagentlots status={response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[prep-check] Request error: {e}")
        return PrepSequenceStatus(
            success=False,
            latest_complete_sequence=None,
            message=f"Connection error while reading reagent lots: {str(e)}",
            latest_by_reagent_type=latest_by_type
        )

    if response.status_code != 200:
        return PrepSequenceStatus(
            success=False,
            latest_complete_sequence=None,
            message=f"Unable to read reagent lots (HTTP {response.status_code})",
            latest_by_reagent_type=latest_by_type
        )

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        print(f"[prep-check] XML parse error: {e}")
        return PrepSequenceStatus(
            success=False,
            latest_complete_sequence=None,
            message=f"Could not parse reagent lots XML: {str(e)}",
            latest_by_reagent_type=latest_by_type
        )

    seq_pattern = re.compile(r"#(\d+)\s*\(192\)")
    kit_id_to_type = {}
    for reagent_type, uri in prep_kit_uris.items():
        kit_id = _extract_reagentkit_id(uri)
        if kit_id:
            kit_id_to_type[kit_id] = reagent_type
    print(f"[prep-check] Kit ID map: {kit_id_to_type}")

    detail_candidates: list[str] = []
    detail_seen: set[str] = set()

    for element in root.iter():
        if _local_name(element.tag) not in {"reagent-lot", "reagentlot"}:
            continue

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
            # Fallback for list-style payloads that expose kit URI on attributes.
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

        # Many Clarity instances return list entries with only lot URI.
        if (not name or not reagent_kit_uri) and lot_uri:
            if lot_uri not in detail_seen:
                detail_candidates.append(lot_uri)
                detail_seen.add(lot_uri)
            continue

        if status and status.upper() != "ACTIVE":
            continue

        if not name or not reagent_kit_uri:
            continue

        reagent_kit_id = _extract_reagentkit_id(reagent_kit_uri)
        reagent_type = kit_id_to_type.get(reagent_kit_id or "")
        if not reagent_type:
            continue

        match = seq_pattern.search(name)
        if not match:
            continue

        seq_num = int(match.group(1))
        print(
            "[prep-check] Matched prep lot: "
            f"name='{name}', kit_uri='{reagent_kit_uri}', kit_id='{reagent_kit_id}', "
            f"type='{reagent_type}', seq={seq_num}"
        )
        current_max = latest_by_type[reagent_type]
        if current_max is None or seq_num > current_max:
            latest_by_type[reagent_type] = seq_num

    limited_candidates = detail_candidates[:max_detail_fetches]
    if len(detail_candidates) > max_detail_fetches:
        print(
            f"[prep-check] Limiting lot detail fetches to {max_detail_fetches} "
            f"(total candidates={len(detail_candidates)})"
        )

    detail_fetches = 0
    if limited_candidates:
        max_workers = min(16, len(limited_candidates))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(
                    _fetch_lot_detail,
                    lot_uri,
                    config.username,
                    config.password,
                    5
                )
                for lot_uri in limited_candidates
            ]

            for future in as_completed(futures):
                detail_fetches += 1
                _, name, reagent_kit_uri, status = future.result()
                if status and status.upper() != "ACTIVE":
                    continue
                if not name or not reagent_kit_uri:
                    continue

                reagent_kit_id = _extract_reagentkit_id(reagent_kit_uri)
                reagent_type = kit_id_to_type.get(reagent_kit_id or "")
                if not reagent_type:
                    continue

                match = seq_pattern.search(name)
                if not match:
                    continue

                seq_num = int(match.group(1))
                print(
                    "[prep-check] Matched prep lot (detail): "
                    f"name='{name}', kit_uri='{reagent_kit_uri}', kit_id='{reagent_kit_id}', "
                    f"type='{reagent_type}', seq={seq_num}"
                )
                current_max = latest_by_type[reagent_type]
                if current_max is None or seq_num > current_max:
                    latest_by_type[reagent_type] = seq_num

    print(f"[prep-check] Detail fetches from lot URIs: {detail_fetches}")
    print(f"[prep-check] Latest sequence by type: {latest_by_type}")
    missing_sequences = [rt for rt, seq in latest_by_type.items() if seq is None]
    if missing_sequences:
        print(f"[prep-check] Missing sequences for: {missing_sequences}")
        return PrepSequenceStatus(
            success=False,
            latest_complete_sequence=None,
            message=(
                "Could not determine latest sequence for: "
                + ", ".join(missing_sequences)
                + ". Ensure reagent lots use names like '#NN (192)'."
            ),
            latest_by_reagent_type=latest_by_type
        )

    unique_latest = sorted(set(seq for seq in latest_by_type.values() if seq is not None))
    if len(unique_latest) != 1:
        print(f"[prep-check] Mismatch detected. unique_latest={unique_latest}")
        mismatch = ", ".join(
            f"{rt}: #{seq}" for rt, seq in latest_by_type.items()
        )
        return PrepSequenceStatus(
            success=False,
            latest_complete_sequence=None,
            message=(
                "Prep reagent set is incomplete/misaligned. Latest numbers are "
                f"{mismatch}. Clean up Clarity LIMS so all three prep reagents "
                "share the same latest number before submitting new lots."
            ),
            latest_by_reagent_type=latest_by_type
        )

    latest_complete = unique_latest[0]
    print(f"[prep-check] Success. latest_complete_sequence={latest_complete}")
    return PrepSequenceStatus(
        success=True,
        latest_complete_sequence=latest_complete,
        message=f"Latest complete prep set is #{latest_complete}",
        latest_by_reagent_type=latest_by_type
    )


def create_reagent_lot(
    config: LIMSConfig,
    name: str,
    lot_number: str,
    reagent_type: str,
    expiry_date: str,
    storage_location: str = "",
    notes: str = ""
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
    
    xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<lot:reagent-lot xmlns:lot="http://genologics.com/ri/reagentlot">
    <reagent-kit uri="{reagent_kit_uri}"/>
    <name>{name}</name>
    <lot-number>{lot_number}</lot-number>
    <expiry-date>{expiry_date}</expiry-date>
    <storage-location>{storage_location}</storage-location>
    <notes>{notes}</notes>
    <status>ACTIVE</status>
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
    try:
        response = requests.get(
            f"{config.base_url}/reagentkits",
            auth=HTTPBasicAuth(config.username, config.password),
            headers={"Accept": "application/xml"},
            timeout=10
        )
        
        if response.status_code == 200:
            return True, "Connection successful"
        else:
            return False, f"HTTP {response.status_code}: {response.text[:100]}"
            
    except requests.exceptions.RequestException as e:
        return False, f"Connection failed: {str(e)}"
