# Owner: Laptop A
"""Latency and Ollama duration breakdown script."""

import time
import json
import statistics
from pathlib import Path
import ollama

repo_root = Path(__file__).resolve().parent.parent
hard_dir = repo_root / "fixtures" / "synthetic_docs" / "hard"
normal_dir = repo_root / "fixtures" / "synthetic_docs"

client = ollama.Client(host="http://localhost:11434")

test_images = [
    normal_dir / "job_normal_id.jpg",
    normal_dir / "college_normal_id.jpg",
    normal_dir / "college_unclear_stamp_marksheet.jpg",
    hard_dir / "hard_perspective_id.jpg",
    hard_dir / "hard_grainy_id.jpg",
]

print("=" * 80)
print("ITEM 7: LATENCY AND OLLAMA DURATION BREAKDOWN (CACHE OFF)")
print("=" * 80)

records = []

for img_path in test_images:
    if not img_path.exists():
        continue
    
    t0 = time.perf_counter()
    resp = client.chat(
        model="qwen3-vl:4b-instruct",
        messages=[{
            "role": "user",
            "content": "Extract fields: applicant_name, id_number as JSON.",
            "images": [str(img_path)]
        }],
        options={"temperature": 0.0, "num_predict": 128},
    )
    wall_s = time.perf_counter() - t0
    
    r_dict = dict(resp)
    load_ns = r_dict.get("load_duration", 0)
    prompt_eval_ns = r_dict.get("prompt_eval_duration", 0)
    eval_ns = r_dict.get("eval_duration", 0)
    eval_tokens = r_dict.get("eval_count", 0)
    prompt_tokens = r_dict.get("prompt_eval_count", 0)
    
    rec = {
        "image": img_path.name,
        "wall_s": round(wall_s, 3),
        "vlm_calls": 1,
        "output_tokens": eval_tokens,
        "prompt_tokens": prompt_tokens,
        "load_duration_s": round(load_ns / 1e9, 3),
        "prompt_eval_duration_s": round(prompt_eval_ns / 1e9, 3),
        "eval_duration_s": round(eval_ns / 1e9, 3),
        "cache": "MISS (cache off)",
    }
    records.append(rec)
    print(f"Page: {rec['image']:<35} | Wall: {rec['wall_s']:6.2f}s | Load: {rec['load_duration_s']:5.2f}s | PromptEval: {rec['prompt_eval_duration_s']:5.2f}s | Eval: {rec['eval_duration_s']:5.2f}s | Tokens: {rec['output_tokens']:3d} | Cache: {rec['cache']}")

wall_times = [r["wall_s"] for r in records]
prompt_eval_times = [r["prompt_eval_duration_s"] for r in records]
eval_times = [r["eval_duration_s"] for r in records]

print("\n--- SUMMARY METRICS (CACHE OFF) ---")
print(f"Mean Wall Latency:        {statistics.mean(wall_times):.2f} s")
print(f"Median Wall Latency:      {statistics.median(wall_times):.2f} s")
print(f"Mean Prompt Eval Time:    {statistics.mean(prompt_eval_times):.2f} s ({statistics.mean(prompt_eval_times)/statistics.mean(wall_times)*100:.1f}% of total)")
print(f"Mean Generation Eval Time:{statistics.mean(eval_times):.2f} s ({statistics.mean(eval_times)/statistics.mean(wall_times)*100:.1f}% of total)")
