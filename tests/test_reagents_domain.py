from __future__ import annotations

import pandas as pd

from shinylims.config.reagents import PREP_REAGENT_TYPES
from shinylims.features.reagents.domain import (
    QUEUE_COLUMNS,
    get_pending_edit_internal_name_error,
    get_prep_queue_mismatch_details,
    get_queue_removal_error,
)


def make_row(**overrides):
    row = {
        "Reagent Type": "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp",
        "Lot Number": "LOT-001",
        "Expiry Date": "2026-12-31",
        "Internal Name": "#41 (192)",
        "Set Letter": "",
        "MiSeq Kit Type": "",
        "RGT Number": "",
    }
    row.update(overrides)
    return row


def make_df(*rows):
    return pd.DataFrame(rows, columns=QUEUE_COLUMNS)


PREP_PCR_REAGENT_TYPE = next(
    reagent_type
    for reagent_type in PREP_REAGENT_TYPES
    if "PCR + Buffers" in reagent_type
)


def test_metadata_only_edit_keeps_internal_name_stable():
    row = make_row()

    error = get_pending_edit_internal_name_error(
        row,
        {
            "Lot Number": "LOT-002",
            "Expiry Date": "2027-01-31",
        },
    )

    assert error is None


def test_miseq_rgt_change_is_rejected():
    row = make_row(
        **{
            "Reagent Type": "MiSeq Reagent Kit (Box 1 of 2)",
            "Internal Name": "RGT36182951 v3",
            "MiSeq Kit Type": "v3",
            "RGT Number": "RGT36182951",
        }
    )

    error = get_pending_edit_internal_name_error(
        row,
        {"RGT Number": "RGT00000001"},
    )

    assert error == "Changing RGT Number would alter the Internal Name. Remove and re-add the lot instead."


def test_index_set_letter_change_is_rejected():
    row = make_row(
        **{
            "Reagent Type": "IDT-ILMN DNA/RNA UD Index Sets",
            "Internal Name": "A#15 (192)",
            "Set Letter": "A",
        }
    )

    error = get_pending_edit_internal_name_error(
        row,
        {"Set Letter": "B"},
    )

    assert error == "Changing Set Letter would alter the Internal Name. Remove and re-add the lot instead."


def test_prep_reagent_type_change_is_rejected():
    row = make_row()

    error = get_pending_edit_internal_name_error(
        row,
        {"Reagent Type": "Illumina DNA Prep – PCR + Buffers (EPM, TB1, RSB) 96sp"},
    )

    assert error == "Changing Reagent Type would alter the Internal Name. Remove and re-add the lot instead."


def test_non_latest_prep_queue_removal_still_blocked():
    pending_lots = make_df(
        make_row(
            **{
                "Reagent Type": "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp",
                "Internal Name": "#41 (192)",
            }
        ),
        make_row(
            **{
                "Reagent Type": PREP_PCR_REAGENT_TYPE,
                "Internal Name": "#42 (192)",
            }
        ),
    )

    error = get_queue_removal_error(pending_lots, 0)

    assert error == "For prep lots, remove the latest number first (#42)."


def test_prep_queue_mismatch_details_returns_bullet_ready_entries():
    pending_lots = make_df(
        make_row(
            **{
                "Reagent Type": "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp",
                "Internal Name": "#41 (192)",
            }
        ),
        make_row(
            **{
                "Reagent Type": "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp",
                "Internal Name": "#42 (192)",
            }
        ),
        make_row(
            **{
                "Reagent Type": PREP_PCR_REAGENT_TYPE,
                "Internal Name": "#43 (192)",
            }
        ),
    )

    details = get_prep_queue_mismatch_details(pending_lots)

    assert details == [
        "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp: 2",
        f"{PREP_PCR_REAGENT_TYPE}: 1",
        "Illumina DNA Prep – Tagmentation (M) Beads 96sp: 0",
    ]
