# Owner: Laptop A
"""INX – Direct PDF text layer extractor.

Reads selectable text from the original PDF using PyMuPDF and scales coordinates
from PDF points (72 DPI) to the 200-DPI pixel space used by the ingest clean page
images (scale factor = 200 / 72).

Lines produced here have conf=1.0 and engine="pdf_text".
"""

from __future__ import annotations

import logging
from pathlib import Path

import pymupdf

from app.schemas import BBox, ParsedLine

logger = logging.getLogger(__name__)


def extract_pdf_page_text_lines(
    pdf_path: Path,
    page_idx: int,
    page_width: int,
    page_height: int,
    dpi: int = 200,
) -> list[ParsedLine]:
    """Extract lines and scaled bounding boxes from a PDF page's native text layer.

    Args:
        pdf_path: Path to original PDF.
        page_idx: 0-based page index.
        page_width: Pixel width of the corresponding clean rendered page image.
        page_height: Pixel height of the corresponding clean rendered page image.
        dpi: Target image DPI (default 200 from ingest).

    Returns:
        List of :class:`ParsedLine` objects with conf=1.0, or empty list if no text layer.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return []

    try:
        doc = pymupdf.open(str(pdf_path))
        if page_idx < 0 or page_idx >= len(doc):
            doc.close()
            return []

        page = doc[page_idx]
        words = page.get_text("words")
        doc.close()

        if not words:
            return []

        # Group words by (block_no, line_no)
        lines_dict: dict[tuple[int, int], list[tuple[Any, ...]]] = {}
        for w in words:
            key = (int(w[5]), int(w[6]))
            lines_dict.setdefault(key, []).append(w)

        scale = float(dpi) / 72.0
        parsed_lines: list[ParsedLine] = []

        for _, line_words in lines_dict.items():
            text = " ".join(str(w[4]) for w in line_words).strip()
            if not text:
                continue

            x0 = min(float(w[0]) for w in line_words) * scale
            y0 = min(float(w[1]) for w in line_words) * scale
            x1 = max(float(w[2]) for w in line_words) * scale
            y1 = max(float(w[3]) for w in line_words) * scale

            # Clamping to clean page dimensions
            x0_clamped = max(0.0, min(float(page_width), x0))
            y0_clamped = max(0.0, min(float(page_height), y0))
            x1_clamped = max(x0_clamped, min(float(page_width), x1))
            y1_clamped = max(y0_clamped, min(float(page_height), y1))

            bbox = BBox(x0=x0_clamped, y0=y0_clamped, x1=x1_clamped, y1=y1_clamped)
            parsed_lines.append(
                ParsedLine(
                    text=text,
                    page=page_idx,
                    bbox=bbox,
                    conf=1.0,
                )
            )

        # Sort reading order (top-to-bottom, left-to-right)
        parsed_lines.sort(key=lambda l: (l.bbox.y0 if l.bbox else 0.0, l.bbox.x0 if l.bbox else 0.0))
        return parsed_lines
    except Exception as exc:
        logger.warning("PDF text layer extraction failed for %s page %d: %s", pdf_path, page_idx, exc)
        return []
