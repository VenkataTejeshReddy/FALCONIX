# INX – Testing Guide

## Philosophy

- **All tests must pass on both laptops** with `requirements-core.txt` only.
- **No real applicant data** in `fixtures/` or `tests/`.
- **Deterministic outcomes** – tests must not depend on random seeds or
  network calls.
- The `MockReader` is the only reader used in unit and integration tests.

---

## Running tests

```bash
# Full suite
pytest tests/ -v

# Only schema tests (fast, zero model deps)
pytest tests/test_schemas.py -v

# With coverage
pytest tests/ --cov=app --cov-report=term-missing
```

---

## Test categories

| File | Scope | Laptop |
|---|---|---|
| `tests/test_schemas.py` | Pydantic model round-trips, enum validation, JSON schemas | Both |
| `tests/test_config.py` | YAML config loading, ScenarioConfig validation | Both |
| `tests/test_mock_reader.py` | MockReader fixture lookup & caching | Both |
| `tests/test_ingest.py` | Ingestion, SHA-256 deduplication, image quality flags, PDF extraction | Both |
| `tests/test_batch.py` | ZIP expansion, directory crawling, zip bomb/slip safety | Both |
| `tests/test_intake.py` | Mbox/eml intake, upfront counts, header deduplication | Both |
| `tests/test_parse.py` | PDF text layer, RapidOCR fallback, Apple Vision OCR, Docling tables | Both (`@pytest.mark.mac` for Mac OCR) |
| `tests/test_extract.py` | Fuzzy regex anchor extraction, bbox scaling, confidence scoring | Both |
| `tests/test_classify.py` | Hierarchical classifier (Layer 1 rules, Layer 2 embeddings, Layer 3 VLM) | Both (`@pytest.mark.mac` for Mac live) |
| `tests/test_validate_dates.py` | Date parsing (dayfirst/yearfirst), expiry & age rules | Both |
| `tests/test_validate_identifiers.py` | Regex patterns, Luhn check, checksum validation | Both |
| `tests/test_validate_crossdoc.py` | Name similarity, cross-document consistency checks | Both |
| `tests/test_validate_checks.py` | Rule-based document consistency & validation rules | Both |
| `tests/test_decide_engine.py` | Deterministic policy evaluation, rule prioritization, routing | Both |
| `tests/test_store.py` | SQLite schema, case saving, event appending, hash-chain audit log | Both |
| `tests/test_protocols.py` | Protocol structural subtyping verification (runtime checks) | Both |
| `tests/test_fixtures.py` | Synthetic fixture integrity, JSON schema validation | Both |
| `tests/test_pipeline.py` | End-to-end pipeline execution with MockReader & full mailbox runs | Both |
| `tests/test_report.py` | Atomic ExcelReport multi-sheet generation (Applicants, Fields, Issues, Run) | Both |
| `tests/test_notify.py` | Jinja2 templated notifications, outbox DB, DRY_RUN & allowlist safety | Both |
| `tests/test_ui.py` | Streamlit AppTest smoke tests (Home, Quick Check, Batch, Reviewer audit) | Both |

---

## Fixture format

Fixture files in `fixtures/` are `ParsedDocument` JSON objects:

```json
{
  "doc_id": "00000000-0000-0000-0000-000000000001",
  "sha256": "aaaa...aaaa",
  "pages": 1,
  "lines": [
    {"text": "John Doe", "page": 0, "conf": 0.99}
  ],
  "tables": [],
  "text_by_page": {"0": "Full Name: John Doe\nEmail: john@example.com"},
  "reader_name": "mock",
  "meta": {}
}
```

Generate with:
```bash
python scripts/make_synthetic_docs.py --all
```

Validate against the JSON Schema:
```bash
python scripts/export_schemas.py
# then use any JSON Schema validator with schemas/ParsedDocument.json
```

---

## Adding a new test

1. Create `tests/test_<module>.py`.
2. Import only from `app.schemas`, `app.config`, or the module under test.
3. Use `tmp_path` (pytest fixture) for any file I/O.
4. Mark Laptop-A-only tests with `@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")`.

---

## CI

On CI (GitHub Actions), only `requirements-core.txt` is installed.
The matrix should run:
- Python 3.11
- OS: ubuntu-latest, windows-latest

```yaml
# .github/workflows/test.yml (not yet created)
jobs:
  test:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest]
        python-version: ["3.11"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -r requirements-core.txt
      - run: pytest tests/ -v
```

---

## Operating Modes: Mock vs Real

INX supports dual execution modes controlled by the `INX_MODE` environment variable:

| Mode | Environment | Description |
|---|---|---|
| `INX_MODE=mock` | Laptop B (Windows), CI, Unit Tests | Zero GPU/model dependencies. Uses `MockReader` looking up synthetic JSON fixtures in `fixtures/synthetic_docs/`. Instantaneous processing for rapid verification. |
| `INX_MODE=real` | Laptop A (macOS Apple Silicon) | Full vision/AI stack: Apple Vision OCR / RapidOCR, Docling layout/tables, Qwen3-VL via Ollama, and BGE-M3 embeddings. |

---

## Streamlit UI Smoke Testing

The Streamlit interface is tested headless without requiring a running web server or browser using `streamlit.testing.v1.AppTest`:

```bash
pytest tests/test_ui.py -v
```

Smoke test coverage includes:
1. **Home Scenario Picker**: Verifies scenario cards render and user choice persists in `st.session_state`.
2. **Quick Check Workflow**: Uploads single document/ZIP fixtures and verifies live processing and policy route assignment.
3. **Batch Intake Workflow**: Ingests mailbox files in mock mode, asserting live ETA calculation, progress tracking, and results table population.
4. **Reviewer Action & Audit Integrity**: Simulates reviewer approvals/rejections and validates that immutable audit events are recorded in SQLite and the hash-chain.

---

## Mailbox End-to-End Evaluation

The synthetic mailbox evaluation checks routing accuracy across all synthetic emails in `job_application.mbox` and `college.mbox`:

```bash
# Run batch pipeline against synthetic mailbox
python scripts/run_cli.py --source data/synthetic_mailboxes/job_application.mbox --scenario job_application

# Run audit chain verification
python -c "from app.store.audit import verify_chain; print(verify_chain())"
```

