'''
data_utils.py module.
Utility functions for data fetching and transformation.

This module provides functions to fetch and transform live Clarity Postgres
data for projects, samples, sequencing runs, and storage containers.

Also includes functions to transform LIMS IDs and comments into HTML.
'''

####################
# IMPORT LIBRARIES #
####################

import datetime
import html
import os
import time
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import tomli

from shinylims.integrations.clarity_pg import create_session
from shinylims.integrations.queries import (
    build_project_rows,
    build_sample_rows,
    build_sequencing_run_rows,
    SEQUENCING_RUNIDS_TO_EXCLUDE,
    build_storage_container_rows,
)
####################
# HELPER FUNCTIONS #
####################




####################
# TRANSFORMATIONS #
####################

def transform_to_html(limsid):
    '''Transform LIMS IDs to HTML links.'''

    if pd.isna(limsid) or limsid == '':
        return limsid
    ids = str(limsid).split(',')
    html_links = []
    for raw_id in ids:
        lims_id = str(raw_id).strip()
        parts = lims_id.split('-')
        if len(parts) == 2 and parts[1].strip().isdigit():
            work_complete_id = quote(parts[1].strip(), safe="")
            label = html.escape(lims_id)
            html_link = (
                f'<a href="https://nvi-prod.claritylims.com/clarity/work-complete/{work_complete_id}" '
                f'target="_blank" rel="noopener noreferrer">{label}</a>'
            )
            html_links.append(html_link)
        else:
            # Handle incorrectly formatted id
            html_links.append(html.escape(lims_id))
    return ', '.join(html_links)


def transform_comments_to_html(comment):
    '''Transform comments to HTML format with line breaks (db linebraks are \n, we need <br>).'''
    if pd.isna(comment) or comment == '':
        return comment
    return html.escape(str(comment)).replace('\n', '<br>')


def sanitize_dataframe_strings(df: pd.DataFrame, skip_columns: set[str] | None = None) -> pd.DataFrame:
    """Escape all string-like cells except explicitly skipped columns that contain trusted HTML."""
    skip = skip_columns or set()
    for col in df.columns:
        if col in skip:
            continue
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            df[col] = df[col].apply(
                lambda v: html.escape(str(v)) if isinstance(v, str) and v != '' else v
            )
    return df


def _get_clarity_pg_sequencing_type_ids() -> list[int]:
    """Return sequencing process type ids for the direct Postgres prototype."""
    raw_value = (os.getenv("CLARITY_PG_SEQUENCING_TYPE_IDS") or "").strip()
    if not raw_value:
        return []

    type_ids: list[int] = []
    for part in raw_value.split(","):
        value = part.strip()
        if not value:
            continue
        type_ids.append(int(value))
    return type_ids


def _env_flag_is_true(name: str) -> bool:
    value = (os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _pg_timing_enabled() -> bool:
    return _env_flag_is_true("CLARITY_PG_TIMING_ENABLED")


def _log_pg_fetch_timing(scope: str, started_at: float, **metrics: object) -> None:
    if not _pg_timing_enabled():
        return

    elapsed_seconds = time.perf_counter() - started_at
    metric_parts = [f"elapsed_s={elapsed_seconds:.3f}"]
    metric_parts.extend(f"{key}={value}" for key, value in metrics.items())
    print(f"[clarity-pg-timing] scope={scope} " + " ".join(metric_parts))


def _format_sequencing_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Apply HTML transforms and sanitization to a sequencing DataFrame."""
    if 'Seq Date' in df.columns:
        df['Seq Date'] = pd.to_datetime(df['Seq Date'], errors='coerce')

    df = df.replace(np.nan, '', regex=True)

    for col in ['seq_limsid', 'nd_limsid', 'qubit_limsid', 'prep_limsid']:
        if col in df.columns:
            df[col] = df[col].apply(transform_to_html)

    html_columns = {
        col for col in ['seq_limsid', 'nd_limsid', 'qubit_limsid', 'prep_limsid']
        if col in df.columns
    }
    return sanitize_dataframe_strings(df, skip_columns=html_columns)


def _format_samples_dataframe(df: pd.DataFrame, *, meta_created: str) -> tuple[pd.DataFrame, str]:
    """Apply HTML transforms, sanitization, and column ordering to a samples DataFrame."""
    if 'Received Date' in df.columns:
        df['Received Date'] = pd.to_datetime(df['Received Date'], errors='coerce')

    df = df.replace(np.nan, '', regex=True)

    for col in ['seq_limsid', 'nd_limsid', 'qubit_limsid', 'prep_limsid']:
        if col in df.columns:
            df[col] = df[col].apply(transform_to_html)

    comment_columns = [col for col in df.columns if 'comment' in col.lower()]
    for col in comment_columns:
        df[col] = df[col].apply(transform_comments_to_html)

    html_columns = set(comment_columns) | {
        col for col in ['seq_limsid', 'nd_limsid', 'qubit_limsid', 'prep_limsid'] if col in df.columns
    } | ({'Storage Box'} if 'Storage Box' in df.columns else set())
    df = sanitize_dataframe_strings(df, skip_columns=html_columns)

    # Place Storage Box immediately before Storage Well
    cols = df.columns.tolist()
    if 'Storage Box' in cols:
        cols.remove('Storage Box')
    if 'Storage Well' in cols:
        storage_well_idx = cols.index('Storage Well')
        cols.insert(storage_well_idx, 'Storage Box')
    df = df[cols]

    return df, meta_created


def _fetch_projects_data_from_postgres() -> tuple[pd.DataFrame, str]:
    """Fetch project rows directly from Clarity Postgres."""
    started_at = time.perf_counter()
    with create_session() as session:
        rows = build_project_rows(session)

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=[
            "Project LIMS ID",
            "Open Date",
            "Status",
            "Project Name",
            "Samples",
            "Species",
            "Submitter",
            "Submitting Lab",
            "Comment",
        ])
    _log_pg_fetch_timing("fetch_projects_data_from_postgres", started_at, row_count=len(df))
    return df, datetime.datetime.now().isoformat()


def _fetch_sequencing_data_from_postgres() -> tuple[pd.DataFrame, str]:
    """Fetch sequencing rows directly from Clarity Postgres."""
    sequencing_type_ids = _get_clarity_pg_sequencing_type_ids()
    if not sequencing_type_ids:
        raise RuntimeError(
            "CLARITY_PG_SEQUENCING_TYPE_IDS is not configured for direct Postgres sequencing reads."
        )

    started_at = time.perf_counter()
    with create_session() as session:
        rows = build_sequencing_run_rows(session, sequencing_type_ids)

    df = pd.DataFrame(rows)
    if not df.empty and "seq_limsid" in df.columns:
        df = df[~df["seq_limsid"].isin(SEQUENCING_RUNIDS_TO_EXCLUDE)]
    if df.empty:
        df = pd.DataFrame(columns=[
            "seq_limsid",
            "Run ID",
            "Instrument",
            "Run Number",
            "Seq Date",
            "Operator",
            "Species",
            "Experiment Name",
            "Casette Type",
            "Read Length",
            "Index Cycles",
            "Sample Count",
            "Loading pM",
            "Diluted Denatured (uL)",
            "Avg Fragment Size",
            "Combined Pool",
            "Phix Loaded (%)",
            "Phix Aligned (%)",
            "Cluster Density",
            "Yield Total",
            "QV30 R1",
            "QV30 R2",
            "PF Reads",
            "Comment",
        ])
    _log_pg_fetch_timing(
        "fetch_sequencing_data_from_postgres",
        started_at,
        row_count=len(df),
        sequencing_type_count=len(sequencing_type_ids),
    )
    return df, datetime.datetime.now().isoformat()


def _fetch_samples_data_from_postgres() -> tuple[pd.DataFrame, str]:
    """Fetch sample rows directly from Clarity Postgres."""
    started_at = time.perf_counter()
    with create_session() as session:
        rows = build_sample_rows(session, open_projects_only=False)

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=[
            "LIMS ID",
            "Project LIMS ID",
            "Received Date",
            "progress",
            "Species",
            "Sample Name",
            "Project Name",
            "submitter",
            "submitting_lab",
            "Project Account",
            "Experiment Name",
            "Extraction Number",
            "Absorbance",
            "A260/280 ratio",
            "A260/230 ratio",
            "Fluorescence",
            "Storage Box",
            "Storage Well",
            "Invoice ID",
            "sample_type",
            "gram_stain",
            "NIRD Filename",
            "Billing Description",
            "price",
            "nd_limsid",
            "qubit_limsid",
            "prep_limsid",
            "seq_limsid",
            "billed_limsid",
            "Increased Pooling (%)",
            "Reagent Label",
        ])
    _log_pg_fetch_timing("fetch_samples_data_from_postgres", started_at, row_count=len(df))
    return df, datetime.datetime.now().isoformat()


def fetch_storage_containers_data() -> pd.DataFrame:
    """Fetch storage container rows directly from Clarity Postgres."""
    started_at = time.perf_counter()
    with create_session() as session:
        rows = build_storage_container_rows(session)
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "Box Name",
                "Status",
                "Created Date",
                "Last Modified",
            ]
        )
    _log_pg_fetch_timing("fetch_storage_containers_data_from_postgres", started_at, row_count=len(df))
    return df


####################
# DATA FETCHING    #
####################


def fetch_projects_data():
    """Fetch project data directly from Clarity Postgres."""
    df, meta_created = _fetch_projects_data_from_postgres()

    if 'Open Date' in df.columns:
        df['Open Date'] = pd.to_datetime(df['Open Date'], errors='coerce')

    df = df.replace(np.nan, '', regex=True)

    comment_columns = [col for col in df.columns if 'comment' in col.lower()]
    for col in comment_columns:
        df[col] = df[col].apply(transform_comments_to_html)

    df = sanitize_dataframe_strings(df, skip_columns=set(comment_columns))

    return df, meta_created


def fetch_all_samples_data():
    """Fetch all live samples directly from Clarity Postgres."""
    df, meta_created = _fetch_samples_data_from_postgres()

    return _format_samples_dataframe(df, meta_created=meta_created)


def fetch_sequencing_data():
    """Fetch sequencing run data directly from Clarity Postgres."""
    df, meta_created = _fetch_sequencing_data_from_postgres()

    return _format_sequencing_dataframe(df), meta_created


# Get app version from pyproject.toml
def get_app_version():
    try:
        # Look in the same directory as app.py
        toml_path = Path(__file__).parent / "pyproject.toml"

        # If not found there, try one level up
        if not toml_path.exists():
            toml_path = Path(__file__).resolve().parent.parent / "pyproject.toml"

        # If still not found, try the current working directory
        if not toml_path.exists():
            toml_path = Path.cwd() / "pyproject.toml"

        if toml_path.exists():
            with open(toml_path, "rb") as f:
                data = tomli.load(f)
                if "tool" in data and "poetry" in data["tool"]:
                    return data["tool"]["poetry"].get("version", "Unknown")
                elif "project" in data:
                    return data["project"].get("version", "Unknown")
                else:
                    for section in data:
                        if "version" in data[section]:
                            return data[section]["version"]

        return "Unknown"
    except Exception:
        return "Unknown"
