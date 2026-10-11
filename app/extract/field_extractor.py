# Owner: Laptop A
"""INX – Primary Extractor implementation for Laptop A.

Implements the Extractor protocol defined in app/extract/base.py.
Coordinates:
1. OCR locator (ocr_fields.py) – Reader A
2. VLM semantic extraction (vlm_reader.py) – Reader B
3. Targeted crop re-read for unclear/missing fields with OCR bboxes
4. Grounding and normalisation (grounding.py)
5. Reconciliation matrix (reconcile.py)
"""

from __future__ import annotations

import gc
import logging
from pathlib import Path
from typing import Any, Optional

from app.extract.base import Extractor
from app.extract.grounding import is_value_grounded, values_are_equal
from app.extract.ocr_fields import find_ocr_field, load_field_labels
from app.extract.reconcile import (
    reconcile_multi_page_results,
    reconcile_single_page_field,
)
from app.extract.vlm_reader import VLMReader
from app.schemas import (
    DocumentRecord,
    DocumentType,
    FieldResult,
    FieldStatus,
    ParsedDocument,
)

logger = logging.getLogger(__name__)


class FieldExtractor:
    """Full multimodal extractor implementing the Extractor protocol."""

    def __init__(
        self,
        vlm_reader: Optional[VLMReader] = None,
        field_labels_cfg: Optional[dict[str, Any]] = None,
    ) -> None:
        self._vlm = vlm_reader or VLMReader()
        self._field_labels = field_labels_cfg or load_field_labels()

    def unload(self) -> None:
        """Unload VLM and reclaim system memory."""
        self._vlm.unload()
        gc.collect()

    def extract(
        self,
        doc: DocumentRecord,
        parsed: ParsedDocument,
        doc_type: DocumentType,
        scenario: Any,
    ) -> list[FieldResult]:
        """Extract scenario fields from document pages using Reader A + Reader B."""
        # 1. Unload any classifier embeddings/rerankers to protect RAM
        try:
            import torch
            if hasattr(torch, "mps") and torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except Exception:
            pass

        # 2. Determine target fields for this document type from scenario
        doc_type_key = doc_type.value if isinstance(doc_type, DocumentType) else str(doc_type)

        target_fields: list[str] = []
        if hasattr(scenario, "documents") and doc_type_key in scenario.documents:
            doc_spec = scenario.documents[doc_type_key]
            target_fields = list(doc_spec.fields.keys())
        elif isinstance(scenario, dict) and "documents" in scenario:
            doc_spec = scenario["documents"].get(doc_type_key, {})
            target_fields = list(doc_spec.get("fields", {}).keys())

        if not target_fields:
            logger.debug("No target fields configured for doc_type %s in scenario", doc_type_key)
            return []

        # 3. Determine pages to inspect (up to long_doc_pages)
        max_pages = 3
        if hasattr(scenario, "thresholds") and hasattr(scenario.thresholds, "long_doc_pages"):
            max_pages = scenario.thresholds.long_doc_pages
        elif isinstance(scenario, dict) and "thresholds" in scenario:
            max_pages = scenario["thresholds"].get("long_doc_pages", 3)

        page_image_paths = [Path(p) for p in doc.page_images[:max_pages]]
        if not page_image_paths and doc.storage_path:
            p_storage = Path(doc.storage_path)
            if p_storage.exists():
                if p_storage.suffix.lower() == ".pdf":
                    try:
                        import pymupdf as fitz
                        pdf = fitz.open(str(p_storage))
                        cache_tmp = Path("data/cache/tmp")
                        cache_tmp.mkdir(parents=True, exist_ok=True)
                        for p_i in range(min(max_pages, len(pdf))):
                            pix = pdf[p_i].get_pixmap(dpi=150)
                            tmp_p = cache_tmp / f"rendered_{doc.sha256[:16]}_p{p_i}.png"
                            pix.save(str(tmp_p))
                            page_image_paths.append(tmp_p)
                        pdf.close()
                    except Exception as pdf_err:
                        logger.warning("Failed to render PDF %s: %s", p_storage, pdf_err)
                else:
                    page_image_paths = [p_storage]

        per_field_page_results: dict[str, list[FieldResult]] = {f: [] for f in target_fields}

        for p_idx, img_path in enumerate(page_image_paths):
            page_text = parsed.text_by_page.get(p_idx, "")

            # Query VLM for all fields on this page in one call
            vlm_res = self._vlm.extract_page_fields(
                page_image_path=img_path,
                field_names=target_fields,
                doc_type_name=doc_type_key,
            )
            vlm_fields = vlm_res.get("fields", {})

            for f_name in target_fields:
                f_cfg = self._field_labels.get(f_name, {})
                f_type = f_cfg.get("type", "text")

                # Step A: OCR Locator (Reader A)
                ocr_val, ocr_bbox, ocr_p = find_ocr_field(parsed, f_name, f_cfg)

                # Step B: VLM Reading (Reader B)
                vlm_f = vlm_fields.get(f_name, {})
                vlm_val = vlm_f.get("value")
                vlm_quote = vlm_f.get("evidence_quote")
                vlm_obscured = bool(vlm_f.get("obscured", False))

                # Step C: Reconcile single page
                rec_r = reconcile_single_page_field(
                    field_name=f_name,
                    doc_type=doc_type,
                    ocr_val=ocr_val,
                    ocr_bbox=ocr_bbox,
                    ocr_page=ocr_p,
                    vlm_val=vlm_val,
                    vlm_quote=vlm_quote,
                    vlm_obscured=vlm_obscured,
                    vlm_page=p_idx,
                    page_text=page_text,
                    field_type=f_type,
                    source_doc_id=doc.doc_id,
                )

                # Step D: Targeted Crop Re-read
                # For fields that are unclear or missing and for which the OCR locator has a bbox
                if rec_r.status in (FieldStatus.unclear, FieldStatus.missing) and ocr_bbox is not None and ocr_val:
                    reread_res = self._vlm.targeted_reread(img_path, f_name, ocr_bbox)
                    reread_val = reread_res.get("value")
                    reread_quote = reread_res.get("evidence_quote")
                    if reread_val and values_are_equal(reread_val, ocr_val, f_type):
                        rec_r.value = ocr_val
                        rec_r.vlm_value = reread_val
                        rec_r.evidence_quote = reread_quote or ocr_val
                        rec_r.status = FieldStatus.valid
                        rec_r.confidence = 0.90
                        rec_r.reason = "Agreed after targeted crop re-read"

                per_field_page_results[f_name].append(rec_r)

        # 4. Multi-page aggregation and conflict detection
        final_results: list[FieldResult] = []
        for f_name in target_fields:
            f_cfg = self._field_labels.get(f_name, {})
            f_type = f_cfg.get("type", "text")
            page_results = per_field_page_results[f_name]

            doc_field_res = reconcile_multi_page_results(
                field_name=f_name,
                page_results=page_results,
                field_type=f_type,
            )
            final_results.append(doc_field_res)

        return final_results


_check: Extractor = FieldExtractor()
