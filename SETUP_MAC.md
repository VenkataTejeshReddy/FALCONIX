# INX – macOS (M4, 16 GB RAM) Setup Guide (Laptop A)

> **Hardware Target:** Apple Silicon Mac (M4 / M-series, 16 GB Unified Memory)  
> **Role:** Laptop A — owns `parse/`, `classify/` (model layers), `extract/`, `index/`  
> **Stack:** Python 3.11, Apple Vision OCR (`ocrmac`), Docling, Ollama (`qwen3-vl:4b-instruct`), `sentence-transformers` (BGE-M3 + `bge-reranker-v2-m3`), `rank-bm25`, Qdrant local.

This document lists the exact installation commands in order to prepare Laptop A for running the fully local INX pipeline without cloud APIs or secret credentials.

---

## 1. System Prerequisites (Homebrew)

Install Python 3.11, Ollama, and system development tools:

```bash
# Ensure Homebrew is installed and up-to-date
brew update

# Install Python 3.11 (if not already installed)
brew install python@3.11

# Install Ollama (local LLM/VLM runner)
brew install ollama

# Verify Python 3.11 is accessible
python3.11 --version
```

---

## 2. Repository & Dedicated `.venv` Setup

The single project environment is the repository `.venv` at `FALCONIX/.venv`:

```bash
# Navigate to the workspace directory
cd /path/to/FALCONIX

# Create virtual environment using Python 3.11
python3.11 -m venv .venv

# Activate the repo .venv
source .venv/bin/activate

# Upgrade pip, wheel, and setuptools
pip install --upgrade pip setuptools wheel
```

---

## 3. Python Package Dependencies

Install core requirements and Laptop A model-layer requirements into the active `.venv`:

```bash
# Install core pipeline dependencies and model stack
pip install -r requirements-core.txt -r requirements-models.txt
```

### Key Libraries Installed:
- **Core:** `pydantic`, `pyyaml`, `rapidfuzz`, `streamlit`, `pymupdf` (fitz), `reportlab`, `openpyxl`, `jinja2`, `python-dotenv`.
- **Laptop A Models:** `docling`, `ocrmac` (macOS Apple Vision OCR), `sentence-transformers` (BGE-M3 + reranker), `rank-bm25` (lexical hybrid retrieval), `qdrant-client`, `ollama`.

---

## 4. Ollama Configuration & Model Pull (Qwen3-VL-4B Instruct)

To keep RAM usage well under 16 GB, configure Ollama to load at most one model at a time and use a short keep-alive.

### 4.1 Configuring the Ollama macOS Desktop App via `launchctl`
For the Ollama macOS GUI application, system-level environment variables must be passed through `launchctl setenv`:

```bash
# Set max loaded models to 1 (avoids loading multiple VLMs into VRAM simultaneously)
launchctl setenv OLLAMA_MAX_LOADED_MODELS "1"

# Set keep-alive to 30s so idle models unload automatically
launchctl setenv OLLAMA_KEEP_ALIVE "30s"

# Restart the Ollama macOS application to apply settings
killall Ollama || true
open -a Ollama
```

### 4.2 Terminal / CLI Environment Variables
Also add these to your shell profile (`~/.zshrc`) or project `.env`:

```bash
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_KEEP_ALIVE=30s
export PYTORCH_ENABLE_MPS_FALLBACK=1
export VLM_MODEL=qwen3-vl:4b-instruct
```

### 4.3 Pull Qwen3-VL-4B Instruct
```bash
# Pull the instruct model directly
ollama pull qwen3-vl:4b-instruct

# Verify available models in Ollama
ollama list
```

---

## 5. Hugging Face Model Snapshot Downloads

Pre-download the embedding and reranker models to the local HuggingFace cache (`~/.cache/huggingface/hub`) so `sentence-transformers` loads them offline without runtime download delays:

```bash
# Download BAAI/bge-m3 (ignore onnx to save ~2.5 GB bandwidth) and BAAI/bge-reranker-v2-m3
python -c "
from huggingface_hub import snapshot_download
print('Downloading BAAI/bge-m3...')
snapshot_download('BAAI/bge-m3', ignore_patterns=['*.onnx*', 'onnx/*'])
print('Downloading BAAI/bge-reranker-v2-m3...')
snapshot_download('BAAI/bge-reranker-v2-m3')
print('Hugging Face model snapshots ready!')
"
```

---

## 6. Configure Runtime Environment (`.env`)

Copy `.env.example` and populate local paths:

```bash
cp .env.example .env
```

Key environment settings in `.env`:
```ini
INX_DATA_DIR=data/
INX_FIXTURES_DIR=fixtures/
INX_AUDIT_DB=data/audit.db

# Qdrant local embedded disk storage
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=inx_docs

# Ollama local VLM
OLLAMA_BASE_URL=http://localhost:11434
VLM_MODEL=qwen3-vl:4b-instruct
OLLAMA_MODEL=qwen3-vl:4b-instruct
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_KEEP_ALIVE=30s

# PyTorch MPS Fallback for Apple Silicon
PYTORCH_ENABLE_MPS_FALLBACK=1
```

---

## 7. Verify the Complete Stack

Run the environment check script from the repository root using the repo `.venv`:

```bash
source .venv/bin/activate
python scripts/check_env.py
```

### What `scripts/check_env.py` Validates:
1. **Python 3.11 & repo `.venv`:** Confirms Python 3.11.x, venv active, and imports for all packages in `requirements-core.txt` and `requirements-models.txt` (including `sentence-transformers` and `rank-bm25`).
2. **ocrmac (Apple Vision OCR):** Renders a synthetic image containing `"Priya Sharma 2021001"` and verifies recognition by macOS Vision framework.
3. **Docling:** Generates a synthetic test PDF, converts it using Docling, and prints the Markdown representation.
4. **Ollama & Qwen3-VL-4B Instruct:** Checks Ollama connectivity (`http://localhost:11434`), runs cold and warm calls on a real marksheet page image from `fixtures/synthetic_docs`, reporting latency, output tokens, tokens/sec, and prints `ollama ps`, memory pressure, and swap usage.
5. **BGE-M3 & bge-reranker-v2-m3:** Loads models via `sentence-transformers` (`SentenceTransformer` and `CrossEncoder`) onto Apple Silicon MPS (`PYTORCH_ENABLE_MPS_FALLBACK=1`), encodes sample sentences (1024-d), tests BM25 lexical search via `rank-bm25`, and frees MPS memory cleanly.
6. **Qdrant local:** Creates a collection at `data/qdrant`, inserts a vector, queries it, validates payload retrieval, and cleans up.
7. **Memory Budget & Limits:** Tracks resident set size (`Memory (Python process only)`) per step to ensure total peak footprint stays under the 16 GB threshold (~1.5 GB observed), verifying `OLLAMA_MAX_LOADED_MODELS=1` and short keep-alives.
8. **Pytest test suite:** Runs `pytest -q` and reports exact numbers of passed/failed tests.
