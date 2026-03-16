"""Canonical reagent configuration used by UI and LIMS API modules.

Edit ``REAGENT_DEFINITIONS`` to maintain the reagent registry.

Top-level reagent fields:
- `type_name`: Human-readable reagent type name used as the logical key across
  the app and in LIMS submissions.

- `kit_id`: Numeric Clarity reagent kit ID as a string, for example ``"302"``.
  Found in BASEURI/reagentkits

- `naming_group`: Internal naming rule group. Allowed values are `prep`,
  `index`, `miseq`, and `phix`. This controls how the app generates the
  `Internal Name`:

  `prep` uses shared numeric prep-set numbering such as `#15 (192)`,
  `index` uses shared numbering plus `set_letter` such as `A#15 (192)`,
  `miseq` uses `RGT Number + MiSeq kit type`, 
  `phix` uses the RGT number directly.

- `requires_rgt_number`: Whether the UI must collect an RGT number before the
  reagent can be queued or submitted.

- `requires_miseq_kit_type`: Whether each variant must define a MiSeq kit type
  such as `v3` or `v2 nano`.

- `submission_status`: Optional LIMS submission status. Allowed values are
  `ACTIVE` and `PENDING`. Defaults to `ACTIVE` if omitted.

- `variants`: List of scanner/dropdown entries that map refs to this reagent
  type.

Variant fields:
- `ref`: Scanned reference barcode / selector value shown in the UI. Used only for scan reference.

- `label`: User-facing selector label.

- `set_letter`: Required for index variants. Used when generating names such as `A#15 (192)`.

- `miseq_kit_type`: Required when `requires_miseq_kit_type` is `True`.

Derived exports:
- `REAGENT_TYPES`: Lightweight metadata keyed by `type_name`.

- `SCANNABLE_REAGENTS`: Flattened list of all selectable/scannable variants.

- `PREP_REAGENT_TYPES`: All reagent types with `naming_group == "prep"`.

- `REAGENT_KIT_IDS`: `type_name` to Clarity `kit_id` mapping.
- `REAGENT_SELECTOR_CHOICES` / `SELECTOR_TO_REAGENT` /
  `SELECTOR_TO_MISEQ_KIT_TYPE`: UI lookup structures generated from the registry.

- `INDEX_REAGENT_TYPE`: The single index reagent type used by current shared
  numbering logic.

The module validates the registry at import time and raises a clear error if the
configuration is inconsistent.
"""

from __future__ import annotations

import re

ALLOWED_NAMING_GROUPS = {"prep", "index", "miseq", "phix"}
ALLOWED_SUBMISSION_STATUSES = {"ACTIVE", "PENDING"}

# Canonical reagent registry.
# Maintain reagent behavior and options by editing this list only.
REAGENT_DEFINITIONS = [
    {
        "type_name": "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp",
        "kit_id": "4", #nvi-test: 203
        "naming_group": "prep",
        "requires_rgt_number": False,
        "requires_miseq_kit_type": False,
        "submission_status": "PENDING",
        "variants": [
            {
                "ref": "20049006",
                "label": "Illumina DNA Prep - IPB + Buffers (SPB, TSB, TWB) 96sp (Ref: 20049006)",
            },
        ],
    },
    {
        "type_name": "Illumina DNA Prep –  PCR + Buffers (EPM,TB1,RSB) 96sp",
        "kit_id": "5", #nvi-test: 202
        "naming_group": "prep",
        "requires_rgt_number": False,
        "requires_miseq_kit_type": False,
        "submission_status": "PENDING",
        "variants": [
            {
                "ref": "20015829",
                "label": "Illumina DNA Prep –  PCR + Buffers (EPM,TB1,RSB) 96sp (Ref: 20015829)",
            },
        ],
    },
    {
        "type_name": "Illumina DNA Prep – Tagmentation (M) Beads 96sp",
        "kit_id": "6", #nvi-test: 102
        "naming_group": "prep",
        "requires_rgt_number": False,
        "requires_miseq_kit_type": False,
        "submission_status": "PENDING",
        "variants": [
            {
                "ref": "20015880",
                "label": "Illumina DNA Prep – Tagmentation (M) Beads 96sp (Ref: 20015880)",
            },
        ],
    },
    {
        "type_name": "IDT-ILMN DNA/RNA UD Index Sets",
        "kit_id": "3", #nvi-test: 302
        "naming_group": "index",
        "requires_rgt_number": False,
        "requires_miseq_kit_type": False,
        "submission_status": "PENDING",
        "variants": [
            {
                "ref": "20091646",
                "label": "IDT-ILMN DNA/RNA UD Index Sets - Set A (Ref: 20091646)",
                "set_letter": "A",
            },
            {
                "ref": "20091647",
                "label": "IDT-ILMN DNA/RNA UD Index Sets - Set B (Ref: 20091647)",
                "set_letter": "B",
            },
            {
                "ref": "20091648",
                "label": "IDT-ILMN DNA/RNA UD Index Sets - Set C (Ref: 20091648)",
                "set_letter": "C",
            },
            {
                "ref": "20091649",
                "label": "IDT-ILMN DNA/RNA UD Index Sets - Set D (Ref: 20091649)",
                "set_letter": "D",
            },
        ],
    },
    {
        "type_name": "MiSeq Reagent Kit (Box 1 of 2)",
        "kit_id": "7", #nvi-test: 35
        "naming_group": "miseq",
        "requires_rgt_number": True,
        "requires_miseq_kit_type": True,
        "variants": [
            {
                "ref": "15043895",
                "label": "MiSeq Reagent Kit v3 (Box 1 of 2) (Ref: 15043895)",
                "miseq_kit_type": "v3",
            },
            {
                "ref": "15033625",
                "label": "MiSeq Reagent Kit v2 nano (Box 1 of 2) (Ref: 15033625)",
                "miseq_kit_type": "v2 nano",
            },
            {
                "ref": "15033624",
                "label": "MiSeq Reagent Kit v2 micro (Box 1 of 2) (Ref: 15033624)",
                "miseq_kit_type": "v2 micro",
            },
        ],
    },
    {
        "type_name": "MiSeq Reagent Kit (Box 2 of 2)",
        "kit_id": "8", #nvi-test: 252
        "naming_group": "miseq",
        "requires_rgt_number": True,
        "requires_miseq_kit_type": True,
        "variants": [
            {
                "ref": "15043894",
                "label": "MiSeq Reagent Kit v3 (Box 2 of 2) (Ref: 15043894)",
                "miseq_kit_type": "v3",
            },
            {
                "ref": "15036714",
                "label": "MiSeq Reagent Kit v2 nano (Box 2 of 2) (Ref: 15036714)",
                "miseq_kit_type": "v2 nano",
            },
            {
                "ref": "15036715",
                "label": "MiSeq Reagent Kit v2 micro (Box 2 of 2) (Ref: 15036715)",
                "miseq_kit_type": "v2 micro",
            },
        ],
    },
    {
        "type_name": "PhiX Control v3",
        "kit_id": "12", #nvi-test: 152
        "naming_group": "phix",
        "requires_rgt_number": True,
        "requires_miseq_kit_type": False,
        "submission_status": "PENDING",
        "variants": [
            {
                "ref": "15017666",
                "label": "PhiX Control v3 (Ref: 15017666)",
            },
        ],
    },
]


def _as_clean_str(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _validate_reagent_definitions() -> None:
    errors: list[str] = []
    seen_type_names: dict[str, int] = {}
    seen_refs: dict[str, str] = {}
    index_type_names: list[str] = []

    for reagent_idx, reagent in enumerate(REAGENT_DEFINITIONS, start=1):
        type_name = _as_clean_str(reagent.get("type_name"))
        if not type_name:
            errors.append(
                f"Entry #{reagent_idx}: missing 'type_name'. "
                "Set a non-empty reagent type string."
            )
            continue

        if type_name in seen_type_names:
            errors.append(
                f"Reagent '{type_name}' is duplicated (entries #{seen_type_names[type_name]} "
                f"and #{reagent_idx}). Keep reagent type names unique."
            )
        else:
            seen_type_names[type_name] = reagent_idx

        kit_id = _as_clean_str(reagent.get("kit_id"))
        if not kit_id:
            errors.append(
                f"Reagent '{type_name}': missing 'kit_id'. Set the numeric Clarity reagent kit ID."
            )
        elif re.fullmatch(r"\d+", kit_id) is None:
            errors.append(
                f"Reagent '{type_name}': invalid kit_id '{kit_id}'. "
                "Use digits only, for example '302'."
            )

        naming_group = _as_clean_str(reagent.get("naming_group"))
        if naming_group not in ALLOWED_NAMING_GROUPS:
            allowed = ", ".join(sorted(ALLOWED_NAMING_GROUPS))
            errors.append(
                f"Reagent '{type_name}': invalid naming_group '{naming_group}'. "
                f"Allowed values: {allowed}."
            )
        if naming_group == "index":
            index_type_names.append(type_name)

        requires_miseq_kit_type = bool(reagent.get("requires_miseq_kit_type"))
        submission_status = _as_clean_str(reagent.get("submission_status")) or "ACTIVE"
        if submission_status not in ALLOWED_SUBMISSION_STATUSES:
            allowed = ", ".join(sorted(ALLOWED_SUBMISSION_STATUSES))
            errors.append(
                f"Reagent '{type_name}': invalid submission_status '{submission_status}'. "
                f"Allowed values: {allowed}."
            )

        variants = reagent.get("variants")
        if not isinstance(variants, list) or len(variants) == 0:
            errors.append(
                f"Reagent '{type_name}': 'variants' must be a non-empty list."
            )
            continue

        for variant_idx, variant in enumerate(variants, start=1):
            if not isinstance(variant, dict):
                errors.append(
                    f"Reagent '{type_name}' variant #{variant_idx}: must be a dictionary."
                )
                continue

            ref = _as_clean_str(variant.get("ref"))
            label = _as_clean_str(variant.get("label"))

            if not ref:
                errors.append(
                    f"Reagent '{type_name}' variant #{variant_idx}: missing 'ref'."
                )
            else:
                previous = seen_refs.get(ref)
                if previous is not None:
                    errors.append(
                        f"Reagent ref '{ref}' is duplicated between {previous} and "
                        f"'{type_name}' variant #{variant_idx}. Refs must be globally unique."
                    )
                else:
                    seen_refs[ref] = f"'{type_name}' variant #{variant_idx}"

            if not label:
                errors.append(
                    f"Reagent '{type_name}' variant #{variant_idx}: missing 'label'."
                )

            if naming_group == "index":
                set_letter = _as_clean_str(variant.get("set_letter"))
                if not set_letter:
                    errors.append(
                        f"Reagent '{type_name}' variant ref '{ref or '?'}': missing 'set_letter'. "
                        "Index variants must define set_letter (A/B/C/D...)."
                    )

            if requires_miseq_kit_type:
                miseq_kit_type = _as_clean_str(variant.get("miseq_kit_type"))
                if not miseq_kit_type:
                    errors.append(
                        f"Reagent '{type_name}' variant ref '{ref or '?'}': missing 'miseq_kit_type'. "
                        "This reagent requires requires_miseq_kit_type=True."
                    )

    if len(index_type_names) != 1:
        errors.append(
            "Exactly one index reagent type is required by current numbering logic. "
            f"Found: {index_type_names or 'none'}."
        )

    if errors:
        formatted = "\n- ".join(errors)
        raise ValueError(
            "Invalid reagent configuration in shinylims.config.reagents:\n"
            f"- {formatted}"
        )


def _build_derived_exports():
    reagent_types: dict[str, dict[str, object]] = {}
    prep_reagent_types: list[str] = []
    reagent_kit_ids: dict[str, str] = {}
    scannable_reagents: list[dict[str, str]] = []
    index_reagent_type: str | None = None

    for reagent in REAGENT_DEFINITIONS:
        type_name = _as_clean_str(reagent["type_name"])
        naming_group = _as_clean_str(reagent["naming_group"])

        reagent_types[type_name] = {
            "naming_group": naming_group,
            "submission_status": _as_clean_str(reagent.get("submission_status")) or "ACTIVE",
        }
        if bool(reagent.get("requires_rgt_number")):
            reagent_types[type_name]["requires_rgt_number"] = True
        if bool(reagent.get("requires_miseq_kit_type")):
            reagent_types[type_name]["requires_miseq_kit_type"] = True

        reagent_kit_ids[type_name] = _as_clean_str(reagent["kit_id"])

        if naming_group == "prep":
            prep_reagent_types.append(type_name)
        if naming_group == "index":
            index_reagent_type = type_name

        for variant in reagent["variants"]:
            item = {
                "ref": _as_clean_str(variant["ref"]),
                "label": _as_clean_str(variant["label"]),
                "reagent_type": type_name,
            }
            set_letter = _as_clean_str(variant.get("set_letter"))
            if set_letter:
                item["set_letter"] = set_letter
            miseq_kit_type = _as_clean_str(variant.get("miseq_kit_type"))
            if miseq_kit_type:
                item["miseq_kit_type"] = miseq_kit_type
            scannable_reagents.append(item)

    # Preserve historical MiSeq selector order by kit type first, then box number.
    # Example: v3 Box1, v3 Box2, v2 nano Box1, v2 nano Box2.
    miseq_positions = [
        idx
        for idx, item in enumerate(scannable_reagents)
        if reagent_types[item["reagent_type"]].get("naming_group") == "miseq"
    ]
    if miseq_positions:
        miseq_items = [scannable_reagents[idx] for idx in miseq_positions]
        kit_type_order: dict[str, int] = {}
        box_order: dict[str, int] = {}
        for item in miseq_items:
            kit_type = _as_clean_str(item.get("miseq_kit_type"))
            if kit_type not in kit_type_order:
                kit_type_order[kit_type] = len(kit_type_order)
            reagent_type = item["reagent_type"]
            if reagent_type not in box_order:
                box_order[reagent_type] = len(box_order)

        sorted_miseq_items = sorted(
            miseq_items,
            key=lambda item: (
                kit_type_order[_as_clean_str(item.get("miseq_kit_type"))],
                box_order[item["reagent_type"]],
            ),
        )
        for idx, sorted_item in zip(miseq_positions, sorted_miseq_items):
            scannable_reagents[idx] = sorted_item

    choices = {"": ""}
    selector_to_reagent: dict[str, tuple[str, str | None]] = {}
    selector_to_miseq_kit_type: dict[str, str] = {}
    for item in scannable_reagents:
        ref = item["ref"]
        choices[ref] = item["label"]
        selector_to_reagent[ref] = (item["reagent_type"], item.get("set_letter"))
        miseq_kit_type = item.get("miseq_kit_type")
        if miseq_kit_type:
            selector_to_miseq_kit_type[ref] = miseq_kit_type

    if index_reagent_type is None:
        # Should not happen due validation, keep explicit guard.
        raise ValueError(
            "Invalid reagent configuration: missing index reagent type after validation."
        )

    return (
        reagent_types,
        prep_reagent_types,
        scannable_reagents,
        reagent_kit_ids,
        choices,
        selector_to_reagent,
        selector_to_miseq_kit_type,
        index_reagent_type,
    )


_validate_reagent_definitions()
(
    REAGENT_TYPES,
    PREP_REAGENT_TYPES,
    SCANNABLE_REAGENTS,
    REAGENT_KIT_IDS,
    REAGENT_SELECTOR_CHOICES,
    SELECTOR_TO_REAGENT,
    SELECTOR_TO_MISEQ_KIT_TYPE,
    INDEX_REAGENT_TYPE,
) = _build_derived_exports()

__all__ = [
    "INDEX_REAGENT_TYPE",
    "PREP_REAGENT_TYPES",
    "REAGENT_DEFINITIONS",
    "REAGENT_KIT_IDS",
    "REAGENT_SELECTOR_CHOICES",
    "REAGENT_TYPES",
    "SCANNABLE_REAGENTS",
    "SELECTOR_TO_MISEQ_KIT_TYPE",
    "SELECTOR_TO_REAGENT",
]
