"""
Shared constants, dataclasses, and cross-domain helper functions for the
Clarity Postgres query layer.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shinylims.integrations.clarity_models import (
    ArtifactUdfView,
    Principals,
    Process,
    ProcessUdfView,
    Researcher,
)


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

PROJECT_IDS_EXCLUDED_FROM_APP = {
    "LEI102",
    "LEI103",
    "LEI104",
    "LEI105",
    "LEI106",
    "LEI108",
    "LEI109",
}

CONTAINER_STATE_LABELS = {
    2: "Active",
    4: "Discarded",
}


# ---------------------------------------------------------------------------
# Shared dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ProcessRecord:
    """Small immutable process projection used during lineage traversal."""

    processid: int
    luid: str | None
    daterun: datetime | None
    workstatus: str | None
    techid: int | None
    typeid: int | None


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def _pg_timing_enabled() -> bool:
    value = (os.getenv("CLARITY_PG_TIMING_ENABLED") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _log_pg_timing(scope: str, started_at: float, **metrics: Any) -> None:
    if not _pg_timing_enabled():
        return
    elapsed_seconds = time.perf_counter() - started_at
    metric_parts = [f"elapsed_s={elapsed_seconds:.3f}"]
    metric_parts.extend(f"{key}={value}" for key, value in metrics.items())
    print(f"[clarity-pg-timing] scope={scope} " + " ".join(metric_parts))


# ---------------------------------------------------------------------------
# Row/value helpers
# ---------------------------------------------------------------------------

def _process_record(row: Any) -> ProcessRecord:
    return ProcessRecord(
        processid=row.processid,
        luid=row.luid,
        daterun=row.daterun,
        workstatus=row.workstatus,
        techid=row.techid,
        typeid=row.typeid,
    )


def _display_name(firstname: str | None, lastname: str | None) -> str | None:
    value = " ".join(
        part for part in ((firstname or "").strip(), (lastname or "").strip()) if part
    )
    return value or None


def _container_state_label(stateid: int | None) -> str | None:
    return CONTAINER_STATE_LABELS.get(stateid)


# ---------------------------------------------------------------------------
# Shared DB helpers (used by 2+ domain modules)
# ---------------------------------------------------------------------------

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
        first = (firstname or "").strip()[:1]
        last = "".join(part[:1] for part in (lastname or "").split())
        value = f"{first}{last}".strip()
        if value:
            result[processid] = value
    return result
