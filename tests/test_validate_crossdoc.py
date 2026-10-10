# Owner: Laptop B
"""INX – Tests: validate/crossdoc.py"""

from __future__ import annotations

import pytest

from app.schemas import (
    CaseRecord,
    DocumentRecord,
    DocumentType,
    FieldResult,
    FieldStatus,
    IssueKind,
    field_key,
)
from app.validate.crossdoc import (
    cross_check_dob,
    cross_check_name,
    normalise_name,
    run_cross_checks,
)


class TestNameNormalization:
    def test_normalise_name_titles_and_case(self):
        assert normalise_name("Dr. Jane E. Doe, PhD") == "jane e doe phd"
        assert normalise_name("Mr. John Doe") == "john doe"
        assert normalise_name("Shri Rajesh Kumar") == "rajesh kumar"


class TestCrossDocComparison:
    def test_exact_name_match_is_valid(self):
        case = CaseRecord(
            scenario="job_application",
            sender_email="jane@example.com",
            fields={
                field_key(DocumentType.resume, "applicant_name"): FieldResult(
                    field="applicant_name",
                    doc_type=DocumentType.resume,
                    value="Dr. Jane Doe",
                ),
                field_key(DocumentType.id_document, "applicant_name"): FieldResult(
                    field="applicant_name",
                    doc_type=DocumentType.id_document,
                    value="Jane Doe",
                ),
            },
        )
        issues = cross_check_name(case)
        assert len(issues) == 0

    def test_near_match_probable_typo_conflict(self):
        case = CaseRecord(
            scenario="job_application",
            sender_email="jane@example.com",
            fields={
                field_key(DocumentType.resume, "applicant_name"): FieldResult(
                    field="applicant_name",
                    doc_type=DocumentType.resume,
                    value="Jane Doe",
                ),
                field_key(DocumentType.id_document, "applicant_name"): FieldResult(
                    field="applicant_name",
                    doc_type=DocumentType.id_document,
                    value="Jan Doe",  # one character typo
                ),
            },
        )
        issues = cross_check_name(case, fuzzy_exact=95.0, fuzzy_near=85.0)
        assert len(issues) == 1
        assert issues[0].kind == IssueKind.conflict
        assert "probable typo" in issues[0].detail
        assert case.fields["resume.applicant_name"].status == FieldStatus.conflict
        assert case.fields["id_document.applicant_name"].status == FieldStatus.conflict

    def test_clear_name_mismatch_conflict(self):
        case = CaseRecord(
            scenario="job_application",
            sender_email="jane@example.com",
            fields={
                field_key(DocumentType.resume, "applicant_name"): FieldResult(
                    field="applicant_name",
                    doc_type=DocumentType.resume,
                    value="Jane Doe",
                ),
                field_key(DocumentType.id_document, "applicant_name"): FieldResult(
                    field="applicant_name",
                    doc_type=DocumentType.id_document,
                    value="Robert Smith",
                ),
            },
        )
        issues = cross_check_name(case)
        assert len(issues) == 1
        assert issues[0].kind == IssueKind.conflict
        assert "does not match" in issues[0].detail

    def test_initials_matching_p_sharma_vs_priya_sharma_not_silently_valid(self):
        """P. Sharma vs Priya Sharma must be flagged and never silently valid."""
        case = CaseRecord(
            scenario="job_application",
            sender_email="sharma@example.com",
            fields={
                field_key(DocumentType.resume, "applicant_name"): FieldResult(
                    field="applicant_name",
                    doc_type=DocumentType.resume,
                    value="P. Sharma",
                ),
                field_key(DocumentType.id_document, "applicant_name"): FieldResult(
                    field="applicant_name",
                    doc_type=DocumentType.id_document,
                    value="Priya Sharma",
                ),
            },
        )
        issues = cross_check_name(case)
        assert len(issues) >= 1
        assert any(i.kind == IssueKind.conflict for i in issues)
        assert case.has_conflict()
        assert case.fields["resume.applicant_name"].status == FieldStatus.conflict

    def test_name_order_inversion_reddy_venkata_vs_venkata_reddy_not_silently_valid(self):
        """Reddy Venkata vs Venkata Reddy must be flagged and never silently valid."""
        case = CaseRecord(
            scenario="job_application",
            sender_email="reddy@example.com",
            fields={
                field_key(DocumentType.resume, "applicant_name"): FieldResult(
                    field="applicant_name",
                    doc_type=DocumentType.resume,
                    value="Reddy Venkata",
                ),
                field_key(DocumentType.id_document, "applicant_name"): FieldResult(
                    field="applicant_name",
                    doc_type=DocumentType.id_document,
                    value="Venkata Reddy",
                ),
            },
        )
        issues = cross_check_name(case)
        assert len(issues) >= 1
        assert any(i.kind == IssueKind.conflict for i in issues)
        assert case.has_conflict()
        assert "order inverted" in issues[0].detail


    def test_dob_mismatch_conflict(self):
        case = CaseRecord(
            scenario="college",
            sender_email="student@example.com",
            fields={
                field_key(DocumentType.marksheet, "date_of_birth"): FieldResult(
                    field="date_of_birth",
                    doc_type=DocumentType.marksheet,
                    value="15/05/2000",
                ),
                field_key(DocumentType.id_document, "date_of_birth"): FieldResult(
                    field="date_of_birth",
                    doc_type=DocumentType.id_document,
                    value="20/08/2001",
                ),
            },
        )
        issues = cross_check_dob(case)
        assert len(issues) == 1
        assert issues[0].kind == IssueKind.conflict
        assert "mismatch" in issues[0].detail.lower()
