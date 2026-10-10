# Owner: Laptop B
"""INX – Mock Extractor (app/extract/mock_extractor.py).

Reads pre-generated fixture files (<sha256>.fields.json) from the
fixtures/synthetic_docs/ directory.  If no fixture file is found, returns an
empty list of FieldResults so the validate stage correctly flags all fields as
missing.  Never guesses.

Fixture format (<sha256>.fields.json):
    [
        {
            "field": "full_name",
            "value": "Rohan Verma",
            "status": "valid",
            "confidence": 0.97,
            "reason": "Fixture"
        },
        ...
    ]
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from app.extract.base import Extractor
from app.schemas import (
    DocumentRecord,
    DocumentType,
    FieldResult,
    FieldStatus,
    ParsedDocument,
)

logger = logging.getLogger(__name__)

_FIXTURE_DIR = Path(os.getenv("INX_FIXTURE_DIR", "fixtures/synthetic_docs"))


class MockExtractor:
    """Extractor backed by JSON fixture files.  Implements the Extractor protocol."""

    def __init__(self, fixture_dir: Path | None = None) -> None:
        self._fixture_dir = fixture_dir or _FIXTURE_DIR

    def extract(
        self,
        doc: DocumentRecord,
        parsed: ParsedDocument,
        doc_type: DocumentType,
        scenario: Any,
    ) -> list[FieldResult]:
        fixture_path = self._fixture_dir / f"{doc.sha256}.fields.json"
        if not fixture_path.exists():
            logger.debug(
                "MockExtractor: no fixture for sha256=%s (%s) – returning empty fields",
                doc.sha256[:12],
                doc.filename,
            )
            return []

        try:
            raw: list[dict] = json.loads(
                fixture_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            logger.warning(
                "MockExtractor: failed to load fixture %s: %s", fixture_path, exc
            )
            return []

        results: list[FieldResult] = []
        for entry in raw:
            try:
                status_str = entry.get("status", "missing")
                fr = FieldResult(
                    field=entry["field"],
                    doc_type=doc_type,
                    value=entry.get("value"),
                    ocr_value=entry.get("ocr_value", entry.get("value")),
                    evidence_quote=entry.get("evidence_quote"),
                    page=entry.get("page"),
                    status=FieldStatus(status_str),
                    reason=entry.get("reason", "Fixture"),
                    confidence=float(entry.get("confidence", 0.0)),
                    source_doc_id=doc.doc_id,
                )
                results.append(fr)
            except Exception as exc:
                logger.warning(
                    "MockExtractor: bad entry in %s: %s – %s",
                    fixture_path,
                    entry,
                    exc,
                )

        return results

    def unload(self) -> None:
        pass  # Nothing to unload for mock
