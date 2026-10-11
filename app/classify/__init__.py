# Owner: Laptop A
"""INX – Classify package."""

from app.classify.base import ClassificationResult, Classifier
try:
    from app.classify.classifier import DocumentClassifier, classify_documents
except ImportError:
    DocumentClassifier = None  # type: ignore
    classify_documents = None  # type: ignore
from app.classify.mock_classifier import MockClassifier
from app.classify.rules import classify_by_keywords, score_document_rules

__all__ = [
    "ClassificationResult",
    "Classifier",
    "DocumentClassifier",
    "MockClassifier",
    "classify_documents",
    "score_document_rules",
    "classify_by_keywords",
]
