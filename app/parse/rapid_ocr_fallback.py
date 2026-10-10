# Owner: Laptop A
"""INX – RapidOCR fallback reader.

Used as a safety fallback if Apple Vision OCR returns zero lines or raises an exception.

Reader name: ``"rapid_ocr"``
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
from PIL import Image

from app.parse.base import Reader
from app.schemas import BBox, DocumentRecord, ParsedDocument, ParsedLine

logger = logging.getLogger(__name__)


class RapidOCRReader:
    """RapidOCR fallback reader – implements the :class:`Reader` protocol."""

    name: str = "rapid_ocr"

    def __init__(self) -> None:
        self._engine: Any = None

    def _get_engine(self) -> Any:
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def read(
        self,
        page_image_paths: list[Path],
        doc_meta: DocumentRecord,
    ) -> ParsedDocument:
        """Run RapidOCR on each page image."""
        engine = self._get_engine()
        all_lines: list[ParsedLine] = []
        text_by_page: dict[int, str] = {}
        page_dims: list[dict[str, Any]] = []

        for page_idx, img_path in enumerate(page_image_paths):
            t0 = time.perf_counter()
            img_path = Path(img_path)
            if not img_path.exists():
                continue

            with Image.open(img_path) as pil_img:
                width, height = pil_img.size

            page_dims.append({"page": page_idx, "width": width, "height": height})

            img_cv = cv2.imread(str(img_path))
            if img_cv is None:
                continue

            raw_results, _ = engine(img_cv)
            page_lines: list[ParsedLine] = []

            if raw_results:
                for item in raw_results:
                    # item: [dt_boxes, text, score]
                    box, text, score = item[0], item[1], float(item[2])
                    clean_text = str(text).strip()
                    if not clean_text:
                        continue

                    # box has 4 corner points [[x, y], ...]
                    x_coords = [float(pt[0]) for pt in box]
                    y_coords = [float(pt[1]) for pt in box]

                    x0 = max(0.0, min(float(width), min(x_coords)))
                    y0 = max(0.0, min(float(height), min(y_coords)))
                    x1 = max(x0, min(float(width), max(x_coords)))
                    y1 = max(y0, min(float(height), max(y_coords)))

                    bbox_obj = BBox(x0=x0, y0=y0, x1=x1, y1=y1)
                    page_lines.append(
                        ParsedLine(
                            text=clean_text,
                            page=page_idx,
                            bbox=bbox_obj,
                            conf=score,
                        )
                    )

            # Sort top to bottom
            page_lines.sort(key=lambda l: (l.bbox.y0 if l.bbox else 0.0, l.bbox.x0 if l.bbox else 0.0))
            all_lines.extend(page_lines)
            text_by_page[page_idx] = "\n".join(l.text for l in page_lines)
            elapsed = time.perf_counter() - t0
            logger.debug("RapidOCR page %d (%dx%d): %d lines in %.2fs", page_idx, width, height, len(page_lines), elapsed)

        meta: dict[str, Any] = {
            "reader": self.name,
            "page_dimensions": page_dims,
            "line_engines": ["rapid_ocr"] * len(all_lines),
        }

        return ParsedDocument(
            doc_id=doc_meta.doc_id,
            sha256=doc_meta.sha256,
            pages=len(page_image_paths) if page_image_paths else 1,
            lines=all_lines,
            tables=[],
            text_by_page=text_by_page,
            reader_name=self.name,
            meta=meta,
        )

    def unload(self) -> None:
        """Release underlying engine and free memory."""
        self._engine = None


assert isinstance(RapidOCRReader(), Reader), "RapidOCRReader does not satisfy Reader protocol"
