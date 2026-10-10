# Owner: Laptop B
"""INX – Pydantic v2 shared data contracts.

All cross-module data types live here.  No other module may define its own
standalone models; everything flows through these schemas so that JSON Schema
exports (scripts/export_schemas.py) stay in sync automatically.

Page numbers are 0-based internally throughout the pipeline and shown as
1-based (+1) to human users in UI and notification messages.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field, computed_field, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class FieldStatus(str, Enum):
    """Outcome of validating a single extracted field."""

    valid = "valid"
    missing = "missing"
    unclear = "unclear"
    conflict = "conflict"
    unreliable = "unreliable"


class WorkflowStatus(str, Enum):
    """High-level lifecycle state of a case."""

    received = "received"
    processing = "processing"
    verified = "verified"
    review_required = "review_required"
    awaiting_information = "awaiting_information"
    approved = "approved"
    rejected = "rejected"


class Route(str, Enum):
    """Decision routing outcome produced by the policy engine."""

    PROCESS = "PROCESS"
    REQUEST_INFO = "REQUEST_INFO"
    MANUAL_VERIFICATION = "MANUAL_VERIFICATION"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class DocumentType(str, Enum):
    """Recognised document archetypes across all scenarios."""

    resume = "resume"
    cover_letter = "cover_letter"
    transcript = "transcript"
    degree_certificate = "degree_certificate"
    id_document = "id_document"
    marksheet = "marksheet"
    registration_letter = "registration_letter"
    offer_letter = "offer_letter"
    reference_letter = "reference_letter"
    unknown = "unknown"


class IssueKind(str, Enum):
    """Kind of issue or discrepancy flagged on a field or document."""

    missing = "missing"
    unclear = "unclear"
    conflict = "conflict"
    unreliable = "unreliable"
    poor_quality = "poor_quality"
    unknown_type = "unknown_type"
    missing_document = "missing_document"
    unsupported_file = "unsupported_file"
    rejected_file = "rejected_file"
    duplicate_file = "duplicate_file"
    no_sender = "no_sender"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def field_key(doc_type: DocumentType | str, field: str) -> str:
    """Generate canonical key '{doc_type}.{field}' for CaseRecord.fields."""
    dt = doc_type.value if isinstance(doc_type, DocumentType) else str(doc_type)
    return f"{dt}.{field}"


# ---------------------------------------------------------------------------
# Geometry / OCR primitives
# ---------------------------------------------------------------------------


class BBox(BaseModel):
    """Axis-aligned bounding box in page-pixel coordinates (top-left origin)."""

    x0: float = Field(..., description="Left edge in pixels")
    y0: float = Field(..., description="Top edge in pixels")
    x1: float = Field(..., description="Right edge in pixels")
    y1: float = Field(..., description="Bottom edge in pixels")

    @model_validator(mode="after")
    def _check_ordering(self) -> "BBox":
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("x1 must be >= x0 and y1 must be >= y0")
        return self

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height


class ParsedLine(BaseModel):
    """One line of text from a parsed page, with provenance."""

    text: str = Field(..., description="Raw text content of the line")
    page: int = Field(
        ..., ge=0, description="0-based page index (display as page+1 to users)"
    )
    bbox: Optional[BBox] = Field(None, description="Bounding box on the page")
    conf: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="OCR / reader confidence score (None = not assessed)",
    )


# ---------------------------------------------------------------------------
# Parsed document (output of parse/ layer)
# ---------------------------------------------------------------------------


class ParsedDocument(BaseModel):
    """Normalised representation of a single document after parsing.

    Produced by any concrete Reader and consumed by classify/ and extract/.
    """

    doc_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique document identifier (UUID4)",
    )
    sha256: str = Field(..., description="SHA-256 hex digest of the source file")
    pages: int = Field(..., ge=1, description="Total number of pages")
    lines: list[ParsedLine] = Field(default_factory=list)
    tables: list[list[list[str]]] = Field(
        default_factory=list,
        description="Nested list: [table][row][cell] – plain text cells",
    )
    text_by_page: dict[int, str] = Field(
        default_factory=dict,
        description="Full concatenated text per 0-based page index",
    )
    reader_name: str = Field(
        "unknown", description="Name of the Reader that produced this output"
    )
    meta: dict[str, Any] = Field(
        default_factory=dict,
        description="Reader-specific metadata (e.g. DPI, colour space, language)",
    )

    @property
    def full_text(self) -> str:
        """All pages concatenated with double newlines."""
        return "\n\n".join(self.text_by_page.get(p, "") for p in range(self.pages))


# ---------------------------------------------------------------------------
# Document record (after classify / before extract)
# ---------------------------------------------------------------------------


class DocumentRecord(BaseModel):
    """One physical file attached to a case, post-ingest + post-parse."""

    doc_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    sha256: str
    mime_type: str = ""
    storage_path: str = Field(
        ...,
        description="Read-only path inside data/originals/ where file is stored",
    )
    pages: int = 1
    doc_type: DocumentType = DocumentType.unknown
    doc_type_confidence: float = Field(0.0, ge=0.0, le=1.0)
    quality_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Ingest-layer quality gate score (None = not assessed)",
    )
    quality_verdict: Optional[Literal["ok", "warn", "poor"]] = Field(
        None, description="Ingest quality assessment verdict"
    )
    quality_issues: list[str] = Field(
        default_factory=list, description="Quality issues flagged during ingest"
    )
    page_images: list[str] = Field(
        default_factory=list, description="Rendered page image paths"
    )
    pdf_has_text_layer: bool = Field(
        False, description="Whether PDF has an extractable text layer"
    )
    is_duplicate: bool = Field(
        False, description="Whether this document is a duplicate file"
    )
    is_readable: Optional[bool] = Field(
        None, description="Whether document is readable (None = not assessed)"
    )
    parsed: Optional[ParsedDocument] = None
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Field extraction results
# ---------------------------------------------------------------------------


class FieldResult(BaseModel):
    """Outcome of extracting and validating one logical field from a case."""

    field: str = Field(..., description="Field name as defined in the scenario YAML")
    doc_type: Optional[DocumentType] = Field(
        None, description="Document type this field was extracted from"
    )
    value: Optional[str] = Field(
        None, description="Final reconciled value chosen by the pipeline"
    )
    ocr_value: Optional[str] = Field(
        None, description="Raw value from the OCR/text reader"
    )
    vlm_value: Optional[str] = Field(
        None, description="Raw value from the VLM reader (Qwen3-VL)"
    )
    evidence_quote: Optional[str] = Field(
        None,
        description="Verbatim text snippet from the source that supports the value",
    )
    page: Optional[int] = Field(
        None, ge=0, description="0-based page where found (display as page+1 to users)"
    )
    bbox: Optional[BBox] = None
    status: FieldStatus = FieldStatus.missing
    reason: str = Field("", description="Human-readable explanation of the status")
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    source_doc_id: Optional[str] = Field(
        None, description="doc_id of the document this field was drawn from"
    )


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------


class Issue(BaseModel):
    """A single discrepancy or problem flagged during validation."""

    field: str = Field(..., description="The field name that triggered the issue")
    kind: IssueKind = Field(
        ..., description="The issue kind that caused this problem"
    )
    detail: str = Field("", description="Human-readable description of the problem")
    doc: Optional[str] = Field(None, description="Filename of the relevant document")
    page: Optional[int] = Field(
        None, ge=0, description="0-based page where found (display as page+1 to users)"
    )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class Decision(BaseModel):
    """Policy engine output for a single case."""

    route: Route
    workflow_status: WorkflowStatus
    reasons: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(
        default_factory=list,
        description="IDs of the policy rules that fired (from YAML)",
    )
    decided_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    decided_by: str = Field(
        "policy_engine",
        description="Always 'policy_engine' – the LLM never makes decisions",
    )


# ---------------------------------------------------------------------------
# Case record (the central unit of work)
# ---------------------------------------------------------------------------


class CaseRecord(BaseModel):
    """Complete representation of one applicant case through the pipeline."""

    case_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique case identifier (UUID4)",
    )
    scenario: str = Field(
        ..., description="Scenario name matching a config YAML (e.g. job_application)"
    )

    # Email provenance
    sender_email: str = Field(
        "", description="From: address of the source email (may be empty)"
    )
    sender_name: str = Field("", description="Display name parsed from From: header")
    message_id: str = Field("", description="Message-ID header of the source email")
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    subject: str = Field("", description="Email subject line")

    # Intake & documents
    documents: list[DocumentRecord] = Field(default_factory=list)
    missing_documents: list[str] = Field(
        default_factory=list,
        description="Names of required document types not present in submission",
    )
    intake_notes: list[str] = Field(
        default_factory=list,
        description="Warnings/notices logged during email and archive ingest",
    )
    skipped_files: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Files skipped during ingest (e.g. unsupported, rejected, duplicate)",
    )

    # Extraction
    fields: dict[str, FieldResult] = Field(
        default_factory=dict,
        description="Mapping of '{doc_type}.{field}' -> FieldResult after extraction",
    )
    issues: list[Issue] = Field(default_factory=list)

    # Decision (populated by decide/ – decision is the source of truth)
    workflow_status: WorkflowStatus = WorkflowStatus.received
    decision: Optional[Decision] = None

    # Audit
    pipeline_version: str = "0.1.0"
    error: Optional[str] = Field(
        None,
        description="Set when a fatal per-case error occurs; never stops the batch",
    )

    @staticmethod
    def field_key(doc_type: DocumentType | str, field: str) -> str:
        """Helper for '{doc_type}.{field}' key generation."""
        return field_key(doc_type, field)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def route(self) -> Optional[Route]:
        """Routing outcome derived from decision (read-only)."""
        return self.decision.route if self.decision is not None else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reasons(self) -> list[str]:
        """Decision reasons derived from decision (read-only)."""
        return self.decision.reasons if self.decision is not None else []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rule_ids(self) -> list[str]:
        """Firing rule IDs derived from decision (read-only)."""
        return self.decision.rule_ids if self.decision is not None else []

    def has_conflict(self) -> bool:
        return any(f.status == FieldStatus.conflict for f in self.fields.values())

    def has_unreliable(self) -> bool:
        return any(f.status == FieldStatus.unreliable for f in self.fields.values())

    def missing_required(
        self,
        required: list[str],
        doc_type: Optional[DocumentType | str] = None,
    ) -> list[str]:
        """Return names/keys of required fields that are missing.

        Accepts canonical '{doc_type}.{field}' keys or bare field names with optional doc_type.
        """
        missing: list[str] = []
        for req in required:
            key = req if (doc_type is None or "." in req) else field_key(doc_type, req)
            fr = self.fields.get(key)
            if fr is None:
                if "." not in key:
                    matching = [f for k, f in self.fields.items() if k.endswith(f".{key}")]
                    if matching:
                        if any(f.status == FieldStatus.missing for f in matching):
                            missing.append(req)
                        continue
                missing.append(req)
            elif fr.status == FieldStatus.missing:
                missing.append(req)
        return missing
