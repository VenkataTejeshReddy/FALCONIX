import io
import zipfile
from pathlib import Path

import pymupdf as fitz
import pytest

from app.ingest.batch import Limits, ingest_many
from app.ingest.ingest import IngestError
from tests.helpers import make_doc_image


def make_pdf(path: Path, text="Marksheet"):
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), text, fontsize=20)
    doc.save(path)
    return path


def zip_of(path: Path, entries: dict[str, bytes]):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return path


def img_bytes(tmp_path, seed):
    return make_doc_image(tmp_path / f"_{seed}.png", seed=seed).read_bytes()


def test_folder_with_mixed_files(tmp_path):
    folder = tmp_path / "bundle"
    folder.mkdir()
    make_doc_image(folder / "cert.jpg", seed=1)
    make_pdf(folder / "marks.pdf")
    (folder / "notes.docx").write_bytes(b"x")
    (folder / ".DS_Store").write_bytes(b"x")
    r = ingest_many(folder, tmp_path / "data")
    assert len(r.ingested) == 2
    assert [o.name for o in r.skipped] == ["notes.docx"]  # .DS_Store silently ignored
    assert not r.rejected


def test_zip_of_five_documents(tmp_path):
    entries = {f"doc{i}.png": img_bytes(tmp_path, i) for i in range(1, 4)}
    entries["marks.pdf"] = make_pdf(tmp_path / "m.pdf").read_bytes()
    entries["form.pdf"] = make_pdf(tmp_path / "f.pdf", "Application form").read_bytes()
    z = zip_of(tmp_path / "applicant.zip", entries)
    r = ingest_many(z, tmp_path / "data")
    assert len(r.ingested) == 5


def test_single_file_source(tmp_path):
    p = make_doc_image(tmp_path / "one.png")
    r = ingest_many(p, tmp_path / "data")
    assert len(r.ingested) == 1


def test_one_bad_file_does_not_stop_the_rest(tmp_path):
    folder = tmp_path / "b"
    folder.mkdir()
    make_doc_image(folder / "good.png", seed=2)
    (folder / "fake.jpg").write_bytes(b"not an image at all")
    r = ingest_many(folder, tmp_path / "data")
    assert len(r.ingested) == 1 and len(r.rejected) == 1
    assert "does not match" in r.rejected[0].reason


def test_zip_slip_blocked(tmp_path):
    z = zip_of(tmp_path / "evil.zip", {"../../evil.png": img_bytes(tmp_path, 3),
                                        "ok.png": img_bytes(tmp_path, 4)})
    r = ingest_many(z, tmp_path / "data")
    assert len(r.ingested) == 1
    assert any("path traversal" in n for n in r.notes)
    assert not (tmp_path.parent / "evil.png").exists()


def test_nested_zip_expanded_one_level_only(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("inner.png", img_bytes(tmp_path, 5))
    deeper = io.BytesIO()
    with zipfile.ZipFile(deeper, "w") as z:
        z.writestr("deep.png", img_bytes(tmp_path, 6))
    inner2 = io.BytesIO()
    with zipfile.ZipFile(inner2, "w") as z:
        z.writestr("level2.zip", deeper.getvalue())
    outer = zip_of(tmp_path / "outer.zip", {"a.zip": inner.getvalue(), "b.zip": inner2.getvalue()})
    r = ingest_many(outer, tmp_path / "data")
    assert len(r.ingested) == 1                      # only a.zip/inner.png
    assert any("nested ZIP" in (o.reason or "") for o in r.skipped)


def test_corrupt_zip_raises(tmp_path):
    p = tmp_path / "bad.zip"
    p.write_bytes(b"PK\x03\x04 garbage garbage")
    with pytest.raises(IngestError):
        ingest_many(p, tmp_path / "data")


def test_zip_bomb_guard(tmp_path):
    z = zip_of(tmp_path / "bomb.zip", {"zeros.png": b"\0" * 5_000_000,
                                       "ok.png": img_bytes(tmp_path, 7)})
    r = ingest_many(z, tmp_path / "data")
    assert len(r.ingested) == 1
    assert any("compression ratio" in n for n in r.notes)


def test_too_many_entries_rejected(tmp_path):
    z = zip_of(tmp_path / "many.zip", {f"f{i}.txt": b"x" for i in range(10)})
    with pytest.raises(IngestError, match="entries"):
        ingest_many(z, tmp_path / "data", Limits(max_entries=5))


def test_document_limit(tmp_path):
    folder = tmp_path / "b"
    folder.mkdir()
    for i in range(3):
        make_doc_image(folder / f"d{i}.png", seed=10 + i)
    r = ingest_many(folder, tmp_path / "data", Limits(max_documents=2))
    assert len(r.ingested) == 2
    assert any("document limit" in (o.reason or "") for o in r.skipped)


def test_empty_folder_and_zip_with_no_documents(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = ingest_many(empty, tmp_path / "data")
    assert not r.outcomes and "No documents" in r.notes[-1]
    z = zip_of(tmp_path / "txt.zip", {"readme.txt": b"hi"})
    r2 = ingest_many(z, tmp_path / "data")
    assert not r2.ingested and len(r2.skipped) == 1


def test_missing_source_and_unsupported_source(tmp_path):
    with pytest.raises(IngestError):
        ingest_many(tmp_path / "nope.zip", tmp_path / "data")
    t = tmp_path / "a.txt"
    t.write_text("x")
    with pytest.raises(IngestError):
        ingest_many(t, tmp_path / "data")


def test_identical_documents_flagged_duplicate(tmp_path):
    same = img_bytes(tmp_path, 9)
    z = zip_of(tmp_path / "dup.zip", {"a.png": same, "b.png": same})
    r = ingest_many(z, tmp_path / "data")
    assert len(r.ingested) == 2
    assert sum(o.result.duplicate for o in r.ingested) == 1