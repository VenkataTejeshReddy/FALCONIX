# Owner: Laptop A
"""INX – CLI Script: Parse documents, dump structured JSON, and generate overlay PNGs.

Usage::

    python scripts/dump_parse.py fixtures/synthetic_docs/college_normal_marksheet.pdf
    python scripts/dump_parse.py fixtures/synthetic_docs/ --out fixtures/

Outputs:
1. Console: prints extracted text, line counts, and Markdown tables.
2. JSON: saves serialised ParsedDocument (model_dump()) to fixtures/<stem>.json
   and fixtures/<sha256>.json in the format expected by MockReader.
3. Overlay PNG: draws bounding boxes on clean page images, coloured by engine:
   - Green: pdf_text
   - Blue:  apple_ocr
   - Orange: rapid_ocr
   - Magenta: docling table
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PIL import Image, ImageDraw, ImageFont

from app.ingest.ingest import ingest
from app.parse.combined_reader import CombinedReader
from app.schemas import DocumentRecord, ParsedDocument

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("dump_parse")

# Colors for bounding box overlays (RGBA / RGB)
ENGINE_COLORS = {
    "pdf_text": (0, 204, 0),       # Green
    "apple_ocr": (0, 102, 255),    # Blue
    "rapid_ocr": (255, 153, 0),    # Orange
    "docling": (255, 0, 255),      # Magenta
    "unknown": (128, 128, 128),    # Gray
}


def draw_overlay(
    clean_image_path: Path,
    parsed_doc: ParsedDocument,
    page_idx: int,
    out_overlay_path: Path,
) -> None:
    """Render bounding boxes coloured by engine onto a copy of the clean page image."""
    if not clean_image_path.exists():
        return

    with Image.open(clean_image_path) as img:
        overlay = img.convert("RGB")

    draw = ImageDraw.Draw(overlay)
    font_path = _REPO_ROOT / "DejaVuSans.ttf"
    try:
        font = ImageFont.truetype(str(font_path), 12) if font_path.exists() else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    line_engines = parsed_doc.meta.get("line_engines", [])

    # Draw lines
    line_idx = 0
    for l in parsed_doc.lines:
        if l.page == page_idx and l.bbox:
            eng = line_engines[line_idx] if line_idx < len(line_engines) else "unknown"
            color = ENGINE_COLORS.get(eng, ENGINE_COLORS["unknown"])
            draw.rectangle(
                [(l.bbox.x0, l.bbox.y0), (l.bbox.x1, l.bbox.y1)],
                outline=color,
                width=2,
            )
        line_idx += 1

    # Draw table bounding boxes
    for t_meta in parsed_doc.meta.get("tables", []):
        if t_meta.get("page") == page_idx and t_meta.get("bbox"):
            tb = t_meta["bbox"]
            color = ENGINE_COLORS["docling"]
            draw.rectangle([(tb[0], tb[1]), (tb[2], tb[3])], outline=color, width=3)
            draw.text((tb[0] + 4, tb[1] + 4), "TABLE [Docling]", fill=color, font=font)

    out_overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(out_overlay_path)
    logger.info("Saved overlay image: %s", out_overlay_path)


def process_file(
    file_path: Path,
    reader: CombinedReader,
    fixtures_dir: Path,
    overlay_dir: Path,
) -> ParsedDocument:
    """Ingest, parse, save JSON fixture, and create overlay PNG for a document."""
    logger.info("=== Processing %s ===", file_path.name)

    # 1. Ingest document to get clean page images & text layer status
    data_dir = _REPO_ROOT / "data"
    ingest_res = ingest(file_path, data_dir=data_dir)

    page_paths = [Path(p) for p in ingest_res.page_paths]

    doc_meta = DocumentRecord(
        filename=file_path.name,
        sha256=ingest_res.sha256,
        storage_path=str(ingest_res.original_path),
        pages=len(page_paths),
        page_images=[str(p) for p in page_paths],
        pdf_has_text_layer=ingest_res.pdf_has_text_layer,
    )

    # 2. Run CombinedReader
    parsed_doc = reader.read(page_paths, doc_meta)

    # 3. Print extracted content to console
    print(f"\n------------------------------------------------------------")
    print(f"DOCUMENT: {file_path.name} (SHA: {parsed_doc.sha256[:12]}..., Pages: {parsed_doc.pages})")
    print(f"Lines Extracted: {len(parsed_doc.lines)}, Tables: {len(parsed_doc.tables)}")
    print(f"------------------------------------------------------------")
    for p_idx in range(parsed_doc.pages):
        text_snippet = parsed_doc.text_by_page.get(p_idx, "").strip()
        print(f"[Page {p_idx + 1} Text]:")
        print(text_snippet[:500] + ("..." if len(text_snippet) > 500 else ""))
        print()

    if parsed_doc.tables:
        print("[Extracted Tables (Docling)]:")
        for t_meta in parsed_doc.meta.get("tables", []):
            print(f"Table on page {t_meta.get('page', 0) + 1}:")
            print(t_meta.get("markdown", ""))
            print()

    # 4. Save parsed JSON in fixtures folder (exact name expected by MockReader)
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    stem_json = fixtures_dir / f"{file_path.stem}.json"
    sha_json = fixtures_dir / f"{parsed_doc.sha256}.json"

    data = parsed_doc.model_dump()
    with stem_json.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    with sha_json.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    logger.info("Saved fixture JSON: %s and %s", stem_json.name, sha_json.name)

    # 5. Generate overlay PNG per page
    for p_idx, page_p in enumerate(page_paths):
        overlay_name = f"{file_path.stem}_p{p_idx + 1}_overlay.png"
        draw_overlay(page_p, parsed_doc, p_idx, overlay_dir / overlay_name)

    return parsed_doc


def main() -> None:
    parser = argparse.ArgumentParser(description="INX parse layer dumper and visualizer.")
    parser.add_argument("target", help="Path to PDF/image file or directory of documents.")
    parser.add_argument("--out", "-o", default=str(_REPO_ROOT / "fixtures"), help="Directory to store fixture JSON.")
    parser.add_argument("--overlay-dir", default=str(_REPO_ROOT / "data" / "overlays"), help="Directory for overlay PNGs.")
    args = parser.parse_args()

    target_path = Path(args.target)
    fixtures_dir = Path(args.out)
    overlay_dir = Path(args.overlay_dir)

    if not target_path.exists():
        logger.error("Target path not found: %s", target_path)
        sys.exit(1)

    reader = CombinedReader()
    try:
        if target_path.is_file():
            process_file(target_path, reader, fixtures_dir, overlay_dir)
        else:
            files = sorted(
                [
                    p for p in target_path.rglob("*")
                    if p.is_file() and p.suffix.lower() in {".pdf", ".jpg", ".jpeg", ".png"}
                ]
            )
            logger.info("Found %d documents in %s", len(files), target_path)
            for f in files:
                process_file(f, reader, fixtures_dir, overlay_dir)
    finally:
        reader.unload()


if __name__ == "__main__":
    main()
