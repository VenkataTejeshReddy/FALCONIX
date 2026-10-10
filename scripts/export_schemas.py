# Owner: Laptop B
"""INX – Script: export Pydantic v2 JSON Schemas to schemas/*.json.

Reads all models from app.schemas and writes their JSON Schema (draft 2020-12)
to the schemas/ directory.  Run this whenever schemas.py changes.

Usage::

    python scripts/export_schemas.py

Output::

    schemas/FieldStatus.json
    schemas/WorkflowStatus.json
    schemas/Route.json
    schemas/DocumentType.json
    schemas/BBox.json
    schemas/FieldResult.json
    schemas/ParsedLine.json
    schemas/ParsedDocument.json
    schemas/DocumentRecord.json
    schemas/CaseRecord.json
    schemas/Decision.json
    schemas/Issue.json
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_SCHEMAS_DIR = _REPO_ROOT / "schemas"


def export_all() -> None:
    """Export JSON Schemas for all public Pydantic models in app.schemas."""
    from app import schemas as S

    _SCHEMAS_DIR.mkdir(exist_ok=True)

    models = [
        S.BBox,
        S.FieldResult,
        S.ParsedLine,
        S.ParsedDocument,
        S.DocumentRecord,
        S.CaseRecord,
        S.Decision,
        S.Issue,
    ]

    for model in models:
        schema = model.model_json_schema()
        out = _SCHEMAS_DIR / f"{model.__name__}.json"
        out.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        print(f"  wrote {out.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    export_all()
