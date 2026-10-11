# Owner: Laptop B
"""Unit tests for notification system: drafter, sender, outbox, and polish."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from app.notify.drafter import (
    AUTO_SEND_KINDS,
    HOLD_KINDS,
    INTERNAL_KINDS,
    classify_email_action,
    draft_email,
)
from app.notify.polish import polish_notification, validate_polished_text
from app.notify.sender import (
    allowed_recipients,
    get_recipient,
    is_dry_run,
    send_email,
    send_notifications,
)
from app.schemas import (
    CaseRecord,
    Decision,
    DocumentRecord,
    DocumentType,
    FieldResult,
    FieldStatus,
    Issue,
    IssueKind,
    Route,
    WorkflowStatus,
)
from app.store.db import (
    get_outbox,
    list_events,
    list_outbox,
    record_outbox,
    release_held,
    update_outbox_status,
)


def _make_case(
    case_id: str = "case-abc",
    route: Route = Route.PROCESS,
    sender_name: str = "Priya Sharma",
    sender_email: str = "priya@example.com",
    issues: list[Issue] | None = None,
) -> CaseRecord:
    case = CaseRecord(
        case_id=case_id,
        scenario="college",
        sender_name=sender_name,
        sender_email=sender_email,
        workflow_status=WorkflowStatus.verified,
        route=route,
        decision=Decision(
            workflow_status=WorkflowStatus.verified,
            route=route,
            reasons=["Routing based on evaluation"],
            rule_ids=["R1"],
        ),
        issues=issues or [],
    )
    return case


def test_email_policy_mapping_for_all_issue_kinds():
    """Verify auto vs held vs none classification for every issue kind."""
    # Auto-send issue kinds
    for kind in AUTO_SEND_KINDS:
        c = _make_case(
            route=Route.REQUEST_INFO,
            issues=[Issue(field="f", kind=kind, detail="test auto")],
        )
        assert classify_email_action(c) == "auto", f"Kind {kind} should be auto"

    # Hold issue kinds
    for kind in HOLD_KINDS:
        c = _make_case(
            route=Route.HUMAN_REVIEW,
            issues=[Issue(field="f", kind=kind, detail="test hold")],
        )
        assert classify_email_action(c) == "held", f"Kind {kind} should be held"

    # Mixed issues with at least one hold kind -> held
    mixed = _make_case(
        route=Route.HUMAN_REVIEW,
        issues=[
            Issue(field="f1", kind=IssueKind.missing, detail="missing f1"),
            Issue(field="f2", kind=IssueKind.conflict, detail="conflict f2"),
        ],
    )
    assert classify_email_action(mixed) == "held"

    # Format failure triggers hold
    fmt_case = _make_case(
        route=Route.HUMAN_REVIEW,
        issues=[
            Issue(field="id_number", kind=IssueKind.unreliable, detail="Invalid checksum on ID"),
        ],
    )
    assert classify_email_action(fmt_case) == "held"

    # Internal kinds only -> none
    internal_case = _make_case(
        route=Route.HUMAN_REVIEW,
        issues=[
            Issue(field="file", kind=IssueKind.duplicate_file, detail="dup file"),
        ],
    )
    assert classify_email_action(internal_case) == "none"

    # Manual upload sender -> none
    manual_case = _make_case(
        route=Route.REQUEST_INFO,
        sender_email="manual@upload.local",
        issues=[Issue(field="f", kind=IssueKind.missing, detail="missing")],
    )
    assert classify_email_action(manual_case) == "none"


def test_recipient_resolution():
    """Verify recipient resolution and exclusion of manual@upload.local."""
    c1 = _make_case(sender_email="user@test.com")
    assert get_recipient(c1) == "user@test.com"

    c2 = _make_case(sender_email="manual@upload.local")
    assert get_recipient(c2) == ""

    c3 = _make_case(sender_email="")
    assert get_recipient(c3) == ""


def test_dry_run_never_sends_email(monkeypatch, tmp_path: Path):
    """With DRY_RUN=true (default), emails are stored in outbox with status dry_run and not sent."""
    monkeypatch.setenv("DRY_RUN", "true")
    db_path = tmp_path / "test_audit.db"

    case = _make_case(
        case_id="case-dry-1",
        route=Route.REQUEST_INFO,
        issues=[Issue(field="degree", kind=IssueKind.missing_document, detail="degree missing")],
    )

    status = send_notifications(case, db_path=db_path)
    assert status == "dry_run"

    outbox = list_outbox(case_id="case-dry-1", db_path=db_path)
    assert len(outbox) == 1
    assert outbox[0]["status"] == "dry_run"
    assert outbox[0]["kind"] == "auto"
    assert "degree" in outbox[0]["body_text"]


def test_allowlist_blocks_unauthorized_recipients(monkeypatch):
    """With DRY_RUN=false, recipients not in ALLOWED_RECIPIENTS are blocked."""
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("ALLOWED_RECIPIENTS", "allowed@test.com, admin@test.com")

    # Allowed recipient passes allowlist check (will try smtp and fail gracefully or raise depending on host)
    assert allowed_recipients() == {"allowed@test.com", "admin@test.com"}

    # Unauthorized recipient raises ValueError
    with pytest.raises(ValueError, match="not in ALLOWED_RECIPIENTS"):
        send_email(
            to_address="unauthorized@test.com",
            subject="Test",
            plain_body="Hello",
        )


def test_outbox_crud_and_release_held(tmp_path: Path):
    """Outbox table stores held messages, allows reviewer release, and appends audit events."""
    db_path = tmp_path / "test_audit.db"

    outbox_id = record_outbox(
        case_id="case-held-1",
        kind="held",
        recipient="held@example.com",
        subject="Action Required",
        body_text="Details on hold",
        status="held",
        db_path=db_path,
    )
    assert outbox_id > 0

    item = get_outbox(outbox_id, db_path=db_path)
    assert item is not None
    assert item["status"] == "held"

    # List held
    held_items = list_outbox(status="held", db_path=db_path)
    assert len(held_items) == 1
    assert held_items[0]["outbox_id"] == outbox_id

    # Release held
    release_held(outbox_id, approved_by="senior_reviewer", db_path=db_path)

    updated = get_outbox(outbox_id, db_path=db_path)
    assert updated["status"] == "draft"
    assert updated["approved_by"] == "senior_reviewer"

    # Verify audit events
    events = list_events(case_id="case-held-1", db_path=db_path)
    stages = [e["stage"] for e in events]
    assert "outbox_recorded" in stages
    assert "outbox_status_changed" in stages


class FakeModelClient:
    """Fake model client for notification polish testing."""

    def __init__(self, response_text: str):
        self.response_text = response_text

    def generate(self, prompt: str) -> str:
        return self.response_text


def test_polish_notification_faithful_vs_hallucinated():
    """Polish rewriting succeeds on faithful rewrites and falls back on hallucinated facts."""
    case = _make_case(
        case_id="case-pol-1",
        route=Route.REQUEST_INFO,
        sender_name="Priya Sharma",
        issues=[
            Issue(field="transcript", kind=IssueKind.missing_document, detail="Official transcript required", doc="transcript"),
        ],
    )

    subj, plain, html = draft_email(case)

    # 1. Faithful model response (covers transcript, no invented numbers/fields)
    faithful_client = FakeModelClient(
        "Dear Priya Sharma,\n\n"
        "Thank you for submitting your application. We noticed that your transcript is missing. "
        "Please provide your transcript at your earliest convenience.\n\n"
        "Reference: case-pol-1\n"
        "INX Admissions Team"
    )
    p_subj, p_plain, p_html = polish_notification(subj, plain, html, case, client=faithful_client)
    assert "transcript" in p_plain
    assert "Priya Sharma" in p_plain

    # 2. Hallucinated number (e.g. invented bank account or score 9876543) -> fallback to template
    hallucinated_client = FakeModelClient(
        "Dear Priya Sharma,\n\n"
        "Please send your transcript and deposit $9876543 to account 445566.\n\n"
        "Reference: case-pol-1"
    )
    fb_subj, fb_plain, fb_html = polish_notification(subj, plain, html, case, client=hallucinated_client)
    assert fb_plain == plain  # Exactly fell back to original draft

    # 3. Missing required issue mention -> fallback to template
    missing_issue_client = FakeModelClient(
        "Dear Priya Sharma,\n\n"
        "Everything looks okay, just contact us.\n\n"
        "Reference: case-pol-1"
    )
    fb_subj2, fb_plain2, fb_html2 = polish_notification(subj, plain, html, case, client=missing_issue_client)
    assert fb_plain2 == plain
