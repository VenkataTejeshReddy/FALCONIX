# Owner: Laptop B
"""INX – Streamlit UI: web interface for the document-to-decision pipeline.

Run with::

    streamlit run app/ui/streamlit_app.py

Pages
-----
1. **Upload & Process** – drag-drop .mbox/.eml, choose scenario, run pipeline.
2. **Case Explorer** – browse and search processed cases from the SQLite DB.
3. **Audit Log** – view and verify the hash-chain audit trail.
4. **Config Inspector** – display loaded scenario YAML in human-readable form.

Session state keys
------------------
``scenario``       : str – selected scenario name
``results``        : list[CaseRecord] – last batch results
``selected_case``  : str | None – case_id selected in explorer
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Optional

import streamlit as st

from app.config import load_scenario
from app.schemas import CaseRecord, Route, WorkflowStatus


# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="INX – The File That Decides",
    page_icon="📂",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------


def _sidebar() -> str:
    """Render sidebar and return the selected page name."""
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Page: Upload & Process
# ---------------------------------------------------------------------------


def page_upload() -> None:
    """Render the upload-and-process page."""
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Page: Case Explorer
# ---------------------------------------------------------------------------


def page_explorer() -> None:
    """Render the case browser/search page."""
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Page: Audit Log
# ---------------------------------------------------------------------------


def page_audit() -> None:
    """Render the audit log viewer with hash-chain verification."""
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Page: Config Inspector
# ---------------------------------------------------------------------------


def page_config() -> None:
    """Display the loaded scenario configuration as an expandable tree."""
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Main entry point: route to the selected page."""
    page = _sidebar()
    pages = {
        "Upload & Process": page_upload,
        "Case Explorer": page_explorer,
        "Audit Log": page_audit,
        "Config Inspector": page_config,
    }
    pages.get(page, page_upload)()


if __name__ == "__main__":
    main()
