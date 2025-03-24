'''
data_utils.py module.
Utility functions for data fetching and transformation.

This module provides functions to fetch and transform data from various sources
including SQLite databases and Posit Connect pins. It handles data for projects,
samples, and sequencing runs with standardized column naming and formatting.
'''

####################
# IMPORT LIBRARIES #
####################

import pandas as pd
import datetime
from src.shinylims.data.db_utils import query_to_dataframe, get_db_update_info
import numpy as np
from pathlib import Path
import tomli

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
    ids = limsid.split(',')
    html_links = []
    for id in ids:
        parts = id.split('-')
        if len(parts) == 2:
            html_link = f'<a href="https://nvi-prod.claritylims.com/clarity/work-complete/{parts[1]}" target="_blank">{id}</a>'
            html_links.append(html_link)
        else:
            # Handle incorrectly formatted id
            html_links.append(id)
    return ', '.join(html_links)


def transform_comments_to_html(comment):
    '''Transform comments to HTML format with line breaks (db linebraks are \n, we need <br>).'''
    if pd.isna(comment) or comment == '':
        return comment
    return comment.replace('\n', '<br>')




####################
# DATA FETCHING    #
####################


def fetch_projects_data():
    """Fetch projects data from SQLite and rename columns to match the app."""

    # Query the projects table
    df = query_to_dataframe("SELECT * FROM projects")
    
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
    
    # Get the actual update timestamp for this table instead of current time
    meta_created = get_table_update_timestamp('projects')

    # Transform comments
    comment_columns = [col for col in df.columns if 'comment' in col.lower()]
    for col in comment_columns:
        df[col] = df[col].apply(transform_comments_to_html)
    
    return df, meta_created


def fetch_all_samples_data():
    """Fetch all samples data from SQLite and rename columns to match the app."""

    # Query all samples
    df = query_to_dataframe("SELECT * FROM samples")
    
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
    
    meta_created = get_table_update_timestamp('samples')
    
    return df, meta_created


def fetch_sequencing_data():
    """Fetch sequencing run data from SQLite and rename columns to match the app."""

    df = query_to_dataframe("SELECT * FROM ilmn_sequencing")
    
    # Rename columns to match what the app expects
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

    # Apply transformations
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    
    # Replace NaN values
    df = df.replace(np.nan, '', regex=True)

    # Transform LIMS IDs to HTML links
    for col in ['seq_limsid', 'nd_limsid', 'qubit_limsid', 'prep_limsid']:
        if col in df.columns:
            df[col] = df[col].apply(transform_to_html)

    
    meta_created = get_table_update_timestamp('ilmn_sequencing')
    
    return df, meta_created


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


