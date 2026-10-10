# Owner: Laptop B
"""INX – Decision explainer: human-readable rationale for routing outcomes.

Transforms the machine-readable :class:`Decision` (rule IDs + reasons list)
and case issues into plain language suitable for applicant emails and audit reports.
"""

from __future__ import annotations

from app.schemas import CaseRecord, Issue


def explain_issue(issue: Issue) -> str:
    """Format a single :class:`Issue` as a one-line human-readable string.

    Page numbers are shown 1-based (+1) to humans.
    """
    parts = [f"Field '{issue.field}'"]
    if issue.page is not None:
        parts.append(f"on page {issue.page + 1}")
    if issue.doc:
        parts.append(f"(doc: {issue.doc})")
    parts.append(f"[{issue.kind.value}]:")
    parts.append(issue.detail or "Discrepancy flagged")
    return " ".join(parts)


def explain_decision(case: CaseRecord) -> str:
    """Return a multi-line plain-text explanation of the case's decision.

    Built strictly from the fired rules and issues (field, page, rule id).

    Raises:
        ValueError: If ``case.decision`` is ``None``.
    """
    if case.decision is None:
        raise ValueError("Cannot explain case without a decision")

    lines = [
        f"Decision: {case.decision.route.value} (Workflow Status: {case.decision.workflow_status.value})",
        "",
        "Policy Rules Fired:",
    ]

    if case.decision.rule_ids:
        for idx, rule_id in enumerate(case.decision.rule_ids):
            reason_str = (
                case.decision.reasons[idx]
                if idx < len(case.decision.reasons)
                else "Policy condition satisfied"
            )
            lines.append(f"  - [{rule_id}] {reason_str}")
    else:
        for reason in case.decision.reasons:
            lines.append(f"  - {reason}")
        if not case.decision.reasons:
            lines.append("  - (No policy rules fired)")

    lines.append("")
    lines.append("Issues Identified:")
    if case.issues:
        for issue in case.issues:
            lines.append(f"  - {explain_issue(issue)}")
    else:
        lines.append("  - None (all validation checks passed)")

    return "\n".join(lines)


def build_applicant_message(case: CaseRecord, template_name: str = "default") -> str:
    """Render a polite, plain-language notification message for the applicant."""
    if case.decision is None:
        return "Your application is currently being processed."

    # Use first available reason or standard status message
    primary_reason = (
        case.decision.reasons[0]
        if case.decision.reasons
        else "Your application status has been updated."
    )

    if case.decision.route.value == "PROCESS":
        return (
            "Thank you for your submission. All documents and required fields "
            "have been verified successfully. Your application has proceeded to processing."
        )
    elif case.decision.route.value == "REQUEST_INFO":
        return (
            f"Your application requires additional information: {primary_reason} "
            "Please reply with the missing documents or details at your earliest convenience."
        )
    elif case.decision.route.value in ("HUMAN_REVIEW", "MANUAL_VERIFICATION"):
        return (
            f"Your application has been received and is undergoing review: {primary_reason} "
            "Our verification team will contact you if any further details are required."
        )
    return primary_reason
