# Owner: Laptop B
"""INX – Email sender: dispatch notification emails via SMTP.

Reads SMTP configuration from environment variables (set in ``.env``).
With ``DRY_RUN=true`` (default) nothing is sent; the draft is stored in the outbox as dry_run.
With ``DRY_RUN=false`` it refuses any recipient not in ``ALLOWED_RECIPIENTS``.

No secrets are logged or committed to Git.
"""

from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Optional

from app.schemas import CaseRecord, Route
from app.store.db import get_outbox, record_outbox, update_outbox_status

logger = logging.getLogger(__name__)

# Routes that trigger an applicant email
_NOTIFY_ROUTES: frozenset[Route] = frozenset({
    Route.REQUEST_INFO,
    Route.HUMAN_REVIEW,
    Route.PROCESS,
})


def is_dry_run() -> bool:
    """Return True if DRY_RUN is enabled (default: true)."""
    val = os.getenv("DRY_RUN", "true").strip().lower()
    return val in ("true", "1", "yes", "")


def allowed_recipients() -> set[str]:
    """Parse ALLOWED_RECIPIENTS comma-separated list from env."""
    raw = os.getenv("ALLOWED_RECIPIENTS", "").strip()
    if not raw:
        return set()
    return {addr.strip().lower() for addr in raw.split(",") if addr.strip()}


def smtp_config() -> dict[str, Any]:
    """Read SMTP configuration from environment variables."""
    return {
        "host": os.getenv("SMTP_HOST", "localhost"),
        "port": int(os.getenv("SMTP_PORT", "1025")),
        "user": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from_addr": os.getenv("SMTP_FROM", "inx@local"),
    }


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

    Raises:
        ValueError: If recipient is not in ALLOWED_RECIPIENTS when DRY_RUN=false.
    """
    # DRY_RUN check
    if is_dry_run():
        logger.info(
            "[DRY_RUN] Would send email to=%s subject=%r (body length=%d)",
            to_address, subject, len(plain_body),
        )
        return False  # Not actually sent

    # Allowlist check (only in live mode)
    allowed = allowed_recipients()
    if allowed and to_address.strip().lower() not in allowed:
        raise ValueError(
            f"Recipient '{to_address}' is not in ALLOWED_RECIPIENTS. "
            f"Allowed: {sorted(allowed)}"
        )

    # Build MIME message
    cfg = smtp_config()
    host = smtp_host or cfg["host"]
    port = smtp_port or cfg["port"]
    from_addr = smtp_from or cfg["from_addr"]

    msg = MIMEMultipart("alternative")
    msg["From"] = from_addr
    msg["To"] = to_address
    msg["Subject"] = subject

    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            user = cfg["user"]
            password = cfg["password"]
            if user and password:
                server.starttls()
                server.login(user, password)
            server.sendmail(from_addr, [to_address], msg.as_string())
        logger.info("Email sent to=%s subject=%r", to_address, subject)
        return True
    except Exception:
        logger.exception("SMTP send failed to=%s", to_address)
        return False


def get_recipient(case: CaseRecord) -> str:
    """Determine recipient address: Reply-To if available, else From.

    Never returns ``manual@upload.local``.
    """
    addr = case.sender_email
    if not addr or addr.strip().lower() == "manual@upload.local":
        return ""
    return addr.strip()


def send_notifications(
    case: CaseRecord,
    db_path: Optional[Path] = None,
    polish_client: Optional[Any] = None,
) -> str:
    """Draft and process notification email for *case*.

    Stores draft in outbox table and dispatches if auto-send and not DRY_RUN.

    Args:
        case: Decided :class:`CaseRecord`.
        db_path: Optional database path for outbox storage.
        polish_client: Optional model client for notification rewording.

    Returns:
        One of ``"none" | "dry_run" | "held" | "sent" | "failed"``.
    """
    if case.route is None or case.route not in _NOTIFY_ROUTES:
        return "none"

    recipient = get_recipient(case)
    if not recipient:
        return "none"

    from app.notify.drafter import classify_email_action, draft_email

    action = classify_email_action(case)
    if action == "none":
        return "none"

    subject, plain_body, html_body = draft_email(case, polish_client=polish_client)

    if action == "held":
        # Record held email in outbox
        record_outbox(
            case_id=case.case_id,
            kind="held",
            recipient=recipient,
            subject=subject,
            body_text=plain_body,
            body_html=html_body,
            status="held",
            db_path=db_path,
        )
        return "held"

    # Action is "auto"
    if is_dry_run():
        record_outbox(
            case_id=case.case_id,
            kind="auto",
            recipient=recipient,
            subject=subject,
            body_text=plain_body,
            body_html=html_body,
            status="dry_run",
            db_path=db_path,
        )
        return "dry_run"

    # Live dispatch
    outbox_id = record_outbox(
        case_id=case.case_id,
        kind="auto",
        recipient=recipient,
        subject=subject,
        body_text=plain_body,
        body_html=html_body,
        status="draft",
        db_path=db_path,
    )

    try:
        ok = send_email(recipient, subject, plain_body, html_body)
        if ok:
            now = datetime.now(timezone.utc).isoformat()
            update_outbox_status(outbox_id, status="sent", sent_at=now, db_path=db_path)
            return "sent"
        else:
            update_outbox_status(
                outbox_id,
                status="failed",
                error="SMTP send failed",
                increment_retries=True,
                db_path=db_path,
            )
            return "failed"
    except Exception as e:
        update_outbox_status(
            outbox_id,
            status="failed",
            error=str(e),
            increment_retries=True,
            db_path=db_path,
        )
        return "failed"


def dispatch_outbox_item(
    outbox_id: int,
    db_path: Optional[Path] = None,
) -> bool:
    """Send an approved or pending item from the outbox table.

    Args:
        outbox_id: Primary key in outbox table.
        db_path: Optional SQLite db path.

    Returns:
        True if sent successfully, False otherwise.
    """
    item = get_outbox(outbox_id, db_path=db_path)
    if not item:
        return False

    recipient = item["recipient"]
    subject = item["subject"]
    plain_body = item["body_text"]
    html_body = item.get("body_html")

    try:
        if is_dry_run():
            logger.info("[DRY_RUN] Dispatched outbox item #%d to %s (simulated)", outbox_id, recipient)
            now = datetime.now(timezone.utc).isoformat()
            update_outbox_status(outbox_id, status="dry_run", sent_at=now, db_path=db_path)
            return True

        allowed = allowed_recipients()
        if allowed and recipient.strip().lower() not in allowed:
            err_msg = f"Recipient '{recipient}' is not in ALLOWED_RECIPIENTS"
            logger.warning("[ALLOWLIST_BLOCKED] Outbox #%d to %s refused: %s", outbox_id, recipient, err_msg)
            update_outbox_status(
                outbox_id,
                status="failed",
                error=err_msg,
                increment_retries=True,
                db_path=db_path,
            )
            return False

        ok = send_email(recipient, subject, plain_body, html_body)
        if ok:
            now = datetime.now(timezone.utc).isoformat()
            update_outbox_status(outbox_id, status="sent", sent_at=now, db_path=db_path)
            return True
        else:
            update_outbox_status(
                outbox_id,
                status="failed",
                error="SMTP send failed",
                increment_retries=True,
                db_path=db_path,
            )
            return False
    except Exception as e:
        update_outbox_status(
            outbox_id,
            status="failed",
            error=str(e),
            increment_retries=True,
            db_path=db_path,
        )
        return False
