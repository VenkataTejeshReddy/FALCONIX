# Owner: Laptop B
"""INX – Tests: intake (email_import and case_builder).

Verifies all email intake edge cases against the full scenario mailboxes
(fixtures/mail/job_applications.mbox and college_applications.mbox).
"""

from __future__ import annotations

import email.message
import io
import mailbox
import zipfile
from pathlib import Path

import pytest

from app.intake.case_builder import (
    build_case,
    build_cases_from_source,
    count_cases,
    iter_cases_from_source,
)
from app.intake.email_import import (
    count_emails,
    import_source,
    iter_messages,
    iter_parsed_emails,
    sanitize_filename,
)
from app.schemas import CaseRecord, WorkflowStatus
from tests.helpers import make_doc_image

# Canonical fixture mailboxes
_REPO_ROOT = Path(__file__).resolve().parent.parent
_JOB_MBOX = _REPO_ROOT / "fixtures" / "mail" / "job_applications.mbox"
_COL_MBOX = _REPO_ROOT / "fixtures" / "mail" / "college_applications.mbox"


@pytest.fixture(scope="module")
def job_mbox() -> Path:
    assert _JOB_MBOX.exists(), "Run `python scripts/make_mbox.py` to generate mailboxes."
    return _JOB_MBOX


@pytest.fixture(scope="module")
def col_mbox() -> Path:
    assert _COL_MBOX.exists(), "Run `python scripts/make_mbox.py` to generate mailboxes."
    return _COL_MBOX


def test_upfront_count_reporting(job_mbox: Path, tmp_path: Path):
    """Verify count_emails and count_cases report total emails up front."""
    total = count_emails(job_mbox)
    assert total == 22, f"Expected 22 emails in job_applications.mbox, got {total}"
    assert count_cases(job_mbox) == 22

    # For an individual .eml file
    msg = email.message.EmailMessage()
    msg["From"] = '"Test" <t@example.com>'
    msg["Subject"] = "S"
    msg["Message-ID"] = "<upfront-count-test@example.com>"
    msg.set_content("body")
    eml_path = tmp_path / "single.eml"
    eml_path.write_bytes(msg.as_bytes())
    assert count_emails(eml_path) == 1
    assert count_cases(eml_path) == 1


def test_sanitize_filename_prevents_traversal():
    """Verify sanitize_filename strips directory traversal and dangerous characters."""
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\windows\\system32\\calc.exe") == "calc.exe"
    assert sanitize_filename("folder/subfolder/doc.pdf") == "doc.pdf"
    assert sanitize_filename("C:\\Users\\Admin\\secret.docx") == "secret.docx"
    assert sanitize_filename("") == "attachment_1.bin"
    assert sanitize_filename(None, index=5) == "attachment_5.bin"
    assert sanitize_filename("   ...   ", index=3) == "attachment_3.bin"


def test_deduplication_by_message_id(job_mbox: Path):
    """Verify duplicate Message-ID is dropped during intake.

    The job mailbox has 22 messages; cases 14 and 15 share the same Message-ID,
    so exactly 21 unique cases should be parsed.
    """
    parsed = list(iter_parsed_emails(job_mbox))
    assert len(parsed) == 21, f"Expected 21 unique emails after dedup, got {len(parsed)}"

    msg_ids = [p.message_id for p in parsed]
    assert len(msg_ids) == len(set(msg_ids)), "Duplicate Message-IDs found after deduplication"

    # The shared ID should appear exactly once
    shared_id = "job-shared-duplicate-msg-id@falconix.test"
    assert msg_ids.count(shared_id) == 1


def test_complete_bundle_is_processed(job_mbox: Path, tmp_path: Path):
    """Edge Case 1: Complete bundle (resume + id) produces ingested documents."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(job_mbox, scenario="job_application", data_dir=data_dir)

    # Case 01 is the complete bundle from Rohan Verma
    case = cases[0]
    assert case.sender_name == "Rohan Verma"
    assert case.sender_email == "rohan.verma@example.com"
    assert case.subject == "Job Application – Senior Engineer"
    assert case.workflow_status == WorkflowStatus.received

    # Both resume.pdf and id_card.jpg are ingested
    filenames = {d.filename for d in case.documents}
    assert "resume.pdf" in filenames
    assert "id_card.jpg" in filenames


def test_email_with_zip_attachment(job_mbox: Path, tmp_path: Path):
    """Edge Case 11: ZIP attachment is transparently expanded and ingested."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(job_mbox, scenario="job_application", data_dir=data_dir)

    # Case 11 (index 10) is the ZIP email from Pooja Hegde
    case = cases[10]
    assert case.sender_name == "Pooja Hegde"
    assert len(case.documents) == 2
    filenames = {d.filename for d in case.documents}
    assert "resume.pdf" in filenames
    assert "id.jpg" in filenames


def test_email_with_no_attachments(job_mbox: Path, tmp_path: Path):
    """Edge Case 12: Email with no attachments does not crash, records a note."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(job_mbox, scenario="job_application", data_dir=data_dir)

    # Case 12 (index 11) is the no-attachment email from Alok Kumar
    case = cases[11]
    assert case.sender_name == "Alok Kumar"
    assert len(case.documents) == 0
    assert any("no attachments" in note.lower() or "no documents" in note.lower()
               for note in case.intake_notes)


def test_email_with_unsupported_attachment(job_mbox: Path, tmp_path: Path):
    """Edge Case 13: .exe attachment is rejected and recorded in skipped_files."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(job_mbox, scenario="job_application", data_dir=data_dir)

    # Case 13 (index 12) is the .exe-only email
    case = cases[12]
    assert len(case.documents) == 0
    assert len(case.skipped_files) >= 1
    skipped_fnames = [sf["filename"] for sf in case.skipped_files]
    assert any("installer.exe" in name for name in skipped_fnames)


def test_eml_single_file_import(tmp_path: Path):
    """Verify single .eml file can be imported directly."""
    eml_file = tmp_path / "single.eml"
    msg = email.message.EmailMessage()
    msg["From"] = '"Aarav Sharma" <aarav@example.com>'
    msg["To"] = "apply@falconix.edu"
    msg["Subject"] = "Single EML Test"
    msg["Message-ID"] = "<single-test-123@example.com>"
    msg.set_content("Single EML application body")

    doc_img = tmp_path / "my_id.png"
    make_doc_image(doc_img, seed=99)
    msg.add_attachment(
        doc_img.read_bytes(), maintype="image", subtype="png", filename="my_id.png"
    )
    eml_file.write_bytes(msg.as_bytes())

    data_dir = tmp_path / "data"
    cases = import_source(eml_file, scenario="job_application", data_dir=data_dir)
    assert len(cases) == 1
    case = cases[0]
    assert case.sender_name == "Aarav Sharma"
    assert case.sender_email == "aarav@example.com"
    assert len(case.documents) == 1
    assert case.documents[0].filename == "my_id.png"


def test_lazy_streaming(job_mbox: Path, tmp_path: Path):
    """Verify iter_cases_from_source yields cases one by one lazily."""
    data_dir = tmp_path / "data"
    stream = iter_cases_from_source(job_mbox, scenario="job_application", data_dir=data_dir)
    first_case = next(stream)
    assert isinstance(first_case, CaseRecord)
    # First unique case is Rohan Verma (case 01)
    assert first_case.sender_email == "rohan.verma@example.com"


def test_same_documents_from_two_senders(job_mbox: Path, tmp_path: Path):
    """Cases 16 & 17: same files from different senders — 17 should flag duplicate_file."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(job_mbox, scenario="job_application", data_dir=data_dir)

    # Case 16 (Candidate Alpha) — original, 2 docs
    case_alpha = cases[14]   # after dedup: 14 unique cases before case 16
    assert case_alpha.sender_name == "Candidate Alpha"
    assert len(case_alpha.documents) == 2

    # Case 17 (Candidate Beta) — same files, should have is_duplicate=True docs
    case_beta = cases[15]
    assert case_beta.sender_name == "Candidate Beta"
    assert any(d.is_duplicate for d in case_beta.documents)


def test_mislabeled_attachment(job_mbox: Path, tmp_path: Path):
    """Case 18: file named marksheet.pdf that is really an ID card — documents ingested."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(job_mbox, scenario="job_application", data_dir=data_dir)

    case = cases[16]
    assert case.sender_name == "Manish Malhotra"
    filenames = {d.filename for d in case.documents}
    assert "marksheet.pdf" in filenames  # accepted but mislabeled


def test_neutral_attachment_names(job_mbox: Path, tmp_path: Path):
    """Case 19: neutral names (scan001.pdf, IMG_2041.jpg) are ingested without errors."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(job_mbox, scenario="job_application", data_dir=data_dir)

    case = cases[17]
    assert case.sender_name == "Aditi Sharma"
    filenames = {d.filename for d in case.documents}
    assert "scan001.pdf" in filenames
    assert "IMG_2041.jpg" in filenames


def test_hard_variants_in_mailbox(job_mbox: Path, tmp_path: Path):
    """Case 21: 3 hard augmented variants are ingested from mailbox."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(job_mbox, scenario="job_application", data_dir=data_dir)

    case = cases[19]
    assert case.sender_name == "Harish Patel"
    assert len(case.documents) == 3
    filenames = {d.filename for d in case.documents}
    assert "tilted_resume.jpg" in filenames
    assert "perspective_id.jpg" in filenames
    assert "scanned_yellow.jpg" in filenames
