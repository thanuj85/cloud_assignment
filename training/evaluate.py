#!/usr/bin/env python3
"""Produce predictions.jsonl for score.py from any of the three models.

    python training/evaluate.py --model student  --version v1
    python training/evaluate.py --model base     --name pythia-70m
    python training/evaluate.py --model teacher  --name teacher

Writes results/<name>_predictions.jsonl, which tools/score.py then turns into
results/<name>_validation.json.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VALIDATION = REPO / "data" / "validation.jsonl"
PROMPT = REPO / "prompts" / "teacher_prompt.txt"


def read_validation() -> list[dict]:
    return [json.loads(line) for line in VALIDATION.read_text(encoding="utf-8").splitlines() if line.strip()]


def student_predictions(version: str, max_new_tokens: int) -> dict[str, str]:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_dir = REPO / "training" / "out" / version
    tok = AutoTokenizer.from_pretrained(model_dir)
    tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_dir).eval()

    predictions: dict[str, str] = {}
    for row in read_validation():
        prompt = f"Command: {row['text']}\nJSON: "
        inputs = tok(prompt, return_tensors="pt")
        with torch.no_grad():
            ids = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tok.pad_token_id,
                eos_token_id=tok.eos_token_id,
            )
        reply = tok.decode(ids[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)
        predictions[row["id"]] = reply.strip()
    return predictions


def base_predictions(max_new_tokens: int) -> dict[str, str]:
    # The untrained base model is loaded exactly like the student, from the hub.
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    name = "EleutherAI/pythia-70m"
    tok = AutoTokenizer.from_pretrained(name)
    tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(name).eval()
    predictions: dict[str, str] = {}
    for row in read_validation():
        prompt = f"Command: {row['text']}\nJSON: "
        inputs = tok(prompt, return_tensors="pt")
        with torch.no_grad():
            ids = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tok.pad_token_id,
                eos_token_id=tok.eos_token_id,
            )
        predictions[row["id"]] = tok.decode(ids[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True).strip()
    return predictions


def teacher_predictions(max_new_tokens: int) -> dict[str, str]:
    import requests

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    template = PROMPT.read_text(encoding="utf-8")
    predictions: dict[str, str] = {}
    for row in read_validation():
        prompt = template.replace("{command}", row["text"])
        payload = {
            "model": os.environ.get("TEACHER_MODEL", "phi3.5"),
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "seed": 42, "num_predict": max_new_tokens},
        }
        response = requests.post(f"{host}/api/generate", json=payload, timeout=300)
        response.raise_for_status()
        predictions[row["id"]] = response.json()["response"].strip()
    return predictions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("student", "base", "teacher"), required=True)
    parser.add_argument("--version", default="v1", help="student model version")
    parser.add_argument("--name", default=None, help="output name, defaults to the model kind")
    parser.add_argument("--max-new-tokens", type=int, default=64)
    args = parser.parse_args()

    if args.model == "student":
        predictions = student_predictions(args.version, args.max_new_tokens)
        name = args.name or f"student_{args.version}"
    elif args.model == "base":
        predictions = base_predictions(args.max_new_tokens)
        name = args.name or "base_pythia70m"
    else:
        predictions = teacher_predictions(args.max_new_tokens)
        name = args.name or "teacher"

    out = REPO / "results" / f"{name}_predictions.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in read_validation():
            handle.write(json.dumps({"id": row["id"], "prediction": predictions[row["id"]]}) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
