# Owner: Laptop B
"""INX – Immutable audit log (store/audit.py).

Writes a tamper-evident, append-only JSONL audit trail for every pipeline
event and coordinates with the SQLite events table. Every stage writes an
event with timestamp, sha256, rule ids, and version.

Integrity
---------
Each entry in JSONL carries the SHA-256 of the *previous* entry's JSON line,
forming a cryptographic hash-chain.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.schemas import CaseRecord
from app.store.db import append_event

_DEFAULT_AUDIT_PATH = Path("data/audit.jsonl")


def _hash_line(line: str) -> str:
    """Return the SHA-256 hex digest of *line* (UTF-8 encoded)."""
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _last_hash(audit_path: Path) -> str:
    """Return the hash of the last line in the audit file, or 'GENESIS'."""
    if not audit_path.exists():
        return "GENESIS"

    last_line = ""
    with audit_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last_line = line.strip()

    if not last_line:
        return "GENESIS"

    return _hash_line(last_line)


def write_audit(
    case: CaseRecord,
    event: str = "pipeline_complete",
    actor: str = "pipeline",
    extra: Optional[dict[str, Any]] = None,
    audit_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Record an immutable stage event to both SQLite events and the JSONL hash-chain.

    Records timestamp, sha256, rule ids, version, actor, and payload.
    """
    path = audit_path or _DEFAULT_AUDIT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Compute case SHA-256 digest
    case_json = case.model_dump_json()
    case_sha256 = hashlib.sha256(case_json.encode("utf-8")).hexdigest()

    now = datetime.now(timezone.utc).isoformat()
    rule_ids = case.rule_ids
    version = case.pipeline_version

    payload_data: dict[str, Any] = {
        "scenario": case.scenario,
        "route": case.route.value if case.route else None,
        "workflow_status": case.workflow_status.value,
        "issue_count": len(case.issues),
    }
    if extra:
        payload_data.update(extra)

    # 2. Write to SQLite events table
    append_event(
        case_id=case.case_id,
        stage=event,
        sha256=case_sha256,
        rule_ids=rule_ids,
        version=version,
        actor=actor,
        payload=payload_data,
        db_path=db_path,
    )

    # 3. Append to JSONL with cryptographic hash-chain
    prev_hash = _last_hash(path)
    entry = {
        "ts": now,
        "case_id": case.case_id,
        "stage": event,
        "actor": actor,
        "sha256": case_sha256,
        "rule_ids": rule_ids,
        "version": version,
        "prev_hash": prev_hash,
        "payload": payload_data,
    }

    line = json.dumps(entry, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def verify_chain(audit_path: Optional[Path] = None) -> bool:
    """Verify the hash-chain integrity of the audit log."""
    path = audit_path or _DEFAULT_AUDIT_PATH
    if not path.exists():
        return True

    prev_hash = "GENESIS"
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue

            entry = json.loads(line_str)
            if entry.get("prev_hash") != prev_hash:
                return False

            prev_hash = _hash_line(line_str)

    return True
