# Owner: Laptop B
"""INX – Tests: decide/engine.py & decide/explain.py"""

from __future__ import annotations

import pytest

from app.config import load_scenario
from app.decide.engine import decide
from app.decide.explain import explain_decision
from app.schemas import (
    CaseRecord,
    DocumentRecord,
    DocumentType,
    FieldResult,
    FieldStatus,
    Issue,
    IssueKind,
    Route,
    WorkflowStatus,
    field_key,
)
from app.validate.checks import validate_case_fields
from app.validate.crossdoc import run_cross_checks
from app.validate.identifiers import generate_verhoeff


def _build_valid_job_application_case() -> CaseRecord:
    """Helper creating a completely valid job_application CaseRecord."""
    base_11 = "28123456789"
    valid_id = base_11 + str(generate_verhoeff(base_11))

    return CaseRecord(
        scenario="job_application",
        sender_email="candidate@example.com",
        documents=[
            DocumentRecord(
                filename="resume.pdf",
                sha256="1" * 64,
                storage_path="data/originals/resume.pdf",
                doc_type=DocumentType.resume,
                quality_verdict="ok",
            ),
            DocumentRecord(
                filename="id.pdf",
                sha256="2" * 64,
                storage_path="data/originals/id.pdf",
                doc_type=DocumentType.id_document,
                quality_verdict="ok",
            ),
        ],
        fields={
            field_key(DocumentType.resume, "applicant_name"): FieldResult(
                field="applicant_name",
                doc_type=DocumentType.resume,
                value="Alice Smith",
                status=FieldStatus.valid,
            ),
            field_key(DocumentType.resume, "email"): FieldResult(
                field="email",
                doc_type=DocumentType.resume,
                value="candidate@example.com",
                status=FieldStatus.valid,
            ),
            field_key(DocumentType.resume, "highest_qualification"): FieldResult(
                field="highest_qualification",
                doc_type=DocumentType.resume,
                value="B.Tech",
                status=FieldStatus.valid,
            ),
            field_key(DocumentType.resume, "institution"): FieldResult(
                field="institution",
                doc_type=DocumentType.resume,
                value="IIT Delhi",
                status=FieldStatus.valid,
            ),
            field_key(DocumentType.resume, "years_experience"): FieldResult(
                field="years_experience",
                doc_type=DocumentType.resume,
                value="5",
                status=FieldStatus.valid,
            ),
            field_key(DocumentType.id_document, "applicant_name"): FieldResult(
                field="applicant_name",
                doc_type=DocumentType.id_document,
                value="Alice Smith",
                status=FieldStatus.valid,
            ),
            field_key(DocumentType.id_document, "id_number"): FieldResult(
                field="id_number",
                doc_type=DocumentType.id_document,
                value=valid_id,
                status=FieldStatus.valid,
            ),
        },
    )


class TestDecideEngine:
    def test_all_valid_routes_to_process(self):
        case = _build_valid_job_application_case()
        decide(case)
        assert case.route == Route.PROCESS
        assert case.workflow_status == WorkflowStatus.verified
        assert "R06" in case.rule_ids

    def test_missing_field_routes_to_request_info(self):
        case = _build_valid_job_application_case()
        # Mark a required field as missing
        case.fields["resume.email"].status = FieldStatus.missing
        case.issues.append(
            Issue(field="email", kind=IssueKind.missing, detail="Email is missing")
        )
        decide(case)
        assert case.route == Route.REQUEST_INFO
        assert case.workflow_status == WorkflowStatus.awaiting_information
        assert "R05" in case.rule_ids

    def test_name_typo_across_docs_routes_to_manual_verification(self):
        case = _build_valid_job_application_case()
        # Create a near match typo conflict (similarity between 85% and 95%)
        case.fields["id_document.applicant_name"].value = "Alicia Smith"  # Typo
        run_cross_checks(case)
        assert case.has_conflict()

        decide(case)
        assert case.route == Route.MANUAL_VERIFICATION
        assert case.workflow_status == WorkflowStatus.review_required
        assert "R01" in case.rule_ids

    def test_poor_quality_routes_to_human_review(self):
        case = _build_valid_job_application_case()
        case.documents[0].quality_verdict = "poor"
        decide(case)
        assert case.route == Route.HUMAN_REVIEW
        assert case.workflow_status == WorkflowStatus.review_required
        assert "R03" in case.rule_ids

    def test_unknown_type_routes_to_human_review(self):
        case = _build_valid_job_application_case()
        case.documents.append(
            DocumentRecord(
                filename="extra.bin",
                sha256="9" * 64,
                storage_path="data/originals/extra.bin",
                doc_type=DocumentType.unknown,
            )
        )
        decide(case)
        assert case.route == Route.HUMAN_REVIEW
        assert case.workflow_status == WorkflowStatus.review_required
        assert "R04" in case.rule_ids

    def test_empty_case_routes_to_human_review(self):
        case = CaseRecord(
            scenario="job_application",
            sender_email="someone@example.com",
            documents=[],
            fields={},
        )
        decide(case)
        assert case.route == Route.HUMAN_REVIEW
        assert case.workflow_status == WorkflowStatus.review_required

    def test_several_issues_at_once_highest_severity_wins_and_all_reasons_kept(self):
        case = _build_valid_job_application_case()
        # 1. Conflict (priority 10 -> MANUAL_VERIFICATION)
        case.fields["resume.applicant_name"].status = FieldStatus.conflict
        case.issues.append(
            Issue(field="applicant_name", kind=IssueKind.conflict, detail="Name mismatch")
        )
        # 2. Unreliable (priority 20 -> HUMAN_REVIEW)
        case.fields["resume.years_experience"].status = FieldStatus.unreliable
        case.issues.append(
            Issue(field="years_experience", kind=IssueKind.unreliable, detail="Low OCR")
        )
        # 3. Missing (priority 40 -> REQUEST_INFO)
        case.fields["resume.email"].status = FieldStatus.missing
        case.issues.append(
            Issue(field="email", kind=IssueKind.missing, detail="Email missing")
        )

        decide(case)
        # Priority 10 wins the route over priority 20 and priority 40!
        assert case.route == Route.MANUAL_VERIFICATION
        assert case.workflow_status == WorkflowStatus.review_required

        # ALL reasons and rule_ids from firing rules are kept
        assert "R01" in case.rule_ids
        assert "R02" in case.rule_ids
        assert "R05" in case.rule_ids
        assert len(case.reasons) >= 3


class TestDecideExplain:
    def test_explain_decision(self):
        case = _build_valid_job_application_case()
        decide(case)
        explanation = explain_decision(case)
        assert "Decision: PROCESS" in explanation
        assert "R06" in explanation
        assert "Issues Identified" in explanation
