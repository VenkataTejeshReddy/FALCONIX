# Owner: Laptop B
"""INX – Tests: validate/identifiers.py"""

from __future__ import annotations

import pytest

from app.validate.identifiers import (
    classify_id_type,
    generate_verhoeff,
    normalise_id,
    validate_aadhaar,
    validate_govt_id,
    validate_pan,
    validate_passport,
    validate_registration,
    validate_verhoeff,
)


class TestVerhoeff:
    def test_known_verhoeff_checksums(self):
        # Generate check digit for '236' -> check digit is 3 -> '2363' is valid
        cd = generate_verhoeff("236")
        assert cd == 3
        assert validate_verhoeff("2363")

    def test_tampered_verhoeff_fails(self):
        # Changing any single digit or adjacent transposition fails
        assert not validate_verhoeff("2364")
        assert not validate_verhoeff("3263")

    def test_12_digit_id_generation_and_validation(self):
        base_11 = "36123456789"
        cd = generate_verhoeff(base_11)
        valid_12 = base_11 + str(cd)
        assert len(valid_12) == 12
        assert validate_govt_id(valid_12)
        assert validate_aadhaar(valid_12)

        # Invalid checksum
        bad_12 = base_11 + str((cd + 1) % 10)
        assert not validate_govt_id(bad_12)
        assert not validate_aadhaar(bad_12)


class TestIdentifiers:
    def test_pan_format(self):
        assert validate_pan("ABCDE1234F")
        assert validate_pan("abcde1234f")  # case-insensitive normalization
        assert not validate_pan("ABCD12345F")
        assert not validate_pan("ABCDE12345")
        assert not validate_pan("")

    def test_passport_format(self):
        assert validate_passport("A1234567", country_code="IN")
        assert not validate_passport("12345678", country_code="IN")
        assert validate_passport("123456789", country_code="US")

    def test_registration_format(self):
        assert validate_registration("REG-2023-001")
        # Custom regex from config
        pattern = r"^[A-Z0-9-]{6,20}$"
        assert validate_registration("COL-987654", pattern=pattern)
        assert not validate_registration("COL", pattern=pattern)

    def test_normalise_id(self):
        assert normalise_id(" abc - 123 ") == "ABC123"

    def test_classify_id_type(self):
        base_11 = "45123456789"
        valid_12 = base_11 + str(generate_verhoeff(base_11))
        assert classify_id_type(valid_12) == "aadhaar"
        assert classify_id_type("ABCDE1234F") == "pan"
        assert classify_id_type("A1234567") == "passport"
