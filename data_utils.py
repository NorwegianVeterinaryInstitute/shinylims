import pandas as pd
from pins import board_connect
from shiny import ui
import numpy as np


def transform_to_html(limsid):
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


def fetch_pinned_data(pin_name):
    
    board = board_connect()
    df = board.pin_read(pin_name)
    if 'Open Date' in df.columns:
        df['Open Date'] = pd.to_datetime(df['Open Date'])
    if 'Received Date' in df.columns:
        df['Received Date'] = pd.to_datetime(df['Received Date'])
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'])

    # Replace NaN-values with empty string
    df = df.replace(np.nan, '', regex=True)

    # Find created date
    meta_created = board.pin_meta(pin_name).created

    # Add html link for limsids

    if "seq_limsid" in df.columns:
        df['seq_limsid'] = df['seq_limsid'].apply(transform_to_html)

    if "nd_limsid" in df.columns:
        df['nd_limsid'] = df['nd_limsid'].apply(transform_to_html)

    if "qubit_limsid" in df.columns:
        df['qubit_limsid'] = df['qubit_limsid'].apply(transform_to_html)
    
    if "prep_limsid" in df.columns:
        df['prep_limsid'] = df['prep_limsid'].apply(transform_to_html)


    return df, meta_created
