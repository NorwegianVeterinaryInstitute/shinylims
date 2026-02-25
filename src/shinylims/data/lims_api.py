"""
lims_api.py - Clarity LIMS API functions for reagent lot management
Location: src/shinylims/data/lims_api.py
"""

import os
import requests
from requests.auth import HTTPBasicAuth
from dataclasses import dataclass


@dataclass
class LIMSConfig:
    """LIMS API configuration."""
    base_url: str
    username: str
    password: str
    
    @classmethod
    def from_environment(cls):
        """Load config from environment variables."""
        return cls(
            base_url=os.environ.get("CLARITY_API_URL", ""),
            username=os.environ.get("CLARITY_API_USERNAME", ""),
            password=os.environ.get("CLARITY_API_PASSWORD", "")
        )
    
    @classmethod
    def for_testing(cls):
        """Load config for local testing - replace with your values."""
        return cls(
            base_url="https://nvi-test.claritylims.com/api/v2",
            username="",  # Replace for local testing
            password=""   # Replace for local testing
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