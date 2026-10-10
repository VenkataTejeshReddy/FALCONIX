# INX – macOS (M4, 16 GB RAM) Setup Guide (Laptop A)

> **Hardware Target:** Apple Silicon Mac (M4 / M-series, 16 GB Unified Memory)  
> **Role:** Laptop A — owns `parse/`, `classify/` (model layers), `extract/`, `index/`  
> **Stack:** Python 3.11, Apple Vision OCR (`ocrmac`), Docling, Ollama (`qwen3-vl:4b`), BGE-M3, `bge-reranker-v2-m3`, Qdrant local.

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

# (Optional) Verify Python 3.11 is accessible
python3.11 --version
```

---

## 2. Repository & Virtual Environment Setup

Clone the repository and set up a dedicated Python 3.11 virtual environment:

```bash
# Navigate to the workspace directory
cd /path/to/FALCONIX

# Create virtual environment using Python 3.11
python3.11 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip, wheel, and setuptools
pip install --upgrade pip setuptools wheel
```

---

## 3. Python Package Dependencies

Install both core requirements and Laptop A model-layer requirements:

```bash
# Install core pipeline dependencies and model stack
pip install -r requirements-core.txt -r requirements-models.txt
```

### Key Libraries Installed:
- **Core:** `pydantic`, `pyyaml`, `rapidfuzz`, `streamlit`, `pymupdf` (fitz), `reportlab`, `openpyxl`, `jinja2`, `python-dotenv`.
- **Laptop A Models:** `docling`, `ocrmac` (macOS Apple Vision OCR), `FlagEmbedding` (BGE-M3 + reranker), `sentence-transformers`, `qdrant-client`, `ollama`.

---

## 4. Ollama Configuration & Model Pull (Qwen3-VL-4B)

To keep RAM usage well under 16 GB, configure Ollama to load at most one model at a time and use a short keep-alive:

### 4.1 Set Environment Variables
Add these to your shell profile (`~/.zshrc`) or `.env`:

```bash
export OLLAMA_MAX_LOADED_MODELS=1
export PYTORCH_ENABLE_MPS_FALLBACK=1
```

### 4.2 Start Ollama Service
```bash
# Run in a separate terminal or ensure the Ollama macOS desktop app is open
ollama serve
```

### 4.3 Pull Qwen3-VL-4B
```bash
# Pull the 4B Vision-Language Model
ollama pull qwen3-vl:4b

# If your local tag was downloaded as qwen3-vl:4b-instruct, alias it to qwen3-vl:4b:
ollama cp qwen3-vl:4b-instruct qwen3-vl:4b

# Verify available models and tags
ollama list
```

---

## 5. Hugging Face Model Snapshot Downloads

Pre-download the embedding and reranker models to the local HuggingFace cache (`~/.cache/huggingface/hub`) so they load locally without runtime downloads:

```bash
# Download BAAI/bge-m3 (dense/sparse/colbert embeddings; ignore onnx to save ~2.5 GB bandwidth)
python -c "
from huggingface_hub import snapshot_download
print('Downloading BAAI/bge-m3...')
snapshot_download('BAAI/bge-m3', ignore_patterns=['*.onnx*', 'onnx/*'])
print('Downloading BAAI/bge-reranker-v2-m3...')
snapshot_download('BAAI/bge-reranker-v2-m3')
print('Snapshot downloads complete!')
"
```

Or using `huggingface-cli`:
```bash
huggingface-cli download BAAI/bge-m3 --exclude "onnx/*" "*.onnx*"
huggingface-cli download BAAI/bge-reranker-v2-m3
```

---

## 6. Configure Runtime Environment (`.env`)

Copy `.env.example` and populate local paths:

```bash
cp .env.example .env
```

Ensure your `.env` contains:
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
OLLAMA_MODEL=qwen3-vl:4b
OLLAMA_MAX_LOADED_MODELS=1

# PyTorch MPS Fallback for Apple Silicon
PYTORCH_ENABLE_MPS_FALLBACK=1
```

---

## 7. Verify the Complete Stack

Run the environment check script to verify all 7 checkpoints:

```bash
python scripts/check_env.py
```

### What `scripts/check_env.py` Validates:
1. **Python 3.11 & venv:** Validates Python 3.11.x, venv active, and imports for all packages in `requirements-core.txt` and `requirements-models.txt`.
2. **ocrmac (Apple Vision OCR):** Renders a synthetic image containing `"Priya Sharma 2021001"` and verifies recognition by macOS Vision framework.
3. **Docling:** Generates a synthetic test PDF, converts it using Docling, and prints the Markdown representation.
4. **Ollama & Qwen3-VL-4B:** Checks Ollama connectivity (`http://localhost:11434`), lists available tags, and runs a test image+prompt call returning structured JSON with latency reporting.
5. **BGE-M3 & bge-reranker-v2-m3:** Loads both models from local HF cache onto Apple Silicon MPS (`PYTORCH_ENABLE_MPS_FALLBACK=1`), encodes sample sentences, checks 1024-dim vectors, reranks a pair, and frees memory.
6. **Qdrant local:** Creates a collection at `data/qdrant`, inserts a vector, queries it, validates payload retrieval, and cleans up.
7. **Memory Budget & Limits:** Tracks resident set size (RSS) per step to ensure total peak footprint stays under the 16 GB threshold (~1.2 GB observed), verifying `OLLAMA_MAX_LOADED_MODELS=1` and short keep-alives.

Expected output:
```text
ALL 7 CHECKS PASSED! Laptop A environment is ready for INX pipeline.
```

---

## 8. Common Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| `AttributeError: module 'ocrmac' has no attribute 'OCR'` | Using wrong import syntax | Use `from ocrmac.ocrmac import OCR` |
| `Cannot connect to Ollama server at http://localhost:11434` | Ollama service is stopped | Run `ollama serve` in a terminal or launch Ollama desktop app |
| `Model 'qwen3-vl:4b' not found in Ollama` | Tag mismatch | Run `ollama cp qwen3-vl:4b-instruct qwen3-vl:4b` or `ollama pull qwen3-vl:4b` |
| `MPS backend out of memory` | Models retained in GPU memory | Set `OLLAMA_MAX_LOADED_MODELS=1`, call `del model`, `gc.collect()`, and `torch.mps.empty_cache()` |
| `Detected Python 3.13 / other` | Active environment is not 3.11 | Recreate venv with `python3.11 -m venv .venv` and run `source .venv/bin/activate` |
