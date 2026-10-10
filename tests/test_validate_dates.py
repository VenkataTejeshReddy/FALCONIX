# Owner: Laptop B
"""INX – Tests: validate/dates.py"""

from __future__ import annotations

from datetime import date

# pyrefly: ignore [missing-import]
import pytest

from app.validate.dates import (
    age_from_dob,
    dates_are_consistent,
    is_plausible_dob,
    is_valid_date_range,
    parse_date,
)


class TestDateParsing:
    @pytest.mark.parametrize(
        "val,expected",
        [
            ("15/08/1995", date(1995, 8, 15)),
            ("15-08-1995", date(1995, 8, 15)),
            ("15.08.1995", date(1995, 8, 15)),
            ("1995-08-15", date(1995, 8, 15)),
            ("1995/08/15", date(1995, 8, 15)),
            ("15 August 1995", date(1995, 8, 15)),
            ("15 Aug 1995", date(1995, 8, 15)),
            ("August 15, 1995", date(1995, 8, 15)),
            ("Aug 15, 1995", date(1995, 8, 15)),
            ("15-Aug-1995", date(1995, 8, 15)),
        ],
    )
    def test_parse_common_formats(self, val: str, expected: date):
        assert parse_date(val) == expected

    @pytest.mark.parametrize(
        "invalid",
        [
            "30/02/2023",  # Feb 30
            "31/04/2023",  # April 31
            "29/02/2023",  # Non-leap year Feb 29
            "15/13/2023",  # Month 13
            "00/05/2023",  # Day 0
            "not a date",
            "",
            "   ",
            None,
        ],
    )
    def test_reject_impossible_dates(self, invalid: str):
        assert parse_date(invalid) is None


class TestDateRangesAndAge:
    def test_valid_date_range(self):
        d = date(2020, 1, 1)
        assert is_valid_date_range(d, min_date=date(2019, 1, 1), max_date=date(2021, 1, 1))
        assert not is_valid_date_range(d, min_date=date(2020, 2, 1))
        assert not is_valid_date_range(d, max_date=date(2019, 12, 31))

    def test_age_calculation(self):
        dob = date(2000, 5, 10)
        ref = date(2025, 5, 9)
        assert age_from_dob(dob, reference=ref) == 24
        ref2 = date(2025, 5, 10)
        assert age_from_dob(dob, reference=ref2) == 25

    def test_plausible_dob(self):
        ref = date(2025, 1, 1)
        # 25 years old -> plausible
        assert is_plausible_dob(date(2000, 1, 1), reference=ref)
        # 10 years old -> not plausible
        assert not is_plausible_dob(date(2015, 1, 1), reference=ref)
        # 120 years old -> not plausible
        assert not is_plausible_dob(date(1905, 1, 1), reference=ref)

    def test_dates_ordering(self):
        d1 = date(2020, 1, 1)
        d2 = date(2022, 6, 1)
        assert dates_are_consistent(d1, d2)
        assert not dates_are_consistent(d2, d1)
        assert dates_are_consistent(None, d2)
        assert dates_are_consistent(d1, None)
