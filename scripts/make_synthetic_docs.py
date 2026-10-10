# Owner: Laptop B
"""INX – Script: generate synthetic fixture documents for testing.

Generates synthetic fake documents (PDF and JPG) for both scenarios
(job_application and college) exercising all edge cases:
- normal
- missing field
- name typo versus another document
- conflicting date or ID
- unclear (stamp over a value)
- blurry phone photo
- unknown document type (a restaurant menu)
- multi-page PDF where a value differs on page 2

Also produces `expected_outcomes.json` mapping document names to their expected
field statuses and routes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.validate.identifiers import generate_verhoeff

_DEFAULT_OUT = _REPO_ROOT / "fixtures" / "synthetic_docs"


def _get_font(size: int = 16) -> ImageFont.ImageFont:
    """Safely obtain a PIL font."""
    font_file = _REPO_ROOT / "DejaVuSans.ttf"
    if font_file.exists():
        try:
            return ImageFont.truetype(str(font_file), size)
        except OSError:
            pass
    for name in ["DejaVuSans.ttf", "arial.ttf", "calibri.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _make_valid_govt_id(base11: str = "23612345678") -> str:
    cd = generate_verhoeff(base11)
    return f"{base11}{cd}"


def _make_invalid_govt_id(base11: str = "23612345678") -> str:
    cd = generate_verhoeff(base11)
    bad_cd = (cd + 1) % 10
    return f"{base11}{bad_cd}"


# ---------------------------------------------------------------------------
# PDF generator helpers (ReportLab)
# ---------------------------------------------------------------------------


def generate_pdf_document(
    out_path: Path,
    title: str,
    fields: list[tuple[str, str]],
    notes: list[str] | None = None,
    second_page_fields: list[tuple[str, str]] | None = None,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=letter)
    width, height = letter

    # Page 1
    c.setFont("Helvetica-Bold", 20)
    c.drawString(60, height - 70, title)
    c.setLineWidth(1.5)
    c.line(60, height - 80, width - 60, height - 80)

    y = height - 120
    c.setFont("Helvetica-Bold", 12)
    for label, val in fields:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(70, y, f"{label}:")
        c.setFont("Helvetica", 12)
        c.drawString(220, y, str(val))
        y -= 28

    if notes:
        y -= 15
        c.setFont("Helvetica-Oblique", 10)
        c.setFillColor(colors.gray)
        for note in notes:
            c.drawString(70, y, note)
            y -= 18
        c.setFillColor(colors.black)

    if second_page_fields is not None:
        c.showPage()
        # Page 2
        c.setFont("Helvetica-Bold", 18)
        c.drawString(60, height - 70, f"{title} – Addendum / Page 2")
        c.setLineWidth(1.5)
        c.line(60, height - 80, width - 60, height - 80)

        y = height - 120
        for label, val in second_page_fields:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(70, y, f"{label}:")
            c.setFont("Helvetica", 12)
            c.drawString(220, y, str(val))
            y -= 28

    c.save()
    return out_path


# ---------------------------------------------------------------------------
# JPG generator helpers (PIL)
# ---------------------------------------------------------------------------


def generate_jpg_document(
    out_path: Path,
    title: str,
    fields: list[tuple[str, str]],
    notes: list[str] | None = None,
    stamp: str | None = None,
    blur: bool = False,
    size: tuple[int, int] = (1400, 1000),
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)

    f_title = _get_font(32)
    f_body = _get_font(22)
    f_bold = _get_font(24)

    # Header
    draw.text((80, 70), title, fill=(20, 20, 20), font=f_title)
    draw.line([(80, 120), (size[0] - 80, 120)], fill=(80, 80, 80), width=3)

    y = 160
    stamp_pos = None
    for label, val in fields:
        draw.text((100, y), f"{label}:", fill=(40, 40, 40), font=f_bold)
        draw.text((380, y), str(val), fill=(0, 0, 0), font=f_body)
        if "id" in label.lower() or "number" in label.lower():
            stamp_pos = (360, y - 10)
        y += 45

    if notes:
        y += 20
        for note in notes:
            draw.text((100, y), note, fill=(120, 120, 120), font=f_body)
            y += 35

    # Stamp overlay if requested
    if stamp and stamp_pos:
        # Draw a semi-obscuring stamp over the value
        sx, sy = stamp_pos
        draw.rectangle([sx, sy, sx + 220, sy + 60], outline=(180, 20, 20), width=4)
        draw.text((sx + 15, sy + 15), stamp, fill=(200, 30, 30), font=_get_font(22))
        # Draw some hatched lines to make value unclear
        for lx in range(sx, sx + 220, 15):
            draw.line([(lx, sy), (lx + 20, sy + 60)], fill=(200, 30, 30), width=2)

    if blur:
        # Simulate blurry camera shot
        img = img.filter(ImageFilter.GaussianBlur(radius=8))

    img.save(out_path, quality=85)
    return out_path


# ---------------------------------------------------------------------------
# Generator implementations
# ---------------------------------------------------------------------------


def generate_all_synthetic_docs(out_dir: Path) -> dict[str, Any]:
    """Generate fake documents for both scenarios across all edge cases.

    Returns the expected_outcomes dictionary.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    outcomes: dict[str, Any] = {}

    valid_id = _make_valid_govt_id("23612345678")
    invalid_id = _make_invalid_govt_id("23612345678")
    diff_id = _make_valid_govt_id("34891234567")

    # =========================================================================
    # 1. JOB APPLICATION SCENARIO
    # =========================================================================

    # 1.1 Normal Case
    f_res_norm_pdf = generate_pdf_document(
        out_dir / "job_normal_resume.pdf",
        "RÉSUMÉ – Rohan Verma",
        [
            ("Applicant Name", "Rohan Verma"),
            ("Email", "rohan.verma@example.com"),
            ("Phone", "+91 98765 43210"),
            ("Highest Qualification", "B.Tech Computer Science"),
            ("Institution", "Indian Institute of Technology"),
            ("Years Experience", "4"),
        ],
    )
    f_id_norm_jpg = generate_jpg_document(
        out_dir / "job_normal_id.jpg",
        "GOVERNMENT IDENTIFICATION CARD",
        [
            ("Applicant Name", "Rohan Verma"),
            ("ID Number", valid_id),
            ("Document Date", "2023-01-15"),
        ],
    )
    outcomes[f_res_norm_pdf.name] = {
        "scenario": "job_application",
        "case_type": "normal",
        "doc_type": "resume",
        "expected_statuses": {
            "applicant_name": "valid",
            "email": "valid",
            "highest_qualification": "valid",
            "institution": "valid",
            "years_experience": "valid",
        },
        "expected_route": "fast_track",
    }
    outcomes[f_id_norm_jpg.name] = {
        "scenario": "job_application",
        "case_type": "normal",
        "doc_type": "id_document",
        "expected_statuses": {
            "applicant_name": "valid",
            "id_number": "valid",
            "document_date": "valid",
        },
        "expected_route": "fast_track",
    }

    # 1.2 Missing Field (email and years_experience missing from resume)
    f_res_missing_pdf = generate_pdf_document(
        out_dir / "job_missing_field_resume.pdf",
        "RÉSUMÉ – Rohan Verma",
        [
            ("Applicant Name", "Rohan Verma"),
            ("Phone", "+91 98765 43210"),
            ("Highest Qualification", "B.Tech Computer Science"),
            ("Institution", "Indian Institute of Technology"),
        ],
    )
    outcomes[f_res_missing_pdf.name] = {
        "scenario": "job_application",
        "case_type": "missing_field",
        "doc_type": "resume",
        "expected_statuses": {
            "applicant_name": "valid",
            "email": "missing",
            "years_experience": "missing",
        },
        "expected_route": "needs_review",
    }

    # 1.3 Name Typo versus ID (Resume has 'Rohan Verma', ID has 'Rohhan Verma')
    f_id_typo_jpg = generate_jpg_document(
        out_dir / "job_name_typo_id.jpg",
        "GOVERNMENT IDENTIFICATION CARD",
        [
            ("Applicant Name", "Rohhan Verma"),
            ("ID Number", valid_id),
            ("Document Date", "2023-01-15"),
        ],
    )
    outcomes[f_id_typo_jpg.name] = {
        "scenario": "job_application",
        "case_type": "name_typo",
        "doc_type": "id_document",
        "expected_statuses": {
            "applicant_name": "conflict",
            "id_number": "valid",
        },
        "expected_route": "needs_review",
    }

    # 1.4 Conflicting ID (checksum invalid)
    f_id_conflict_pdf = generate_pdf_document(
        out_dir / "job_conflicting_id.pdf",
        "GOVERNMENT IDENTIFICATION CARD",
        [
            ("Applicant Name", "Rohan Verma"),
            ("ID Number", invalid_id),
            ("Document Date", "2023-01-15"),
        ],
    )
    outcomes[f_id_conflict_pdf.name] = {
        "scenario": "job_application",
        "case_type": "conflicting_id",
        "doc_type": "id_document",
        "expected_statuses": {
            "applicant_name": "valid",
            "id_number": "conflict",
        },
        "expected_route": "needs_review",
    }

    # 1.5 Unclear Stamp Over Value
    f_id_unclear_jpg = generate_jpg_document(
        out_dir / "job_unclear_stamp_id.jpg",
        "GOVERNMENT IDENTIFICATION CARD",
        [
            ("Applicant Name", "Rohan Verma"),
            ("ID Number", valid_id),
            ("Document Date", "2023-01-15"),
        ],
        stamp="VOID / COPY",
    )
    outcomes[f_id_unclear_jpg.name] = {
        "scenario": "job_application",
        "case_type": "unclear_stamp",
        "doc_type": "id_document",
        "expected_statuses": {
            "id_number": "unclear",
        },
        "expected_route": "needs_review",
    }

    # 1.6 Blurry Phone Photo
    f_res_blurry_jpg = generate_jpg_document(
        out_dir / "job_blurry_photo_resume.jpg",
        "RÉSUMÉ – Rohan Verma",
        [
            ("Applicant Name", "Rohan Verma"),
            ("Email", "rohan.verma@example.com"),
            ("Highest Qualification", "B.Tech Computer Science"),
        ],
        blur=True,
    )
    outcomes[f_res_blurry_jpg.name] = {
        "scenario": "job_application",
        "case_type": "blurry_photo",
        "doc_type": "resume",
        "expected_quality": "poor",
        "expected_route": "needs_review",
    }

    # 1.7 Unknown Document Type (Restaurant Dinner Menu)
    f_unknown_menu_pdf = generate_pdf_document(
        out_dir / "job_unknown_menu.pdf",
        "THE GOLDEN SPOON – DINNER MENU",
        [
            ("Appetizer", "Bruschetta al Pomodoro – $8.00"),
            ("First Course", "Truffle Tagliatelle – $18.50"),
            ("Main Course", "Pan-Seared Sea Bass – $26.00"),
            ("Dessert", "Classic Tiramisu – $7.50"),
            ("Beverage", "Sparkling Water 750ml – $4.00"),
        ],
    )
    outcomes[f_unknown_menu_pdf.name] = {
        "scenario": "job_application",
        "case_type": "unknown_document",
        "doc_type": "unknown",
        "expected_statuses": {},
        "expected_route": "manual_review",
    }

    # 1.8 Multi-page PDF where value differs on Page 2
    f_multipage_pdf = generate_pdf_document(
        out_dir / "job_multipage_differing_value.pdf",
        "APPLICANT DECLARATION & SUMMARY",
        [
            ("Applicant Name", "Rohan Verma"),
            ("ID Number", valid_id),
            ("Document Date", "2023-01-15"),
        ],
        second_page_fields=[
            ("Applicant Name", "Rohan Verma"),
            ("ID Number", diff_id),  # Differs from page 1!
            ("Document Date", "2021-11-20"),
        ],
    )
    outcomes[f_multipage_pdf.name] = {
        "scenario": "job_application",
        "case_type": "multipage_differing_value",
        "doc_type": "id_document",
        "expected_statuses": {
            "id_number": "conflict",
        },
        "expected_route": "needs_review",
    }

    # =========================================================================
    # 2. COLLEGE SCENARIO
    # =========================================================================

    # 2.1 Normal Case
    col_marks_norm_pdf = generate_pdf_document(
        out_dir / "college_normal_marksheet.pdf",
        "STATEMENT OF MARKS – SEMESTER VIII",
        [
            ("Applicant Name", "Ananya Iyer"),
            ("Course", "Computer Engineering"),
            ("Institution", "National Institute of Technology"),
            ("Marks or Grade", "8.8 CGPA"),
            ("Issue Date", "2023-06-20"),
        ],
    )
    col_id_norm_jpg = generate_jpg_document(
        out_dir / "college_normal_id.jpg",
        "STUDENT IDENTIFICATION CARD",
        [
            ("Applicant Name", "Ananya Iyer"),
            ("Date of Birth", "2001-04-12"),
            ("ID Number", valid_id),
        ],
    )
    outcomes[col_marks_norm_pdf.name] = {
        "scenario": "college",
        "case_type": "normal",
        "doc_type": "marksheet",
        "expected_statuses": {
            "applicant_name": "valid",
            "marks_or_grade": "valid",
            "institution": "valid",
            "course": "valid",
            "issue_date": "valid",
        },
        "expected_route": "fast_track",
    }
    outcomes[col_id_norm_jpg.name] = {
        "scenario": "college",
        "case_type": "normal",
        "doc_type": "id_document",
        "expected_statuses": {
            "applicant_name": "valid",
            "date_of_birth": "valid",
            "id_number": "valid",
        },
        "expected_route": "fast_track",
    }

    # 2.2 Missing Field (Marksheet missing issue_date)
    col_marks_missing_pdf = generate_pdf_document(
        out_dir / "college_missing_date_marksheet.pdf",
        "STATEMENT OF MARKS – SEMESTER VIII",
        [
            ("Applicant Name", "Ananya Iyer"),
            ("Course", "Computer Engineering"),
            ("Institution", "National Institute of Technology"),
            ("Marks or Grade", "8.8 CGPA"),
        ],
    )
    outcomes[col_marks_missing_pdf.name] = {
        "scenario": "college",
        "case_type": "missing_field",
        "doc_type": "marksheet",
        "expected_statuses": {
            "applicant_name": "valid",
            "issue_date": "missing",
        },
        "expected_route": "needs_review",
    }

    # 2.3 Name Typo versus ID (Marksheet has 'Ananya Iyer', ID has 'Ananya Iyyar')
    col_id_typo_jpg = generate_jpg_document(
        out_dir / "college_name_typo_id.jpg",
        "STUDENT IDENTIFICATION CARD",
        [
            ("Applicant Name", "Ananya Iyyar"),
            ("Date of Birth", "2001-04-12"),
            ("ID Number", valid_id),
        ],
    )
    outcomes[col_id_typo_jpg.name] = {
        "scenario": "college",
        "case_type": "name_typo",
        "doc_type": "id_document",
        "expected_statuses": {
            "applicant_name": "conflict",
            "id_number": "valid",
        },
        "expected_route": "needs_review",
    }

    # 2.4 Conflicting Date / Impossible DOB (DOB in future: 2045-01-01)
    col_id_bad_dob_pdf = generate_pdf_document(
        out_dir / "college_future_dob_id.pdf",
        "STUDENT IDENTIFICATION CARD",
        [
            ("Applicant Name", "Ananya Iyer"),
            ("Date of Birth", "2045-01-01"),
            ("ID Number", valid_id),
        ],
    )
    outcomes[col_id_bad_dob_pdf.name] = {
        "scenario": "college",
        "case_type": "conflicting_date",
        "doc_type": "id_document",
        "expected_statuses": {
            "date_of_birth": "conflict",
        },
        "expected_route": "needs_review",
    }

    # Write expected_outcomes.json
    outcomes_path = out_dir / "expected_outcomes.json"
    with open(outcomes_path, "w", encoding="utf-8") as f:
        json.dump(outcomes, f, indent=2)

    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic fake documents.")
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help="Output directory for generated documents and expected_outcomes.json",
    )
    args = parser.parse_args()

    print(f"Generating synthetic documents in {args.out}...")
    outcomes = generate_all_synthetic_docs(args.out)
    print(f"Done. Generated {len(outcomes)} document fixtures and expected_outcomes.json.")


if __name__ == "__main__":
    main()
