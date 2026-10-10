# Owner: Laptop A
"""INX – Reader Protocol and base utilities for the parse layer.

All concrete readers (Docling, Apple Vision OCR, Qwen3-VL, Mock) must
implement the :class:`Reader` Protocol defined here.  This ensures that
classify/ and extract/ can swap readers without any code changes.

Protocol
--------
``read(page_image_paths, doc_meta) -> ParsedDocument``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.schemas import DocumentRecord, ParsedDocument


@runtime_checkable
class Reader(Protocol):
    """Duck-type contract that every parse reader must satisfy.

    Attributes
    ----------
    name : str
        Short identifier used in ``ParsedDocument.reader_name``
        (e.g. ``"docling"``, ``"apple_ocr"``, ``"vlm"``, ``"mock"``).
    """

    name: str

    def read(
        self,
        page_image_paths: list[Path],
        doc_meta: DocumentRecord,
    ) -> ParsedDocument:
        """Convert page images (and optional raw bytes) into a ParsedDocument.

        Args:
            page_image_paths: Ordered list of PNG/JPEG paths – one per page.
                The caller guarantees these are read-only copies.
            doc_meta: The :class:`DocumentRecord` stub for this file.
                Readers may inspect ``mime_type``, ``filename``, etc.

        Returns:
            A :class:`ParsedDocument` with at minimum ``sha256``, ``pages``,
            and ``text_by_page`` populated.
        """
        ...


# ---------------------------------------------------------------------------
# Shared utility functions used by concrete readers
# ---------------------------------------------------------------------------


def render_pdf_to_images(pdf_path: Path, dpi: int = 150) -> list[Path]:
    """Render each page of a PDF to a temporary PNG and return the paths.

    Uses PyMuPDF (fitz).  The caller is responsible for cleaning up the
    temporary directory when done.

    Args:
        pdf_path: Path to the source PDF file.
        dpi: Resolution for rendering (default 150 dpi).

    Returns:
        Ordered list of PNG paths, one per page.

    Raises:
        ImportError: If ``pymupdf`` is not installed.
        FileNotFoundError: If *pdf_path* does not exist.
    """
    raise NotImplementedError


def image_to_base64(image_path: Path) -> str:
    """Return a base64-encoded string for an image file (for VLM prompts).

    Args:
        image_path: Path to a PNG or JPEG file.

    Returns:
        Base64-encoded bytes as a ``str`` (no ``data:`` URI prefix).
    """
    raise NotImplementedError


def merge_parsed_documents(parts: list[ParsedDocument]) -> ParsedDocument:
    """Combine multiple :class:`ParsedDocument` objects (e.g. per-reader outputs).

    Used by the reconcile layer when multiple readers process the same file.

    Args:
        parts: Non-empty list of :class:`ParsedDocument` objects for the same
            source file.  All must share the same ``sha256``.

    Returns:
        A merged :class:`ParsedDocument` with concatenated lines and tables
        and a ``reader_name`` of ``"merged"``.

    Raises:
        ValueError: If *parts* is empty or sha256 values differ.
    """
    raise NotImplementedError
