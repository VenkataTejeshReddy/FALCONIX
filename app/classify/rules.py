# Owner: Laptop A
"""INX – Rule-based document type classification.

Applies deterministic keyword/layout rules to classify a :class:`ParsedDocument`
into a :class:`DocumentType` before any ML-based classification runs.
Rules are fast, interpretable, and give classify/ a strong prior.
"""

from __future__ import annotations

from app.schemas import DocumentType, ParsedDocument


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------

# Each rule is a tuple: (DocumentType, list[indicator_phrases])
# All phrases are matched case-insensitively against the full document text.
_KEYWORD_RULES: list[tuple[DocumentType, list[str]]] = [
    (DocumentType.resume, ["curriculum vitae", "resume", "work experience", "employment history"]),
    (DocumentType.cover_letter, ["dear hiring", "i am writing to apply", "cover letter"]),
    (DocumentType.transcript, ["academic transcript", "grade report", "semester results", "transcript of records"]),
    (DocumentType.degree_certificate, ["degree certificate", "bachelor of", "master of", "doctor of", "awarded the degree"]),
    (DocumentType.id_document, ["national id", "passport", "aadhaar", "date of birth", "id number", "identification"]),
    (DocumentType.marksheet, ["mark sheet", "marksheet", "marks obtained", "total marks", "percentage"]),
    (DocumentType.registration_letter, ["registration number", "registered student", "enrollment confirmation"]),
    (DocumentType.offer_letter, ["offer of admission", "offer letter", "pleased to offer"]),
    (DocumentType.reference_letter, ["to whom it may concern", "letter of recommendation", "reference letter"]),
]


def classify_by_keywords(
    doc: ParsedDocument,
    threshold: float = 0.0,
) -> tuple[DocumentType, float]:
    """Score a document against keyword rules and return the best match.

    Args:
        doc: The parsed document to classify.
        threshold: Minimum confidence required to return a non-unknown type.

    Returns:
        A (DocumentType, confidence) tuple.  Confidence is the fraction of
        indicator phrases matched for the winning type (0.0 – 1.0).
        Returns ``(DocumentType.unknown, 0.0)`` when no rule fires above the
        threshold.
    """
    raise NotImplementedError


def classify_by_layout(doc: ParsedDocument) -> tuple[DocumentType, float]:
    """Use structural signals (table density, line count, etc.) to classify.

    Complements :func:`classify_by_keywords` for documents with sparse text.

    Args:
        doc: The parsed document.

    Returns:
        A (DocumentType, confidence) tuple.
    """
    raise NotImplementedError
