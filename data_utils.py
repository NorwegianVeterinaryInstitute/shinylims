# data_fetcher.py
import pandas as pd
from pins import board_connect

def fetch_pinned_data(pin_name):
    board = board_connect()
    df = board.pin_read(pin_name)
    if 'Open Date' in df.columns:
        df['Open Date'] = pd.to_datetime(df['Open Date'])
    if 'Received Date' in df.columns:
        df['Received Date'] = pd.to_datetime(df['Received Date'])
    meta_created = board.pin_meta(pin_name).created

    return df, meta_created