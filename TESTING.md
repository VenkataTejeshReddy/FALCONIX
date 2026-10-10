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
| `tests/test_schemas.py` | Pydantic round-trips, enum validation | Both |
| `tests/test_config.py` | YAML loading, ScenarioConfig validation | Both |
| `tests/test_mock_reader.py` | MockReader fixture lookup | Both |
| `tests/test_pipeline.py` | Full pipeline with MockReader | Both |

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
