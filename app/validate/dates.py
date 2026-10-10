# Owner: Laptop B
"""INX – Date field validation helpers.

Centralises all date parsing and range logic used by multiple validators
and cross-document checks.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

# Accepted input format strings (tried in order)
_DATE_FORMATS: list[str] = [
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%Y/%m/%d",
    "%Y-%m-%d",
    "%Y.%m.%d",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%m/%d/%Y",
    "%m-%d-%Y",
]


def parse_date(value: str) -> Optional[date]:
    """Try to parse *value* as a date using common formats.

    Args:
        value: Raw string extracted from a document.

    Returns:
        A :class:`datetime.date` on success, ``None`` on failure or if date is impossible.
    """
    if not value or not isinstance(value, str):
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
            # Basic sanity check on plausible calendar year range
            if 1900 <= dt.year <= 2100:
                return dt.date()
        except ValueError:
            continue

    return None


def is_valid_date_range(
    d: date,
    min_date: Optional[date] = None,
    max_date: Optional[date] = None,
) -> bool:
    """Check whether *d* falls within [min_date, max_date].

    Args:
        d: The date to check.
        min_date: Inclusive lower bound; ``None`` means no lower bound.
        max_date: Inclusive upper bound; ``None`` means no upper bound.

    Returns:
        ``True`` if *d* is within range.
    """
    if min_date is not None and d < min_date:
        return False
    if max_date is not None and d > max_date:
        return False
    return True


def age_from_dob(dob: date, reference: Optional[date] = None) -> int:
    """Calculate age in whole years at *reference* date (default: today).

    Args:
        dob: Date of birth.
        reference: Reference date; defaults to ``date.today()``.

    Returns:
        Age in years.
    """
    ref = reference or date.today()
    return ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))


def is_plausible_dob(
    dob: date,
    min_age: int = 16,
    max_age: int = 100,
    reference: Optional[date] = None,
) -> bool:
    """Check whether *dob* represents a plausible applicant age."""
    age = age_from_dob(dob, reference=reference)
    return min_age <= age <= max_age


def dates_are_consistent(earlier: Optional[date], later: Optional[date]) -> bool:
    """Return ``True`` if *earlier* <= *later* (or either is None).

    Args:
        earlier: The expected earlier date.
        later: The expected later date.

    Returns:
        ``True`` if ordering is valid or either date is missing.
    """
    if earlier is None or later is None:
        return True
    return earlier <= later
