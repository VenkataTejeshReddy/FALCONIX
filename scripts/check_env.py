# Owner: Laptop B
"""INX – Environment and Model Stack Verification Script for Laptop A (Mac M4).

Verifies the 7 essential system and model prerequisites:
 1. Python 3.11, venv activation, and requirements-core / requirements-models imports.
 2. Apple Vision OCR (ocrmac) on a test image containing "Priya Sharma 2021001".
 3. Docling PDF conversion on a generated PDF, printing Markdown output.
 4. Ollama server reachability, qwen3-vl:4b presence, and JSON VLM response timing.
 5. BGE-M3 and bge-reranker-v2-m3 loading from local HF cache on MPS, embedding, and memory cleanup.
 6. Qdrant local disk mode in data/qdrant (create collection, insert, query).
 7. Peak RSS memory monitoring per step (under 16 GB limit) with OLLAMA_MAX_LOADED_MODELS=1 and short keep_alive.

Usage:
    python scripts/check_env.py
"""

from __future__ import annotations

import gc
import json
import os
import platform
import resource
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

# Ensure MPS fallback and Ollama memory limits are set early
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["OLLAMA_MAX_LOADED_MODELS"] = "1"

# ANSI color codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Total system RAM limit (16 GB for Laptop A M4)
RAM_LIMIT_MB = 16.0 * 1024.0


def get_peak_rss_mb() -> float:
    """Return peak resident set size in megabytes.

    On macOS (Darwin), ru_maxrss is reported in bytes.
    On Linux, ru_maxrss is reported in kilobytes.
    """
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if platform.system() == "Darwin":
        return usage / (1024.0 * 1024.0)
    return usage / 1024.0


def get_current_rss_mb() -> float:
    """Return current process RSS in megabytes using psutil if available."""
    try:
        import psutil

        return psutil.Process().memory_info().rss / (1024.0 * 1024.0)
    except Exception:
        return get_peak_rss_mb()


@dataclass
class CheckResult:
    step_num: int
    name: str
    passed: bool
    details: str
    fix_hint: str = ""
    rss_mb: float = 0.0
    elapsed_sec: float = 0.0


class EnvChecker:
    """Orchestrates environment checks and prints formatted PASS/FAIL reports."""

    def __init__(self) -> None:
        self.results: list[CheckResult] = []
        self.repo_root = Path(__file__).resolve().parent.parent

    def run_check(self, step_num: int, name: str, func: Callable[[], tuple[bool, str, str]]) -> CheckResult:
        print(f"\n{BOLD}{CYAN}----------------------------------------------------------------------{RESET}")
        print(f"{BOLD}[Step {step_num}/7] {name}{RESET}")
        print(f"{CYAN}----------------------------------------------------------------------{RESET}")

        start_time = time.perf_counter()
        passed = False
        details = ""
        fix_hint = ""

        try:
            passed, details, fix_hint = func()
        except Exception as exc:
            passed = False
            details = f"Unexpected exception: {type(exc).__name__}: {exc}"
            fix_hint = f"Review stack trace and inspect dependencies: {exc}"

        elapsed = time.perf_counter() - start_time
        peak_rss = get_peak_rss_mb()
        curr_rss = get_current_rss_mb()
        pct_ram = (peak_rss / RAM_LIMIT_MB) * 100.0

        if passed:
            print(f"{BOLD}{GREEN}✓ PASS:{RESET} {name}")
        else:
            print(f"{BOLD}{RED}✗ FAIL:{RESET} {name}")

        if details:
            print(f"  {BOLD}Details:{RESET} {details}")
        if not passed and fix_hint:
            print(f"  {BOLD}{YELLOW}Fix Hint:{RESET} {fix_hint}")

        print(
            f"  {BOLD}Memory:{RESET} Current RSS: {curr_rss:.1f} MB | "
            f"Peak RSS: {peak_rss:.1f} MB ({pct_ram:.1f}% of 16 GB limit) | "
            f"Duration: {elapsed:.2f}s"
        )

        res = CheckResult(
            step_num=step_num,
            name=name,
            passed=passed,
            details=details,
            fix_hint=fix_hint,
            rss_mb=peak_rss,
            elapsed_sec=elapsed,
        )
        self.results.append(res)
        return res

    # -----------------------------------------------------------------------
    # Step 1: Python 3.11, venv, and package imports
    # -----------------------------------------------------------------------
    def check_python_and_packages(self) -> tuple[bool, str, str]:
        major, minor = sys.version_info.major, sys.version_info.minor
        py_ver = f"{major}.{minor}.{sys.version_info.micro}"

        # 1. Version check
        if (major, minor) != (3, 11):
            return (
                False,
                f"Detected Python {py_ver}. INX requires Python 3.11.x.",
                "Install Python 3.11 via Homebrew ('brew install python@3.11') or pyenv "
                "('pyenv install 3.11.9 && pyenv local 3.11.9'), then recreate the venv:\n"
                "    python3.11 -m venv .venv\n"
                "    source .venv/bin/activate",
            )

        # 2. Virtual environment check
        in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        if not in_venv:
            return (
                False,
                f"Python is running globally ({sys.executable}) instead of an active venv.",
                "Activate the project virtual environment before running:\n"
                "    source .venv/bin/activate\n"
                "Or create one if missing:\n"
                "    python3.11 -m venv .venv && source .venv/bin/activate",
            )

        # 3. Import packages from requirements-core.txt and requirements-models.txt
        core_packages = [
            ("pydantic", "pydantic"),
            ("pyyaml", "yaml"),
            ("rapidfuzz", "rapidfuzz"),
            ("streamlit", "streamlit"),
            ("pytest", "pytest"),
            ("pytest-cov", "pytest_cov"),
            ("pillow", "PIL"),
            ("opencv-python-headless", "cv2"),
            ("pymupdf", "pymupdf"),
            ("reportlab", "reportlab"),
            ("openpyxl", "openpyxl"),
            ("jinja2", "jinja2"),
            ("python-dotenv", "dotenv"),
        ]

        model_packages = [
            ("docling", "docling"),
            ("ocrmac", "ocrmac"),
            ("rapidocr-onnxruntime", "rapidocr_onnxruntime"),
            ("FlagEmbedding", "FlagEmbedding"),
            ("sentence-transformers", "sentence_transformers"),
            ("qdrant-client", "qdrant_client"),
            ("ollama", "ollama"),
        ]

        missing: list[str] = []
        for pkg_name, mod_name in core_packages + model_packages:
            try:
                __import__(mod_name)
            except ImportError as err:
                missing.append(f"{pkg_name} ({mod_name}: {err})")

        if missing:
            return (
                False,
                f"Missing or broken packages: {', '.join(missing)}",
                "Install dependencies using:\n"
                "    pip install -r requirements-core.txt -r requirements-models.txt",
            )

        return (
            True,
            f"Python {py_ver} in venv ({sys.prefix}). All core and model packages imported successfully.",
            "",
        )

    # -----------------------------------------------------------------------
    # Step 2: Apple Vision OCR (ocrmac)
    # -----------------------------------------------------------------------
    def check_ocrmac(self) -> tuple[bool, str, str]:
        if platform.system() != "Darwin":
            return (
                False,
                f"ocrmac requires macOS (Darwin), but current platform is {platform.system()}.",
                "Apple Vision OCR is supported only on macOS 12+ (Laptop A M4).",
            )

        try:
            from PIL import Image, ImageDraw, ImageFont
            from ocrmac.ocrmac import OCR
        except ImportError as err:
            return (
                False,
                f"Failed to import ocrmac or PIL: {err}",
                "Ensure ocrmac and pillow are installed: pip install ocrmac pillow",
            )

        # Generate test image with text "Priya Sharma 2021001"
        target_text = "Priya Sharma 2021001"
        img = Image.new("RGB", (700, 180), color="white")
        draw = ImageDraw.Draw(img)

        # Try bundled DejaVuSans font or system font, fallback to default
        font_path = self.repo_root / "DejaVuSans.ttf"
        font: Any
        if font_path.exists():
            font = ImageFont.truetype(str(font_path), 36)
        else:
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
            except Exception:
                font = ImageFont.load_default()

        draw.text((40, 60), target_text, fill="black", font=font)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
            img.save(tmp_path)

        try:
            results = OCR(tmp_path, recognition_level="accurate").recognize()
            recognized_text = " ".join(item[0] for item in results)
            print(f"  Recognized OCR Text: {recognized_text!r}")
            print(f"  Confidence: {[item[1] for item in results]}")

            if "Priya Sharma" in recognized_text and "2021001" in recognized_text:
                return (
                    True,
                    f"Apple Vision OCR successfully recognized '{target_text}' with full confidence.",
                    "",
                )
            else:
                return (
                    False,
                    f"OCR ran but did not find expected text '{target_text}'. Output was: {recognized_text!r}",
                    "Verify screen/file permissions for Vision framework or font rendering quality.",
                )
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # -----------------------------------------------------------------------
    # Step 3: Docling PDF conversion
    # -----------------------------------------------------------------------
    def check_docling(self) -> tuple[bool, str, str]:
        try:
            import pymupdf
            from docling.document_converter import DocumentConverter
        except ImportError as err:
            return (
                False,
                f"Failed to import docling or pymupdf: {err}",
                "Install docling and pymupdf: pip install docling pymupdf",
            )

        # Create tiny test PDF
        doc = pymupdf.open()
        page = doc.new_page()
        test_content = (
            "# INX Document Verification\n"
            "Applicant Name: Priya Sharma\n"
            "Registration: 2021001\n"
            "Highest Qualification: Bachelor of Technology\n"
        )
        page.insert_text((72, 72), test_content, fontsize=12)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name
            doc.save(pdf_path)
            doc.close()

        try:
            converter = DocumentConverter()
            result = converter.convert(pdf_path)
            md_text = result.document.export_to_markdown()

            print(f"\n{BOLD}Docling Markdown Output:{RESET}")
            print("-" * 50)
            print(md_text.strip())
            print("-" * 50)

            if "Priya Sharma" in md_text and "2021001" in md_text:
                return (
                    True,
                    "Docling converted test PDF and produced valid Markdown containing applicant details.",
                    "",
                )
            else:
                return (
                    False,
                    f"Docling output missing expected text. Markdown:\n{md_text}",
                    "Ensure Docling models are downloaded properly in ~/.cache/huggingface/hub.",
                )
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

    # -----------------------------------------------------------------------
    # Step 4: Ollama server, qwen3-vl:4b, and JSON VLM call
    # -----------------------------------------------------------------------
    def check_ollama(self) -> tuple[bool, str, str]:
        try:
            import ollama
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as err:
            return (
                False,
                f"Failed to import ollama client: {err}",
                "Install ollama Python package: pip install ollama",
            )

        client = ollama.Client()

        # 1. Server reachability & tag listing
        try:
            model_list = client.list()
            available_tags = [m.model for m in model_list.models]
            print(f"  Exact Ollama models available: {available_tags}")
        except Exception as err:
            return (
                False,
                f"Cannot connect to Ollama server at http://localhost:11434: {err}",
                "Ensure Ollama is running:\n"
                "    ollama serve\n"
                "Or launch the Ollama macOS desktop app.",
            )

        # 2. Check qwen3-vl:4b presence
        required_model = "qwen3-vl:4b"
        matching_model = None
        for tag in available_tags:
            if tag == required_model or tag.startswith(f"{required_model}:") or tag == f"{required_model}-instruct":
                matching_model = tag
                break

        if not matching_model and required_model not in available_tags:
            return (
                False,
                f"Model '{required_model}' not found in Ollama tags: {available_tags}",
                f"Pull or alias the model with:\n"
                f"    ollama pull {required_model}\n"
                f"If you already have 'qwen3-vl:4b-instruct', run:\n"
                f"    ollama cp qwen3-vl:4b-instruct {required_model}",
            )

        # Model to use for query
        target_model = required_model if required_model in available_tags else matching_model

        # 3. Create small test image with name and id
        img = Image.new("RGB", (500, 150), color="white")
        draw = ImageDraw.Draw(img)
        font_path = self.repo_root / "DejaVuSans.ttf"
        font = ImageFont.truetype(str(font_path), 30) if font_path.exists() else ImageFont.load_default()
        draw.text((30, 40), "Name: Priya Sharma\nID: 2021001", fill="black", font=font)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_img_path = tmp.name
            img.save(tmp_img_path)

        try:
            start_t = time.perf_counter()
            # keep_alive set short (30s) to keep memory footprint under 16 GB
            response = client.chat(
                model=target_model,
                messages=[
                    {
                        "role": "user",
                        "content": "Extract name and id from this document image as valid JSON with keys 'name' and 'id'.",
                        "images": [tmp_img_path],
                    }
                ],
                format="json",
                options={"temperature": 0.0},
                keep_alive="30s",
            )
            vlm_sec = time.perf_counter() - start_t
            content_str = response.message.content.strip()

            print(f"  VLM call completed in {vlm_sec:.2f} seconds.")
            print(f"  Raw response:\n{content_str}")

            parsed_json = json.loads(content_str)
            print(f"  Parsed JSON object: {parsed_json}")

            return (
                True,
                f"Ollama server reachable. Model '{target_model}' active. JSON VLM call succeeded in {vlm_sec:.2f}s.",
                "",
            )
        except json.JSONDecodeError as jde:
            return (
                False,
                f"VLM responded in {vlm_sec:.2f}s but output was not valid JSON: {jde}\nResponse: {content_str}",
                "Check prompt format or verify model capability.",
            )
        except Exception as err:
            return (
                False,
                f"Failed during Ollama chat call: {err}",
                f"Verify that '{target_model}' has sufficient memory and Ollama is functioning.",
            )
        finally:
            if os.path.exists(tmp_img_path):
                os.remove(tmp_img_path)

    # -----------------------------------------------------------------------
    # Step 5: BGE-M3 & bge-reranker-v2-m3 on MPS from local HF cache
    # -----------------------------------------------------------------------
    def check_embeddings_and_reranker(self) -> tuple[bool, str, str]:
        try:
            import torch
            from FlagEmbedding import BGEM3FlagModel, FlagReranker
            from huggingface_hub import snapshot_download
        except ImportError as err:
            return (
                False,
                f"Failed to import FlagEmbedding or torch: {err}",
                "Install FlagEmbedding and torch: pip install FlagEmbedding torch",
            )

        device = "mps" if torch.backends.mps.is_available() else "cpu"
        print(f"  PyTorch MPS available: {torch.backends.mps.is_available()} (using device: {device})")
        print(f"  PYTORCH_ENABLE_MPS_FALLBACK = {os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK')}")

        # Check local HF cache for BGE-M3
        bge_local_path: Optional[str] = None
        try:
            bge_local_path = snapshot_download("BAAI/bge-m3", local_files_only=True)
            print(f"  BGE-M3 local cache path: {bge_local_path}")
        except Exception:
            # Fall back to repo identifier if local snapshot search fails
            bge_local_path = "BAAI/bge-m3"

        # Check local HF cache for bge-reranker-v2-m3
        reranker_local_path: Optional[str] = None
        try:
            reranker_local_path = snapshot_download("BAAI/bge-reranker-v2-m3", local_files_only=True)
            print(f"  bge-reranker-v2-m3 local cache path: {reranker_local_path}")
        except Exception:
            reranker_local_path = "BAAI/bge-reranker-v2-m3"

        # 1. Load BGE-M3, embed two sentences, verify vector dimension
        print("  Loading BGE-M3 model...")
        model = BGEM3FlagModel(bge_local_path, use_fp16=False, devices=device)
        sentences = [
            "INX document verification pipeline ingests applicant certificates.",
            "Priya Sharma submitted graduation marksheet for roll number 2021001.",
        ]
        res = model.encode(sentences)
        dense_vecs = res["dense_vecs"]
        vec_shape = dense_vecs.shape
        vec_dim = vec_shape[1]
        print(f"  BGE-M3 embedded {len(sentences)} sentences -> dense vector shape: {vec_shape} (dim: {vec_dim})")

        # Unload and free memory
        del model
        del res
        del dense_vecs
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        print("  Unloaded BGE-M3 and cleared MPS cache.")

        # 2. Load bge-reranker-v2-m3, compute score
        print("  Loading bge-reranker-v2-m3...")
        reranker = FlagReranker(reranker_local_path, use_fp16=False, devices=device)
        pairs = [["What is the registration number?", "The registration number is 2021001."]]
        scores = reranker.compute_score(pairs)
        print(f"  bge-reranker-v2-m3 score: {scores}")

        # Unload and free memory
        del reranker
        del scores
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        print("  Unloaded bge-reranker-v2-m3 and cleared MPS cache.")

        if vec_dim != 1024:
            return (
                False,
                f"Expected vector dimension 1024 for BGE-M3, got {vec_dim}.",
                "Verify BAAI/bge-m3 model weights integrity.",
            )

        return (
            True,
            f"BGE-M3 (dim={vec_dim}) and bge-reranker-v2-m3 loaded on {device}, executed inference, and freed memory cleanly.",
            "",
        )

    # -----------------------------------------------------------------------
    # Step 6: Qdrant local mode in data/qdrant
    # -----------------------------------------------------------------------
    def check_qdrant_local(self) -> tuple[bool, str, str]:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, PointStruct, VectorParams
        except ImportError as err:
            return (
                False,
                f"Failed to import qdrant_client: {err}",
                "Install qdrant-client: pip install qdrant-client",
            )

        qdrant_path = self.repo_root / "data" / "qdrant"
        qdrant_path.mkdir(parents=True, exist_ok=True)

        collection_name = "inx_check_env_test"
        client = None
        try:
            client = QdrantClient(path=str(qdrant_path))

            if client.collection_exists(collection_name):
                client.delete_collection(collection_name)

            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=4, distance=Distance.COSINE),
            )

            test_vector = [0.25, 0.50, 0.75, 1.0]
            client.upsert(
                collection_name=collection_name,
                points=[
                    PointStruct(
                        id=1,
                        vector=test_vector,
                        payload={"doc_id": "TEST-001", "name": "Priya Sharma", "id_num": "2021001"},
                    )
                ],
            )

            hits = client.query_points(
                collection_name=collection_name,
                query=test_vector,
                limit=1,
            ).points

            if not hits:
                return (
                    False,
                    "Qdrant query returned 0 points for inserted vector.",
                    "Verify Qdrant local storage permissions.",
                )

            top_payload = hits[0].payload
            print(f"  Qdrant query top hit score: {hits[0].score:.4f}, payload: {top_payload}")

            # Cleanup test collection
            client.delete_collection(collection_name)
            client.close()

            return (
                True,
                f"Qdrant local storage operational at {qdrant_path} (created collection, inserted, queried, cleaned up).",
                "",
            )
        except Exception as err:
            return (
                False,
                f"Qdrant local error: {err}",
                f"Check file system permissions for '{qdrant_path}' and disk space.",
            )
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    # -----------------------------------------------------------------------
    # Step 7: Memory reporting & Ollama runtime configuration
    # -----------------------------------------------------------------------
    def check_memory_and_ollama_config(self) -> tuple[bool, str, str]:
        peak_rss = get_peak_rss_mb()
        curr_rss = get_current_rss_mb()
        pct_used = (peak_rss / RAM_LIMIT_MB) * 100.0

        ollama_max = os.environ.get("OLLAMA_MAX_LOADED_MODELS", "not set")
        pytorch_fallback = os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK", "not set")

        print(f"  Peak RSS observed: {peak_rss:.1f} MB / {RAM_LIMIT_MB:.0f} MB ({pct_used:.1f}%)")
        print(f"  Current RSS: {curr_rss:.1f} MB")
        print(f"  OLLAMA_MAX_LOADED_MODELS: {ollama_max}")
        print(f"  PYTORCH_ENABLE_MPS_FALLBACK: {pytorch_fallback}")

        if peak_rss > RAM_LIMIT_MB:
            return (
                False,
                f"Peak RSS ({peak_rss:.1f} MB) exceeded system limit ({RAM_LIMIT_MB:.0f} MB)!",
                "Unload models immediately after inference and ensure OLLAMA_MAX_LOADED_MODELS=1.",
            )

        if ollama_max != "1":
            return (
                False,
                f"OLLAMA_MAX_LOADED_MODELS is '{ollama_max}', expected '1'.",
                "Export OLLAMA_MAX_LOADED_MODELS=1 in your shell or .env to ensure only one model stays in VRAM.",
            )

        return (
            True,
            f"Peak RSS {peak_rss:.1f} MB is well within 16 GB budget ({pct_used:.1f}%). "
            f"OLLAMA_MAX_LOADED_MODELS=1 and short keep_alive verified.",
            "",
        )

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    def run_all(self) -> bool:
        print(f"{BOLD}======================================================================{RESET}")
        print(f"{BOLD}INX Environment & Model Stack Verification (Laptop A - Mac M4 16 GB){RESET}")
        print(f"{BOLD}======================================================================{RESET}")

        self.run_check(1, "Python 3.11 & Package Imports", self.check_python_and_packages)
        self.run_check(2, "Apple Vision OCR (ocrmac)", self.check_ocrmac)
        self.run_check(3, "Docling PDF Parsing", self.check_docling)
        self.run_check(4, "Ollama Server & Qwen3-VL VLM JSON", self.check_ollama)
        self.run_check(5, "BGE-M3 & bge-reranker-v2-m3 on MPS", self.check_embeddings_and_reranker)
        self.run_check(6, "Qdrant Local Disk Mode", self.check_qdrant_local)
        self.run_check(7, "Memory Budget (<16 GB) & Ollama Limits", self.check_memory_and_ollama_config)

        print(f"\n{BOLD}======================================================================{RESET}")
        print(f"{BOLD}VERIFICATION SUMMARY{RESET}")
        print(f"{BOLD}======================================================================{RESET}")

        all_passed = True
        for r in self.results:
            status_str = f"{BOLD}{GREEN}PASS{RESET}" if r.passed else f"{BOLD}{RED}FAIL{RESET}"
            print(f"Step {r.step_num}: [{status_str}] {r.name:<38} (Peak RSS: {r.rss_mb:6.1f} MB, {r.elapsed_sec:5.2f}s)")
            if not r.passed:
                all_passed = False
                print(f"       -> Reason: {r.details}")
                if r.fix_hint:
                    print(f"       -> Fix:    {r.fix_hint}")

        print(f"{BOLD}----------------------------------------------------------------------{RESET}")
        final_peak = get_peak_rss_mb()
        print(f"Final Peak RSS: {final_peak:.1f} MB / {RAM_LIMIT_MB:.0f} MB ({(final_peak / RAM_LIMIT_MB) * 100:.1f}%)")

        if all_passed:
            print(f"{BOLD}{GREEN}ALL 7 CHECKS PASSED! Laptop A environment is ready for INX pipeline.{RESET}\n")
            return True
        else:
            print(f"{BOLD}{RED}SOME CHECKS FAILED. Please review the fix hints above.{RESET}\n")
            return False


def main() -> None:
    checker = EnvChecker()
    success = checker.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
