# Owner: Laptop B
"""INX – Email drafter: generate notification emails for applicants.

Produces plain-text and HTML email bodies from Jinja2 templates stored in
``app/notify/templates/``.  The drafter never sends emails itself; that is
handled by :mod:`app.notify.sender`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.schemas import CaseRecord

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def draft_email(
    case: CaseRecord,
    template_name: Optional[str] = None,
) -> tuple[str, str, str]:
    """Render subject, plain-text body, and HTML body for a case notification.

    The template is chosen based on ``case.route`` if *template_name* is not
    provided::

        PROCESS              -> process.j2
        REQUEST_INFO         -> request_info.j2
        MANUAL_VERIFICATION  -> manual_verification.j2
        HUMAN_REVIEW         -> human_review.j2

    Args:
        case: The decided :class:`CaseRecord`.
        template_name: Override the auto-selected template stem.

    Returns:
        A 3-tuple of ``(subject, plain_body, html_body)``.

    Raises:
        ValueError: If ``case.decision`` is ``None``.
        FileNotFoundError: If the template file does not exist.
    """
    raise NotImplementedError


def _route_to_template(case: CaseRecord) -> str:
    """Map ``case.route`` to a Jinja2 template filename stem."""
    raise NotImplementedError
