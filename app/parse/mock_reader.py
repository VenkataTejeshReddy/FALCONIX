# Owner: Laptop A (used on both; no model dependency)
"""INX – Mock reader: loads pre-baked fixture JSON files as ParsedDocuments.

Purpose
-------
Allows the full pipeline to run end-to-end on *both* laptops and in CI
without any ML model installed.  For each document the reader looks up a
fixture file in ``fixtures/`` using the SHA-256 digest or a canonical name.

Fixture lookup order
--------------------
1. ``fixtures/<sha256>.json``
2. ``fixtures/<filename_stem>.json``
3. ``fixtures/default_<scenario>.json``  (fallback)
4. A minimal empty :class:`ParsedDocument` if no fixture matches (warns).

Fixture format
--------------
The JSON file is the serialised form of :class:`ParsedDocument` (``model_dump()``
output).  Use ``scripts/make_synthetic_docs.py`` to generate them.
"""

from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path
from typing import Optional

from app.parse.base import Reader
from app.schemas import DocumentRecord, ParsedDocument, ParsedLine

logger = logging.getLogger(__name__)

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"


class MockReader:
    """Fixture-based reader – implements the :class:`Reader` protocol.

    Parameters
    ----------
    fixtures_dir:
        Override the default ``fixtures/`` directory (useful in tests).
    scenario:
        Scenario name used for the generic fallback fixture.
    """

    name: str = "mock"

    def __init__(
        self,
        fixtures_dir: Optional[Path] = None,
        scenario: str = "job_application",
    ) -> None:
        self._fixtures_dir = fixtures_dir or _FIXTURES_DIR
        self._scenario = scenario

    # ------------------------------------------------------------------
    # Fixture resolution
    # ------------------------------------------------------------------

    def _find_fixture(self, sha256: str, filename: str) -> Optional[Path]:
        """Return the first matching fixture path, or None."""
        stem = Path(filename).stem

        candidates = [
            self._fixtures_dir / f"{sha256}.json",
            self._fixtures_dir / f"{stem}.json",
            self._fixtures_dir / f"default_{self._scenario}.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                logger.debug("MockReader: fixture match %s", candidate)
                return candidate
        return None

    def _load_fixture(self, path: Path) -> ParsedDocument:
        """Deserialise a fixture JSON file into a :class:`ParsedDocument`."""
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return ParsedDocument.model_validate(data)

    def _empty_document(self, doc_meta: DocumentRecord) -> ParsedDocument:
        """Return a minimal valid :class:`ParsedDocument` when no fixture exists."""
        warnings.warn(
            f"MockReader: no fixture found for {doc_meta.filename!r} "
            f"(sha256={doc_meta.sha256[:8]}…). Returning empty document.",
            UserWarning,
            stacklevel=3,
        )
        return ParsedDocument(
            sha256=doc_meta.sha256,
            pages=1,
            reader_name=self.name,
            text_by_page={0: ""},
        )

    # ------------------------------------------------------------------
    # Reader protocol
    # ------------------------------------------------------------------

    def read(
        self,
        page_image_paths: list[Path],
        doc_meta: DocumentRecord,
    ) -> ParsedDocument:
        """Load a fixture JSON and return it as a :class:`ParsedDocument`.

        ``page_image_paths`` is accepted for API compatibility but is not used.

        Args:
            page_image_paths: Ignored by this reader.
            doc_meta: Used to look up the fixture by sha256 and filename.

        Returns:
            The fixture :class:`ParsedDocument`, or a minimal empty one with
            a ``UserWarning`` if no fixture matches.
        """
        fixture_path = self._find_fixture(doc_meta.sha256, doc_meta.filename)
        if fixture_path is None:
            return self._empty_document(doc_meta)

        doc = self._load_fixture(fixture_path)
        # Ensure the doc_id and sha256 match the live record
        doc = doc.model_copy(
            update={
                "sha256": doc_meta.sha256,
                "reader_name": self.name,
            }
        )
        return doc


# Verify the class satisfies the Reader protocol at import time.
assert isinstance(MockReader(), Reader), "MockReader does not satisfy Reader protocol"
