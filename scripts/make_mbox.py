# Owner: Laptop B
"""INX – Script: create a test .mbox file with synthetic emails.

Generates a multi-message .mbox archive with attachments that exercise the
intake pipeline end-to-end.  Useful for integration tests and demos.

Usage::

    python scripts/make_mbox.py --scenario job_application --count 5
    python scripts/make_mbox.py --scenario college --count 3 --out data/test.mbox
"""

from __future__ import annotations

import argparse
import mailbox
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


def make_mbox(
    scenario: str,
    count: int,
    out_path: Path,
) -> Path:
    """Create a test .mbox file with *count* synthetic email cases.

    Args:
        scenario: Scenario name (``"job_application"`` | ``"college"``).
        count: Number of emails to generate.
        out_path: Output path for the .mbox file.

    Returns:
        The path to the written .mbox file.
    """
    raise NotImplementedError


def main() -> None:
    """Parse CLI arguments and call :func:`make_mbox`."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
