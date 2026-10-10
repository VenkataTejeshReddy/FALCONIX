# Owner: Laptop B
"""INX – Email intake: import .mbox / .eml files into raw case envelopes.

Responsibilities
----------------
* Open .mbox archives (multi-message) and .eml files (single message) lazily.
* Extract sender metadata (sender, display name, reply-to), subject, Message-ID,
  and date.
* Extract and save all attachments into a temporary directory per email.
* Deduplicate emails by Message-ID.
* Never trust attachment filenames (strip directories and traversal tokens).
* Report total email counts up front so UI/CLI can display progress.
"""

from __future__ import annotations

import email
import email.message
import email.policy
import email.utils
import hashlib
import mailbox
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from app.schemas import CaseRecord


@dataclass
class ParsedEmail:
    """Represents the extracted metadata and staged attachments of one email."""

    sender: str
    display_name: str
    reply_to: str
    subject: str
    message_id: str
    date_str: str
    received_at: datetime
    attachment_folder: Path
    attachment_paths: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    raw_message: email.message.Message | None = None


# ---------------------------------------------------------------------------
# Path & Filename Sanitation
# ---------------------------------------------------------------------------


def sanitize_filename(filename: str | None, index: int = 1) -> str:
    """Strip directory traversal, path separators, and illegal characters.

    Never trusts filenames supplied by email attachments.
    """
    if not filename:
        return f"attachment_{index}.bin"

    # Normalize backslashes and forward slashes, take only the basename
    cleaned = filename.replace("\\", "/").strip()
    cleaned = cleaned.split("/")[-1].strip()
    cleaned = Path(cleaned).name

    # Remove dangerous/illegal characters and null bytes
    cleaned = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', "_", cleaned).strip()
    # Strip leading/trailing dots or spaces
    cleaned = cleaned.strip(". ")

    if not cleaned:
        return f"attachment_{index}.bin"
    return cleaned


# ---------------------------------------------------------------------------
# Lazy Message Iteration
# ---------------------------------------------------------------------------


def _iter_eml(path: Path) -> Generator[email.message.Message, None, None]:
    """Yield the single message from a .eml file."""
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=email.policy.default)
        yield msg


def _iter_mbox(path: Path) -> Generator[email.message.Message, None, None]:
    """Yield each message lazily from an .mbox archive."""
    mbox = mailbox.mbox(str(path))
    try:
        for msg in mbox:
            # Convert mailbox message to standard email.message.Message
            raw_bytes = msg.as_bytes()
            parsed = email.message_from_bytes(raw_bytes, policy=email.policy.default)
            yield parsed
    finally:
        mbox.close()


def count_emails(path: Path) -> int:
    """Report total emails in the source up front (for UI progress display)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Source file not found: {p}")
    ext = p.suffix.lower()
    if ext == ".eml":
        return 1
    elif ext == ".mbox":
        mbox = mailbox.mbox(str(p))
        try:
            return len(mbox)
        finally:
            mbox.close()
    else:
        raise ValueError(f"Unsupported email file type: '{ext}'. Supported: .mbox, .eml")


def iter_messages(path: Path) -> Generator[email.message.Message, None, None]:
    """Yield :class:`email.message.Message` objects lazily from .mbox or .eml."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Source file not found: {p}")
    ext = p.suffix.lower()
    if ext == ".eml":
        yield from _iter_eml(p)
    elif ext == ".mbox":
        yield from _iter_mbox(p)
    else:
        raise ValueError(f"Unsupported email file type: '{ext}'. Supported: .mbox, .eml")


# ---------------------------------------------------------------------------
# Attachment Extraction
# ---------------------------------------------------------------------------


def _extract_attachments(
    msg: email.message.Message, dest_dir: Path
) -> list[Path]:
    """Extract and save all attachments from *msg* into *dest_dir* with safe filenames."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    seen_names: set[str] = set()
    idx = 1

    for part in msg.walk():
        if part.is_multipart():
            continue

        filename = part.get_filename()
        content_disposition = part.get_content_disposition()
        if not filename and content_disposition != "attachment":
            continue

        safe_name = sanitize_filename(filename, index=idx)
        # Disambiguate if duplicate attachment names appear within one message
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix
        disambiguated = safe_name
        dup_counter = 1
        while disambiguated in seen_names:
            disambiguated = f"{stem}_{dup_counter}{suffix}"
            dup_counter += 1
        seen_names.add(disambiguated)

        payload = part.get_payload(decode=True)
        if payload is not None:
            out_file = dest_dir / disambiguated
            out_file.write_bytes(payload)
            saved_paths.append(out_file)
            idx += 1

    return saved_paths


# ---------------------------------------------------------------------------
# Lazy Parsed Email Streaming
# ---------------------------------------------------------------------------


def iter_parsed_emails(
    path: Path, work_dir: Path | None = None
) -> Generator[ParsedEmail, None, None]:
    """Parse .mbox/.eml lazily, saving attachments into per-email folders and deduping by Message-ID.

    Yields:
        :class:`ParsedEmail` instances.
    """
    seen_message_ids: set[str] = set()
    base_work_dir = (
        Path(work_dir)
        if work_dir is not None
        else Path(tempfile.gettempdir()) / "falconix_intake"
    )
    base_work_dir.mkdir(parents=True, exist_ok=True)

    email_idx = 0
    for msg in iter_messages(path):
        email_idx += 1

        # Sender & display name
        from_hdr = str(msg.get("From", ""))
        display_name, sender_addr = email.utils.parseaddr(from_hdr)

        # Reply-To
        reply_to_hdr = str(msg.get("Reply-To", ""))
        _, reply_to_addr = email.utils.parseaddr(reply_to_hdr)
        if not reply_to_addr:
            reply_to_addr = sender_addr

        # Subject & Date
        subject = str(msg.get("Subject", "")).strip()
        date_hdr = str(msg.get("Date", "")).strip()
        received_at: datetime
        try:
            if date_hdr:
                dt = email.utils.parsedate_to_datetime(date_hdr)
                received_at = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            else:
                received_at = datetime.now(timezone.utc)
        except Exception:
            received_at = datetime.now(timezone.utc)

        # Message-ID & Deduplication
        raw_msg_id = str(msg.get("Message-ID", "")).strip()
        cleaned_msg_id = raw_msg_id.strip("<> ").strip()
        if not cleaned_msg_id:
            # Fallback synthetic ID if missing
            digest = hashlib.sha256(
                f"{sender_addr}_{subject}_{date_hdr}_{email_idx}".encode()
            ).hexdigest()[:16]
            cleaned_msg_id = f"synthetic-{digest}@falconix.local"

        if cleaned_msg_id in seen_message_ids:
            # Deduplicate: skip duplicate Message-ID
            continue
        seen_message_ids.add(cleaned_msg_id)

        # Attachment staging folder
        folder_token = hashlib.sha256(cleaned_msg_id.encode()).hexdigest()[:12]
        email_dest_dir = base_work_dir / f"email_{email_idx}_{folder_token}"
        attachment_paths = _extract_attachments(msg, email_dest_dir)

        notes: list[str] = []
        if not attachment_paths:
            notes.append("Email has no attachments.")

        yield ParsedEmail(
            sender=sender_addr,
            display_name=display_name,
            reply_to=reply_to_addr,
            subject=subject,
            message_id=cleaned_msg_id,
            date_str=date_hdr,
            received_at=received_at,
            attachment_folder=email_dest_dir,
            attachment_paths=attachment_paths,
            notes=notes,
            raw_message=msg,
        )


def import_source(
    path: Path, scenario: str, data_dir: Path | str = "data"
) -> list[CaseRecord]:
    """Import an email source into a list of CaseRecord objects."""
    from app.intake.case_builder import build_cases_from_source

    return build_cases_from_source(path, scenario, data_dir=data_dir)
