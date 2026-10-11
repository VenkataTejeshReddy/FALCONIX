# Owner: Laptop A
"""INX – Tests: Extractor (Reader B).

Unit tests cover:
1. Normalisation & grounding:
   - Text normalisation (casefold, punctuation, whitespace, digits).
   - Strict matching on IDs, dates, numbers, emails (NO fuzzy matching).
   - Fuzzy matching on names (token fuzzy >= 90).
2. Reconcile matrix:
   - Both null -> missing.
   - VLM null, OCR present -> unclear ("readers disagree").
   - VLM present, OCR null (grounded in OCR text) -> valid (confidence 0.75).
   - VLM present, OCR null (unreferenced) -> unreliable.
   - Both present, normalised equal -> valid (confidence 0.95).
   - Both present, differ -> unclear (never conflict on one page).
   - VLM obscured=True -> unclear.
3. Multi-page conflict:
   - Different normalised values on different pages -> conflict (value None).
4. VLM model lifetime & client calls:
   - keep_alive passed on every request.
   - unload() sends keep_alive=0.
   - JSON failure / retry robustness.
5. Integration test on macOS marked @pytest.mark.mac.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.extract.field_extractor import FieldExtractor
from app.extract.grounding import (
    is_quote_grounded,
    is_value_grounded,
    normalise_field_value,
    normalise_text,
    values_are_equal,
)
from app.extract.ocr_fields import find_ocr_field
from app.extract.reconcile import (
    reconcile_multi_page_results,
    reconcile_single_page_field,
)
from app.extract.vlm_reader import VLMReader
from app.schemas import BBox, DocumentRecord, DocumentType, FieldResult, FieldStatus, ParsedDocument, ParsedLine

is_mac = sys.platform == "darwin"


# ---------------------------------------------------------------------------
# 1. Normalisation & Grounding
# ---------------------------------------------------------------------------


def test_normalise_text_rules():
    raw = "  Applicant:  ROHAN  VERMA,  (Ph.D.) - Roll #2021!  "
    norm = normalise_text(raw)
    assert norm == "applicant rohan verma ph d roll 2021"


def test_strict_matching_no_fuzzy_for_ids_dates_numbers_emails():
    # IDs: must match exactly after stripping spaces and hyphens
    assert values_are_equal("2361 2345 6782", "2361-2345-6782", "id")
    assert not values_are_equal("2361 2345 6782", "2361 2345 6783", "id")  # 1 digit off fails

    # Dates: must match exact calendar date
    assert values_are_equal("2023-01-15", "15/01/2023", "date")
    assert values_are_equal("15 Jan 2023", "2023-01-15", "date")
    assert not values_are_equal("2023-01-15", "2023-01-16", "date")

    # Numbers: must match exact number
    assert values_are_equal("4", "4.0", "number")
    assert values_are_equal("4 years", "4", "number")
    assert not values_are_equal("4", "5", "number")

    # Emails: must match exact email
    assert values_are_equal("User@Example.COM", "user@example.com", "email")
    assert not values_are_equal("user1@example.com", "user2@example.com", "email")

    # Names: fuzzy token match >= 90 allowed
    assert values_are_equal("Rohan Verma", "Verma, Rohan", "name")
    assert values_are_equal("Dr. Rohan Verma", "Rohan Verma", "name")
    assert not values_are_equal("Rohan Verma", "Priya Sharma", "name")


def test_quote_grounding():
    ocr_text = "This is an official certificate issued to Rohan Verma on 2023-01-15."
    assert is_quote_grounded("Rohan Verma on 2023-01-15", ocr_text)
    assert not is_quote_grounded("Completely Unrelated Text", ocr_text)


# ---------------------------------------------------------------------------
# 2. Reconcile Matrix
# ---------------------------------------------------------------------------


def test_reconcile_both_null():
    res = reconcile_single_page_field(
        field_name="email",
        doc_type=DocumentType.resume,
        ocr_val=None,
        ocr_bbox=None,
        ocr_page=None,
        vlm_val=None,
        vlm_quote=None,
        vlm_obscured=False,
        vlm_page=0,
        page_text="",
        field_type="email",
    )
    assert res.status == FieldStatus.missing
    assert res.value is None


def test_reconcile_vlm_null_ocr_present():
    bbox = BBox(x0=10, y0=20, x1=100, y1=40)
    res = reconcile_single_page_field(
        field_name="email",
        doc_type=DocumentType.resume,
        ocr_val="rohan@example.com",
        ocr_bbox=bbox,
        ocr_page=0,
        vlm_val=None,
        vlm_quote=None,
        vlm_obscured=False,
        vlm_page=0,
        page_text="Email: rohan@example.com",
        field_type="email",
    )
    assert res.status == FieldStatus.unclear
    assert res.value == "rohan@example.com"
    assert "readers disagree" in res.reason


def test_reconcile_vlm_present_ocr_null_grounded():
    page_txt = "Contact us at rohan@example.com for inquiries."
    res = reconcile_single_page_field(
        field_name="email",
        doc_type=DocumentType.resume,
        ocr_val=None,
        ocr_bbox=None,
        ocr_page=None,
        vlm_val="rohan@example.com",
        vlm_quote="rohan@example.com for inquiries",
        vlm_obscured=False,
        vlm_page=0,
        page_text=page_txt,
        field_type="email",
    )
    assert res.status == FieldStatus.valid
    assert res.value == "rohan@example.com"
    assert res.confidence == 0.75
    assert "locator did not find it" in res.reason


def test_reconcile_vlm_present_ocr_null_unreferenced():
    res = reconcile_single_page_field(
        field_name="email",
        doc_type=DocumentType.resume,
        ocr_val=None,
        ocr_bbox=None,
        ocr_page=None,
        vlm_val="hallucinated@example.com",
        vlm_quote="fake quote",
        vlm_obscured=False,
        vlm_page=0,
        page_text="Completely different document text",
        field_type="email",
    )
    assert res.status == FieldStatus.unreliable


def test_reconcile_both_present_equal():
    page_txt = "Candidate Name: Rohan Verma"
    bbox = BBox(x0=10, y0=20, x1=100, y1=40)
    res = reconcile_single_page_field(
        field_name="applicant_name",
        doc_type=DocumentType.resume,
        ocr_val="Rohan Verma",
        ocr_bbox=bbox,
        ocr_page=0,
        vlm_val="Rohan Verma",
        vlm_quote="Candidate Name: Rohan Verma",
        vlm_obscured=False,
        vlm_page=0,
        page_text=page_txt,
        field_type="name",
    )
    assert res.status == FieldStatus.valid
    assert res.value == "Rohan Verma"
    assert res.confidence == 0.95


def test_reconcile_both_present_differ_never_conflict_on_one_page():
    bbox = BBox(x0=10, y0=20, x1=100, y1=40)
    res = reconcile_single_page_field(
        field_name="id_number",
        doc_type=DocumentType.id_document,
        ocr_val="236123456782",
        ocr_bbox=bbox,
        ocr_page=0,
        vlm_val="236123456789",
        vlm_quote="ID: 236123456789",
        vlm_obscured=False,
        vlm_page=0,
        page_text="ID: 236123456782",
        field_type="id",
    )
    assert res.status == FieldStatus.unclear
    assert res.status != FieldStatus.conflict  # Never conflict on a single page
    assert res.ocr_value == "236123456782"
    assert res.vlm_value == "236123456789"


def test_reconcile_vlm_obscured():
    bbox = BBox(x0=10, y0=20, x1=100, y1=40)
    res = reconcile_single_page_field(
        field_name="id_number",
        doc_type=DocumentType.id_document,
        ocr_val="236123456782",
        ocr_bbox=bbox,
        ocr_page=0,
        vlm_val="236123456782",
        vlm_quote="236123456782",
        vlm_obscured=True,
        vlm_page=0,
        page_text="236123456782",
        field_type="id",
    )
    assert res.status == FieldStatus.unclear
    assert "obscured" in res.reason


# ---------------------------------------------------------------------------
# 3. Multi-Page Conflict
# ---------------------------------------------------------------------------


def test_multi_page_conflict():
    r1 = FieldResult(
        field="institution",
        doc_type=DocumentType.marksheet,
        value="National Institute of Technology",
        page=0,
        status=FieldStatus.valid,
        confidence=0.95,
    )
    r2 = FieldResult(
        field="institution",
        doc_type=DocumentType.marksheet,
        value="Indian Institute of Technology",
        page=1,
        status=FieldStatus.valid,
        confidence=0.95,
    )
    merged = reconcile_multi_page_results("institution", [r1, r2], "text")
    assert merged.status == FieldStatus.conflict
    assert merged.value is None
    assert "page 1: National Institute of Technology" in merged.reason
    assert "page 2: Indian Institute of Technology" in merged.reason


# ---------------------------------------------------------------------------
# 4. VLM Reader Client Calls, Keep-Alive, & Robustness
# ---------------------------------------------------------------------------


def test_vlm_reader_keep_alive_and_unload(tmp_path: Path):
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.message.content = json.dumps({
        "fields": {
            "email": {"value": "test@example.com", "evidence_quote": "test@example.com", "obscured": False}
        },
        "stamp_present": False,
        "signature_present": False,
    })
    mock_resp.eval_count = 42
    mock_client.chat.return_value = mock_resp

    reader = VLMReader(client=mock_client, keep_alive="3m", cache_dir=tmp_path)

    test_img = tmp_path / "page.png"
    from PIL import Image
    Image.new("RGB", (200, 200), "white").save(test_img)

    res = reader.extract_page_fields(test_img, ["email"], "resume")
    assert res["fields"]["email"]["value"] == "test@example.com"

    # Verify keep_alive was passed explicitly
    call_args = mock_client.chat.call_args[1]
    assert call_args["keep_alive"] == "3m"

    # Verify unload sends keep_alive=0
    reader.unload()
    unload_call_args = mock_client.chat.call_args[1]
    assert unload_call_args["keep_alive"] == 0


def test_vlm_reader_json_failure_recovery(tmp_path: Path):
    mock_client = MagicMock()
    # First response is malformed JSON, second response is valid
    resp_bad = MagicMock()
    resp_bad.message.content = "Malformed not-json response"
    resp_good = MagicMock()
    resp_good.message.content = json.dumps({
        "fields": {
            "applicant_name": {"value": "Priya Sharma", "evidence_quote": "Priya Sharma", "obscured": False}
        },
        "stamp_present": False,
        "signature_present": False,
    })
    resp_good.eval_count = 25
    mock_client.chat.side_effect = [Exception("JSON Error"), resp_good]

    reader = VLMReader(client=mock_client, cache_dir=tmp_path)
    test_img = tmp_path / "page_retry.png"
    from PIL import Image
    Image.new("RGB", (200, 200), "white").save(test_img)

    res = reader.extract_page_fields(test_img, ["applicant_name"], "id_document")
    assert res["fields"]["applicant_name"]["value"] == "Priya Sharma"


# ---------------------------------------------------------------------------
# 5. Integration Test (Mac only)
# ---------------------------------------------------------------------------


@pytest.mark.mac
@pytest.mark.skipif(not is_mac, reason="Vision OCR and local VLM are run on Apple Silicon / macOS")
def test_field_extractor_real_fixture():
    fixture_path = Path("fixtures/job_normal_resume.json")
    if not fixture_path.exists():
        pytest.skip("Fixture not found")

    from app.config import load_scenario
    scenario = load_scenario("job_application")
    parsed = ParsedDocument.model_validate_json(fixture_path.read_text())

    doc_meta = DocumentRecord(
        filename="job_normal_resume.pdf",
        sha256=parsed.sha256,
        storage_path="fixtures/synthetic_docs/job_normal_resume.pdf",
        pages=parsed.pages,
        page_images=[],
        doc_type=DocumentType.resume,
    )

    extractor = FieldExtractor()
    try:
        results = extractor.extract(doc_meta, parsed, DocumentType.resume, scenario)
        res_by_name = {r.field: r for r in results}
        assert "applicant_name" in res_by_name
        assert "email" in res_by_name
        # OCR locator finds exact values from parsed document
        assert res_by_name["applicant_name"].ocr_value == "Rohan Verma"
        assert res_by_name["email"].ocr_value == "rohan.verma@example.com"
    finally:
        extractor.unload()
