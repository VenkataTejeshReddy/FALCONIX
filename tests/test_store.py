# Owner: Laptop B
"""INX – Tests: store/db.py & store/audit.py"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from app.schemas import (
    CaseRecord,
    DocumentRecord,
    DocumentType,
    FieldResult,
    FieldStatus,
)
from app.store.audit import verify_chain, write_audit
from app.store.db import (
    _get_connection,
    append_event,
    list_cases,
    list_events,
    load_case,
    save_case,
)


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_audit.db"


@pytest.fixture
def tmp_jsonl_path(tmp_path: Path) -> Path:
    return tmp_path / "test_audit.jsonl"


class TestDatabaseStore:
    def test_wal_mode_and_tables_exist(self, tmp_db_path: Path):
        conn = _get_connection(tmp_db_path)
        cur = conn.execute("PRAGMA journal_mode;")
        row = cur.fetchone()
        assert row[0].lower() == "wal"

        # Check all 4 tables exist
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tables = {r[0] for r in cur.fetchall()}
        assert {"cases", "documents", "fields", "events"}.issubset(tables)
        conn.close()

    def test_save_and_load_case_round_trip(self, tmp_db_path: Path):
        case = CaseRecord(
            scenario="job_application",
            sender_email="test@example.com",
            documents=[
                DocumentRecord(
                    filename="resume.pdf",
                    sha256="1" * 64,
                    storage_path="data/originals/resume.pdf",
                    doc_type=DocumentType.resume,
                )
            ],
            fields={
                "resume.email": FieldResult(
                    field="email",
                    doc_type=DocumentType.resume,
                    value="test@example.com",
                    status=FieldStatus.valid,
                )
            },
        )
        save_case(case, db_path=tmp_db_path)

        loaded = load_case(case.case_id, db_path=tmp_db_path)
        assert loaded is not None
        assert loaded.case_id == case.case_id
        assert loaded.sender_email == case.sender_email
        assert len(loaded.documents) == 1
        assert "resume.email" in loaded.fields

    def test_list_cases(self, tmp_db_path: Path):
        c1 = CaseRecord(scenario="job_application", sender_email="c1@example.com")
        c2 = CaseRecord(scenario="college", sender_email="c2@example.com")
        save_case(c1, db_path=tmp_db_path)
        save_case(c2, db_path=tmp_db_path)

        job_cases = list_cases(scenario="job_application", db_path=tmp_db_path)
        assert len(job_cases) == 1
        assert job_cases[0].case_id == c1.case_id

    def test_append_only_events(self, tmp_db_path: Path):
        case_id = str(uuid.uuid4())
        eid1 = append_event(
            case_id=case_id,
            stage="ingest",
            sha256="abc123sha",
            rule_ids=[],
            version="0.1.0",
            payload={"files": 2},
            db_path=tmp_db_path,
        )
        eid2 = append_event(
            case_id=case_id,
            stage="decide",
            sha256="def456sha",
            rule_ids=["R06"],
            version="0.1.0",
            payload={"route": "PROCESS"},
            db_path=tmp_db_path,
        )
        assert eid2 > eid1

        events = list_events(case_id=case_id, db_path=tmp_db_path)
        assert len(events) == 2
        assert events[0]["stage"] == "ingest"
        assert events[1]["stage"] == "decide"
        assert events[1]["rule_ids"] == ["R06"]


class TestAuditLog:
    def test_write_audit_and_verify_chain(self, tmp_jsonl_path: Path, tmp_db_path: Path):
        case = CaseRecord(scenario="job_application", sender_email="alice@example.com")
        write_audit(case, event="ingest", audit_path=tmp_jsonl_path, db_path=tmp_db_path)
        write_audit(case, event="validate", audit_path=tmp_jsonl_path, db_path=tmp_db_path)
        write_audit(case, event="decide", audit_path=tmp_jsonl_path, db_path=tmp_db_path)

        assert verify_chain(tmp_jsonl_path)

    def test_tampered_audit_chain_fails_verification(self, tmp_jsonl_path: Path, tmp_db_path: Path):
        case = CaseRecord(scenario="job_application", sender_email="alice@example.com")
        write_audit(case, event="ingest", audit_path=tmp_jsonl_path, db_path=tmp_db_path)
        write_audit(case, event="decide", audit_path=tmp_jsonl_path, db_path=tmp_db_path)

        # Tamper with the file
        lines = tmp_jsonl_path.read_text(encoding="utf-8").splitlines()
        lines[0] = lines[0].replace("ingest", "tampered_stage")
        tmp_jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        assert not verify_chain(tmp_jsonl_path)
