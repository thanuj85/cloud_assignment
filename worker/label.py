#!/usr/bin/env python3
"""Teacher labeller: label one shard of the command pool with phi3.5 via Ollama.

    SHARD_INDEX=0 SHARD_COUNT=4 python worker/label.py

A command at line number L (counting from 0) belongs to shard L % SHARD_COUNT,
so every command is labelled exactly once and the shards are disjoint.

The output object is datasets/teacher/shard-<index>.jsonl, one line per command:

    {"id": "C0001", "text": "...", "teacher_raw": "<exact reply from the teacher>"}

The raw reply is stored verbatim: it is never repaired here. clean.py decides
what is usable. Re-running the worker resumes: commands already present in the
shard object are skipped, so a long labelling run can be restarted safely.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s3util

REPO = Path(__file__).resolve().parents[1]
POOL_KEY = "commands_pool.jsonl"
TEACHER_PREFIX = "teacher/"
MODEL = "phi3.5"
TEMPERATURE = 0.0
SEED = 42
NUM_CTX = 2048
# The teacher sometimes appends an explanation after the JSON. Stopping at the
# first newline keeps the reply to the object itself; whatever still slips
# through is rejected by clean.py, never repaired.
STOP = ["\n"]


def prompt_template() -> str:
    return (REPO / "prompts" / "teacher_prompt.txt").read_text(encoding="utf-8")


def build_prompt(template: str, command: str) -> str:
    if "{command}" in template:
        return template.replace("{command}", command)
    return f"{template.rstrip()}\n\nCommand: {command}\nJSON:\n"


def ask_teacher(host: str, prompt: str, timeout: float = 300.0) -> str:
    """One non-streaming generation with temperature 0 and a fixed seed."""
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": TEMPERATURE, "seed": SEED, "num_ctx": NUM_CTX, "stop": STOP},
    }
    response = requests.post(f"{host.rstrip('/')}/api/generate", json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()["response"]


def select_shard(commands: list[dict], index: int, count: int) -> list[dict]:
    return [cmd for line, cmd in enumerate(commands) if line % count == index]


def label(command: str, template: str, host: str, retries: int = 3) -> str:
    prompt = build_prompt(template, command)
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return ask_teacher(host, prompt)
        except (requests.RequestException, KeyError) as exc:  # transient Ollama failure
            last = exc
            print(f"  attempt {attempt} failed: {exc}", file=sys.stderr)
            time.sleep(2 * attempt)
    raise RuntimeError(f"teacher failed for {command!r}: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-index", type=int, default=int(os.environ.get("SHARD_INDEX", "0")))
    parser.add_argument("--shard-count", type=int, default=int(os.environ.get("SHARD_COUNT", "1")))
    parser.add_argument("--ollama-host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    parser.add_argument("--input", help="local commands_pool.jsonl (offline mode)")
    parser.add_argument("--output", help="local output path (offline mode)")
    parser.add_argument("--limit", type=int, default=0, help="label at most N commands (smoke test)")
    args = parser.parse_args()

    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("need 0 <= SHARD_INDEX < SHARD_COUNT")

    s3 = None
    if args.input:
        commands = [json.loads(line) for line in Path(args.input).read_text().splitlines() if line.strip()]
    else:
        s3 = s3util.client()
        commands = list(s3util.read_jsonl(s3, s3util.DATASETS, POOL_KEY))

    shard = select_shard(commands, args.shard_index, args.shard_count)
    out_key = f"{TEACHER_PREFIX}shard-{args.shard_index}.jsonl"

    # Resume: keep whatever this shard already produced.
    done: set[str] = set()
    rows: list[dict] = []
    if args.output:
        path = Path(args.output)
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    rows.append(row)
                    done.add(row["id"])
    else:
        try:
            for row in s3util.read_jsonl(s3, s3util.DATASETS, out_key):
                rows.append(row)
                done.add(row["id"])
        except ClientError as exc:  # the shard object does not exist yet
            if exc.response.get("Error", {}).get("Code") not in {"NoSuchKey", "404"}:
                raise

    template = prompt_template()
    pending = [cmd for cmd in shard if cmd["id"] not in done]
    if args.limit:
        pending = pending[: args.limit]

    print(
        f"shard {args.shard_index}/{args.shard_count}: {len(shard)} commands, "
        f"{len(done)} done, {len(pending)} to label"
    )

    started = time.time()
    for n, cmd in enumerate(pending, start=1):
        raw = label(cmd["text"], template, args.ollama_host)
        rows.append({"id": cmd["id"], "text": cmd["text"], "teacher_raw": raw})
        if n % 25 == 0 or n == len(pending):
            rate = n / max(time.time() - started, 1e-6)
            print(f"  {n}/{len(pending)} ({rate:.2f}/s)")
            flush(s3, args.output, out_key, rows)

    flush(s3, args.output, out_key, rows)
    print(f"wrote {len(rows)} records -> {args.output or 's3://' + s3util.DATASETS + '/' + out_key}")
    return 0


def flush(s3, output: str | None, out_key: str, rows: list[dict]) -> None:
    """Write the current shard state, ordered by id, to its object."""
    rows.sort(key=lambda r: r["id"])
    if output:
        Path(output).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    else:
        s3util.put_jsonl(s3, s3util.DATASETS, out_key, rows)


if __name__ == "__main__":
    raise SystemExit(main())
