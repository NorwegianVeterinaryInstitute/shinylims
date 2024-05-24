#from pathlib import Path

import pandas as pd
from pins import board_connect

#app_dir = Path(__file__).parent

board = board_connect()

#df = board.pin_read("vi2451/penguins_limsshiny")


wgs_df = board.pin_read("vi2172/wgs_samples_limsshiny")
meta = board.pin_meta("vi2172/wgs_samples_limsshiny")
wgs_date_created = meta.created