# Owner: Laptop B
"""INX – Tests: Classifier and Extractor Protocols."""

from __future__ import annotations

from typing import Any

from app.classify.base import ClassificationResult, Classifier
from app.extract.base import Extractor
from app.schemas import DocumentRecord, DocumentType, FieldResult, ParsedDocument


class DummyClassifier:
    def classify(
        self, doc: DocumentRecord, parsed: ParsedDocument
    ) -> ClassificationResult:
        return ClassificationResult(
            doc_type=DocumentType.resume,
            confidence=1.0,
            layer="rules",
            reasons=["test"],
            scores={"resume": 1.0},
        )

    def unload(self) -> None:
        pass


class DummyExtractor:
    def extract(
        self,
        doc: DocumentRecord,
        parsed: ParsedDocument,
        doc_type: DocumentType,
        scenario: Any,
    ) -> list[FieldResult]:
        return []

    def unload(self) -> None:
        pass


def test_classifier_protocol_conformance():
    """Verify that a trivial class conforms to the Classifier protocol."""
    instance: Classifier = DummyClassifier()
    assert hasattr(instance, "classify")
    assert callable(instance.classify)
    assert hasattr(instance, "unload")
    assert callable(instance.unload)


def test_extractor_protocol_conformance():
    """Verify that a trivial class conforms to the Extractor protocol."""
    instance: Extractor = DummyExtractor()
    assert hasattr(instance, "extract")
    assert callable(instance.extract)
    assert hasattr(instance, "unload")
    assert callable(instance.unload)
