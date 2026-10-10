# Owner: Laptop B
"""INX – Cross-document consistency checks.

After individual field validation, this module checks that field values
extracted from *different* documents in the same case are consistent with
each other (e.g. the name on the transcript matches the name on the ID).
"""

from __future__ import annotations

import re
from typing import Optional

from rapidfuzz import fuzz

from app.config import ScenarioConfig, load_scenario
from app.schemas import (
    CaseRecord,
    DocumentType,
    FieldResult,
    FieldStatus,
    Issue,
    IssueKind,
)
from app.validate.dates import parse_date
from app.validate.identifiers import normalise_id

# Common titles/honorifics to strip during name normalization
_HONORIFICS_RE = re.compile(
    r"\b(mr|mrs|ms|miss|dr|prof|shri|smt|km|master|sir|rev|md)\b\.?",
    re.IGNORECASE,
)


def normalise_name(name: str) -> str:
    """Normalize a person's name for robust cross-document comparison."""
    if not name:
        return ""
    text = name.strip()
    text = _HONORIFICS_RE.sub("", text)
    # Remove punctuation
    text = re.sub(r"[^\w\s]", "", text)
    # Collapse whitespace and lowercase
    return " ".join(text.lower().split())


def normalise_institution(inst: str) -> str:
    """Normalize institution name by stripping common stop-words and punctuation."""
    if not inst:
        return ""
    text = inst.strip().lower()
    text = re.sub(r"[^\w\s]", "", text)
    tokens = [
        t
        for t in text.split()
        if t not in {"the", "of", "for", "and", "&", "in", "at"}
    ]
    return " ".join(tokens)


def _get_fields_by_name(case: CaseRecord, field_name: str) -> list[tuple[str, FieldResult]]:
    """Return all (doc_key, FieldResult) pairs in case where field matches *field_name*."""
    results: list[tuple[str, FieldResult]] = []
    for k, fr in case.fields.items():
        if fr.field == field_name and fr.value and fr.value.strip():
            results.append((k, fr))
    return results


def cross_check_name(
    case: CaseRecord,
    fuzzy_exact: float = 95.0,
    fuzzy_near: float = 85.0,
) -> list[Issue]:
    """Verify applicant_name is consistent across all documents in *case*.

    Exact match = valid;
    Near match = conflict with reason 'probable typo';
    Clear mismatch = conflict.
    """
    pairs = _get_fields_by_name(case, "applicant_name")
    if len(pairs) < 2:
        return []

    issues: list[Issue] = []
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            k1, fr1 = pairs[i]
            k2, fr2 = pairs[j]
            val1 = fr1.value or ""
            val2 = fr2.value or ""

            norm1 = normalise_name(val1)
            norm2 = normalise_name(val2)
            doc1 = fr1.doc_type.value if fr1.doc_type else k1
            doc2 = fr2.doc_type.value if fr2.doc_type else k2

            if norm1 == norm2:
                continue

            tokens1 = norm1.split()
            tokens2 = norm2.split()

            # Check if tokens are identical but in inverted order (e.g. Reddy Venkata vs Venkata Reddy)
            if sorted(tokens1) == sorted(tokens2) and tokens1 != tokens2:
                detail = f"name order inverted: '{val1}' ({doc1}) vs '{val2}' ({doc2})"
                fr1.status = FieldStatus.conflict
                fr2.status = FieldStatus.conflict
                fr1.reason = detail
                fr2.reason = detail
                issues.append(
                    Issue(
                        field="applicant_name",
                        kind=IssueKind.conflict,
                        detail=detail,
                        doc=f"{doc1}, {doc2}",
                        page=fr1.page,
                    )
                )
                continue

            # Check if one contains initials matching the other (e.g. P. Sharma vs Priya Sharma)
            is_initial_variant = False
            if len(tokens1) == len(tokens2):
                diffs = 0
                initial_match = True
                for t1, t2 in zip(tokens1, tokens2):
                    if t1 != t2:
                        diffs += 1
                        if (len(t1) == 1 and t2.startswith(t1)) or (len(t2) == 1 and t1.startswith(t2)):
                            pass
                        else:
                            initial_match = False
                if diffs > 0 and initial_match:
                    is_initial_variant = True

            if is_initial_variant:
                detail = f"initial vs full name: '{val1}' ({doc1}) vs '{val2}' ({doc2})"
                fr1.status = FieldStatus.conflict
                fr2.status = FieldStatus.conflict
                fr1.reason = detail
                fr2.reason = detail
                issues.append(
                    Issue(
                        field="applicant_name",
                        kind=IssueKind.conflict,
                        detail=detail,
                        doc=f"{doc1}, {doc2}",
                        page=fr1.page,
                    )
                )
                continue

            ratio = fuzz.token_sort_ratio(norm1, norm2)
            doc1 = fr1.doc_type.value if fr1.doc_type else k1
            doc2 = fr2.doc_type.value if fr2.doc_type else k2

            if ratio >= fuzzy_exact:
                # Treated as equivalent
                continue
            elif ratio >= fuzzy_near:
                # Near match -> probable typo
                detail = f"probable typo: '{val1}' ({doc1}) vs '{val2}' ({doc2}) [similarity {ratio:.1f}%]"
                fr1.status = FieldStatus.conflict
                fr2.status = FieldStatus.conflict
                fr1.reason = detail
                fr2.reason = detail
                issues.append(
                    Issue(
                        field="applicant_name",
                        kind=IssueKind.conflict,
                        detail=detail,
                        doc=f"{doc1}, {doc2}",
                        page=fr1.page,
                    )
                )
            else:
                # Clear mismatch
                detail = f"applicant_name conflict: '{val1}' ({doc1}) does not match '{val2}' ({doc2}) [similarity {ratio:.1f}%]"
                fr1.status = FieldStatus.conflict
                fr2.status = FieldStatus.conflict
                fr1.reason = detail
                fr2.reason = detail
                issues.append(
                    Issue(
                        field="applicant_name",
                        kind=IssueKind.conflict,
                        detail=detail,
                        doc=f"{doc1}, {doc2}",
                        page=fr1.page,
                    )
                )

    return issues


def cross_check_dob(case: CaseRecord) -> list[Issue]:
    """Verify date_of_birth is consistent across all documents in *case*."""
    pairs = _get_fields_by_name(case, "date_of_birth")
    if len(pairs) < 2:
        return []

    issues: list[Issue] = []
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            k1, fr1 = pairs[i]
            k2, fr2 = pairs[j]
            d1 = parse_date(fr1.value or "")
            d2 = parse_date(fr2.value or "")
            doc1 = fr1.doc_type.value if fr1.doc_type else k1
            doc2 = fr2.doc_type.value if fr2.doc_type else k2

            if d1 and d2 and d1 != d2:
                detail = f"Date of birth mismatch: '{fr1.value}' ({doc1}) vs '{fr2.value}' ({doc2})"
                fr1.status = FieldStatus.conflict
                fr2.status = FieldStatus.conflict
                fr1.reason = detail
                fr2.reason = detail
                issues.append(
                    Issue(
                        field="date_of_birth",
                        kind=IssueKind.conflict,
                        detail=detail,
                        doc=f"{doc1}, {doc2}",
                        page=fr1.page,
                    )
                )
    return issues


def cross_check_id(
    case: CaseRecord,
    fuzzy_exact: float = 95.0,
    fuzzy_near: float = 85.0,
) -> list[Issue]:
    """Verify id_number is consistent across all documents in *case*."""
    pairs = _get_fields_by_name(case, "id_number")
    if len(pairs) < 2:
        return []

    issues: list[Issue] = []
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            k1, fr1 = pairs[i]
            k2, fr2 = pairs[j]
            norm1 = normalise_id(fr1.value or "")
            norm2 = normalise_id(fr2.value or "")
            doc1 = fr1.doc_type.value if fr1.doc_type else k1
            doc2 = fr2.doc_type.value if fr2.doc_type else k2

            if norm1 == norm2:
                continue

            ratio = fuzz.ratio(norm1, norm2)
            if ratio >= fuzzy_near:
                detail = f"probable typo in ID number: '{fr1.value}' ({doc1}) vs '{fr2.value}' ({doc2})"
            else:
                detail = f"ID number mismatch: '{fr1.value}' ({doc1}) vs '{fr2.value}' ({doc2})"

            fr1.status = FieldStatus.conflict
            fr2.status = FieldStatus.conflict
            fr1.reason = detail
            fr2.reason = detail
            issues.append(
                Issue(
                    field="id_number",
                    kind=IssueKind.conflict,
                    detail=detail,
                    doc=f"{doc1}, {doc2}",
                    page=fr1.page,
                )
            )

    return issues


def cross_check_institution(
    case: CaseRecord,
    fuzzy_exact: float = 95.0,
    fuzzy_near: float = 85.0,
) -> list[Issue]:
    """Verify institution is consistent across documents."""
    pairs = _get_fields_by_name(case, "institution")
    if len(pairs) < 2:
        return []

    issues: list[Issue] = []
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            k1, fr1 = pairs[i]
            k2, fr2 = pairs[j]
            norm1 = normalise_institution(fr1.value or "")
            norm2 = normalise_institution(fr2.value or "")
            doc1 = fr1.doc_type.value if fr1.doc_type else k1
            doc2 = fr2.doc_type.value if fr2.doc_type else k2

            if norm1 == norm2:
                continue

            ratio = fuzz.token_sort_ratio(norm1, norm2)
            if ratio >= fuzzy_exact:
                continue
            elif ratio >= fuzzy_near:
                detail = f"probable typo in institution: '{fr1.value}' ({doc1}) vs '{fr2.value}' ({doc2})"
            else:
                detail = f"Institution mismatch: '{fr1.value}' ({doc1}) vs '{fr2.value}' ({doc2})"

            fr1.status = FieldStatus.conflict
            fr2.status = FieldStatus.conflict
            fr1.reason = detail
            fr2.reason = detail
            issues.append(
                Issue(
                    field="institution",
                    kind=IssueKind.conflict,
                    detail=detail,
                    doc=f"{doc1}, {doc2}",
                    page=fr1.page,
                )
            )

    return issues


def cross_check_dates(case: CaseRecord) -> list[Issue]:
    """Ensure dates within a case are logically ordered (e.g. issue_date >= date_of_birth)."""
    issues: list[Issue] = []
    dobs = _get_fields_by_name(case, "date_of_birth")
    issue_dates = _get_fields_by_name(case, "issue_date")

    for _, fr_dob in dobs:
        dob = parse_date(fr_dob.value or "")
        if not dob:
            continue
        for _, fr_iss in issue_dates:
            iss = parse_date(fr_iss.value or "")
            if not iss:
                continue
            if iss < dob:
                detail = f"Issue date ({iss}) cannot be earlier than date of birth ({dob})"
                fr_iss.status = FieldStatus.conflict
                fr_iss.reason = detail
                issues.append(
                    Issue(
                        field="issue_date",
                        kind=IssueKind.conflict,
                        detail=detail,
                        doc=fr_iss.doc_type.value if fr_iss.doc_type else None,
                        page=fr_iss.page,
                    )
                )
    return issues


def run_cross_checks(
    case: CaseRecord, config: Optional[ScenarioConfig] = None
) -> list[Issue]:
    """Execute all cross-document checks and append issues to *case*."""
    cfg = config or load_scenario(case.scenario)
    fuzzy_exact = cfg.thresholds.fuzzy_exact if cfg.thresholds else 95.0
    fuzzy_near = cfg.thresholds.fuzzy_near if cfg.thresholds else 85.0

    all_issues: list[Issue] = []

    # Run check per field in cfg.crossdoc.compare
    to_compare = set(cfg.crossdoc.compare) if cfg.crossdoc else set()
    if not to_compare:
        to_compare = {"applicant_name", "id_number", "institution", "date_of_birth"}

    if "applicant_name" in to_compare:
        all_issues.extend(
            cross_check_name(case, fuzzy_exact=fuzzy_exact, fuzzy_near=fuzzy_near)
        )
    if "date_of_birth" in to_compare or "dob" in to_compare:
        all_issues.extend(cross_check_dob(case))
    if "id_number" in to_compare:
        all_issues.extend(
            cross_check_id(case, fuzzy_exact=fuzzy_exact, fuzzy_near=fuzzy_near)
        )
    if "institution" in to_compare:
        all_issues.extend(
            cross_check_institution(case, fuzzy_exact=fuzzy_exact, fuzzy_near=fuzzy_near)
        )

    all_issues.extend(cross_check_dates(case))

    case.issues.extend(all_issues)
    return all_issues
