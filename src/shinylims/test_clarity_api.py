"""
test_clarity_api.py - Run this locally to test API connectivity
"""

import requests
from requests.auth import HTTPBasicAuth
from datetime import date, timedelta

# For local testing, you can hardcode these temporarily
# (We'll move to environment variables for Posit Connect)
BASE_URL = "https://nvi-test.claritylims.com/api/v2"
USERNAME = ""
PASSWORD = ""


# Reagent kit URIs from your LIMS
REAGENT_KIT_URIS = {
    "IDT-ILMN DNA/RNA UD Index Sets": f"{BASE_URL}/reagentkits/302",
    "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp": f"{BASE_URL}/reagentkits/203",
    "Illumina DNA Prep – PCR + Buffers (EPM, TB1, RSB) 96sp": f"{BASE_URL}/reagentkits/202",
    "Illumina DNA Prep – Tagmentation (M) Beads 96sp": f"{BASE_URL}/reagentkits/102",
}


def create_reagent_lot(
    name: str,
    lot_number: str,
    reagent_kit_uri: str,
    expiry_date: str,
    storage_location: str = "",
    notes: str = ""
):
    """
    Create a new reagent lot in Clarity LIMS.
    """
    
    url = f"{BASE_URL}/reagentlots"
    
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
    
    print(f"--- Sending POST to {url} ---")
    print(f"Payload:\n{xml_payload}\n")
    
    response = requests.post(
        url,
        auth=HTTPBasicAuth(USERNAME, PASSWORD),
        headers={
            "Content-Type": "application/xml",
            "Accept": "application/xml"
        },
        data=xml_payload.encode('utf-8')
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response:\n{response.text}")
    
    if response.status_code in [200, 201]:
        print("\n✅ Reagent lot created successfully!")
    else:
        print(f"\n❌ Failed to create reagent lot")
    
    return response


def test_create_lot():
    """Test creating a single reagent lot."""
    
    # Use a future expiry date (1 year from now)
    future_expiry = (date.today() + timedelta(days=365)).strftime("%Y-%m-%d")
    
    response = create_reagent_lot(
        name="#99 (192) - TEST FROM API",
        lot_number="TEST-12345-API",
        reagent_kit_uri=REAGENT_KIT_URIS["Illumina DNA Prep – Tagmentation (M) Beads 96sp"],
        expiry_date=future_expiry,
        storage_location="-20°C Freezer",
        notes="Test lot created via API - safe to delete"
    )
    
    return response


if __name__ == "__main__":
    print("=" * 60)
    print("Testing Reagent Lot Creation")
    print("=" * 60)
    test_create_lot()