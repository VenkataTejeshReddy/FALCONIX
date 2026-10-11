# Owner: Laptop B
"""INX – Email drafter: generate notification emails from structured issues.

Produces plain-text and HTML email bodies from Jinja2 templates stored in
``app/notify/templates/``.  The drafter never sends emails itself; that is
handled by :mod:`app.notify.sender`.

Email policy
------------
- **AUTO-SEND** for: missing, missing_document, poor_quality, rejected_file,
  unsupported_file.  These are unambiguous problems the applicant must address.
- **HOLD** for reviewer approval: conflict, unclear, unreliable, and any
  format failure.  An 11-digit ID may be an OCR misread; do not accuse an
  applicant automatically.
- One email per case, grouped by issue.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.decide.explain import explain_issue
from app.schemas import CaseRecord, IssueKind

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# ---------------------------------------------------------------------------
# Issue-kind → email policy mapping
# ---------------------------------------------------------------------------

# AUTO-SEND: safe to send without human review
AUTO_SEND_KINDS: frozenset[IssueKind] = frozenset({
    IssueKind.missing,
    IssueKind.missing_document,
    IssueKind.poor_quality,
    IssueKind.rejected_file,
    IssueKind.unsupported_file,
})

# HOLD: require reviewer approval before sending
HOLD_KINDS: frozenset[IssueKind] = frozenset({
    IssueKind.conflict,
    IssueKind.unclear,
    IssueKind.unreliable,
})

# These are never emailed to the applicant (internal routing)
INTERNAL_KINDS: frozenset[IssueKind] = frozenset({
    IssueKind.duplicate_file,
    IssueKind.unknown_type,
    IssueKind.no_sender,
})


def classify_email_action(case: CaseRecord) -> str:
    """Determine whether a notification should be auto-sent or held.

    Returns:
        ``"auto"``  – safe to send immediately.
        ``"held"``  – requires reviewer approval.
        ``"none"``  – no email should be sent.
    """
    # Never email manual@upload.local
    if case.sender_email == "manual@upload.local":
        return "none"

    # Never email if no sender
    if not case.sender_email:
        return "none"

    if not case.issues:
        # No issues → PROCESS route gets a confirmation email
        if case.route and case.route.value == "PROCESS":
            return "auto"
        return "none"

    has_hold = False
    has_auto = False

    for iss in case.issues:
        detail_lower = (iss.detail or "").lower()
        is_format_failure = any(term in detail_lower for term in ("format", "checksum", "digit", "invalid date", "regex", "length"))
        if iss.kind in HOLD_KINDS or is_format_failure:
            has_hold = True
        elif iss.kind in AUTO_SEND_KINDS:
            has_auto = True
        # INTERNAL_KINDS are ignored for applicant email policy

    if has_hold:
        return "held"
    if has_auto:
        return "auto"
    return "none"


def _get_jinja_env() -> Environment:
    """Create a Jinja2 environment pointing at the templates directory."""
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _build_issue_lines(case: CaseRecord) -> list[str]:
    """Build human-readable issue descriptions using explain.py."""
    return [explain_issue(iss) for iss in case.issues]


def draft_email(
    case: CaseRecord,
    template_name: Optional[str] = None,
    polish_client: Optional[Any] = None,
) -> tuple[str, str, str]:
    """Render subject, plain-text body, and HTML body for a case notification.

    The template is chosen based on ``case.route`` if *template_name* is not
    provided::

        PROCESS              -> notification.txt / notification.html
        REQUEST_INFO         -> notification.txt / notification.html
        MANUAL_VERIFICATION  -> notification.txt / notification.html
        HUMAN_REVIEW         -> notification.txt / notification.html

    Args:
        case: The decided :class:`CaseRecord`.
        template_name: Override the auto-selected template stem.
        polish_client: Optional model client for notification rewording.

    Returns:
        A 3-tuple of ``(subject, plain_body, html_body)``.

    Raises:
        ValueError: If ``case.decision`` is ``None``.
    """
    if case.decision is None:
        raise ValueError("Cannot draft email for case without a decision")

    env = _get_jinja_env()
    issue_lines = _build_issue_lines(case)
    action = classify_email_action(case)

    # Determine recipient name
    recipient_name = case.sender_name or case.sender_email

    # Determine reply-to / from
    route_val = case.route.value if case.route else "UNKNOWN"

    # Build template context
    context = {
        "case": case,
        "recipient_name": recipient_name,
        "route": route_val,
        "issue_lines": issue_lines,
        "issues": case.issues,
        "fields": case.fields,
        "action": action,
        "case_id": case.case_id,
        "scenario": case.scenario,
    }

    # Subject line
    if route_val == "PROCESS":
        subject = f"Your Application Has Been Received – Ref: {case.case_id[:8]}"
    elif route_val == "REQUEST_INFO":
        subject = f"Action Required: Your Application – Ref: {case.case_id[:8]}"
    elif route_val == "MANUAL_VERIFICATION":
        subject = f"Application Under Review – Ref: {case.case_id[:8]}"
    else:
        subject = f"Application Status Update – Ref: {case.case_id[:8]}"

    # Render plain-text template
    try:
        txt_tpl = env.get_template("notification.txt")
        plain_body = txt_tpl.render(**context)
    except Exception:
        logger.warning("notification.txt template not found, using fallback")
        plain_body = _fallback_plain(case, issue_lines, route_val)

    # Render HTML template
    try:
        html_tpl = env.get_template("notification.html")
        html_body = html_tpl.render(**context)
    except Exception:
        logger.warning("notification.html template not found, using fallback")
        html_body = _fallback_html(case, issue_lines, route_val)

    # Optional polish if enabled or test client provided
    from app.notify.polish import is_polish_enabled, polish_notification
    if is_polish_enabled() or polish_client is not None:
        subject, plain_body, html_body = polish_notification(
            subject=subject,
            plain_body=plain_body,
            html_body=html_body,
            case=case,
            client=polish_client,
        )

    return subject, plain_body, html_body


def _fallback_plain(case: CaseRecord, issue_lines: list[str], route: str) -> str:
    """Minimal plain-text fallback when templates are missing."""
    lines = [
        f"Dear {case.sender_name or case.sender_email},",
        "",
    ]
    if route == "PROCESS":
        lines.append(
            "Your submission has been received and verified successfully. "
            "It has been forwarded for processing."
        )
    elif route == "REQUEST_INFO":
        lines.append(
            "We have reviewed your submission and found that additional "
            "information is required."
        )
    else:
        lines.append(
            "Your submission has been received and is under review by our team."
        )

    if issue_lines:
        lines.append("")
        lines.append("Details:")
        for il in issue_lines:
            lines.append(f"  • {il}")

    lines.extend([
        "",
        f"Reference: {case.case_id}",
        "",
        "Regards,",
        "INX Processing Team",
    ])
    return "\n".join(lines)


def _fallback_html(case: CaseRecord, issue_lines: list[str], route: str) -> str:
    """Minimal HTML fallback when templates are missing."""
    name = case.sender_name or case.sender_email
    if route == "PROCESS":
        message = (
            "Your submission has been received and verified successfully. "
            "It has been forwarded for processing."
        )
    elif route == "REQUEST_INFO":
        message = (
            "We have reviewed your submission and found that additional "
            "information is required."
        )
    else:
        message = "Your submission has been received and is under review by our team."

    issues_html = ""
    if issue_lines:
        items = "".join(f"<li>{il}</li>" for il in issue_lines)
        issues_html = f"<h3>Details</h3><ul>{items}</ul>"

    return f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
<p>Dear {name},</p>
<p>{message}</p>
{issues_html}
<p>Reference: <strong>{case.case_id}</strong></p>
<p>Regards,<br>INX Processing Team</p>
</body>
</html>"""


def _route_to_template(case: CaseRecord) -> str:
    """Map ``case.route`` to a Jinja2 template filename stem."""
    if case.route is None:
        return "notification"
    mapping = {
        "PROCESS": "notification",
        "REQUEST_INFO": "notification",
        "MANUAL_VERIFICATION": "notification",
        "HUMAN_REVIEW": "notification",
    }
    return mapping.get(case.route.value, "notification")
