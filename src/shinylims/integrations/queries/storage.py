"""
Storage query: builds DNA storage container rows from Clarity Postgres.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shinylims.integrations.clarity_models import Container, ContainerType
from shinylims.integrations.queries._shared import _container_state_label

DNA_STORAGE_CONTAINER_TYPE_NAME = "DNA for NGS"


def build_storage_container_rows(session: Session) -> list[dict[str, Any]]:
    """Return DNA storage containers with display-ready column names."""
    rows = session.execute(
        select(
            Container.name,
            Container.stateid,
            Container.createddate,
            Container.lastmodifieddate,
        )
        .join(ContainerType, ContainerType.typeid == Container.typeid)
        .where(ContainerType.name == DNA_STORAGE_CONTAINER_TYPE_NAME)
        .order_by(Container.name.desc())
    ).all()

    results: list[dict[str, Any]] = []
    for container_name, stateid, createddate, lastmodifieddate in rows:
        results.append(
            {
                "Box Name": container_name,
                "Status": _container_state_label(stateid) or f"State {stateid}",
                "Created Date": createddate,
                "Last Modified": lastmodifieddate,
            }
        )
    return results
