# Owner: Laptop A
"""INX – Field schema: per-scenario extraction targets.

Defines which fields are expected for each scenario and document type,
and the normalisation / validation hint per field.  This module bridges
:mod:`app.config` (YAML) and the runtime extractor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from app.schemas import FieldStatus


@dataclass
class FieldTarget:
    """Extraction target for one field within a scenario."""

    name: str
    description: str = ""
    required: bool = True
    validators: list[str] = field(default_factory=list)
    normalise: Optional[Callable[[str], str]] = None
    """Optional normalisation function applied before validation."""


# ---------------------------------------------------------------------------
# Pre-built field targets shared across scenarios
# ---------------------------------------------------------------------------

APPLICANT_NAME = FieldTarget(
    name="applicant_name",
    description="Full legal name of the applicant",
    validators=["non_empty", "no_digits"],
)

EMAIL = FieldTarget(
    name="email",
    description="Contact email address",
    validators=["email_format"],
)

PHONE = FieldTarget(
    name="phone",
    description="Contact phone number",
    validators=["phone_format"],
)

DATE_OF_BIRTH = FieldTarget(
    name="date_of_birth",
    description="Applicant's date of birth",
    validators=["date_format", "dob_range"],
)

INSTITUTION = FieldTarget(
    name="institution",
    description="Name of the educational institution",
    validators=["non_empty"],
)

ID_NUMBER = FieldTarget(
    name="id_number",
    description="Government-issued identification number",
    validators=["non_empty", "id_format"],
)


def get_field_targets(scenario: str) -> list[FieldTarget]:
    """Return the ordered list of :class:`FieldTarget` objects for a scenario.

    Args:
        scenario: Scenario name (``"job_application"`` | ``"college"``).

    Returns:
        Ordered list of targets.  Order affects reconciliation priority.

    Raises:
        ValueError: If the scenario is unknown.
    """
    raise NotImplementedError
