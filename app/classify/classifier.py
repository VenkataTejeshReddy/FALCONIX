# Owner: Laptop A
"""INX – Document type classifier.

Combines rule-based signals (:mod:`app.classify.rules`) with an optional
embedding-based fallback to assign a :class:`DocumentType` and confidence
score to every :class:`DocumentRecord` in a case.

Public API
----------
``classify_documents(case) -> None``  (mutates case.documents in-place)
"""

from __future__ import annotations

from app.schemas import CaseRecord, DocumentRecord, DocumentType


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_one(record: DocumentRecord, scenario: str) -> None:
    """Classify a single document record in-place.

    Runs keyword rules first; falls back to embedding similarity if the
    keyword confidence is below the scenario threshold.

    Args:
        record: The :class:`DocumentRecord` to classify.
        scenario: Scenario name used to load thresholds from config.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_documents(case: CaseRecord) -> None:
    """Classify all documents in *case* and update their ``doc_type`` fields.

    Mutates each :class:`DocumentRecord` in ``case.documents`` in-place,
    setting ``doc_type`` and ``doc_type_confidence``.  Documents whose
    ``is_readable`` flag is ``False`` are skipped and left as
    ``DocumentType.unknown``.

    Args:
        case: The active :class:`CaseRecord`.  ``documents`` must be
            populated by the intake layer before calling this function.
    """
    raise NotImplementedError
