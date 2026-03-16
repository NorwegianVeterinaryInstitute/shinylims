"""Static configuration for Illumina index plate map parsing and layout."""

from __future__ import annotations

import re

SUPPORTED_INDEX_SET_LETTERS = ("A", "B", "C", "D")
PLATE_ROWS = tuple("ABCDEFGH")
PLATE_COLUMNS = tuple(range(1, 13))

INDEX_SET_PATTERNS = (
    re.compile(r"\bSET\s*([A-D])\b", re.IGNORECASE),
    re.compile(r"\b([A-D])\s*#\s*\d+", re.IGNORECASE),
)

INDEX_NOTE_PREFIX_PATTERNS = (
    re.compile(r"^\s*Kolonne\s+(?P<body>.+)$", re.IGNORECASE),
    re.compile(r"^\s*Column\s+(?P<body>.+)$", re.IGNORECASE),
)

INDEX_NOTE_SEGMENT_PATTERN = re.compile(
    r"(?P<column>\d{1,2})(?:\s*\((?P<wells>[^)]*)\))?",
    re.IGNORECASE,
)

INDEX_NOTE_WELL_PATTERN = re.compile(r"\b(?P<row>[A-H])0?(?P<column>[1-9]|1[0-2])\b", re.IGNORECASE)


def normalize_well(row: str, column: int) -> str:
    """Return a canonical 96-well plate label such as A01."""
    return f"{row.upper()}{column:02d}"


def wells_for_column(column: int) -> list[str]:
    """Return all wells for one 96-well plate column."""
    return [normalize_well(row, column) for row in PLATE_ROWS]
