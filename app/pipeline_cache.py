# Owner: Laptop B
"""INX – Extraction Result Cache (app/pipeline_cache.py).

Provides persistent disk caching for field extraction results keyed by:
    key = sha256(sha256(page image bytes) + model + prompt_version)

Handed to the real extractor to skip redundant LLM/VLM calls.
Controlled via the --no-cache CLI flag.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ResultCache:
    """JSON file-based cache for extraction results in data/cache/."""

    def __init__(self, cache_dir: Path | str = "data/cache") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_key(page_image_bytes: bytes, model: str, prompt_version: str) -> str:
        """Derive cache key from sha256(page image bytes) + model + prompt_version."""
        img_sha = hashlib.sha256(page_image_bytes).hexdigest()
        compound = f"{img_sha}:{model}:{prompt_version}".encode("utf-8")
        return hashlib.sha256(compound).hexdigest()

    def get(self, key: str) -> Optional[dict[str, Any]]:
        """Retrieve cached result dict, or None on cache miss."""
        target = self.cache_dir / f"{key}.json"
        if not target.exists():
            return None
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Cache read failed for key %s: %s", key, exc)
            return None

    def set(self, key: str, value: Any) -> None:
        """Write extraction result dict to disk cache."""
        target = self.cache_dir / f"{key}.json"
        try:
            target.write_text(json.dumps(value, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Cache write failed for key %s: %s", key, exc)

    def has(self, key: str) -> bool:
        """Check if key exists in cache."""
        return (self.cache_dir / f"{key}.json").exists()

    def clear(self) -> int:
        """Wipe all cached entries; return count removed."""
        count = 0
        for p in self.cache_dir.glob("*.json"):
            try:
                p.unlink()
                count += 1
            except Exception:
                pass
        return count
