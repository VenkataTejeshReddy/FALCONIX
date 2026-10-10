# Fixtures

This directory contains JSON fixture files used by
[`MockReader`](../app/parse/mock_reader.py) to provide pre-baked
`ParsedDocument` responses without requiring any ML model.

## File naming convention

| Filename pattern | Priority | Description |
|---|---|---|
| `<sha256>.json` | 1st | Exact match by SHA-256 of the source file |
| `<filename_stem>.json` | 2nd | Match by file name without extension |
| `default_<scenario>.json` | 3rd | Generic fallback for a scenario |

## Generating fixtures

```bash
python scripts/make_synthetic_docs.py --all
```

This writes `default_job_application.json` and `default_college.json` plus
one sample per `DocumentType`.

## Adding a custom fixture

1. Run the ingest step on a real document to get its SHA-256:
   ```bash
   python -c "from app.ingest.ingest import compute_sha256; print(compute_sha256('path/to/doc.pdf'))"
   ```
2. Create `fixtures/<sha256>.json` containing the `ParsedDocument` JSON
   (use `ParsedDocument(...).model_dump_json(indent=2)` as a template).

## Schema

Each fixture file must validate against `schemas/ParsedDocument.json`.

## Confidentiality

**Never commit real applicant data to this directory.**
Fixtures must contain only synthetic or anonymised content.
