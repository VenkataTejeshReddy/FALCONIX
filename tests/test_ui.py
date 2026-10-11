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
