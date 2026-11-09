#!/usr/bin/env python3
"""Sequence-level distillation: fine-tune pythia-70m to imitate the teacher's replies.

    python training/train.py                     # reads training/config.yaml only
    python training/train.py --subset 50         # make train SUBSET=50
    python training/train.py --train-file datasets/v1/train.jsonl --local

Each example is the same prompt shape the service uses at inference time:

    Command: what is the weather in london
    JSON: {"intent": "weather_query", "date": null, "time": null, "place": "london"}

The loss is computed on the reply only; the prompt tokens are masked with -100.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from pathlib import Path

import torch
import yaml
from torch.optim import AdamW
from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "worker"))
import s3util


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_records(config: dict, subset: int, local: bool, train_file: str | None) -> list[dict]:
    limit = subset or config["train_limit"]
    rows: list[dict] = []
    if local or train_file:
        blob = Path(train_file or REPO / "datasets/v1/train.jsonl").read_text(encoding="utf-8")
        lines = [json.loads(line) for line in blob.splitlines() if line.strip()]
    else:
        s3 = s3util.client()
        key = config["train_uri"].split("/", 3)[3] if config["train_uri"].count("/") > 3 else "v1/train.jsonl"
        lines = list(s3util.read_jsonl(s3, s3util.DATASETS, key))
    for row in lines:
        rows.append(row)
        if len(rows) >= limit:
            break
    if not rows:
        raise SystemExit("no training records found")
    return rows


def template(record: dict) -> str:
    return f"Command: {record['text']}\nJSON: {record['teacher_raw']}"


def encode(record: dict, tok, max_len: int) -> dict:
    prompt = f"Command: {record['text']}\nJSON: "
    reply = record["teacher_raw"]
    prompt_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    reply_ids = tok(reply + tok.eos_token, add_special_tokens=False)["input_ids"]
    ids = (prompt_ids + reply_ids)[:max_len]
    labels = ([-100] * len(prompt_ids) + reply_ids)[:max_len]
    return {"input_ids": ids, "labels": labels}


def collate(batch: list[dict], pad_id: int, max_len: int) -> dict:
    width = min(max(len(item["input_ids"]) for item in batch), max_len)
    input_ids, labels, mask = [], [], []
    for item in batch:
        ids, lab = item["input_ids"][:width], item["labels"][:width]
        pad = width - len(ids)
        input_ids.append(ids + [pad_id] * pad)
        labels.append(lab + [-100] * pad)
        mask.append([1] * len(ids) + [0] * pad)
    return {
        "input_ids": torch.tensor(input_ids, dtype=torch.long),
        "attention_mask": torch.tensor(mask, dtype=torch.long),
        "labels": torch.tensor(labels, dtype=torch.long),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(REPO / "training" / "config.yaml"))
    parser.add_argument("--subset", type=int, default=int(os.environ.get("SUBSET", "0")))
    parser.add_argument("--train-file", default=None)
    parser.add_argument("--local", action="store_true", help="read the training file from disk, not S3")
    parser.add_argument("--version", default=None, help="override model_version")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    version = args.version or config["model_version"]
    seed = int(config["seed"])
    set_seed(seed)
    random.seed(seed)
    torch.manual_seed(seed)

    records = load_records(config, args.subset, args.local, args.train_file)
    print(f"training on {len(records)} records -> models/{version}")

    tok = AutoTokenizer.from_pretrained(config["base_model"])
    tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(config["base_model"])
    model.train()

    max_len = int(config["max_seq_len"])
    data = [encode(r, tok, max_len) for r in records]

    optim = AdamW(model.parameters(), lr=float(config["learning_rate"]))
    batch_size = int(config["batch_size"])
    generator = random.Random(seed)

    loss_path = REPO / "training" / "loss.csv"
    losses: list[tuple[int, float, int]] = []
    for epoch in range(1, int(config["epochs"]) + 1):
        order = list(range(len(data)))
        generator.shuffle(order)
        running, seen = 0.0, 0
        for start in range(0, len(order), batch_size):
            chunk = [data[i] for i in order[start : start + batch_size]]
            batch = collate(chunk, tok.pad_token_id, max_len)
            out = model(**batch)
            out.loss.backward()
            optim.step()
            optim.zero_grad(set_to_none=True)
            running += out.loss.item() * len(chunk)
            seen += len(chunk)
            print(f"  epoch {epoch} step {start // batch_size + 1}: loss {out.loss.item():.4f}", flush=True)
        epoch_loss = running / max(seen, 1)
        losses.append((epoch, epoch_loss, seen))
        print(f"epoch {epoch}: mean loss {epoch_loss:.4f}", flush=True)

    with loss_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["epoch", "loss"])
        for epoch, loss, _ in losses:
            writer.writerow([epoch, f"{loss:.6f}"])

    out_dir = REPO / config["output_dir"] / version
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    (out_dir / "training_meta.json").write_text(
        json.dumps(
            {
                "base_model": config["base_model"],
                "records": len(records),
                "epochs": config["epochs"],
                "batch_size": batch_size,
                "learning_rate": config["learning_rate"],
                "max_seq_len": max_len,
                "seed": seed,
                "library_versions": config["library_versions"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"saved model and tokenizer to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
