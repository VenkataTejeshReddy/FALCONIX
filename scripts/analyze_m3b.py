# Owner: Laptop A
"""Analysis of M3b summary data."""

import json
from pathlib import Path
from rapidfuzz import fuzz

repo_root = Path(__file__).resolve().parent.parent
summary_path = repo_root / "scripts" / "m3b_summary.json"
summary = json.loads(summary_path.read_text())

print("=" * 80)
print("1. HARD DOCUMENTS AUDIT")
print("=" * 80)
hard_docs = [
    "hard_tilted_resume.jpg",
    "hard_perspective_id.jpg",
    "hard_shadow_marksheet.jpg",
    "hard_grainy_id.jpg",
    "hard_scanned_yellow_resume.jpg",
]

for doc_name in hard_docs:
    d = summary.get(doc_name, {})
    img_path = repo_root / "fixtures" / "synthetic_docs" / "hard" / doc_name
    print(f"\nDocument: {doc_name}")
    print(f"Image Path: {img_path.resolve()}")
    print("Actually Visible OCR Lines:")
    for line in d.get("ocr_lines", []):
        print(f"  {line}")
    print("Ground Truth (from ground_truth.json):")
    for f, val in d.get("true_fields", {}).items():
        print(f"  {f}: {val}")
    print("Extractor Value & Status:")
    for f, ext in d.get("extracted", {}).items():
        print(f"  {f}: value={ext['value']!r}, status={ext['status']}, ocr={ext['ocr_value']!r}, vlm={ext['vlm_value']!r}")

print("\n" + "=" * 80)
print("2. FALSE-VALIDS AUDIT (Fields with status=='valid' but value != ground_truth)")
print("=" * 80)

# Check all false-valids
false_valids = []
for doc_name, d in summary.items():
    true_fields = d.get("true_fields", {})
    ext_fields = d.get("extracted", {})
    for f, true_val in true_fields.items():
        ext_info = ext_fields.get(f, {})
        status = ext_info.get("status", "missing")
        ext_val = ext_info.get("value")
        
        # Check match
        # strict equality after normalisation
        def norm(v):
            return " ".join(str(v).strip().lower().split()) if v is not None else ""
        
        is_match = (norm(ext_val) == norm(true_val))
        if f == "applicant_name" and fuzz.ratio(norm(ext_val), norm(true_val)) >= 90:
            is_match = True

        if status == "valid" and not is_match:
            false_valids.append({
                "doc": doc_name,
                "field": f,
                "gt_value": true_val,
                "ext_value": ext_val,
                "ocr_lines": d.get("ocr_lines", []),
                "defect": d.get("defect"),
                "is_hard": d.get("is_hard"),
            })

print(f"Total false-valids found: {len(false_valids)}")
for i, fv in enumerate(false_valids, 1):
    doc = fv["doc"]
    field = fv["field"]
    gt_val = fv["gt_value"]
    ext_val = fv["ext_value"]
    defect = fv["defect"]
    is_hard = fv["is_hard"]
    
    # Determine value as printed from OCR lines
    val_printed = "Unknown"
    for l in fv["ocr_lines"]:
        if ext_val and ext_val.lower() in l.lower():
            val_printed = ext_val
            break
    if val_printed == "Unknown" and ext_val:
        val_printed = ext_val

    # Categorize
    if is_hard:
        category = "ground-truth mismatch"
    elif defect == "typo":
        category = "typo printed as written"
    else:
        category = "real error"
    
    print(f"\n[{i}] Doc: {doc} | Field: {field}")
    print(f"    Ground-truth value: {gt_val!r}")
    print(f"    Value as printed:   {val_printed!r}")
    print(f"    Extractor value:    {ext_val!r}")
    print(f"    Status:             valid")
    print(f"    Category:           {category}")

print("\n" + "=" * 80)
print("5. NORMAL DOCS AUDIT (Check all 29 fields across the 7 normal documents)")
print("=" * 80)
normal_docs = [
    "job_normal_resume.pdf",
    "job_normal_id.jpg",
    "scan001.pdf",
    "IMG_2041.jpg",
    "college_normal_marksheet.pdf",
    "college_normal_id.jpg",
    "college_normal_reg_letter.pdf",
]
for doc_name in normal_docs:
    d = summary.get(doc_name, {})
    for f, true_val in d.get("true_fields", {}).items():
        ext = d.get("extracted", {}).get(f, {})
        status = ext.get("status")
        val = ext.get("value")
        if status != "valid":
            print(f"NON-VALID FIELD in normal docs: {doc_name} -> {f}")
            print(f"  True value: {true_val!r}")
            print(f"  Extracted:  {val!r}")
            print(f"  Status:     {status}")
            print(f"  Reason:     {ext.get('reason')}")
            print(f"  OCR lines:  {d.get('ocr_lines')}")

print("\n" + "=" * 80)
print("4. OBSCURED DOCS AUDIT (8 injected fields)")
print("=" * 80)
obscured_docs = [
    "job_unclear_stamp_id.jpg",
    "college_unclear_stamp_marksheet.jpg",
]
for doc_name in obscured_docs:
    d = summary.get(doc_name, {})
    print(f"\nDocument: {doc_name} (defect: {d.get('defect')}, altered: {d.get('altered_field')})")
    for f, true_val in d.get("true_fields", {}).items():
        ext = d.get("extracted", {}).get(f, {})
        print(f"  Field: {f}")
        print(f"    True value:     {true_val!r}")
        print(f"    OCR value:      {ext.get('ocr_value')!r}")
        print(f"    VLM value:      {ext.get('vlm_value')!r}")
        print(f"    Obscured flag:  {ext.get('obscured')}")
        print(f"    Evidence quote: {ext.get('quote')!r}")
        print(f"    Status:         {ext.get('status')}")
        print(f"    Reason:         {ext.get('reason')}")

