# Owner: Laptop B
"""INX – Streamlit UI: Interactive Document-to-Decision Dashboard.

Run with:
    streamlit run app/ui/streamlit_app.py

Features:
1. Scenario Selection (Job Application vs College Admission cards)
2. Batch Run (.mbox/.eml intake, live progress, stage updates, route results)
3. Quick Check (Single document/ZIP evaluation for testing)
4. Case Inspector (Original doc viewer, PyMuPDF rendering, bbox overlay toggle,
   fields with status badges and dual OCR/VLM readings)
5. Reviewer Actions (Accept/correct values, approve/reject with mandatory audit events)
6. Outbox / Emails (Held draft approval, allowlist check, DRY_RUN status)
7. Audit & Policy (Cryptographic hash-chain verification, policy YAML, Excel export)
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

import streamlit as st
from PIL import Image, ImageDraw

from app.config import load_scenario
from app.intake.email_import import count_emails
from app.notify.sender import allowed_recipients, dispatch_outbox_item, is_dry_run
from app.pipeline import build_pipeline
from app.schemas import (
    CaseRecord,
    FieldStatus,
    IssueKind,
    Route,
    WorkflowStatus,
)
from app.store.audit import verify_chain, verify_chain_detailed, write_audit
from app.store.db import (
    get_outbox,
    list_cases,
    list_events,
    list_outbox,
    load_case,
    release_held,
    save_case,
)

logger = logging.getLogger(__name__)

# Repository Paths
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FIXTURES_DIR = _REPO_ROOT / "fixtures"
_MAIL_DIR = _FIXTURES_DIR / "mail"
_SYNTHETIC_DIR = _FIXTURES_DIR / "synthetic_docs"


def get_data_dir() -> Path:
    """Return runtime data directory from environment or default."""
    return Path(os.getenv("INX_DATA_DIR", "data"))


def get_db_path() -> Path:
    """Return runtime SQLite database path."""
    return get_data_dir() / "audit.db"


def get_audit_path() -> Path:
    """Return runtime JSONL audit log path."""
    return get_data_dir() / "audit.jsonl"

# ---------------------------------------------------------------------------
# Page Configuration & Styling
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="INX – The File That Decides",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for polished, modern enterprise aesthetic
st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.1rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 1.2rem;
    }
    .card-container {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 22px;
        margin-bottom: 15px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    .badge-route-process {
        background-color: #DCFCE7;
        color: #166534;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
    }
    .badge-route-request-info {
        background-color: #DBEAFE;
        color: #1E40AF;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
    }
    .badge-route-manual {
        background-color: #FFEDD5;
        color: #9A3412;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
    }
    .badge-route-human {
        background-color: #FEE2E2;
        color: #991B1B;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
    }
    .field-card {
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 12px;
        margin-bottom: 10px;
        background-color: #FFFFFF;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_pdf_page(pdf_path: Path, page_idx: int = 0) -> Optional[Image.Image]:
    """Render a PDF page to a PIL Image using PyMuPDF."""
    try:
        import pymupdf

        doc = pymupdf.open(str(pdf_path))
        if page_idx >= len(doc):
            page_idx = 0
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=150)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()
        return img
    except Exception as exc:
        logger.warning("Failed to render PDF page via PyMuPDF: %s", exc)
        return None


def _draw_bboxes(
    img: Image.Image, case: CaseRecord, doc_type: str, page_idx: int
) -> Image.Image:
    """Draw bounding boxes for extracted fields onto the processed clean page image."""
    drawn = img.copy().convert("RGB")
    draw = ImageDraw.Draw(drawn)

    for _, fr in case.fields.items():
        if fr.page == page_idx and fr.bbox is not None:
            dt_match = fr.doc_type is None or (
                getattr(fr.doc_type, "value", str(fr.doc_type)) == doc_type
            )
            if dt_match:
                b = fr.bbox
                try:
                    color = "#16A34A" if fr.status == FieldStatus.valid else "#DC2626"
                    draw.rectangle([b.x0, b.y0, b.x1, b.y1], outline=color, width=3)
                    label = f"{fr.field}: {fr.value or ''}"
                    draw.text((b.x0 + 4, max(0, b.y0 - 16)), label, fill=color)
                except Exception as exc:
                    logger.debug("Failed drawing bbox for field %s: %s", fr.field, exc)

    return drawn


def _route_badge_html(route: Optional[str]) -> str:
    """Return colored HTML badge for a given route."""
    if not route:
        return "<span style='color:#94A3B8;'>UNKNOWN</span>"
    r = route.upper()
    if r == "PROCESS":
        return f"<span class='badge-route-process'>{r}</span>"
    if r == "REQUEST_INFO":
        return f"<span class='badge-route-request-info'>{r}</span>"
    if r == "MANUAL_VERIFICATION":
        return f"<span class='badge-route-manual'>{r}</span>"
    return f"<span class='badge-route-human'>{r}</span>"


def safe_render_table(rows: list[dict[str, Any]], placeholder: Any = None) -> None:
    """Render a tabular dataset safely using Markdown/HTML fallback when pandas is blocked."""
    if not rows:
        return

    try:
        import pandas  # noqa: F401
        if placeholder:
            placeholder.dataframe(rows, width="stretch")
        else:
            st.dataframe(rows, width="stretch")
    except Exception:
        headers = list(rows[0].keys())
        lines = [
            "| " + " | ".join(str(h) for h in headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for r in rows:
            lines.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
        md_text = "\n".join(lines)
        if placeholder:
            placeholder.markdown(md_text)
        else:
            st.markdown(md_text)


# ---------------------------------------------------------------------------
# Sidebar Navigation & Context
# ---------------------------------------------------------------------------


def render_sidebar() -> str:
    """Render the sidebar controls and scenario selector."""
    st.sidebar.markdown("### ⚙️ System Context")

    mode = os.getenv("INX_MODE", "mock").upper()
    st.sidebar.info(f"**Execution Mode**: `{mode}`")

    # Scenario Selector
    scenario_options = {
        "job_application": "💼 Job Application",
        "college": "🎓 College Admission",
    }
    curr_scenario = st.session_state.get("scenario", "job_application")
    chosen_scenario = st.sidebar.selectbox(
        "Active Scenario",
        options=list(scenario_options.keys()),
        format_func=lambda x: scenario_options[x],
        index=0 if curr_scenario == "job_application" else 1,
        key="sidebar_scenario_select",
    )
    if chosen_scenario != curr_scenario:
        st.session_state["scenario"] = chosen_scenario

    st.sidebar.divider()

    nav_tabs = [
        "Home / Scenario",
        "Batch Intake",
        "Quick Check",
        "Case Inspector",
        "Emails & Outbox",
        "Audit & Policy",
    ]
    selected_nav = st.sidebar.radio("Navigation", nav_tabs, key="nav_radio")
    return selected_nav


# ---------------------------------------------------------------------------
# View: Home / Scenario Selector
# ---------------------------------------------------------------------------


def view_home() -> None:
    """Render the two large scenario selection cards and initial instructions."""
    st.markdown("<div class='main-header'>INX: The File That Decides</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='sub-header'>Local, Policy-Driven Document Intelligence & Decision Pipeline</div>",
        unsafe_allow_html=True,
    )

    st.markdown("#### Select an Application Scenario:")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            """
            <div class='card-container'>
                <h3>💼 Job Application Intake</h3>
                <p>Automated verification for engineering and corporate candidate dossiers.</p>
                <ul>
                    <li><b>Required Documents:</b> Resume, Government Photo ID</li>
                    <li><b>Validated Fields:</b> Candidate Name, Email, Phone, Experience</li>
                    <li><b>Integrity Rules:</b> Cross-document name and ID check, date bounds</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Select Job Application", key="btn_select_job", type="primary", use_container_width=True):
            st.session_state["scenario"] = "job_application"
            st.success("Selected Job Application Scenario! Proceed to 'Batch Intake' or 'Quick Check'.")

    with col2:
        st.markdown(
            """
            <div class='card-container'>
                <h3>🎓 College Admission Intake</h3>
                <p>Academic qualification processing and credential fraud prevention.</p>
                <ul>
                    <li><b>Required Documents:</b> Academic Marksheet, Student ID</li>
                    <li><b>Validated Fields:</b> Student Name, Roll/Reg No, Marks/Grade, DOB</li>
                    <li><b>Integrity Rules:</b> Strict DOB limits, checksum validation, stamp inspection</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Select College Admission", key="btn_select_college", type="primary", use_container_width=True):
            st.session_state["scenario"] = "college"
            st.success("Selected College Admission Scenario! Proceed to 'Batch Intake' or 'Quick Check'.")

    st.divider()

    curr = st.session_state.get("scenario", "job_application")
    st.info(
        f"**Currently Active Scenario:** `{curr}`\n\n"
        "👉 Next step: Upload an `.mbox` or `.eml` mailbox in the **Batch Intake** tab, "
        "or test individual files in the **Quick Check** tab."
    )


# ---------------------------------------------------------------------------
# View: Batch Intake
# ---------------------------------------------------------------------------


def view_batch() -> None:
    """Process email mailboxes (.mbox / .eml) with live progress and results table."""
    scenario = st.session_state.get("scenario", "job_application")
    st.markdown(f"### 📦 Batch Email Intake – `{scenario}`")

    # Source selection
    source_choice = st.radio(
        "Select Source",
        ["Use Pre-built Fixture Mailbox", "Upload Custom .mbox / .eml"],
        horizontal=True,
        key="batch_source_choice",
    )

    source_path: Optional[Path] = None

    if source_choice == "Use Pre-built Fixture Mailbox":
        fixture_file = (
            "job_applications.mbox"
            if scenario == "job_application"
            else "college_applications.mbox"
        )
        default_path = _MAIL_DIR / fixture_file
        if default_path.exists():
            source_path = default_path
            count = count_emails(source_path)
            st.success(f"Loaded `{fixture_file}` with **{count} emails** ready for processing.")
        else:
            st.warning(f"Fixture mailbox not found at `{default_path}`.")
    else:
        uploaded_file = st.file_uploader(
            "Upload .mbox or .eml file",
            type=["mbox", "eml"],
            key="batch_file_uploader",
        )
        if uploaded_file is not None:
            tmp_dir = get_data_dir() / "tmp" / "uploads"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            source_path = tmp_dir / uploaded_file.name
            source_path.write_bytes(uploaded_file.getbuffer())
            count = count_emails(source_path)
            st.info(f"Uploaded `{uploaded_file.name}` containing **{count} emails**.")

    batch_limit_val = st.number_input(
        "Max Emails to Process (0 = All)",
        min_value=0,
        value=int(st.session_state.get("batch_limit_input", 0)),
        step=1,
        key="batch_limit_input",
    )
    batch_limit = int(batch_limit_val) if batch_limit_val > 0 else None

    # Real mode cold start announcement
    mode = os.getenv("INX_MODE", "mock").lower()
    if mode == "real":
        st.info("ℹ️ Real Mode: Using local Qwen3-VL via Ollama & BGE-M3. First call may experience cold-start latency (~5-10s).")

    # Run Batch Button
    if source_path is not None and st.button("🚀 Start Batch Processing", key="btn_run_batch", type="primary"):
        total_emails = count_emails(source_path)
        if batch_limit:
            total_emails = min(total_emails, batch_limit)
        progress_bar = st.progress(0, text="Initializing pipeline...")
        status_text = st.empty()
        results_placeholder = st.empty()

        pipeline = build_pipeline(scenario=scenario, data_dir=get_data_dir())

        batch_results: list[dict[str, Any]] = []
        skipped_dups: list[str] = []
        start_time = time.time()

        try:
            events_generator = pipeline.run_batch(source_path, scenario=scenario, limit=batch_limit)
            for ev in events_generator:
                if ev.kind == "batch_started":
                    status_text.text(f"Batch started: {ev.message}")
                elif ev.kind == "skipped_duplicate":
                    skipped_dups.append(ev.message)
                elif ev.kind == "case_started":
                    frac = ev.index / max(total_emails, 1)
                    eta_str = ""
                    if ev.index > 1:
                        elapsed = time.time() - start_time
                        avg_c = elapsed / (ev.index - 1)
                        rem = max(0.0, (total_emails - ev.index + 1) * avg_c)
                        eta_str = f" | Est. remaining: ~{int(rem)}s"
                    progress_bar.progress(frac, text=f"Processing case {ev.index}/{total_emails}: {ev.sender}{eta_str}")
                elif ev.kind == "stage":
                    status_text.text(f"Case {ev.index}/{total_emails} ({ev.sender}) → Stage: {ev.stage.upper()} ({ev.status})")
                elif ev.kind == "case_finished":
                    batch_results.append({
                        "Case ID": ev.case_id,
                        "Sender": ev.sender,
                        "Route": ev.status,
                        "Reason": ev.message,
                    })
                    safe_render_table(batch_results, results_placeholder)
                elif ev.kind == "batch_finished":
                    progress_bar.progress(1.0, text="Batch execution completed!")
                    status_text.text(f"Finished: {ev.message} in {time.time() - start_time:.1f}s")
                else:
                    logger.debug("Received event kind '%s': %s", ev.kind, ev.message)
        except Exception as exc:
            logger.exception("Batch execution failed: %s", exc)
            st.error(f"⚠️ Batch processing interrupted: {exc}")
        finally:
            # Memory discipline: release model weights if supported
            if hasattr(pipeline, "classifier") and hasattr(pipeline.classifier, "unload"):
                try:
                    pipeline.classifier.unload()
                except Exception:
                    pass
            if hasattr(pipeline, "extractor") and hasattr(pipeline.extractor, "unload"):
                try:
                    pipeline.extractor.unload()
                except Exception:
                    pass

        st.session_state["batch_results"] = batch_results

        # Summary Metrics
        st.divider()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Processed Cases", len(batch_results))
        m2.metric("Skipped Duplicates", len(skipped_dups))
        m3.metric("Total Seconds", f"{time.time() - start_time:.1f}s")
        avg_s = (time.time() - start_time) / max(len(batch_results), 1)
        m4.metric("Avg Seconds/Case", f"{avg_s:.2f}s")

        # Collect skipped / rejected attachments across cases
        all_skipped_attachments = []
        for r in batch_results:
            c = load_case(r["Case ID"], db_path=get_db_path())
            if c and c.skipped_files:
                for sf in c.skipped_files:
                    all_skipped_attachments.append({
                        "Case": c.case_id[:8],
                        "Filename": sf.get("filename", ""),
                        "Status": sf.get("status", ""),
                        "Reason": sf.get("reason", ""),
                    })

        if skipped_dups:
            st.warning(f"⚠️ **Skipped Duplicate Emails ({len(skipped_dups)}):**")
            for dup in skipped_dups:
                st.markdown(f"- `{dup}`")

        if all_skipped_attachments:
            st.warning(f"⚠️ **Skipped / Rejected Attachments ({len(all_skipped_attachments)}):**")
            safe_render_table(all_skipped_attachments)

    # Display Persistent Results Table & Filter
    saved_results = st.session_state.get("batch_results", [])
    if saved_results:
        st.markdown("#### 📋 Processed Batch Results")
        filter_route = st.selectbox(
            "Filter by Route",
            ["All Routes", "PROCESS", "REQUEST_INFO", "MANUAL_VERIFICATION", "HUMAN_REVIEW"],
            key="results_filter_route",
        )
        filtered = saved_results
        if filter_route != "All Routes":
            filtered = [r for r in saved_results if r["Route"] == filter_route]

        safe_render_table(filtered)

        case_to_inspect = st.selectbox(
            "Select Case to Inspect",
            [r["Case ID"] for r in filtered],
            key="select_batch_case_id",
        )
        if st.button("🔍 View Case in Inspector", key="btn_inspect_from_batch"):
            st.session_state["selected_case_id"] = case_to_inspect
            st.session_state["nav_radio"] = "Case Inspector"


# ---------------------------------------------------------------------------
# View: Quick Check (Judge's / Single Document Test)
# ---------------------------------------------------------------------------


def view_quick_check() -> None:
    """Quick-check individual files or ZIP archives (process_files) without email wrapper."""
    scenario = st.session_state.get("scenario", "job_application")
    st.markdown(f"### ⚡ Quick Check – `{scenario}`")
    st.markdown(
        "Evaluate single documents or ZIP bundles directly (e.g., handed over by a judge). "
        "Sender is automatically set to `manual@upload.local` with no emails dispatched."
    )

    qc_mode = st.radio(
        "Choose Input Method",
        ["Select Synthetic Fixture Document", "Upload Custom Files / ZIP"],
        horizontal=True,
        key="qc_input_mode",
    )

    target_paths: list[Path] = []

    if qc_mode == "Select Synthetic Fixture Document":
        if _SYNTHETIC_DIR.exists():
            fixture_files = sorted([f.name for f in _SYNTHETIC_DIR.glob("*.*") if f.suffix.lower() in [".pdf", ".jpg", ".png", ".zip"]])
            chosen_file = st.selectbox("Choose Fixture File", fixture_files, key="qc_fixture_select")
            if chosen_file:
                target_paths = [_SYNTHETIC_DIR / chosen_file]
                st.caption(f"Path: `{target_paths[0]}`")
    else:
        uploaded_files = st.file_uploader(
            "Upload Document(s) or ZIP",
            accept_multiple_files=True,
            type=["pdf", "png", "jpg", "jpeg", "zip"],
            key="qc_uploader",
        )
        if uploaded_files:
            tmp_dir = get_data_dir() / "tmp" / "quick_check"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            for uf in uploaded_files:
                p = tmp_dir / uf.name
                p.write_bytes(uf.getbuffer())
                target_paths.append(p)

    if target_paths and st.button("🔍 Evaluate Document", key="btn_run_quick_check", type="primary"):
        try:
            with st.spinner("Processing document through pipeline..."):
                pipeline = build_pipeline(scenario=scenario, data_dir=get_data_dir())
                events = list(pipeline.process_files(target_paths, scenario=scenario, label="Quick Check"))

            case_finish = next((ev for ev in events if ev.kind == "case_finished"), None)
            if case_finish:
                st.success("Evaluation complete!")
                st.markdown(
                    f"**Case Reference:** `{case_finish.case_id}` &nbsp;&nbsp;|&nbsp;&nbsp; "
                    f"**Route:** {_route_badge_html(case_finish.status)} &nbsp;&nbsp;|&nbsp;&nbsp; "
                    f"**Reasons:** {case_finish.message}",
                    unsafe_allow_html=True,
                )
                c_record = load_case(case_finish.case_id, db_path=get_db_path())
                if c_record and c_record.fields:
                    st.markdown("##### Extracted Fields:")
                    field_summary = [
                        {
                            "Field": fr.field,
                            "Value": fr.value or "(empty)",
                            "Status": fr.status.value,
                            "Confidence": f"{fr.confidence:.2f}",
                        }
                        for fr in c_record.fields.values()
                    ]
                    safe_render_table(field_summary)

                st.session_state["selected_case_id"] = case_finish.case_id
                if st.button("Inspect Case Details", key="btn_open_qc_case"):
                    st.session_state["nav_radio"] = "Case Inspector"
            else:
                st.error("Document evaluation produced no outcome.")
        except Exception as exc:
            logger.exception("Quick check evaluation failed: %s", exc)
            st.error(f"⚠️ Quick check failed: {exc}")


# ---------------------------------------------------------------------------
# View: Case Inspector & Reviewer Actions
# ---------------------------------------------------------------------------


def view_case_inspector() -> None:
    """Inspect original documents, bounding boxes, extracted fields, and reviewer actions."""
    st.markdown("### 🔍 Case Inspector & Verification")

    # Select case
    all_cases = list_cases(db_path=get_db_path())
    if not all_cases:
        st.warning("No cases found in database. Run a batch or quick check first.")
        return

    case_ids = [c.case_id for c in all_cases]
    default_id = st.session_state.get("selected_case_id")
    default_idx = case_ids.index(default_id) if default_id in case_ids else 0

    selected_id = st.selectbox(
        "Select Case",
        case_ids,
        index=default_idx,
        format_func=lambda x: f"{x[:8]}... – {next((c.sender_name or c.sender_email for c in all_cases if c.case_id == x), 'Unknown')} ({next((c.route.value if c.route else 'UNKNOWN' for c in all_cases if c.case_id == x), '')})",
        key="inspector_case_select",
    )
    st.session_state["selected_case_id"] = selected_id

    case = load_case(selected_id, db_path=get_db_path())
    if not case:
        st.error(f"Could not load case {selected_id}")
        return

    # Top Case Status Banner
    route_val = case.route.value if case.route else "UNKNOWN"
    st.markdown(
        f"**Applicant:** `{case.sender_name or case.sender_email}` &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"**Route:** {_route_badge_html(route_val)} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"**Workflow Status:** `{case.workflow_status.value}`",
        unsafe_allow_html=True,
    )

    st.divider()

    # Two-Column Layout: Left = Document Viewer, Right = Extracted Fields
    col_doc, col_fields = st.columns([1.1, 1.0])

    with col_doc:
        st.markdown("#### 📄 Document Viewer")
        if not case.documents:
            st.info("No documents attached to this case.")
        else:
            doc_names = [f"{d.doc_type.value}: {d.filename}" for d in case.documents]
            doc_idx = st.selectbox(
                "Document",
                range(len(case.documents)),
                format_func=lambda i: doc_names[i],
                key="doc_select_idx",
            )
            doc = case.documents[doc_idx]

            if doc.pages > 1:
                selected_page = st.selectbox(
                    f"Select Page (1 to {doc.pages})",
                    range(doc.pages),
                    format_func=lambda p: f"Page {p + 1} of {doc.pages}",
                    key=f"page_sel_{doc.doc_id}",
                )
            else:
                selected_page = 0

            storage_p = Path(doc.storage_path) if doc.storage_path else None
            show_bbox = st.toggle("Show Processed Page with Bounding Boxes", value=False, key="toggle_bbox")

            rendered_img: Optional[Image.Image] = None

            if show_bbox and doc.page_images and selected_page < len(doc.page_images):
                # Load processed page image (page{N}_clean.png)
                page_img_path = Path(doc.page_images[selected_page])
                if page_img_path.exists():
                    clean_img = Image.open(page_img_path)
                    rendered_img = _draw_bboxes(clean_img, case, doc.doc_type.value, page_idx=selected_page)
            elif storage_p and storage_p.exists():
                if storage_p.suffix.lower() == ".pdf":
                    rendered_img = _render_pdf_page(storage_p, page_idx=selected_page)
                else:
                    try:
                        rendered_img = Image.open(storage_p)
                    except Exception:
                        rendered_img = None

            if rendered_img:
                st.image(rendered_img, caption=f"{doc.filename} (Page {selected_page + 1})", width="stretch")
            else:
                st.warning("Preview image unavailable for this file.")

            # Download Original Button
            if storage_p and storage_p.exists():
                st.download_button(
                    "⬇️ Download Original Document",
                    data=storage_p.read_bytes(),
                    file_name=doc.filename,
                    mime="application/octet-stream",
                    key="btn_download_original",
                )

            if case.skipped_files:
                st.divider()
                st.warning(f"⚠️ **Skipped / Rejected Attachments ({len(case.skipped_files)}):**")
                safe_render_table([
                    {
                        "Filename": sf.get("filename", "unknown"),
                        "Status": sf.get("status", "rejected"),
                        "Reason": sf.get("reason", ""),
                    }
                    for sf in case.skipped_files
                ])

    with col_fields:
        st.markdown("#### 📑 Extracted Fields & Provenance")
        if not case.fields:
            st.info("No fields extracted for this case.")
        else:
            for key, fr in case.fields.items():
                status_color = (
                    "#16A34A" if fr.status == FieldStatus.valid else
                    "#2563EB" if fr.status == FieldStatus.unclear else
                    "#D97706" if fr.status == FieldStatus.conflict else
                    "#DC2626"
                )
                dual_reading = ""
                if fr.ocr_value and fr.vlm_value and fr.ocr_value.strip().lower() != fr.vlm_value.strip().lower():
                    dual_reading = f"<div style='font-size:0.85rem; color:#475569;'>OCR: <code>{fr.ocr_value}</code> | VLM: <code>{fr.vlm_value}</code></div>"

                quote = f"<div style='font-size:0.85rem; color:#64748B;'>Quote: <i>\"{fr.evidence_quote}\"</i></div>" if fr.evidence_quote else ""
                page_info = f"Page: {fr.page + 1}" if fr.page is not None else ""

                st.markdown(
                    f"""
                    <div class='field-card'>
                        <div style='display:flex; justify-content:space-between; margin-bottom:4px;'>
                            <b>{fr.field}</b>
                            <span style='color:{status_color}; font-weight:600;'>{fr.status.value.upper()}</span>
                        </div>
                        <div style='font-size:1.05rem; font-weight:500;'>{fr.value or '(empty)'}</div>
                        {dual_reading}
                        {quote}
                        <div style='font-size:0.8rem; color:#94A3B8; margin-top:2px;'>{page_info}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    st.divider()

    # Below: Decision Details, Fired Rules with Text, and Issues
    col_dec, col_iss = st.columns(2)

    with col_dec:
        st.markdown("#### ⚖️ Policy Decision & Fired Rules")
        if case.decision:
            st.markdown(f"**Route:** `{case.decision.route.value}`")
            st.markdown(f"**Workflow Status:** `{case.workflow_status.value}`")
            st.markdown("**Plain-language Reasons:**")
            for r in case.decision.reasons:
                st.markdown(f"- {r}")

            st.markdown("**Fired Policy Rules & Description:**")
            rule_texts: dict[str, str] = {}
            try:
                scen_cfg = load_scenario(case.scenario)
                for pr in scen_cfg.policy:
                    rule_texts[pr.id] = pr.name or pr.description or ""
            except Exception:
                pass

            if case.decision.rule_ids:
                for rid in case.decision.rule_ids:
                    r_desc = rule_texts.get(rid, "")
                    if r_desc:
                        st.markdown(f"- **`{rid}`**: {r_desc}")
                    else:
                        st.markdown(f"- **`{rid}`**")
            else:
                st.markdown("*(No policy rules fired)*")
        else:
            st.info("Decision engine has not evaluated this case.")

    with col_iss:
        st.markdown("#### ⚠️ Flagged Issues")
        if not case.issues:
            st.success("No issues detected on this case.")
        else:
            for iss in case.issues:
                page_str = f" (page {iss.page + 1})" if iss.page is not None else ""
                st.markdown(f"- **`{iss.kind.value}`** on `{iss.field}`: {iss.detail}{page_str}")

    st.divider()

    # Reviewer Actions (Human-in-the-Loop)
    st.markdown("#### ✍️ Reviewer Actions (Audit-Tracked)")
    st.caption("Human reviewer decisions write immutable audit events without altering original extraction.")

    rev_name = st.text_input("Reviewer Name", value="Reviewer Jane", key="input_reviewer_name")

    col_act1, col_act2 = st.columns(2)

    with col_act1:
        st.markdown("##### Correct / Accept Field Value")
        if case.fields:
            field_to_edit = st.selectbox("Select Field", list(case.fields.keys()), key="rev_field_select")
            curr_val = case.fields[field_to_edit].value or ""
            new_val = st.text_input("Proposed Correction", value=curr_val, key="rev_new_val")
            rev_note = st.text_input("Reviewer Justification Note (Required)", key="rev_correction_note")

            b_c1, b_c2 = st.columns(2)
            with b_c1:
                if st.button("Accept Value", key="btn_accept_val"):
                    case.intake_notes.append(
                        f"[{rev_name}]: Accepted extraction '{curr_val}' for field '{field_to_edit}'"
                    )
                    save_case(case, db_path=get_db_path())
                    write_audit(
                        case,
                        event="reviewer_action",
                        actor=rev_name,
                        extra={
                            "action": "accept_value",
                            "field": field_to_edit,
                            "value": curr_val,
                        },
                        audit_path=get_audit_path(),
                        db_path=get_db_path(),
                    )
                    st.success(f"Accepted extraction for '{field_to_edit}'.")

            with b_c2:
                if st.button("Save Value Correction", key="btn_save_correction"):
                    if not rev_note.strip():
                        st.error("A mandatory reviewer note is required.")
                    else:
                        case.intake_notes.append(
                            f"[{rev_name}]: Correction noted for '{field_to_edit}': proposed '{new_val}' (original extraction '{curr_val}' preserved). Note: {rev_note}"
                        )
                        # Rule 2b invariant: never overwrite original extraction on case.fields
                        save_case(case, db_path=get_db_path())
                        write_audit(
                            case,
                            event="reviewer_action",
                            actor=rev_name,
                            extra={
                                "action": "correct_value",
                                "field": field_to_edit,
                                "original_value": curr_val,
                                "corrected_value": new_val,
                                "note": rev_note,
                            },
                            audit_path=get_audit_path(),
                            db_path=get_db_path(),
                        )
                        st.success(f"Correction for '{field_to_edit}' recorded and audited!")

    with col_act2:
        st.markdown("##### Workflow Decision Action")
        w_note = st.text_input("Decision Note", key="rev_decision_note")

        c_a, c_b, c_c = st.columns(3)
        with c_a:
            if st.button("✅ Approve Case", key="btn_approve_case"):
                case.workflow_status = WorkflowStatus.approved
                save_case(case, db_path=get_db_path())
                write_audit(
                    case,
                    event="reviewer_action",
                    actor=rev_name,
                    extra={"action": "approve_case", "note": w_note},
                    audit_path=get_audit_path(),
                    db_path=get_db_path(),
                )
                st.success("Case marked APPROVED!")
                st.rerun()

        with c_b:
            if st.button("❌ Reject Case", key="btn_reject_case"):
                if not w_note.strip():
                    st.error("Rejection requires a mandatory note.")
                else:
                    case.workflow_status = WorkflowStatus.rejected
                    save_case(case, db_path=get_db_path())
                    write_audit(
                        case,
                        event="reviewer_action",
                        actor=rev_name,
                        extra={"action": "reject_case", "note": w_note},
                        audit_path=get_audit_path(),
                        db_path=get_db_path(),
                    )
                    st.warning("Case marked REJECTED.")
                    st.rerun()

        with c_c:
            if st.button("📩 Request Info", key="btn_request_info_case"):
                case.workflow_status = WorkflowStatus.awaiting_information
                save_case(case, db_path=get_db_path())
                write_audit(
                    case,
                    event="reviewer_action",
                    actor=rev_name,
                    extra={"action": "request_info", "note": w_note},
                    audit_path=get_audit_path(),
                    db_path=get_db_path(),
                )
                st.info("Status set to Awaiting Information.")
                st.rerun()


# ---------------------------------------------------------------------------
# View: Emails & Outbox
# ---------------------------------------------------------------------------


def view_emails() -> None:
    """View generated notification drafts, held emails, and approve/send."""
    st.markdown("### 📬 Emails & Outbox Management")

    # Safety status
    dry_run = is_dry_run()
    allowed = allowed_recipients()

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.info(f"**DRY_RUN Mode:** `{'ENABLED (Simulation only)' if dry_run else 'DISABLED (Live SMTP)'}`")
    with col_s2:
        allowed_str = ", ".join(sorted(allowed)) if allowed else "(all allowed)"
        st.info(f"**Allowed Recipients:** `{allowed_str}`")

    outbox_items = list_outbox(db_path=get_db_path())
    if not outbox_items:
        st.info("Outbox is currently empty.")
        return

    st.markdown("#### Outbox Items")
    safe_render_table(
        [
            {
                "ID": item["outbox_id"],
                "Case": item["case_id"][:8],
                "Recipient": item["recipient"],
                "Subject": item["subject"],
                "Kind": item["kind"],
                "Status": item["status"],
                "Approved By": item.get("approved_by") or "-",
            }
            for item in outbox_items
        ]
    )

    # Approve & Send Held Drafts
    held_items = [i for i in outbox_items if i["status"] in ("held", "draft")]
    if held_items:
        st.markdown("#### 📨 Approve & Send Draft")
        held_select = st.selectbox(
            "Select Message",
            held_items,
            format_func=lambda x: f"ID #{x['outbox_id']} – To: {x['recipient']} ({x['status']}): {x['subject']}",
            key="select_held_email",
        )
        if held_select:
            st.text_area("Body Preview", value=held_select["body_text"], height=120, disabled=True)
            reviewer = st.text_input("Approver Name", value="Reviewer Jane", key="approver_email_input")

            if st.button("🚀 Approve & Send Email", key="btn_send_held_email", type="primary"):
                release_held(held_select["outbox_id"], approved_by=reviewer, db_path=get_db_path())
                ok = dispatch_outbox_item(held_select["outbox_id"], db_path=get_db_path())
                if ok:
                    st.success(f"Email #{held_select['outbox_id']} dispatched!")
                    st.rerun()
                else:
                    if dry_run:
                        st.info("Simulation: Email approved and recorded in DRY_RUN mode.")
                    else:
                        st.error("SMTP dispatch failed. Check server logs.")


# ---------------------------------------------------------------------------
# View: Audit & Policy
# ---------------------------------------------------------------------------


def view_audit() -> None:
    """View append-only audit events, verify cryptographic hash-chain, and inspect policy."""
    st.markdown("### 🛡️ Audit Trail & Policy Verification")

    scenario = st.session_state.get("scenario", "job_application")

    tab_audit, tab_policy, tab_reports = st.tabs(["Audit Trail", "Loaded Policy YAML", "Reports Export"])

    with tab_audit:
        st.markdown("#### Cryptographic Hash-Chain Verification")
        if st.button("🔐 Verify Hash-Chain Integrity", key="btn_verify_chain", type="primary"):
            audit_p = get_audit_path()
            intact, broken_line = verify_chain_detailed(audit_p)
            if intact:
                st.success("✅ Chain intact: Tamper-evident SHA-256 cryptographic chain fully verified.")
            else:
                st.error(f"❌ Chain broken at line {broken_line}! Tampering detected.")

        st.divider()

        st.markdown("#### Append-Only Event Stream")
        events = list_events(limit=200, db_path=get_db_path())
        if events:
            safe_render_table(
                [
                    {
                        "ID": e["event_id"],
                        "Timestamp": e["ts"],
                        "Case": e["case_id"][:8],
                        "Stage": e["stage"],
                        "Actor": e["actor"],
                        "Rules": ", ".join(e["rule_ids"]),
                    }
                    for e in reversed(events)
                ]
            )
        else:
            st.info("No events logged yet.")

    with tab_policy:
        st.markdown(f"#### Active Policy Rules: `{scenario}`")
        yaml_p = _REPO_ROOT / "config" / f"{scenario}.yaml"
        if yaml_p.exists():
            st.code(yaml_p.read_text(encoding="utf-8"), language="yaml")
        else:
            st.error(f"Policy file not found: `{yaml_p}`")

    with tab_reports:
        st.markdown("#### Multi-Sheet Excel Reports")
        latest_report = get_data_dir() / "reports" / "latest.xlsx"
        if latest_report.exists():
            st.download_button(
                "⬇️ Download latest.xlsx",
                data=latest_report.read_bytes(),
                file_name="latest.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="btn_download_latest_xlsx",
            )
        else:
            st.info("No Excel report generated yet. Run a batch first.")


# ---------------------------------------------------------------------------
# Main Routing
# ---------------------------------------------------------------------------


def main() -> None:
    """Main application router with graceful error handling."""
    try:
        selected = render_sidebar()

        if selected == "Home / Scenario":
            view_home()
        elif selected == "Batch Intake":
            view_batch()
        elif selected == "Quick Check":
            view_quick_check()
        elif selected == "Case Inspector":
            view_case_inspector()
        elif selected == "Emails & Outbox":
            view_emails()
        elif selected == "Audit & Policy":
            view_audit()
    except Exception as exc:
        # Streamlit internal control flow exceptions (e.g. st.rerun) must bubble up
        if type(exc).__name__ in ("RerunException", "StopException"):
            raise
        logger.exception("Streamlit application error: %s", exc)
        st.error(f"⚠️ A system error occurred: {exc}. Please consult the log files.")


if __name__ == "__main__":
    main()
