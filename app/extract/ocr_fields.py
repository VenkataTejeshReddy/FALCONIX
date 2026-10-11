# Owner: Laptop A
"""INX – OCR field locator (Reader A value extraction).

Finds ocr_value for each target field from ParsedDocument using label synonyms
plus spatial geometry (value to the right of or below the label, using bboxes)
and type regexes.

Returns (value, bbox, page) or (None, None, None).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml

from app.schemas import BBox, ParsedDocument, ParsedLine

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "field_labels.yaml"
_FIELD_LABELS_CACHE: Optional[dict[str, Any]] = None


def load_field_labels(config_path: Optional[Path] = None) -> dict[str, Any]:
    """Load config/field_labels.yaml cached in-memory."""
    global _FIELD_LABELS_CACHE
    if _FIELD_LABELS_CACHE is not None and config_path is None:
        return _FIELD_LABELS_CACHE

    p = config_path or _CONFIG_PATH
    if not p.exists():
        return {}

    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    cfg = data.get("fields", {})
    if config_path is None:
        _FIELD_LABELS_CACHE = cfg
    return cfg


def _clean_val(text: str) -> str:
    """Trim leading/trailing punctuation and whitespace."""
    val = text.strip()
    val = re.sub(r"^[:\-\–\—\s]+", "", val)
    val = re.sub(r"[\s\:\-]+$", "", val)
    return val.strip()


def find_ocr_field(
    parsed: ParsedDocument,
    field_name: str,
    field_cfg: Optional[dict[str, Any]] = None,
) -> tuple[Optional[str], Optional[BBox], Optional[int]]:
    """Locate field value from ParsedDocument using labels, geometry, and regex.

    Args:
        parsed: The ParsedDocument produced by the parse layer.
        field_name: Target logical field name (e.g. 'applicant_name', 'email').
        field_cfg: Optional override of field configuration from field_labels.yaml.

    Returns:
        (value, bbox, page) on success, or (None, None, None) if not found.
    """
    if not parsed.lines:
        return None, None, None

    if field_cfg is None:
        all_cfg = load_field_labels()
        cfg = all_cfg.get(field_name, {})
    else:
        cfg = field_cfg

    synonyms: list[str] = cfg.get("synonyms", [])
    synonyms = [s.strip().lower() for s in synonyms if s.strip()]
    synonyms.append(field_name.replace("_", " ").lower())
    synonyms.append(field_name.lower())

    # Sort synonyms by length descending so more specific labels match first
    synonyms = sorted(set(synonyms), key=len, reverse=True)

    field_type = cfg.get("type", "text")
    type_regex = cfg.get("regex")

    # Group lines by page for geometry calculations
    lines_by_page: dict[int, list[ParsedLine]] = {}
    for line in parsed.lines:
        lines_by_page.setdefault(line.page, []).append(line)

    # -----------------------------------------------------------------------
    # Step 1: Search by Label Matching
    # -----------------------------------------------------------------------
    for page_idx, lines in lines_by_page.items():
        for i, line in enumerate(lines):
            line_txt_lower = line.text.lower().strip()

            # Check if this line starts with or contains any synonym
            matched_synonym = None
            for syn in synonyms:
                # Match label at start of line or after boundary
                pattern = r"(?:^|[\n\r]|[\b])" + re.escape(syn) + r"(?:[:\-\–\—\s]|$)"
                if re.search(pattern, line_txt_lower):
                    matched_synonym = syn
                    break

            if not matched_synonym:
                continue

            # Case A: Value is on the SAME line after label
            # e.g. "Applicant Name: Rohan Verma" or "email: test@example.com"
            pattern_inline = (
                r"(?i)(?:^|[\b])"
                + re.escape(matched_synonym)
                + r"[:\-\–\—\s]+(.+)$"
            )
            inline_match = re.search(pattern_inline, line.text.strip())
            if inline_match:
                candidate = _clean_val(inline_match.group(1))
                if candidate:
                    return candidate, line.bbox, page_idx

            # Case B: Value is on another line to the RIGHT of this label line
            # Check lines on same page with overlapping horizontal band and x > label.x
            label_box = line.bbox
            if label_box:
                label_y_mid = (label_box.y0 + label_box.y1) / 2.0
                label_height = max(10.0, label_box.height)

                right_candidates = []
                for other_line in lines:
                    if other_line is line or not other_line.bbox:
                        continue
                    ob = other_line.bbox
                    ob_y_mid = (ob.y0 + ob.y1) / 2.0
                    # Same horizontal band
                    if abs(label_y_mid - ob_y_mid) <= label_height * 0.9:
                        # Must be strictly to the right
                        if ob.x0 >= label_box.x0 + 10.0:
                            right_candidates.append(other_line)

                # Pick the closest candidate to the right
                if right_candidates:
                    right_candidates.sort(key=lambda l: l.bbox.x0 if l.bbox else 0.0)
                    chosen = right_candidates[0]
                    candidate = _clean_val(chosen.text)
                    if candidate:
                        return candidate, chosen.bbox, page_idx

                # Case C: Value is on line directly BELOW this label line
                below_candidates = []
                for other_line in lines:
                    if other_line is line or not other_line.bbox:
                        continue
                    ob = other_line.bbox
                    # Below the label within reasonable vertical distance (~2 lines)
                    if 0.0 <= (ob.y0 - label_box.y1) <= label_height * 2.2:
                        # Reasonable horizontal alignment
                        if ob.x0 <= label_box.x1 + 50.0 and ob.x1 >= label_box.x0 - 50.0:
                            below_candidates.append(other_line)

                if below_candidates:
                    below_candidates.sort(key=lambda l: l.bbox.y0 if l.bbox else 0.0)
                    chosen = below_candidates[0]
                    candidate = _clean_val(chosen.text)
                    if candidate:
                        return candidate, chosen.bbox, page_idx

    # -----------------------------------------------------------------------
    # Step 2: Fallback Type-Based Regex Scanning (Email, Phone, ID, Date)
    # -----------------------------------------------------------------------
    if type_regex and field_type in ("email", "phone", "id", "date"):
        compiled_re = re.compile(type_regex)
        for page_idx, lines in lines_by_page.items():
            for line in lines:
                m = compiled_re.search(line.text)
                if m:
                    candidate = _clean_val(m.group(0))
                    if candidate:
                        return candidate, line.bbox, page_idx

    return None, None, None
