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

