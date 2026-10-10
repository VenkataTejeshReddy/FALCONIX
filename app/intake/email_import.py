# Owner: Laptop B
"""INX – Email intake: import .mbox / .eml files into raw case envelopes.

Responsibilities
----------------
* Open .mbox archives (multi-message) and .eml files (single message).
* Extract sender metadata, subject, Message-ID, and all attachments.
* Expand ZIP attachments transparently.
* Hand off to :mod:`app.intake.case_builder` to assemble :class:`CaseRecord`
  objects.

Public API
----------
``import_source(path, scenario) -> list[CaseRecord]``
"""

from __future__ import annotations

import email
import mailbox
import zipfile
from pathlib import Path
from typing import Generator

from app.schemas import CaseRecord


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iter_eml(path: Path) -> Generator[email.message.Message, None, None]:
    """Yield the single message from a .eml file."""
    raise NotImplementedError


def _iter_mbox(path: Path) -> Generator[email.message.Message, None, None]:
    """Yield each message from an .mbox archive."""
    raise NotImplementedError


def _expand_zip(zip_bytes: bytes, dest_dir: Path) -> list[Path]:
    """Write a ZIP attachment to *dest_dir* and return extracted file paths."""
    raise NotImplementedError


def _extract_attachments(
    msg: email.message.Message, dest_dir: Path
) -> list[Path]:
    """Return paths of all saved attachments (ZIPs are expanded in-place)."""
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def iter_messages(path: Path) -> Generator[email.message.Message, None, None]:
    """Yield :class:`email.message.Message` objects from a .mbox or .eml file.

    Args:
        path: Absolute path to a ``.mbox`` or ``.eml`` file.

    Yields:
        One :class:`email.message.Message` per email in the source.

    Raises:
        ValueError: If the file extension is not supported.
        FileNotFoundError: If *path* does not exist.
    """
    raise NotImplementedError


def import_source(path: Path, scenario: str) -> list[CaseRecord]:
    """Parse an email source file into a list of draft :class:`CaseRecord` objects.

    Each email becomes exactly one case.  Attachments (including ZIP contents)
    are saved to a temporary staging directory; ingest/ takes ownership next.

    Args:
        path: Path to a ``.mbox`` or ``.eml`` file.
        scenario: Scenario name (``"job_application"`` | ``"college"``).

    Returns:
        A list of :class:`CaseRecord` instances with ``documents`` populated
        but pipeline stages not yet run.
    """
    raise NotImplementedError
