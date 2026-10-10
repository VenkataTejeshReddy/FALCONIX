# Owner: Laptop B
"""INX – Script: create scenario .mbox archives and expected outcomes.

Builds:
- fixtures/mail/job_applications.mbox
- fixtures/mail/college_applications.mbox

Each mailbox contains at least 22 deterministic emails exercising every edge case:
1. Complete bundle (PROCESS)
2. One required field missing (REQUEST_INFO)
3. Name typo across two documents (MANUAL_VERIFICATION)
4. "P. Sharma" vs "Priya Sharma" (MANUAL_VERIFICATION)
5. Invalid ID checksum (HUMAN_REVIEW)
6. Value hidden by a stamp (HUMAN_REVIEW)
7. Blurry phone photo (HUMAN_REVIEW)
8. Unknown document type (restaurant menu) (HUMAN_REVIEW)
9. Required document missing entirely (REQUEST_INFO)
10. Document type not expected for scenario (HUMAN_REVIEW)
11. Email with a ZIP (PROCESS)
12. Email with no attachment (REQUEST_INFO)
13. Email with only an .exe (REQUEST_INFO)
14. Same Message-ID twice (First: PROCESS, Second: HUMAN_REVIEW / duplicate)
15. Same documents sent by two different senders (Second: HUMAN_REVIEW / duplicate)
16. Mislabeled attachment (marksheet.pdf that is really an ID card) (HUMAN_REVIEW)
17. Attachments with neutral names (scan001.pdf, IMG_2041.jpg) (PROCESS)
18. Document with prompt injection (HUMAN_REVIEW)
19. 3 Hard variants in mailbox (HUMAN_REVIEW)
20. 6-page PDF where value differs on page 5 (MANUAL_VERIFICATION)

Updates fixtures/synthetic_docs/expected_outcomes.json with EMAIL-level expectations.
"""

from __future__ import annotations

import argparse
import email.message
import email.utils
import io
import json
import mailbox
import sys
import zipfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SYNTHETIC_DIR = _REPO_ROOT / "fixtures" / "synthetic_docs"
_HARD_DIR = _SYNTHETIC_DIR / "hard"
_MAIL_DIR = _REPO_ROOT / "fixtures" / "mail"


def _read_doc(name: str) -> bytes:
    """Read bytes from synthetic_docs or synthetic_docs/hard."""
    p1 = _SYNTHETIC_DIR / name
    if p1.exists():
        return p1.read_bytes()
    p2 = _HARD_DIR / name
    if p2.exists():
        return p2.read_bytes()
    raise FileNotFoundError(f"Fixture document not found: {name}")


def _make_zip(files: dict[str, str]) -> bytes:
    """Create in-memory zip bytes from fixture file map: {zip_path: fixture_name}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for zip_name, fixture_name in files.items():
            zf.writestr(zip_name, _read_doc(fixture_name))
    return buf.getvalue()


def _build_email(
    sender: str,
    sender_name: str,
    to: str,
    subject: str,
    msg_id: str,
    timestamp: int,
    body: str,
    attachments: list[tuple[str, bytes, str, str]] | None = None,
) -> email.message.EmailMessage:
    msg = email.message.EmailMessage()
    msg["From"] = f'"{sender_name}" <{sender}>'
    msg["Reply-To"] = f'"{sender_name}" <{sender}>'
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{msg_id.strip('<> ')}>"
    msg["Date"] = email.utils.formatdate(timestamp, usegmt=True)
    msg.set_content(body)

    if attachments:
        for fname, data, maintype, subtype in attachments:
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=fname)

    return msg


# ---------------------------------------------------------------------------
# Mailbox Builders
# ---------------------------------------------------------------------------


def build_job_application_emails() -> tuple[list[email.message.EmailMessage], dict[str, Any]]:
    """Build all emails and email expectations for job_applications.mbox."""
    msgs: list[email.message.EmailMessage] = []
    expectations: dict[str, Any] = {}
    base_time = 1700000000

    def add_case(
        case_id: str,
        sender_name: str,
        sender_email: str,
        subject: str,
        body: str,
        attachments: list[tuple[str, str]],  # (attachment_filename, fixture_name)
        expected_status: str,
        expected_route: str,
        expected_issues: list[str],
        custom_msg_id: str | None = None,
    ):
        msg_id = custom_msg_id or f"job-{case_id}@falconix.test"
        built_att: list[tuple[str, bytes, str, str]] = []
        doc_names: list[str] = []

        for att_name, fix_name in attachments:
            doc_names.append(att_name)
            if att_name.endswith(".zip"):
                raw = _make_zip({"resume.pdf": "job_normal_resume.pdf", "id.jpg": "job_normal_id.jpg"})
                built_att.append((att_name, raw, "application", "zip"))
            elif att_name.endswith(".exe"):
                raw = b"MZ\x90\x00Synthetic_PE_Executable_Payload"
                built_att.append((att_name, raw, "application", "octet-stream"))
            else:
                raw = _read_doc(fix_name)
                ext = Path(att_name).suffix.lower()
                mtype, stype = ("image", "jpeg") if ext in [".jpg", ".jpeg"] else ("application", "pdf")
                built_att.append((att_name, raw, mtype, stype))

        eml = _build_email(
            sender=sender_email,
            sender_name=sender_name,
            to="jobs@falconix.test",
            subject=subject,
            msg_id=msg_id,
            timestamp=base_time + len(msgs) * 3600,
            body=body,
            attachments=built_att,
        )
        msgs.append(eml)

        cleaned_id = msg_id.strip("<> ")
        expectations[cleaned_id] = {
            "mailbox": "job_applications.mbox",
            "case_id": case_id,
            "subject": subject,
            "sender": sender_email,
            "sender_name": sender_name,
            "message_id": f"<{cleaned_id}>",
            "documents": doc_names,
            "expected_workflow_status": expected_status,
            "expected_route": expected_route,
            "expected_issue_kinds": expected_issues,
        }

    # 1. Complete bundle (PROCESS)
    add_case(
        "01-complete", "Rohan Verma", "rohan.verma@example.com",
        "Job Application – Senior Engineer", "Complete application bundle.",
        [("resume.pdf", "job_normal_resume.pdf"), ("id_card.jpg", "job_normal_id.jpg")],
        "verified", "PROCESS", []
    )

    # 2. One required field missing (REQUEST_INFO)
    add_case(
        "02-missing-field", "Sunita Deshmukh", "sunita.d@example.com",
        "Application – Sunita Deshmukh", "Submitting resume without email/exp.",
        [("resume.pdf", "job_missing_field_resume.pdf"), ("id_card.jpg", "job_normal_id.jpg")],
        "awaiting_information", "REQUEST_INFO", ["missing"]
    )

    # 3. Name typo across two documents (MANUAL_VERIFICATION)
    add_case(
        "03-name-typo", "Rohan Verma", "rohan.v@example.com",
        "Application Discrepancy Case", "Submitting resume and ID with slight name typo.",
        [("resume.pdf", "job_normal_resume.pdf"), ("id_card.jpg", "job_name_typo_id.jpg")],
        "review_required", "MANUAL_VERIFICATION", ["conflict"]
    )

    # 4. "P. Sharma" vs "Priya Sharma" (MANUAL_VERIFICATION)
    add_case(
        "04-initials-typo", "Priya Sharma", "priya.sharma@example.com",
        "Application – Priya Sharma", "ID has initials P. Sharma.",
        [("resume.pdf", "job_normal_resume.pdf"), ("id_card.jpg", "job_initials_typo_id.jpg")],
        "review_required", "MANUAL_VERIFICATION", ["conflict"]
    )

    # 5. Invalid ID checksum (HUMAN_REVIEW)
    add_case(
        "05-invalid-id", "Karthik Subramanian", "karthik.sub@example.com",
        "Application with Corrupt ID Checksum", "ID card with bad Verhoeff checksum.",
        [("resume.pdf", "job_normal_resume.pdf"), ("id_card.pdf", "job_conflicting_id.pdf")],
        "review_required", "HUMAN_REVIEW", ["unreliable"]
    )

    # 6. Value hidden by a stamp (HUMAN_REVIEW)
    add_case(
        "06-obscured-stamp", "Vikramaditya Rao", "v.rao@example.com",
        "Application – Stamped ID", "ID card has stamp over number.",
        [("resume.pdf", "job_normal_resume.pdf"), ("id_card.jpg", "job_unclear_stamp_id.jpg")],
        "review_required", "HUMAN_REVIEW", ["unclear"]
    )

    # 7. Blurry phone photo (HUMAN_REVIEW)
    add_case(
        "07-blurry-photo", "Aarav Mehta", "aarav.m@example.com",
        "Application – Camera Capture", "Photo taken with mobile device.",
        [("resume.jpg", "job_blurry_photo_resume.jpg"), ("id_card.jpg", "job_normal_id.jpg")],
        "review_required", "HUMAN_REVIEW", ["poor_quality"]
    )

    # 8. Unknown document type (restaurant menu) (HUMAN_REVIEW)
    add_case(
        "08-unknown-menu", "Neha Gupta", "neha.g@example.com",
        "Application and Attachments", "Contains dinner menu by mistake.",
        [("menu.pdf", "job_unknown_menu.pdf"), ("id_card.jpg", "job_normal_id.jpg")],
        "review_required", "HUMAN_REVIEW", ["unknown_type"]
    )

    # 9. Required document missing entirely (REQUEST_INFO)
    add_case(
        "09-missing-doc", "Deepak Joshi", "deepak.j@example.com",
        "Application without Government ID", "Only resume attached, ID omitted.",
        [("resume.pdf", "job_normal_resume.pdf")],
        "awaiting_information", "REQUEST_INFO", ["missing_document"]
    )

    # 10. Document type not expected for scenario (HUMAN_REVIEW)
    add_case(
        "10-unexpected-doc", "Siddharth Sen", "siddharth.s@example.com",
        "Application with College Marksheet", "Includes college marksheet.",
        [("resume.pdf", "job_normal_resume.pdf"), ("id_card.jpg", "job_normal_id.jpg"), ("marksheet.pdf", "job_unexpected_marksheet.pdf")],
        "review_required", "HUMAN_REVIEW", ["unknown_type"]
    )

    # 11. Email with a ZIP (PROCESS)
    add_case(
        "11-zip-bundle", "Pooja Hegde", "pooja.h@example.com",
        "Application in Zip Archive", "All documents packed into zip.",
        [("documents.zip", "")],
        "verified", "PROCESS", []
    )

    # 12. Email with no attachment (REQUEST_INFO)
    add_case(
        "12-no-attachment", "Alok Kumar", "alok.k@example.com",
        "Inquiry: Application Submission", "Please find my application enclosed (no file attached).",
        [],
        "awaiting_information", "REQUEST_INFO", ["missing_document"]
    )

    # 13. Email with only an .exe (REQUEST_INFO)
    add_case(
        "13-only-exe", "Security Auditor", "auditor@example.com",
        "Diagnostics Tool Payload", "Diagnostic executable attached.",
        [("installer.exe", "")],
        "awaiting_information", "REQUEST_INFO", ["unsupported_file", "missing_document"]
    )

    # 14. Duplicate Message-ID (First copy)
    add_case(
        "14-dup-id-first", "Dr. Priya Nair", "priya.nair@example.com",
        "Application Resubmission Test", "First copy of message.",
        [("resume.pdf", "job_normal_resume.pdf"), ("id_card.jpg", "job_normal_id.jpg")],
        "verified", "PROCESS", [],
        custom_msg_id="job-shared-duplicate-msg-id@falconix.test"
    )

    # 15. Duplicate Message-ID (Second copy)
    add_case(
        "15-dup-id-second", "Dr. Priya Nair (Second)", "priya.nair@example.com",
        "Re: Application Resubmission Test", "Second copy with identical Message-ID.",
        [("resume.pdf", "job_normal_resume.pdf")],
        "review_required", "HUMAN_REVIEW", ["duplicate_file"],
        custom_msg_id="job-shared-duplicate-msg-id@falconix.test"
    )

    # 16. Same documents sent by two different senders (Sender A)
    add_case(
        "16-same-docs-sender-a", "Candidate Alpha", "candidate.a@example.com",
        "Candidate Alpha Application", "Original applicant submission.",
        [("resume.pdf", "job_normal_resume.pdf"), ("id_card.jpg", "job_normal_id.jpg")],
        "verified", "PROCESS", []
    )

    # 17. Same documents sent by two different senders (Sender B)
    add_case(
        "17-same-docs-sender-b", "Candidate Beta", "candidate.b@example.com",
        "Candidate Beta Application", "Duplicate applicant submission using identical files.",
        [("resume.pdf", "job_normal_resume.pdf"), ("id_card.jpg", "job_normal_id.jpg")],
        "review_required", "HUMAN_REVIEW", ["duplicate_file"]
    )

    # 18. Mislabeled attachment (marksheet.pdf that is really an ID card) (HUMAN_REVIEW)
    add_case(
        "18-mislabeled-doc", "Manish Malhotra", "manish.m@example.com",
        "Application with Mislabeled Document", "File named marksheet.pdf is an ID card.",
        [("resume.pdf", "job_normal_resume.pdf"), ("marksheet.pdf", "job_mislabeled_id_as_marksheet.pdf")],
        "review_required", "HUMAN_REVIEW", ["unclear"]
    )

    # 19. Attachments with neutral names (scan001.pdf, IMG_2041.jpg) (PROCESS)
    add_case(
        "19-neutral-names", "Aditi Sharma", "aditi.s@example.com",
        "Documents Attached", "Scans attached with scanner default names.",
        [("scan001.pdf", "scan001.pdf"), ("IMG_2041.jpg", "IMG_2041.jpg")],
        "verified", "PROCESS", []
    )

    # 20. Prompt injection document (HUMAN_REVIEW)
    add_case(
        "20-prompt-injection", "Red Team Tester", "redteam@example.com",
        "Security Evaluation Application", "Contains prompt injection string.",
        [("profile.pdf", "job_prompt_injection.pdf"), ("id_card.jpg", "job_normal_id.jpg")],
        "review_required", "HUMAN_REVIEW", ["unreliable"]
    )

    # 21. Three Hard Variants (HUMAN_REVIEW)
    add_case(
        "21-hard-variants", "Harish Patel", "harish.p@example.com",
        "Application with Challenging Mobile Scans", "Includes tilted, perspective-warped, and yellowed scans.",
        [
            ("tilted_resume.jpg", "hard_tilted_resume.jpg"),
            ("perspective_id.jpg", "hard_perspective_id.jpg"),
            ("scanned_yellow.jpg", "hard_scanned_yellow_resume.jpg"),
        ],
        "review_required", "HUMAN_REVIEW", ["poor_quality", "unreliable"]
    )

    # 22. 6-page PDF where field value differs on page 5 (MANUAL_VERIFICATION)
    add_case(
        "22-six-page-retrieval", "Rajesh Kumar", "rajesh.k@example.com",
        "Application Dossier 6-Pages", "6-page comprehensive dossier.",
        [("dossier.pdf", "job_6page_differing_page5.pdf"), ("resume.pdf", "job_normal_resume.pdf")],
        "review_required", "MANUAL_VERIFICATION", ["conflict"]
    )

    return msgs, expectations


def build_college_application_emails() -> tuple[list[email.message.EmailMessage], dict[str, Any]]:
    """Build all emails and email expectations for college_applications.mbox."""
    msgs: list[email.message.EmailMessage] = []
    expectations: dict[str, Any] = {}
    base_time = 1700100000

    def add_case(
        case_id: str,
        sender_name: str,
        sender_email: str,
        subject: str,
        body: str,
        attachments: list[tuple[str, str]],
        expected_status: str,
        expected_route: str,
        expected_issues: list[str],
        custom_msg_id: str | None = None,
    ):
        msg_id = custom_msg_id or f"col-{case_id}@falconix.test"
        built_att: list[tuple[str, bytes, str, str]] = []
        doc_names: list[str] = []

        for att_name, fix_name in attachments:
            doc_names.append(att_name)
            if att_name.endswith(".zip"):
                raw = _make_zip({"marksheet.pdf": "college_normal_marksheet.pdf", "id.jpg": "college_normal_id.jpg"})
                built_att.append((att_name, raw, "application", "zip"))
            elif att_name.endswith(".exe"):
                raw = b"MZ\x90\x00Synthetic_PE_Executable_Payload"
                built_att.append((att_name, raw, "application", "octet-stream"))
            else:
                raw = _read_doc(fix_name)
                ext = Path(att_name).suffix.lower()
                mtype, stype = ("image", "jpeg") if ext in [".jpg", ".jpeg"] else ("application", "pdf")
                built_att.append((att_name, raw, mtype, stype))

        eml = _build_email(
            sender=sender_email,
            sender_name=sender_name,
            to="admissions@falconix.test",
            subject=subject,
            msg_id=msg_id,
            timestamp=base_time + len(msgs) * 3600,
            body=body,
            attachments=built_att,
        )
        msgs.append(eml)

        cleaned_id = msg_id.strip("<> ")
        expectations[cleaned_id] = {
            "mailbox": "college_applications.mbox",
            "case_id": case_id,
            "subject": subject,
            "sender": sender_email,
            "sender_name": sender_name,
            "message_id": f"<{cleaned_id}>",
            "documents": doc_names,
            "expected_workflow_status": expected_status,
            "expected_route": expected_route,
            "expected_issue_kinds": expected_issues,
        }

    # 1. Complete bundle (PROCESS)
    add_case(
        "01-complete", "Ananya Iyer", "ananya.iyer@example.com",
        "College Admission Submission", "Full academic marksheet and student ID.",
        [("marksheet.pdf", "college_normal_marksheet.pdf"), ("student_id.jpg", "college_normal_id.jpg")],
        "verified", "PROCESS", []
    )

    # 2. One required field missing (REQUEST_INFO)
    add_case(
        "02-missing-field", "Rupa Roy", "rupa.r@example.com",
        "Marksheet Submission without Issue Date", "Marksheet missing issue_date.",
        [("marksheet.pdf", "college_missing_date_marksheet.pdf"), ("student_id.jpg", "college_normal_id.jpg")],
        "awaiting_information", "REQUEST_INFO", ["missing"]
    )

    # 3. Name typo across two documents (MANUAL_VERIFICATION)
    add_case(
        "03-name-typo", "Ananya Iyer", "ananya.iyer@example.com",
        "Admission Application Typo Case", "Marksheet has Ananya Iyer, ID has Ananya Iyyar.",
        [("marksheet.pdf", "college_normal_marksheet.pdf"), ("student_id.jpg", "college_name_typo_id.jpg")],
        "review_required", "MANUAL_VERIFICATION", ["conflict"]
    )

    # 4. "P. Sharma" vs "Priya Sharma" (MANUAL_VERIFICATION)
    add_case(
        "04-initials-typo", "Priya Sharma", "priya.s@example.com",
        "College Application – Priya Sharma", "ID has initials P. Sharma.",
        [("marksheet.pdf", "college_normal_marksheet.pdf"), ("student_id.jpg", "college_initials_typo_id.jpg")],
        "review_required", "MANUAL_VERIFICATION", ["conflict"]
    )

    # 5. Invalid DOB / ID Checksum (HUMAN_REVIEW)
    add_case(
        "05-invalid-dob", "Kavita Rao", "kavita.r@example.com",
        "Admission with Future Date of Birth", "ID card with DOB in 2045.",
        [("marksheet.pdf", "college_normal_marksheet.pdf"), ("student_id.pdf", "college_future_dob_id.pdf")],
        "review_required", "HUMAN_REVIEW", ["unreliable"]
    )

    # 6. Value hidden by a stamp (HUMAN_REVIEW)
    add_case(
        "06-obscured-stamp", "Divya Menon", "divya.m@example.com",
        "Submission with Stamped Grade Sheet", "Marks obscured by stamp.",
        [("marksheet.jpg", "college_unclear_stamp_marksheet.jpg"), ("student_id.jpg", "college_normal_id.jpg")],
        "review_required", "HUMAN_REVIEW", ["unclear"]
    )

    # 7. Blurry phone photo (HUMAN_REVIEW)
    add_case(
        "07-blurry-photo", "Sanjay Singhania", "sanjay.s@example.com",
        "Marksheet Smartphone Photo", "Blurry mobile capture of marksheet.",
        [("marksheet.jpg", "college_blurry_photo_marksheet.jpg"), ("student_id.jpg", "college_normal_id.jpg")],
        "review_required", "HUMAN_REVIEW", ["poor_quality"]
    )

    # 8. Unknown document type (restaurant menu) (HUMAN_REVIEW)
    add_case(
        "08-unknown-menu", "Madhav Varma", "madhav.v@example.com",
        "College Admission Documents", "Dinner menu attached by mistake.",
        [("menu.pdf", "college_unknown_menu.pdf"), ("student_id.jpg", "college_normal_id.jpg")],
        "review_required", "HUMAN_REVIEW", ["unknown_type"]
    )

    # 9. Required document missing entirely (REQUEST_INFO)
    add_case(
        "09-missing-doc", "Shreya Ghoshal", "shreya.g@example.com",
        "Marksheet Submission Only", "Only marksheet attached, ID omitted.",
        [("marksheet.pdf", "college_normal_marksheet.pdf")],
        "awaiting_information", "REQUEST_INFO", ["missing_document"]
    )

    # 10. Document type not expected for scenario (HUMAN_REVIEW)
    add_case(
        "10-unexpected-doc", "Nikhil Chopra", "nikhil.c@example.com",
        "Submission with Employment Offer Letter", "Includes employment offer letter.",
        [("marksheet.pdf", "college_normal_marksheet.pdf"), ("student_id.jpg", "college_normal_id.jpg"), ("offer.pdf", "college_unexpected_offer_letter.pdf")],
        "review_required", "HUMAN_REVIEW", ["unknown_type"]
    )

    # 11. Email with a ZIP (PROCESS)
    add_case(
        "11-zip-bundle", "Pooja Hegde", "pooja.h@example.com",
        "Academic Records in Archive", "Complete college records in ZIP.",
        [("college_bundle.zip", "")],
        "verified", "PROCESS", []
    )

    # 12. Email with no attachment (REQUEST_INFO)
    add_case(
        "12-no-attachment", "Gaurav Roy", "gaurav.r@example.com",
        "Inquiry on College Admissions", "Seeking guidance on admission deadline.",
        [],
        "awaiting_information", "REQUEST_INFO", ["missing_document"]
    )

    # 13. Email with only an .exe (REQUEST_INFO)
    add_case(
        "13-only-exe", "Campus Security", "security@example.com",
        "System Utility Attachment", "Executable binary tool attached.",
        [("installer.exe", "")],
        "awaiting_information", "REQUEST_INFO", ["unsupported_file", "missing_document"]
    )

    # 14. Duplicate Message-ID (First copy)
    add_case(
        "14-dup-id-first", "Dr. Swaminathan", "swami@example.com",
        "Endorsement for Admission", "First copy of message.",
        [("marksheet.pdf", "college_normal_marksheet.pdf"), ("student_id.jpg", "college_normal_id.jpg")],
        "verified", "PROCESS", [],
        custom_msg_id="col-shared-duplicate-msg-id@falconix.test"
    )

    # 15. Duplicate Message-ID (Second copy)
    add_case(
        "15-dup-id-second", "Dr. Swaminathan (Copy)", "swami@example.com",
        "Re: Endorsement for Admission", "Duplicate copy sharing Message-ID.",
        [("marksheet.pdf", "college_normal_marksheet.pdf")],
        "review_required", "HUMAN_REVIEW", ["duplicate_file"],
        custom_msg_id="col-shared-duplicate-msg-id@falconix.test"
    )

    # 16. Same documents sent by two different senders (Sender A)
    add_case(
        "16-same-docs-sender-a", "Student Alpha", "student.a@example.com",
        "Student Alpha Records", "Original student submission.",
        [("marksheet.pdf", "college_normal_marksheet.pdf"), ("student_id.jpg", "college_normal_id.jpg")],
        "verified", "PROCESS", []
    )

    # 17. Same documents sent by two different senders (Sender B)
    add_case(
        "17-same-docs-sender-b", "Student Beta", "student.b@example.com",
        "Student Beta Records", "Duplicate student submission using identical files.",
        [("marksheet.pdf", "college_normal_marksheet.pdf"), ("student_id.jpg", "college_normal_id.jpg")],
        "review_required", "HUMAN_REVIEW", ["duplicate_file"]
    )

    # 18. Mislabeled attachment (marksheet.pdf that is really an ID card) (HUMAN_REVIEW)
    add_case(
        "18-mislabeled-doc", "Tanya Sen", "tanya.s@example.com",
        "Admission with Mislabeled Document", "File named marksheet.pdf is an ID card.",
        [("marksheet.pdf", "college_mislabeled_id_as_marksheet.pdf"), ("student_id.jpg", "college_normal_id.jpg")],
        "review_required", "HUMAN_REVIEW", ["unclear"]
    )

    # 19. Attachments with neutral names (scan001.pdf, IMG_2041.jpg) (PROCESS)
    add_case(
        "19-neutral-names", "Preeti Das", "preeti.d@example.com",
        "College Submission – Scans", "Neutral scanner filenames.",
        [("scan001.pdf", "scan001.pdf"), ("IMG_2041.jpg", "IMG_2041.jpg")],
        "verified", "PROCESS", []
    )

    # 20. Prompt injection document (HUMAN_REVIEW)
    add_case(
        "20-prompt-injection", "Adversarial Student", "adversary@example.com",
        "Transcript Verification Application", "Contains prompt injection payload.",
        [("transcript.pdf", "college_prompt_injection.pdf"), ("student_id.jpg", "college_normal_id.jpg")],
        "review_required", "HUMAN_REVIEW", ["unreliable"]
    )

    # 21. Three Hard Variants (HUMAN_REVIEW)
    add_case(
        "21-hard-variants", "Ravi Shankar", "ravi.s@example.com",
        "Challenging Scans and Certificate", "Shadowed marksheet, noisy ID, and decorative certificate.",
        [
            ("shadowed_marksheet.jpg", "hard_shadow_marksheet.jpg"),
            ("grainy_id.jpg", "hard_grainy_id.jpg"),
            ("decorative_certificate.pdf", "hard_decorative_certificate.pdf"),
        ],
        "review_required", "HUMAN_REVIEW", ["poor_quality", "unreliable"]
    )

    # 22. 6-page PDF where field value differs on page 5 (MANUAL_VERIFICATION)
    add_case(
        "22-six-page-retrieval", "Mohan Lal", "mohan.l@example.com",
        "6-Page Academic Transcript", "Multi-page transcript dossier.",
        [("transcript_6page.pdf", "college_6page_differing_page5.pdf"), ("student_id.jpg", "college_normal_id.jpg")],
        "review_required", "MANUAL_VERIFICATION", ["conflict"]
    )

    return msgs, expectations


def build_scenario_mailboxes(mail_dir: Path = _MAIL_DIR) -> dict[str, Any]:
    """Build job_applications.mbox and college_applications.mbox deterministically."""
    mail_dir.mkdir(parents=True, exist_ok=True)
    all_email_expectations: dict[str, Any] = {}

    # 1. Job applications mailbox
    job_mbox_path = mail_dir / "job_applications.mbox"
    if job_mbox_path.exists():
        job_mbox_path.unlink()
    job_msgs, job_exp = build_job_application_emails()
    job_mbox = mailbox.mbox(str(job_mbox_path))
    job_mbox.lock()
    try:
        for m in job_msgs:
            job_mbox.add(m)
        job_mbox.flush()
    finally:
        job_mbox.unlock()
    all_email_expectations.update(job_exp)

    # 2. College applications mailbox
    col_mbox_path = mail_dir / "college_applications.mbox"
    if col_mbox_path.exists():
        col_mbox_path.unlink()
    col_msgs, col_exp = build_college_application_emails()
    col_mbox = mailbox.mbox(str(col_mbox_path))
    col_mbox.lock()
    try:
        for m in col_msgs:
            col_mbox.add(m)
        col_mbox.flush()
    finally:
        col_mbox.unlock()
    all_email_expectations.update(col_exp)

    # Update expected_outcomes.json
    outcomes_path = _SYNTHETIC_DIR / "expected_outcomes.json"
    existing_outcomes: dict[str, Any] = {}
    if outcomes_path.exists():
        try:
            existing_outcomes = json.loads(outcomes_path.read_text(encoding="utf-8"))
        except Exception:
            existing_outcomes = {}

    # Separate into documents and emails sections while maintaining top-level access
    doc_section = existing_outcomes.get("documents", {})
    for k, v in existing_outcomes.items():
        if k not in ["documents", "emails"] and isinstance(v, dict) and "expected_statuses" in v:
            doc_section[k] = v

    combined_outcomes = {
        "documents": doc_section,
        "emails": all_email_expectations,
    }
    # Mirror top-level keys for backwards-compatibility
    for doc_k, doc_v in doc_section.items():
        combined_outcomes[doc_k] = doc_v
    for email_k, email_v in all_email_expectations.items():
        combined_outcomes[email_k] = email_v

    with open(outcomes_path, "w", encoding="utf-8") as f:
        json.dump(combined_outcomes, f, indent=2)

    return all_email_expectations


# ---------------------------------------------------------------------------
# Backward-compatible shims for test_intake.py
# ---------------------------------------------------------------------------

def build_synthetic_messages() -> list[email.message.EmailMessage]:
    """Build all job-application emails (shim for test_intake.py)."""
    msgs, _ = build_job_application_emails()
    return msgs


def make_mbox(
    scenario: str = "job_application",
    count: int = 6,
    out_path: Path = _MAIL_DIR / "job_applications.mbox",
    eml_dir: Path | None = None,
) -> Path:
    """Create a test .mbox (shim for test_intake.py / old CLI).

    Writes job_applications.mbox (or college_applications.mbox based on scenario)
    and optionally writes individual .eml files.
    """
    if scenario == "college":
        msgs, _ = build_college_application_emails()
    else:
        msgs, _ = build_job_application_emails()

    selected = msgs[:count] if count <= len(msgs) else msgs

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    mbox = mailbox.mbox(str(out_path))
    mbox.lock()
    try:
        for m in selected:
            mbox.add(m)
        mbox.flush()
    finally:
        mbox.unlock()

    if eml_dir is not None:
        eml_dir.mkdir(parents=True, exist_ok=True)
        for i, msg in enumerate(selected, start=1):
            (eml_dir / f"email_{i:02d}.eml").write_bytes(msg.as_bytes())

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create scenario mailboxes and email expectations.")
    parser.add_argument("--mail-dir", type=Path, default=_MAIL_DIR, help="Output mailboxes directory")
    args = parser.parse_args()

    print(f"Building scenario mailboxes in {args.mail_dir}...")
    exps = build_scenario_mailboxes(args.mail_dir)
    print(f"Done. Generated mailboxes with {len(exps)} total email expectations.")


if __name__ == "__main__":
    main()
