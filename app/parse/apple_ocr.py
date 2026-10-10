# Owner: Laptop A
"""INX – Apple Vision OCR reader (macOS only).

Uses ``ocrmac`` to call the native Vision framework for high-accuracy OCR on
Apple Silicon.  This reader is only available on macOS 12+ (Laptop A, M4).

Reader name: ``"apple_ocr"``
"""

from __future__ import annotations

from pathlib import Path

from app.parse.base import Reader
from app.schemas import DocumentRecord, ParsedDocument


class AppleOCRReader:
    """Apple Vision OCR reader – implements the :class:`Reader` protocol.

    Parameters
    ----------
    language_correction:
        Whether to enable Vision's language correction heuristics.
    recognition_level:
        ``"accurate"`` (default) or ``"fast"``.
    """

    name: str = "apple_ocr"

    def __init__(
        self,
        language_correction: bool = True,
        recognition_level: str = "accurate",
    ) -> None:
        self._language_correction = language_correction
        self._recognition_level = recognition_level

    def read(
        self,
        page_image_paths: list[Path],
        doc_meta: DocumentRecord,
    ) -> ParsedDocument:
        """Run Apple Vision OCR over each page image.

        Args:
            page_image_paths: PNG paths, one per page.
            doc_meta: Source document metadata.

        Returns:
            A :class:`ParsedDocument` with per-line bounding boxes and
            confidence scores from the Vision framework.
        """
        raise NotImplementedError


assert isinstance(AppleOCRReader(), Reader), "AppleOCRReader does not satisfy Reader protocol"
