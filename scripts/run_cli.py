# Owner: Laptop B
"""INX – CLI entry point: run the full pipeline from the command line.

Usage examples::

    python scripts/run_cli.py \\
        --scenario job_application \\
        --source fixtures/mail/job_applications.mbox \\
        --mode mock

    python scripts/run_cli.py \\
        --scenario college \\
        --source fixtures/mail/college_applications.mbox \\
        --mode mock --limit 5

    python scripts/run_cli.py \\
        --scenario job_application \\
        --source fixtures/mail/job_applications.mbox \\
        --mode real --no-cache
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ANSI colour helpers (safe to strip for non-TTY)
_IS_TTY = os.isatty(1) if hasattr(os, "isatty") else False

_ROUTE_COLOUR = {
    "PROCESS":              "\033[92m",  # green
    "REQUEST_INFO":         "\033[93m",  # yellow
    "MANUAL_VERIFICATION":  "\033[94m",  # blue
    "HUMAN_REVIEW":         "\033[91m",  # red
}
_RESET = "\033[0m" if _IS_TTY else ""


def _colour(route: str) -> str:
    if not _IS_TTY:
        return route
    return f"{_ROUTE_COLOUR.get(route, '')}{route}{_RESET}"


def _fmt_row(index: int, sender: str, status: str, route: str, reasons: list[str]) -> str:
    reasons_str = "; ".join(reasons[:2]) if reasons else "-"
    return (
        f"  [{index:>3}] {sender:<35} "
        f"status={status:<22} route={_colour(route):<30} "
        f"reasons: {reasons_str}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FALCONIX – Run the document-processing pipeline from CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scenario",
        required=True,
        help="Scenario name (e.g. job_application | college)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to .mbox file or single .eml",
    )
    parser.add_argument(
        "--mode",
        choices=["mock", "real"],
        default=os.getenv("INX_MODE", "mock"),
        help="Pipeline mode: mock (default) or real (needs GPU/Ollama)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable result cache (real mode only)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N cases (useful for quick smoke tests)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run identifier (auto-generated if omitted)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-stage events",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.source.exists():
        print(f"ERROR: source not found: {args.source}")
        raise SystemExit(1)

    # Set env so pipeline picks up mode
    os.environ["INX_MODE"] = args.mode

    from app.pipeline import ProgressEvent, build_pipeline

    pipeline = build_pipeline(
        scenario=args.scenario,
        mode=args.mode,
        use_cache=not args.no_cache,
    )

    # --- Counters for batch summary ---
    route_counts: dict[str, int] = {}
    skipped_dups: list[str] = []
    case_rows: list[tuple[int, str, str, str, list[str]]] = []
    total_cases = 0
    t_batch_start = time.monotonic()

    print(f"\n{'=' * 80}")
    print(f"  FALCONIX  |  scenario={args.scenario}  mode={args.mode}  "
          f"source={args.source.name}")
    print(f"{'=' * 80}")

    # Stream events from pipeline
    current_case: dict = {}

    for event in pipeline.run_batch(
        args.source,
        scenario=args.scenario,
        run_id=args.run_id,
        limit=args.limit,
    ):
        if event.kind == "batch_started":
            print(f"\n  Total emails in source: {event.total}")
            print(f"  Run ID: {event.message.split('run_id=')[-1].split()[0]}\n")

        elif event.kind == "case_started":
            current_case = {"index": event.index, "sender": event.sender,
                            "case_id": event.case_id, "stages": []}
            if args.verbose:
                print(f"  > [{event.index}] {event.sender}")

        elif event.kind == "stage":
            if args.verbose:
                icon = "[OK]" if event.status == "ok" else "[ERR]"
                print(f"      {icon} {event.stage:<20} {event.elapsed_s:.3f}s  "
                      f"{event.message[:60] if event.message else ''}")

        elif event.kind == "case_finished":
            total_cases += 1
            route = event.status.upper()
            route_counts[route] = route_counts.get(route, 0) + 1
            case_rows.append((
                event.index, event.sender, "received->processed",
                route, event.message.split("; ") if event.message else [],
            ))
            print(_fmt_row(
                event.index, event.sender,
                "processed", route,
                event.message.split("; ") if event.message else [],
            ))

        elif event.kind == "skipped_duplicate":
            msg_id = event.message.replace("Duplicate Message-ID: ", "")
            skipped_dups.append(msg_id)
            print(f"  [SKIP] Duplicate Message-ID: {msg_id}")

        elif event.kind == "batch_finished":
            pass  # summary printed below

    elapsed = time.monotonic() - t_batch_start

    # --- Batch summary ---
    print(f"\n{'-' * 80}")
    print(f"  BATCH SUMMARY")
    print(f"{'-' * 80}")
    print(f"  Cases processed : {total_cases}")
    print(f"  Skipped dups    : {len(skipped_dups)}")
    print(f"  Elapsed         : {elapsed:.1f}s")
    print(f"\n  Route breakdown:")
    for route, count in sorted(route_counts.items()):
        pct = count / max(total_cases, 1) * 100
        print(f"    {_colour(route):<40} {count:>4} ({pct:.0f}%)")
    if skipped_dups:
        print(f"\n  Skipped Message-IDs:")
        for mid in skipped_dups:
            print(f"    {mid}")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
