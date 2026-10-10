# Owner: Laptop B
"""INX – Tests: validate/checks.py"""

from __future__ import annotations

import pytest

from app.config import load_scenario
from app.schemas import (
    CaseRecord,
    DocumentRecord,
    DocumentType,
    FieldResult,
    FieldStatus,
    IssueKind,
    field_key,
)
from app.validate.checks import (
    get_validator,
    run_validators,
    validate_case_fields,
    validate_email_format,
    validate_no_digits,
    validate_non_empty,
    validate_number_range,
    validate_phone_format,
)
from app.validate.identifiers import generate_verhoeff


class TestFieldValidators:
    def test_non_empty(self):
        st, reas = validate_non_empty("Alice")
        assert st == FieldStatus.valid

        st, reas = validate_non_empty("   ")
        assert st == FieldStatus.missing
        assert "missing" in reas.lower()

    def test_no_digits(self):
        st, reas = validate_no_digits("John Doe")
        assert st == FieldStatus.valid

        st, reas = validate_no_digits("John Doe 2nd")
        assert st == FieldStatus.unreliable
        assert "numeric" in reas.lower()

    def test_email_format(self):
        st, _ = validate_email_format("user@example.com")
        assert st == FieldStatus.valid

        st, reas = validate_email_format("bad-email@")
        assert st == FieldStatus.unreliable
        assert "invalid email" in reas.lower()

    def test_phone_format(self):
        st, _ = validate_phone_format("+1-800-555-0199")
        assert st == FieldStatus.valid

        st, reas = validate_phone_format("123")  # too short
        assert st == FieldStatus.unreliable

    def test_number_range_years_experience(self):
        st, _ = validate_number_range("5", min=0, max=60)
        assert st == FieldStatus.valid

        st, _ = validate_number_range("7 years", min=0, max=60)
        assert st == FieldStatus.valid

        st, reas = validate_number_range("75", min=0, max=60)
        assert st == FieldStatus.unreliable
        assert "exceeds" in reas.lower()

        st, reas = validate_number_range("-2", min=0, max=60)
        assert st == FieldStatus.unreliable

    def test_never_default_unknown_value_to_valid(self):
        # Empty field with non_empty validator returns missing, never valid
        st, reas = run_validators("email", "", ["non_empty", "email_format"])
        assert st == FieldStatus.missing
        assert len(reas) > 0


class TestCaseFieldValidation:
    def test_missing_required_document_flags_issue(self):
        case = CaseRecord(
            scenario="job_application",
            sender_email="candidate@example.com",
            documents=[],  # No documents submitted
        )
        validate_case_fields(case)
        assert "resume" in case.missing_documents
        assert "id_document" in case.missing_documents
        assert any(i.kind == IssueKind.missing_document for i in case.issues)

    def test_valid_case_fields(self):
        # Generate valid 12-digit ID
        base_11 = "28123456789"
        valid_id = base_11 + str(generate_verhoeff(base_11))

        case = CaseRecord(
            scenario="job_application",
            sender_email="alice@example.com",
            documents=[
                DocumentRecord(
                    filename="resume.pdf",
                    sha256="1" * 64,
                    storage_path="data/originals/resume.pdf",
                    doc_type=DocumentType.resume,
                ),
                DocumentRecord(
                    filename="id.pdf",
                    sha256="2" * 64,
                    storage_path="data/originals/id.pdf",
                    doc_type=DocumentType.id_document,
                ),
            ],
            fields={
                field_key(DocumentType.resume, "applicant_name"): FieldResult(
                    field="applicant_name", doc_type=DocumentType.resume, value="Alice Smith"
                ),
                field_key(DocumentType.resume, "email"): FieldResult(
                    field="email", doc_type=DocumentType.resume, value="alice@example.com"
                ),
                field_key(DocumentType.resume, "highest_qualification"): FieldResult(
                    field="highest_qualification", doc_type=DocumentType.resume, value="B.Tech Computer Science"
                ),
                field_key(DocumentType.resume, "institution"): FieldResult(
                    field="institution", doc_type=DocumentType.resume, value="National Institute of Technology"
                ),
                field_key(DocumentType.resume, "years_experience"): FieldResult(
                    field="years_experience", doc_type=DocumentType.resume, value="4"
                ),
                field_key(DocumentType.id_document, "applicant_name"): FieldResult(
                    field="applicant_name", doc_type=DocumentType.id_document, value="Alice Smith"
                ),
                field_key(DocumentType.id_document, "id_number"): FieldResult(
                    field="id_number", doc_type=DocumentType.id_document, value=valid_id
                ),
            },
        )
        validate_case_fields(case)
        assert len(case.missing_documents) == 0
        assert all(f.status == FieldStatus.valid for f in case.fields.values())
        assert len(case.issues) == 0
