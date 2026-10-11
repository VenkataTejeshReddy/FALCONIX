# Owner: Laptop A
"""Audit script for Milestone M3b verification."""

from __future__ import annotations

import json
import logging
import os
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
from app.extract.grounding import is_value_grounded, normalise_field_value, values_are_equal
from app.extract.ocr_fields import find_ocr_field, load_field_labels
from app.ingest.ingest import ingest
from app.parse.combined_reader import CombinedReader
from app.schemas import (
    CaseRecord,
    DocumentRecord,
    DocumentType,
    FieldResult,
    FieldStatus,
    ParsedDocument,
)
from app.validate.checks import validate_case_fields
from app.validate.crossdoc import run_cross_checks

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def main():
    synthetic_dir = _REPO_ROOT / "fixtures" / "synthetic_docs"
    hard_dir = synthetic_dir / "hard"
    data_dir = _REPO_ROOT / "data"
    gt_path = synthetic_dir / "ground_truth.json"

    ground_truth = json.loads(gt_path.read_text(encoding="utf-8"))
    field_labels = load_field_labels()

    scenarios = {
        "job_application": load_scenario("job_application"),
        "college": load_scenario("college"),
    }

    reader = CombinedReader()
    extractor = FieldExtractor(field_labels_cfg=field_labels)

    # Dictionary to hold full per-doc evaluation results
    doc_results = {}

    for doc_name, gt_entry in ground_truth.items():
        doc_path = synthetic_dir / doc_name
        is_hard = False
        if not doc_path.exists():
            doc_path = hard_dir / doc_name
            is_hard = True

        if not doc_path.exists():
            continue

        sc_name = gt_entry.get("scenario", "job_application")
        sc_cfg = scenarios.get(sc_name, scenarios["job_application"])
        doc_type_str = gt_entry.get("doc_type", "unknown")
        doc_type = DocumentType(doc_type_str) if doc_type_str in DocumentType._value2member_map_ else DocumentType.unknown

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
        results = extractor.extract(doc_meta, parsed, doc_type, sc_cfg)
        res_by_field = {r.field: r for r in results}

        doc_results[doc_name] = {
            "path": doc_path,
            "is_hard": is_hard,
            "gt_entry": gt_entry,
            "parsed": parsed,
            "doc_meta": doc_meta,
            "doc_type": doc_type,
            "sc_cfg": sc_cfg,
            "extracted": res_by_field,
        }

    # Dump the results to a temp JSON so we can analyze cleanly
    summary = {}
    for doc_name, d in doc_results.items():
        gt_entry = d["gt_entry"]
        true_fields = gt_entry.get("true_fields", {})
        ext_fields = {}
        for f, r in d["extracted"].items():
            ext_fields[f] = {
                "value": r.value,
                "ocr_value": r.ocr_value,
                "vlm_value": r.vlm_value,
                "status": r.status.value,
                "quote": r.evidence_quote,
                "reason": r.reason,
                "obscured": "obscured" in r.reason.lower(),
            }
        summary[doc_name] = {
            "is_hard": d["is_hard"],
            "defect": gt_entry.get("defect", "none"),
            "altered_field": gt_entry.get("altered_field"),
            "true_fields": true_fields,
            "extracted": ext_fields,
            "ocr_lines": [l.text for l in d["parsed"].lines],
        }

    out_file = _REPO_ROOT / "scripts" / "m3b_summary.json"
    out_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Summary written to {out_file}")

    extractor.unload()
    reader.unload()


if __name__ == "__main__":
    main()
