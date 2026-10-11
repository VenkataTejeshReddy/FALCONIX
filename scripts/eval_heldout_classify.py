# Owner: Laptop A
"""Held-out Layer 2/3 Classifier Evaluation Script (M4b).

Evaluates 10 held-out paraphrased/heading-free document variants where Layer 1
keywords are removed or disguised, testing Layer 2 (BGE-M3 dense embeddings)
and Layer 3 (Qwen3-VL VLM).

Filenames are strictly hidden from the classifier.
Reports per-document: layer used, predicted type, confidence, seconds, peak memory.
"""

from __future__ import annotations

import os
import resource
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.classify.classifier import DocumentClassifier
from app.schemas import DocumentRecord, DocumentType, ParsedDocument, ParsedLine

_HELDOUT_VARIANTS: list[dict] = [
    # 1. Resume (paraphrased achievements, no traditional keywords)
    {
        "id": "variant_1_resume",
        "expected": DocumentType.resume,
        "description": "Resume: Paraphrased career achievements without CV/resume headers",
        "text": (
            "Senior Technical Lead & Systems Architect\n"
            "Over the past six years I designed high-throughput distributed microservices in Go and Python, "
            "architected real-time streaming engines, and graduated with honors in computation.\n"
            "Key Accomplishments: Built event-driven ingestion handling 100k req/sec, cut latency by 45%, "
            "and managed an infrastructure cluster across AWS and GCP.\n"
            "Contact: ananya.iyer@example.org | Phone: +91 98765 12345\n"
            "Academic Background: Bachelor of Engineering in Computing (First Class Honours, 2018)"
        ),
    },
    # 2. Resume (pure narrative, no section headers)
    {
        "id": "variant_2_resume",
        "expected": DocumentType.resume,
        "description": "Resume: Pure career narrative & technical competencies without headers",
        "text": (
            "Vikramaditya Rao — Platform Engineer\n"
            "Tenacious builder with deep expertise in fault-tolerant backend architectures. "
            "Spearheaded database partitioning, implemented zero-downtime deployment pipelines, "
            "and reduced compute costs across multi-region VPC environments.\n"
            "Core Tooling: Rust, Docker, Kubernetes, Apache Kafka, PostgreSQL.\n"
            "Reach: vikram.rao@techcorp.io | +91 91234 56789\n"
            "Alumnus of State University, Graduated 2016"
        ),
    },
    # 3. ID Document (paraphrased citizen credential)
    {
        "id": "variant_3_id",
        "expected": DocumentType.id_document,
        "description": "ID: Paraphrased citizen identity document without standard title",
        "text": (
            "Official State Republic Citizen Document\n"
            "Bearer Name: Ananya Iyer\n"
            "Permanent Registry Code: 849201948201\n"
            "Birth Date: 1994-09-12\n"
            "Jurisdiction: Republic Ministry of Personal Records\n"
            "Verification Office: Federal Civil Records Division"
        ),
    },
    # 4. ID Document (institutional credential, paraphrased)
    {
        "id": "variant_4_id",
        "expected": DocumentType.id_document,
        "description": "ID: Institutional credential with unique numeric code",
        "text": (
            "State Personal Verification Record\n"
            "Holder: Vikram Malhotra\n"
            "Unique Identifier: 938102948194\n"
            "Issued: 2021-11-04\n"
            "Validating Authority: Department of Vital Records and Verification Authority"
        ),
    },
    # 5. Marksheet (paraphrased modular grade outcome)
    {
        "id": "variant_5_marksheet",
        "expected": DocumentType.marksheet,
        "description": "Marksheet: Paraphrased course marks and scores without standard headers",
        "text": (
            "Coursework and Modular Assessment Outcome\n"
            "Learner: Priyadarshini Rao\n"
            "Assessment Table:\n"
            "Advanced Operating Systems\tScore: 92/100\tPerformance Level: A+\n"
            "Distributed Algorithms\tScore: 88/100\tPerformance Level: A\n"
            "Cryptography & Network Security\tScore: 95/100\tPerformance Level: O\n"
            "Compiler Optimization\tScore: 90/100\tPerformance Level: A+\n"
            "Overall Cumulative Score: 9.25 out of 10.0"
        ),
    },
    # 6. Marksheet (assessment score summary)
    {
        "id": "variant_6_marksheet",
        "expected": DocumentType.marksheet,
        "description": "Marksheet: Term score breakdown with tabular credits",
        "text": (
            "Curricular Subject Evaluation Breakdown\n"
            "Candidate: Siddharth Nair\n"
            "Subject Scores:\n"
            "Theory of Computation\t3 Credits\tMarks: 84/100\n"
            "Database Systems\t4 Credits\tMarks: 89/100\n"
            "Computer Architecture\t4 Credits\tMarks: 91/100\n"
            "Overall Average Standing: 8.85"
        ),
    },
    # 7. Registration Letter (paraphrased enrollment affiliation)
    {
        "id": "variant_7_reg_letter",
        "expected": DocumentType.registration_letter,
        "description": "Registration Letter: Formal matriculation confirmation",
        "text": (
            "To Whom It May Concern,\n"
            "This official communication confirms that candidate Aarav Patel has been formally matriculated "
            "into the Department of Electrical Engineering under institutional enrollment code BLR-2023-9481.\n"
            "The candidate is an officially enrolled member of the academic registry for the active session."
        ),
    },
    # 8. Registration Letter (formal administrative certificate)
    {
        "id": "variant_8_reg_letter",
        "expected": DocumentType.registration_letter,
        "description": "Registration Letter: Formal administrative matriculation attestation",
        "text": (
            "Administrative Registry Communication\n"
            "This is to attest that Ms. Sneha Kulkarni is duly registered as an active student scholar "
            "in the faculty of science under official docket roster entry REG-84920.\n"
            "Confirmed and attested by the Academic Secretariat."
        ),
    },
    # 9. No Heading Resume (pure raw text)
    {
        "id": "variant_9_no_heading_resume",
        "expected": DocumentType.resume,
        "description": "No Heading Resume: Raw profile text with zero titles or headings",
        "text": (
            "Deepak Sharma\n"
            "Seven years building enterprise cloud solutions, leading sprint planning, mentoring junior developers. "
            "Core competencies include containerization, Kubernetes, distributed caching, and microservice resilience. "
            "Graduated 2017 with distinction in computer science.\n"
            "deepak.sharma@example.com | +91 98765 43210"
        ),
    },
    # 10. No Heading ID Document (pure raw personal identity data)
    {
        "id": "variant_10_no_heading_id",
        "expected": DocumentType.id_document,
        "description": "No Heading ID: Bare identity data lines with zero headings",
        "text": (
            "Kavita R. Deshmukh\n"
            "Born July 14, 1996\n"
            "Designated citizen reference: 472910394821\n"
            "Endorsed by Regional Registrar"
        ),
    },
]


def run_heldout_evaluation() -> None:
    clf = DocumentClassifier()

    print("=" * 90)
    print("M4b: HELD-OUT LAYER 2/3 CLASSIFIER EVALUATION REPORT")
    print("Heading & explicit keyword lines paraphrased or removed; filenames strictly hidden")
    print("=" * 90)

    correct_count = 0
    total_count = len(_HELDOUT_VARIANTS)
    results = []

    for variant in _HELDOUT_VARIANTS:
        v_id = variant["id"]
        expected = variant["expected"]
        raw_text = variant["text"]

        # Build ParsedDocument with lines and text_by_page
        lines = [
            ParsedLine(text=l.strip(), page=0)
            for l in raw_text.splitlines()
            if l.strip()
        ]
        parsed = ParsedDocument(
            doc_id=f"heldout-{v_id}",
            sha256=f"sha_{v_id}",
            pages=1,
            lines=lines,
            text_by_page={0: raw_text},
            reader_name="heldout_test",
        )

        # Build DocumentRecord with HIDDEN filename
        doc_meta = DocumentRecord(
            doc_id=f"heldout-{v_id}",
            filename="unnamed_hidden_stream.bin",
            sha256=f"sha_{v_id}",
            storage_path=f"/anonymous/path/unnamed_{v_id}.bin",
            pages=1,
        )

        # Measure latency & peak memory
        t0 = time.perf_counter()
        cres = clf.classify(doc_meta, parsed)
        elapsed = time.perf_counter() - t0

        # Memory usage in MB (macOS ru_maxrss is bytes)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        peak_mb = usage.ru_maxrss / (1024 * 1024)

        is_correct = (cres.doc_type == expected)
        if is_correct:
            correct_count += 1

        results.append({
            "id": v_id,
            "description": variant["description"],
            "expected": expected.value,
            "predicted": cres.doc_type.value,
            "confidence": cres.confidence,
            "layer": cres.layer,
            "seconds": round(elapsed, 4),
            "peak_mb": round(peak_mb, 2),
            "reasons": cres.reasons[:2],
            "correct": is_correct,
        })

    # Print Results Table
    print(f"\n{'Document':<30} | {'Expected':<18} | {'Predicted':<18} | {'Layer':<16} | {'Conf':<5} | {'Sec':<7} | {'Peak MB':<8} | Status")
    print("-" * 125)
    for r in results:
        status = "✓ PASS" if r["correct"] else "✗ FAIL"
        print(f"{r['id']:<30} | {r['expected']:<18} | {r['predicted']:<18} | {r['layer']:<16} | {r['confidence']:<5.2f} | {r['seconds']:<7.4f} | {r['peak_mb']:<8.1f} | {status}")

    print("\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)
    acc = (correct_count / total_count) * 100
    print(f"Held-out Dataset Accuracy: {correct_count}/{total_count} ({acc:.1f}%)")
    print("Layer Distribution:")
    from collections import Counter
    layers = Counter(r["layer"] for r in results)
    for l, count in layers.items():
        print(f"  - {l:<18}: {count} documents ({count/total_count*100:.1f}%)")

    clf.unload()


if __name__ == "__main__":
    run_heldout_evaluation()
