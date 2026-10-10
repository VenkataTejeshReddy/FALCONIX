# Owner: Laptop B
"""INX – Excel report: append one row per case to a shared workbook.

Each call to :func:`append_excel_row` adds one row to
``data/reports/cases.xlsx``.  The workbook is created with headers on the
first run.  Uses ``openpyxl`` for writing.

Column layout (in order):

    case_id | scenario | sender_email | route | workflow_status |
    received_at | decided_at | rule_ids | issues_count |
    <one column per scenario field, value only> |
    error (if any)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.schemas import CaseRecord

_DEFAULT_REPORT_PATH = Path("data/reports/cases.xlsx")

# Base columns always present
_BASE_HEADERS: list[str] = [
    "case_id",
    "scenario",
    "sender_email",
    "sender_name",
    "route",
    "workflow_status",
    "received_at",
    "decided_at",
    "rule_ids",
    "issues_count",
    "error",
]


def _get_scenario_headers(scenario: str) -> list[str]:
    """Return the ordered list of field-name columns for *scenario*.

    Args:
        scenario: Scenario name.

    Returns:
        List of field names from the scenario config, in definition order.
    """
    raise NotImplementedError


def _ensure_workbook(path: Path, headers: list[str]) -> None:
    """Create the workbook and write headers if the file does not exist.

    Args:
        path: Target ``.xlsx`` path.
        headers: Column header strings.
    """
    raise NotImplementedError


def _case_to_row(case: CaseRecord, headers: list[str]) -> list:
    """Convert *case* to an ordered list of cell values matching *headers*.

    Args:
        case: The :class:`CaseRecord` to serialise.
        headers: Ordered column header list.

    Returns:
        List of values in header order.  Missing fields produce an empty
        string; lists are joined with ``"; "``.
    """
    raise NotImplementedError


def append_excel_row(
    case: CaseRecord,
    report_path: Optional[Path] = None,
) -> None:
    """Append one row to the Excel workbook for *case*.

    Creates the workbook and headers if the file does not exist yet.

    Args:
        case: The :class:`CaseRecord` to write.
        report_path: Override the default report path.
    """
    raise NotImplementedError
