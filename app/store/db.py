# Owner: Laptop B
"""INX – SQLite case database and event store (store/db.py).

Persists serialised :class:`CaseRecord` objects and append-only stage audit
events to a local SQLite database in WAL mode. No ORM is used.

Tables:
    cases       – Master records with JSON payload and routing metadata
    documents   – Physical files associated with each case
    fields      – Validated extracted fields per case
    events      – Append-only audit trail (no UPDATE / DELETE allowed)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.schemas import CaseRecord

_DEFAULT_DB_PATH = Path("data/audit.db")


def _get_connection(db_path: Path) -> sqlite3.Connection:
    """Open (and create parent dirs if necessary) the SQLite database with WAL mode."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create cases, documents, fields, and events tables if not already present."""
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cases (
                case_id     TEXT PRIMARY KEY,
                scenario    TEXT NOT NULL,
                route       TEXT,
                status      TEXT,
                sender_email TEXT,
                created_at  TEXT,
                updated_at  TEXT,
                payload     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                doc_id          TEXT PRIMARY KEY,
                case_id         TEXT NOT NULL,
                filename        TEXT,
                sha256          TEXT,
                doc_type        TEXT,
                quality_verdict TEXT,
                storage_path    TEXT,
                pages           INTEGER,
                created_at      TEXT,
                FOREIGN KEY (case_id) REFERENCES cases (case_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS fields (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id     TEXT NOT NULL,
                doc_type    TEXT,
                field_name  TEXT,
                value       TEXT,
                status      TEXT,
                confidence  REAL,
                reason      TEXT,
                FOREIGN KEY (case_id) REFERENCES cases (case_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS events (
                event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                case_id     TEXT NOT NULL,
                stage       TEXT NOT NULL,
                sha256      TEXT,
                rule_ids    TEXT,
                version     TEXT,
                actor       TEXT,
                payload     TEXT
            );
            """
        )


def save_case(
    case: CaseRecord,
    db_path: Optional[Path] = None,
) -> None:
    """Insert or replace a :class:`CaseRecord` and its associated documents/fields."""
    path = db_path or _DEFAULT_DB_PATH
    conn = _get_connection(path)
    now = datetime.now(timezone.utc).isoformat()
    route_val = case.route.value if case.route else None
    status_val = case.workflow_status.value

    with conn:
        conn.execute(
            """
            INSERT INTO cases (case_id, scenario, route, status, sender_email, created_at, updated_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                scenario = excluded.scenario,
                route = excluded.route,
                status = excluded.status,
                sender_email = excluded.sender_email,
                updated_at = excluded.updated_at,
                payload = excluded.payload;
            """,
            (
                case.case_id,
                case.scenario,
                route_val,
                status_val,
                case.sender_email,
                case.received_at.isoformat(),
                now,
                case.model_dump_json(),
            ),
        )

        # Sync documents table
        conn.execute("DELETE FROM documents WHERE case_id = ?", (case.case_id,))
        for doc in case.documents:
            conn.execute(
                """
                INSERT INTO documents (doc_id, case_id, filename, sha256, doc_type, quality_verdict, storage_path, pages, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    doc.doc_id,
                    case.case_id,
                    doc.filename,
                    doc.sha256,
                    doc.doc_type.value,
                    doc.quality_verdict,
                    doc.storage_path,
                    doc.pages,
                    doc.ingested_at.isoformat(),
                ),
            )

        # Sync fields table
        conn.execute("DELETE FROM fields WHERE case_id = ?", (case.case_id,))
        for fr in case.fields.values():
            dt_val = fr.doc_type.value if fr.doc_type else None
            conn.execute(
                """
                INSERT INTO fields (case_id, doc_type, field_name, value, status, confidence, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    case.case_id,
                    dt_val,
                    fr.field,
                    fr.value,
                    fr.status.value,
                    fr.confidence,
                    fr.reason,
                ),
            )
    conn.close()


def load_case(
    case_id: str,
    db_path: Optional[Path] = None,
) -> Optional[CaseRecord]:
    """Retrieve a :class:`CaseRecord` by its UUID."""
    path = db_path or _DEFAULT_DB_PATH
    if not path.exists():
        return None

    conn = _get_connection(path)
    cur = conn.execute("SELECT payload FROM cases WHERE case_id = ?", (case_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None
    return CaseRecord.model_validate_json(row["payload"])


def list_cases(
    scenario: Optional[str] = None,
    route: Optional[str] = None,
    limit: int = 200,
    db_path: Optional[Path] = None,
) -> list[CaseRecord]:
    """Query cases with optional filters."""
    path = db_path or _DEFAULT_DB_PATH
    if not path.exists():
        return []

    conn = _get_connection(path)
    query = "SELECT payload FROM cases WHERE 1=1"
    params: list[Any] = []

    if scenario:
        query += " AND scenario = ?"
        params.append(scenario)
    if route:
        query += " AND route = ?"
        params.append(route)

    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    cur = conn.execute(query, params)
    rows = cur.fetchall()
    conn.close()

    return [CaseRecord.model_validate_json(r["payload"]) for r in rows]


# ---------------------------------------------------------------------------
# Append-only Events API (No update or delete functions provided)
# ---------------------------------------------------------------------------


def append_event(
    case_id: str,
    stage: str,
    sha256: str = "",
    rule_ids: Optional[list[str]] = None,
    version: str = "0.1.0",
    actor: str = "pipeline",
    payload: Optional[dict[str, Any]] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Append an immutable stage event to the events table.

    Returns:
        The auto-generated event_id.
    """
    path = db_path or _DEFAULT_DB_PATH
    conn = _get_connection(path)
    now = datetime.now(timezone.utc).isoformat()
    rids_str = json.dumps(rule_ids or [])
    p_str = json.dumps(payload or {})

    with conn:
        cur = conn.execute(
            """
            INSERT INTO events (ts, case_id, stage, sha256, rule_ids, version, actor, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (now, case_id, stage, sha256, rids_str, version, actor, p_str),
        )
        event_id = cur.lastrowid
    conn.close()
    return event_id


def list_events(
    case_id: Optional[str] = None,
    limit: int = 500,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Query append-only events for audit verification."""
    path = db_path or _DEFAULT_DB_PATH
    if not path.exists():
        return []

    conn = _get_connection(path)
    query = "SELECT * FROM events WHERE 1=1"
    params: list[Any] = []

    if case_id:
        query += " AND case_id = ?"
        params.append(case_id)

    query += " ORDER BY event_id ASC LIMIT ?"
    params.append(limit)

    cur = conn.execute(query, params)
    rows = cur.fetchall()
    conn.close()

    results: list[dict[str, Any]] = []
    for r in rows:
        results.append(
            {
                "event_id": r["event_id"],
                "ts": r["ts"],
                "case_id": r["case_id"],
                "stage": r["stage"],
                "sha256": r["sha256"],
                "rule_ids": json.loads(r["rule_ids"] or "[]"),
                "version": r["version"],
                "actor": r["actor"],
                "payload": json.loads(r["payload"] or "{}"),
            }
        )
    return results
