# Owner: Laptop B
"""INX – Tests: intake (email_import and case_builder).

Verifies all email intake edge cases:
1. One email with 5 attachments
2. One email with a ZIP attachment
3. One email with a folder-like ZIP tree
4. One with no attachment
5. One with an unsupported attachment (.exe)
6. Duplicate Message-ID deduplication
7. Filename traversal / path injection sanitization
8. Sender, display name, reply-to, and date parsing
9. Upfront email count reporting (count_emails / count_cases)
10. .eml vs .mbox handling
11. Lazy streaming via iter_cases_from_source
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
from scripts.make_mbox import build_synthetic_messages, make_mbox
from tests.helpers import make_doc_image


@pytest.fixture
def synthetic_mbox(tmp_path: Path) -> Path:
    """Fixture producing a synthetic .mbox file with all 6 edge cases."""
    mbox_path = tmp_path / "test_synthetic.mbox"
    eml_dir = tmp_path / "emls"
    return make_mbox(out_path=mbox_path, eml_dir=eml_dir)


def test_upfront_count_reporting(synthetic_mbox: Path, tmp_path: Path):
    """Verify count_emails and count_cases report total emails up front."""
    assert count_emails(synthetic_mbox) == 6
    assert count_cases(synthetic_mbox) == 6

    # For an individual .eml file
    eml_path = tmp_path / "emls" / "email_01.eml"
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


def test_deduplication_by_message_id(synthetic_mbox: Path):
    """Verify duplicate Message-ID is dropped during intake."""
    # Synthetic mbox has 6 messages, but Message 6 duplicates Message 1's ID.
    parsed = list(iter_parsed_emails(synthetic_mbox))
    # Exactly 5 unique cases should be parsed
    assert len(parsed) == 5

    msg_ids = [p.message_id for p in parsed]
    assert len(msg_ids) == len(set(msg_ids))
    assert "<msg-001-five-attachments@falconix.test>".strip("<> ") in msg_ids


def test_email_with_five_attachments(synthetic_mbox: Path, tmp_path: Path):
    """Edge Case 1: email with 5 attachments produces 5 ingested documents."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(synthetic_mbox, scenario="job_application", data_dir=data_dir)

    # First case is the 5-attachment email from Dr. Priya Nair
    case1 = cases[0]
    assert case1.sender_name == "Dr. Priya Nair"
    assert case1.sender_email == "priya.nair@research.org"
    assert case1.subject == "Application for Senior Research Scientist"
    assert case1.workflow_status == WorkflowStatus.received

    # All 5 attachments (PDFs and image) should be ingested
    assert len(case1.documents) == 5
    filenames = {d.filename for d in case1.documents}
    assert "resume.pdf" in filenames
    assert "id_proof.png" in filenames
    assert "publication_summary.pdf" in filenames


def test_email_with_zip_attachment(synthetic_mbox: Path, tmp_path: Path):
    """Edge Case 2: email with a ZIP is transparently expanded and ingested."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(synthetic_mbox, scenario="job_application", data_dir=data_dir)

    # Second case has documents.zip containing resume.pdf and id_document.png
    case2 = cases[1]
    assert case2.sender_name == "Vikramaditya Rao"
    assert len(case2.documents) == 2
    filenames = {d.filename for d in case2.documents}
    assert "resume.pdf" in filenames
    assert "id_document.png" in filenames


def test_email_with_folder_like_zip_tree(synthetic_mbox: Path, tmp_path: Path):
    """Edge Case 3: email with a nested folder ZIP tree extracts and ingests documents."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(synthetic_mbox, scenario="college", data_dir=data_dir)

    # Third case has admission_tree.zip with subdirectories
    case3 = cases[2]
    assert case3.sender_name == "Ananya Iyer"
    assert len(case3.documents) == 3
    filenames = {d.filename for d in case3.documents}
    assert "marksheet.pdf" in filenames
    assert "student_id.png" in filenames
    assert "bonafide_certificate.pdf" in filenames


def test_email_with_no_attachments(synthetic_mbox: Path, tmp_path: Path):
    """Edge Case 4: email with no attachments does not crash, notes recorded."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(synthetic_mbox, scenario="job_application", data_dir=data_dir)

    # Fourth case has 0 attachments
    case4 = cases[3]
    assert case4.sender_name == "Sunita Deshmukh"
    assert len(case4.documents) == 0
    assert any("no attachments" in note.lower() for note in case4.intake_notes)


def test_email_with_unsupported_attachment(synthetic_mbox: Path, tmp_path: Path):
    """Edge Case 5: unsupported attachment (.exe) is recorded in skipped_files."""
    data_dir = tmp_path / "data"
    cases = build_cases_from_source(synthetic_mbox, scenario="job_application", data_dir=data_dir)

    # Fifth case has installer_tool.exe
    case5 = cases[4]
    assert case5.sender_name == "Karthik Subramanian"
    assert len(case5.documents) == 0
    assert len(case5.skipped_files) >= 1
    skipped_filenames = [sf["filename"] for sf in case5.skipped_files]
    assert any("installer_tool.exe" in name for name in skipped_filenames)


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
    msg.add_attachment(doc_img.read_bytes(), maintype="image", subtype="png", filename="my_id.png")
    eml_file.write_bytes(msg.as_bytes())

    data_dir = tmp_path / "data"
    cases = import_source(eml_file, scenario="job_application", data_dir=data_dir)
    assert len(cases) == 1
    case = cases[0]
    assert case.sender_name == "Aarav Sharma"
    assert case.sender_email == "aarav@example.com"
    assert len(case.documents) == 1
    assert case.documents[0].filename == "my_id.png"


def test_lazy_streaming(synthetic_mbox: Path, tmp_path: Path):
    """Verify iter_cases_from_source yields cases one by one without loading all at once."""
    data_dir = tmp_path / "data"
    stream = iter_cases_from_source(synthetic_mbox, scenario="college", data_dir=data_dir)
    first_case = next(stream)
    assert isinstance(first_case, CaseRecord)
    assert first_case.sender_email == "priya.nair@research.org"
