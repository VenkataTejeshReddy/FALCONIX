# Owner: Laptop A
"""INX – Combined Reader: the primary Reader used by the INX pipeline on Laptop A.

Integrates:
1. Native PDF text layer extraction (via PyMuPDF) when pdf_has_text_layer is True.
2. Apple Vision OCR (via ocrmac) for scanned documents or pages lacking a text layer.
3. RapidOCR fallback if Apple OCR returns zero lines or raises an error.
4. Docling for table structure extraction (Markdown and row matrices).
5. Overlapping line deduplication and reading order with column-aware sorting.
6. Non-raising error handling: on any failure, returns a ParsedDocument with meta["error"].
7. Unload support and latency logging per page.

Reader name: ``"combined"``
"""

from __future__ import annotations

import gc
import logging
import time
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from app.parse.apple_ocr import AppleOCRReader
from app.parse.base import Reader
from app.parse.docling_reader import DoclingReader
from app.parse.pdf_text import extract_pdf_page_text_lines
from app.parse.rapid_ocr_fallback import RapidOCRReader
from app.schemas import BBox, DocumentRecord, ParsedDocument, ParsedLine

logger = logging.getLogger(__name__)


def bbox_iou(b1: BBox, b2: BBox) -> float:
    """Compute Intersection-over-Union between two bounding boxes."""
    inter_x0 = max(b1.x0, b2.x0)
    inter_y0 = max(b1.y0, b2.y0)
    inter_x1 = min(b1.x1, b2.x1)
    inter_y1 = min(b1.y1, b2.y1)

    inter_w = max(0.0, inter_x1 - inter_x0)
    inter_h = max(0.0, inter_y1 - inter_y0)
    inter_area = inter_w * inter_h

    union_area = b1.area + b2.area - inter_area
    if union_area <= 0.0:
        return 0.0
    return inter_area / union_area


def deduplicate_lines(
    lines: list[tuple[ParsedLine, str]],
    iou_threshold: float = 0.5,
) -> list[tuple[ParsedLine, str]]:
    """Drop duplicate or heavily overlapping lines on the same page.

    Args:
        lines: List of tuples (ParsedLine, engine_name).

    Returns:
        Deduplicated list preserving highest-confidence instances.
    """
    if not lines:
        return []

    # Engine priority rank: pdf_text > apple_ocr > rapid_ocr
    engine_rank = {"pdf_text": 3, "apple_ocr": 2, "rapid_ocr": 1}

    kept: list[tuple[ParsedLine, str]] = []
    for line, eng in lines:
        if not line.bbox:
            kept.append((line, eng))
            continue

        duplicate = False
        for idx, (existing_line, existing_eng) in enumerate(kept):
            if not existing_line.bbox:
                continue

            iou = bbox_iou(line.bbox, existing_line.bbox)
            exact_match = line.text.strip().lower() == existing_line.text.strip().lower()

            if iou >= iou_threshold or (exact_match and iou > 0.2):
                duplicate = True
                # If new line has higher engine rank or higher conf, replace existing
                rank_new = engine_rank.get(eng, 0)
                rank_old = engine_rank.get(existing_eng, 0)
                conf_new = line.conf if line.conf is not None else 0.0
                conf_old = existing_line.conf if existing_line.conf is not None else 0.0

                if (rank_new, conf_new) > (rank_old, conf_old):
                    kept[idx] = (line, eng)
                break

        if not duplicate:
            kept.append((line, eng))

    return kept


def sort_reading_order(
    lines_with_engine: list[tuple[ParsedLine, str]],
    page_width: float,
) -> list[tuple[ParsedLine, str]]:
    """Sort lines in top-to-bottom, left-to-right reading order with 2-column detection."""
    if len(lines_with_engine) <= 1 or page_width <= 0:
        return lines_with_engine

    mid = page_width * 0.5
    left_col_count = 0
    right_col_count = 0
    spanning_count = 0

    for line, _ in lines_with_engine:
        if not line.bbox:
            continue
        if line.bbox.x1 < mid * 1.05 and line.bbox.x0 < mid * 0.95:
            left_col_count += 1
        elif line.bbox.x0 > mid * 0.95 and line.bbox.x1 > mid * 1.05:
            right_col_count += 1
        else:
            spanning_count += 1

    is_two_column = (left_col_count >= 3 and right_col_count >= 3 and (left_col_count + right_col_count) > spanning_count * 2)

    def sort_key(item: tuple[ParsedLine, str]) -> tuple[int, float, float]:
        line, _ = item
        if not line.bbox:
            return (0, 0.0, 0.0)

        y = line.bbox.y0
        x = line.bbox.x0

        if not is_two_column:
            # Single column: group by horizontal bands (~10px) then left-to-right
            band = round(y / 10.0) * 10.0
            return (0, band, x)

        # Two-column: spanning lines (headers) first, then col 0, then col 1
        if line.bbox.x0 < mid * 0.85 and line.bbox.x1 > mid * 1.15:
            return (0, y, x)
        elif (line.bbox.x0 + line.bbox.x1) / 2.0 < mid:
            return (1, y, x)
        else:
            return (2, y, x)

    return sorted(lines_with_engine, key=sort_key)


class CombinedReader:
    """The primary INX parse-layer reader.

    Combines native PDF text layers, Apple Vision OCR, RapidOCR fallback, and
    Docling tables into a unified ParsedDocument.
    """

    name: str = "combined"

    def __init__(self) -> None:
        self._apple_ocr = AppleOCRReader()
        self._rapid_ocr = RapidOCRReader()
        self._docling = DoclingReader()

    def unload(self) -> None:
        """Unload models and release memory."""
        self._docling.unload()
        self._rapid_ocr.unload()
        gc.collect()

    def read(
        self,
        page_image_paths: list[Path],
        doc_meta: DocumentRecord,
    ) -> ParsedDocument:
        """Parse document pages into a structured ParsedDocument.

        Guaranteed NEVER to raise: returns a ParsedDocument with meta["error"] on failure.
        """
        try:
            return self._read_internal(page_image_paths, doc_meta)
        except Exception as exc:
            logger.error("CombinedReader failed on doc %s: %s", doc_meta.filename, exc, exc_info=True)
            return ParsedDocument(
                doc_id=doc_meta.doc_id,
                sha256=doc_meta.sha256,
                pages=len(page_image_paths) if page_image_paths else 1,
                lines=[],
                tables=[],
                text_by_page={0: ""},
                reader_name=self.name,
                meta={"error": f"{type(exc).__name__}: {exc}"},
            )

    def _read_internal(
        self,
        page_image_paths: list[Path],
        doc_meta: DocumentRecord,
    ) -> ParsedDocument:
        page_image_paths = [Path(p) for p in page_image_paths]
        total_pages = len(page_image_paths) if page_image_paths else 1

        all_lines: list[ParsedLine] = []
        line_engines: list[str] = []
        text_by_page: dict[int, str] = {}
        page_dimensions: list[dict[str, Any]] = []

        is_pdf = doc_meta.filename.lower().endswith(".pdf") or (
            doc_meta.storage_path and doc_meta.storage_path.lower().endswith(".pdf")
        )
        pdf_path = Path(doc_meta.storage_path) if doc_meta.storage_path else None
        has_text_layer = getattr(doc_meta, "pdf_has_text_layer", False)

        for p_idx, img_path in enumerate(page_image_paths):
            t_page_start = time.perf_counter()
            width, height = 800, 1000

            if img_path.exists():
                with Image.open(img_path) as pil_img:
                    width, height = pil_img.size

            page_dimensions.append({"page": p_idx, "width": width, "height": height})

            page_raw_lines: list[tuple[ParsedLine, str]] = []

            # 1. Try native PDF text layer if available
            if is_pdf and has_text_layer and pdf_path and pdf_path.exists():
                pdf_lines = extract_pdf_page_text_lines(
                    pdf_path=pdf_path,
                    page_idx=p_idx,
                    page_width=width,
                    page_height=height,
                    dpi=200,
                )
                if pdf_lines:
                    for l in pdf_lines:
                        page_raw_lines.append((l, "pdf_text"))

            # 2. If no lines from PDF text layer, run Apple Vision OCR
            if not page_raw_lines:
                try:
                    ocr_doc = self._apple_ocr.read([img_path], doc_meta)
                    for l in ocr_doc.lines:
                        # Re-tag page index
                        l.page = p_idx
                        page_raw_lines.append((l, "apple_ocr"))
                except Exception as ocr_err:
                    logger.warning("Apple Vision OCR failed on page %d: %s", p_idx, ocr_err)

            # 3. If Apple OCR returned nothing or failed, use RapidOCR fallback
            if not page_raw_lines:
                try:
                    rapid_doc = self._rapid_ocr.read([img_path], doc_meta)
                    for l in rapid_doc.lines:
                        l.page = p_idx
                        page_raw_lines.append((l, "rapid_ocr"))
                except Exception as rapid_err:
                    logger.warning("RapidOCR fallback failed on page %d: %s", p_idx, rapid_err)

            # 4. Deduplicate overlapping lines and sort reading order
            deduped = deduplicate_lines(page_raw_lines, iou_threshold=0.5)
            ordered = sort_reading_order(deduped, page_width=float(width))

            # Store page results
            final_page_lines = [item[0] for item in ordered]
            final_page_engines = [item[1] for item in ordered]

            all_lines.extend(final_page_lines)
            line_engines.extend(final_page_engines)
            text_by_page[p_idx] = "\n".join(l.text for l in final_page_lines)

            elapsed_page = time.perf_counter() - t_page_start
            primary_engine = final_page_engines[0] if final_page_engines else "none"
            logger.info(
                "CombinedReader page %d/%d (%dx%d) in %.2fs: %d lines (primary: %s)",
                p_idx + 1,
                total_pages,
                width,
                height,
                elapsed_page,
                len(final_page_lines),
                primary_engine,
            )

        # 5. Extract tables via Docling
        tables: list[list[list[str]]] = []
        tables_meta: list[dict[str, Any]] = []
        try:
            docling_doc = self._docling.read(page_image_paths, doc_meta)
            tables = docling_doc.tables
            tables_meta = docling_doc.meta.get("tables", [])
        except Exception as docling_err:
            logger.warning("Docling table extraction encountered an issue: %s", docling_err)

        meta: dict[str, Any] = {
            "reader": self.name,
            "page_dimensions": page_dimensions,
            "line_engines": line_engines,
            "tables": tables_meta,
            "total_lines": len(all_lines),
            "total_tables": len(tables),
        }

        return ParsedDocument(
            doc_id=doc_meta.doc_id,
            sha256=doc_meta.sha256,
            pages=total_pages,
            lines=all_lines,
            tables=tables,
            text_by_page=text_by_page,
            reader_name=self.name,
            meta=meta,
        )


assert isinstance(CombinedReader(), Reader), "CombinedReader does not satisfy Reader protocol"
