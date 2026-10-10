# Owner: Laptop A
"""INX – Field reconciliation: merge OCR and VLM values into a consensus.

When two readers produce different values for the same field, this module
decides which value to trust (or sets ``status=conflict`` if they are
irreconcilable).

Rules (in priority order):
1. If both readers agree → value = agreed; confidence = max(both).
2. If one reader produced no value → take the other; confidence = lower.
3. If values differ by ≤ ``fuzzy_threshold`` (e.g. minor OCR noise) →
   take the higher-confidence value; status = valid.
4. If values differ significantly → status = conflict; both raw values
   are stored in ``ocr_value`` / ``vlm_value``.
"""

from __future__ import annotations

from app.schemas import FieldResult, FieldStatus


def reconcile_field(
    ocr_result: FieldResult,
    vlm_result: FieldResult,
    fuzzy_threshold: float = 0.90,
) -> FieldResult:
    """Produce a single :class:`FieldResult` from two reader outputs.

    Args:
        ocr_result: Output from the OCR / text reader.
        vlm_result: Output from the VLM reader.
        fuzzy_threshold: Minimum string similarity to treat values as
            equivalent (uses ``rapidfuzz.fuzz.ratio``).

    Returns:
        Merged :class:`FieldResult` following the priority rules above.
    """
    raise NotImplementedError


def reconcile_case_fields(
    fields_ocr: dict[str, FieldResult],
    fields_vlm: dict[str, FieldResult],
    fuzzy_threshold: float = 0.90,
) -> dict[str, FieldResult]:
    """Reconcile all fields for a case across two reader outputs.

    Args:
        fields_ocr: Fields extracted by the OCR reader.
        fields_vlm: Fields extracted by the VLM reader.
        fuzzy_threshold: Forwarded to :func:`reconcile_field`.

    Returns:
        Merged field dict ready to be stored in ``CaseRecord.fields``.
    """
    raise NotImplementedError
