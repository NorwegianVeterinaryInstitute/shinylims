'''
db_utils.py
Database utility functions for ShinyLIMS SQLite interactions.

This module manages SQLite database connections and queries for ShinyLIMS, 
with support for downloading databases from Posit Connect pins. It provides 
connection management, query execution, and database status monitoring.
'''

import sqlite3
import pandas as pd
from contextlib import contextmanager
import os
from pins import board_connect
from dotenv import load_dotenv
import datetime

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
        conn = None
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    finally:
        if conn:
            conn.close()


def refresh_db_connection():
    """Force a refresh of the database connection."""
    global _DB_PATH, _DB_PATH_ERROR

    _DB_PATH = None
    _DB_PATH_ERROR = None


####################
# DATABASE QUERIES #
####################

def query_to_dataframe(query, params=None):
    """Execute a SQL query and return results as a pandas DataFrame."""
    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=params)
    

def get_db_update_info():
    """Get database update information from the update log."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if update_log table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='update_log'")
            has_log = cursor.fetchone() is not None
            
            if not has_log:
                # Fall back to file modification time
                db_path = get_db_path()
                if os.path.exists(db_path):
                    mod_time = os.path.getmtime(db_path)
                    return {
                        'last_update': datetime.datetime.fromtimestamp(mod_time).isoformat(),
                        'update_method': 'file_timestamp',
                        'updates': []
                    }
            
            # Get the most recent successful update for each table
            cursor.execute("""
                WITH RankedUpdates AS (
                    SELECT 
                        script_name, 
                        timestamp, 
                        status, 
                        records_affected, 
                        tables_affected,
                        execution_time_s,
                        ROW_NUMBER() OVER (PARTITION BY tables_affected ORDER BY timestamp DESC) as rn
                    FROM update_log
                    WHERE status = 'success'
                )
                SELECT script_name, timestamp, status, records_affected, tables_affected, execution_time_s
                FROM RankedUpdates
                WHERE rn = 1
                ORDER BY timestamp DESC
            """)
            latest_updates = cursor.fetchall()
            
            # Get the 5 most recent updates regardless of status
            cursor.execute("""
                SELECT script_name, timestamp, status, records_affected, tables_affected, execution_time_s, error_message
                FROM update_log
                ORDER BY timestamp DESC
                LIMIT 5
            """)
            recent_updates = cursor.fetchall()
            
            # Format the results
            table_updates = {}
            for update in latest_updates:
                table = update[4]  # tables_affected
                table_updates[table] = {
                    'script': update[0],
                    'timestamp': update[1],
                    'status': update[2],
                    'records_affected': update[3],
                    'execution_time': update[5]
                }
            
            updates = []
            for update in recent_updates:
                updates.append({
                    'script': update[0],
                    'timestamp': update[1],
                    'status': update[2],
                    'records_affected': update[3],
                    'tables_affected': update[4],
                    'execution_time': update[5],
                    'error': update[6]
                })
            
            # Get the most recent successful update timestamp
            last_update = max([upd['timestamp'] for upd in table_updates.values()]) if table_updates else None
            
            return {
                'last_update': last_update,
                'update_method': 'update_log',
                'table_updates': table_updates,
                'recent_updates': updates
            }
    except Exception as e:
        print(f"Error getting database update info: {e}")
        return {
            'last_update': datetime.datetime.now().isoformat(),
            'update_method': 'error',
            'table_updates': {},
            'recent_updates': [],
            'error': str(e)
        }
