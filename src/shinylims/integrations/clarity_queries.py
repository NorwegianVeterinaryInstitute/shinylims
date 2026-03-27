"""
Prototype SQLAlchemy queries for traversing Clarity sequencing lineage directly in Postgres.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from shinylims.integrations.clarity_models import (
    Analyte,
    ArtifactSampleMap,
    ArtifactLabelMap,
    ArtifactUdfView,
    Container,
    ContainerPlacement,
    EntityUdfView,
    Lab,
    OutputMapping,
    Principals,
    Process,
    ProcessIOTracker,
    ProcessUdfView,
    Project,
    ReagentLabel,
    Researcher,
    ResultFile,
    Sample,
    SampleUdfView,
    Artifact,
)

PROJECT_COMMENT_UDF = "Message to the lab (attached to email and Clarity LIMS)"
PROJECT_COMMENT_PLACEHOLDER = (
    "USE THIS FIELD. Any comments placed here will be forwarded to all lab members "
    "working on NGS samples."
)
PROJECT_IDS_EXCLUDED_FROM_APP = {
    "LEI102",
    "LEI103",
    "LEI104",
    "LEI105",
    "LEI106",
    "LEI108",
    "LEI109",
}
ALLOWED_SAMPLE_TYPES = (
    "WGS colonies - freezer",
    "WGS colonies - dish",
    "WGS DNA",
    "Prepared Pool",
    "Prepared Libraries",
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
class ProcessRecord:
    """Small immutable process projection used during lineage traversal."""

    processid: int
    luid: str | None
    daterun: datetime | None
    workstatus: str | None
    techid: int | None
    typeid: int | None


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


def _parse_run_id(run_id: str | None) -> tuple[str | None, str | None]:
    if not run_id:
        return None, None
    parts = re.split(r"[_-]", run_id)
    if len(parts) > 3:
        return parts[1], parts[2]
    return None, None


def _process_record(row: Any) -> ProcessRecord:
    return ProcessRecord(
        processid=row.processid,
        luid=row.luid,
        daterun=row.daterun,
        workstatus=row.workstatus,
        techid=row.techid,
        typeid=row.typeid,
    )


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


def _operator_initials(firstname: str | None, lastname: str | None) -> str | None:
    first = (firstname or "").strip()[:1]
    last = "".join(part[:1] for part in (lastname or "").split())
    value = f"{first}{last}".strip()
    return value or None


def _display_name(firstname: str | None, lastname: str | None) -> str | None:
    value = " ".join(part for part in ((firstname or "").strip(), (lastname or "").strip()) if part)
    return value or None


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
    if x_position is None or y_position is None or y_position < 1:
        return None
    return f"{chr(64 + y_position)}:{x_position}"


def _format_storage_box_html(container_name: str | None, container_state: str | None) -> str | None:
    if not container_name:
        return None
    if container_state == "Discarded":
        return f'<span style="color: red; font-weight: bold;">{container_name} (discarded)</span>'
    return container_name


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


def _load_process_udfs(
    session: Session,
    process_ids: list[int],
    udf_names: set[str],
) -> dict[int, dict[str, str]]:
    if not process_ids or not udf_names:
        return {}

    rows = session.execute(
        select(
            ProcessUdfView.processid,
            ProcessUdfView.udfname,
            ProcessUdfView.udfvalue,
        )
        .where(ProcessUdfView.processid.in_(process_ids))
        .where(ProcessUdfView.udfname.in_(udf_names))
    ).all()

    result: dict[int, dict[str, str]] = defaultdict(dict)
    for processid, udfname, udfvalue in rows:
        result[processid][udfname] = udfvalue
    return dict(result)


def _load_artifact_udfs(
    session: Session,
    artifact_ids: list[int],
    udf_names: set[str],
) -> dict[int, dict[str, str]]:
    if not artifact_ids or not udf_names:
        return {}

    rows = session.execute(
        select(
            ArtifactUdfView.artifactid,
            ArtifactUdfView.udfname,
            ArtifactUdfView.udfvalue,
        )
        .where(ArtifactUdfView.artifactid.in_(artifact_ids))
        .where(ArtifactUdfView.udfname.in_(udf_names))
    ).all()

    result: dict[int, dict[str, str]] = defaultdict(dict)
    for artifactid, udfname, udfvalue in rows:
        result[artifactid][udfname] = udfvalue
    return dict(result)


def _load_operator_initials(
    session: Session,
    process_ids: list[int],
) -> dict[int, str]:
    if not process_ids:
        return {}

    rows = session.execute(
        select(
            Process.processid,
            Researcher.firstname,
            Researcher.lastname,
        )
        .join(Principals, Principals.principalid == Process.techid)
        .join(Researcher, Researcher.researcherid == Principals.researcherid)
        .where(Process.processid.in_(process_ids))
    ).all()

    result: dict[int, str] = {}
    for processid, firstname, lastname in rows:
        value = _operator_initials(firstname, lastname)
        if value:
            result[processid] = value
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


def build_project_rows(session: Session) -> list[dict[str, Any]]:
    """Build project rows shaped like the current `projects` dataset."""
    species_udf = SampleUdfView.__table__.alias("species_udf")
    comment_udf = EntityUdfView.__table__.alias("comment_udf")

    rows = session.execute(
        select(
            Project.projectid,
            Project.luid,
            Project.opendate,
            Project.closedate,
            Project.name.label("project_name"),
            Researcher.firstname,
            Researcher.lastname,
            Lab.name.label("lab_name"),
            Sample.processid.label("sample_processid"),
            species_udf.c.udfvalue.label("species"),
            comment_udf.c.udfvalue.label("comment"),
        )
        .outerjoin(Researcher, Researcher.researcherid == Project.researcherid)
        .outerjoin(Lab, Lab.labid == Researcher.labid)
        .outerjoin(Sample, Sample.projectid == Project.projectid)
        .outerjoin(
            species_udf,
            (species_udf.c.sampleid == Sample.sampleid) & (species_udf.c.udfname == "Species"),
        )
        .outerjoin(
            comment_udf,
            (comment_udf.c.attachtoid == Project.projectid)
            & (comment_udf.c.attachtoclassid == 83)
            & (comment_udf.c.udfname == PROJECT_COMMENT_UDF),
        )
        .order_by(Project.projectid)
    ).all()

    projects: dict[int, dict[str, Any]] = {}
    sample_counts: dict[int, set[int]] = defaultdict(set)
    species_by_project: dict[int, list[str]] = defaultdict(list)

    for row in rows:
        project = projects.get(row.projectid)
        if project is None:
            status = "CLOSED" if row.closedate else ("OPEN" if row.opendate else "PENDING")
            comment = row.comment
            if comment == PROJECT_COMMENT_PLACEHOLDER:
                comment = ""
            project = {
                "project_limsid": row.luid,
                "open_date": row.opendate,
                "status": status,
                "project_name": row.project_name,
                "sample_count": 0,
                "species": "",
                "submitter": _display_name(row.firstname, row.lastname),
                "submitting_lab": row.lab_name,
                "comment": comment or "",
            }
            projects[row.projectid] = project

        if row.sample_processid is not None:
            sample_counts[row.projectid].add(row.sample_processid)

        species = row.species
        if species and species not in species_by_project[row.projectid]:
            species_by_project[row.projectid].append(species)

    result: list[dict[str, Any]] = []
    for projectid, project in projects.items():
        if project["project_limsid"] in PROJECT_IDS_EXCLUDED_FROM_APP:
            continue
        project["sample_count"] = len(sample_counts.get(projectid, set()))
        project["species"] = ", ".join(species_by_project.get(projectid, []))
        result.append(project)
    return result


def _load_sample_udf_rows(
    session: Session,
    open_projects_only: bool,
) -> list[Any]:
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
            ContainerPlacement.wellxposition,
            ContainerPlacement.wellyposition,
        )
        .join(Container, Container.containerid == ContainerPlacement.containerid)
        .where(ContainerPlacement.processartifactid.in_(artifact_ids))
    ).all()

    result: dict[int, dict[str, str | None]] = {}
    for artifactid, container_name, x_position, y_position in rows:
        result[artifactid] = {
            "container_name": container_name,
            "container_state": None,
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


def build_sample_rows(
    session: Session,
    *,
    open_projects_only: bool = True,
) -> list[dict[str, Any]]:
    """Build sample rows shaped like the current `samples` dataset."""
    sample_rows = _load_sample_udf_rows(session, open_projects_only=open_projects_only)
    if not sample_rows:
        return []

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

    processes_by_luid = _load_processes_by_luid(session, sorted(referenced_process_luids))
    referenced_process_ids = sorted({process.processid for process in processes_by_luid.values()})

    process_udfs = _load_process_udfs(
        session,
        referenced_process_ids,
        {"Faktura ID (fra økonomi)", "Run ID"},
    )
    process_output_artifacts = _load_process_sample_output_analytes(session, referenced_process_ids)
    process_input_artifacts = _load_process_sample_input_artifacts(session, referenced_process_ids)
    original_artifacts_by_sample = _load_original_artifacts_by_sample(session, sample_process_ids)

    artifact_ids: set[int] = set(original_artifacts_by_sample.values())
    for artifact_list in process_output_artifacts.values():
        artifact_ids.update(artifact_list)
    for artifact_list in process_input_artifacts.values():
        artifact_ids.update(artifact_list)

    artifact_udfs = _load_artifact_udfs(
        session,
        sorted(artifact_ids),
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
    artifact_locations = _load_artifact_locations(session, sorted(artifact_ids))
    artifact_reagent_labels = _load_artifact_reagent_labels(session, sorted(artifact_ids))

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
                artifact_udf_map = artifact_udfs.get(artifact_list[0], {})
                if artifact_udf_map.get("Concentration Absorbance (ng/µl)"):
                    absorbance_values.append(artifact_udf_map["Concentration Absorbance (ng/µl)"])
                if artifact_udf_map.get("A260/280 ratio"):
                    a260_280_values.append(artifact_udf_map["A260/280 ratio"])
                if artifact_udf_map.get("A260/230 ratio"):
                    a260_230_values.append(artifact_udf_map["A260/230 ratio"])
                if artifact_udf_map.get("Concentration Fluorescence (ng/µl)"):
                    fluorescence_values.append(artifact_udf_map["Concentration Fluorescence (ng/µl)"])

                location = artifact_locations.get(artifact_list[0], {})
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
                artifactid = artifact_list[0]
                prep_udfs = artifact_udfs.get(artifactid, {})
                if prep_udfs.get("Experiment Name"):
                    experiment_names.append(prep_udfs["Experiment Name"])
                reagent_labels.extend(artifact_reagent_labels.get(artifactid, []))

            for extraction_luid in _split_luid_list(row.extractions_limsid):
                process_record = processes_by_luid.get(extraction_luid)
                if process_record is None:
                    continue
                artifact_list = process_output_artifacts.get((process_record.processid, row.sample_processid), [])
                if not artifact_list:
                    continue
                extraction_value = artifact_udfs.get(artifact_list[0], {}).get("Extraction Number")
                if extraction_value:
                    extraction_numbers.append(extraction_value)

            extraction_number = (
                row.sample_extraction_number if row.sample_type == "WGS DNA"
                else _join_unique_non_empty(extraction_numbers)
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
                "limsid": row.limsid,
                "project_limsid": row.project_limsid,
                "received_date": row.datereceived,
                "progress": row.progress,
                "species_name": row.species_name,
                "name": row.sample_name,
                "project_name": row.project_name,
                "submitter": _display_name(row.firstname, row.lastname),
                "submitting_lab": row.lab_name,
                "project_account": row.project_account,
                "experiment_name": _join_unique_non_empty(experiment_names),
                "extraction_number": extraction_number,
                "concentration_absorbance": _join_unique_non_empty(absorbance_values),
                "a260_280_ratio": _join_unique_non_empty(a260_280_values),
                "a260_230_ratio": _join_unique_non_empty(a260_230_values),
                "concentration_fluorescence": _join_unique_non_empty(fluorescence_values),
                "storage_box": _join_unique_non_empty(storage_box_values),
                "storage_box_formatted": _join_unique_non_empty(storage_box_formatted_values),
                "storage_well": _join_unique_non_empty(storage_well_values),
                "invoice_id": _join_unique_non_empty(invoice_ids),
                "sample_type": row.sample_type,
                "gram_stain": row.gram_stain,
                "nird_filename": _join_unique_non_empty(nird_filenames),
                "billing_description": _join_unique_non_empty(billing_descriptions),
                "price": _join_unique_non_empty(price_values),
                "nd_limsid": row.nd_limsid,
                "qubit_limsid": row.qubit_limsid,
                "prep_limsid": row.prep_limsid,
                "seq_limsid": row.seq_limsid,
                "billed_limsid": row.billed_limsid,
                "increased_pooling": row.increased_pooling,
                "reagent_label": _join_unique_non_empty(reagent_labels),
            }
        )

    return results


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
    step6_all_inputs_by_process = _all_input_artifacts_by_process(session, step6_process_ids)

    step5_artifact_ids = sorted(set(step6_input_by_process.values()))
    step5_by_artifact = _producer_by_artifact(session, step5_artifact_ids)

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
            step6_all_inputs_by_process.get(step6_process.processid, []) if step6_process else []
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
    """Build sequencing rows shaped like the current `ilmn_sequencing` dataset."""
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

        avg_fragment_size = step6_input_udfs.get("Average Size - bp")
        combined_pool = "No" if avg_fragment_size else "NA"
        if not avg_fragment_size:
            upstream_sizes = []
            for artifactid in lineage.step5_input_artifactids:
                value = artifact_udfs.get(artifactid, {}).get("Average Size - bp")
                if value and value not in upstream_sizes:
                    upstream_sizes.append(value)
            if upstream_sizes:
                avg_fragment_size = " + ".join(upstream_sizes)
                combined_pool = "Yes"

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
                f"2 x {read_1_cycles}" if read_1_cycles == read_2_cycles else f"{read_1_cycles} + {read_2_cycles}"
            )

        sample_context = representative_sample_context.get(lineage.representative_input_artifactid, {})

        rows.append(
            {
                "seq_limsid": lineage.sequencing_process.luid,
                "run_id": run_id,
                "instrument": instrument,
                "run_number": run_number,
                "seq_date": lineage.sequencing_process.daterun,
                "operator": operator,
                "species": sample_context.get("species"),
                "experiment_name": representative_udfs.get("Experiment Name"),
                "casette_type": _kit_type_from_application(representative_udfs.get("Application")),
                "read_length": read_length,
                "index_cycles": _coerce_int(step7_udfs.get("Index Cycles")),
                "sample_count": sample_context.get("sample_count"),
                "loading_pm": _coerce_float(step6_udfs.get("Final Library Loading (pM)")),
                "diluted_denatured_ul": _coerce_float(
                    step6_udfs.get("Volume 20pM Denat Sample (µl)")
                    or step6_udfs.get("1. Library Pool Denatured 20pM (µl)")
                ),
                "avg_fragment_size": avg_fragment_size,
                "combined_pool": combined_pool,
                "phix_loaded_percent": _coerce_float(step6_udfs.get("PhiX / library spike-in (%)")),
                "phix_aligned_percent": _coerce_float(representative_udfs.get("% Aligned R1")),
                "cluster_density": _coerce_float(representative_udfs.get("Cluster Density (K/mm^2) R1")),
                "yield_total": total_yield,
                "qv30_r1": _coerce_float(representative_udfs.get("% Bases >=Q30 R1")),
                "qv30_r2": _coerce_float(representative_udfs.get("% Bases >=Q30 R2")),
                "pf_reads": _coerce_float(representative_udfs.get("Reads PF (M) R1")),
                "comment": seq_udfs.get("Comment"),
            }
        )

    return rows


def sequencing_lineage_debug_query(
    sequencing_type_ids: list[int],
) -> Select[Any]:
    """Return the anchor query used to find sequencing processes for this prototype."""
    return (
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
    )
