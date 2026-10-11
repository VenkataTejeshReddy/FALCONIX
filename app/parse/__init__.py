# Owner: Laptop A
"""INX – Parse package."""

from app.parse.apple_ocr import AppleOCRReader
from app.parse.base import Reader
from app.parse.combined_reader import CombinedReader
from app.parse.docling_reader import DoclingReader
from app.parse.mock_reader import MockReader
from app.parse.rapid_ocr_fallback import RapidOCRReader

__all__ = [
    "Reader",
    "CombinedReader",
    "AppleOCRReader",
    "DoclingReader",
    "RapidOCRReader",
    "MockReader",
]
