# Owner: Laptop A
"""INX – Apple Vision OCR reader (macOS only).

Uses ``ocrmac`` to call Apple's native Vision framework for high-accuracy OCR on
Apple Silicon (macOS 12+).

Coordinate contract:
Every bounding box is in pixel coordinates of the page image produced by ingest
(page{N}_clean.png), 0-based page indexing, top-left origin, clamped to image bounds.
Image width and height are recorded in ParsedDocument.meta["page_dimensions"].

Reader name: ``"apple_ocr"``
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


def vision_to_pixel_bbox(
    box: tuple[float, float, float, float],
    width: int,
    height: int,
) -> BBox:
    """Convert Vision normalized bottom-left box (x, y, w, h) to clamped pixel top-left BBox."""
    x, y, w, h = box

    # Vision coordinates: (x, y) is bottom-left, w is width, h is height (all in 0..1)
    # Top-left pixel space:
    x0 = x * float(width)
    y0 = (1.0 - y - h) * float(height)
    x1 = (x + w) * float(width)
    y1 = (1.0 - y) * float(height)

    # Clamping
    x0_clamped = max(0.0, min(float(width), x0))
    y0_clamped = max(0.0, min(float(height), y0))
    x1_clamped = max(x0_clamped, min(float(width), x1))
    y1_clamped = max(y0_clamped, min(float(height), y1))

    return BBox(x0=x0_clamped, y0=y0_clamped, x1=x1_clamped, y1=y1_clamped)


def preprocess_image_for_ocr(img_path: Path) -> tuple[Path, bool]:
    """Lightweight preprocessing to aid Apple OCR on hard/small scans.

    Applies shadow removal, bilateral denoising, CLAHE local contrast, and upscaling.
    Returns (processed_path, is_temporary).
    Does NOT modify the original file or the clean page used for coordinates.
    """
    try:
        img = cv2.imread(str(img_path))
        if img is None:
            return img_path, False

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 1. Shadow removal / illumination normalization via background subtraction
        dilated = cv2.dilate(gray, np.ones((7, 7), np.uint8))
        bg = cv2.medianBlur(dilated, 25)
        diff = 255 - cv2.absdiff(gray, bg)
        norm = cv2.normalize(diff, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX)

        # 2. Bilateral filtering for grain suppression while preserving edges
        denoised = cv2.bilateralFilter(norm, 9, 75, 75)

        # 3. CLAHE local contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)

        # 4. Upscale small text if resolution is modest
        if max(h, w) < 1600:
            scale = min(2.5, 1600.0 / max(h, w))
            enhanced = cv2.resize(enhanced, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        cv2.imwrite(tmp.name, enhanced)
        return Path(tmp.name), True
    except Exception as exc:
        logger.debug("preprocess_image_for_ocr skipped: %s", exc)
        return img_path, False



class AppleOCRReader:
    """Apple Vision OCR reader – implements the :class:`Reader` protocol."""

    name: str = "apple_ocr"

    def __init__(
        self,
        language_correction: bool = True,
        recognition_level: str = "accurate",
        languages: Optional[list[str]] = None,
    ) -> None:
        self._language_correction = language_correction
        self._recognition_level = recognition_level
        self._languages = languages or ["en-US"]

    def read(
        self,
        page_image_paths: list[Path],
        doc_meta: DocumentRecord,
    ) -> ParsedDocument:
        """Run Apple Vision OCR over each page image."""
        try:
            from ocrmac.ocrmac import OCR
        except ImportError as err:
            raise ImportError(
                "ocrmac is required for AppleOCRReader on macOS: pip install ocrmac"
            ) from err

        all_lines: list[ParsedLine] = []
        text_by_page: dict[int, str] = {}
        page_dims: list[dict[str, Any]] = []

        for page_idx, img_path in enumerate(page_image_paths):
            t0 = time.perf_counter()
            img_path = Path(img_path)
            if not img_path.exists():
                logger.warning("Page image not found: %s", img_path)
                continue

            with Image.open(img_path) as pil_img:
                width, height = pil_img.size

            page_dims.append({"page": page_idx, "width": width, "height": height})

            # Check if image benefits from enhanced contrast/resolution for Vision
            ocr_path, is_temp = preprocess_image_for_ocr(img_path)

            try:
                ocr = OCR(
                    str(ocr_path),
                    recognition_level=self._recognition_level,
                    language_preference=self._languages,
                )
                raw_results = ocr.recognize(px=False)
            finally:
                if is_temp and ocr_path.exists():
                    ocr_path.unlink(missing_ok=True)

            page_lines: list[ParsedLine] = []
            for text, conf, box in raw_results:
                clean_text = text.strip()
                if not clean_text:
                    continue

                bbox_obj = vision_to_pixel_bbox(box, width, height)
                parsed_line = ParsedLine(
                    text=clean_text,
                    page=page_idx,
                    bbox=bbox_obj,
                    conf=float(conf),
                )
                page_lines.append(parsed_line)

            # Sort page lines top-to-bottom
            page_lines.sort(key=lambda l: (l.bbox.y0 if l.bbox else 0.0, l.bbox.x0 if l.bbox else 0.0))
            all_lines.extend(page_lines)
            text_by_page[page_idx] = "\n".join(l.text for l in page_lines)

            elapsed = time.perf_counter() - t0
            logger.debug(
                "AppleOCR page %d (%dx%d): %d lines in %.2fs",
                page_idx,
                width,
                height,
                len(page_lines),
                elapsed,
            )

        meta: dict[str, Any] = {
            "reader": self.name,
            "recognition_level": self._recognition_level,
            "page_dimensions": page_dims,
            "line_engines": ["apple_ocr"] * len(all_lines),
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


assert isinstance(AppleOCRReader(), Reader), "AppleOCRReader does not satisfy Reader protocol"
