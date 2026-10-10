# Owner: Laptop B
"""INX – Identifier validation helpers.

Validates government-issued ID numbers, registration numbers, and other
structured identifiers extracted from documents.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Verhoeff algorithm tables (Dihedral group D5)
# ---------------------------------------------------------------------------

_VERHOEFF_D: list[list[int]] = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]

_VERHOEFF_P: list[list[int]] = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]

_VERHOEFF_INV: list[int] = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def validate_verhoeff(num_str: str) -> bool:
    """Validate a numeric string against the Verhoeff checksum.

    Args:
        num_str: Digits only string.

    Returns:
        ``True`` if checksum matches.
    """
    if not num_str or not num_str.isdigit():
        return False

    c = 0
    for i, ch in enumerate(reversed(num_str)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def generate_verhoeff(num_str: str) -> int:
    """Generate the Verhoeff check digit for a string of digits."""
    c = 0
    for i, ch in enumerate(reversed(num_str)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[(i + 1) % 8][int(ch)]]
    return _VERHOEFF_INV[c]


def validate_govt_id(value: str) -> bool:
    """Validate a 12-digit government identification number with Verhoeff check.

    Accepts numbers with optional spaces or dashes.
    """
    if not value or not isinstance(value, str):
        return False

    cleaned = re.sub(r"[\s-]", "", value)
    if not re.match(r"^[0-9]{12}$", cleaned):
        return False

    return validate_verhoeff(cleaned)


def validate_aadhaar(value: str) -> bool:
    """Validate a 12-digit Indian Aadhaar number (12 digits + Verhoeff, doesn't start with 0 or 1)."""
    if not value or not isinstance(value, str):
        return False

    cleaned = re.sub(r"[\s-]", "", value)
    if not re.match(r"^[2-9][0-9]{11}$", cleaned):
        return False

    return validate_verhoeff(cleaned)


def validate_pan(value: str) -> bool:
    """Validate an Indian PAN card number (AAAAA9999A format)."""
    if not value or not isinstance(value, str):
        return False

    cleaned = normalise_id(value)
    return bool(re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$", cleaned))


def validate_passport(value: str, country_code: str = "IN") -> bool:
    """Validate a passport number for the given country code."""
    if not value or not isinstance(value, str):
        return False

    cleaned = normalise_id(value)
    patterns = {
        "IN": r"^[A-Z][0-9]{7}$",
        "US": r"^[0-9]{9}$",
        "GB": r"^[0-9]{9}$",
    }
    pattern = patterns.get(country_code.upper(), r"^[A-Z0-9]{6,12}$")
    return bool(re.match(pattern, cleaned))


def validate_registration(value: str, pattern: Optional[str] = None) -> bool:
    """Validate an institution-assigned registration / roll number."""
    if not value or not isinstance(value, str):
        return False

    cleaned = value.strip()
    regex = pattern or r"^[A-Z0-9-]{3,30}$"
    return bool(re.match(regex, cleaned, re.IGNORECASE))


def normalise_id(value: str) -> str:
    """Strip whitespace, dashes, and convert to uppercase."""
    if not value:
        return ""
    return re.sub(r"[\s-]", "", value).upper()


def classify_id_type(value: str) -> Optional[str]:
    """Heuristically identify the type of an ID string."""
    if not value:
        return None

    cleaned = normalise_id(value)
    if validate_aadhaar(cleaned) or validate_govt_id(cleaned):
        return "aadhaar"
    if validate_pan(cleaned):
        return "pan"
    if validate_passport(cleaned, "IN"):
        return "passport"
    if re.match(r"^[A-Z0-9-]{4,20}$", cleaned):
        return "registration"

    return None
