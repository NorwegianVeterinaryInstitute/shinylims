"""
Sequencing queries: builds sequencing run rows by walking the artifact lineage
directly in Clarity Postgres.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shinylims.integrations.clarity_models import (
    ArtifactSampleMap,
    ArtifactUdfView,
    OutputMapping,
    Process,
    ProcessIOTracker,
    Project,
    ResultFile,
    Sample,
    SampleUdfView,
)
from shinylims.integrations.queries._shared import (
    ProcessRecord,
    _load_artifact_udfs,
    _load_operator_initials,
    _load_process_udfs,
    _log_pg_timing,
    _process_record,
)

SEQUENCING_ARTIFACT_UDFS = {
    "% Aligned R1",
    "% Bases >=Q30 R1",
    "% Bases >=Q30 R2",
    "Application",
    "Average Size - bp",
    "Cluster Density (K/mm^2) R1",
    "Experiment Name",
    "Reads PF (M) R1",
    "Yield PF (Gb) R1",
    "Yield PF (Gb) R2",
}

SEQUENCING_PROCESS_UDFS = {
    "1. Library Pool Denatured 20pM (µl)",
    "Comment",
    "Final Library Loading (pM)",
    "Index Cycles",
    "PhiX / library spike-in (%)",
    "Read 1 Cycles",
    "Read 2 Cycles",
    "Run ID",
    "Volume 20pM Denat Sample (µl)",
}


@dataclass(frozen=True, slots=True)
class SequencingLineage:
    """Resolved artifact lineage for one sequencing process."""

    sequencing_process: ProcessRecord
    representative_input_artifactid: int
    step7_process: ProcessRecord | None
    step6_process: ProcessRecord | None
    step5_process: ProcessRecord | None
    step7_input_artifactid: int | None
    step6_input_artifactid: int | None
    step5_input_artifactids: tuple[int, ...]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _coerce_float(value: str | float | int | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: str | float | int | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_run_id(run_id: str | None) -> tuple[str | None, str | None]:
    if not run_id:
        return None, None
    parts = re.split(r"[_-]", run_id)
    if len(parts) > 3:
        return parts[1], parts[2]
    return None, None


def _kit_type_from_application(application: str | None) -> str | None:
    if not application:
        return None
    app = application.lower()
    if "v3" in app:
        return "MiSeq Reagent kit v3 (600 cycles)"
    if "v2 nano" in app:
        return "MiSeq Reagent Nano Kit v2 (500 cycles)"
    if "v2 micro" in app:
        return "MiSeq reagent kit v2 mikro (300 cycles)"
    if "nextseq mo" in app:
        return "Mid Output kit"
    if "nextseq ho" in app:
        return "High Output kit"
    if "custom" in app:
        return "Not Available (Custom application)"
    return application


def _first_input_artifact_by_process(session: Session, process_ids: list[int]) -> dict[int, int]:
    if not process_ids:
        return {}

    rows = session.execute(
        select(
            ProcessIOTracker.processid,
            ProcessIOTracker.trackerid,
            ProcessIOTracker.inputartifactid,
        )
        .where(ProcessIOTracker.processid.in_(process_ids))
        .where(ProcessIOTracker.inputartifactid.is_not(None))
        .order_by(ProcessIOTracker.processid, ProcessIOTracker.trackerid)
    ).all()

    result: dict[int, int] = {}
    for processid, _, artifactid in rows:
        if processid not in result:
            result[processid] = artifactid
    return result


def _all_input_artifacts_by_process(session: Session, process_ids: list[int]) -> dict[int, list[int]]:
    if not process_ids:
        return {}

    rows = session.execute(
        select(
            ProcessIOTracker.processid,
            ProcessIOTracker.trackerid,
            ProcessIOTracker.inputartifactid,
        )
        .where(ProcessIOTracker.processid.in_(process_ids))
        .where(ProcessIOTracker.inputartifactid.is_not(None))
        .order_by(ProcessIOTracker.processid, ProcessIOTracker.trackerid)
    ).all()

    result: dict[int, list[int]] = defaultdict(list)
    for processid, _, artifactid in rows:
        result[processid].append(artifactid)
    return dict(result)


def _representative_input_by_sequencing_process(
    session: Session,
    sequencing_process_ids: list[int],
) -> dict[int, int]:
    if not sequencing_process_ids:
        return {}

    rows = session.execute(
        select(
            Process.processid,
            ProcessIOTracker.trackerid,
            ProcessIOTracker.inputartifactid,
        )
        .join(ProcessIOTracker, ProcessIOTracker.processid == Process.processid)
        .join(OutputMapping, OutputMapping.trackerid == ProcessIOTracker.trackerid)
        .join(ResultFile, ResultFile.artifactid == OutputMapping.outputartifactid)
        .where(Process.processid.in_(sequencing_process_ids))
        .where(ProcessIOTracker.inputartifactid.is_not(None))
        .order_by(Process.processid, ProcessIOTracker.trackerid)
    ).all()

    result: dict[int, int] = {}
    for processid, _, artifactid in rows:
        if processid not in result:
            result[processid] = artifactid
    return result


def _producer_by_artifact(session: Session, artifact_ids: list[int]) -> dict[int, ProcessRecord]:
    if not artifact_ids:
        return {}

    rows = session.execute(
        select(
            OutputMapping.outputartifactid.label("artifactid"),
            Process.processid,
            Process.luid,
            Process.daterun,
            Process.workstatus,
            Process.techid,
            Process.typeid,
        )
        .join(ProcessIOTracker, ProcessIOTracker.trackerid == OutputMapping.trackerid)
        .join(Process, Process.processid == ProcessIOTracker.processid)
        .where(OutputMapping.outputartifactid.in_(artifact_ids))
        .order_by(OutputMapping.outputartifactid, Process.processid)
    ).all()

    result: dict[int, ProcessRecord] = {}
    for row in rows:
        artifactid = row.artifactid
        candidate = _process_record(row)
        existing = result.get(artifactid)
        if existing is None or (existing.workstatus != "COMPLETE" and candidate.workstatus == "COMPLETE"):
            result[artifactid] = candidate
    return result


def _load_artifact_sample_context(
    session: Session,
    artifact_ids: list[int],
) -> dict[int, dict[str, Any]]:
    if not artifact_ids:
        return {}

    species_udf = SampleUdfView.__table__.alias("species_udf")
    rows = session.execute(
        select(
            ArtifactSampleMap.artifactid,
            Sample.processid,
            Sample.sampleid,
            Project.name.label("project_name"),
            species_udf.c.udfvalue.label("species"),
        )
        .join(Sample, Sample.processid == ArtifactSampleMap.processid)
        .join(Project, Project.projectid == Sample.projectid)
        .outerjoin(
            species_udf,
            (species_udf.c.sampleid == Sample.sampleid) & (species_udf.c.udfname == "Species"),
        )
        .where(ArtifactSampleMap.artifactid.in_(artifact_ids))
    ).all()

    species_by_artifact: dict[int, list[str]] = defaultdict(list)
    sample_counts: dict[int, set[int]] = defaultdict(set)
    for artifactid, sample_processid, _, project_name, species in rows:
        sample_counts[artifactid].add(sample_processid)
        if species and species != "Not Applicable":
            if species not in species_by_artifact[artifactid]:
                species_by_artifact[artifactid].append(species)
        elif project_name and project_name not in species_by_artifact[artifactid]:
            species_by_artifact[artifactid].append(project_name)

    result: dict[int, dict[str, Any]] = {}
    for artifactid in artifact_ids:
        result[artifactid] = {
            "species": ", ".join(species_by_artifact.get(artifactid, [])) or None,
            "sample_count": len(sample_counts.get(artifactid, set())),
        }
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_sequencing_processes(
    session: Session,
    sequencing_type_ids: list[int],
) -> list[ProcessRecord]:
    """Return sequencing processes that should anchor the lineage walk."""
    rows = session.execute(
        select(
            Process.processid,
            Process.luid,
            Process.daterun,
            Process.workstatus,
            Process.techid,
            Process.typeid,
        )
        .where(Process.typeid.in_(sequencing_type_ids))
        .order_by(Process.processid)
    ).all()
    return [_process_record(row) for row in rows]


def build_sequencing_lineages(
    session: Session,
    sequencing_type_ids: list[int],
) -> list[SequencingLineage]:
    """Walk the actual artifact chain upstream from sequencing processes."""
    sequencing_processes = get_sequencing_processes(session, sequencing_type_ids)
    if not sequencing_processes:
        return []

    seq_ids = [process.processid for process in sequencing_processes]
    representative_inputs = _representative_input_by_sequencing_process(session, seq_ids)

    step7_artifact_ids = sorted(set(representative_inputs.values()))
    step7_by_artifact = _producer_by_artifact(session, step7_artifact_ids)

    step7_process_ids = [process.processid for process in step7_by_artifact.values()]
    step7_input_by_process = _first_input_artifact_by_process(session, step7_process_ids)

    step6_artifact_ids = sorted(set(step7_input_by_process.values()))
    step6_by_artifact = _producer_by_artifact(session, step6_artifact_ids)

    step6_process_ids = [process.processid for process in step6_by_artifact.values()]
    step6_input_by_process = _first_input_artifact_by_process(session, step6_process_ids)

    step5_artifact_ids = sorted(set(step6_input_by_process.values()))
    step5_by_artifact = _producer_by_artifact(session, step5_artifact_ids)

    step5_process_ids = sorted({process.processid for process in step5_by_artifact.values()})
    step5_all_inputs_by_process = _all_input_artifacts_by_process(session, step5_process_ids)

    result: list[SequencingLineage] = []
    for sequencing_process in sequencing_processes:
        representative_input_artifactid = representative_inputs.get(sequencing_process.processid)
        if representative_input_artifactid is None:
            continue

        step7_process = step7_by_artifact.get(representative_input_artifactid)
        step7_input_artifactid = (
            step7_input_by_process.get(step7_process.processid) if step7_process else None
        )
        step6_process = (
            step6_by_artifact.get(step7_input_artifactid) if step7_input_artifactid is not None else None
        )
        step6_input_artifactid = (
            step6_input_by_process.get(step6_process.processid) if step6_process else None
        )
        step5_process = (
            step5_by_artifact.get(step6_input_artifactid) if step6_input_artifactid is not None else None
        )
        step5_input_artifactids = tuple(
            step5_all_inputs_by_process.get(step5_process.processid, []) if step5_process else []
        )

        result.append(
            SequencingLineage(
                sequencing_process=sequencing_process,
                representative_input_artifactid=representative_input_artifactid,
                step7_process=step7_process,
                step6_process=step6_process,
                step5_process=step5_process,
                step7_input_artifactid=step7_input_artifactid,
                step6_input_artifactid=step6_input_artifactid,
                step5_input_artifactids=step5_input_artifactids,
            )
        )
    return result


def build_sequencing_run_rows(
    session: Session,
    sequencing_type_ids: list[int],
) -> list[dict[str, Any]]:
    """Build sequencing rows with display-ready column names."""
    lineages = build_sequencing_lineages(session, sequencing_type_ids)
    if not lineages:
        return []

    process_ids: set[int] = set()
    artifact_ids: set[int] = set()
    representative_artifact_ids: list[int] = []

    for lineage in lineages:
        process_ids.add(lineage.sequencing_process.processid)
        artifact_ids.add(lineage.representative_input_artifactid)
        representative_artifact_ids.append(lineage.representative_input_artifactid)
        for process_record in (lineage.step7_process, lineage.step6_process, lineage.step5_process):
            if process_record is not None:
                process_ids.add(process_record.processid)
        for artifactid in (
            lineage.step7_input_artifactid,
            lineage.step6_input_artifactid,
            *lineage.step5_input_artifactids,
        ):
            if artifactid is not None:
                artifact_ids.add(artifactid)

    process_udfs = _load_process_udfs(session, sorted(process_ids), SEQUENCING_PROCESS_UDFS)
    artifact_udfs = _load_artifact_udfs(session, sorted(artifact_ids), SEQUENCING_ARTIFACT_UDFS)
    operator_initials = _load_operator_initials(session, sorted(process_ids))
    representative_sample_context = _load_artifact_sample_context(session, representative_artifact_ids)

    rows: list[dict[str, Any]] = []
    for lineage in lineages:
        seq_udfs = process_udfs.get(lineage.sequencing_process.processid, {})
        step7_udfs = process_udfs.get(lineage.step7_process.processid, {}) if lineage.step7_process else {}
        step6_udfs = process_udfs.get(lineage.step6_process.processid, {}) if lineage.step6_process else {}
        representative_udfs = artifact_udfs.get(lineage.representative_input_artifactid, {})
        step6_input_udfs = (
            artifact_udfs.get(lineage.step6_input_artifactid, {})
            if lineage.step6_input_artifactid is not None
            else {}
        )

        run_id = seq_udfs.get("Run ID")
        instrument, run_number = _parse_run_id(run_id)

        pool_count = len(lineage.step5_input_artifactids)
        combined_pool = "Yes" if pool_count > 1 else "No" if pool_count == 1 else "NA"

        avg_fragment_size = step6_input_udfs.get("Average Size - bp")
        if not avg_fragment_size:
            upstream_sizes = []
            for artifactid in lineage.step5_input_artifactids:
                value = artifact_udfs.get(artifactid, {}).get("Average Size - bp")
                if value and value not in upstream_sizes:
                    upstream_sizes.append(value)
            if upstream_sizes:
                avg_fragment_size = " + ".join(upstream_sizes)

        yield_r1 = _coerce_float(representative_udfs.get("Yield PF (Gb) R1"))
        yield_r2 = _coerce_float(representative_udfs.get("Yield PF (Gb) R2"))
        total_yield = yield_r1 + yield_r2 if yield_r1 is not None and yield_r2 is not None else None

        operator = None
        if lineage.step7_process is not None:
            operator = operator_initials.get(lineage.step7_process.processid)
        if operator is None:
            operator = operator_initials.get(lineage.sequencing_process.processid)

        read_1_cycles = step7_udfs.get("Read 1 Cycles")
        read_2_cycles = step7_udfs.get("Read 2 Cycles")
        read_length = None
        if read_1_cycles and read_2_cycles:
            read_length = (
                f"2 x {read_1_cycles}" if read_1_cycles == read_2_cycles
                else f"{read_1_cycles} + {read_2_cycles}"
            )

        sample_context = representative_sample_context.get(lineage.representative_input_artifactid, {})

        rows.append(
            {
                "seq_limsid": lineage.sequencing_process.luid,
                "Run ID": run_id,
                "Instrument": instrument,
                "Run Number": run_number,
                "Seq Date": lineage.sequencing_process.daterun,
                "Operator": operator,
                "Species": sample_context.get("species"),
                "Experiment Name": representative_udfs.get("Experiment Name"),
                "Casette Type": _kit_type_from_application(representative_udfs.get("Application")),
                "Read Length": read_length,
                "Index Cycles": _coerce_int(step7_udfs.get("Index Cycles")),
                "Sample Count": sample_context.get("sample_count"),
                "Loading pM": _coerce_float(step6_udfs.get("Final Library Loading (pM)")),
                "Diluted Denatured (uL)": _coerce_float(
                    step6_udfs.get("Volume 20pM Denat Sample (µl)")
                    or step6_udfs.get("1. Library Pool Denatured 20pM (µl)")
                ),
                "Avg Fragment Size": avg_fragment_size,
                "Combined Pool": combined_pool,
                "Phix Loaded (%)": _coerce_float(step6_udfs.get("PhiX / library spike-in (%)")),
                "Phix Aligned (%)": _coerce_float(representative_udfs.get("% Aligned R1")),
                "Cluster Density": _coerce_float(representative_udfs.get("Cluster Density (K/mm^2) R1")),
                "Yield Total": total_yield,
                "QV30 R1": _coerce_float(representative_udfs.get("% Bases >=Q30 R1")),
                "QV30 R2": _coerce_float(representative_udfs.get("% Bases >=Q30 R2")),
                "PF Reads": _coerce_float(representative_udfs.get("Reads PF (M) R1")),
                "Comment": seq_udfs.get("Comment"),
            }
        )

    return rows


