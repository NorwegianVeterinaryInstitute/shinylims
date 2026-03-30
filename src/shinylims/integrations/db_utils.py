'''
db_utils.py
SQLite helper functions retained for the historical samples dataset.

This module downloads the legacy SQLite pin from Posit Connect and provides
read-only query helpers for the `samples_historical` table.
'''

import sqlite3
import pandas as pd
from contextlib import contextmanager
import os
from pins import board_connect
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Variables to track database file
_DB_PATH = None
_DB_PATH_ERROR = None


####################
# DATABASE CONNECT #
####################

def get_db_path():
    """Get the path to the SQLite database file from pin."""
    global _DB_PATH, _DB_PATH_ERROR

    if _DB_PATH_ERROR is not None:
        raise RuntimeError(_DB_PATH_ERROR)
    
    if _DB_PATH is None:
        try:
            # Connect to Posit Connect board
            board = board_connect(
                api_key=os.getenv('POSIT_API_KEY'), 
                server_url=os.getenv('POSIT_SERVER_URL')
            )
            
            # Get database from pin
            db_pin_name = "vi2172/clarity_lims_sqlite"
            
            # Download pin - this returns a list with the file path
            result = board.pin_download(db_pin_name)
            
            # When downloading a file pin, the result is a list with the file path
            if isinstance(result, list) and len(result) > 0:
                db_path = result[0]  # Get the first file path
                
                # Check if the file exists
                if os.path.isfile(db_path):
                    _DB_PATH = db_path
                    _DB_PATH_ERROR = None
                else:
                    raise FileNotFoundError(f"Downloaded file path {db_path} does not exist")
            else:
                raise ValueError(f"Unexpected result from pin_download: {result}")
        except Exception as e:
            _DB_PATH_ERROR = str(e)
            raise RuntimeError(_DB_PATH_ERROR) from e
    
    return _DB_PATH


@contextmanager
def get_connection():
    """Context manager for SQLite connections."""
    conn = None
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        if conn:
            conn.close()


def query_to_dataframe(query, params=None):
    """Execute a SQL query and return results as a pandas DataFrame."""
    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=params)
