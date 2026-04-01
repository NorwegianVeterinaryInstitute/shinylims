"""
Project query: builds project rows directly from the Clarity Postgres schema.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shinylims.integrations.clarity_models import (
    EntityUdfView,
    Lab,
    Project,
    Researcher,
    Sample,
    SampleUdfView,
)
from shinylims.integrations.queries._shared import (
    PROJECT_IDS_EXCLUDED_FROM_APP,
    _display_name,
)

PROJECT_COMMENT_UDF = "Message to the lab (attached to email and Clarity LIMS)"
PROJECT_COMMENT_PLACEHOLDERS = (
    "USE THIS FIELD. Any comments placed here will be forwarded to all lab members "
    "working on NGS samples.",
    "Ingen merknad vedlagt prosjektet",
)


def build_project_rows(session: Session) -> list[dict[str, Any]]:
    """Build project rows with display-ready column names."""
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
            if comment in PROJECT_COMMENT_PLACEHOLDERS:
                comment = ""
            project = {
                "Project LIMS ID": row.luid,
                "Open Date": row.opendate,
                "Status": status,
                "Project Name": row.project_name,
                "Samples": 0,
                "Species": "",
                "Submitter": _display_name(row.firstname, row.lastname),
                "Submitting Lab": row.lab_name,
                "Comment": comment or "",
            }
            projects[row.projectid] = project

        if row.sample_processid is not None:
            sample_counts[row.projectid].add(row.sample_processid)

        species = row.species
        if species and species not in species_by_project[row.projectid]:
            species_by_project[row.projectid].append(species)

    result: list[dict[str, Any]] = []
    for projectid, project in projects.items():
        if project["Project LIMS ID"] in PROJECT_IDS_EXCLUDED_FROM_APP:
            continue
        project["Samples"] = len(sample_counts.get(projectid, set()))
        project["Species"] = ", ".join(species_by_project.get(projectid, []))
        result.append(project)
    return result
