# INX – Architecture

## System Overview

```
Email source (.mbox / .eml)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  INTAKE (Laptop B)                                          │
│  email_import → iter_messages → extract_attachments         │
│                  └── expand_zip                             │
│  case_builder → CaseRecord (status: received)               │
└───────────────────────────┬─────────────────────────────────┘
                            │  List[CaseRecord]
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  INGEST (pre-built, do not modify)                          │
│  validate → SHA-256 → read-only storage → quality_gate      │
│  deskew → ingest_many                                       │
└───────────────────────────┬─────────────────────────────────┘
                            │  DocumentRecord.storage_path set
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  PARSE (Laptop A)                                           │
│  render_pdf_to_images → Reader.read() → ParsedDocument      │
│  Readers: docling | apple_ocr | vlm | mock                  │
└───────────────────────────┬─────────────────────────────────┘
                            │  ParsedDocument (lines, tables, text_by_page)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  CLASSIFY (Laptop A)                                        │
│  rules.classify_by_keywords + classify_by_layout            │
│  → DocumentRecord.doc_type, doc_type_confidence             │
└───────────────────────────┬─────────────────────────────────┘
                            │  DocumentType assigned
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  EXTRACT (Laptop A)                                         │
│  field_extractor.extract_fields                             │
│  grounding.ground_all_fields                                │
│  reconcile.reconcile_case_fields (OCR ⊕ VLM)               │
│  → CaseRecord.fields: Dict[str, FieldResult]                │
└───────────────────────────┬─────────────────────────────────┘
                            │  FieldResult per field
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  VALIDATE (Laptop B)                                        │
│  checks.validate_case    ← named validators from YAML       │
│  crossdoc.run_cross_checks                                  │
│  → FieldResult.status updated; CaseRecord.issues populated  │
└───────────────────────────┬─────────────────────────────────┘
                            │  issues list
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  DECIDE (Laptop B)                                          │
│  engine.decide → eval policy rules (safe namespace)         │
│  explain.explain_decision                                   │
│  → CaseRecord.route, .workflow_status, .decision            │
└───────────────────────────┬─────────────────────────────────┘
                            │  Decision
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  STORE + AUDIT + REPORT + NOTIFY (Laptop B)                 │
│  db.save_case → SQLite  (cases, events, outbox tables)      │
│  audit.write_audit → JSONL hash-chain (SHA-256 chained)     │
│  ExcelReport.append_case → data/reports/<run_id>.xlsx       │
│    Sheets: Applicants, Fields, Issues, Run                  │
│    Atomic write (temp file → rename) after EVERY case       │
│    Copied to data/reports/latest.xlsx                       │
│  drafter.py → Jinja2 templates (.txt + .html)               │
│    Built ONLY from structured issues (never raw LLM text)   │
│  sender.py → DRY_RUN (default), allowlist, outbox/held      │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  UI – Streamlit (Laptop B)                                   │
│  Home → Scenario cards (job_application / college)           │
│  Batch Intake → .mbox/.eml, live progress, ETA, results     │
│  Quick Check → single file / ZIP, process_files              │
│  Case Inspector → original doc viewer, bbox overlay,         │
│    fields with dual OCR/VLM readings, policy reasons         │
│  Reviewer Actions → accept/correct/approve/reject/req_info   │
│    (writes immutable audit events; only place status can      │
│     become approved/rejected)                                │
│  Emails & Outbox → held drafts, approve & send               │
│  Audit & Policy → hash-chain verification, YAML view, Excel │
└─────────────────────────────────────────────────────────────┘
```

## Technology Choices

| Layer | Technology | Reason |
|---|---|---|
| Data contracts | Pydantic v2 | Fast validation, JSON Schema export, model_copy |
| Config | YAML + pydantic | Human-editable policy without code changes |
| Parse (primary) | Docling | Layout-aware, table extraction, open-source |
| Parse (OCR) | Apple Vision (ocrmac) | Native M4 quality, no network |
| Parse (VLM) | Qwen3-VL-4B via Ollama | Visual understanding for complex layouts |
| Parse (CI) | MockReader | Fixture-based, zero dependencies |
| Retrieval | BGE-M3 + Qdrant local | Fully offline, high-quality multilingual |
| Reranking | bge-reranker-v2-m3 | Cross-encoder for precision |
| Storage | SQLite (stdlib) | Zero-dependency, WAL for concurrency |
| Excel | openpyxl | Pure Python, no Excel installation |
| Email | stdlib smtplib | No external mail SDK |
| UI | Streamlit | Rapid prototyping, no JS |

## Two-Laptop Split

Every file starts with `# Owner: Laptop A` or `# Owner: Laptop B`.

**Laptop A (Mac M4, 16 GB)** – model-heavy:
- `app/parse/` (all readers except mock)
- `app/classify/`
- `app/extract/`
- `app/index/`

**Laptop B** – policy, storage, UI:
- `app/schemas.py`, `app/config.py`, `app/pipeline.py`
- `app/intake/`
- `app/validate/`
- `app/decide/`
- `app/store/`, `app/notify/`, `app/report/`, `app/ui/`

Both laptops share: `app/parse/mock_reader.py`, `config/`, `fixtures/`,
`scripts/`, `tests/`.

## RAG (Index layer – built last)

For documents > ~5 pages, the extractor falls back to a retrieval step:
1. Chunk `ParsedDocument.lines` into ~256-token windows.
2. Embed with BGE-M3 and upsert into Qdrant (collection per case or per run).
3. Query with field name as the question.
4. Rerank top-k with bge-reranker-v2-m3.
5. The top passage is used as the extraction context.

This path is gated behind a document-length threshold in the scenario YAML
and is **not** activated in the initial scaffold.
