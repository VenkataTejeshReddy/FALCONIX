# Owner: Laptop B
"""INX – Tests: synthetic data fixture integrity and determinism.

Verifies:
1. Generators are deterministic (fixed seeds, identical bytes across runs).
2. Every file named in ground_truth.json exists.
3. Every file named in expected_outcomes.json exists.
4. Every email in the mailboxes has an expectation in expected_outcomes.json.
5. Ground truth schemas conform to contracts.
"""

from __future__ import annotations

import hashlib
import json
import mailbox
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SYNTHETIC_DIR = _REPO_ROOT / "fixtures" / "synthetic_docs"
_HARD_DIR = _SYNTHETIC_DIR / "hard"
_MAIL_DIR = _REPO_ROOT / "fixtures" / "mail"


@pytest.fixture(scope="module")
def ground_truth() -> dict:
    gt_path = _SYNTHETIC_DIR / "ground_truth.json"
    assert gt_path.exists(), f"ground_truth.json not found at {gt_path}"
    with open(gt_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected_outcomes() -> dict:
    eo_path = _SYNTHETIC_DIR / "expected_outcomes.json"
    assert eo_path.exists(), f"expected_outcomes.json not found at {eo_path}"
    with open(eo_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_every_file_named_in_ground_truth_exists(ground_truth: dict):
    """Every document listed in ground_truth.json must physically exist."""
    assert len(ground_truth) > 0
    for filename, entry in ground_truth.items():
        p1 = _SYNTHETIC_DIR / filename
        p2 = _HARD_DIR / filename
        assert p1.exists() or p2.exists(), f"File in ground_truth.json does not exist: {filename}"
        assert "true_fields" in entry
        assert "defect" in entry
        assert "details" in entry


def test_every_file_named_in_expected_outcomes_exists(expected_outcomes: dict):
    """Every document listed in expected_outcomes.json must physically exist."""
    docs = expected_outcomes.get("documents", {})
    assert len(docs) > 0
    for filename in docs:
        p1 = _SYNTHETIC_DIR / filename
        p2 = _HARD_DIR / filename
        assert p1.exists() or p2.exists(), f"Document in expected_outcomes.json does not exist: {filename}"


def test_every_email_in_mailboxes_has_expectation(expected_outcomes: dict):
    """Every email in job_applications.mbox and college_applications.mbox must have an expectation."""
    emails_exp = expected_outcomes.get("emails", {})
    assert len(emails_exp) > 0

    mailboxes = [
        _MAIL_DIR / "job_applications.mbox",
        _MAIL_DIR / "college_applications.mbox",
    ]

    for mbox_path in mailboxes:
        assert mbox_path.exists(), f"Mailbox file missing: {mbox_path}"
        mbox = mailbox.mbox(str(mbox_path))
        try:
            assert len(mbox) > 0, f"Mailbox {mbox_path} is empty"
            for msg in mbox:
                msg_id = msg.get("Message-ID", "").strip("<> ").strip()
                assert msg_id, f"Email missing Message-ID header in {mbox_path}"
                assert msg_id in emails_exp, f"Email with Message-ID <{msg_id}> missing from expected_outcomes.json"

                exp = emails_exp[msg_id]
                assert "expected_workflow_status" in exp
                assert "expected_route" in exp
                assert "expected_issue_kinds" in exp
                assert isinstance(exp["expected_issue_kinds"], list)
                assert exp["expected_route"] in ["PROCESS", "REQUEST_INFO", "MANUAL_VERIFICATION", "HUMAN_REVIEW"]
        finally:
            mbox.close()


def test_generators_are_deterministic(tmp_path: Path):
    """Generators must produce deterministic, identical outputs when run with fixed seeds."""
    from scripts.augment_docs import generate_all_hard_variants
    from scripts.make_synthetic_docs import generate_all_synthetic_docs

    temp_out_1 = tmp_path / "run1"
    temp_out_2 = tmp_path / "run2"

    gt1, out1 = generate_all_synthetic_docs(temp_out_1)
    gt2, out2 = generate_all_synthetic_docs(temp_out_2)

    # Ground truth contents identical
    assert gt1 == gt2

    # Binary files identical
    sample_files = [
        "job_normal_resume.pdf",
        "job_normal_id.jpg",
        "hard/hard_tilted_resume.jpg",
        "hard/hard_shadow_marksheet.jpg",
    ]
    for rel_path in sample_files:
        f1 = temp_out_1 / rel_path
        f2 = temp_out_2 / rel_path
        assert f1.exists() and f2.exists(), f"File missing in deterministic test: {rel_path}"
        h1 = hashlib.sha256(f1.read_bytes()).hexdigest()
        h2 = hashlib.sha256(f2.read_bytes()).hexdigest()
        assert h1 == h2, f"Generator output is non-deterministic for {rel_path}"
