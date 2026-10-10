# Owner: Laptop B
"""INX – Top-level pipeline orchestrator.

Wires together all pipeline stages for a single :class:`~app.schemas.CaseRecord`.
Each stage is called in sequence; exceptions are caught and recorded on
``case.error`` without aborting the surrounding batch.

Usage (programmatic)::

    from app.pipeline import run_case
    from app.schemas import CaseRecord

    case = CaseRecord(scenario="job_application", sender_email="a@b.com")
    result = run_case(case)

Usage (batch)::

    from app.pipeline import run_batch
    results = run_batch(cases)
"""

from __future__ import annotations

import logging
import traceback
from typing import Optional

from app.schemas import CaseRecord, WorkflowStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage imports (lazy to avoid circular imports at module load time)
# ---------------------------------------------------------------------------


def _import_stages():
    """Return a dict of stage callables, imported lazily."""
    from app.classify.classifier import classify_documents
    from app.decide.engine import decide
    from app.extract.field_extractor import extract_fields
    from app.notify.sender import send_notifications
    from app.report.excel import append_excel_row
    from app.store.audit import write_audit
    from app.store.db import save_case
    from app.validate.checks import validate_case

    return {
        "classify": classify_documents,
        "extract": extract_fields,
        "validate": validate_case,
        "decide": decide,
        "store": save_case,
        "audit": write_audit,
        "report": append_excel_row,
        "notify": send_notifications,
    }


# ---------------------------------------------------------------------------
# Single-case runner
# ---------------------------------------------------------------------------


def run_case(
    case: CaseRecord,
    *,
    skip_notify: bool = False,
    skip_report: bool = False,
    reader_name: str = "mock",
) -> CaseRecord:
    """Execute the full pipeline for one case.

    The function mutates *case* in-place and also returns it.  Any unhandled
    exception in a stage is caught, logged, and stored in ``case.error``; the
    case is then routed to HUMAN_REVIEW automatically.

    Args:
        case: The :class:`CaseRecord` to process.  Must have at least
            ``scenario`` and ``sender_email`` set.
        skip_notify: If ``True``, the notify stage is bypassed (useful in
            tests and CLI dry-runs).
        skip_report: If ``True``, the Excel append stage is bypassed.
        reader_name: Name of the parse Reader to use
            (``"mock"`` | ``"docling"`` | ``"apple_ocr"`` | ``"vlm"``).

    Returns:
        The mutated :class:`CaseRecord`.
    """
    logger.info("Pipeline start – case_id=%s scenario=%s", case.case_id, case.scenario)
    case.workflow_status = WorkflowStatus.processing

    stages = _import_stages()

    _ordered_stages = [
        ("classify", stages["classify"]),
        ("extract", stages["extract"]),
        ("validate", stages["validate"]),
        ("decide", stages["decide"]),
        ("store", stages["store"]),
        ("audit", stages["audit"]),
    ]
    if not skip_report:
        _ordered_stages.append(("report", stages["report"]))
    if not skip_notify:
        _ordered_stages.append(("notify", stages["notify"]))

    for stage_name, stage_fn in _ordered_stages:
        try:
            logger.debug("Stage %s – case_id=%s", stage_name, case.case_id)
            stage_fn(case)
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            logger.error(
                "Stage %s failed for case_id=%s:\n%s", stage_name, case.case_id, tb
            )
            case.error = f"Stage '{stage_name}' raised an exception – see logs."
            from app.schemas import Route

            case.route = Route.HUMAN_REVIEW
            case.workflow_status = WorkflowStatus.review_required
            break

    logger.info(
        "Pipeline end – case_id=%s route=%s status=%s",
        case.case_id,
        case.route,
        case.workflow_status,
    )
    return case


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------


def run_batch(
    cases: list[CaseRecord],
    *,
    skip_notify: bool = False,
    skip_report: bool = False,
    reader_name: str = "mock",
) -> list[CaseRecord]:
    """Process a list of cases sequentially; one bad case never stops the rest.

    Args:
        cases: List of :class:`CaseRecord` objects produced by the intake layer.
        skip_notify: Forwarded to :func:`run_case`.
        skip_report: Forwarded to :func:`run_case`.
        reader_name: Forwarded to :func:`run_case`.

    Returns:
        The same list with all cases mutated in-place.
    """
    results: list[CaseRecord] = []
    for idx, case in enumerate(cases):
        logger.info("Batch %d/%d – case_id=%s", idx + 1, len(cases), case.case_id)
        try:
            run_case(
                case,
                skip_notify=skip_notify,
                skip_report=skip_report,
                reader_name=reader_name,
            )
        except Exception:  # noqa: BLE001 – absolute last resort
            tb = traceback.format_exc()
            logger.critical(
                "UNHANDLED exception in run_case for case_id=%s:\n%s",
                case.case_id,
                tb,
            )
            case.error = "Unhandled pipeline exception – see logs."
        results.append(case)

    ok = sum(1 for c in results if c.error is None)
    logger.info("Batch complete – %d/%d succeeded", ok, len(results))
    return results
