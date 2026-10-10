# Owner: Laptop B
"""INX – Case builder: assembles a CaseRecord from a parsed email message.

Takes the parsed email metadata produced by :mod:`app.intake.email_import`,
invokes batch ingestion (:func:`app.ingest.batch.ingest_many`) on its attachment
directory, and produces fully structured :class:`CaseRecord` objects.

Reports totals up front so the UI can display progress (N emails).
"""

from __future__ import annotations

import email
import email.message
import email.utils
import hashlib
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from app.ingest.batch import BatchResult, DocOutcome, ingest_many
from app.ingest.ingest import IngestResult
from app.intake.email_import import (
    ParsedEmail,
    count_emails,
    iter_parsed_emails,
    sanitize_filename,
)
from app.schemas import CaseRecord, DocumentRecord, DocumentType, WorkflowStatus


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_sender(msg: email.message.Message) -> tuple[str, str]:
    """Return (email_address, display_name) from the From: header."""
    from_hdr = str(msg.get("From", ""))
    disp_name, email_addr = email.utils.parseaddr(from_hdr)
    return email_addr, disp_name


def _make_document_record(
    filename: str, outcome_result: IngestResult | None = None
) -> DocumentRecord:
    """Create a :class:`DocumentRecord` for an ingested attachment."""
    if outcome_result is not None:
        return DocumentRecord(
            doc_id=str(uuid.uuid4()),
            filename=Path(filename).name,
            sha256=outcome_result.sha256,
            mime_type="",
            storage_path=str(outcome_result.original_path),
            pages=len(outcome_result.page_paths),
            doc_type=DocumentType.unknown,
            doc_type_confidence=0.0,
            quality_score=None,
            quality_verdict=outcome_result.overall_quality,  # type: ignore[arg-type]
            quality_issues=[
                issue for q in outcome_result.quality for issue in q.issues
            ],
            page_images=outcome_result.page_paths,
            pdf_has_text_layer=outcome_result.pdf_has_text_layer,
            is_duplicate=outcome_result.duplicate,
            is_readable=None,
            ingested_at=datetime.now(timezone.utc),
        )

    # Stub when result is not available
    return DocumentRecord(
        doc_id=str(uuid.uuid4()),
        filename=Path(filename).name,
        sha256="",
        storage_path="",
        pages=1,
        doc_type=DocumentType.unknown,
    )


# ---------------------------------------------------------------------------
# Case Assembly
# ---------------------------------------------------------------------------


def build_case_from_parsed_email(
    parsed: ParsedEmail,
    scenario: str,
    data_dir: str | Path = "data",
) -> CaseRecord:
    """Build a :class:`CaseRecord` from a :class:`ParsedEmail` by calling ingest_many()."""
    case = CaseRecord(
        case_id=str(uuid.uuid4()),
        scenario=scenario,
        sender_email=parsed.sender,
        sender_name=parsed.display_name,
        message_id=parsed.message_id,
        received_at=parsed.received_at,
        subject=parsed.subject,
        workflow_status=WorkflowStatus.received,
    )

    intake_notes = list(parsed.notes)
    documents: list[DocumentRecord] = []
    skipped_files: list[dict[str, str | None]] = []

    # If attachments exist in the staging directory, run batch ingest on it
    if parsed.attachment_folder.exists() and any(parsed.attachment_folder.iterdir()):
        batch_result: BatchResult = ingest_many(
            parsed.attachment_folder, data_dir=data_dir
        )
        intake_notes.extend(batch_result.notes)

        for outcome in batch_result.outcomes:
            if outcome.status == "ingested" and outcome.result is not None:
                doc = _make_document_record(outcome.name, outcome.result)
                documents.append(doc)
            else:
                skipped_files.append(
                    {
                        "filename": outcome.name,
                        "status": outcome.status,
                        "reason": outcome.reason,
                    }
                )
    else:
        intake_notes.append("No attachments staged for this case.")

    case.documents = documents
    case.skipped_files = skipped_files  # type: ignore[assignment]
    case.intake_notes = intake_notes
    return case


def build_case(
    msg: email.message.Message,
    attachment_paths: list[Path],
    scenario: str,
    data_dir: str | Path = "data",
) -> CaseRecord:
    """Assemble a :class:`CaseRecord` from a raw email message and attachment paths."""
    email_addr, disp_name = _parse_sender(msg)
    subject = str(msg.get("Subject", "")).strip()
    raw_msg_id = str(msg.get("Message-ID", "")).strip().strip("<> ")
    if not raw_msg_id:
        raw_msg_id = f"synthetic-{uuid.uuid4().hex[:12]}@falconix.local"

    date_hdr = str(msg.get("Date", "")).strip()
    try:
        if date_hdr:
            dt = email.utils.parsedate_to_datetime(date_hdr)
            received_at = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        else:
            received_at = datetime.now(timezone.utc)
    except Exception:
        received_at = datetime.now(timezone.utc)

    # Stage files into a folder if not already in one
    if attachment_paths and all(p.parent == attachment_paths[0].parent for p in attachment_paths):
        staging_dir = attachment_paths[0].parent
    else:
        staging_dir = Path(tempfile.mkdtemp(prefix="case_stage_"))
        for p in attachment_paths:
            if p.exists():
                safe_name = sanitize_filename(p.name)
                dest = staging_dir / safe_name
                import shutil
                shutil.copy2(p, dest)

    parsed = ParsedEmail(
        sender=email_addr,
        display_name=disp_name,
        reply_to=email_addr,
        subject=subject,
        message_id=raw_msg_id,
        date_str=date_hdr,
        received_at=received_at,
        attachment_folder=staging_dir,
        attachment_paths=attachment_paths,
    )
    return build_case_from_parsed_email(parsed, scenario, data_dir=data_dir)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def count_cases(source_path: Path) -> int:
    """Return total number of emails in source up front for progress UI."""
    return count_emails(source_path)


def iter_cases_from_source(
    path: Path,
    scenario: str,
    data_dir: str | Path = "data",
) -> Generator[CaseRecord, None, None]:
    """Lazily generate :class:`CaseRecord` objects from an email source."""
    for parsed in iter_parsed_emails(path):
        yield build_case_from_parsed_email(parsed, scenario, data_dir=data_dir)


def build_cases_from_source(
    path: Path,
    scenario: str,
    data_dir: str | Path = "data",
) -> list[CaseRecord]:
    """Import all emails from source into a list of :class:`CaseRecord` objects."""
    return list(iter_cases_from_source(path, scenario, data_dir=data_dir))
