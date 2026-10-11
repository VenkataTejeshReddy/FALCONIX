# Owner: Laptop A
"""Tests for Hierarchical Document Classifier (M4).

Includes:
1. Protocol conformance and interface tests.
2. Unit tests for Layer 1 rules (decisive vs non-decisive, margin).
3. Unit tests with BGE-M3 and Ollama VLM calls mocked.
4. Anonymity test verifying filename is never used.
5. Integration tests on real synthetic fixtures marked @pytest.mark.mac.
"""

from __future__ import annotations

import unittest.mock as mock
from pathlib import Path

import numpy as np
import pytest

from app.classify.base import ClassificationResult, Classifier
from app.classify.classifier import DocumentClassifier, classify_documents
from app.classify.rules import score_document_rules
from app.ingest.ingest import ingest
from app.parse.combined_reader import CombinedReader
from app.schemas import (
    CaseRecord,
    DocumentRecord,
    DocumentType,
    ParsedDocument,
    ParsedLine,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SYNTHETIC_DIR = _REPO_ROOT / "fixtures" / "synthetic_docs"


# ---------------------------------------------------------------------------
# 1. Protocol Conformance & Basic Properties
# ---------------------------------------------------------------------------


def test_classifier_protocol_conformance():
    """Verify DocumentClassifier conforms to Classifier protocol."""
    clf = DocumentClassifier()
    assert hasattr(clf, "classify")
    assert callable(clf.classify)
    assert hasattr(clf, "unload")
    assert callable(clf.unload)
    clf.unload()


def test_filename_never_used_for_classification():
    """Filename must never influence classification (e.g. marksheet.pdf containing ID card)."""
    clf = DocumentClassifier()
    # Create parsed document representing an ID card
    parsed = ParsedDocument(
        doc_id="test-anon",
        sha256="dummy_sha",
        pages=1,
        lines=[
            ParsedLine(text="GOVERNMENT IDENTIFICATION CARD", page=0),
            ParsedLine(text="Applicant Name: Rohan Verma", page=0),
            ParsedLine(text="ID Number: 236123456782", page=0),
            ParsedLine(text="Document Date: 2023-01-15", page=0),
        ],
        reader_name="test",
    )
    # Give it a misleading filename: "my_resume_or_marksheet.pdf"
    doc_meta = DocumentRecord(
        doc_id="test-anon",
        filename="my_resume_or_marksheet.pdf",
        sha256="dummy_sha",
        storage_path="/path/to/my_resume_or_marksheet.pdf",
        pages=1,
    )
    result = clf.classify(doc_meta, parsed)
    assert result.doc_type == DocumentType.id_document
    assert result.confidence >= 0.60
    assert result.layer == "rules"
    clf.unload()


# ---------------------------------------------------------------------------
# 2. Layer 1 Rules: Decisive vs Non-Decisive
# ---------------------------------------------------------------------------


def test_rules_dinner_menu_returns_unknown():
    """Dinner menu must be penalized by negative keywords and classified as unknown."""
    parsed = ParsedDocument(
        doc_id="menu-test",
        sha256="menu_sha",
        pages=1,
        lines=[
            ParsedLine(text="THE GOLDEN SPOON – DINNER MENU", page=0),
            ParsedLine(text="Appetizer: Bruschetta al Pomodoro – $8.00", page=0),
            ParsedLine(text="First Course: Truffle Tagliatelle – $18.50", page=0),
            ParsedLine(text="Main Course: Pan-Seared Sea Bass – $26.00", page=0),
            ParsedLine(text="Dessert: Classic Tiramisu – $7.50", page=0),
        ],
        reader_name="test",
    )
    top_t, score, is_decisive, reasons, scores = score_document_rules(parsed)
    assert top_t == DocumentType.unknown or score < 0.30
    assert is_decisive is False


def test_rules_decisive_margin_threshold():
    """Top score >= 0.60 and margin >= 0.25 required for Layer 1 decisiveness."""
    # Clearly decisive resume
    parsed_clear = ParsedDocument(
        doc_id="clear-resume",
        sha256="sha1",
        pages=1,
        lines=[
            ParsedLine(text="CURRICULUM VITAE", page=0),
            ParsedLine(text="Rohan Verma", page=0),
            ParsedLine(text="Work Experience: Senior Software Engineer at Tech Corp", page=0),
            ParsedLine(text="Employment History: 5 years experience in distributed systems", page=0),
            ParsedLine(text="Technical Skills: Python, PyTorch, C++", page=0),
            ParsedLine(text="Email: rohan@example.com", page=0),
            ParsedLine(text="Phone: +91 98765 43210", page=0),
            ParsedLine(text="Education: B.Tech Computer Science", page=0),
        ],
        reader_name="test",
    )
    top_t, score, is_decisive, _, _ = score_document_rules(parsed_clear)
    assert top_t == DocumentType.resume
    assert score >= 0.60
    assert is_decisive is True


# ---------------------------------------------------------------------------
# 3. Unit Tests with Model Calls Mocked
# ---------------------------------------------------------------------------


def test_layer2_embedding_fallback_mocked():
    """When Layer 1 is non-decisive, Layer 2 BGE-M3 similarity resolves the type."""
    clf = DocumentClassifier()

    # Ambiguous short text where Layer 1 is not decisive
    parsed = ParsedDocument(
        doc_id="ambiguous-doc",
        sha256="amb_sha",
        pages=1,
        lines=[
            ParsedLine(text="General Information Document", page=0),
            ParsedLine(text="Applicant profile notes and overview", page=0),
        ],
        reader_name="test",
    )
    doc_meta = DocumentRecord(
        doc_id="ambiguous-doc",
        filename="unnamed.bin",
        sha256="amb_sha",
        storage_path="/path/unnamed.bin",
        pages=1,
    )

    # Mock BGE-M3 SentenceTransformer
    mock_model = mock.MagicMock()
    # Produce mock embeddings
    # doc embedding dot product with resume description = 0.88, others = 0.20
    def mock_encode(text, normalize_embeddings=True):
        if "curriculum vitae" in text.lower() or "resume" in text.lower():
            vec = np.zeros(1024, dtype=np.float32)
            vec[0] = 1.0
            return vec
        elif "General Information" in text:
            vec = np.zeros(1024, dtype=np.float32)
            vec[0] = 0.90
            vec[1] = 0.10
            return vec
        else:
            vec = np.zeros(1024, dtype=np.float32)
            vec[5] = 1.0
            return vec

    mock_model.encode.side_effect = mock_encode
    clf._embedding_model = mock_model

    result = clf.classify(doc_meta, parsed)
    assert result.doc_type == DocumentType.resume
    assert result.layer in ("rules+embedding", "embedding")
    clf.unload()


def test_layer3_vlm_resolution_mocked(tmp_path: Path):
    """When Layers 1 and 2 disagree/fail, Layer 3 VLM resolves disagreement with reduced confidence."""
    clf = DocumentClassifier()

    img_file = tmp_path / "page_0.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

    doc_meta = DocumentRecord(
        doc_id="vlm-test",
        filename="anon_image.png",
        sha256="vlm_sha",
        storage_path=str(img_file),
        pages=1,
        page_images=[str(img_file)],
    )
    # Empty OCR text so Layers 1 and 2 cannot decide
    parsed = ParsedDocument(
        doc_id="vlm-test",
        sha256="vlm_sha",
        pages=1,
        lines=[],
        reader_name="test",
    )

    with mock.patch.object(clf, "_classify_layer3_vlm", return_value=(DocumentType.marksheet, 0.75, ["Layer 3 VLM: resolved"])):
        result = clf.classify(doc_meta, parsed)
        assert result.doc_type == DocumentType.marksheet
        assert result.confidence == 0.75
        assert result.layer == "vlm"

    clf.unload()


def test_unload_frees_memory():
    """Verify unload() frees model references and clears MPS cache."""
    clf = DocumentClassifier()
    clf._embedding_model = mock.MagicMock()
    clf._proto_embeddings = {"resume": np.zeros(1024)}

    clf.unload()
    assert clf._embedding_model is None
    assert clf._proto_embeddings is None


# ---------------------------------------------------------------------------
# 4. Integration Tests on Real Synthetic Fixtures (@pytest.mark.mac)
# ---------------------------------------------------------------------------


@pytest.mark.mac
def test_integration_classify_clean_fixtures():
    """Integration test running real DocumentClassifier against synthetic fixtures."""
    clf = DocumentClassifier()
    reader = CombinedReader()

    test_docs = [
        ("job_normal_resume.pdf", DocumentType.resume),
        ("job_normal_id.jpg", DocumentType.id_document),
        ("college_normal_marksheet.pdf", DocumentType.marksheet),
        ("college_normal_reg_letter.pdf", DocumentType.registration_letter),
        ("job_unknown_menu.pdf", DocumentType.unknown),
        ("job_mislabeled_id_as_marksheet.pdf", DocumentType.id_document),
    ]

    try:
        for fname, expected_type in test_docs:
            fpath = _SYNTHETIC_DIR / fname
            if not fpath.exists():
                continue

            ing_res = ingest(fpath, data_dir=_REPO_ROOT / "data")
            page_paths = [Path(p) for p in ing_res.page_paths]
            # Anonymized doc meta (filename hidden)
            meta = DocumentRecord(
                doc_id=f"integ-{ing_res.sha256[:8]}",
                filename="unnamed.bin",
                sha256=ing_res.sha256,
                storage_path=str(ing_res.original_path),
                pages=len(page_paths),
                page_images=[str(p) for p in page_paths],
                pdf_has_text_layer=ing_res.pdf_has_text_layer,
            )
            parsed = reader.read(page_paths, meta)
            result = clf.classify(meta, parsed)

            assert result.doc_type == expected_type, (
                f"Mismatch on {fname}: expected {expected_type.value}, got {result.doc_type.value} (layer={result.layer})"
            )
    finally:
        clf.unload()
        reader.unload()
