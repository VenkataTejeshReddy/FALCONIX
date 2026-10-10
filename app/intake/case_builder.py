# Owner: Laptop B
"""INX – Case builder: assembles a CaseRecord from a parsed email message.

Takes the raw :class:`email.message.Message` produced by
:mod:`app.intake.email_import` together with the saved attachment paths and
produces a fully structured :class:`CaseRecord` ready for the pipeline.

Public API
----------
``build_case(msg, attachment_paths, scenario) -> CaseRecord``
"""

from __future__ import annotations

import email
from pathlib import Path

from app.schemas import CaseRecord, DocumentRecord


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_sender(msg: email.message.Message) -> tuple[str, str]:
    """Return (email_address, display_name) from the From: header."""
    raise NotImplementedError


def _make_document_record(path: Path) -> DocumentRecord:
    """Create a :class:`DocumentRecord` stub for a staged attachment path.

    SHA-256 and storage_path are populated; parsing happens later.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_case(
    msg: email.message.Message,
    attachment_paths: list[Path],
    scenario: str,
) -> CaseRecord:
    """Assemble a :class:`CaseRecord` from a parsed email and its attachments.

    Args:
        msg: Parsed email message.
        attachment_paths: Paths to all staged attachment files (post ZIP-expand).
        scenario: Scenario name for this batch.

    Returns:
        A :class:`CaseRecord` with ``sender_email``, ``sender_name``,
        ``message_id``, ``subject``, and ``documents`` populated.
        ``workflow_status`` is set to ``received``.
    """
    raise NotImplementedError
