# Owner: Laptop B
"""INX – Tests: schema round-trip and enum validation.

Tests are intentionally dependency-light and must pass on both laptops with
only requirements-core.txt installed.

Run with::

    pytest tests/test_schemas.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
import uuid
from datetime import datetime

import pytest
import yaml
from pydantic import ValidationError

from app.schemas import (
    BBox,
    CaseRecord,
    Decision,
    DocumentRecord,
    DocumentType,
    FieldResult,
    FieldStatus,
    Issue,
    IssueKind,
    ParsedDocument,
    ParsedLine,
    Route,
    WorkflowStatus,
    field_key,
)

CONFIG_DIR = Path(__file__).parent.parent / "config"


# ---------------------------------------------------------------------------
# Enum validation
# ---------------------------------------------------------------------------


class TestEnums:
    def test_field_status_values(self):
        assert set(FieldStatus) == {
            FieldStatus.valid,
            FieldStatus.missing,
            FieldStatus.unclear,
            FieldStatus.conflict,
            FieldStatus.unreliable,
        }

    def test_workflow_status_values(self):
        expected = {
            "received", "processing", "verified", "review_required",
            "awaiting_information", "approved", "rejected",
        }
        assert {s.value for s in WorkflowStatus} == expected

    def test_route_values(self):
        assert set(r.value for r in Route) == {
            "PROCESS", "REQUEST_INFO", "MANUAL_VERIFICATION", "HUMAN_REVIEW"
        }

    def test_document_type_unknown_exists(self):
        assert DocumentType.unknown.value == "unknown"

    def test_issue_kind_values(self):
        expected = {
            "missing",
            "unclear",
            "conflict",
            "unreliable",
            "poor_quality",
            "unknown_type",
            "missing_document",
            "unsupported_file",
            "rejected_file",
            "duplicate_file",
            "no_sender",
        }
        assert {k.value for k in IssueKind} == expected

    def test_field_status_from_string(self):
        assert FieldStatus("valid") == FieldStatus.valid
        assert FieldStatus("conflict") == FieldStatus.conflict

    def test_invalid_field_status_raises(self):
        with pytest.raises(ValueError):
            FieldStatus("nonexistent")

    def test_route_from_string(self):
        assert Route("PROCESS") == Route.PROCESS
        assert Route("HUMAN_REVIEW") == Route.HUMAN_REVIEW


# ---------------------------------------------------------------------------
# BBox
# ---------------------------------------------------------------------------


class TestBBox:
    def test_basic_construction(self):
        b = BBox(x0=0, y0=0, x1=100, y1=200)
        assert b.width == 100
        assert b.height == 200
        assert b.area == 20_000

    def test_negative_coordinates_allowed(self):
        b = BBox(x0=-20, y0=-10, x1=80, y1=90)
        assert b.width == 100
        assert b.height == 100

    def test_invalid_ordering_raises(self):
        with pytest.raises(ValidationError):
            BBox(x0=100, y0=0, x1=50, y1=200)  # x1 < x0

    def test_json_round_trip(self):
        b = BBox(x0=10, y0=20, x1=110, y1=220)
        restored = BBox.model_validate_json(b.model_dump_json())
        assert restored == b


# ---------------------------------------------------------------------------
# ParsedLine
# ---------------------------------------------------------------------------


class TestParsedLine:
    def test_construction_without_bbox(self):
        line = ParsedLine(text="Hello world", page=0)
        assert line.bbox is None
        assert line.conf is None

    def test_with_bbox_and_conf(self):
        bbox = BBox(x0=0, y0=0, x1=50, y1=10)
        line = ParsedLine(text="Test", page=1, bbox=bbox, conf=0.8)
        assert line.bbox.width == 50
        assert line.conf == 0.8

    def test_confidence_clamp(self):
        with pytest.raises(ValidationError):
            ParsedLine(text="X", page=0, conf=1.5)

    def test_json_round_trip(self):
        line = ParsedLine(text="Sample", page=2, conf=0.75)
        restored = ParsedLine.model_validate_json(line.model_dump_json())
        assert restored == line


# ---------------------------------------------------------------------------
# ParsedDocument
# ---------------------------------------------------------------------------


class TestParsedDocument:
    def _sample(self) -> ParsedDocument:
        return ParsedDocument(
            sha256="a" * 64,
            pages=2,
            lines=[ParsedLine(text="Line 1", page=0, conf=1.0)],
            text_by_page={0: "Line 1", 1: "Line 2"},
        )

    def test_full_text(self):
        doc = self._sample()
        assert "Line 1" in doc.full_text
        assert "Line 2" in doc.full_text

    def test_defaults(self):
        doc = self._sample()
        assert doc.reader_name == "unknown"
        assert doc.tables == []

    def test_json_round_trip(self):
        doc = self._sample()
        restored = ParsedDocument.model_validate_json(doc.model_dump_json())
        assert restored.sha256 == doc.sha256
        assert restored.pages == doc.pages
        assert len(restored.lines) == len(doc.lines)

    def test_doc_id_is_uuid(self):
        doc = self._sample()
        uuid.UUID(doc.doc_id)


# ---------------------------------------------------------------------------
# FieldResult
# ---------------------------------------------------------------------------


class TestFieldResult:
    def test_defaults(self):
        fr = FieldResult(field="email")
        assert fr.status == FieldStatus.missing
        assert fr.value is None
        assert fr.confidence == 0.0
        assert fr.doc_type is None

    def test_valid_field_with_doc_type(self):
        fr = FieldResult(
            field="email",
            doc_type=DocumentType.resume,
            value="a@b.com",
            status=FieldStatus.valid,
            confidence=0.95,
        )
        assert fr.status == FieldStatus.valid
        assert fr.doc_type == DocumentType.resume

    def test_json_round_trip(self):
        fr = FieldResult(
            field="phone",
            doc_type=DocumentType.resume,
            value="+1-800-555-0000",
            status=FieldStatus.valid,
            confidence=0.88,
            page=0,
        )
        restored = FieldResult.model_validate_json(fr.model_dump_json())
        assert restored == fr


# ---------------------------------------------------------------------------
# Issue
# ---------------------------------------------------------------------------


class TestIssue:
    def test_construction(self):
        issue = Issue(
            field="id_number",
            kind=IssueKind.missing,
            detail="ID number not found in id_document",
            doc="passport.pdf",
            page=0,
        )
        assert issue.kind == IssueKind.missing

    def test_json_round_trip(self):
        issue = Issue(field="email", kind=IssueKind.unclear, detail="Low conf")
        restored = Issue.model_validate_json(issue.model_dump_json())
        assert restored == issue


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class TestDecision:
    def test_construction(self):
        d = Decision(
            route=Route.PROCESS,
            workflow_status=WorkflowStatus.verified,
            reasons=["All fields valid"],
            rule_ids=["R06"],
        )
        assert d.decided_by == "policy_engine"

    def test_json_round_trip(self):
        d = Decision(
            route=Route.REQUEST_INFO,
            workflow_status=WorkflowStatus.awaiting_information,
        )
        restored = Decision.model_validate_json(d.model_dump_json())
        assert restored.route == Route.REQUEST_INFO


# ---------------------------------------------------------------------------
# CaseRecord
# ---------------------------------------------------------------------------


class TestCaseRecord:
    def _sample(self) -> CaseRecord:
        return CaseRecord(
            scenario="job_application",
            sender_email="alice@example.com",
            sender_name="Alice",
        )

    def test_case_id_is_uuid(self):
        case = self._sample()
        uuid.UUID(case.case_id)

    def test_default_status(self):
        case = self._sample()
        assert case.workflow_status == WorkflowStatus.received

    def test_empty_sender_email_allowed(self):
        case = CaseRecord(scenario="job_application", sender_email="")
        assert case.sender_email == ""

    def test_decision_is_source_of_truth_and_properties_read_only(self):
        case = self._sample()
        assert case.decision is None
        assert case.route is None
        assert case.reasons == []
        assert case.rule_ids == []

        case.decision = Decision(
            route=Route.HUMAN_REVIEW,
            workflow_status=WorkflowStatus.review_required,
            reasons=["Unclear fields"],
            rule_ids=["R07"],
        )
        assert case.route == Route.HUMAN_REVIEW
        assert case.reasons == ["Unclear fields"]
        assert case.rule_ids == ["R07"]

        with pytest.raises(AttributeError):
            case.route = Route.PROCESS  # read-only property

    def test_new_intake_fields_default_to_empty(self):
        case = self._sample()
        assert case.missing_documents == []
        assert case.intake_notes == []
        assert case.skipped_files == []

    def test_has_conflict_false_by_default(self):
        case = self._sample()
        assert not case.has_conflict()

    def test_has_conflict_true(self):
        case = self._sample()
        key = field_key(DocumentType.resume, "email")
        case.fields[key] = FieldResult(
            field="email", doc_type=DocumentType.resume, status=FieldStatus.conflict
        )
        assert case.has_conflict()

    def test_missing_required(self):
        case = self._sample()
        k1 = field_key(DocumentType.resume, "email")
        k2 = field_key(DocumentType.resume, "phone")
        case.fields[k1] = FieldResult(
            field="email", doc_type=DocumentType.resume, status=FieldStatus.valid
        )
        missing = case.missing_required([k1, k2])
        assert k2 in missing
        assert k1 not in missing

    def test_two_documents_different_applicant_name_fields(self):
        """Assert a CaseRecord can hold two different applicant_name fields from two docs."""
        case = CaseRecord(
            scenario="job_application",
            sender_email="jane@example.com",
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
        )
        k_resume = field_key(DocumentType.resume, "applicant_name")
        k_id = field_key(DocumentType.id_document, "applicant_name")

        case.fields[k_resume] = FieldResult(
            field="applicant_name",
            doc_type=DocumentType.resume,
            value="Jane Doe",
            status=FieldStatus.valid,
        )
        case.fields[k_id] = FieldResult(
            field="applicant_name",
            doc_type=DocumentType.id_document,
            value="Jane Elizabeth Doe",
            status=FieldStatus.valid,
        )

        assert case.fields["resume.applicant_name"].value == "Jane Doe"
        assert case.fields["id_document.applicant_name"].value == "Jane Elizabeth Doe"
        assert (
            case.fields["resume.applicant_name"].value
            != case.fields["id_document.applicant_name"].value
        )
        assert len(case.fields) == 2

    def test_json_round_trip(self):
        case = self._sample()
        key = field_key(DocumentType.resume, "name")
        case.fields[key] = FieldResult(
            field="name",
            doc_type=DocumentType.resume,
            value="Alice",
            status=FieldStatus.valid,
        )
        case.issues.append(
            Issue(field="phone", kind=IssueKind.missing, detail="No phone")
        )
        restored = CaseRecord.model_validate_json(case.model_dump_json())
        assert restored.case_id == case.case_id
        assert restored.sender_email == case.sender_email
        assert key in restored.fields
        assert len(restored.issues) == 1

    def test_json_schema_is_valid_dict(self):
        schema = CaseRecord.model_json_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema

    def test_decision_round_trip_on_case(self):
        case = self._sample()
        case.decision = Decision(
            route=Route.HUMAN_REVIEW,
            workflow_status=WorkflowStatus.review_required,
            rule_ids=["R04"],
        )
        restored = CaseRecord.model_validate_json(case.model_dump_json())
        assert restored.decision.route == Route.HUMAN_REVIEW
        assert restored.route == Route.HUMAN_REVIEW


# ---------------------------------------------------------------------------
# DocumentRecord
# ---------------------------------------------------------------------------


class TestDocumentRecord:
    def test_construction(self):
        dr = DocumentRecord(
            filename="resume.pdf",
            sha256="b" * 64,
            storage_path="data/originals/resume.pdf",
        )
        assert dr.doc_type == DocumentType.unknown
        assert dr.quality_score is None
        assert dr.is_readable is None
        assert dr.quality_verdict is None
        assert dr.quality_issues == []
        assert dr.page_images == []
        assert dr.pdf_has_text_layer is False
        assert dr.is_duplicate is False

    def test_quality_verdict_values(self):
        dr = DocumentRecord(
            filename="doc.pdf",
            sha256="c" * 64,
            storage_path="data/originals/doc.pdf",
            quality_verdict="ok",
            quality_issues=["none"],
            pdf_has_text_layer=True,
            is_duplicate=True,
        )
        assert dr.quality_verdict == "ok"
        assert dr.pdf_has_text_layer is True
        assert dr.is_duplicate is True

    def test_json_round_trip(self):
        dr = DocumentRecord(
            filename="id.jpg",
            sha256="c" * 64,
            storage_path="data/originals/id.jpg",
            doc_type=DocumentType.id_document,
            quality_verdict="warn",
        )
        restored = DocumentRecord.model_validate_json(dr.model_dump_json())
        assert restored.doc_type == DocumentType.id_document
        assert restored.quality_verdict == "warn"


# ---------------------------------------------------------------------------
# YAML Contract Validation
# ---------------------------------------------------------------------------


class TestYAMLContracts:
    @pytest.mark.parametrize("scenario", ["job_application", "college"])
    def test_yaml_document_keys_are_valid_document_types(self, scenario: str):
        """Assert every YAML document key is a valid DocumentType."""
        path = CONFIG_DIR / f"{scenario}.yaml"
        assert path.exists(), f"Missing config: {path}"
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        valid_doc_types = {dt.value for dt in DocumentType}
        for doc_key in data.get("documents", {}).keys():
            assert (
                doc_key in valid_doc_types
            ), f"Document key {doc_key!r} in {scenario}.yaml is not a valid DocumentType"

    @pytest.mark.parametrize("scenario", ["job_application", "college"])
    def test_yaml_rule_ids_are_unique(self, scenario: str):
        """Assert every rule id is unique within each scenario."""
        path = CONFIG_DIR / f"{scenario}.yaml"
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        rule_ids = [r["id"] for r in data.get("rules", [])]
        assert len(rule_ids) == len(
            set(rule_ids)
        ), f"Duplicate rule IDs found in {scenario}.yaml: {rule_ids}"

    @pytest.mark.parametrize("scenario", ["job_application", "college"])
    def test_yaml_rule_route_and_status_are_valid_enums(self, scenario: str):
        """Assert every rule route and status is a valid enum value."""
        path = CONFIG_DIR / f"{scenario}.yaml"
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        valid_routes = {r.value for r in Route}
        valid_statuses = {s.value for s in WorkflowStatus}

        for rule in data.get("rules", []):
            rule_id = rule.get("id", "unknown")
            route = rule.get("route")
            status = rule.get("status")
            assert (
                route in valid_routes
            ), f"Rule {rule_id} in {scenario}.yaml has invalid route: {route!r}"
            assert (
                status in valid_statuses
            ), f"Rule {rule_id} in {scenario}.yaml has invalid status: {status!r}"
