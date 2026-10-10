# Owner: Laptop B
"""INX – Script: create a test .mbox file with synthetic emails.

Generates a multi-message .mbox archive and individual .eml files covering:
1. One email with 5 attachments
2. One email with a ZIP
3. One email with a folder-like ZIP tree
4. One with no attachment
5. One with an unsupported attachment
6. One duplicate Message-ID

Different fake senders and display names.
"""

from __future__ import annotations

import argparse
import email.message
import email.utils
import io
import mailbox
import sys
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.helpers import make_doc_image

_DEFAULT_MBOX = _REPO_ROOT / "fixtures" / "synthetic.mbox"
_DEFAULT_EML_DIR = _REPO_ROOT / "fixtures" / "emls"


def _create_minimal_pdf_bytes(title: str = "Document") -> bytes:
    """Create minimal valid PDF bytes using PyMuPDF."""
    import pymupdf as fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), title, fontsize=18)
    page.insert_text((72, 140), "This is a synthetic test document for FALCONIX intake.", fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _create_image_bytes(text: str = "ID CARD", seed: int = 1) -> bytes:
    """Create PNG image bytes using tests.helpers."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "temp.png"
        make_doc_image(p, seed=seed)
        return p.read_bytes()


def _create_zip_bytes(entries: dict[str, bytes]) -> bytes:
    """Create an in-memory ZIP file with given entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def build_synthetic_messages() -> list[email.message.EmailMessage]:
    """Build the 6 synthetic EmailMessage objects representing each edge case."""
    pdf1 = _create_minimal_pdf_bytes("Curriculum Vitae - Dr. Priya Nair")
    pdf2 = _create_minimal_pdf_bytes("Publication Record - Dr. Priya Nair")
    pdf3 = _create_minimal_pdf_bytes("Experience Letter - Research Institute")
    pdf4 = _create_minimal_pdf_bytes("Recommendation - Prof. Sharma")
    id_img = _create_image_bytes("ID Proof - Aadhaar", seed=101)

    messages: list[email.message.EmailMessage] = []

    # -------------------------------------------------------------------------
    # Email 1: 5 Attachments
    # -------------------------------------------------------------------------
    msg1 = email.message.EmailMessage()
    msg1["From"] = '"Dr. Priya Nair" <priya.nair@research.org>'
    msg1["Reply-To"] = '"Dr. Priya Nair" <priya.nair@research.org>'
    msg1["To"] = "admissions@falconix.edu"
    msg1["Subject"] = "Application for Senior Research Scientist"
    msg1["Message-ID"] = "<msg-001-five-attachments@falconix.test>"
    msg1["Date"] = email.utils.formatdate(localtime=True)
    msg1.set_content("Dear Admissions Committee,\n\nPlease find my 5 application documents attached.\n\nBest regards,\nDr. Priya Nair")
    msg1.add_attachment(pdf1, maintype="application", subtype="pdf", filename="resume.pdf")
    msg1.add_attachment(id_img, maintype="image", subtype="png", filename="id_proof.png")
    msg1.add_attachment(pdf2, maintype="application", subtype="pdf", filename="publication_summary.pdf")
    msg1.add_attachment(pdf3, maintype="application", subtype="pdf", filename="experience_letter.pdf")
    msg1.add_attachment(pdf4, maintype="application", subtype="pdf", filename="recommendation.pdf")
    messages.append(msg1)

    # -------------------------------------------------------------------------
    # Email 2: ZIP Attachment
    # -------------------------------------------------------------------------
    msg2 = email.message.EmailMessage()
    msg2["From"] = '"Vikramaditya Rao" <v.rao@techcorp.in>'
    msg2["Reply-To"] = '"Vikramaditya Rao" <v.rao@techcorp.in>'
    msg2["To"] = "jobs@falconix.edu"
    msg2["Subject"] = "Job Application – Software Architect"
    msg2["Message-ID"] = "<msg-002-zip-attachment@falconix.test>"
    msg2["Date"] = email.utils.formatdate(localtime=True)
    msg2.set_content("Hello Team,\n\nAttaching my application bundle in a ZIP archive.\n\nRegards,\nVikramaditya Rao")
    zip_bytes_flat = _create_zip_bytes({
        "resume.pdf": _create_minimal_pdf_bytes("Resume - Vikramaditya Rao"),
        "id_document.png": _create_image_bytes("Gov ID - Vikramaditya", seed=202),
    })
    msg2.add_attachment(zip_bytes_flat, maintype="application", subtype="zip", filename="documents.zip")
    messages.append(msg2)

    # -------------------------------------------------------------------------
    # Email 3: Folder-like ZIP Tree
    # -------------------------------------------------------------------------
    msg3 = email.message.EmailMessage()
    msg3["From"] = '"Ananya Iyer" <ananya.iyer@collegemail.edu>'
    msg3["Reply-To"] = '"Ananya Iyer" <ananya.iyer@collegemail.edu>'
    msg3["To"] = "college-intake@falconix.edu"
    msg3["Subject"] = "College Admission Submission with Folder Hierarchy"
    msg3["Message-ID"] = "<msg-003-nested-zip-tree@falconix.test>"
    msg3["Date"] = email.utils.formatdate(localtime=True)
    msg3.set_content("Respected Dean,\n\nSubmitting all verified records organized into folder directories.\n\nThank you,\nAnanya Iyer")
    zip_bytes_tree = _create_zip_bytes({
        "admission_docs/academic/marksheet.pdf": _create_minimal_pdf_bytes("Semester VIII Marksheet - Ananya Iyer"),
        "admission_docs/identity/student_id.png": _create_image_bytes("Student ID - Ananya", seed=303),
        "admission_docs/letters/bonafide_certificate.pdf": _create_minimal_pdf_bytes("Bonafide Certificate"),
    })
    msg3.add_attachment(zip_bytes_tree, maintype="application", subtype="zip", filename="bundle_tree.zip")
    messages.append(msg3)

    # -------------------------------------------------------------------------
    # Email 4: No Attachments
    # -------------------------------------------------------------------------
    msg4 = email.message.EmailMessage()
    msg4["From"] = '"Sunita Deshmukh" <sunita.d@freemail.com>'
    msg4["Reply-To"] = '"Sunita Deshmukh" <sunita.d@freemail.com>'
    msg4["To"] = "inquiry@falconix.edu"
    msg4["Subject"] = "Inquiry regarding application deadlines"
    msg4["Message-ID"] = "<msg-004-no-attachments@falconix.test>"
    msg4["Date"] = email.utils.formatdate(localtime=True)
    msg4.set_content("Hello Admissions,\n\nCould you please let me know the deadline for submitting official transcripts?\n\nSincerely,\nSunita Deshmukh")
    messages.append(msg4)

    # -------------------------------------------------------------------------
    # Email 5: Unsupported Attachment (.exe / binary)
    # -------------------------------------------------------------------------
    msg5 = email.message.EmailMessage()
    msg5["From"] = '"Karthik Subramanian" <karthik.sub@startup.io>'
    msg5["Reply-To"] = '"Karthik Subramanian" <karthik.sub@startup.io>'
    msg5["To"] = "jobs@falconix.edu"
    msg5["Subject"] = "Submission with executable system report"
    msg5["Message-ID"] = "<msg-005-unsupported-attachment@falconix.test>"
    msg5["Date"] = email.utils.formatdate(localtime=True)
    msg5.set_content("Hi Team,\n\nAttaching system diagnostics.\n\nThanks,\nKarthik")
    unsupported_payload = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00Synthetic PE Executable"
    msg5.add_attachment(unsupported_payload, maintype="application", subtype="octet-stream", filename="installer_tool.exe")
    messages.append(msg5)

    # -------------------------------------------------------------------------
    # Email 6: Duplicate Message-ID (Same ID as Email 1)
    # -------------------------------------------------------------------------
    msg6 = email.message.EmailMessage()
    msg6["From"] = '"Dr. Priya Nair (Follow-up)" <priya.nair@research.org>'
    msg6["Reply-To"] = '"Dr. Priya Nair" <priya.nair@research.org>'
    msg6["To"] = "admissions@falconix.edu"
    msg6["Subject"] = "Re: Application for Senior Research Scientist (Duplicate Submission)"
    msg6["Message-ID"] = "<msg-001-five-attachments@falconix.test>"  # Same Message-ID as msg1!
    msg6["Date"] = email.utils.formatdate(localtime=True)
    msg6.set_content("Dear Admissions,\n\nResending my previous email.\n\nBest,\nDr. Priya Nair")
    msg6.add_attachment(pdf1, maintype="application", subtype="pdf", filename="resume_dup.pdf")
    messages.append(msg6)

    return messages


def make_mbox(
    scenario: str = "job_application",
    count: int = 6,
    out_path: Path = _DEFAULT_MBOX,
    eml_dir: Path | None = _DEFAULT_EML_DIR,
) -> Path:
    """Create a synthetic .mbox and .eml set with the requested edge cases."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    all_msgs = build_synthetic_messages()
    selected_msgs = all_msgs[:count] if count <= len(all_msgs) else all_msgs

    # Create .mbox
    mbox = mailbox.mbox(str(out_path))
    mbox.lock()
    try:
        for msg in selected_msgs:
            mbox.add(msg)
        mbox.flush()
    finally:
        mbox.unlock()

    # Create .eml set if directory requested
    if eml_dir is not None:
        eml_dir.mkdir(parents=True, exist_ok=True)
        for i, msg in enumerate(selected_msgs, start=1):
            eml_path = eml_dir / f"email_{i:02d}.eml"
            eml_path.write_bytes(msg.as_bytes())

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create synthetic .mbox and .eml test files.")
    parser.add_argument("--scenario", default="job_application", help="Scenario name")
    parser.add_argument("--count", type=int, default=6, help="Number of messages (up to 6)")
    parser.add_argument("--out", type=Path, default=_DEFAULT_MBOX, help="Output .mbox path")
    parser.add_argument("--eml-dir", type=Path, default=_DEFAULT_EML_DIR, help="Output .eml directory")
    args = parser.parse_args()

    print(f"Creating synthetic mbox at {args.out} and emls in {args.eml_dir}...")
    created = make_mbox(scenario=args.scenario, count=args.count, out_path=args.out, eml_dir=args.eml_dir)
    print(f"Done. Created {created} with {args.count} synthetic emails.")


if __name__ == "__main__":
    main()
