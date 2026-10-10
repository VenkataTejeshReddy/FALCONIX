# Owner: Laptop A
"""INX – Base protocol and data structures for document classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.schemas import DocumentRecord, DocumentType, ParsedDocument


@dataclass
class ClassificationResult:
    doc_type: DocumentType
    confidence: float  # 0..1
    layer: str  # "rules" | "embedding" | "vlm" | "fixture" | "none"
    reasons: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(
        default_factory=dict
    )  # per type, for the audit trail


class Classifier(Protocol):
    def classify(
        self, doc: DocumentRecord, parsed: ParsedDocument
    ) -> ClassificationResult: ...

    def unload(self) -> None: ...
