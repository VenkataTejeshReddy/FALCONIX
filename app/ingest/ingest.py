"""Stage 1: Ingestion.

Responsibilities
  1. Validate the input (type, size, magic bytes, corruption).
  2. Hash it (SHA-256) and store the ORIGINAL untouched and read-only.
  3. Render to page images (PDF -> PNG, image -> EXIF-corrected PNG).
  4. Quality gate: blur / brightness / contrast / resolution. Never guess on bad input.
  5. Gentle preprocessing (deskew, CLAHE, light denoise). No binarization.

The original file is never modified or replaced. Derived images live elsewhere.
"""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field, asdict
from pathlib import Path

import cv2
import pymupdf as fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageOps

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
MAX_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 20
PDF_DPI = 200

# Quality thresholds (tune on your own samples)
MIN_SHORT_SIDE = 700        # px
BLUR_POOR = 40.0            # Laplacian variance below this -> poor
BLUR_WARN = 100.0
DARK_P98_MAX = 90           # even the brightest pixels are dark -> underexposed
WASHED_P2_MIN = 150         # even the darkest pixels are light -> washed out / no ink
CONTRAST_MIN = 60.0         # p98 - p2 intensity range (robust for sparse text on white)

MAGIC = {
    b"%PDF": {".pdf"},
    b"\xff\xd8\xff": {".jpg", ".jpeg"},
    b"\x89PNG": {".png"},
    b"RIFF": {".webp"},
}


class IngestError(Exception):
    """Raised for invalid input. Message is safe to show to the user."""


@dataclass
class QualityReport:
    page: int
    width: int
    height: int
    blur_score: float
    brightness: float
    contrast: float
    issues: list[str] = field(default_factory=list)
    verdict: str = "ok"  # ok | warn | poor


@dataclass
class IngestResult:
    sha256: str
    original_path: str
    extension: str
    duplicate: bool
    page_paths: list[str]            # preprocessed images, one per page
    raw_page_paths: list[str]        # rendered but not preprocessed
    pdf_has_text_layer: bool
    quality: list[QualityReport]
    overall_quality: str             # ok | warn | poor
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- validation
def _sniff_ext(head: bytes) -> set[str] | None:
    for magic, exts in MAGIC.items():
        if head.startswith(magic):
            if magic == b"RIFF" and head[8:12] != b"WEBP":
                return None
            return exts
    return None


def validate_file(path: Path) -> bytes:
    """Return file bytes or raise IngestError."""
    if not path.exists() or not path.is_file():
        raise IngestError("File not found.")
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXT:
        raise IngestError(f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXT)}")
    data = path.read_bytes()
    if len(data) == 0:
        raise IngestError("File is empty.")
    if len(data) > MAX_BYTES:
        raise IngestError(f"File too large ({len(data)/1e6:.1f} MB, limit {MAX_BYTES/1e6:.0f} MB).")
    sniffed = _sniff_ext(data[:16])
    if sniffed is None or ext not in sniffed:
        raise IngestError("File content does not match its extension (possibly renamed or corrupt).")
    return data


# ------------------------------------------------------------------- storage
def store_original(data: bytes, ext: str, originals_dir: Path) -> tuple[str, Path, bool]:
    """Store under <sha256><ext>, read-only. Returns (sha, path, is_duplicate)."""
    sha = hashlib.sha256(data).hexdigest()
    originals_dir.mkdir(parents=True, exist_ok=True)
    dest = originals_dir / f"{sha}{ext}"
    if dest.exists():
        return sha, dest, True
    dest.write_bytes(data)
    os.chmod(dest, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # 0o444
    return sha, dest, False


# ----------------------------------------------------------------- rendering
def _render_pdf(path: Path) -> tuple[list[np.ndarray], bool]:
    try:
        doc = fitz.open(path)
    except Exception as e:  # corrupt PDF
        raise IngestError(f"PDF could not be opened: {e}")
    if doc.needs_pass:
        raise IngestError("PDF is password protected.")
    if doc.page_count == 0:
        raise IngestError("PDF has no pages.")
    if doc.page_count > MAX_PDF_PAGES:
        raise IngestError(f"PDF has {doc.page_count} pages (limit {MAX_PDF_PAGES}).")
    has_text = False
    pages = []
    zoom = PDF_DPI / 72
    for page in doc:
        if page.get_text("text").strip():
            has_text = True
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        pages.append(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
    return pages, has_text


def _load_image(path: Path) -> np.ndarray:
    try:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)  # fix phone rotation
        img = img.convert("RGB")
    except Exception as e:
        raise IngestError(f"Image could not be decoded: {e}")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


# ------------------------------------------------------------- quality gate
def assess_quality(img: np.ndarray, page: int = 1) -> QualityReport:
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Normalise size so blur score is comparable across resolutions
    scale = 1200 / max(h, w)
    g = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    blur = float(cv2.Laplacian(g, cv2.CV_64F).var())
    bright = float(gray.mean())
    p2, p98 = np.percentile(gray, [2, 98])
    contrast = float(p98 - p2)

    issues: list[str] = []
    verdict = "ok"

    def bump(level: str):
        nonlocal verdict
        order = {"ok": 0, "warn": 1, "poor": 2}
        if order[level] > order[verdict]:
            verdict = level

    if min(h, w) < MIN_SHORT_SIDE:
        issues.append(f"low resolution ({w}x{h})"); bump("poor")
    if blur < BLUR_POOR:
        issues.append(f"image is blurry (score {blur:.0f})"); bump("poor")
    elif blur < BLUR_WARN:
        issues.append(f"image is slightly soft (score {blur:.0f})"); bump("warn")
    if p98 < DARK_P98_MAX:
        issues.append(f"too dark (brightest pixels at {p98:.0f}/255)"); bump("poor")
    elif p2 > WASHED_P2_MIN:
        issues.append(f"washed out, no dark content (darkest pixels at {p2:.0f}/255)"); bump("warn")
    if contrast < CONTRAST_MIN:
        issues.append(f"very low contrast (range {contrast:.0f})"); bump("poor")

    return QualityReport(page, w, h, round(blur, 1), round(bright, 1), round(contrast, 1), issues, verdict)


# ------------------------------------------------------------ preprocessing
def estimate_skew(img: np.ndarray, max_angle: float = 10.0, step: float = 0.5) -> float:
    """Projection-profile search: the angle that maximises row-sum variance."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    scale = 600 / max(gray.shape)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    binary = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    h, w = binary.shape
    center = (w / 2, h / 2)
    best_angle, best_score = 0.0, -1.0
    for a in np.arange(-max_angle, max_angle + step, step):
        M = cv2.getRotationMatrix2D(center, float(a), 1.0)
        rot = cv2.warpAffine(binary, M, (w, h), flags=cv2.INTER_NEAREST)
        score = float(np.var(rot.sum(axis=1)))
        if score > best_score:
            best_angle, best_score = float(a), score
    return best_angle


def preprocess(img: np.ndarray) -> tuple[np.ndarray, list[str]]:
    notes: list[str] = []
    out = img
    angle = estimate_skew(out)
    if abs(angle) >= 0.5:
        h, w = out.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        out = cv2.warpAffine(out, M, (w, h), flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_REPLICATE)
        notes.append(f"deskewed by {angle:+.1f} deg")
    # CLAHE on lightness only (keeps colour and decorative fonts intact)
    lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
    l, a_, b_ = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    out = cv2.cvtColor(cv2.merge((l, a_, b_)), cv2.COLOR_LAB2BGR)
    out = cv2.fastNlMeansDenoisingColored(out, None, 3, 3, 7, 21)  # deliberately mild
    notes.append("CLAHE + light denoise applied")
    return out, notes


# --------------------------------------------------------------- public API
def ingest(path: str | Path, data_dir: str | Path = "data") -> IngestResult:
    path, data_dir = Path(path), Path(data_dir)
    data = validate_file(path)
    ext = path.suffix.lower()
    sha, stored, duplicate = store_original(data, ext, data_dir / "originals")

    if ext == ".pdf":
        raw_pages, has_text = _render_pdf(stored)
    else:
        raw_pages, has_text = [_load_image(stored)], False

    derived = data_dir / "derived" / sha
    derived.mkdir(parents=True, exist_ok=True)

    raw_paths, proc_paths, reports, notes = [], [], [], []
    if duplicate:
        notes.append("Duplicate: identical file (same SHA-256) was ingested before.")

    for i, img in enumerate(raw_pages, start=1):
        rp = derived / f"page{i}_raw.png"
        cv2.imwrite(str(rp), img)
        raw_paths.append(str(rp))

        report = assess_quality(img, i)
        reports.append(report)

        proc, pn = preprocess(img)
        pp = derived / f"page{i}_clean.png"
        cv2.imwrite(str(pp), proc)
        proc_paths.append(str(pp))
        notes.extend(f"page {i}: {n}" for n in pn)

    order = {"ok": 0, "warn": 1, "poor": 2}
    overall = max((r.verdict for r in reports), key=lambda v: order[v])

    return IngestResult(
        sha256=sha, original_path=str(stored), extension=ext, duplicate=duplicate,
        page_paths=proc_paths, raw_page_paths=raw_paths, pdf_has_text_layer=has_text,
        quality=reports, overall_quality=overall, notes=notes,
    )