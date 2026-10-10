# Owner: Laptop B
"""INX – Runtime configuration loader.

Reads scenario YAML files from config/ and surfaces them as typed objects.
All pipeline components receive a ScenarioConfig; they must never read YAML
themselves.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Global environment defaults
# ---------------------------------------------------------------------------

VLM_MODEL: str = os.getenv("VLM_MODEL", os.getenv("OLLAMA_MODEL", "qwen3-vl:4b-instruct"))
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# ---------------------------------------------------------------------------
# Sub-models that mirror YAML structure
# ---------------------------------------------------------------------------


class PolicyRule(BaseModel):
    """One entry from the ``rules`` list in a scenario YAML."""

    id: str = Field(..., description="Unique rule identifier, e.g. R01")
    condition: str = Field(
        ..., alias="if", description="Python-evaluable expression (read-only context)"
    )
    route: str
    status: str
    reason: str = ""
    applicant_message: str = ""
    message: str = ""  # backwards compatibility if populated
    priority: int = Field(0, description="Lower number = higher priority")

    model_config = {"populate_by_name": True, "extra": "allow"}

    @property
    def display_reason(self) -> str:
        return self.reason or self.message


class FieldSpec(BaseModel):
    """Specification for one extractable field within a document type."""

    required: bool = True
    validators: list[str] = Field(default_factory=list)
    description: str = ""
    min: Optional[int | float] = None
    max: Optional[int | float] = None
    regex: Optional[str] = None

    model_config = {"extra": "allow"}


class DocumentSpec(BaseModel):
    """Expected document type entry in the scenario YAML."""

    required: bool = True
    fields: dict[str, FieldSpec] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class Thresholds(BaseModel):
    """Numeric thresholds referenced by the decision engine."""

    min_field_confidence: float = 0.70
    fuzzy_exact: float = 95.0
    fuzzy_near: float = 85.0
    long_doc_pages: int = 3
    min_ocr_confidence: Optional[float] = None
    max_skew_degrees: Optional[float] = None

    model_config = {"extra": "allow"}


class CrossDocConfig(BaseModel):
    """Cross-document consistency configuration."""

    compare: list[str] = Field(default_factory=list)
    compare_sender_email: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class ScenarioConfig(BaseModel):
    """Fully parsed, validated configuration for one INX scenario."""

    name: str
    description: str = ""
    documents: dict[str, DocumentSpec] = Field(default_factory=dict)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    crossdoc: CrossDocConfig = Field(default_factory=CrossDocConfig)
    rules: list[PolicyRule] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}

    @property
    def required_doc_types(self) -> list[str]:
        return [k for k, v in self.documents.items() if v.required]

    @property
    def all_required_fields(self) -> list[str]:
        seen: list[str] = []
        for doc in self.documents.values():
            for fname, fspec in doc.fields.items():
                if fspec.required and fname not in seen:
                    seen.append(fname)
        return seen

    @property
    def sorted_rules(self) -> list[PolicyRule]:
        return sorted(self.rules, key=lambda r: r.priority)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(__file__).parent.parent / "config"
_cache: dict[str, ScenarioConfig] = {}


def load_scenario(name: str, config_dir: Optional[Path] = None) -> ScenarioConfig:
    """Load and cache a scenario config by name.

    Args:
        name: Scenario identifier, e.g. ``"job_application"``.
        config_dir: Override the default ``config/`` directory (useful in tests).

    Returns:
        A fully validated :class:`ScenarioConfig`.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
        ValueError: If the YAML is structurally invalid.
    """
    if name in _cache:
        return _cache[name]

    base = config_dir or Path(os.getenv("INX_CONFIG_DIR", str(_CONFIG_DIR)))
    path = base / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Scenario config not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    cfg = ScenarioConfig.model_validate(raw)
    _cache[name] = cfg
    return cfg


def clear_cache() -> None:
    """Evict all cached configs (useful in tests)."""
    _cache.clear()
