# Owner: Laptop A
"""INX – Evidence grounding and text normalisation.

Rules:
1. Normalise text: casefold, collapse whitespace, strip punctuation, keep digits.
2. Quote grounding: evidence_quote must appear in page OCR text with
   rapidfuzz.fuzz.partial_ratio >= 90, else unreliable.
3. Value grounding:
   - ids, dates, numbers, emails: NO fuzzy matching – must match exactly after
     normalisation, otherwise unreliable.
   - names: token fuzzy >= 90.
   - text fields: substring or token fuzzy >= 90.
"""

from __future__ import annotations

import re
import string
from typing import Optional

from rapidfuzz import fuzz

from app.schemas import FieldResult, ParsedDocument
from app.validate.dates import parse_date
from app.validate.identifiers import normalise_id


def normalise_text(text: Optional[str]) -> str:
    """Normalise arbitrary text: casefold, strip punctuation, keep digits, collapse whitespace."""
    if not text:
        return ""
    # Casefold
    s = text.casefold()
    # Replace punctuation with spaces
    transl = str.maketrans({p: " " for p in string.punctuation})
    s = s.translate(transl)
    # Collapse whitespace
    return re.sub(r"\s+", " ", s).strip()


def normalise_field_value(value: Optional[str], field_type: str = "text") -> str:
    """Type-specific canonical normalisation for strict/exact comparisons.

    - id: strip spaces and hyphens, uppercase.
    - date: parse via parse_date into ISO YYYY-MM-DD if valid, else lowercase stripped.
    - number: extract integer/float string representation (e.g. '4.0' -> '4').
    - email: lowercase, strip whitespace.
    - name / text: general text normalisation.
    """
    if value is None:
        return ""

    val_str = str(value).strip()
    if not val_str:
        return ""

    ft = field_type.lower()
    if ft == "id":
        return normalise_id(val_str)
    elif ft == "date":
        d = parse_date(val_str)
        if d is not None:
            return d.isoformat()
        return normalise_text(val_str)
    elif ft == "email":
        return val_str.lower().strip()
    elif ft == "number":
        # Extract leading numeric digits
        m = re.search(r"[-+]?\d*\.?\d+", val_str)
        if m:
            num = float(m.group(0))
            if num.is_integer():
                return str(int(num))
            return str(num)
        return normalise_text(val_str)
    else:
        return normalise_text(val_str)


def values_are_equal(val1: Optional[str], val2: Optional[str], field_type: str = "text") -> bool:
    """Compare two values for equivalence according to field_type rules.

    - id, date, number, email: STRICT / exact match after normalisation.
    - name: token fuzzy match >= 90.
    - text: exact normalised match or token fuzzy match >= 90.
    """
    if val1 is None or val2 is None:
        return val1 is val2

    ft = field_type.lower()
    n1 = normalise_field_value(val1, ft)
    n2 = normalise_field_value(val2, ft)

    if not n1 and not n2:
        return True
    if not n1 or not n2:
        return False

    # IDs, dates, numbers, emails have NO fuzzy matching
    if ft in ("id", "date", "number", "email"):
        return n1 == n2

    if ft == "name":
        if n1 == n2:
            return True
        return fuzz.token_sort_ratio(n1, n2) >= 90 or fuzz.token_set_ratio(n1, n2) >= 90

    # General text
    if n1 == n2:
        return True
    return fuzz.token_sort_ratio(n1, n2) >= 90


def is_quote_grounded(quote: Optional[str], page_text: Optional[str], threshold: float = 90.0) -> bool:
    """Verify that evidence_quote is present in page OCR text with partial_ratio >= 90."""
    if not quote or not page_text:
        return False

    norm_q = normalise_text(quote)
    norm_txt = normalise_text(page_text)

    if not norm_q or not norm_txt:
        return False

    if norm_q in norm_txt:
        return True

    return fuzz.partial_ratio(norm_q, norm_txt) >= threshold


def is_value_grounded(value: Optional[str], field_type: str, page_text: Optional[str]) -> bool:
    """Check that value itself appears in the OCR text of the page.

    - ids: exact match in page text after stripping spaces and hyphens.
    - dates: parsed date matches a date parsed from page text, or exact normalized date match.
    - numbers: normalized number appears in normalized page text.
    - emails: normalized email appears in page text.
    - names: token fuzzy >= 90 against best-matching substring/tokens.
    - text: substring or token fuzzy >= 90.
    """
    if not value or not page_text:
        return False

    ft = field_type.lower()
    norm_val = normalise_field_value(value, ft)
    if not norm_val:
        return False

    if ft == "id":
        norm_page_ids = re.sub(r"[\s\-]", "", page_text).upper()
        return norm_val in norm_page_ids

    if ft == "date":
        d = parse_date(value)
        if d is not None:
            # Check ISO format in normalized text or scan dates in page_text
            d_iso = d.isoformat()
            if d_iso in page_text:
                return True
            # Check individual date tokens in page
            date_patterns = re.findall(
                r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\b|\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",
                page_text,
            )
            for dp in date_patterns:
                p_dt = parse_date(dp)
                if p_dt == d:
                    return True
        return normalise_text(value) in normalise_text(page_text)

    if ft == "email":
        return norm_val in page_text.lower()

    if ft == "number":
        # Word boundary or token match for number
        norm_p = normalise_text(page_text)
        return bool(re.search(r"\b" + re.escape(norm_val) + r"\b", norm_p))

    if ft == "name":
        norm_p = normalise_text(page_text)
        if norm_val in norm_p:
            return True
        return fuzz.partial_ratio(norm_val, norm_p) >= 90

    # General text
    norm_p = normalise_text(page_text)
    if norm_val in norm_p:
        return True
    return fuzz.partial_ratio(norm_val, norm_p) >= 90
