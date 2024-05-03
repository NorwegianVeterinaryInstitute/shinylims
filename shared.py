#from pathlib import Path

import pandas as pd
from pins import board_connect

#app_dir = Path(__file__).parent

board = board_connect()

df = board.pin_read("vi2451/penguins_limsshiny")
