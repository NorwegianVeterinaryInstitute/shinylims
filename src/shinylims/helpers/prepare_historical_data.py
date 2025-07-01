import pandas as pd
import sqlite3
from pathlib import Path

def prepare_historical_data(csv_path, sqlite_path):
    """
    Convert historical CSV to match current samples schema and store in SQLite
    
    Args:
        csv_path: Path to historical CSV file
        sqlite_path: Path where to create historical SQLite database
    """
    
    # Define the exact schema from your main database
    samples_schema = [
        'limsid', 'project_limsid', 'received_date', 'progress', 'species_name',
        'name', 'project_name', 'submitter', 'submitting_lab', 'project_account',
        'experiment_name', 'extraction_number', 'concentration_absorbance',
        'a260_280_ratio', 'a260_230_ratio', 'concentration_fluorescence',
        'storage_box', 'storage_well', 'invoice_id', 'sample_type',
        'gram_stain', 'nird_filename', 'billing_description', 'price',
        'nd_limsid', 'qubit_limsid', 'prep_limsid', 'seq_limsid',
        'billed_limsid', 'increased_pooling', 'reagent_label'
    ]
    
    # Read historical CSV
    print(f"Reading historical data from {csv_path}")
    historical_df = pd.read_csv(csv_path)
    print(f"Historical CSV has {len(historical_df)} rows and columns: {list(historical_df.columns)}")
    
    # Create a new DataFrame with current schema
    aligned_df = pd.DataFrame(columns=samples_schema)
    
    # Column mapping - customize this based on your historical CSV column names
    column_mapping = {
        # Historical CSV column -> Database column
        'Løpende nr': 'limsid',                   # Will be prefixed with HIST_
         'PrøveID-(eksternt)-eller-PJS-nummer-(VI-internt)': 'name',
         'Bakterie art/stamme': 'species_name', 
         'Prosjekt': 'project_name',
         'Nanodrop, ng/µL': 'concentration_absorbance',
         'A260/A280': 'a260_280_ratio',
         'A260/A230 (2.0-2.2)': 'a260_230_ratio',
         'Qubit,  ng/µL': 'concentration_fluorescence',
         'Library Prep, startdato link (LPååååmmddINITIALER)' : 'experiment_name',
    }
    
    # Print available columns for mapping verification
    print("\nAvailable historical columns:")
    for i, col in enumerate(historical_df.columns):
        print(f"  {i+1}. {col}")
    
    # Transfer mapped data
    mapped_count = 0
    for hist_col, db_col in column_mapping.items():
        if hist_col in historical_df.columns:
            aligned_df[db_col] = historical_df[hist_col]
            mapped_count += 1
            print(f"Mapped: {hist_col} -> {db_col}")
        else:
            print(f"Warning: Historical column '{hist_col}' not found")
    
    # Fill remaining columns with None (will become NULL in SQLite)
    aligned_df = aligned_df.where(pd.notna(aligned_df), None)
    
    # Add a marker to identify historical data
    aligned_df['data_source'] = 'historical'
    
    # Handle LIMS ID with HIST_ prefix
    if 'limsid' in aligned_df.columns and not aligned_df['limsid'].isna().all():
        # Add HIST_ prefix to existing "Løpende nr" values
        aligned_df['limsid'] = aligned_df['limsid'].apply(
            lambda x: f"HIST_{x}" if pd.notna(x) else f"HIST_UNKNOWN_{pd.np.random.randint(100000, 999999)}"
        )
        print("Added HIST_ prefix to Løpende nr values")
    else:
        # Generate unique LIMS IDs if no "Løpende nr" column was mapped
        aligned_df['limsid'] = [f"HIST_{i+1:06d}" for i in range(len(aligned_df))]
        print("Generated new historical LIMS IDs")
    
    # Convert date format if needed (adjust based on your date format)
    if 'received_date' in aligned_df.columns and not aligned_df['received_date'].isna().all():
        aligned_df['received_date'] = pd.to_datetime(aligned_df['received_date'], errors='coerce').dt.strftime('%Y-%m-%d')
    
    print(f"\nPrepared {len(aligned_df)} historical records")
    print(f"Mapped {mapped_count} columns successfully")
    
    # Save to SQLite with the same table structure
    conn = sqlite3.connect(sqlite_path)
    
    # Create table with same schema as main database
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS samples (
        limsid TEXT PRIMARY KEY,
        project_limsid TEXT,
        received_date TEXT,
        progress TEXT,
        species_name TEXT,
        name TEXT,
        project_name TEXT,
        submitter TEXT,
        submitting_lab TEXT,
        project_account TEXT,
        experiment_name TEXT,
        extraction_number TEXT,
        concentration_absorbance TEXT,
        a260_280_ratio TEXT,
        a260_230_ratio TEXT,
        concentration_fluorescence TEXT,
        storage_box TEXT,
        storage_well TEXT,
        invoice_id TEXT,
        sample_type TEXT,
        gram_stain TEXT,
        nird_filename TEXT,
        billing_description TEXT,
        price TEXT,
        nd_limsid TEXT,
        qubit_limsid TEXT,
        prep_limsid TEXT,
        seq_limsid TEXT,
        billed_limsid TEXT,
        increased_pooling TEXT,
        reagent_label TEXT,
        data_source TEXT
    )
    """
    
    conn.execute(create_table_sql)
    aligned_df.to_sql('samples', conn, if_exists='replace', index=False)
    conn.close()
    
    print(f"Historical data saved to {sqlite_path}")
    return aligned_df

# Example usage:
if __name__ == "__main__":
    # Update these paths to match your setup
    csv_path = "/home/magnus/shinylims/src/shinylims/helpers/wgs_historical.csv"
    sqlite_path = "/home/magnus/shinylims/src/shinylims/helpers/historical_samples.db"
    
    # Run the preparation
    prepare_historical_data(csv_path, sqlite_path)

    