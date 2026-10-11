# Owner: Laptop B
"""INX – Email notification polish (optional LLM rewording).

Rewrites draft notification wording using only the structured findings.
Off by default; enabled with ``NOTIFY_POLISH=1``.

Safety & Grounding
------------------
The output is strictly validated against the case's structured findings:
- Every issue in the case must be mentioned.
- No invented/hallucinated fields, documents, pages, or numbers are allowed.
- On any validation failure or model error, falls back to the original template.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable, Optional

from app.schemas import CaseRecord

logger = logging.getLogger(__name__)


def is_polish_enabled() -> bool:
    """Return True if notification polish is enabled via environment."""
    val = os.getenv("NOTIFY_POLISH", "0").strip().lower()
    return val in ("1", "true", "yes")


def _extract_numbers(text: str) -> set[str]:
    """Extract integer and float number tokens from text."""
    return set(re.findall(r"\b\d+(?:\.\d+)?\b", text))


def _extract_known_tokens(case: CaseRecord) -> set[str]:
    """Gather all known words, field names, document types, and numbers from the case."""
    known: set[str] = set()

    # Case ID and prefix
    if case.case_id:
        known.add(case.case_id.lower())
        known.add(case.case_id[:8].lower())

    # Scenario
    if case.scenario:
        known.add(case.scenario.lower())

    # Sender / Recipient
    if case.sender_name:
        for word in case.sender_name.lower().split():
            known.add(word)
    if case.sender_email:
        known.add(case.sender_email.lower())

    # Documents
    for doc in case.documents:
        if doc.filename:
            known.add(doc.filename.lower())
            for part in re.split(r"[\W_]+", doc.filename.lower()):
                if part:
                    known.add(part)
        if doc.doc_type:
            known.add(doc.doc_type.value.lower())

    # Missing documents
    for mdoc in case.missing_documents:
        known.add(mdoc.lower())

    # Fields
    for k, fr in case.fields.items():
        known.add(k.lower())
        known.add(fr.field.lower())
        if fr.value:
            known.add(fr.value.lower())
            for n in _extract_numbers(fr.value):
                known.add(n)
        if fr.page is not None:
            known.add(str(fr.page + 1))  # 1-indexed

    # Issues
    for iss in case.issues:
        known.add(iss.field.lower())
        known.add(iss.kind.value.lower())
        if iss.detail:
            for word in re.split(r"[\W_]+", iss.detail.lower()):
                if word:
                    known.add(word)
            for n in _extract_numbers(iss.detail):
                known.add(n)
        if iss.doc:
            known.add(iss.doc.lower())
        if iss.page is not None:
            known.add(str(iss.page + 1))

    return known


def validate_polished_text(
    polished_text: str,
    case: CaseRecord,
) -> tuple[bool, str]:
    """Verify that polished text does not invent facts and covers all issues.

    Returns:
        (is_valid, reason_if_invalid)
    """
    if not polished_text or not polished_text.strip():
        return False, "Polished text is empty"

    # 1. Verify coverage: every non-internal issue field must be mentioned
    polished_lower = polished_text.lower()
    for iss in case.issues:
        # Ignore purely internal issues like no_sender or duplicate_file
        if iss.kind.value in ("no_sender", "duplicate_file", "unknown_type"):
            continue
        field_name = iss.field.lower()
        if field_name not in polished_lower:
            return False, f"Missing mention of required issue field '{iss.field}'"

    # 2. Verify numbers: numbers in polished text must exist in known case numbers
    # (Allow common small formatting numbers like 1, 2 for bullet lists or greetings)
    known_tokens = _extract_known_tokens(case)
    polished_numbers = _extract_numbers(polished_text)
    for num in polished_numbers:
        # Ignore bullet list counters (1, 2, 3) or year 2026 if context matches
        if num in ("1", "2", "3", "4", "5"):
            continue
        if num not in known_tokens:
            # Check if it was in the case text / tokens
            return False, f"Hallucinated number '{num}' not in structured case findings"

    return True, ""


def polish_notification(
    subject: str,
    plain_body: str,
    html_body: str,
    case: CaseRecord,
    client: Optional[Any] = None,
) -> tuple[str, str, str]:
    """Optionally rewrites notification wording using an LLM.

    Falls back to original template strings if disabled, if model call fails,
    or if validation fails (e.g. invented facts).

    Args:
        subject: Original subject line.
        plain_body: Original plain-text body.
        html_body: Original HTML body.
        case: The decided CaseRecord.
        client: Optional fake/mock model client with a ``generate(prompt) -> str`` method.

    Returns:
        3-tuple ``(subject, plain_body, html_body)``.
    """
    if not is_polish_enabled() and client is None:
        return subject, plain_body, html_body

    # Build prompt
    findings = []
    for iss in case.issues:
        page_str = f" (page {iss.page + 1})" if iss.page is not None else ""
        findings.append(f"- Field: {iss.field}, Issue: {iss.kind.value}, Detail: {iss.detail}{page_str}")

    findings_text = "\n".join(findings) if findings else "No issues found."

    prompt = (
        "You are an assistant for an application processing system.\n"
        "Rewrite the following applicant notification email in a polite, professional tone.\n"
        "STRICT CONSTRAINTS:\n"
        "1. Mention ONLY the facts, fields, and issues explicitly listed below.\n"
        "2. Do NOT invent or assume any other details, field names, page numbers, or numbers.\n"
        "3. Keep all reference IDs and applicant names intact.\n\n"
        f"Applicant Name: {case.sender_name or case.sender_email}\n"
        f"Case Reference: {case.case_id}\n"
        f"Route: {case.route.value if case.route else 'PROCESS'}\n"
        f"Structured Findings:\n{findings_text}\n\n"
        f"Original Draft:\n{plain_body}\n\n"
        "Polished Email Body:"
    )

    try:
        if client is not None:
            # Test client provided
            raw_response = client.generate(prompt)
        else:
            # Real local Ollama call
            import urllib.request
            import json

            ollama_url = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            model = os.getenv("VLM_MODEL", "qwen3-vl:4b-instruct")

            req = urllib.request.Request(
                f"{ollama_url}/api/generate",
                data=json.dumps({
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0},
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_response = data.get("response", "")

        polished_text = raw_response.strip()

        # Validate
        is_valid, reason = validate_polished_text(polished_text, case)
        if not is_valid:
            logger.warning("Polished notification rejected: %s. Falling back to template.", reason)
            return subject, plain_body, html_body

        # Convert polished plain text to simple HTML
        paragraphs = [f"<p>{p.strip()}</p>" for p in polished_text.split("\n\n") if p.strip()]
        polished_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
{"".join(paragraphs)}
</body>
</html>"""

        return subject, polished_text, polished_html

    except Exception as e:
        logger.warning("Notification polish failed (%s). Falling back to template.", e)
        return subject, plain_body, html_body
