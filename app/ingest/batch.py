"""Batch ingestion: one SOURCE (file, folder or ZIP) -> many documents.

A source is typically the attachments of ONE email (one applicant = one case).
Rules
  * One bad document never stops the others. Every document gets an outcome:
      ingested | skipped (not a supported document) | rejected (invalid/corrupt)
  * ZIPs are extracted defensively (zip-slip, zip bombs, encrypted, symlinks,
    too many entries). Nested ZIPs are expanded one level only.
  * Nothing is silently dropped: skipped and rejected files are reported.
  * Originals are stored by ingest() exactly as before (hashed, read-only).

Owner: Laptop B (pure Python, no heavy models).
"""
from __future__ import annotations

import shutil
import stat
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

from app.ingest.ingest import ALLOWED_EXT, MAX_BYTES, IngestError, IngestResult, ingest

IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
IGNORED_DIRS = {"__macosx"}


@dataclass(frozen=True)
class Limits:
    max_entries: int = 200               # entries inside one ZIP
    max_documents: int = 30              # documents processed per bundle
    max_total_uncompressed: int = 300 * 1024 * 1024
    max_ratio: int = 200                 # uncompressed / compressed (zip-bomb guard)
    max_zip_depth: int = 1               # ZIP inside ZIP allowed this many levels


@dataclass
class DocOutcome:
    name: str                            # path inside the bundle, e.g. "marks/sem1.pdf"
    status: str                          # ingested | skipped | rejected
    reason: str | None = None
    result: IngestResult | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["result"] = self.result.to_dict() if self.result else None
        return d


@dataclass
class BatchResult:
    source: str
    outcomes: list[DocOutcome] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ingested(self) -> list[DocOutcome]:
        return [o for o in self.outcomes if o.status == "ingested"]

    @property
    def skipped(self) -> list[DocOutcome]:
        return [o for o in self.outcomes if o.status == "skipped"]

    @property
    def rejected(self) -> list[DocOutcome]:
        return [o for o in self.outcomes if o.status == "rejected"]

    def summary(self) -> dict:
        return {"source": self.source, "ingested": len(self.ingested),
                "skipped": len(self.skipped), "rejected": len(self.rejected),
                "notes": self.notes}

    def to_dict(self) -> dict:
        return {"source": self.source, "notes": self.notes,
                "outcomes": [o.to_dict() for o in self.outcomes], "summary": self.summary()}


# ------------------------------------------------------------------ ZIP safety
def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def safe_extract_zip(zip_path: Path, dest: Path, limits: Limits) -> list[str]:
    """Extract defensively. Returns notes. Raises IngestError if the ZIP is unusable."""
    notes: list[str] = []
    if not zipfile.is_zipfile(zip_path):
        raise IngestError("Not a valid ZIP archive (corrupt or wrong format).")
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise IngestError(f"ZIP could not be opened: {e}")

    with zf:
        infos = zf.infolist()
        if len(infos) > limits.max_entries:
            raise IngestError(f"ZIP has {len(infos)} entries (limit {limits.max_entries}).")
        total = sum(i.file_size for i in infos)
        if total > limits.max_total_uncompressed:
            raise IngestError(f"ZIP expands to {total/1e6:.0f} MB (limit "
                              f"{limits.max_total_uncompressed/1e6:.0f} MB).")

        dest.mkdir(parents=True, exist_ok=True)
        dest_root = dest.resolve()
        for info in infos:
            if info.is_dir():
                continue
            if info.flag_bits & 0x1:
                notes.append(f"skipped encrypted entry: {info.filename}")
                continue
            if _is_symlink(info):
                notes.append(f"skipped symlink entry: {info.filename}")
                continue
            if info.compress_size and info.file_size / max(info.compress_size, 1) > limits.max_ratio:
                notes.append(f"skipped suspicious compression ratio: {info.filename}")
                continue
            if info.file_size > MAX_BYTES:
                notes.append(f"skipped oversized entry: {info.filename}")
                continue
            target = (dest_root / info.filename).resolve()
            if dest_root != target and dest_root not in target.parents:
                notes.append(f"blocked path traversal entry: {info.filename}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    return notes


# ------------------------------------------------------------------ collection
def _ignored(rel: Path) -> bool:
    parts = [p.lower() for p in rel.parts]
    return (rel.name.lower() in IGNORED_NAMES or rel.name.startswith(".")
            or any(p in IGNORED_DIRS for p in parts))


def _walk(root: Path, limits: Limits, work: Path, depth: int,
          outcomes: list[DocOutcome], notes: list[str]) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if _ignored(rel):
            continue
        ext = p.suffix.lower()
        name = rel.as_posix()
        if ext == ".zip":
            if depth >= limits.max_zip_depth:
                outcomes.append(DocOutcome(name, "skipped", "nested ZIP beyond allowed depth"))
                continue
            sub = work / f"nested_{abs(hash(name)) % 10**8}"
            try:
                notes.extend(f"{name}: {n}" for n in safe_extract_zip(p, sub, limits))
            except IngestError as e:
                outcomes.append(DocOutcome(name, "rejected", str(e)))
                continue
            for n, fp in _walk(sub, limits, work, depth + 1, outcomes, notes):
                found.append((f"{name}/{n}", fp))
        elif ext in ALLOWED_EXT:
            found.append((name, p))
        else:
            outcomes.append(DocOutcome(name, "skipped", f"unsupported file type '{ext or 'none'}'"))
    return found


def collect(source: Path, work_dir: Path, limits: Limits
            ) -> tuple[list[tuple[str, Path]], list[DocOutcome], list[str]]:
    """Resolve a source into a flat list of (name, path) documents."""
    outcomes: list[DocOutcome] = []
    notes: list[str] = []
    if not source.exists():
        raise IngestError(f"Source not found: {source}")

    if source.is_dir():
        return _walk(source, limits, work_dir, 0, outcomes, notes), outcomes, notes

    ext = source.suffix.lower()
    if ext == ".zip":
        extract_to = work_dir / "zip_extract"
        notes.extend(safe_extract_zip(source, extract_to, limits))
        return _walk(extract_to, limits, work_dir, 0, outcomes, notes), outcomes, notes
    if ext in ALLOWED_EXT:
        return [(source.name, source)], outcomes, notes
    raise IngestError(f"Unsupported source type '{ext}'. Give a PDF, image, ZIP or folder.")


# ---------------------------------------------------------------- public API
def ingest_many(source: str | Path, data_dir: str | Path = "data",
                limits: Limits | None = None) -> BatchResult:
    """Ingest a file, a folder, or a ZIP. Never raises for a bad single document;
    raises IngestError only if the SOURCE itself is unusable (e.g. corrupt ZIP)."""
    limits = limits or Limits()
    source, data_dir = Path(source), Path(data_dir)
    work_dir = data_dir / "tmp" / f"batch_{abs(hash(str(source.resolve()))) % 10**8}"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    batch = BatchResult(source=str(source))
    try:
        files, outcomes, notes = collect(source, work_dir, limits)
        batch.outcomes.extend(outcomes)
        batch.notes.extend(notes)

        if len(files) > limits.max_documents:
            batch.notes.append(f"{len(files)} documents found; processing the first "
                               f"{limits.max_documents} (limit).")
            for name, _ in files[limits.max_documents:]:
                batch.outcomes.append(DocOutcome(name, "skipped", "over per-bundle document limit"))
            files = files[:limits.max_documents]

        for name, path in files:
            try:
                res = ingest(path, data_dir)
                batch.outcomes.append(DocOutcome(name, "ingested", None, res))
            except IngestError as e:
                batch.outcomes.append(DocOutcome(name, "rejected", str(e)))
            except Exception as e:  # defensive: a bug in one file must not kill the batch
                batch.outcomes.append(DocOutcome(name, "rejected", f"unexpected error: {e}"))

        if not batch.outcomes:
            batch.notes.append("No documents found in the source.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)  # originals are already stored by hash
    return batch