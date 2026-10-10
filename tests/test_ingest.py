import os
import stat

import cv2
import pymupdf as fitz
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.ingest.ingest import (IngestError, estimate_skew, ingest, assess_quality)


def make_doc_image(path, size=(1400, 1000), rotate=0.0, blur=0, dark=False):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    d.text((120, 100), "CERTIFICATE OF COMPLETION", fill="black", font=font)
    for i in range(10):
        d.text((120, 220 + i * 60), f"This is to certify that Priya Sharma, roll no 2021{i:04d}", fill="black", font=font)
    if rotate:
        img = img.rotate(rotate, expand=False, fillcolor="white")
    arr = np.array(img)
    if blur:
        arr = cv2.GaussianBlur(arr, (0, 0), blur)
    if dark:
        arr = (arr * 0.15).astype(np.uint8)
    Image.fromarray(arr).save(path)
    return path


def test_normal_image(tmp_path):
    p = make_doc_image(tmp_path / "ok.jpg")
    r = ingest(p, tmp_path / "data")
    assert r.overall_quality == "ok"
    assert len(r.page_paths) == 1 and os.path.exists(r.page_paths[0])


def test_original_is_untouched_and_readonly(tmp_path):
    p = make_doc_image(tmp_path / "ok.png")
    before = p.read_bytes()
    r = ingest(p, tmp_path / "data")
    assert open(r.original_path, "rb").read() == before
    mode = os.stat(r.original_path).st_mode
    assert not (mode & stat.S_IWUSR)


def test_blurry_flagged_poor(tmp_path):
    p = make_doc_image(tmp_path / "blur.jpg", blur=6)
    r = ingest(p, tmp_path / "data")
    assert r.overall_quality == "poor"
    assert any("blur" in i for i in r.quality[0].issues)


def test_dark_flagged(tmp_path):
    p = make_doc_image(tmp_path / "dark.png", dark=True)
    r = ingest(p, tmp_path / "data")
    assert r.overall_quality == "poor"


def test_low_resolution_flagged(tmp_path):
    p = make_doc_image(tmp_path / "small.png", size=(500, 350))
    r = ingest(p, tmp_path / "data")
    assert any("resolution" in i for i in r.quality[0].issues)


def test_skew_estimated_and_corrected(tmp_path):
    p = make_doc_image(tmp_path / "skew.png", rotate=4.0)
    img = cv2.imread(str(p))
    angle = estimate_skew(img)
    assert abs(abs(angle) - 4.0) <= 1.0
    r = ingest(p, tmp_path / "data")
    residual = estimate_skew(cv2.imread(r.page_paths[0]))
    assert abs(residual) <= 1.0


def test_duplicate_detected(tmp_path):
    p = make_doc_image(tmp_path / "a.png")
    first = ingest(p, tmp_path / "data")
    second = ingest(p, tmp_path / "data")
    assert not first.duplicate and second.duplicate
    assert first.sha256 == second.sha256


def test_pdf_pages_and_text_layer(tmp_path):
    pdf = fitz.open()
    for t in ("Page one", "Page two"):
        page = pdf.new_page()
        page.insert_text((72, 100), t, fontsize=20)
    path = tmp_path / "two.pdf"
    pdf.save(path)
    r = ingest(path, tmp_path / "data")
    assert len(r.page_paths) == 2
    assert r.pdf_has_text_layer is True


def test_invalid_extension(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("hello")
    with pytest.raises(IngestError):
        ingest(p, tmp_path / "data")


def test_empty_file(tmp_path):
    p = tmp_path / "e.pdf"
    p.write_bytes(b"")
    with pytest.raises(IngestError, match="empty"):
        ingest(p, tmp_path / "data")


def test_renamed_file_rejected(tmp_path):
    p = tmp_path / "fake.jpg"
    p.write_bytes(b"this is not a jpeg at all")
    with pytest.raises(IngestError, match="does not match"):
        ingest(p, tmp_path / "data")


def test_truncated_jpeg_rejected(tmp_path):
    good = make_doc_image(tmp_path / "g.jpg")
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(good.read_bytes()[:300])
    with pytest.raises(IngestError):
        ingest(bad, tmp_path / "data")