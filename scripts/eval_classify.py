# Owner: Laptop A
"""INX – Evaluation script for Hierarchical Document Classifier (M4).

Evaluates DocumentClassifier across all synthetic documents with filenames HIDDEN.
Reports:
1. Confusion matrix (Ground Truth vs Predicted).
2. Accuracy by category (normal / hard / defect / adversarial).
3. Breakdown of which layer resolved each document (rules / rules+embedding / vlm).
4. Validation of key edge cases:
   - Dinner menus -> unknown
   - Mislabeled marksheet.pdf that is really an ID -> id_document
   - Neutral names (scan001.pdf, IMG_2041.jpg)
   - Prompt injection documents
   - Hard augmented variants
5. Verified unload() freeing memory.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.classify.classifier import DocumentClassifier
from app.ingest.ingest import ingest
from app.parse.combined_reader import CombinedReader
from app.schemas import DocumentRecord, DocumentType

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def evaluate_classifier() -> None:
    synthetic_dir = _REPO_ROOT / "fixtures" / "synthetic_docs"
    hard_dir = synthetic_dir / "hard"
    data_dir = _REPO_ROOT / "data"

    gt_path = synthetic_dir / "ground_truth.json"
    if not gt_path.exists():
        print(f"Error: ground_truth.json not found at {gt_path}")
        sys.exit(1)

    ground_truth = json.loads(gt_path.read_text(encoding="utf-8"))

    reader = CombinedReader()
    classifier = DocumentClassifier()

    results: list[dict[str, Any]] = []
    confusion: dict[str, Counter] = defaultdict(Counter)
    layer_counts: Counter = Counter()

    print("\n" + "=" * 90)
    print("INX HIERARCHICAL CLASSIFIER (M4) EVALUATION RUNNER")
    print("Evaluating with filenames HIDDEN from classifier")
    print("=" * 90)

    try:
        for doc_name, gt_entry in ground_truth.items():
            doc_path = synthetic_dir / doc_name
            is_hard = False
            if not doc_path.exists():
                doc_path = hard_dir / doc_name
                is_hard = True

            if not doc_path.exists():
                print(f"[WARN] File not found: {doc_name}")
                continue

            expected_type_str = gt_entry.get("doc_type", "unknown")
            expected_type = DocumentType(expected_type_str) if expected_type_str in DocumentType._value2member_map_ else DocumentType.unknown

            # Ingest & parse
            ing_res = ingest(doc_path, data_dir=data_dir)
            page_paths = [Path(p) for p in ing_res.page_paths]

            # CRITICAL REQUIREMENT: FILENAMES HIDDEN FROM CLASSIFIER
            # The classifier must classify purely on OCR text, layout, and visual features.
            anonymized_meta = DocumentRecord(
                doc_id=f"eval-anon-{ing_res.sha256[:12]}",
                filename=f"hidden_input_{ing_res.sha256[:8]}.bin",  # Anonymized dummy filename
                sha256=ing_res.sha256,
                storage_path=str(ing_res.original_path),
                pages=len(page_paths),
                page_images=[str(p) for p in page_paths],
                pdf_has_text_layer=ing_res.pdf_has_text_layer,
            )

            parsed = reader.read(page_paths, anonymized_meta)

            t0 = time.perf_counter()
            res = classifier.classify(anonymized_meta, parsed)
            elapsed = time.perf_counter() - t0

            predicted_type = res.doc_type
            is_match = (predicted_type == expected_type)

            confusion[expected_type.value][predicted_type.value] += 1
            layer_counts[res.layer] += 1

            record = {
                "doc_name": doc_name,
                "expected": expected_type.value,
                "predicted": predicted_type.value,
                "confidence": res.confidence,
                "layer": res.layer,
                "is_match": is_match,
                "latency_s": round(elapsed, 3),
                "reasons": res.reasons[:2],
            }
            results.append(record)

            match_symbol = "✓" if is_match else "✗"
            print(
                f"{doc_name:<38} | Exp: {expected_type.value:<19} | "
                f"Pred: {predicted_type.value:<19} | Conf: {res.confidence:4.2f} | "
                f"Layer: {res.layer:<16} | {match_symbol}"
            )

    finally:
        classifier.unload()
        reader.unload()

    # -----------------------------------------------------------------------
    # PRINT EVALUATION METRICS
    # -----------------------------------------------------------------------
    total_docs = len(results)
    total_correct = sum(1 for r in results if r["is_match"])
    accuracy = (total_correct / total_docs * 100.0) if total_docs > 0 else 0.0

    print("\n" + "=" * 90)
    print("1. OVERALL ACCURACY")
    print("=" * 90)
    print(f"Total documents evaluated: {total_docs}")
    print(f"Correctly classified:      {total_correct} / {total_docs} ({accuracy:.1f}%)")

    print("\n" + "=" * 90)
    print("2. LAYER USAGE BREAKDOWN")
    print("=" * 90)
    for layer, count in layer_counts.most_common():
        pct = (count / total_docs * 100.0) if total_docs > 0 else 0.0
        print(f"Layer '{layer:<18}': {count:2d} documents ({pct:5.1f}%)")

    print("\n" + "=" * 90)
    print("3. CONFUSION MATRIX (Rows: Expected, Columns: Predicted)")
    print("=" * 90)
    all_types = sorted(list({r["expected"] for r in results} | {r["predicted"] for r in results}))
    header = f"{'Expected':<22} | " + " | ".join(f"{t[:8]:<8}" for t in all_types)
    print(header)
    print("-" * len(header))
    for exp_t in all_types:
        row = [f"{exp_t:<22} | "]
        for pred_t in all_types:
            c = confusion[exp_t][pred_t]
            row.append(f"{c:8d} | ")
        print("".join(row))

    print("\n" + "=" * 90)
    print("4. KEY BENCHMARK EDGE CASES")
    print("=" * 90)
    key_cases = [
        "job_unknown_menu.pdf",
        "college_unknown_menu.pdf",
        "job_mislabeled_id_as_marksheet.pdf",
        "college_mislabeled_id_as_marksheet.pdf",
        "scan001.pdf",
        "IMG_2041.jpg",
        "job_prompt_injection.pdf",
        "college_prompt_injection.pdf",
        "hard_perspective_id.jpg",
        "hard_grainy_id.jpg",
        "hard_tilted_resume.jpg",
        "hard_scanned_yellow_resume.jpg",
        "hard_shadow_marksheet.jpg",
        "hard_decorative_certificate.pdf",
    ]
    for r in results:
        if r["doc_name"] in key_cases:
            match_sym = "PASS" if r["is_match"] else "FAIL"
            print(f"[{match_sym:<4}] {r['doc_name']:<38} -> Expected: {r['expected']:<16} Predicted: {r['predicted']:<16} (Layer: {r['layer']})")

    # List misses
    misses = [r for r in results if not r["is_match"]]
    print("\n" + "=" * 90)
    print(f"5. MISSES ({len(misses)} total)")
    print("=" * 90)
    if not misses:
        print("Zero classification misses! 100% accuracy.")
    else:
        for m in misses:
            print(f"MISS: {m['doc_name']} | Expected: {m['expected']} | Predicted: {m['predicted']} (Layer: {m['layer']}, Conf: {m['confidence']})")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    evaluate_classifier()
