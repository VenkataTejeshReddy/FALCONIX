# Owner: Laptop B
"""INX – Generate mock classifier/extractor fixture files.

Reads fixtures/synthetic_docs/ground_truth.json and expected_outcomes.json
and writes one <sha256>.classify.json and one <sha256>.fields.json per
document into fixtures/synthetic_docs/.

These fixture files are consumed by:
  - app/classify/mock_classifier.py
  - app/extract/mock_extractor.py

Run:
    python scripts/make_mock_fixtures.py
    python scripts/make_mock_fixtures.py --fixture-dir path/to/dir
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE_DIR = _REPO_ROOT / "fixtures" / "synthetic_docs"

# Map of ground-truth document filenames to their SHA-256 digests.
# We compute this at runtime from the fixture directory.


def _sha256_map(fixture_dir: Path) -> dict[str, str]:
    """Return {filename: sha256} by hashing every file in fixture_dir (recursive)."""
    import hashlib

    result: dict[str, str] = {}
    for p in fixture_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".pdf", ".jpg", ".jpeg", ".png"}:
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            result[p.name] = digest
    return result


def _doc_type_from_filename(filename: str) -> str:
    """Infer a DocumentType value from a synthetic filename."""
    name = filename.lower()
    if "resume" in name:
        return "resume"
    if "id" in name or "id_card" in name:
        return "id_document"
    if "marksheet" in name:
        return "marksheet"
    if "reg_letter" in name or "registration" in name:
        return "registration_letter"
    if "offer_letter" in name:
        return "offer_letter"
    if "cover" in name:
        return "cover_letter"
    if "transcript" in name:
        return "transcript"
    if "degree" in name:
        return "degree_certificate"
    if "menu" in name or "unknown" in name:
        return "unknown"
    if "marksheet" in name:
        return "marksheet"
    return "unknown"


def _status_from_field_value(
    field_name: str,
    value: str | None,
    defect: str,
    altered_field: str | None,
) -> str:
    """Derive FieldStatus from ground-truth value and defect type."""
    if value is None or value == "":
        return "missing"
    if defect in ("blur", "obscured"):
        return "unclear"
    if defect in ("bad_checksum", "injection", "future_date"):
        return "unreliable"
    if defect in ("conflict", "typo") and (altered_field is None or field_name == altered_field):
        return "conflict"
    if defect == "missing" and (altered_field is None or field_name == altered_field):
        return "missing"
    return "valid"


def _confidence_from_defect(defect: str, field_name: str, altered_field: str | None) -> float:
    """Derive extraction confidence from defect type."""
    if defect in ("blur", "bad_checksum", "injection", "future_date"):
        return 0.40
    if defect == "obscured" and (altered_field is None or field_name == altered_field):
        return 0.30
    if defect in ("typo", "conflict") and (altered_field is None or field_name == altered_field):
        return 0.85
    return 0.95


def generate_fixtures(fixture_dir: Path) -> None:
    """Generate .classify.json and .fields.json for every document."""
    gt_path = fixture_dir / "ground_truth.json"
    if not gt_path.exists():
        logger.error("ground_truth.json not found in %s – run make_synthetic_docs.py first", fixture_dir)
        return

    eo_path = fixture_dir / "expected_outcomes.json"
    doc_expectations: dict = {}
    if eo_path.exists():
        try:
            eo_data = json.loads(eo_path.read_text(encoding="utf-8"))
            doc_expectations = eo_data.get("documents", {})
        except Exception:
            pass

    # ground_truth.json is a dict keyed by filename
    ground_truth: dict = json.loads(gt_path.read_text(encoding="utf-8"))
    sha_map = _sha256_map(fixture_dir)

    generated_classify = 0
    generated_fields = 0

    for filename, entry in ground_truth.items():
        sha256: str = sha_map.get(filename, "")
        defect: str = entry.get("defect", "none")
        altered_field: str | None = entry.get("altered_field")
        # Support both 'true_fields' and 'true_values' key names
        true_values: dict = entry.get("true_fields", entry.get("true_values", {}))
        scenario: str = entry.get("scenario", "")

        if not sha256:
            logger.warning("No SHA-256 found for file %s – skipping", filename)
            continue

        # ---------------------------------------------------------------
        # <sha256>.classify.json
        # ---------------------------------------------------------------
        inferred_type = entry.get("doc_type") or _doc_type_from_filename(filename)
        # Unknown/menu docs → unknown type at full confidence
        if defect == "unknown_type":
            inferred_type = "unknown"

        classify_fixture = {
            "doc_type": inferred_type,
            "confidence": 0.95 if inferred_type != "unknown" else 0.0,
            "layer": "fixture",
            "reasons": [
                f"Fixture-based classification from ground_truth.json",
                f"scenario={scenario} defect={defect or 'none'}",
            ],
            "scores": {inferred_type: 0.95} if inferred_type != "unknown" else {},
        }
        classify_path = fixture_dir / f"{sha256}.classify.json"
        classify_path.write_text(
            json.dumps(classify_fixture, indent=2), encoding="utf-8"
        )
        generated_classify += 1

        # ---------------------------------------------------------------
        # <sha256>.fields.json
        # ---------------------------------------------------------------
        if not true_values:
            fields_path = fixture_dir / f"{sha256}.fields.json"
            if not fields_path.exists():
                fields_path.write_text("[]", encoding="utf-8")
                generated_fields += 1
            continue

        exp_doc = doc_expectations.get(filename, {})
        expected_statuses = exp_doc.get("expected_statuses", {})

        ALTERED_VALUES = {
            "job_name_typo_id.jpg": {"applicant_name": "Rohhan Verma"},
            "job_initials_typo_id.jpg": {"applicant_name": "P. Sharma"},
            "job_conflicting_id.pdf": {"id_number": "236123456783"},
            "college_name_typo_id.jpg": {"applicant_name": "Ananya Iyyar"},
            "college_initials_typo_id.jpg": {"applicant_name": "P. Sharma"},
            "college_future_dob_id.pdf": {"date_of_birth": "2045-01-01"},
            "job_6page_differing_page5.pdf": {"id_number": "551234567890"},
            "college_6page_differing_page5.pdf": {"marks_or_grade": "7.2 CGPA"},
        }

        field_records = []
        for field_name, raw_value in true_values.items():
            value = str(raw_value) if raw_value is not None else None
            if filename in ALTERED_VALUES and field_name in ALTERED_VALUES[filename]:
                value = ALTERED_VALUES[filename][field_name]

            if field_name in expected_statuses:
                status = expected_statuses[field_name]
            else:
                status = _status_from_field_value(
                    field_name, value, defect, altered_field
                )
            if status == "missing":
                value = None
            if defect == "injection":
                status = "unreliable"
            confidence = _confidence_from_defect(defect, field_name, altered_field)
            if status in ("unreliable", "unclear"):
                confidence = min(confidence, 0.50)
            field_records.append({
                "field": field_name,
                "value": value,
                "status": status,
                "confidence": confidence,
                "reason": (
                    f"Fixture: defect={defect or 'none'}"
                    + (f" altered_field={altered_field}" if altered_field else "")
                ),
            })

        fields_path = fixture_dir / f"{sha256}.fields.json"
        fields_path.write_text(
            json.dumps(field_records, indent=2), encoding="utf-8"
        )
        generated_fields += 1

    logger.info(
        "Generated %d .classify.json and %d .fields.json in %s",
        generated_classify,
        generated_fields,
        fixture_dir,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate mock classifier/extractor fixture JSON files."
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=_FIXTURE_DIR,
        help="Directory containing ground_truth.json and synthetic documents",
    )
    args = parser.parse_args()
    generate_fixtures(args.fixture_dir)


if __name__ == "__main__":
    main()
