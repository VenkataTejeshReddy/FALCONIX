# Owner: Laptop A
"""INX – Evaluation script for Extractor (Reader B).

Runs FieldExtractor on every synthetic document in fixtures/synthetic_docs
(including hard/ variants and prompt injection) against ground_truth.json.
Uses STRICT matching: ids, dates, numbers, emails must match exactly after
normalisation; only names may use fuzzy >= 90.

Reports:
1. Exact match rate and status distribution per field.
2. Two headline metrics:
   (a) FALSE-VALID RATE: fields with status valid but value != truth (target 0)
   (b) DEFECT DETECTION RATE: injected defects that ended non-valid
3. Metrics split by normal / hard / defect documents, and defect docs by defect type.
4. Measured cold-load seconds and warm seconds per page.
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

from app.config import load_scenario
from app.extract.field_extractor import FieldExtractor
from app.extract.grounding import normalise_field_value, values_are_equal
from app.extract.ocr_fields import load_field_labels
from app.ingest.ingest import ingest
from app.parse.combined_reader import CombinedReader
from app.schemas import DocumentRecord, DocumentType, FieldStatus

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def evaluate_all() -> None:
    synthetic_dir = _REPO_ROOT / "fixtures" / "synthetic_docs"
    hard_dir = synthetic_dir / "hard"
    data_dir = _REPO_ROOT / "data"

    gt_path = synthetic_dir / "ground_truth.json"
    if not gt_path.exists():
        print(f"Error: ground_truth.json not found at {gt_path}")
        sys.exit(1)

    ground_truth = json.loads(gt_path.read_text(encoding="utf-8"))
    field_labels = load_field_labels()

    scenarios = {
        "job_application": load_scenario("job_application"),
        "college": load_scenario("college"),
    }

    reader = CombinedReader()
    extractor = FieldExtractor(field_labels_cfg=field_labels)

    # Metrics collectors
    split_records = defaultdict(list)
    defect_type_records = defaultdict(list)
    field_stats = defaultdict(lambda: {"total": 0, "exact": 0, "statuses": Counter()})

    total_fields_tested = 0
    total_false_valid = 0

    total_injected_defects = 0
    detected_injected_defects = 0

    page_latencies: list[float] = []

    print("\n" + "=" * 90)
    print("INX EXTRACTOR (READER B) EVALUATION RUNNER")
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

            scenario_name = gt_entry.get("scenario", "job_application")
            scenario_cfg = scenarios.get(scenario_name, scenarios["job_application"])
            doc_type_str = gt_entry.get("doc_type", "unknown")
            doc_type = DocumentType(doc_type_str) if doc_type_str in DocumentType._value2member_map_ else DocumentType.unknown

            true_fields = gt_entry.get("true_fields", {})
            defect = gt_entry.get("defect", "none")
            altered_field = gt_entry.get("altered_field")

            # Ingest & parse
            ing_res = ingest(doc_path, data_dir=data_dir)
            page_paths = [Path(p) for p in ing_res.page_paths]
            doc_meta = DocumentRecord(
                doc_id=f"eval-{doc_path.stem}",
                filename=doc_path.name,
                sha256=ing_res.sha256,
                storage_path=str(ing_res.original_path),
                pages=len(page_paths),
                page_images=[str(p) for p in page_paths],
                pdf_has_text_layer=ing_res.pdf_has_text_layer,
            )

            parsed = reader.read(page_paths, doc_meta)

            # Measure extraction time
            t0 = time.perf_counter()
            results = extractor.extract(doc_meta, parsed, doc_type, scenario_cfg)
            elapsed = time.perf_counter() - t0
            if page_paths:
                page_latencies.append(elapsed / len(page_paths))

            res_by_field = {r.field: r for r in results}

            # Classify into split
            if is_hard:
                category = "hard"
            elif defect != "none":
                category = "defect"
            else:
                category = "normal"

            doc_eval = {
                "doc_name": doc_name,
                "category": category,
                "defect": defect,
                "altered_field": altered_field,
                "fields": {},
            }

            for f_name, true_val in true_fields.items():
                total_fields_tested += 1
                f_type = field_labels.get(f_name, {}).get("type", "text")
                fr = res_by_field.get(f_name)

                status_val = fr.status.value if fr else "missing"
                extracted_val = fr.value if fr else None

                field_stats[f_name]["total"] += 1
                field_stats[f_name]["statuses"][status_val] += 1

                is_match = values_are_equal(extracted_val, str(true_val), f_type)
                if is_match and status_val == "valid":
                    field_stats[f_name]["exact"] += 1

                # Check false valid
                is_false_valid = (status_val == "valid" and not is_match)
                if is_false_valid:
                    total_false_valid += 1

                # Check defect detection on altered field
                is_defect_field = (f_name == altered_field) or (defect in ("obscured", "blur", "unknown_type"))
                if is_defect_field:
                    total_injected_defects += 1
                    if status_val != "valid":
                        detected_injected_defects += 1

                doc_eval["fields"][f_name] = {
                    "true": true_val,
                    "extracted": extracted_val,
                    "status": status_val,
                    "match": is_match,
                    "false_valid": is_false_valid,
                }

            split_records[category].append(doc_eval)
            if defect != "none":
                defect_type_records[defect].append(doc_eval)

    finally:
        extractor.unload()
        reader.unload()

    # -----------------------------------------------------------------------
    # PRINT RESULTS
    # -----------------------------------------------------------------------
    print("\n" + "=" * 90)
    print("1. PER-FIELD ACCURACY & STATUS DISTRIBUTION")
    print("=" * 90)
    print(f"{'Field Name':<25} | {'Total':<5} | {'Exact Valid':<12} | {'Status Distribution'}")
    print("-" * 90)
    for f_name, stats in sorted(field_stats.items()):
        tot = stats["total"]
        ex = stats["exact"]
        rate = (ex / tot * 100.0) if tot > 0 else 0.0
        dist = ", ".join(f"{k}:{v}" for k, v in stats["statuses"].items())
        print(f"{f_name:<25} | {tot:<5} | {ex:3d} ({rate:5.1f}%) | {dist}")

    print("\n" + "=" * 90)
    print("2. HEADLINE METRICS")
    print("=" * 90)
    false_valid_rate = (total_false_valid / total_fields_tested * 100.0) if total_fields_tested > 0 else 0.0
    defect_detect_rate = (detected_injected_defects / total_injected_defects * 100.0) if total_injected_defects > 0 else 0.0

    print(f"Total logical fields evaluated: {total_fields_tested}")
    print(f"(a) FALSE-VALID RATE:          {total_false_valid:3d} / {total_fields_tested} ({false_valid_rate:.2f}%)")
    print(f"(b) DEFECT DETECTION RATE:     {detected_injected_defects:3d} / {total_injected_defects} ({defect_detect_rate:.1f}%)")

    print("\n" + "=" * 90)
    print("3. SPLIT BREAKDOWN (NORMAL / HARD / DEFECT)")
    print("=" * 90)
    for cat in ("normal", "hard", "defect"):
        docs = split_records[cat]
        cat_fields = 0
        cat_matches = 0
        cat_false_val = 0
        for d in docs:
            for f_info in d["fields"].values():
                cat_fields += 1
                if f_info["match"] and f_info["status"] == "valid":
                    cat_matches += 1
                if f_info["false_valid"]:
                    cat_false_val += 1
        cat_rate = (cat_matches / cat_fields * 100.0) if cat_fields > 0 else 0.0
        print(f"[{cat.upper():<6}] {len(docs):2d} docs | Fields: {cat_fields:3d} | Valid Matches: {cat_matches:3d} ({cat_rate:.1f}%) | False-Valid: {cat_false_val}")

    print("\n" + "=" * 90)
    print("4. DEFECT DOCUMENTS BY DEFECT TYPE")
    print("=" * 90)
    for def_type, docs in sorted(defect_type_records.items()):
        def_fields = 0
        def_flagged = 0
        for d in docs:
            alt = d["altered_field"]
            for fname, finfo in d["fields"].items():
                if fname == alt or def_type in ("obscured", "blur", "unknown_type"):
                    def_fields += 1
                    if finfo["status"] != "valid":
                        def_flagged += 1
        pct = (def_flagged / def_fields * 100.0) if def_fields > 0 else 100.0
        print(f"Defect: {def_type:<22} | Injected fields: {def_fields:2d} | Flagged non-valid: {def_flagged:2d} ({pct:.1f}%)")

    print("\n" + "=" * 90)
    print("5. MODEL TIMINGS")
    print("=" * 90)
    cold_load = getattr(extractor._vlm, "cold_load_seconds", 0.0)
    avg_sec = sum(page_latencies) / len(page_latencies) if page_latencies else 0.0
    print(f"Cold-load seconds:             {cold_load:.3f} s")
    print(f"Warm seconds per page (avg):   {avg_sec:.3f} s")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    evaluate_all()
