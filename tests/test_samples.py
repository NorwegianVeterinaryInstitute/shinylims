from __future__ import annotations

import pandas as pd

from shinylims.features.samples import (
    _batch_filter_non_matches_csv,
    _find_batch_filter_matches,
)


def test_find_batch_filter_matches_returns_sorted_non_matches():
    df = pd.DataFrame(
        {
            "Sample Name": ["alpha", "beta", "gamma"],
            "LIMS ID": ["L1", "L2", "L3"],
        }
    )

    found, not_found = _find_batch_filter_matches(
        df, "Sample Name", {"gamma", "missing-b", "alpha", "missing-a"}
    )

    assert found == {"alpha", "gamma"}
    assert not_found == ["missing-a", "missing-b"]


def test_batch_filter_non_matches_csv_uses_selected_column_header():
    csv_text = _batch_filter_non_matches_csv(["L9", "L10"], "LIMS ID")

    assert csv_text == "LIMS ID\nL9\nL10\n"
