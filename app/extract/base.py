# Owner: Laptop A
"""INX – Base protocol for field extraction."""

from __future__ import annotations

from typing import Any, Protocol

from app.schemas import DocumentRecord, DocumentType, FieldResult, ParsedDocument


class Extractor(Protocol):
    def extract(
        self,
        doc: DocumentRecord,
        parsed: ParsedDocument,
        doc_type: DocumentType,
        scenario: Any,
    ) -> list[FieldResult]:  # scenario = object from app.config.load_scenario
        ...

    def unload(self) -> None: ...
