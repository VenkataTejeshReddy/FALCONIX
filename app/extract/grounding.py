# Owner: Laptop A
"""INX – Evidence grounding: link extracted values back to source positions.

After extraction, each :class:`FieldResult` should carry a verbatim
``evidence_quote`` and a ``bbox``.  This module handles the reverse-lookup:
given a field value, find the span in the :class:`ParsedDocument` that most
likely produced it, and record page + bbox.
"""

from __future__ import annotations

from app.schemas import BBox, FieldResult, ParsedDocument


def ground_field(
    result: FieldResult,
    doc: ParsedDocument,
    fuzzy_threshold: float = 0.85,
) -> FieldResult:
    """Attach a source quote and bounding box to an already-extracted field.

    Uses fuzzy string matching (``rapidfuzz``) to locate the evidence span
    within the parsed lines of *doc*.

    Args:
        result: The extracted :class:`FieldResult` (value must be set).
        doc: The :class:`ParsedDocument` to search within.
        fuzzy_threshold: Minimum similarity ratio (0–1) for a match.

    Returns:
        A copy of *result* with ``evidence_quote``, ``page``, and ``bbox``
        populated if a match is found.  Returns *result* unchanged if no
        match meets the threshold.
    """
    raise NotImplementedError


def ground_all_fields(
    fields: dict[str, FieldResult],
    docs: list["app.schemas.DocumentRecord"],  # noqa: F821
    fuzzy_threshold: float = 0.85,
) -> None:
    """Ground every field result in *fields* in-place.

    Iterates over the field dict and calls :func:`ground_field` for each
    result that has a ``value`` but is missing ``evidence_quote``.

    Args:
        fields: Mapping of field_name -> :class:`FieldResult`.
        docs: List of :class:`DocumentRecord` objects whose ``parsed``
            attribute is set.
        fuzzy_threshold: Forwarded to :func:`ground_field`.
    """
    raise NotImplementedError
