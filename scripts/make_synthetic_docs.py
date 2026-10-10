# Owner: Laptop B
"""INX – Script: generate synthetic fixture JSON files for testing.

Creates one ParsedDocument JSON file per document type per scenario and
writes them to fixtures/.  These are the fixture files consumed by
:class:`app.parse.mock_reader.MockReader`.

Usage::

    python scripts/make_synthetic_docs.py [--scenario job_application|college]
    python scripts/make_synthetic_docs.py --all

Output files::

    fixtures/default_job_application.json
    fixtures/default_college.json
    fixtures/<doc_type>_sample.json   (one per doc type)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Root of the repository
_REPO_ROOT = Path(__file__).parent.parent
_FIXTURES_DIR = _REPO_ROOT / "fixtures"


def make_job_application_fixtures() -> None:
    """Write synthetic ParsedDocument JSON files for the job_application scenario."""
    raise NotImplementedError


def make_college_fixtures() -> None:
    """Write synthetic ParsedDocument JSON files for the college scenario."""
    raise NotImplementedError


def main() -> None:
    """Parse args and generate requested fixtures."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
