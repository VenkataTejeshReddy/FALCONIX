# Owner: Laptop A
"""INX – Rule-based document type classification (Layer 1).

Scores each DocumentType from the OCR text and layout signals of all pages.
A decision is considered decisive if:
    top_score >= 0.6 and (top_score - second_score) >= 0.25
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from app.schemas import DocumentType, ParsedDocument

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PROTOTYPES_PATH = _REPO_ROOT / "config" / "doc_type_prototypes.yaml"


def load_doc_prototypes(path: Optional[Path] = None) -> dict[str, Any]:
    """Load doc_type_prototypes.yaml configuration."""
    cfg_path = path or _PROTOTYPES_PATH
    if not cfg_path.exists():
        logger.warning("Prototypes file not found at %s", cfg_path)
        return {}
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# Pre-compiled layout patterns
_ID_NUMBER_PATTERN = re.compile(r"\b\d{12}\b|\b\d{4}\s\d{4}\s\d{4}\b|\b[A-Z]\d{7,9}\b")
_REG_NUMBER_PATTERN = re.compile(r"\b[A-Z0-9]{2,6}[-\s]\d{4}[-\s]\d{3,6}\b|roll\s*(?:no|number)|reg(?:istration)?\s*(?:no|number)", re.I)
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"\+?\d{1,3}[-.\s]?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}")
_GRADE_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\s*(?:cgpa|gpa|%)\b|\bgrade\s*:\s*[A-O][+-]?\b", re.I)


def extract_parsed_text(parsed: ParsedDocument) -> str:
    """Extract full document text, using text_by_page or falling back to lines."""
    text = parsed.full_text
    if not text.strip() and parsed.lines:
        text = "\n".join(line.text for line in parsed.lines if line.text)
    return text


def score_document_rules(
    parsed: ParsedDocument,
    prototypes: Optional[dict[str, Any]] = None,
) -> tuple[DocumentType, float, bool, list[str], dict[str, float]]:
    """Score all document types using keyword and layout rules over parsed document text.

    Args:
        parsed: The ParsedDocument containing all lines and tables.
        prototypes: Optional prototype dict from doc_type_prototypes.yaml.

    Returns:
        (top_type, top_score, is_decisive, reasons, all_scores)
    """
    protos = prototypes or load_doc_prototypes()
    raw_text = extract_parsed_text(parsed)
    full_text = raw_text.lower()
    total_lines = len(parsed.lines)
    has_tables = len(parsed.tables) > 0 or any("table" in l.lower() or "\t" in l for l in full_text.splitlines())

    raw_scores: dict[str, float] = {}
    reasons_by_type: dict[str, list[str]] = {}

    for type_name, proto in protos.items():
        score = 0.0
        reasons: list[str] = []

        keywords = proto.get("keywords", {})
        negative_keywords = proto.get("negative_keywords", {})
        layout_hints = proto.get("layout_hints", {})

        # 1. Positive keyword scoring
        # Denominator is sum of top 3 weights (title + key fields), since synonyms are mutually exclusive
        top_k_weights = sorted(keywords.values(), reverse=True)[:3] if keywords else [1.0]
        max_possible = max(1.0, sum(top_k_weights))
        matched_kw_weight = 0.0
        for kw, weight in keywords.items():
            kw_clean = kw.lower().strip()
            # Whole word or phrase search
            if re.search(r"(?:^|[^\w])" + re.escape(kw_clean) + r"(?:[^\w]|$)", full_text):
                matched_kw_weight += weight
                reasons.append(f"+keyword '{kw}' ({weight:.1f})")

        # 2. Negative keyword penalty
        penalty = 0.0
        for neg_kw, weight in negative_keywords.items():
            neg_clean = neg_kw.lower().strip()
            if re.search(r"(?:^|[^\w])" + re.escape(neg_clean) + r"(?:[^\w]|$)", full_text):
                penalty += weight
                reasons.append(f"-neg_keyword '{neg_kw}' (-{weight:.1f})")

        # Base normalized keyword score
        kw_ratio = min(1.0, matched_kw_weight / max_possible)
        score = max(0.0, kw_ratio - (penalty * 0.35))

        # 3. Layout hints bonus / penalty
        if type_name == "id_document":
            if _ID_NUMBER_PATTERN.search(raw_text):
                score += 0.25
                reasons.append("+layout id_number_pattern (+0.25)")
            if parsed.pages <= 2 and (matched_kw_weight > 0 or _ID_NUMBER_PATTERN.search(raw_text)):
                score += 0.10
            if "menu" in full_text:
                score = 0.0

        elif type_name == "resume":
            has_email = bool(_EMAIL_PATTERN.search(raw_text))
            has_phone = bool(_PHONE_PATTERN.search(raw_text))
            if has_email and has_phone:
                score += 0.25
                reasons.append("+layout contact_info (+0.25)")
            if total_lines >= 8 and (matched_kw_weight > 0 or (has_email and has_phone)):
                score += 0.10

        elif type_name == "marksheet":
            if has_tables and (matched_kw_weight > 0 or _GRADE_PATTERN.search(raw_text)):
                score += 0.25
                reasons.append("+layout table_structure (+0.25)")
            if _GRADE_PATTERN.search(raw_text):
                score += 0.25
                reasons.append("+layout grade_pattern (+0.25)")

        elif type_name == "registration_letter":
            if _REG_NUMBER_PATTERN.search(raw_text):
                score += 0.30
                reasons.append("+layout reg_number_pattern (+0.30)")

        # Cap score at 1.0
        final_score = round(min(1.0, max(0.0, score)), 4)
        raw_scores[type_name] = final_score
        reasons_by_type[type_name] = reasons

    # Rank types by score descending
    sorted_types = sorted(raw_scores.items(), key=lambda kv: kv[1], reverse=True)
    if not sorted_types:
        return DocumentType.unknown, 0.0, False, ["No prototype definitions"], {}

    top_type_str, top_score = sorted_types[0]
    second_score = sorted_types[1][1] if len(sorted_types) > 1 else 0.0
    margin = top_score - second_score

    # Decisive condition: top_score >= 0.6 and margin >= 0.25
    is_decisive = (top_score >= 0.60) and (margin >= 0.25)

    doc_type = DocumentType(top_type_str) if top_type_str in DocumentType._value2member_map_ else DocumentType.unknown
    if top_score < 0.30:
        doc_type = DocumentType.unknown

    decisive_reasons = reasons_by_type.get(top_type_str, [])
    if is_decisive:
        decisive_reasons.insert(0, f"Layer 1 decisive: score={top_score:.2f}, margin={margin:.2f}>=0.25")
    else:
        decisive_reasons.insert(0, f"Layer 1 non-decisive: score={top_score:.2f}, margin={margin:.2f}")

    return doc_type, top_score, is_decisive, decisive_reasons, raw_scores


def classify_by_keywords(
    doc: ParsedDocument,
    threshold: float = 0.60,
) -> tuple[DocumentType, float]:
    """Public helper matching legacy API."""
    doc_type, score, is_decisive, _, _ = score_document_rules(doc)
    if is_decisive and score >= threshold:
        return doc_type, score
    return DocumentType.unknown, 0.0
