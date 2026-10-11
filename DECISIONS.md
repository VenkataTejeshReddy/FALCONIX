# INX – Architecture Decision Records

## ADR-001: Single shared schemas.py

**Status:** Accepted

**Context:** Multiple pipeline stages need common data types. Without a single
source of truth, types diverge and inter-stage contracts break silently.

**Decision:** All Pydantic models live in `app/schemas.py`. No module may define
its own standalone models. JSON Schema files are exported by a script.

**Consequences:** Import cycles are avoided by importing only from `app.schemas`
(never cross-importing between pipeline stages). Refactoring a model
automatically propagates to all stages.

---

## ADR-002: LLM as extractor only, never as decision-maker

**Status:** Accepted

**Context:** LLMs are probabilistic and can hallucinate. Routing decisions
(approve / reject / escalate) must be deterministic, auditable, and
traceable to an explicit policy.

**Decision:** The VLM reader (Qwen3-VL) is used only in the parse layer to
produce text from images. All routing decisions are produced by
`app/decide/engine.py` evaluating rules from `config/*.yaml`. The engine
never calls any LLM.

**Consequences:** Every decision is traceable to a rule ID. Changing policy
requires editing YAML, not prompts. Audit logs cite rule IDs, not LLM outputs.

---

## ADR-003: Two-reader design with reconciliation

**Status:** Accepted

**Context:** A single OCR reader can fail on degraded scans. A VLM reader is
slower and less precise on clean PDFs. Neither is always best.

**Decision:** Each document is processed by two readers in parallel (OCR + VLM).
`app/extract/reconcile.py` merges the outputs: agreement → valid; minor
difference → take higher-confidence; major difference → `status=conflict`.

**Consequences:** Conflict detection is automatic. Spurious conflicts from known
OCR noise (e.g. `0` vs `O`) are handled by the fuzzy threshold.

---

## ADR-004: Original files are never modified

**Status:** Accepted

**Context:** Legal admissibility and audit integrity require that submitted
documents remain byte-identical to what was received.

**Decision:** Ingest copies each attachment to `data/originals/<sha256>.<ext>`
(read-only permissions). All pipeline stages operate on copies or extracted
text. The SHA-256 is the stable document identity.

**Consequences:** Storage grows with each submission. A purge policy (outside
INX scope) must be defined separately.

---

## ADR-005: One bad case / document never stops a batch

**Status:** Accepted

**Context:** A corrupt attachment or an edge-case document must not block the
processing of hundreds of other valid cases.

**Decision:** `pipeline.run_batch()` wraps each `run_case()` call in a
`try/except`. Exceptions are caught, logged, and stored in
`CaseRecord.error`; the case is routed to `HUMAN_REVIEW`. The batch
continues.

**Consequences:** Silent failures are possible if logging is not monitored.
The audit log provides the safety net.

---

## ADR-006: Separate requirements files per laptop

**Status:** Accepted

**Context:** Heavy ML libraries (Docling, ocrmac, FlagEmbedding) cannot be
installed on Laptop B (Windows, no GPU). Installing them would break CI.

**Decision:** `requirements-core.txt` is the minimal set for Laptop B and CI.
`requirements-models.txt` is additive and only installed on Laptop A.
`MockReader` enables end-to-end pipeline testing without models.

**Consequences:** Any new model dependency must be added only to
`requirements-models.txt` and guarded with `try/ImportError` in the
relevant reader module.

---

## ADR-007: Audit log as append-only hash-chain

**Status:** Accepted

**Context:** Regulators may require tamper-evident logs. A plain JSONL log
can be edited without detection.

**Decision:** Each audit entry carries the SHA-256 of the previous line,
forming a chain. `audit.verify_chain()` validates integrity on demand.

**Consequences:** Performance overhead per append is one SHA-256 operation.
The chain must be reset explicitly when rolling over to a new log file.

---

## ADR-008: Standardized embedding and retrieval stack

**Status:** Accepted

**Context:** INX requires dense vector representations and reranking for RAG on long
documents. We evaluated `FlagEmbedding` vs `sentence-transformers` + `rank-bm25`.
`FlagEmbedding` introduces heavy extraneous dependencies (`accelerate`, `datasets`,
`ir-datasets`, `peft`) and multi-vector overhead.

**Decision:** Standardize on ONE embedding and retrieval path in project code:
- `sentence-transformers`: `SentenceTransformer("BAAI/bge-m3")` for dense 1024-d embeddings.
- `sentence-transformers`: `CrossEncoder("BAAI/bge-reranker-v2-m3")` for reranking.
- `rank-bm25`: `BM25Okapi` for lexical keyword search in hybrid retrieval.

**Consequences:** Clean dependency tree, direct HuggingFace cache loading on Apple Silicon
MPS, and reproducible lockfile across environments.

---

## ADR-009: Keying and Cross-Comparing Duplicate Document Types

**Status:** Accepted

**Context:** A case may contain multiple documents of the same type (for example, two resumes or two identity documents). When storing extracted fields on `CaseRecord.fields`, keys cannot collide without overwriting valid data. Furthermore, field discrepancies between these instances should be detected.

**Decision:** 
1. When more than one document in a single case shares a `doc_type`, the first document uses `<doc_type>.<field>` via `field_key(doc_type, field)`.
2. Subsequent documents of the same type append an instance suffix `#N` (e.g. `<doc_type>#2.<field>`).
3. Extracted fields from duplicate document types are cross-compared to identify any field-level inconsistencies or conflicts across instances of the same document type.

**Consequences:** Field keys remain unambiguous across all attachments. Multi-document submissions retain full auditability without field collisions.

---

## ADR-010: Atomic Excel Reporting with Multi-Sheet Layout

**Status:** Accepted

**Context:** Batch runs can fail mid-way due to crash or power loss. Standard file appending can leave Excel files corrupted or locked by another process. Furthermore, operational stakeholders require four distinct views: high-level applicant routing, granular field extractions, issue breakdowns, and run configuration metadata.

**Decision:** 
1. Implement `ExcelReport` (`app/report/excel.py`) using openpyxl with 4 dedicated sheets: `Applicants`, `Fields`, `Issues`, and `Run`.
2. On every single case completion, append the case rows and write to a temporary file (`.xlsx.tmp`) before atomic rename (`os.replace`) to the run file (`data/reports/<run_id>.xlsx`) and `data/reports/latest.xlsx`.

**Consequences:** At no point is the report in a corrupt or incomplete state. If a batch terminates prematurely, all cases processed up to that instant are completely preserved and readable.

---

## ADR-011: Outbox Pattern and Deterministic Templated Notifications

**Status:** Accepted

**Context:** Automatically emailing applicants based on model extractions poses two major risks: hallucinated policy text / prompt injection from adversarial resumes, and premature or misaddressed email dispatch during testing.

**Decision:**
1. All generated notifications are rendered deterministically using Jinja2 templates (`app/notify/drafter.py`) populated exclusively with structured `Issue` records and validated applicant names. No free-form LLM text generation is permitted in emails.
2. An optional polish layer (Ollama) may only improve grammar; if it hallucinates any dates, names, numbers, or policy codes not present in the draft, it is immediately discarded and falls back to the template.
3. Outgoing messages enter an SQLite `outbox` table (`app/notify/sender.py`).
4. Strict safety defaults: `DRY_RUN=true` by default (never hits SMTP network), recipient address allowlisting (blocking non-allowlisted emails even if mock SMTP is configured), and requiring explicit human reviewer approval before any `held` draft can be marked sent.

**Consequences:** Complete immunity to prompt injection via applicant documents. Zero risk of test emails escaping into real applicant mailboxes.

---

## ADR-012: Dual-Mode Streamlit UI with Immutable Audit Trail

**Status:** Accepted

**Context:** Operators need a visual workbench to inspect cases, view original and processed documents, inspect bounding boxes, review discrepancies, and take adjudication actions. The UI must run equally well on developer Windows laptops (no GPU, `INX_MODE=mock`) and production macOS machines (`INX_MODE=real`).

**Decision:**
1. Streamlit application (`app/ui/streamlit_app.py`) dynamically detects `INX_MODE` and sets mock/real pipeline readers accordingly.
2. Document visualization renders original PDFs/images alongside processed clean images (`page{N}_clean.png`) with Pillow bounding box overlays drawn from `FieldResult.bbox`.
3. Reviewer actions (accept value, correct value with mandatory note, approve, reject, request info) write immutable hash-chained audit events. The pipeline extractor/engine never marks a case `APPROVED` or `REJECTED` directly; that privilege is restricted exclusively to human reviewers.

**Consequences:** Complete separation of automated policy assessment from binding legal decisions. Smoke testing runs seamlessly in CI via `streamlit.testing.v1.AppTest`.

---

## ADR-013: Strict Matching on Identifiers and Dates

**Status:** Accepted

**Context:** Relaxed or forgiving matching on dates and personal IDs causes false valids (e.g. accepting tampered Verhoeff numbers or corrupt calendar dates). In legal and enterprise compliance intake, automated systems must never silently coerce or validate altered data.

**Decision:**
1. Verhoeff checksum algorithm is strictly enforced for 12-digit personal identity numbers. Tampered checksums immediately fail validation.
2. Date parsing strictly enforces calendar validity (rejecting 30/02/2023, 31/04/2023, 29/02/2023 non-leap, future DOB, and out-of-order date ranges).
3. Cross-document comparison flags subtle typos, initials (e.g. P. Sharma vs Priya Sharma), and surname inversions as candidate conflicts rather than silently marking them valid.
4. Validation defects are evaluated against values *as printed*, ensuring defect detection rate is preserved end-to-end.

**Consequences:** Eliminates false-valid leakage. Increases human review volume slightly for genuine edge cases, ensuring compliance safety.

---

## ADR-014: Unified Memory Management via keep_alive and unload() Policy

**Status:** Accepted

**Context:** Modern neural models (BGE-M3, Docling OCR, Qwen3-VL) compete for unified memory and CPU RAM on Apple Silicon. Leaving models permanently resident or leaking PyTorch MPS tensors degrades system performance, causing subsequent test suites or batch jobs to stall or trigger memory pressure.

**Decision:**
1. All concrete readers and classifiers implementing project protocols expose an explicit `unload()` method.
2. `DocumentClassifier.unload()` sets model references to `None`, clears cached prototype embeddings, executes `gc.collect()`, and calls `torch.mps.empty_cache()`.
3. Ollama requests set `keep_alive="3m"`, allowing rapid consecutive queries within an intake batch while guaranteeing automatic process unloading after inactivity.

**Consequences:** Peak memory remains bounded (~1 GB). Prevents MPS memory fragmentation across multi-stage pipeline executions.

---

## ADR-015: Anonymized Classification – Filename Never Used

**Status:** Accepted

**Context:** File names are unauthenticated user-supplied strings and frequent attack vectors. A malicious applicant may name a fake resume `official_marksheet.pdf`, or legitimate scanners may output neutral filenames such as `scan001.pdf` or `IMG_2041.jpg`.

**Decision:**
1. `DocumentClassifier.classify()` strictly ignores `DocumentRecord.filename`.
2. All classification logic operates exclusively on parsed document content: OCR text, bounding-box layout hints, dense semantic embeddings, and rendered page imagery.
3. Test harnesses and benchmarks anonymize filenames (`hidden_input_<sha>.bin`) to enforce protocol independence.

**Consequences:** The classifier cannot be deceived by deceptive filenames, and naturally handles neutral filenames from scanner hardware.

---

## ADR-016: Three-Tier Hierarchical Classification Architecture

**Status:** Accepted

**Context:** Keyword rules are fast and deterministic for clear documents, but fail on degraded scans or unconventional layouts. Calling a heavy VLM for every single document in a batch is slow and computationally prohibitive.

**Decision:**
1. **Layer 1 (Rules):** Evaluates keyword weights, negative keyword penalties, and structural layout signals. Decisive if and only if $\text{top\_score} \ge 0.60$ and $\text{margin} \ge 0.25$.
2. **Layer 2 (Embeddings):** Evaluates BGE-M3 dense cosine similarity between document text (first 1,500 chars) and archetype descriptions when Layer 1 is non-decisive.
3. **Layer 3 (VLM):** Invoked only when Layers 1 and 2 disagree or best confidence is low. Constrained by JSON schema to enum types or `"unknown"`.
4. **Safety Contract:** Document text is strictly data, never prompt instructions.

**Consequences:** 85%+ of standard documents resolve in milliseconds via Layer 1/2. Layer 3 VLM handles visual ambiguities without being vulnerable to prompt injection.

---

## ADR-017: Held-Out Semantic Generalization vs Fixture Overfitting

**Status:** Accepted

**Context:** Prototype keywords can inadvertently overfit to specific synthetic generator templates (e.g. "Candidate Profile Evaluation"). Evaluating only against familiar fixtures creates a false illusion of robustness.

**Decision:**
1. Remove all fixture-specific phrases from `config/doc_type_prototypes.yaml` (e.g. "candidate profile evaluation", "central verification bureau", "consolidated dossier").
2. Retain only generic domain terms across resumes, IDs, marksheets, and letters.
3. Maintain an isolated held-out test harness with paraphrased descriptions and heading-free documents.
4. Report fixture accuracy (74.3%) and held-out semantic generalization accuracy (40.0%) as distinct, honest metrics.

**Consequences:** Transparent accounting of model generalization boundaries. Real-world documents with ambiguous or non-standard text route safely to Layer 3 VLM or manual review rather than making confident false assumptions.


