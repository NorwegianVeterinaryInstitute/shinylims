"""
Small debug entry points for the Clarity Postgres prototype.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from shinylims.integrations.clarity_pg import create_session
from shinylims.integrations.queries.sequencing import (
    SequencingLineage,
    build_sequencing_lineages,
    build_sequencing_run_rows,
)


def _parse_type_ids(raw_values: list[str]) -> list[int]:
    type_ids: list[int] = []
    for raw_value in raw_values:
        for part in raw_value.split(","):
            value = part.strip()
            if not value:
                continue
            type_ids.append(int(value))
    return type_ids


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(sep=" ", timespec="seconds")


def _lineage_to_payload(lineage: SequencingLineage, row: dict[str, Any] | None) -> dict[str, Any]:
    payload = {
        "sequencing_process": {
            "processid": lineage.sequencing_process.processid,
            "luid": lineage.sequencing_process.luid,
            "workstatus": lineage.sequencing_process.workstatus,
            "daterun": _format_timestamp(lineage.sequencing_process.daterun),
            "typeid": lineage.sequencing_process.typeid,
        },
        "representative_input_artifactid": lineage.representative_input_artifactid,
        "step7_process": asdict(lineage.step7_process) if lineage.step7_process else None,
        "step6_process": asdict(lineage.step6_process) if lineage.step6_process else None,
        "step5_process": asdict(lineage.step5_process) if lineage.step5_process else None,
        "step7_input_artifactid": lineage.step7_input_artifactid,
        "step6_input_artifactid": lineage.step6_input_artifactid,
        "step5_input_artifactids": list(lineage.step5_input_artifactids),
    }
    if payload["step7_process"] is not None:
        payload["step7_process"]["daterun"] = _format_timestamp(lineage.step7_process.daterun)
    if payload["step6_process"] is not None:
        payload["step6_process"]["daterun"] = _format_timestamp(lineage.step6_process.daterun)
    if payload["step5_process"] is not None:
        payload["step5_process"]["daterun"] = _format_timestamp(lineage.step5_process.daterun)
    if row is not None:
        row_payload = dict(row)
        if isinstance(row_payload.get("Seq Date"), datetime):
            row_payload["Seq Date"] = _format_timestamp(row_payload["Seq Date"])
        payload["row"] = row_payload
    return payload


def _print_human_readable(payload: dict[str, Any]) -> None:
    seq = payload["sequencing_process"]
    print(
        f"Seq {seq['luid'] or '<missing-luid>'} "
        f"(processid={seq['processid']}, status={seq['workstatus']}, date={seq['daterun']})"
    )
    print(f"  representative input artifact: {payload['representative_input_artifactid']}")

    for key in ("step7_process", "step6_process", "step5_process"):
        process = payload[key]
        input_key = {
            "step7_process": "step7_input_artifactid",
            "step6_process": "step6_input_artifactid",
            "step5_process": "step5_input_artifactids",
        }[key]
        if process is None:
            print(f"  {key}: <missing>")
            continue
        print(
            f"  {key}: luid={process['luid']} processid={process['processid']} "
            f"status={process['workstatus']} input={payload[input_key]}"
        )

    row = payload.get("row")
    if row:
        print(
            "  row:"
            f" run_id={row.get('Run ID')}"
            f" instrument={row.get('Instrument')}"
            f" sample_count={row.get('Sample Count')}"
            f" read_length={row.get('Read Length')}"
            f" operator={row.get('Operator')}"
            f" experiment_name={row.get('Experiment Name')}"
        )
        print(
            "       "
            f"cassette={row.get('Casette Type')}"
            f" index_cycles={row.get('Index Cycles')}"
            f" loading_pm={row.get('Loading pM')}"
            f" diluted_denatured_ul={row.get('Diluted Denatured (uL)')}"
        )
        print(
            "       "
            f"avg_fragment_size={row.get('Avg Fragment Size')}"
            f" combined_pool={row.get('Combined Pool')}"
            f" phix_loaded_percent={row.get('Phix Loaded (%)')}"
            f" phix_aligned_percent={row.get('Phix Aligned (%)')}"
        )
        print(
            "       "
            f"cluster_density={row.get('Cluster Density')}"
            f" yield_total={row.get('Yield Total')}"
            f" qv30_r1={row.get('QV30 R1')}"
            f" qv30_r2={row.get('QV30 R2')}"
            f" pf_reads={row.get('PF Reads')}"
        )
        print(
            "       "
            f"species={row.get('Species')}"
            f" comment={row.get('Comment')}"
        )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Debug the direct Postgres sequencing-lineage traversal."
    )
    parser.add_argument(
        "--type-id",
        action="append",
        required=True,
        help="Sequencing process type id. Repeat or pass a comma-separated list.",
    )
    parser.add_argument(
        "--seq-limsid",
        action="append",
        default=[],
        help="Optional sequencing process LIMS id filter. Repeat to inspect specific runs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of lineages to print after filtering.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of a compact human-readable summary.",
    )
    args = parser.parse_args(argv)

    sequencing_type_ids = _parse_type_ids(args.type_id)
    seq_limsid_filter = {value.strip() for value in args.seq_limsid if value.strip()}

    with create_session() as session:
        lineages = build_sequencing_lineages(session, sequencing_type_ids)
        rows = build_sequencing_run_rows(session, sequencing_type_ids)

    rows_by_limsid = {row.get("seq_limsid"): row for row in rows}

    if seq_limsid_filter:
        lineages = [
            lineage
            for lineage in lineages
            if lineage.sequencing_process.luid in seq_limsid_filter
        ]

    if args.limit >= 0:
        lineages = lineages[: args.limit]

    payloads = [
        _lineage_to_payload(
            lineage,
            rows_by_limsid.get(lineage.sequencing_process.luid),
        )
        for lineage in lineages
    ]

    if args.json:
        print(json.dumps(payloads, indent=2, ensure_ascii=True))
        return 0

    for payload in payloads:
        _print_human_readable(payload)

    if not payloads:
        print("No matching sequencing lineages found.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
