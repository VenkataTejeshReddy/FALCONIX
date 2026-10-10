# Owner: Laptop B
"""INX – Email sender: dispatch notification emails via SMTP.

Reads SMTP configuration from environment variables (set in ``.env``).
Only sends emails for routes that require applicant notification:
``REQUEST_INFO`` and ``HUMAN_REVIEW`` (and optionally ``PROCESS``).

No email is sent for ``MANUAL_VERIFICATION`` (internal routing).
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.schemas import CaseRecord, Route

logger = logging.getLogger(__name__)

# Routes that trigger an applicant email
_NOTIFY_ROUTES: frozenset[Route] = frozenset({
    Route.REQUEST_INFO,
    Route.HUMAN_REVIEW,
    Route.PROCESS,
})


def send_email(
    to_address: str,
    subject: str,
    plain_body: str,
    html_body: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_from: Optional[str] = None,
) -> bool:
    """Send a single email via SMTP.

    Args:
        to_address: Recipient email address.
        subject: Email subject line.
        plain_body: Plain-text fallback body.
        html_body: Optional HTML body part.
        smtp_host: SMTP server hostname (default: ``$SMTP_HOST``).
        smtp_port: SMTP port (default: ``$SMTP_PORT``).
        smtp_from: Sender address (default: ``$SMTP_FROM``).

    Returns:
        ``True`` if sent successfully, ``False`` on any SMTP error (logged).
    """
    raise NotImplementedError


def send_notifications(case: CaseRecord) -> None:
    """Draft and send applicant notification email for *case* if applicable.

    Skips sending if the case's route is not in ``_NOTIFY_ROUTES``.

    Args:
        case: Decided :class:`CaseRecord`.
    """
    raise NotImplementedError
