#!/usr/bin/env python3
"""Clean the raw teacher shards into the training set.

    python worker/clean.py                     # cluster mode, reads/writes object storage
    python worker/clean.py --local-in DIR --local-out FILE

Reads every datasets/teacher/shard-*.jsonl object, drops the bad records
described in the brief, keeps the survivors in id order, and writes

    datasets/v1/train.jsonl    the cleaned records
    datasets/v1/train.sha256   sha256sum of that file, in `sha256sum` format

Every record is counted under exactly one heading, so that

    input = (a) + (b) + (c) + (d) + duplicates + kept
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s3util

REPO = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((REPO / "data" / "schema.json").read_text(encoding="utf-8"))
KEYS = set(SCHEMA["keys"])
INTENTS = set(SCHEMA["intents"])
SLOTS = ("date", "time", "place")


def slot_is_grounded(value, command: str) -> bool:
    """A slot must be null, or text that really occurs in the command."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return value.strip().lower() in command.lower()


def reject_reason(raw: str, command: str) -> str | None:
    """Return 'a', 'b', 'c' or 'd' for a bad record, or None if it is usable."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "a"
    if not isinstance(obj, dict) or set(obj) != KEYS:
        return "b"
    if obj["intent"] not in INTENTS:
        return "c"
    if not all(slot_is_grounded(obj[slot], command) for slot in SLOTS):
        return "d"
    return None


def clean(rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    counts = {"input": len(rows), "a": 0, "b": 0, "c": 0, "d": 0, "duplicates": 0, "kept": 0}
    survivors: list[dict] = []
    for row in rows:
        reason = reject_reason(row.get("teacher_raw", ""), row.get("text", ""))
        if reason:
            counts[reason] += 1
        else:
            survivors.append(row)

    # (e) duplicate commands: the same text under different ids, keep the smallest id.
    survivors.sort(key=lambda r: r["id"])
    seen: set[str] = set()
    kept: list[dict] = []
    for row in survivors:
        key = row["text"].strip().lower()
        if key in seen:
            counts["duplicates"] += 1
            continue
        seen.add(key)
        kept.append({"id": row["id"], "text": row["text"], "teacher_raw": row["teacher_raw"]})

    kept.sort(key=lambda r: r["id"])
    counts["kept"] = len(kept)
    return kept, counts


def serialise(rows: list[dict]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")


def report(counts: dict[str, int]) -> None:
    total = counts["a"] + counts["b"] + counts["c"] + counts["d"] + counts["duplicates"] + counts["kept"]
    print(f"{'input records':<28}{counts['input']:>8}")
    print(f"{'(a) invalid JSON':<28}{counts['a']:>8}")
    print(f"{'(b) wrong keys':<28}{counts['b']:>8}")
    print(f"{'(c) unknown intent':<28}{counts['c']:>8}")
    print(f"{'(d) slot not in command':<28}{counts['d']:>8}")
    print(f"{'duplicate commands':<28}{counts['duplicates']:>8}")
    print(f"{'kept':<28}{counts['kept']:>8}")
    print(f"{'sum of headings':<28}{total:>8}")
    assert total == counts["input"], "counts do not add up"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-in", help="directory holding shard-*.jsonl")
    parser.add_argument("--local-out", help="where to write train.jsonl")
    args = parser.parse_args()

    if args.local_in:
        rows: list[dict] = []
        for path in sorted(Path(args.local_in).glob("shard-*.jsonl")):
            rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
        rows.sort(key=lambda r: r["id"])
        kept, counts = clean(rows)
        blob = serialise(kept)
        out = Path(args.local_out or "train.jsonl")
        out.write_bytes(blob)
        (out.parent / (out.name.replace(".jsonl", "") + ".sha256")).write_text(
            f"{hashlib.sha256(blob).hexdigest()}  {out.name}\n", encoding="utf-8"
        )
        report(counts)
        print(f"wrote {out} ({len(kept)} records)")
        return 0

    s3 = s3util.client()
    rows = []
    for key in s3util.list_keys(s3, s3util.DATASETS, "teacher/shard-"):
        rows.extend(s3util.read_jsonl(s3, s3util.DATASETS, key))
    rows.sort(key=lambda r: r["id"])
    kept, counts = clean(rows)
    blob = serialise(kept)
    digest = hashlib.sha256(blob).hexdigest()
    s3.put_object(Bucket=s3util.DATASETS, Key="v1/train.jsonl", Body=blob)
    s3.put_object(Bucket=s3util.DATASETS, Key="v1/train.sha256", Body=f"{digest}  train.jsonl\n".encode())
    report(counts)
    print(f"wrote s3://{s3util.DATASETS}/v1/train.jsonl sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
