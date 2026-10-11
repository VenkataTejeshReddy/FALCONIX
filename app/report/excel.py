# Owner: Laptop B
"""INX – Excel report: multi-sheet workbook updated after every case.

Written atomically (temp file → rename) after EVERY case to
``data/reports/<run_id>.xlsx`` and copied to ``data/reports/latest.xlsx``.

Sheets
------
- **Applicants**: case overview with route-based row colouring.
- **Fields**: per-document field extraction results.
- **Issues**: every issue flagged on each case.
- **Run**: aggregate statistics (counts by route, duplicates, timing).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.schemas import CaseRecord, Route

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Route → colour mapping
# ---------------------------------------------------------------------------

_ROUTE_FILLS: dict[str, PatternFill] = {
    "PROCESS": PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),
    "REQUEST_INFO": PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid"),
    "MANUAL_VERIFICATION": PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid"),
    "HUMAN_REVIEW": PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),
}

_HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)

# ---------------------------------------------------------------------------
# Sheet column definitions
# ---------------------------------------------------------------------------

_APPLICANTS_HEADERS = [
    "Case ID",
    "Applicant Name",
    "Name Flag",
    "Email",
    "Scenario",
    "Documents Received",
    "Workflow Status",
    "Route",
    "Issue Summary",
    "Email Status",
    "Updated At",
]

_FIELDS_HEADERS = [
    "Case ID",
    "Document",
    "Field",
    "Value",
    "OCR Value",
    "VLM Value",
    "Status",
    "Reason",
    "Page",
]

_ISSUES_HEADERS = [
    "Case ID",
    "Kind",
    "Field",
    "Detail",
    "Document",
    "Page",
]

_RUN_HEADERS = [
    "Metric",
    "Value",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _style_header_row(ws, headers: list[str]) -> None:
    """Apply bold white-on-blue styling to the first row."""
    for col_idx, hdr in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=hdr)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", wrap_text=True)


def _auto_width(ws, min_width: int = 10, max_width: int = 40) -> None:
    """Set column widths based on content length."""
    for col in ws.iter_cols(min_row=1, max_row=ws.max_row):
        col_letter = get_column_letter(col[0].column)
        max_len = max(
            (len(str(cell.value or "")) for cell in col),
            default=min_width,
        )
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, min_width), max_width)


def _applicant_name(case: CaseRecord) -> str:
    """Extract the best available applicant name from fields, falling back to sender_name."""
    for key, fr in case.fields.items():
        if "name" in key.lower() and "applicant" in key.lower() and fr.value:
            return fr.value
        if key.endswith(".applicant_name") and fr.value:
            return fr.value
    # Fallback: check any name field
    for key, fr in case.fields.items():
        if key.endswith(".name") and fr.value:
            return fr.value
    return case.sender_name or case.sender_email


def _name_flag(case: CaseRecord) -> str:
    """Return 'MISMATCH' if extracted name differs from email display name."""
    extracted = _applicant_name(case)
    display = case.sender_name
    if not extracted or not display:
        return ""
    if extracted.strip().lower() == display.strip().lower():
        return ""
    return "MISMATCH"


def _docs_received(case: CaseRecord) -> str:
    """Comma-separated list of document types received."""
    types = []
    for doc in case.documents:
        t = doc.doc_type.value if doc.doc_type else "unknown"
        types.append(f"{t} ({doc.filename})")
    return "; ".join(types) if types else "(none)"


def _issue_summary(case: CaseRecord) -> str:
    """One-line summary of all issue kinds."""
    if not case.issues:
        return ""
    kinds = {}
    for iss in case.issues:
        k = iss.kind.value
        kinds[k] = kinds.get(k, 0) + 1
    return "; ".join(f"{k}×{v}" for k, v in kinds.items())


def _applicant_row(case: CaseRecord, email_status: str = "none") -> list[Any]:
    """Build one row for the Applicants sheet."""
    route_val = case.route.value if case.route else ""
    return [
        case.case_id,
        _applicant_name(case),
        _name_flag(case),
        case.sender_email,
        case.scenario,
        _docs_received(case),
        case.workflow_status.value,
        route_val,
        _issue_summary(case),
        email_status,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    ]


def _field_rows(case: CaseRecord) -> list[list[Any]]:
    """Build rows for the Fields sheet from case.fields."""
    rows = []
    for key, fr in case.fields.items():
        parts = key.split(".", 1)
        doc_type = parts[0] if len(parts) == 2 else ""
        rows.append([
            case.case_id,
            doc_type,
            fr.field,
            fr.value or "",
            fr.ocr_value or "",
            fr.vlm_value or "",
            fr.status.value,
            fr.reason or "",
            (fr.page + 1) if fr.page is not None else "",
        ])
    return rows


def _issue_rows(case: CaseRecord) -> list[list[Any]]:
    """Build rows for the Issues sheet."""
    rows = []
    for iss in case.issues:
        rows.append([
            case.case_id,
            iss.kind.value,
            iss.field,
            iss.detail,
            iss.doc or "",
            (iss.page + 1) if iss.page is not None else "",
        ])
    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ExcelReport:
    """Manages the multi-sheet Excel report for one pipeline run.

    Usage::

        report = ExcelReport(run_id="abc-123", data_dir=Path("data"))
        report.append_case(case, email_status="dry_run")
        report.finalise(elapsed_s=42.0, skipped_dups=2, dup_files=3)
    """

    def __init__(
        self,
        run_id: str,
        data_dir: Optional[Path] = None,
    ) -> None:
        self._run_id = run_id
        self._data_dir = data_dir or Path(os.getenv("INX_DATA_DIR", "data"))
        self._report_dir = self._data_dir / "reports"
        self._report_dir.mkdir(parents=True, exist_ok=True)
        self._report_path = self._report_dir / f"{run_id}.xlsx"
        self._latest_path = self._report_dir / "latest.xlsx"
        self._case_count = 0
        self._route_counts: dict[str, int] = {}
        self._total_seconds = 0.0
        self._wb: Optional[Workbook] = None

    def _get_or_create_workbook(self) -> Workbook:
        """Load existing workbook or create a new one with headers."""
        if self._wb is not None:
            return self._wb

        if self._report_path.exists():
            self._wb = load_workbook(str(self._report_path))
        else:
            self._wb = Workbook()
            # Create and style all sheets
            ws_app = self._wb.active
            ws_app.title = "Applicants"
            _style_header_row(ws_app, _APPLICANTS_HEADERS)

            ws_fields = self._wb.create_sheet("Fields")
            _style_header_row(ws_fields, _FIELDS_HEADERS)

            ws_issues = self._wb.create_sheet("Issues")
            _style_header_row(ws_issues, _ISSUES_HEADERS)

            ws_run = self._wb.create_sheet("Run")
            _style_header_row(ws_run, _RUN_HEADERS)

        return self._wb

    def append_case(
        self,
        case: CaseRecord,
        email_status: str = "none",
        elapsed_s: float = 0.0,
    ) -> None:
        """Append one case to the report and write atomically.

        Args:
            case: The decided CaseRecord.
            email_status: One of none|dry_run|held|sent|failed.
            elapsed_s: Time spent processing this case.
        """
        wb = self._get_or_create_workbook()
        self._case_count += 1
        self._total_seconds += elapsed_s

        route_val = case.route.value if case.route else "UNKNOWN"
        self._route_counts[route_val] = self._route_counts.get(route_val, 0) + 1

        # Applicants sheet
        ws_app = wb["Applicants"]
        row_data = _applicant_row(case, email_status)
        ws_app.append(row_data)

        # Apply route colour to the entire row
        fill = _ROUTE_FILLS.get(route_val)
        if fill:
            row_num = ws_app.max_row
            for col_idx in range(1, len(_APPLICANTS_HEADERS) + 1):
                ws_app.cell(row=row_num, column=col_idx).fill = fill

        # Fields sheet
        ws_fields = wb["Fields"]
        for row in _field_rows(case):
            ws_fields.append(row)

        # Issues sheet
        ws_issues = wb["Issues"]
        for row in _issue_rows(case):
            ws_issues.append(row)

        # Write atomically
        self._write_atomic(wb)

    def finalise(
        self,
        elapsed_s: float = 0.0,
        skipped_dups: int = 0,
        dup_files: int = 0,
    ) -> Path:
        """Write the Run sheet with aggregate stats and return the report path.

        Args:
            elapsed_s: Total batch elapsed time in seconds.
            skipped_dups: Number of duplicate Message-IDs skipped.
            dup_files: Number of duplicate file issues raised.

        Returns:
            Path to the finalised report.
        """
        wb = self._get_or_create_workbook()
        ws_run = wb["Run"]

        # Clear existing data rows (keep header)
        while ws_run.max_row > 1:
            ws_run.delete_rows(2)

        total_elapsed = elapsed_s or self._total_seconds
        avg_seconds = (total_elapsed / self._case_count) if self._case_count > 0 else 0.0

        stats = [
            ("Total Cases", self._case_count),
            ("Duplicate Emails Skipped", skipped_dups),
            ("Duplicate Files", dup_files),
            ("Total Seconds", round(total_elapsed, 2)),
            ("Average Seconds per Case", round(avg_seconds, 2)),
            ("", ""),
            ("--- Route Counts ---", ""),
        ]
        for route_name in ["PROCESS", "REQUEST_INFO", "MANUAL_VERIFICATION", "HUMAN_REVIEW"]:
            stats.append((route_name, self._route_counts.get(route_name, 0)))

        for label, value in stats:
            ws_run.append([label, value])

        # Auto-width all sheets
        for ws in wb.worksheets:
            _auto_width(ws)

        self._write_atomic(wb)
        return self._report_path

    def _write_atomic(self, wb: Workbook) -> None:
        """Write workbook to a temp file then rename for atomicity."""
        try:
            fd, tmp_path = tempfile.mkstemp(
                suffix=".xlsx",
                dir=str(self._report_dir),
            )
            os.close(fd)
            wb.save(tmp_path)

            # Atomic rename (Windows: need to remove destination first)
            if self._report_path.exists():
                self._report_path.unlink()
            os.rename(tmp_path, str(self._report_path))

            # Copy to latest.xlsx
            shutil.copy2(str(self._report_path), str(self._latest_path))

        except Exception:
            logger.exception("Failed to write Excel report atomically")
            # Try direct write as fallback
            try:
                wb.save(str(self._report_path))
                shutil.copy2(str(self._report_path), str(self._latest_path))
            except Exception:
                logger.exception("Fallback direct write also failed")


# ---------------------------------------------------------------------------
# Convenience function (backward compat)
# ---------------------------------------------------------------------------


def append_excel_row(
    case: CaseRecord,
    report_path: Optional[Path] = None,
) -> None:
    """Append one row to a single-sheet workbook for backward compatibility."""
    path = report_path or Path("data/reports/cases.xlsx")
    report = ExcelReport(run_id="legacy", data_dir=path.parent.parent)
    report._report_path = path
    report._latest_path = path.parent / "latest.xlsx"
    report.append_case(case)
