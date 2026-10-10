# Owner: Laptop B
"""INX – CLI entry point: run the pipeline from the command line.

Usage::

    python scripts/run_cli.py --source path/to/batch.mbox \\
                              --scenario job_application \\
                              --reader mock

    python scripts/run_cli.py --source data/emails/ \\
                              --scenario college \\
                              --reader docling \\
                              --skip-notify \\
                              --out data/results.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def parse_args() -> argparse.Namespace:
    """Define and parse CLI arguments."""
    raise NotImplementedError


def main() -> None:
    """Main CLI entry point: load cases, run pipeline, write output."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
