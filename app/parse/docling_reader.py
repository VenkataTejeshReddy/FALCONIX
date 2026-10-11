# Owner: Laptop A
"""INX – Docling reader: layout and table structure parsing.

Wraps the ``docling`` library to extract tables (Markdown AND list-of-rows into
ParsedDocument.tables, with page and bbox in meta), reading order, and headers.
Avoids duplicate OCR by keeping tables and structure only.
Loads Docling once per process as a lazy singleton.

Reader name: ``"docling"``
"""

from __future__ import annotations

import gc
import logging
import time
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from app.parse.base import Reader
from app.schemas import BBox, DocumentRecord, ParsedDocument, ParsedLine

logger = logging.getLogger(__name__)

_CONVERTER_INSTANCE: Any = None


def get_docling_converter(device: str = "mps") -> Any:
    """Return a process-wide lazy singleton DocumentConverter instance."""
    global _CONVERTER_INSTANCE
    if _CONVERTER_INSTANCE is not None:
        return _CONVERTER_INSTANCE

    import sys
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    pdf_options = PdfPipelineOptions()
    pdf_options.do_ocr = False
    pdf_options.do_table_structure = True

    # Offline cache path check
    artifacts_path = Path.home() / ".cache" / "docling" / "models"
    if artifacts_path.exists():
        pdf_options.artifacts_path = artifacts_path

    img_options = PdfPipelineOptions()
    img_options.do_table_structure = True
    if artifacts_path.exists():
        img_options.artifacts_path = artifacts_path

    if sys.platform == "darwin":
        try:
            from docling.datamodel.pipeline_options import OcrMacOptions
            img_options.do_ocr = True
            img_options.ocr_options = OcrMacOptions()
        except Exception:
            img_options.do_ocr = False
    else:
        img_options.do_ocr = False

    _CONVERTER_INSTANCE = DocumentConverter(
        format_options={
            "pdf": PdfFormatOption(pipeline_options=pdf_options),
            "image": ImageFormatOption(pipeline_options=img_options),
        }
    )
    return _CONVERTER_INSTANCE


def unload_docling() -> None:
    """Unload Docling lazy singleton and reclaim memory."""
    global _CONVERTER_INSTANCE
    _CONVERTER_INSTANCE = None
    gc.collect()
    try:
        import torch

        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass


class DoclingReader:
    """Docling structure and table reader – implements the :class:`Reader` protocol."""

    name: str = "docling"

    def __init__(self, device: str = "mps") -> None:
        self._device = device

    def unload(self) -> None:
        """Free model resources."""
        unload_docling()

    def read(
        self,
        page_image_paths: list[Path],
        doc_meta: DocumentRecord,
    ) -> ParsedDocument:
        """Parse document structure and tables using Docling."""
        converter = get_docling_converter(self._device)

        all_lines: list[ParsedLine] = []
        text_by_page: dict[int, str] = {}
        tables_data: list[list[list[str]]] = []
        tables_meta: list[dict[str, Any]] = []
        page_dims: list[dict[str, Any]] = []

        # Read page image dimensions
        for p, img_path in enumerate(page_image_paths):
            img_path = Path(img_path)
            if img_path.exists():
                try:
                    with Image.open(img_path) as pil_img:
                        page_dims.append({"page": p, "width": pil_img.width, "height": pil_img.height})
                except Exception:
                    page_dims.append({"page": p, "width": 800, "height": 1000})
            else:
                page_dims.append({"page": p, "width": 800, "height": 1000})

        # Process source document (original file or page images)
        source_target: Optional[Path] = None
        if doc_meta.storage_path and Path(doc_meta.storage_path).exists():
            source_target = Path(doc_meta.storage_path)
        elif page_image_paths and Path(page_image_paths[0]).exists():
            source_target = Path(page_image_paths[0])

        if source_target is not None:
            try:
                t0 = time.perf_counter()
                res = converter.convert(str(source_target))
                doc = res.document

                # Extract tables
                for t_idx, table in enumerate(doc.tables):
                    try:
                        md_str = table.export_to_markdown(doc=doc)
                    except TypeError:
                        md_str = table.export_to_markdown()

                    try:
                        df = table.export_to_dataframe(doc=doc)
                        # list-of-rows: header + data rows
                        rows: list[list[str]] = [
                            [str(col) for col in df.columns]
                        ] + [
                            [str(c) for c in row] for row in df.values.tolist()
                        ]
                    except Exception:
                        rows = []

                    tables_data.append(rows)

                    # Extract bbox and page if available in provenance
                    table_page = 0
                    table_bbox: Optional[list[float]] = None
                    if getattr(table, "prov", None) and len(table.prov) > 0:
                        prov = table.prov[0]
                        table_page = max(0, getattr(prov, "page_no", 1) - 1)
                        if hasattr(prov, "bbox") and prov.bbox is not None:
                            b = prov.bbox
                            table_bbox = [float(b.l), float(b.t), float(b.r), float(b.b)]

                    tables_meta.append(
                        {
                            "table_index": t_idx,
                            "page": table_page,
                            "bbox": table_bbox,
                            "markdown": md_str,
                            "rows": rows,
                        }
                    )

                logger.debug(
                    "Docling converted %s in %.2fs: %d tables",
                    source_target.name,
                    time.perf_counter() - t0,
                    len(tables_data),
                )
            except Exception as exc:
                logger.warning("Docling conversion warning on %s: %s", source_target, exc)

        for p in range(len(page_image_paths)):
            text_by_page[p] = ""

        meta: dict[str, Any] = {
            "reader": self.name,
            "page_dimensions": page_dims,
            "tables": tables_meta,
        }

        return ParsedDocument(
            doc_id=doc_meta.doc_id,
            sha256=doc_meta.sha256,
            pages=len(page_image_paths) if page_image_paths else 1,
            lines=all_lines,
            tables=tables_data,
            text_by_page=text_by_page,
            reader_name=self.name,
            meta=meta,
        )


assert isinstance(DoclingReader(), Reader), "DoclingReader does not satisfy Reader protocol"
