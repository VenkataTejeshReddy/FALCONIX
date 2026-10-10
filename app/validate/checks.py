# Owner: Laptop B
"""INX – Field-level validation checks.

Each validator is a function with signature::

    def validate_<name>(value: str, **kwargs) -> tuple[FieldStatus, str]:
        ...

Returns a (status, reason) pair.  Validators are named in ``validators``
lists inside scenario YAML files and resolved by name at runtime.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from app.config import ScenarioConfig, load_scenario
from app.schemas import (
    CaseRecord,
    DocumentType,
    FieldResult,
    FieldStatus,
    Issue,
    IssueKind,
    field_key,
)
from app.validate.dates import age_from_dob, is_plausible_dob, parse_date
from app.validate.identifiers import (
    validate_govt_id,
    validate_registration,
)

# Type alias for validators
Validator = Callable[..., tuple[FieldStatus, str]]

# Registry populated by @register_validator
_REGISTRY: dict[str, Validator] = {}


def register_validator(name: str):
    """Decorator that registers a validator function by name."""

    def decorator(fn: Validator) -> Validator:
        _REGISTRY[name] = fn
        return fn

    return decorator


def get_validator(name: str) -> Validator:
    """Look up a registered validator by name.

    Raises:
        KeyError: If no validator with *name* is registered.
    """
    if name not in _REGISTRY:
        raise KeyError(f"No validator registered: {name!r}")
    return _REGISTRY[name]


# ---------------------------------------------------------------------------
# Built-in validators
# ---------------------------------------------------------------------------


@register_validator("non_empty")
def validate_non_empty(value: str, **_) -> tuple[FieldStatus, str]:
    """Fail if the value is blank or whitespace-only."""
    if not value or not value.strip():
        return FieldStatus.missing, "Field is empty or missing"
    return FieldStatus.valid, "Non-empty value present"


@register_validator("no_digits")
def validate_no_digits(value: str, **_) -> tuple[FieldStatus, str]:
    """Fail if the value contains any numeric digit (e.g. a name field)."""
    if not value:
        return FieldStatus.missing, "Field is empty"
    if any(ch.isdigit() for ch in value):
        return (
            FieldStatus.unreliable,
            f"Value contains invalid numeric characters: {value!r}",
        )
    return FieldStatus.valid, "No digits found"


@register_validator("email_format")
def validate_email_format(value: str, **_) -> tuple[FieldStatus, str]:
    """Basic RFC 5321 email format check."""
    if not value or not value.strip():
        return FieldStatus.missing, "Email is missing"
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    if not re.match(pattern, value.strip()):
        return FieldStatus.unreliable, f"Invalid email format: {value!r}"
    return FieldStatus.valid, "Valid email format"


@register_validator("phone_format")
def validate_phone_format(value: str, **_) -> tuple[FieldStatus, str]:
    """Accept 7–20 digit strings with optional '+', spaces, dashes, parentheses."""
    if not value or not value.strip():
        return FieldStatus.missing, "Phone number is missing"
    digits = re.sub(r"\D", "", value)
    if not (7 <= len(digits) <= 15):
        return (
            FieldStatus.unreliable,
            f"Invalid phone number length ({len(digits)} digits): {value!r}",
        )
    if not re.match(r"^\+?[0-9\s\-().]{7,25}$", value.strip()):
        return FieldStatus.unreliable, f"Invalid phone format: {value!r}"
    return FieldStatus.valid, "Valid phone format"


@register_validator("date_format")
def validate_date_format(value: str, **_) -> tuple[FieldStatus, str]:
    """Accept common date formats: DD/MM/YYYY, YYYY-MM-DD, DD-Mon-YYYY, etc."""
    if not value or not value.strip():
        return FieldStatus.missing, "Date is missing"
    d = parse_date(value)
    if d is None:
        return FieldStatus.unreliable, f"Unparseable or impossible date: {value!r}"
    return FieldStatus.valid, f"Parsed date: {d.isoformat()}"


@register_validator("dob_range")
def validate_dob_range(value: str, **_) -> tuple[FieldStatus, str]:
    """Ensure applicant age is within a plausible range (16–100 years)."""
    if not value or not value.strip():
        return FieldStatus.missing, "Date of birth is missing"
    d = parse_date(value)
    if d is None:
        return FieldStatus.unreliable, f"Invalid date of birth: {value!r}"
    if not is_plausible_dob(d, min_age=16, max_age=100):
        age = age_from_dob(d)
        return (
            FieldStatus.unreliable,
            f"Implausible applicant age ({age} years) from DOB {value!r}",
        )
    return FieldStatus.valid, f"Valid DOB ({age_from_dob(d)} years old)"


@register_validator("govt_id_format")
def validate_govt_id_format(value: str, **_) -> tuple[FieldStatus, str]:
    """Validate 12-digit government identification with Verhoeff checksum."""
    if not value or not value.strip():
        return FieldStatus.missing, "Government ID is missing"
    if not validate_govt_id(value):
        return (
            FieldStatus.unreliable,
            f"Invalid 12-digit government ID format or failed Verhoeff checksum: {value!r}",
        )
    return FieldStatus.valid, "Valid 12-digit ID with Verhoeff checksum"


# Backwards compatibility alias
_REGISTRY["id_format"] = validate_govt_id_format


@register_validator("registration_format")
def validate_registration_format(
    value: str, regex: Optional[str] = None, **_
) -> tuple[FieldStatus, str]:
    """Validate institution registration/roll number against regex."""
    if not value or not value.strip():
        return FieldStatus.missing, "Registration number is missing"
    if not validate_registration(value, pattern=regex):
        return (
            FieldStatus.unreliable,
            f"Registration number {value!r} does not match expected pattern {regex or 'alphanumeric'}",
        )
    return FieldStatus.valid, "Valid registration format"


@register_validator("number_range")
def validate_number_range(
    value: str,
    min: Optional[int | float] = None,
    max: Optional[int | float] = None,
    **_,
) -> tuple[FieldStatus, str]:
    """Validate numeric value falls within [min, max] range (e.g. years of experience)."""
    if not value or not value.strip():
        return FieldStatus.missing, "Numeric value is missing"
    try:
        # Extract leading numeric component if present (e.g. '5 years' -> 5)
        m = re.search(r"[-+]?[0-9]*\.?[0-9]+", value)
        if not m:
            return FieldStatus.unreliable, f"No numeric value found in {value!r}"
        num = float(m.group(0))
    except (ValueError, TypeError):
        return FieldStatus.unreliable, f"Cannot parse numeric value from {value!r}"

    if min is not None and num < min:
        return FieldStatus.unreliable, f"Value {num} is below minimum {min}"
    if max is not None and num > max:
        return FieldStatus.unreliable, f"Value {num} exceeds maximum {max}"

    return FieldStatus.valid, f"Value {num} is within [{min}, {max}]"


@register_validator("grade_format")
def validate_grade_format(value: str, **_) -> tuple[FieldStatus, str]:
    """Validate academic grade or marks."""
    if not value or not value.strip():
        return FieldStatus.missing, "Marks or grade is missing"
    cleaned = value.strip()
    # Accept percentages, letter grades (A+, B, etc.), GPA/CGPA (8.5/10), or divisions
    if re.search(r"^[A-F][+-]?$|^\d+(\.\d+)?(\s*(\%|cgpa|gpa|/\s*\d+))?$|first|second|pass|distinction", cleaned, re.IGNORECASE):
        return FieldStatus.valid, f"Valid grade/marks format: {cleaned}"
    return FieldStatus.unclear, f"Unrecognized grade format: {cleaned}"


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------

_STATUS_SEVERITY: dict[FieldStatus, int] = {
    FieldStatus.valid: 0,
    FieldStatus.unclear: 1,
    FieldStatus.unreliable: 2,
    FieldStatus.conflict: 3,
    FieldStatus.missing: 4,
}


def run_validators(
    field_name: str,
    value: Optional[str],
    validator_names: list[str],
    **kwargs: Any,
) -> tuple[FieldStatus, str]:
    """Run all named validators for *field_name* and return the worst outcome.

    Never defaults an unknown or unassessed value to valid.
    """
    if not validator_names:
        if not value or not value.strip():
            return FieldStatus.missing, f"Field '{field_name}' is empty"
        return FieldStatus.valid, "Value present (no validators defined)"

    # If empty, check if non_empty is among validators
    if not value or not value.strip():
        if "non_empty" in validator_names:
            return FieldStatus.missing, f"Required field '{field_name}' is missing"
        return FieldStatus.missing, f"Field '{field_name}' has empty value"

    worst_status = FieldStatus.valid
    reasons: list[str] = []

    for name in validator_names:
        fn = _REGISTRY.get(name)
        if fn is None:
            worst_status = FieldStatus.unclear
            reasons.append(f"Unknown validator {name!r}")
            continue

        status, reason = fn(value, **kwargs)
        if _STATUS_SEVERITY.get(status, 0) > _STATUS_SEVERITY.get(worst_status, 0):
            worst_status = status
        if status != FieldStatus.valid:
            reasons.append(reason)

    final_reason = "; ".join(reasons) if reasons else "All format checks passed"
    return worst_status, final_reason


def validate_case_fields(
    case: CaseRecord, config: Optional[ScenarioConfig] = None
) -> None:
    """Run all field validators across all expected documents in *case*.

    Appends identified issues to ``case.issues`` and updates field statuses.
    """
    cfg = config or load_scenario(case.scenario)

    # 1. Check required documents presence
    present_types = {d.doc_type.value for d in case.documents}
    for doc_type_name in cfg.required_doc_types:
        if doc_type_name not in present_types:
            if doc_type_name not in case.missing_documents:
                case.missing_documents.append(doc_type_name)
            case.issues.append(
                Issue(
                    field=doc_type_name,
                    kind=IssueKind.missing_document,
                    detail=f"Required document '{doc_type_name}' was not submitted",
                    doc=doc_type_name,
                )
            )

    # 2. Check each expected document's fields
    for doc_type_name, doc_spec in cfg.documents.items():
        doc_is_present = doc_type_name in present_types
        dt_enum = (
            DocumentType(doc_type_name)
            if doc_type_name in DocumentType._value2member_map_
            else DocumentType.unknown
        )
        if not doc_is_present and not doc_spec.required:
            continue

        for field_name, fspec in doc_spec.fields.items():
            key = field_key(doc_type_name, field_name)
            fr = case.fields.get(key)

            if not doc_is_present:
                if fspec.required:
                    if fr is None:
                        case.fields[key] = FieldResult(
                            field=field_name,
                            doc_type=dt_enum,
                            status=FieldStatus.missing,
                            reason=f"Document '{doc_type_name}' missing",
                        )
                    case.issues.append(
                        Issue(
                            field=field_name,
                            kind=IssueKind.missing,
                            detail=f"Field '{field_name}' missing because '{doc_type_name}' is not submitted",
                            doc=doc_type_name,
                        )
                    )
                continue

            if fr is None or not fr.value or not fr.value.strip():
                if fspec.required:
                    if fr is None:
                        fr = FieldResult(
                            field=field_name,
                            doc_type=dt_enum,
                            status=FieldStatus.missing,
                            reason=f"Required field '{field_name}' not found",
                        )
                        case.fields[key] = fr
                    else:
                        fr.status = FieldStatus.missing
                        fr.reason = f"Required field '{field_name}' is empty"

                    case.issues.append(
                        Issue(
                            field=field_name,
                            kind=IssueKind.missing,
                            detail=f"Required field '{field_name}' is missing in '{doc_type_name}'",
                            doc=doc_type_name,
                            page=fr.page,
                        )
                    )
                continue

            # fr has a value! Run validators
            val_status, val_reason = run_validators(
                field_name=field_name,
                value=fr.value,
                validator_names=fspec.validators,
                regex=fspec.regex,
                min=fspec.min,
                max=fspec.max,
            )
            # If the extractor already determined this field has an issue
            # (e.g. unclear, conflict, unreliable), preserve that status unless validator finds an issue
            if fr.status in (FieldStatus.unclear, FieldStatus.conflict, FieldStatus.unreliable):
                status = fr.status
                reason = fr.reason or val_reason
            else:
                status = val_status
                reason = val_reason

            fr.status = status
            fr.reason = reason

            if status != FieldStatus.valid:
                kind_map = {
                    FieldStatus.missing: IssueKind.missing,
                    FieldStatus.unclear: IssueKind.unclear,
                    FieldStatus.conflict: IssueKind.conflict,
                    FieldStatus.unreliable: IssueKind.unreliable,
                }
                case.issues.append(
                    Issue(
                        field=field_name,
                        kind=kind_map.get(status, IssueKind.unreliable),
                        detail=reason,
                        doc=doc_type_name,
                        page=fr.page,
                    )
                )
