# Owner: Laptop A
"""INX – VLM reader: Qwen3-VL-4B via Ollama for visual question answering.

Sends each page image to a locally running Ollama server with the Qwen3-VL
model.  Used as a second reader when OCR quality is low or fields are
ambiguous.

Reader name: ``"vlm"``
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.parse.base import Reader
from app.schemas import DocumentRecord, ParsedDocument


class VLMReader:
    """Qwen3-VL reader via Ollama – implements the :class:`Reader` protocol.

    Parameters
    ----------
    ollama_base_url:
        Base URL of the Ollama API server.
    model:
        Model tag to use (default ``"qwen3-vl:4b"``).
    prompt_template:
        Optional Jinja2 template string for the VLM prompt.  If ``None``,
        the built-in extraction prompt is used.
    """

    name: str = "vlm"

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        model: str = "qwen3-vl:4b",
        prompt_template: Optional[str] = None,
    ) -> None:
        self._base_url = ollama_base_url
        self._model = model
        self._prompt_template = prompt_template

    def read(
        self,
        page_image_paths: list[Path],
        doc_meta: DocumentRecord,
    ) -> ParsedDocument:
        """Send page images to Qwen3-VL and parse the structured response.

        Args:
            page_image_paths: PNG paths sent as base64 in the VLM prompt.
            doc_meta: Used to tailor the prompt (scenario, filename, etc.).

        Returns:
            A :class:`ParsedDocument` with text extracted by the VLM.  Tables
            are included where the VLM identifies tabular structure.

        Note:
            The VLM *extracts* text; it does **not** make any decision.
            Confidence scores are approximated from response entropy.
        """
        raise NotImplementedError


assert isinstance(VLMReader(), Reader), "VLMReader does not satisfy Reader protocol"
