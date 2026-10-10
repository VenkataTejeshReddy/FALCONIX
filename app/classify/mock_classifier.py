# Owner: Laptop B
"""INX – Mock Classifier (app/classify/mock_classifier.py).

Reads pre-generated fixture files (<sha256>.classify.json) from the
fixtures/synthetic_docs/ directory.  If no fixture file is found, returns the
most conservative result (unknown type, confidence 0.0) so mock mode never
silently guesses.

Fixture format (<sha256>.classify.json):
    {
        "doc_type": "resume",
        "confidence": 0.95,
        "layer": "fixture",
        "reasons": ["Fixture-based classification"]
    }
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from app.classify.base import ClassificationResult, Classifier
from app.schemas import DocumentRecord, DocumentType, ParsedDocument

logger = logging.getLogger(__name__)

_FIXTURE_DIR = Path(os.getenv("INX_FIXTURE_DIR", "fixtures/synthetic_docs"))
_CONSERVATIVE = ClassificationResult(
    doc_type=DocumentType.unknown,
    confidence=0.0,
    layer="none",
    reasons=["No fixture file found – conservative fallback"],
)


class MockClassifier:
    """Classifier backed by JSON fixture files.  Implements the Classifier protocol."""

    def __init__(self, fixture_dir: Path | None = None) -> None:
        self._fixture_dir = fixture_dir or _FIXTURE_DIR

    def classify(
        self, doc: DocumentRecord, parsed: ParsedDocument
    ) -> ClassificationResult:
        fixture_path = self._fixture_dir / f"{doc.sha256}.classify.json"
        if not fixture_path.exists():
            logger.debug(
                "MockClassifier: no fixture for sha256=%s (%s) – returning conservative",
                doc.sha256[:12],
                doc.filename,
            )
            return _CONSERVATIVE

        try:
            data = json.loads(fixture_path.read_text(encoding="utf-8"))
            return ClassificationResult(
                doc_type=DocumentType(data["doc_type"]),
                confidence=float(data.get("confidence", 0.0)),
                layer=data.get("layer", "fixture"),
                reasons=data.get("reasons", ["Fixture"]),
                scores=data.get("scores", {}),
            )
        except Exception as exc:
            logger.warning(
                "MockClassifier: failed to load fixture %s: %s", fixture_path, exc
            )
            return _CONSERVATIVE

    def unload(self) -> None:
        pass  # Nothing to unload for mock
