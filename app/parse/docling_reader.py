# Owner: Laptop A
"""INX – Docling reader: high-fidelity layout-aware PDF/image parsing.

Wraps the ``docling`` library to extract text, tables, and bounding boxes
from PDFs and scanned images.  Docling is only available on Laptop A.

Reader name: ``"docling"``
"""

from __future__ import annotations

from pathlib import Path

from app.parse.base import Reader
from app.schemas import DocumentRecord, ParsedDocument


class DoclingReader:
    """Docling-backed reader – implements the :class:`Reader` protocol.

    Parameters
    ----------
    device:
        Compute device string passed to Docling (``"cpu"`` | ``"mps"`` |
        ``"cuda"``).  Defaults to ``"mps"`` for Apple Silicon.
    """

    name: str = "docling"

    def __init__(self, device: str = "mps") -> None:
        self._device = device

    def read(
        self,
        page_image_paths: list[Path],
        doc_meta: DocumentRecord,
    ) -> ParsedDocument:
        """Parse a document using Docling's pipeline.

        Args:
            page_image_paths: Ordered page images produced by the PDF renderer.
            doc_meta: Source document metadata.

        Returns:
            A :class:`ParsedDocument` with rich layout data including tables
            and per-line bounding boxes.
        """
        raise NotImplementedError


assert isinstance(DoclingReader(), Reader), "DoclingReader does not satisfy Reader protocol"
