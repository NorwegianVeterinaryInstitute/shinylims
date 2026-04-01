"""
Pin legacy Excel archive files to Posit Connect.

Uploads the sample prep log and sequencing log as file-type pins so they
can be served as direct download links via the LEGACY_METADATA_*_URL
environment variables in the ShinyLIMS app.

Usage:
    python scripts/pin_legacy_excel_archives.py \\
        --sample-prep path/to/sample_prep_log.xlsx \\
        --sequencing-log path/to/sequencing_log.xlsx

After uploading, the script prints the Posit Connect content URL for
each pin — paste these into ``.env`` as LEGACY_METADATA_SAMPLE_PREP_URL
and LEGACY_METADATA_SEQUENCING_LOG_URL.

Requires POSIT_API_KEY and POSIT_SERVER_URL in the environment (or .env).
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pins import board_connect

POSIT_USER = "vi2172"

PINS = {
    "sample_prep": {
        "pin_name": f"{POSIT_USER}/legacy_metadata_sample_prep",
        "env_var": "LEGACY_METADATA_SAMPLE_PREP_URL",
    },
    "sequencing_log": {
        "pin_name": f"{POSIT_USER}/legacy_metadata_sequencing_log",
        "env_var": "LEGACY_METADATA_SEQUENCING_LOG_URL",
    },
}


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Pin legacy Excel archives to Posit Connect.",
    )
    parser.add_argument(
        "--sample-prep",
        type=Path,
        required=True,
        help="Path to the sample preparation log .xlsx file.",
    )
    parser.add_argument(
        "--sequencing-log",
        type=Path,
        required=True,
        help="Path to the sequencing log .xlsx file.",
    )
    args = parser.parse_args()

    api_key = os.getenv("POSIT_API_KEY")
    server_url = os.getenv("POSIT_SERVER_URL")
    if not api_key or not server_url:
        sys.exit("Error: POSIT_API_KEY and POSIT_SERVER_URL must be set (check .env).")

    # cache=None avoids a board_deparse bug in pins 0.8.5 with the pinscache protocol
    board = board_connect(api_key=api_key, server_url=server_url, cache=None)

    uploads = [
        (args.sample_prep, PINS["sample_prep"]),
        (args.sequencing_log, PINS["sequencing_log"]),
    ]

    for filepath, info in uploads:
        if not filepath.exists():
            sys.exit(f"Error: {filepath} not found.")

        pin_name = info["pin_name"]
        print(f"Uploading {filepath} as '{pin_name}' ...")
        board.pin_upload(str(filepath), name=pin_name)
        print(f"  Done: {pin_name}")

    print("\nDone! Set the download URLs in .env:")
    for info in PINS.values():
        print(f"  {info['env_var']}=<content URL from Posit Connect>")


if __name__ == "__main__":
    main()
