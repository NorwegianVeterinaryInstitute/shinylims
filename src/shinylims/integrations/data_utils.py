'''
data_utils.py module.
Utility functions for data fetching and transformation.

This module provides functions to fetch and transform data from the
SQLite database stored as Posit Connect pin. It handles data for projects,
samples, and sequencing runs with standardized column naming and formatting.

Also includes functions to transform LIMS IDs and comments into HTML
'''

####################
# IMPORT LIBRARIES #
####################

import datetime
import html
import os
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import tomli

from shinylims.integrations.clarity_pg import create_session
from shinylims.integrations.clarity_queries import (
    build_project_rows,
    build_sample_rows,
    build_sequencing_run_rows,
)
from shinylims.integrations.db_utils import query_to_dataframe, get_db_update_info

####################
# HELPER FUNCTIONS #
####################

def get_table_update_timestamp(table_name):
    """
    Get the last update timestamp for a specific table from the update_log.
    
    Args:
        table_name (str): Name of the table to get the timestamp for
        
    Returns:
        str: ISO formatted timestamp of the last update for this table
    """
    update_info = get_db_update_info()
    
    # Check if we have table-specific update info
    if update_info.get('update_method') == 'update_log' and update_info.get('table_updates'):
        # Handle case where tables_affected might contain our table name
        # We need to check if the table_name is in the tables_affected field
        for db_table, update in update_info['table_updates'].items():
            # The tables_affected field might contain multiple tables or a pattern
            # Check if our table is mentioned in this field
            if table_name in db_table:
                return update['timestamp']
    
    # Fall back to the overall last update time if available
    if update_info.get('last_update'):
        return update_info['last_update']
    
    # Last resort - use current time
    return datetime.datetime.now().isoformat()




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


def _format_sequencing_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize sequencing rows to the app-facing dataframe shape."""
    df = df.rename(columns={
        'seq_limsid': 'seq_limsid',
        'run_id': 'Run ID',
        'instrument': 'Instrument',
        'run_number': 'Run Number',
        'seq_date': 'Seq Date',
        'operator': 'Operator',
        'species': 'Species',
        'experiment_name': 'Experiment Name',
        'casette_type': 'Casette Type',
        'read_length': 'Read Length',
        'index_cycles': 'Index Cycles',
        'sample_count': 'Sample Count',
        'loading_pm': 'Loading pM',
        'diluted_denatured_ul': 'Diluted Denatured (uL)',
        'avg_fragment_size': 'Avg Fragment Size',
        'combined_pool': 'Combined Pool',
        'phix_loaded_percent': 'Phix Loaded (%)',
        'phix_aligned_percent': 'Phix Aligned (%)',
        'cluster_density': 'Cluster Density',
        'yield_total' : 'Yield Total',
        'qv30_r1': 'QV30 R1',
        'qv30_r2':  'QV30 R2',
        'pf_reads': 'PF Reads',
        'comment' : 'Comment'
    })

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
    """Normalize sample rows to the app-facing dataframe shape."""
    if "storage_box_formatted" not in df.columns:
        containers_query = "SELECT container_name, state FROM storage_containers"
        containers_df = query_to_dataframe(containers_query)
        container_states = dict(zip(containers_df['container_name'], containers_df['state']))

        def format_storage_box(row):
            box_name = row.get('storage_box', '')

            if pd.isna(box_name) or box_name == '':
                return ''

            boxes = [box.strip() for box in str(box_name).split(',')]
            formatted_boxes = []

            for box in boxes:
                if not box:
                    continue

                box_state = container_states.get(box, None)
                if box_state == 'Discarded':
                    formatted_boxes.append(
                        f'<span style="color: red; font-weight: bold;">{html.escape(box)} (discarded)</span>'
                    )
                else:
                    formatted_boxes.append(html.escape(box))

            return ', '.join(formatted_boxes)

        df['storage_box_formatted'] = df.apply(format_storage_box, axis=1)

    if 'storage_box' in df.columns:
        df = df.drop('storage_box', axis=1)

    df = df.rename(columns={
        'limsid': 'LIMS ID',
        'project_limsid': 'Project LIMS ID',
        'received_date': 'Received Date',
        'species_name': 'Species',
        'name': 'Sample Name',
        'project_name': 'Project Name',
        'project_account': 'Project Account',
        'experiment_name': 'Experiment Name',
        'invoice_id': 'Invoice ID',
        'extraction_number': 'Extraction Number',
        'concentration_absorbance': 'Absorbance',
        'a260_280_ratio': 'A260/280 ratio',
        'a260_230_ratio': 'A260/230 ratio',
        'concentration_fluorescence': 'Fluorescence',
        'storage_box_formatted': 'Storage Box',
        'storage_well': 'Storage Well',
        'billing_description': 'Billing Description',
        'reagent_label': 'Reagent Label',
        'increased_pooling': 'Increased Pooling (%)',
        'nird_filename': 'NIRD Filename',
    })

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

    cols = df.columns.tolist()
    if 'Storage Box' in cols:
        cols.remove('Storage Box')
    if 'Storage Well' in cols:
        storage_well_idx = cols.index('Storage Well')
        cols.insert(storage_well_idx, 'Storage Box')
    df = df[cols]

    return df, meta_created


def _fetch_projects_data_from_postgres() -> tuple[pd.DataFrame, str]:
    """Fetch project rows directly from Clarity Postgres using the prototype query layer."""
    with create_session() as session:
        rows = build_project_rows(session)

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=[
            "project_limsid",
            "open_date",
            "status",
            "project_name",
            "sample_count",
            "species",
            "submitter",
            "submitting_lab",
            "comment",
        ])
    return df, datetime.datetime.now().isoformat()


def _fetch_sequencing_data_from_postgres() -> tuple[pd.DataFrame, str]:
    """Fetch sequencing rows directly from Clarity Postgres using the prototype query layer."""
    sequencing_type_ids = _get_clarity_pg_sequencing_type_ids()
    if not sequencing_type_ids:
        raise RuntimeError(
            "CLARITY_PG_SEQUENCING_TYPE_IDS is not configured for direct Postgres sequencing reads."
        )

    with create_session() as session:
        rows = build_sequencing_run_rows(session, sequencing_type_ids)

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=[
            "seq_limsid",
            "run_id",
            "instrument",
            "run_number",
            "seq_date",
            "operator",
            "species",
            "experiment_name",
            "casette_type",
            "read_length",
            "index_cycles",
            "sample_count",
            "loading_pm",
            "diluted_denatured_ul",
            "avg_fragment_size",
            "combined_pool",
            "phix_loaded_percent",
            "phix_aligned_percent",
            "cluster_density",
            "yield_total",
            "qv30_r1",
            "qv30_r2",
            "pf_reads",
            "comment",
        ])
    return df, datetime.datetime.now().isoformat()


def _fetch_samples_data_from_postgres() -> tuple[pd.DataFrame, str]:
    """Fetch sample rows directly from Clarity Postgres using the prototype query layer."""
    with create_session() as session:
        rows = build_sample_rows(session, open_projects_only=False)

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=[
            "limsid",
            "project_limsid",
            "received_date",
            "progress",
            "species_name",
            "name",
            "project_name",
            "submitter",
            "submitting_lab",
            "project_account",
            "experiment_name",
            "extraction_number",
            "concentration_absorbance",
            "a260_280_ratio",
            "a260_230_ratio",
            "concentration_fluorescence",
            "storage_box",
            "storage_box_formatted",
            "storage_well",
            "invoice_id",
            "sample_type",
            "gram_stain",
            "nird_filename",
            "billing_description",
            "price",
            "nd_limsid",
            "qubit_limsid",
            "prep_limsid",
            "seq_limsid",
            "billed_limsid",
            "increased_pooling",
            "reagent_label",
        ])
    return df, datetime.datetime.now().isoformat()




####################
# DATA FETCHING    #
####################


def fetch_projects_data():
    """Fetch projects data from Postgres when configured, otherwise from SQLite."""
    if _env_flag_is_true("CLARITY_PG_PROJECTS_ENABLED"):
        df, meta_created = _fetch_projects_data_from_postgres()
    else:
        df = query_to_dataframe("SELECT * FROM projects")
        meta_created = get_table_update_timestamp('projects')
    
    # Rename columns to match what the app expects
    df = df.rename(columns={
        'open_date': 'Open Date',
        'project_name': 'Project Name',
        'sample_count': 'Samples',
        'submitting_lab': 'Submitting Lab',
        'comment': 'Comment',
        'status': 'Status',
        'submitter': 'Submitter',
        'species': 'Species',
        'status': 'Status',
        'project_limsid': 'Project LIMS ID',
    })
    
    # Apply transformations
    if 'Open Date' in df.columns:
        df['Open Date'] = pd.to_datetime(df['Open Date'], errors='coerce')
    
    # Replace NaN values
    df = df.replace(np.nan, '', regex=True)

    # Transform comments
    comment_columns = [col for col in df.columns if 'comment' in col.lower()]
    for col in comment_columns:
        df[col] = df[col].apply(transform_comments_to_html)

    df = sanitize_dataframe_strings(df, skip_columns=set(comment_columns))
    
    return df, meta_created


def fetch_all_samples_data():
    """Fetch all samples data from Postgres when configured, otherwise from SQLite."""
    if _env_flag_is_true("CLARITY_PG_SAMPLES_ENABLED"):
        df, meta_created = _fetch_samples_data_from_postgres()
    else:
        df = query_to_dataframe("SELECT * FROM samples")
        meta_created = get_table_update_timestamp('samples')

    return _format_samples_dataframe(df, meta_created=meta_created)





def fetch_historical_samples_data():
    """
    Fetch historical samples data from SQLite database.
    Returns: tuple of (DataFrame, creation_date)
    """

    df = query_to_dataframe("SELECT * FROM samples_historical")

    # Rename columns to match what the app expects
    df = df.rename(columns={
        'limsid': 'LIMS ID',
        'project_limsid': 'Project LIMS ID',
        'received_date': 'Received Date',
        'species_name': 'Species',
        'name': 'Sample Name',
        'project_name': 'Project Name',
        'project_account': 'Project Account',
        'experiment_name': 'Experiment Name',
        'invoice_id': 'Invoice ID',
        'extraction_number': 'Extraction Number',
        'concentration_absorbance': 'Absorbance',
        'a260_280_ratio': 'A260/280 ratio',
        'a260_230_ratio': 'A260/230 ratio',
        'concentration_fluorescence': 'Fluorescence',
        'storage_box': 'Storage Box Name',
        'storage_well': 'Storage Well',
        'billing_description': 'Billing Description',
        'reagent_label': 'Reagent Label',
        'increased_pooling': 'Increased Pooling (%)',
        'nird_filename': 'NIRD Filename',
    })
    
    # Apply transformations
    if 'Received Date' in df.columns:
        df['Received Date'] = pd.to_datetime(df['Received Date'], errors='coerce')
    
    # Replace NaN values
    df = df.replace(np.nan, '', regex=True)
    
    # Transform LIMS IDs to HTML links
    for col in ['seq_limsid', 'nd_limsid', 'qubit_limsid', 'prep_limsid']:
        if col in df.columns:
            df[col] = df[col].apply(transform_to_html)
    
    # Transform comments
    comment_columns = [col for col in df.columns if 'comment' in col.lower()]
    for col in comment_columns:
        df[col] = df[col].apply(transform_comments_to_html)

    html_columns = set(comment_columns) | {
        col for col in ['seq_limsid', 'nd_limsid', 'qubit_limsid', 'prep_limsid'] if col in df.columns
    }
    df = sanitize_dataframe_strings(df, skip_columns=html_columns)

    return df

def fetch_sequencing_data():
    """Fetch sequencing run data from Postgres when configured, otherwise from SQLite."""
    sequencing_type_ids = _get_clarity_pg_sequencing_type_ids()
    if sequencing_type_ids:
        df, meta_created = _fetch_sequencing_data_from_postgres()
    else:
        df = query_to_dataframe("SELECT * FROM ilmn_sequencing")
        meta_created = get_table_update_timestamp('ilmn_sequencing')

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
                # Try different possible locations of version information
                if "tool" in data and "poetry" in data["tool"]:
                    return data["tool"]["poetry"].get("version", "Unknown")
                elif "project" in data:
                    return data["project"].get("version", "Unknown")
                else:
                    # Direct search for version if not in expected locations
                    for section in data:
                        if "version" in data[section]:
                            return data[section]["version"]
        
        return "Unknown"
    except Exception as e:
        return "Unknown"
