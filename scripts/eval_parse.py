# Owner: Laptop A
"""INX – Evaluation script for Parse Layer (Reader A).

Evaluates CombinedReader on every synthetic document in fixtures/synthetic_docs
(including hard/ variants) against ground_truth.json.
Reports exact / approximate / not found field counts per document and per engine.
Saves parsed JSON fixtures into fixtures/ for MockReader.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rapidfuzz import fuzz

from app.ingest.ingest import ingest
from app.parse.combined_reader import CombinedReader
from app.schemas import DocumentRecord, ParsedDocument

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def evaluate_document(
    doc_name: str,
    doc_path: Path,
    gt_entry: dict[str, Any],
    reader: CombinedReader,
    fixtures_dir: Path,
) -> dict[str, Any]:
    # Ingest document
    data_dir = _REPO_ROOT / "data"
    ingest_res = ingest(doc_path, data_dir=data_dir)
    page_paths = [Path(p) for p in ingest_res.page_paths]

    doc_meta = DocumentRecord(
        filename=doc_path.name,
        sha256=ingest_res.sha256,
        storage_path=str(ingest_res.original_path),
        pages=len(page_paths),
        page_images=[str(p) for p in page_paths],
        pdf_has_text_layer=ingest_res.pdf_has_text_layer,
    )

    parsed_doc = reader.read(page_paths, doc_meta)

    # Save fixture JSON for MockReader
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    stem_json = fixtures_dir / f"{doc_path.stem}.json"
    sha_json = fixtures_dir / f"{parsed_doc.sha256}.json"
    json_bytes = parsed_doc.model_dump_json(indent=2)
    stem_json.write_text(json_bytes, encoding="utf-8")
    sha_json.write_text(json_bytes, encoding="utf-8")

    full_text = parsed_doc.full_text.lower()
    line_engines = parsed_doc.meta.get("line_engines", [])
    primary_engine = line_engines[0] if line_engines else "none"

    true_fields = gt_entry.get("true_fields", {})
    exact_count = 0
    approx_count = 0
    not_found_count = 0

    field_results = {}
    for f_name, f_val in true_fields.items():
        val_str = str(f_val).strip().lower()
        if not val_str:
            continue

        if val_str in full_text:
            exact_count += 1
            field_results[f_name] = "EXACT"
        elif fuzz.partial_ratio(val_str, full_text) >= 80:
            approx_count += 1
            field_results[f_name] = "APPROX"
        else:
            not_found_count += 1
            field_results[f_name] = "NOT_FOUND"

    return {
        "document": doc_name,
        "engine": primary_engine,
        "pages": parsed_doc.pages,
        "lines": len(parsed_doc.lines),
        "exact": exact_count,
        "approx": approx_count,
        "not_found": not_found_count,
        "total_fields": len(true_fields),
        "fields": field_results,
    }


def main() -> None:
    synthetic_dir = _REPO_ROOT / "fixtures" / "synthetic_docs"
    hard_dir = synthetic_dir / "hard"
    fixtures_dir = _REPO_ROOT / "fixtures"

    gt_path = synthetic_dir / "ground_truth.json"
    if not gt_path.exists():
        print(f"Error: ground_truth.json not found at {gt_path}")
        sys.exit(1)

    with gt_path.open("r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    reader = CombinedReader()
    results = []

    print("\n" + "=" * 80)
    print("INX PARSE LAYER (READER A) EVALUATION REPORT")
    print("=" * 80)

    try:
        for doc_name, gt_entry in ground_truth.items():
            doc_path = synthetic_dir / doc_name
            if not doc_path.exists():
                doc_path = hard_dir / doc_name

            if not doc_path.exists():
                print(f"[WARN] File not found: {doc_name}")
                continue

            res = evaluate_document(doc_name, doc_path, gt_entry, reader, fixtures_dir)
            results.append(res)
            print(
                f"{res['document']:<38} | Engine: {res['engine']:<10} | "
                f"Exact: {res['exact']:2d} | Approx: {res['approx']:2d} | Not Found: {res['not_found']:2d} "
                f"(Total: {res['total_fields']})"
            )
    finally:
        reader.unload()

    total_exact = sum(r["exact"] for r in results)
    total_approx = sum(r["approx"] for r in results)
    total_not_found = sum(r["not_found"] for r in results)
    total_fields = sum(r["total_fields"] for r in results)

    print("\n" + "=" * 80)
    print("EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Total documents evaluated: {len(results)}")
    print(f"Total true fields tested:   {total_fields}")
    print(f"  - Exact matches:          {total_exact:4d} ({total_exact / total_fields * 100:.1f}%)")
    print(f"  - Approximate matches:    {total_approx:4d} ({total_approx / total_fields * 100:.1f}%)")
    print(f"  - Not found:              {total_not_found:4d} ({total_not_found / total_fields * 100:.1f}%)")
    print(f"Overall field capture rate: {(total_exact + total_approx) / total_fields * 100:.1f}%")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
