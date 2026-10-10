# Owner: Laptop B
"""INX – Demo reset script (scripts/reset_demo.py).

Wipes all runtime artefacts so the next pipeline run starts from a clean slate.

Deleted targets:
  data/audit.db           – SQLite database
  data/audit.jsonl        – JSONL hash-chain audit log
  data/originals/         – Ingested document copies
  data/derived/           – Rendered page images and derivatives
  data/cache/             – Extraction result cache
  data/reports/           – Generated Excel / PDF reports
  data/emails/            – Stored raw RFC-822 .eml files
  data/tmp/               – Temporary staging directories

Safe guards:
  - Requires --yes to actually delete anything.
  - Handles read-only files (Windows common after pytest).
  - Prints a dry-run diff if --yes is omitted.
  - Never touches fixtures/ or config/.

Usage::

    python scripts/reset_demo.py --yes
    python scripts/reset_demo.py          # dry run (prints what would be deleted)
"""

from __future__ import annotations

import argparse
import logging
import os
import stat
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories to fully wipe (all contents + directory itself recreated empty)
_WIPE_DIRS = [
    "data/originals",
    "data/derived",
    "data/cache",
    "data/reports",
    "data/emails",
    "data/tmp",
]

# Individual files to delete
_WIPE_FILES = [
    "data/audit.db",
    "data/audit.db-wal",
    "data/audit.db-shm",
    "data/audit.jsonl",
]


def _remove_readonly(func, path, _exc_info):
    """Error handler for shutil.rmtree to remove read-only files on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as exc:
        logger.warning("Could not remove %s: %s", path, exc)


def _count_items(base: Path, targets: list[str]) -> int:
    total = 0
    for rel in targets:
        p = base / rel
        if p.is_dir():
            total += sum(1 for _ in p.rglob("*") if _.is_file())
        elif p.is_file():
            total += 1
    return total


def reset(base: Path, dry_run: bool) -> None:
    import shutil

    all_targets = _WIPE_DIRS + _WIPE_FILES
    total = _count_items(base, all_targets)

    if dry_run:
        print(f"\n{'=' * 60}")
        print("  DRY RUN - nothing will be deleted")
        print(f"  Would remove ~{total} files across:")
        for rel in all_targets:
            p = base / rel
            if p.exists():
                print(f"    {p.relative_to(base)}")
        print(f"\n  Re-run with --yes to actually delete.\n{'=' * 60}\n")
        return

    deleted_files = 0
    deleted_dirs = 0

    # Wipe directories
    for rel in _WIPE_DIRS:
        p = base / rel
        if p.is_dir():
            shutil.rmtree(p, onerror=_remove_readonly)
            deleted_dirs += 1
            logger.info("Removed directory: %s", p)
        # Recreate empty dir so pipeline doesn't crash on first run
        p.mkdir(parents=True, exist_ok=True)

    # Delete individual files
    for rel in _WIPE_FILES:
        p = base / rel
        if p.is_file():
            try:
                os.chmod(p, stat.S_IWRITE)
                p.unlink()
                deleted_files += 1
                logger.info("Deleted file: %s", p)
            except Exception as exc:
                logger.warning("Could not delete %s: %s", p, exc)

    print(f"\n  [OK] Reset complete - removed {deleted_dirs} directories "
          f"({total} files) and {deleted_files} standalone files.\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wipe FALCONIX runtime artefacts for a clean demo restart.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete files (omit for a safe dry run)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_REPO_ROOT,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args()

    dry_run = not args.yes
    base = args.data_dir.resolve()

    print(f"\n  FALCONIX Demo Reset  {'(DRY RUN)' if dry_run else ''}")
    print(f"  Base: {base}\n")

    # Safety check: never wipe if we're outside the repo
    if not (base / "app").is_dir():
        print("ERROR: data-dir does not look like the FALCONIX repo root. Aborting.")
        sys.exit(1)

    reset(base, dry_run=dry_run)


if __name__ == "__main__":
    main()
