"""
Sample query: builds sample rows directly from the Clarity Postgres schema.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from shinylims.integrations.clarity_models import (
    Analyte,
    Artifact,
    ArtifactLabelMap,
    ArtifactSampleMap,
    Container,
    ContainerPlacement,
    Lab,
    OutputMapping,
    Process,
    ProcessIOTracker,
    Project,
    ReagentLabel,
    Researcher,
    Sample,
    SampleUdfView,
)
from shinylims.integrations.queries._shared import (
    PROJECT_IDS_EXCLUDED_FROM_APP,
    ProcessRecord,
    _container_state_label,
    _display_name,
    _load_artifact_udfs,
    _load_process_udfs,
    _process_record,
)

ALLOWED_SAMPLE_TYPES = (
    "WGS colonies - freezer",
    "WGS colonies - dish",
    "WGS DNA",
    "Prepared Pool",
    "Prepared Libraries",
)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _join_unique_non_empty(values: list[str | None]) -> str | None:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return ", ".join(items) if items else None


def _split_luid_list(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [part.strip() for part in str(raw_value).split(",") if part.strip()]


def _clean_genus_value(genus_raw: str | None) -> str:
    if not genus_raw:
        return ""
    genus = re.sub(r"[\s\u00A0\u3000]+", "", genus_raw)
    genus = re.sub(r"(?i)\s*spp$", "", genus)
    genus = re.sub(r"[^A-Za-z0-9_-]", "", genus)
    return genus


def _build_nird_filename(
    *,
    run_id: str | None,
    project_account: str | None,
    genus_raw: str | None,
    nird_directory: str | None,
) -> str | None:
    if not run_id or not project_account:
        return None

    match = re.match(r"^\d{6}_[A-Z]+\d+", run_id)
    run_id_condensed = match.group(0) if match else None
    if not run_id_condensed:
        return None

    run_date_int = int(run_id_condensed[:6])
    genus_clean = _clean_genus_value(genus_raw)

    if run_date_int <= 241206:
        suffix = f"{run_id_condensed}.{project_account}.x.tar"
    elif run_date_int < 251017:
        suffix = f"{run_id_condensed}.{project_account}.tar"
    elif genus_clean:
        suffix = f"{run_id_condensed}.{project_account}_{genus_clean}.tar"
    else:
        suffix = f"{run_id_condensed}.{project_account}.tar"

    if nird_directory:
        return f"{nird_directory}{suffix}"
    return suffix


def _format_well_label(x_position: int | None, y_position: int | None) -> str | None:
    if x_position is None or y_position is None or y_position < 0:
        return None
    return f"{chr(65 + y_position)}:{x_position + 1}"


def _format_storage_box_html(container_name: str | None, container_state: str | None) -> str | None:
    if not container_name:
        return None
    if container_state == "Discarded":
        return f'<span style="color: red; font-weight: bold;">{container_name} (discarded)</span>'
    return container_name


def _load_sample_udf_rows(session: Session, open_projects_only: bool) -> list[Any]:
    udf_subquery = (
        select(
            SampleUdfView.sampleid.label("sampleid"),
            func.max(case((SampleUdfView.udfname == "Progress", SampleUdfView.udfvalue))).label("progress"),
            func.max(case((SampleUdfView.udfname == "Species", SampleUdfView.udfvalue))).label("species_name"),
            func.max(case((SampleUdfView.udfname == "Project Account", SampleUdfView.udfvalue))).label("project_account"),
            func.max(case((SampleUdfView.udfname == "Sample Type", SampleUdfView.udfvalue))).label("sample_type"),
            func.max(case((SampleUdfView.udfname == "Gram Stain", SampleUdfView.udfvalue))).label("gram_stain"),
            func.max(case((SampleUdfView.udfname == "NIRD Location", SampleUdfView.udfvalue))).label("nird_location"),
            func.max(case((SampleUdfView.udfname == "Genus/VIGAS Project", SampleUdfView.udfvalue))).label("genus"),
            func.max(case((SampleUdfView.udfname == "nd_limsid", SampleUdfView.udfvalue))).label("nd_limsid"),
            func.max(case((SampleUdfView.udfname == "qubit_limsid", SampleUdfView.udfvalue))).label("qubit_limsid"),
            func.max(case((SampleUdfView.udfname == "prep_limsid", SampleUdfView.udfvalue))).label("prep_limsid"),
            func.max(case((SampleUdfView.udfname == "seq_limsid", SampleUdfView.udfvalue))).label("seq_limsid"),
            func.max(case((SampleUdfView.udfname == "billed_limsid", SampleUdfView.udfvalue))).label("billed_limsid"),
            func.max(case((SampleUdfView.udfname == "extractions_limsid", SampleUdfView.udfvalue))).label("extractions_limsid"),
            func.max(case((SampleUdfView.udfname == "Increased Pooling (%)", SampleUdfView.udfvalue))).label("increased_pooling"),
            func.max(case((SampleUdfView.udfname == "Extraction Number", SampleUdfView.udfvalue))).label("sample_extraction_number"),
        )
        .group_by(SampleUdfView.sampleid)
        .subquery()
    )

    stmt = (
        select(
            Sample.processid.label("sample_processid"),
            Sample.sampleid,
            Sample.datereceived,
            Sample.controltypeid,
            Process.luid.label("limsid"),
            Project.luid.label("project_limsid"),
            Project.closedate,
            Project.name.label("project_name"),
            Researcher.firstname,
            Researcher.lastname,
            Lab.name.label("lab_name"),
            Sample.name.label("sample_name"),
            udf_subquery.c.progress,
            udf_subquery.c.species_name,
            udf_subquery.c.project_account,
            udf_subquery.c.sample_type,
            udf_subquery.c.gram_stain,
            udf_subquery.c.nird_location,
            udf_subquery.c.genus,
            udf_subquery.c.nd_limsid,
            udf_subquery.c.qubit_limsid,
            udf_subquery.c.prep_limsid,
            udf_subquery.c.seq_limsid,
            udf_subquery.c.billed_limsid,
            udf_subquery.c.extractions_limsid,
            udf_subquery.c.increased_pooling,
            udf_subquery.c.sample_extraction_number,
        )
        .join(Process, Process.processid == Sample.processid)
        .join(Project, Project.projectid == Sample.projectid)
        .outerjoin(Researcher, Researcher.researcherid == Project.researcherid)
        .outerjoin(Lab, Lab.labid == Researcher.labid)
        .outerjoin(udf_subquery, udf_subquery.c.sampleid == Sample.sampleid)
        .where(udf_subquery.c.sample_type.in_(ALLOWED_SAMPLE_TYPES))
    )
    if open_projects_only:
        stmt = stmt.where(Project.closedate.is_(None))
    return session.execute(stmt.order_by(Sample.processid)).all()


def _load_processes_by_luid(session: Session, process_luids: list[str]) -> dict[str, ProcessRecord]:
    if not process_luids:
        return {}

    rows = session.execute(
        select(
            Process.processid,
            Process.luid,
            Process.daterun,
            Process.workstatus,
            Process.techid,
            Process.typeid,
        )
        .where(Process.luid.in_(process_luids))
    ).all()

    result: dict[str, ProcessRecord] = {}
    for row in rows:
        if row.luid:
            result[row.luid] = _process_record(row)
    return result


def _load_process_sample_output_analytes(
    session: Session,
    process_ids: list[int],
) -> dict[tuple[int, int], list[int]]:
    if not process_ids:
        return {}

    rows = session.execute(
        select(
            ProcessIOTracker.processid,
            ArtifactSampleMap.processid.label("sample_processid"),
            OutputMapping.outputartifactid,
        )
        .join(OutputMapping, OutputMapping.trackerid == ProcessIOTracker.trackerid)
        .join(Analyte, Analyte.artifactid == OutputMapping.outputartifactid)
        .join(ArtifactSampleMap, ArtifactSampleMap.artifactid == OutputMapping.outputartifactid)
        .where(ProcessIOTracker.processid.in_(process_ids))
        .order_by(ProcessIOTracker.processid, ArtifactSampleMap.processid, OutputMapping.outputartifactid)
    ).all()

    result: dict[tuple[int, int], list[int]] = defaultdict(list)
    for processid, sample_processid, artifactid in rows:
        result[(processid, sample_processid)].append(artifactid)
    return dict(result)


def _load_process_sample_input_artifacts(
    session: Session,
    process_ids: list[int],
) -> dict[tuple[int, int], list[int]]:
    if not process_ids:
        return {}

    rows = session.execute(
        select(
            ProcessIOTracker.processid,
            ArtifactSampleMap.processid.label("sample_processid"),
            ProcessIOTracker.inputartifactid,
        )
        .join(ArtifactSampleMap, ArtifactSampleMap.artifactid == ProcessIOTracker.inputartifactid)
        .where(ProcessIOTracker.processid.in_(process_ids))
        .where(ProcessIOTracker.inputartifactid.is_not(None))
        .order_by(ProcessIOTracker.processid, ArtifactSampleMap.processid, ProcessIOTracker.inputartifactid)
    ).all()

    result: dict[tuple[int, int], list[int]] = defaultdict(list)
    for processid, sample_processid, artifactid in rows:
        result[(processid, sample_processid)].append(artifactid)
    return dict(result)


def _load_original_artifacts_by_sample(
    session: Session,
    sample_process_ids: list[int],
) -> dict[int, int]:
    if not sample_process_ids:
        return {}

    rows = session.execute(
        select(
            ArtifactSampleMap.processid.label("sample_processid"),
            Artifact.artifactid,
        )
        .join(Artifact, Artifact.artifactid == ArtifactSampleMap.artifactid)
        .where(ArtifactSampleMap.processid.in_(sample_process_ids))
        .where(Artifact.isoriginal.is_(True))
        .order_by(ArtifactSampleMap.processid, Artifact.artifactid)
    ).all()

    result: dict[int, int] = {}
    for sample_processid, artifactid in rows:
        if sample_processid not in result:
            result[sample_processid] = artifactid
    return result


def _load_artifact_locations(
    session: Session,
    artifact_ids: list[int],
) -> dict[int, dict[str, str | None]]:
    if not artifact_ids:
        return {}

    rows = session.execute(
        select(
            ContainerPlacement.processartifactid,
            Container.name,
            Container.stateid,
            ContainerPlacement.wellxposition,
            ContainerPlacement.wellyposition,
        )
        .join(Container, Container.containerid == ContainerPlacement.containerid)
        .where(ContainerPlacement.processartifactid.in_(artifact_ids))
    ).all()

    result: dict[int, dict[str, str | None]] = {}
    for artifactid, container_name, stateid, x_position, y_position in rows:
        result[artifactid] = {
            "container_name": container_name,
            "container_state": _container_state_label(stateid),
            "well_label": _format_well_label(x_position, y_position),
        }
    return result


def _load_artifact_reagent_labels(
    session: Session,
    artifact_ids: list[int],
) -> dict[int, list[str]]:
    if not artifact_ids:
        return {}

    rows = session.execute(
        select(
            ArtifactLabelMap.artifactid,
            ReagentLabel.name,
        )
        .join(ReagentLabel, ReagentLabel.labelid == ArtifactLabelMap.labelid)
        .where(ArtifactLabelMap.artifactid.in_(artifact_ids))
        .order_by(ArtifactLabelMap.artifactid, ReagentLabel.name)
    ).all()

    result: dict[int, list[str]] = defaultdict(list)
    for artifactid, label_name in rows:
        if label_name and label_name not in result[artifactid]:
            result[artifactid].append(label_name)
    return dict(result)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_sample_rows(
    session: Session,
    *,
    open_projects_only: bool = True,
) -> list[dict[str, Any]]:
    """Build sample rows with display-ready column names."""
    import time
    from shinylims.integrations.queries._shared import _log_pg_timing, _pg_timing_enabled

    total_started_at = time.perf_counter()

    stage_started_at = time.perf_counter()
    sample_rows = _load_sample_udf_rows(session, open_projects_only=open_projects_only)
    _log_pg_timing(
        "build_sample_rows.load_sample_udf_rows",
        stage_started_at,
        row_count=len(sample_rows),
        open_projects_only=open_projects_only,
    )
    if not sample_rows:
        _log_pg_timing("build_sample_rows.total", total_started_at, result_count=0)
        return []

    stage_started_at = time.perf_counter()
    sample_process_ids = [row.sample_processid for row in sample_rows]

    referenced_process_luids: set[str] = set()
    for row in sample_rows:
        for value in (
            row.billed_limsid,
            row.seq_limsid,
            row.qubit_limsid,
            row.prep_limsid,
            row.extractions_limsid,
        ):
            referenced_process_luids.update(_split_luid_list(value))
    _log_pg_timing(
        "build_sample_rows.collect_referenced_processes",
        stage_started_at,
        sample_process_count=len(sample_process_ids),
        referenced_luid_count=len(referenced_process_luids),
    )

    stage_started_at = time.perf_counter()
    processes_by_luid = _load_processes_by_luid(session, sorted(referenced_process_luids))
    referenced_process_ids = sorted({process.processid for process in processes_by_luid.values()})
    _log_pg_timing(
        "build_sample_rows.load_processes_by_luid",
        stage_started_at,
        process_count=len(processes_by_luid),
        referenced_process_id_count=len(referenced_process_ids),
    )

    stage_started_at = time.perf_counter()
    process_udfs = _load_process_udfs(
        session,
        referenced_process_ids,
        {"Faktura ID (fra økonomi)", "Run ID"},
    )
    process_output_artifacts = _load_process_sample_output_analytes(session, referenced_process_ids)
    process_input_artifacts = _load_process_sample_input_artifacts(session, referenced_process_ids)
    original_artifacts_by_sample = _load_original_artifacts_by_sample(session, sample_process_ids)
    _log_pg_timing(
        "build_sample_rows.load_process_and_artifact_maps",
        stage_started_at,
        process_udf_count=len(process_udfs),
        output_artifact_keys=len(process_output_artifacts),
        input_artifact_keys=len(process_input_artifacts),
        original_artifact_count=len(original_artifacts_by_sample),
    )

    stage_started_at = time.perf_counter()
    artifact_ids: set[int] = set(original_artifacts_by_sample.values())
    for artifact_list in process_output_artifacts.values():
        artifact_ids.update(artifact_list)
    for artifact_list in process_input_artifacts.values():
        artifact_ids.update(artifact_list)
    artifact_id_list = sorted(artifact_ids)
    _log_pg_timing(
        "build_sample_rows.collect_artifact_ids",
        stage_started_at,
        artifact_count=len(artifact_id_list),
    )

    stage_started_at = time.perf_counter()
    artifact_udfs = _load_artifact_udfs(
        session,
        artifact_id_list,
        {
            "Concentration Absorbance (ng/µl)",
            "A260/280 ratio",
            "A260/230 ratio",
            "Concentration Fluorescence (ng/µl)",
            "Experiment Name",
            "Extraction Number",
            "Price (NOK)",
            "Analysis Description",
        },
    )
    artifact_locations = _load_artifact_locations(session, artifact_id_list)
    artifact_reagent_labels = _load_artifact_reagent_labels(session, artifact_id_list)
    _log_pg_timing(
        "build_sample_rows.load_artifact_metadata",
        stage_started_at,
        artifact_udf_count=len(artifact_udfs),
        artifact_location_count=len(artifact_locations),
        artifact_reagent_label_count=len(artifact_reagent_labels),
    )

    stage_started_at = time.perf_counter()
    results: list[dict[str, Any]] = []
    for row in sample_rows:
        if row.project_limsid in PROJECT_IDS_EXCLUDED_FROM_APP:
            continue
        if row.controltypeid is not None or row.sample_type == "Controls":
            continue

        is_prepared = row.sample_type in {"Prepared Pool", "Prepared Libraries"}
        is_wgs = row.sample_type in {"WGS colonies - freezer", "WGS colonies - dish", "WGS DNA"}
        if not (is_prepared or is_wgs):
            continue

        absorbance_values: list[str] = []
        a260_280_values: list[str] = []
        a260_230_values: list[str] = []
        fluorescence_values: list[str] = []
        storage_box_values: list[str] = []
        storage_box_formatted_values: list[str] = []
        storage_well_values: list[str] = []
        experiment_names: list[str] = []
        reagent_labels: list[str] = []
        invoice_ids: list[str] = []
        price_values: list[str] = []
        billing_descriptions: list[str] = []
        extraction_numbers: list[str] = []
        nird_filenames: list[str] = []

        for billed_luid in _split_luid_list(row.billed_limsid):
            if billed_luid == "utenfor LIMS":
                continue
            process_record = processes_by_luid.get(billed_luid)
            if process_record is None:
                continue
            billed_udfs = process_udfs.get(process_record.processid, {})
            invoice_id = billed_udfs.get("Faktura ID (fra økonomi)")
            if invoice_id:
                invoice_ids.append(invoice_id)
            artifact_list = process_output_artifacts.get((process_record.processid, row.sample_processid), [])
            if artifact_list:
                billed_artifact_udfs = artifact_udfs.get(artifact_list[0], {})
                if billed_artifact_udfs.get("Price (NOK)"):
                    price_values.append(billed_artifact_udfs["Price (NOK)"])
                if billed_artifact_udfs.get("Analysis Description"):
                    billing_descriptions.append(billed_artifact_udfs["Analysis Description"])

        for seq_luid in _split_luid_list(row.seq_limsid):
            process_record = processes_by_luid.get(seq_luid)
            if process_record is None:
                continue
            run_id = process_udfs.get(process_record.processid, {}).get("Run ID")
            file_name = _build_nird_filename(
                run_id=run_id,
                project_account=row.project_account,
                genus_raw=row.genus,
                nird_directory=row.nird_location,
            )
            if file_name:
                nird_filenames.append(file_name)

        if is_wgs:
            for qubit_luid in _split_luid_list(row.qubit_limsid):
                process_record = processes_by_luid.get(qubit_luid)
                if process_record is None:
                    continue
                artifact_list = process_input_artifacts.get((process_record.processid, row.sample_processid), [])
                if not artifact_list:
                    continue
                for artifactid in artifact_list:
                    artifact_udf_map = artifact_udfs.get(artifactid, {})
                    if artifact_udf_map.get("Concentration Absorbance (ng/µl)"):
                        absorbance_values.append(artifact_udf_map["Concentration Absorbance (ng/µl)"])
                    if artifact_udf_map.get("A260/280 ratio"):
                        a260_280_values.append(artifact_udf_map["A260/280 ratio"])
                    if artifact_udf_map.get("A260/230 ratio"):
                        a260_230_values.append(artifact_udf_map["A260/230 ratio"])
                    if artifact_udf_map.get("Concentration Fluorescence (ng/µl)"):
                        fluorescence_values.append(artifact_udf_map["Concentration Fluorescence (ng/µl)"])

                    location = artifact_locations.get(artifactid, {})
                    container_name = location.get("container_name")
                    if container_name:
                        storage_box_values.append(container_name)
                        storage_box_formatted = _format_storage_box_html(
                            container_name,
                            location.get("container_state"),
                        )
                        if storage_box_formatted:
                            storage_box_formatted_values.append(storage_box_formatted)
                    if location.get("well_label"):
                        storage_well_values.append(location["well_label"])

            for prep_luid in _split_luid_list(row.prep_limsid):
                process_record = processes_by_luid.get(prep_luid)
                if process_record is None:
                    continue
                artifact_list = process_output_artifacts.get((process_record.processid, row.sample_processid), [])
                if not artifact_list:
                    continue
                prep_udfs = artifact_udfs.get(artifact_list[0], {})
                if prep_udfs.get("Experiment Name"):
                    experiment_names.append(prep_udfs["Experiment Name"])
                for artifactid in artifact_list:
                    reagent_labels.extend(artifact_reagent_labels.get(artifactid, []))

            for extraction_luid in _split_luid_list(row.extractions_limsid):
                process_record = processes_by_luid.get(extraction_luid)
                if process_record is None:
                    continue
                artifact_list = process_output_artifacts.get((process_record.processid, row.sample_processid), [])
                for artifactid in artifact_list:
                    extraction_value = artifact_udfs.get(artifactid, {}).get("Extraction Number")
                    if extraction_value:
                        extraction_numbers.append(extraction_value)

            extraction_number = (
                row.sample_extraction_number if row.sample_type == "WGS DNA"
                else ", ".join(extraction_numbers) if extraction_numbers else None
            )
        else:
            original_artifactid = original_artifacts_by_sample.get(row.sample_processid)
            if original_artifactid is not None:
                prepared_udfs = artifact_udfs.get(original_artifactid, {})
                if prepared_udfs.get("Experiment Name"):
                    experiment_names.append(prepared_udfs["Experiment Name"])
                reagent_labels.extend(artifact_reagent_labels.get(original_artifactid, []))
                location = artifact_locations.get(original_artifactid, {})
                container_name = location.get("container_name")
                if container_name:
                    storage_box_values.append(container_name)
                    storage_box_formatted = _format_storage_box_html(
                        container_name,
                        location.get("container_state"),
                    )
                    if storage_box_formatted:
                        storage_box_formatted_values.append(storage_box_formatted)
                if location.get("well_label"):
                    storage_well_values.append(location["well_label"])
            extraction_number = row.sample_extraction_number

        results.append(
            {
                "LIMS ID": row.limsid,
                "Project LIMS ID": row.project_limsid,
                "Received Date": row.datereceived,
                "progress": row.progress,
                "Species": row.species_name,
                "Sample Name": row.sample_name,
                "Project Name": row.project_name,
                "submitter": _display_name(row.firstname, row.lastname),
                "submitting_lab": row.lab_name,
                "Project Account": row.project_account,
                "Experiment Name": _join_unique_non_empty(experiment_names),
                "Extraction Number": extraction_number,
                "Absorbance": ", ".join(absorbance_values) if absorbance_values else None,
                "A260/280 ratio": ", ".join(a260_280_values) if a260_280_values else None,
                "A260/230 ratio": ", ".join(a260_230_values) if a260_230_values else None,
                "Fluorescence": ", ".join(fluorescence_values) if fluorescence_values else None,
                "Storage Box": _join_unique_non_empty(storage_box_formatted_values),
                "Storage Well": _join_unique_non_empty(storage_well_values),
                "Invoice ID": _join_unique_non_empty(invoice_ids),
                "sample_type": row.sample_type,
                "gram_stain": row.gram_stain,
                "NIRD Filename": _join_unique_non_empty(nird_filenames),
                "Billing Description": _join_unique_non_empty(billing_descriptions),
                "price": _join_unique_non_empty(price_values),
                "nd_limsid": row.nd_limsid,
                "qubit_limsid": row.qubit_limsid,
                "prep_limsid": row.prep_limsid,
                "seq_limsid": row.seq_limsid,
                "billed_limsid": row.billed_limsid,
                "Increased Pooling (%)": row.increased_pooling,
                "Reagent Label": ", ".join(reagent_labels) if reagent_labels else None,
            }
        )

    _log_pg_timing(
        "build_sample_rows.assemble_results",
        stage_started_at,
        result_count=len(results),
    )
    _log_pg_timing(
        "build_sample_rows.total",
        total_started_at,
        sample_row_count=len(sample_rows),
        result_count=len(results),
    )
    return results
