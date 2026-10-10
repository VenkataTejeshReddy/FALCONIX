# INX – The File That Decides

> **A fully local, privacy-first document-to-decision system.**
> No cloud APIs. No secrets in code. One bad document never stops a batch.

---

## What it does

INX ingests email-attached documents (`.mbox` / `.eml`), parses them with
two independent readers (OCR + VLM), extracts structured fields, validates
them against scenario rules, and routes each case to one of four outcomes:

| Route | Meaning |
|---|---|
| `PROCESS` | All fields valid – forward to next step |
| `REQUEST_INFO` | Required field/document missing – ask applicant |
| `MANUAL_VERIFICATION` | Conflicting data – human must reconcile |
| `HUMAN_REVIEW` | Unreliable quality or unknown doc – escalate |

**The LLM extracts text only. It never makes decisions. Decisions come from `config/*.yaml`.**

---

## Scenarios

| Scenario | Config file | Required documents |
|---|---|---|
| `job_application` | `config/job_application.yaml` | résumé + government ID |
| `college` | `config/college.yaml` | marksheet + ID (+ optional registration letter) |

---

## Quick start

### Both laptops (Laptop B / CI)

```bash
git clone <repo>
cd FALCONIX
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements-core.txt

# Generate synthetic fixtures
python scripts/make_synthetic_docs.py --all

# Run the test suite
pytest tests/ -v

# Launch the UI
streamlit run app/ui/streamlit_app.py
```

### Laptop A (full model stack)

```bash
pip install -r requirements-core.txt -r requirements-models.txt

# Start Ollama with Qwen3-VL
ollama pull qwen3-vl:4b && ollama serve

# Start Qdrant
docker run -p 6333:6333 qdrant/qdrant

# Run CLI with docling reader
python scripts/run_cli.py --source data/batch.mbox --scenario job_application --reader docling
```

---

## Project layout

```
FALCONIX/
├── app/
│   ├── schemas.py          # Shared Pydantic v2 contracts (Laptop B)
│   ├── config.py           # YAML config loader (Laptop B)
│   ├── pipeline.py         # Stage orchestrator (Laptop B)
│   ├── intake/             # Email import + case builder (Laptop B)
│   ├── parse/              # Reader protocol + 4 readers (Laptop A)
│   ├── classify/           # Document type classification (Laptop A)
│   ├── extract/            # Field extraction + reconcile (Laptop A)
│   ├── index/              # RAG: BGE-M3 + Qdrant (Laptop A)
│   ├── validate/           # Field + cross-doc validation (Laptop B)
│   ├── decide/             # Policy engine (Laptop B)
│   ├── store/              # SQLite DB + audit log (Laptop B)
│   ├── notify/             # Email drafter + sender (Laptop B)
│   ├── report/             # Excel row appender (Laptop B)
│   └── ui/                 # Streamlit interface (Laptop B)
├── config/
│   ├── job_application.yaml
│   └── college.yaml
├── fixtures/               # Synthetic ParsedDocument JSON files
├── schemas/                # Exported JSON Schema files
├── scripts/                # CLI tools
├── tests/                  # pytest suite
├── data/                   # gitignored: originals, DB, reports
├── requirements-core.txt
├── requirements-models.txt
├── .env.example
└── .gitignore
```

---

## Key invariants

1. **Original files are never modified.** They are copied to `data/originals/` (read-only) on ingest.
2. **Unknown → never approved.** A document of type `unknown` or a field with status `unreliable` cannot produce `Route.PROCESS`.
3. **One bad case never stops a batch.** `pipeline.run_batch()` catches all exceptions per-case.
4. **The LLM is not the decision-maker.** Every routing outcome is traceable to a rule ID in the YAML config.
5. **Audit chain integrity.** Each audit entry chains to the SHA-256 of the previous entry.

---

## Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Component diagram, data-flow, technology choices |
| [DECISIONS.md](DECISIONS.md) | Architecture Decision Records (ADRs) |
| [TESTING.md](TESTING.md) | Test strategy, fixture format, CI setup |
