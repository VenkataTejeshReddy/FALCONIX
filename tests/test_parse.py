# Owner: Laptop A
"""INX – Tests: Parse layer (Reader A).

Tests:
1. Coordinate conversion from Vision normalized space to top-left pixel space.
2. Clamping of bounding boxes to image dimensions.
3. PDF text-layer coordinate scaling (72 DPI points to 200 DPI pixel space).
4. Line deduplication and overlap merging.
5. Reading order sorting with column handling.
6. Integration tests on Apple OCR, Docling, and CombinedReader (marked @pytest.mark.mac).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.parse.apple_ocr import AppleOCRReader, vision_to_pixel_bbox
from app.parse.combined_reader import (
    CombinedReader,
    bbox_iou,
    deduplicate_lines,
    sort_reading_order,
)
from app.parse.docling_reader import DoclingReader
from app.parse.pdf_text import extract_pdf_page_text_lines
from app.schemas import BBox, DocumentRecord, ParsedLine

is_mac = sys.platform == "darwin"


# ---------------------------------------------------------------------------
# Unit Tests (Cross-platform)
# ---------------------------------------------------------------------------


def test_vision_coordinate_conversion():
    """Verify Vision bottom-left normalized coordinates convert to top-left pixels."""
    # Box: x=0.1, y=0.2, w=0.3, h=0.4 on 1000x2000 image
    # Vision: (0.1, 0.2) is bottom-left, top is y + h = 0.6
    # Top-left pixel y0 = (1.0 - 0.6) * 2000 = 800
    # Top-left pixel y1 = (1.0 - 0.2) * 2000 = 1600
    # Top-left pixel x0 = 0.1 * 1000 = 100
    # Top-left pixel x1 = (0.1 + 0.3) * 1000 = 400
    vision_box = (0.1, 0.2, 0.3, 0.4)
    bbox = vision_to_pixel_bbox(vision_box, width=1000, height=2000)

    assert pytest.approx(bbox.x0, 0.01) == 100.0
    assert pytest.approx(bbox.y0, 0.01) == 800.0
    assert pytest.approx(bbox.x1, 0.01) == 400.0
    assert pytest.approx(bbox.y1, 0.01) == 1600.0


def test_bbox_clamping():
    """Verify coordinates outside [0, width] x [0, height] are clamped."""
    # Negative x, exceeding width
    vision_box = (-0.1, -0.2, 1.4, 1.5)
    bbox = vision_to_pixel_bbox(vision_box, width=500, height=800)

    assert bbox.x0 >= 0.0
    assert bbox.y0 >= 0.0
    assert bbox.x1 <= 500.0
    assert bbox.y1 <= 800.0


def test_bbox_iou():
    """Verify bounding box IoU calculation."""
    b1 = BBox(x0=0, y0=0, x1=10, y1=10)
    b2 = BBox(x0=0, y0=0, x1=10, y1=10)
    assert pytest.approx(bbox_iou(b1, b2)) == 1.0

    b3 = BBox(x0=5, y0=0, x1=15, y1=10)
    # Inter: 5x10=50, union: 100 + 100 - 50 = 150 -> 50/150 = 1/3
    assert pytest.approx(bbox_iou(b1, b3), 0.01) == 1.0 / 3.0

    b4 = BBox(x0=20, y0=20, x1=30, y1=30)
    assert bbox_iou(b1, b4) == 0.0


def test_line_deduplication():
    """Verify overlapping lines are merged, keeping higher priority/confidence."""
    line_a = ParsedLine(
        text="Applicant Name",
        page=0,
        bbox=BBox(x0=50, y0=100, x1=200, y1=130),
        conf=0.75,
    )
    line_b = ParsedLine(
        text="Applicant Name",
        page=0,
        bbox=BBox(x0=51, y0=101, x1=201, y1=131),
        conf=0.99,
    )
    distinct_line = ParsedLine(
        text="Phone Number",
        page=0,
        bbox=BBox(x0=50, y0=200, x1=200, y1=230),
        conf=0.90,
    )

    items = [(line_a, "rapid_ocr"), (line_b, "apple_ocr"), (distinct_line, "apple_ocr")]
    deduped = deduplicate_lines(items, iou_threshold=0.5)

    assert len(deduped) == 2
    kept_texts = [l.text for l, _ in deduped]
    assert "Applicant Name" in kept_texts
    assert "Phone Number" in kept_texts
    # Higher engine / conf kept
    app_line, eng = [item for item in deduped if item[0].text == "Applicant Name"][0]
    assert eng == "apple_ocr"
    assert app_line.conf == 0.99


def test_sort_reading_order_two_columns():
    """Verify reading order detects 2-column layout and sorts col 0 before col 1."""
    # Page width 1000. Left column x in [50..400], Right column x in [550..900]
    left_top = (ParsedLine(text="Left Top", page=0, bbox=BBox(x0=50, y0=100, x1=300, y1=120)), "ocr")
    left_bot = (ParsedLine(text="Left Bot", page=0, bbox=BBox(x0=50, y0=200, x1=300, y1=220)), "ocr")
    left_mid = (ParsedLine(text="Left Mid", page=0, bbox=BBox(x0=50, y0=150, x1=300, y1=170)), "ocr")

    right_top = (ParsedLine(text="Right Top", page=0, bbox=BBox(x0=600, y0=100, x1=850, y1=120)), "ocr")
    right_bot = (ParsedLine(text="Right Bot", page=0, bbox=BBox(x0=600, y0=200, x1=850, y1=220)), "ocr")
    right_mid = (ParsedLine(text="Right Mid", page=0, bbox=BBox(x0=600, y0=150, x1=850, y1=170)), "ocr")

    items = [right_bot, left_bot, right_top, left_top, left_mid, right_mid]
    ordered = sort_reading_order(items, page_width=1000.0)

    ordered_texts = [l.text for l, _ in ordered]
    assert ordered_texts == [
        "Left Top",
        "Left Mid",
        "Left Bot",
        "Right Top",
        "Right Mid",
        "Right Bot",
    ]


def test_text_layer_scaling(tmp_path: Path):
    """Verify PDF native text layer extraction and point-to-pixel scaling (200/72)."""
    import pymupdf

    pdf_path = tmp_path / "test_scaled.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)  # 8.5x11 inches in points
    # Insert text at (72, 72) pt
    page.insert_text((72, 72), "Scaling Verification Test", fontsize=12)
    doc.save(str(pdf_path))
    doc.close()

    # Target 200 DPI image size: 612 * (200/72) = 1700, 792 * (200/72) = 2200
    target_w = round(612 * (200.0 / 72.0))
    target_h = round(792 * (200.0 / 72.0))

    lines = extract_pdf_page_text_lines(
        pdf_path=pdf_path,
        page_idx=0,
        page_width=target_w,
        page_height=target_h,
        dpi=200,
    )

    assert len(lines) >= 1
    line = lines[0]
    assert "Scaling Verification Test" in line.text
    assert line.conf == 1.0
    assert line.bbox is not None
    # 72 points * (200/72) = 200.0 pixels
    assert pytest.approx(line.bbox.x0, 2.0) == 200.0
    assert line.bbox.x1 <= target_w
    assert line.bbox.y1 <= target_h


# ---------------------------------------------------------------------------
# Integration Tests (macOS only)
# ---------------------------------------------------------------------------


@pytest.mark.mac
@pytest.mark.skipif(not is_mac, reason="macOS Vision OCR is only supported on Apple Silicon / macOS")
def test_apple_ocr_reader_integration(tmp_path: Path):
    """Run AppleOCRReader on a generated test image."""
    img = Image.new("RGB", (600, 150), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((30, 45), "Priya Sharma 2021001", fill="black")

    img_path = tmp_path / "test_apple_ocr.png"
    img.save(img_path)

    reader = AppleOCRReader()
    meta = DocumentRecord(
        doc_id="test-doc-apple",
        filename="test_apple_ocr.png",
        sha256="fake_sha",
        storage_path=str(img_path),
        pages=1,
    )
    parsed = reader.read([img_path], meta)

    assert parsed.reader_name == "apple_ocr"
    assert parsed.pages == 1
    assert any("Priya Sharma" in l.text for l in parsed.lines)
    assert any("2021001" in l.text for l in parsed.lines)
    assert len(parsed.meta.get("page_dimensions", [])) == 1


@pytest.mark.mac
@pytest.mark.skipif(not is_mac, reason="CombinedReader uses Apple Vision OCR on macOS")
def test_combined_reader_integration(tmp_path: Path):
    """Run CombinedReader on clean synthetic test image and verify no exceptions."""
    img = Image.new("RGB", (700, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 50), "Official Document Record\nApplicant: Vikramaditya Rao", fill="black")

    img_path = tmp_path / "test_combined.png"
    img.save(img_path)

    reader = CombinedReader()
    meta = DocumentRecord(
        doc_id="test-combined-1",
        filename="test_combined.png",
        sha256="combined_sha",
        storage_path=str(img_path),
        pages=1,
    )
    try:
        parsed = reader.read([img_path], meta)
        assert parsed.reader_name == "combined"
        assert len(parsed.lines) >= 1
        assert parsed.text_by_page[0]
        assert "Vikramaditya" in parsed.full_text or "Official" in parsed.full_text
        assert "line_engines" in parsed.meta
    finally:
        reader.unload()


@pytest.mark.mac
@pytest.mark.skipif(not is_mac, reason="Docling is part of Laptop A model stack")
def test_docling_reader_integration(tmp_path: Path):
    """Verify DoclingReader processes a simple document and unloads cleanly."""
    import pymupdf

    pdf_path = tmp_path / "docling_sample.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Docling Verification Header", fontsize=14)
    doc.save(str(pdf_path))
    doc.close()

    # Generate page image simulating ingest output
    img_path = tmp_path / "page0_clean.png"
    img = Image.new("RGB", (600, 300), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((30, 30), "Docling Verification Header", fill="black")
    img.save(img_path)

    reader = DoclingReader()
    meta = DocumentRecord(
        doc_id="docling-1",
        filename="docling_sample.pdf",
        sha256="docling_sha",
        storage_path=str(pdf_path),
        pages=1,
    )
    try:
        parsed = reader.read([img_path], meta)
        assert parsed.reader_name == "docling"
        assert "tables" in parsed.meta
    finally:
        reader.unload()

