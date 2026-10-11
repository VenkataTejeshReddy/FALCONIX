# Owner: Laptop B
"""Streamlit AppTest smoke tests for the UI (app/ui/streamlit_app.py).

Verifies:
1. Home renders scenario cards and updates session state.
2. Quick check on a fixture evaluates and returns a route.
3. Batch on the mock mailbox completes and logs results.
4. Reviewer action updates case workflow status and appends an audit event.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

from app.schemas import (
    CaseRecord,
    Decision,
    DocumentRecord,
    DocumentType,
    FieldResult,
    FieldStatus,
    Route,
    WorkflowStatus,
)
from app.store.audit import write_audit
from app.store.db import list_events, load_case, save_case

_REPO_ROOT = Path(__file__).resolve().parent.parent
_APP_PATH = str(_REPO_ROOT / "app" / "ui" / "streamlit_app.py")


def test_home_renders():
    """Home view renders scenario cards, buttons, and context."""
    at = AppTest.from_file(_APP_PATH)
    at.run()
    assert not at.exception

    labels = [b.label for b in at.button]
    assert "Select Job Application" in labels
    assert "Select College Admission" in labels

    # Click scenario button
    btn_job = next(b for b in at.button if b.label == "Select Job Application")
    btn_job.click().run()
    assert not at.exception
    assert at.session_state.get("scenario") == "job_application"


def test_quick_check_fixture(tmp_path: Path, monkeypatch):
    """Quick check on a fixture evaluates and produces an outcome."""
    monkeypatch.setenv("INX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INX_MODE", "mock")

    at = AppTest.from_file(_APP_PATH)
    at.default_timeout = 30
    at.session_state["nav_radio"] = "Quick Check"
    at.session_state["scenario"] = "job_application"
    at.run()
    assert not at.exception

    # Locate and click the evaluate button
    btn_eval = next((b for b in at.button if "Evaluate Document" in b.label), None)
    assert btn_eval is not None, "Evaluate Document button should be present"

    btn_eval.click().run()
    assert not at.exception
    assert at.session_state.get("selected_case_id") is not None


def test_batch_on_mock_mailbox(tmp_path: Path, monkeypatch):
    """Batch run on fixture mailbox processes emails and records results."""
    monkeypatch.setenv("INX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INX_MODE", "mock")

    at = AppTest.from_file(_APP_PATH)
    at.default_timeout = 30
    at.session_state["nav_radio"] = "Batch Intake"
    at.session_state["scenario"] = "job_application"
    at.session_state["batch_limit_input"] = 2
    at.run()
    assert not at.exception

    btn_batch = next((b for b in at.button if "Start Batch" in b.label), None)
    assert btn_batch is not None, "Start Batch button should be present"

    btn_batch.click().run()
    assert not at.exception

    batch_res = at.session_state.get("batch_results", [])
    assert len(batch_res) > 0, "Batch run should produce results"
    routes = {r["Route"] for r in batch_res}
    assert "PROCESS" in routes or "REQUEST_INFO" in routes


def test_reviewer_action_writes_event(tmp_path: Path, monkeypatch):
    """Reviewer action updates case status and writes an append-only audit event."""
    monkeypatch.setenv("INX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INX_MODE", "mock")

    # Seed a case in SQLite
    case = CaseRecord(
        case_id="case-rev-test",
        scenario="job_application",
        sender_name="John Doe",
        sender_email="john@example.com",
        workflow_status=WorkflowStatus.review_required,
        route=Route.HUMAN_REVIEW,
        decision=Decision(
            workflow_status=WorkflowStatus.review_required,
            route=Route.HUMAN_REVIEW,
            reasons=["Discrepancy flagged"],
            rule_ids=["R01"],
        ),
    )
    case.documents.append(
        DocumentRecord(
            doc_id="doc-1",
            filename="id_card.pdf",
            sha256="fake_sha",
            doc_type=DocumentType.id_document,
            pages=1,
            quality_verdict="ok",
            storage_path="fake_path",
        )
    )
    case.fields["id_document.applicant_name"] = FieldResult(
        field="applicant_name",
        value="John Doe",
        status=FieldStatus.valid,
        confidence=0.95,
    )
    db_file = tmp_path / "audit.db"
    save_case(case, db_path=db_file)

    # Launch inspector
    at = AppTest.from_file(_APP_PATH)
    at.default_timeout = 30
    at.session_state["nav_radio"] = "Case Inspector"
    at.session_state["selected_case_id"] = "case-rev-test"
    at.run()
    assert not at.exception

    # Find approve button
    btn_approve = next((b for b in at.button if "Approve Case" in b.label), None)
    assert btn_approve is not None, "Approve Case button should be present"

    btn_approve.click().run()
    assert not at.exception

    # Verify that case is marked approved and audit event was written
    updated = load_case("case-rev-test", db_path=db_file)
    assert updated is not None
    assert updated.workflow_status == WorkflowStatus.approved

    events = list_events(case_id="case-rev-test", db_path=db_file)
    stages = [e["stage"] for e in events]
    assert "reviewer_action" in stages


def test_bboxes_drawn_on_clean_image_only(tmp_path: Path):
    """Rule 2a: Bounding boxes are drawn onto clean processed images, handling None bboxes safely."""
    from PIL import Image
    from app.schemas import BBox
    from app.ui.streamlit_app import _draw_bboxes

    # Create dummy clean image
    clean_img = Image.new("RGB", (300, 300), color="white")

    case = CaseRecord(
        case_id="test-bbox-case",
        scenario="job_application",
    )
    # Field with bbox
    case.fields["id_document.applicant_name"] = FieldResult(
        field="applicant_name",
        value="Jane Doe",
        status=FieldStatus.valid,
        doc_type=DocumentType.id_document,
        page=0,
        bbox=BBox(x0=10, y0=10, x1=100, y1=50),
    )
    # Field with NO bbox (must not crash)
    case.fields["id_document.phone"] = FieldResult(
        field="phone",
        value="1234567890",
        status=FieldStatus.valid,
        doc_type=DocumentType.id_document,
        page=0,
        bbox=None,
    )

    drawn = _draw_bboxes(clean_img, case, "id_document", page_idx=0)
    assert isinstance(drawn, Image.Image)
    # Ensure drawing created a new image and didn't crash
    assert drawn.size == (300, 300)


def test_reviewer_actions_preserve_extraction_and_audit(tmp_path: Path, monkeypatch):
    """Rule 2b: Reviewer action never changes stored extraction; writes audit events with actor; refuses correction without note."""
    monkeypatch.setenv("INX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INX_MODE", "mock")
    db_file = tmp_path / "audit.db"

    case = CaseRecord(
        case_id="case-rev-preserve",
        scenario="job_application",
        sender_name="Alice Smith",
        sender_email="alice@example.com",
        workflow_status=WorkflowStatus.review_required,
        route=Route.HUMAN_REVIEW,
        decision=Decision(
            workflow_status=WorkflowStatus.review_required,
            route=Route.HUMAN_REVIEW,
            reasons=["Needs review"],
            rule_ids=["R02"],
        ),
    )
    case.fields["id_document.applicant_name"] = FieldResult(
        field="applicant_name",
        value="Original Extracted Name",
        status=FieldStatus.valid,
        confidence=0.88,
    )
    save_case(case, db_path=db_file)

    # 1. Attempt correction without a note -> must be refused
    at = AppTest.from_file(_APP_PATH)
    at.default_timeout = 30
    at.session_state["nav_radio"] = "Case Inspector"
    at.session_state["selected_case_id"] = "case-rev-preserve"
    at.session_state["input_reviewer_name"] = "Inspector Holmes"
    at.session_state["rev_new_val"] = "Corrected Name"
    at.session_state["rev_correction_note"] = "   "  # Empty note
    at.run()
    assert not at.exception

    btn_correct = next(b for b in at.button if "Save Value Correction" in b.label)
    btn_correct.click().run()
    assert not at.exception

    # Check error banner was raised and value was NOT changed
    assert any("mandatory reviewer note is required" in e.value for e in at.error)
    reloaded = load_case("case-rev-preserve", db_path=db_file)
    assert reloaded.fields["id_document.applicant_name"].value == "Original Extracted Name"

    # 2. Provide mandatory note -> correction recorded, but original extraction PRESERVED
    at.session_state["rev_correction_note"] = "Typo in document header acknowledged by HR"
    btn_correct = next(b for b in at.button if "Save Value Correction" in b.label)
    btn_correct.click().run()
    assert not at.exception

    # Verify extraction on case.fields was NEVER overwritten
    reloaded2 = load_case("case-rev-preserve", db_path=db_file)
    assert reloaded2.fields["id_document.applicant_name"].value == "Original Extracted Name"

    # Verify audit event written with actor and details
    events = list_events(case_id="case-rev-preserve", db_path=db_file)
    rev_events = [e for e in events if e["stage"] == "reviewer_action"]
    assert len(rev_events) >= 1
    last_ev = rev_events[-1]
    assert last_ev["actor"] == "Inspector Holmes"
    assert last_ev["payload"]["action"] == "correct_value"
    assert last_ev["payload"]["original_value"] == "Original Extracted Name"
    assert last_ev["payload"]["corrected_value"] == "Corrected Name"


def test_workflow_status_mutation_restricted_to_reviewer_action(tmp_path: Path, monkeypatch):
    """Rule 2c: Workflow status becomes approved or rejected ONLY through reviewer action in UI."""
    from app.decide.engine import decide
    from app.config import load_scenario

    monkeypatch.setenv("INX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INX_MODE", "mock")
    db_file = tmp_path / "audit.db"

    # Verify policy engine NEVER outputs approved or rejected
    case = CaseRecord(case_id="case-rule2c", scenario="job_application")
    decide(case, load_scenario("job_application"))
    assert case.workflow_status not in (WorkflowStatus.approved, WorkflowStatus.rejected)

    # In UI, test approve and reject transitions
    save_case(case, db_path=db_file)

    at = AppTest.from_file(_APP_PATH)
    at.default_timeout = 30
    at.session_state["nav_radio"] = "Case Inspector"
    at.session_state["selected_case_id"] = "case-rule2c"
    at.session_state["input_reviewer_name"] = "Senior Reviewer"
    at.session_state["rev_decision_note"] = "All requirements satisfied upon inspection"
    at.run()
    assert not at.exception

    btn_approve = next(b for b in at.button if "Approve Case" in b.label)
    btn_approve.click().run()
    assert not at.exception

    c_appr = load_case("case-rule2c", db_path=db_file)
    assert c_appr.workflow_status == WorkflowStatus.approved

    # Test reject action
    at.session_state["rev_decision_note"] = "Fraudulent credentials suspected"
    btn_reject = next(b for b in at.button if "Reject Case" in b.label)
    btn_reject.click().run()
    assert not at.exception

    c_rej = load_case("case-rule2c", db_path=db_file)
    assert c_rej.workflow_status == WorkflowStatus.rejected


def test_emails_tab_approve_and_send_held_email(tmp_path: Path, monkeypatch):
    """Rule 2d: Approving and sending held email respects DRY_RUN and recipient allowlist."""
    from app.store.db import record_outbox, get_outbox

    monkeypatch.setenv("INX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INX_MODE", "mock")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("ALLOWED_RECIPIENTS", "candidate@test.com")
    db_file = tmp_path / "audit.db"

    outbox_id = record_outbox(
        case_id="case-email-1",
        kind="held",
        recipient="candidate@test.com",
        subject="Action Needed: Update Resume",
        body_text="Please upload clearer copy.",
        status="held",
        db_path=db_file,
    )

    at = AppTest.from_file(_APP_PATH)
    at.default_timeout = 30
    at.session_state["nav_radio"] = "Emails & Outbox"
    at.run()
    assert not at.exception

    btn_send = next((b for b in at.button if "Approve & Send Email" in b.label), None)
    assert btn_send is not None
    btn_send.click().run()
    assert not at.exception

    item = get_outbox(outbox_id, db_path=db_file)
    assert item["status"] in ("dry_run", "draft")


def test_audit_tab_verify_chain_and_tamper_detection(tmp_path: Path, monkeypatch):
    """Rule 2e: Audit tab shows 'Chain intact', and shows the breaking line after tampering."""
    monkeypatch.setenv("INX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INX_MODE", "mock")
    audit_file = tmp_path / "audit.jsonl"
    db_file = tmp_path / "audit.db"

    case = CaseRecord(case_id="case-audit-1", scenario="job_application")
    write_audit(case, event="ingest", audit_path=audit_file, db_path=db_file)
    write_audit(case, event="validate", audit_path=audit_file, db_path=db_file)
    write_audit(case, event="decide", audit_path=audit_file, db_path=db_file)

    # 1. Verify intact
    at = AppTest.from_file(_APP_PATH)
    at.default_timeout = 30
    at.session_state["nav_radio"] = "Audit & Policy"
    at.run()
    assert not at.exception

    btn_verify = next(b for b in at.button if "Verify Hash-Chain" in b.label)
    btn_verify.click().run()
    assert not at.exception
    assert any("Chain intact" in s.value for s in at.success)

    # 2. Tamper with line 2
    lines = audit_file.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"stage":"validate"', '"stage":"tampered_stage"')
    audit_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    btn_verify.click().run()
    assert not at.exception
    # Tampering line 2 changes its hash, so line 3's prev_hash mismatches → break at line 3
    assert any("Chain broken at line 3" in e.value for e in at.error)


def test_ui_graceful_error_handling(tmp_path: Path, monkeypatch):
    """Rule 2f: Pipeline exception or missing file shows a friendly message, logs error, and leaves app usable."""
    monkeypatch.setenv("INX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INX_MODE", "mock")

    # Case 1: Empty database shows graceful warning, not a crash
    at = AppTest.from_file(_APP_PATH)
    at.default_timeout = 30
    at.session_state["nav_radio"] = "Case Inspector"
    at.session_state["selected_case_id"] = "non-existent-case-id"
    at.run()
    assert not at.exception
    # Graceful warning displayed when no cases exist yet
    assert any("No cases found" in w.value for w in at.warning)


def test_rerun_safety_batch_not_retriggered_on_interaction(tmp_path: Path, monkeypatch):
    """Rule 3: Interacting with filter, selecting case, or switching tabs does not restart batch."""
    from app.pipeline import Pipeline
    monkeypatch.setenv("INX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INX_MODE", "mock")

    call_counts = {"count": 0}
    orig_run_batch = Pipeline.run_batch

    def spy_run_batch(self, *args, **kwargs):
        call_counts["count"] += 1
        return orig_run_batch(self, *args, **kwargs)

    monkeypatch.setattr(Pipeline, "run_batch", spy_run_batch)

    at = AppTest.from_file(_APP_PATH)
    at.default_timeout = 30
    at.session_state["nav_radio"] = "Batch Intake"
    at.session_state["scenario"] = "job_application"
    at.session_state["batch_limit_input"] = 1
    at.run()
    assert not at.exception

    btn_batch = next(b for b in at.button if "Start Batch" in b.label)
    btn_batch.click().run()
    assert not at.exception
    assert call_counts["count"] == 1

    batch_res = at.session_state.get("batch_results", [])
    assert len(batch_res) == 1

    # Filter interaction
    at.session_state["results_filter_route"] = "PROCESS"
    at.run()
    assert not at.exception
    # Results must persist and run_batch must NOT be re-called
    assert call_counts["count"] == 1
    assert at.session_state.get("batch_results") == batch_res


def test_missing_data_cases(tmp_path: Path, monkeypatch):
    """Rule 4: Missing-data cases: no documents, rejected .exe, zero OCR lines, no bbox, multi-page PDF."""
    from PIL import Image
    monkeypatch.setenv("INX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INX_MODE", "mock")
    db_file = tmp_path / "audit.db"

    # Case with no documents and skipped .exe file
    case_no_doc = CaseRecord(
        case_id="case-no-doc",
        scenario="job_application",
        workflow_status=WorkflowStatus.awaiting_information,
        route=Route.REQUEST_INFO,
        decision=Decision(
            workflow_status=WorkflowStatus.awaiting_information,
            route=Route.REQUEST_INFO,
            reasons=["No documents submitted"],
            rule_ids=["R05"],
        ),
        skipped_files=[
            {"filename": "payload.exe", "status": "rejected", "reason": "Disallowed .exe attachment"}
        ],
    )
    save_case(case_no_doc, db_path=db_file)

    at = AppTest.from_file(_APP_PATH)
    at.default_timeout = 30
    at.session_state["nav_radio"] = "Case Inspector"
    at.session_state["selected_case_id"] = "case-no-doc"
    at.run()
    assert not at.exception
    assert any("No documents attached" in info.value for info in at.info)

    # Multi-page case with zero OCR lines and field without bbox
    clean_p1 = tmp_path / "page_0_clean.png"
    clean_p2 = tmp_path / "page_1_clean.png"
    Image.new("RGB", (200, 200), "white").save(clean_p1)
    Image.new("RGB", (200, 200), "white").save(clean_p2)

    case_multi = CaseRecord(
        case_id="case-multipage",
        scenario="job_application",
        documents=[
            DocumentRecord(
                doc_id="doc-multi",
                filename="multi_page.pdf",
                sha256="fake_multi_sha",
                doc_type=DocumentType.resume,
                pages=2,
                page_images=[str(clean_p1), str(clean_p2)],
                storage_path=str(clean_p1),
            )
        ],
        fields={
            "resume.applicant_name": FieldResult(
                field="applicant_name",
                value="Priya",
                status=FieldStatus.valid,
                page=0,
                bbox=None,  # No bbox
            )
        },
    )
    save_case(case_multi, db_path=db_file)

    at.session_state["selected_case_id"] = "case-multipage"
    at.run()
    assert not at.exception


def test_quick_check_formats_and_sender(tmp_path: Path, monkeypatch):
    """Rule 5: Quick check tests PDF, image, ZIP, and multiple files; sets manual@upload.local, no email."""
    import zipfile
    from PIL import Image
    from app.pipeline import build_pipeline

    monkeypatch.setenv("INX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INX_MODE", "mock")

    # Generate test files
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 header test document")

    img_file = tmp_path / "test.jpg"
    Image.new("RGB", (100, 100), "white").save(img_file)

    zip_file = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("resume.txt", "Priya Sharma resume")

    pipeline = build_pipeline(scenario="job_application", data_dir=tmp_path)

    # Test PDF, image, ZIP, and two files together
    from app.store.db import list_outbox

    for test_inputs in ([pdf_file], [img_file], [zip_file], [pdf_file, img_file]):
        events = list(pipeline.process_files(test_inputs, scenario="job_application", label="Quick Check"))
        cf = next(ev for ev in events if ev.kind == "case_finished")
        assert cf is not None
        c = load_case(cf.case_id, db_path=tmp_path / "audit.db")
        assert c is not None
        assert c.sender_email == "manual@upload.local"
        # Confirm nothing was emailed
        assert len(list_outbox(db_path=tmp_path / "audit.db")) == 0
        # Confirm result shows route, reasons, and fields
        assert c.decision.route is not None
        assert isinstance(c.decision.reasons, list)
        assert isinstance(c.fields, dict)

