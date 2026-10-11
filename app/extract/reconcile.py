# Owner: Laptop A
"""INX – Field reconciliation: merge OCR locator and VLM outputs.

Rules:
- both null -> missing
- vlm null, ocr present -> unclear ("readers disagree")
- vlm present, ocr null: value in OCR text and quote grounded -> valid,
  confidence 0.75, reason says "locator did not find it"; otherwise unreliable
- both present, normalised equal -> valid, confidence high (needs grounded quote)
- both present, differ -> unclear, keep both values; never conflict on one page
- VLM obscured=true -> unclear
- the same field with different normalised values on different pages of one document
  -> conflict (value None, reason lists "page 1: X; page 2: Y"); pages up to
  long_doc_pages are all read.
"""

from __future__ import annotations

from typing import Any, Optional

from app.extract.grounding import (
    is_quote_grounded,
    is_value_grounded,
    values_are_equal,
)
from app.schemas import BBox, DocumentType, FieldResult, FieldStatus


def reconcile_single_page_field(
    field_name: str,
    doc_type: DocumentType,
    ocr_val: Optional[str],
    ocr_bbox: Optional[BBox],
    ocr_page: Optional[int],
    vlm_val: Optional[str],
    vlm_quote: Optional[str],
    vlm_obscured: bool,
    vlm_page: int,
    page_text: str,
    field_type: str = "text",
    source_doc_id: Optional[str] = None,
) -> FieldResult:
    """Reconcile OCR and VLM readings for a single field on a single page."""
    # 1. Both null
    if not ocr_val and not vlm_val:
        return FieldResult(
            field=field_name,
            doc_type=doc_type,
            value=None,
            ocr_value=None,
            vlm_value=None,
            evidence_quote=None,
            page=vlm_page,
            bbox=None,
            status=FieldStatus.missing,
            reason="Field not found in document",
            confidence=0.0,
            source_doc_id=source_doc_id,
        )

    # 2. VLM reports obscured
    if vlm_obscured:
        return FieldResult(
            field=field_name,
            doc_type=doc_type,
            value=vlm_val or ocr_val,
            ocr_value=ocr_val,
            vlm_value=vlm_val,
            evidence_quote=vlm_quote,
            page=ocr_page if ocr_page is not None else vlm_page,
            bbox=ocr_bbox,
            status=FieldStatus.unclear,
            reason="Field obscured",
            confidence=0.40,
            source_doc_id=source_doc_id,
        )

    # 3. VLM null, OCR present
    if ocr_val and not vlm_val:
        return FieldResult(
            field=field_name,
            doc_type=doc_type,
            value=ocr_val,
            ocr_value=ocr_val,
            vlm_value=None,
            evidence_quote=None,
            page=ocr_page if ocr_page is not None else vlm_page,
            bbox=ocr_bbox,
            status=FieldStatus.unclear,
            reason="readers disagree",
            confidence=0.50,
            source_doc_id=source_doc_id,
        )

    # 4. VLM present, OCR null
    if vlm_val and not ocr_val:
        val_grounded = is_value_grounded(vlm_val, field_type, page_text)
        quote_grounded = is_quote_grounded(vlm_quote, page_text)

        if val_grounded and quote_grounded:
            return FieldResult(
                field=field_name,
                doc_type=doc_type,
                value=vlm_val,
                ocr_value=None,
                vlm_value=vlm_val,
                evidence_quote=vlm_quote,
                page=vlm_page,
                bbox=None,
                status=FieldStatus.valid,
                reason="locator did not find it; grounded in OCR text",
                confidence=0.75,
                source_doc_id=source_doc_id,
            )
        else:
            reason = "unreliable"
            if not quote_grounded:
                reason = "evidence quote not grounded in OCR text"
            elif not val_grounded:
                reason = "VLM value not found in OCR text"
            return FieldResult(
                field=field_name,
                doc_type=doc_type,
                value=vlm_val,
                ocr_value=None,
                vlm_value=vlm_val,
                evidence_quote=vlm_quote,
                page=vlm_page,
                bbox=None,
                status=FieldStatus.unreliable,
                reason=reason,
                confidence=0.30,
                source_doc_id=source_doc_id,
            )

    # 5. Both present
    assert ocr_val is not None and vlm_val is not None
    are_equal = values_are_equal(ocr_val, vlm_val, field_type)

    if are_equal:
        quote_grounded = is_quote_grounded(vlm_quote, page_text)
        if quote_grounded:
            return FieldResult(
                field=field_name,
                doc_type=doc_type,
                value=ocr_val,
                ocr_value=ocr_val,
                vlm_value=vlm_val,
                evidence_quote=vlm_quote,
                page=ocr_page if ocr_page is not None else vlm_page,
                bbox=ocr_bbox,
                status=FieldStatus.valid,
                reason="OCR and VLM agree with grounded quote",
                confidence=0.95,
                source_doc_id=source_doc_id,
            )
        else:
            # If values match exactly and OCR has bbox, value is grounded
            val_grounded = is_value_grounded(ocr_val, field_type, page_text)
            if val_grounded:
                return FieldResult(
                    field=field_name,
                    doc_type=doc_type,
                    value=ocr_val,
                    ocr_value=ocr_val,
                    vlm_value=vlm_val,
                    evidence_quote=vlm_quote,
                    page=ocr_page if ocr_page is not None else vlm_page,
                    bbox=ocr_bbox,
                    status=FieldStatus.valid,
                    reason="OCR and VLM agree",
                    confidence=0.85,
                    source_doc_id=source_doc_id,
                )
            return FieldResult(
                field=field_name,
                doc_type=doc_type,
                value=ocr_val,
                ocr_value=ocr_val,
                vlm_value=vlm_val,
                evidence_quote=vlm_quote,
                page=ocr_page if ocr_page is not None else vlm_page,
                bbox=ocr_bbox,
                status=FieldStatus.unreliable,
                reason="evidence quote not grounded in OCR text",
                confidence=0.40,
                source_doc_id=source_doc_id,
            )
    else:
        # Both present, differ -> unclear; keep both values; never conflict on one page
        return FieldResult(
            field=field_name,
            doc_type=doc_type,
            value=ocr_val,
            ocr_value=ocr_val,
            vlm_value=vlm_val,
            evidence_quote=vlm_quote,
            page=ocr_page if ocr_page is not None else vlm_page,
            bbox=ocr_bbox,
            status=FieldStatus.unclear,
            reason=f"readers disagree: OCR={ocr_val!r}, VLM={vlm_val!r}",
            confidence=0.50,
            source_doc_id=source_doc_id,
        )


def reconcile_multi_page_results(
    field_name: str,
    page_results: list[FieldResult],
    field_type: str = "text",
) -> FieldResult:
    """Aggregate per-page results for a field into a single document FieldResult.

    If different pages have differing valid/unclear values:
      -> conflict (value None, reason lists 'page 1: X; page 2: Y')
    """
    if not page_results:
        return FieldResult(field=field_name, status=FieldStatus.missing)

    # Filter pages where a value was extracted
    with_val = [r for r in page_results if r.value is not None]
    if not with_val:
        # Return first result (missing)
        return page_results[0]

    if len(with_val) == 1:
        return with_val[0]

    # Compare values across distinct pages
    first_r = with_val[0]
    differing = []
    for other_r in with_val[1:]:
        if other_r.page != first_r.page and not values_are_equal(first_r.value, other_r.value, field_type):
            differing.append(other_r)

    if differing:
        # Cross-page conflict!
        pages_summary = [f"page {first_r.page + 1}: {first_r.value}"]
        for d in differing:
            pages_summary.append(f"page {d.page + 1}: {d.value}")
        reason_msg = "; ".join(pages_summary)

        return FieldResult(
            field=field_name,
            doc_type=first_r.doc_type,
            value=None,
            ocr_value=first_r.ocr_value,
            vlm_value=first_r.vlm_value,
            evidence_quote=first_r.evidence_quote,
            page=first_r.page,
            bbox=first_r.bbox,
            status=FieldStatus.conflict,
            reason=reason_msg,
            confidence=0.0,
            source_doc_id=first_r.source_doc_id,
        )

    # If all pages agree, return the highest confidence result
    return max(with_val, key=lambda r: r.confidence)
