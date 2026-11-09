#!/usr/bin/env python3
"""Check that the shards partition the command pool: no gaps, no repeats.

    python scripts/check_shards.py --local datasets/teacher
    python scripts/check_shards.py                      # reads s3://datasets/teacher/

Exits non-zero when a pool id is missing, or appears in more than one shard.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "worker"))
import s3util


def load(local: str | None) -> list[dict]:
    if local:
        rows = []
        for path in sorted(Path(local).glob("shard-*.jsonl")):
            rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
        return rows
    s3 = s3util.client()
    rows = []
    for key in s3util.list_keys(s3, s3util.DATASETS, "teacher/shard-"):
        rows.extend(s3util.read_jsonl(s3, s3util.DATASETS, key))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local")
    parser.add_argument("--pool", default=str(REPO / "data" / "commands_pool.jsonl"))
    args = parser.parse_args()

    pool_ids = {json.loads(line)["id"] for line in Path(args.pool).read_text().splitlines() if line.strip()}
    counts = Counter(row["id"] for row in load(args.local))
    repeated = sorted(i for i, n in counts.items() if n > 1)
    missing = sorted(pool_ids - set(counts))
    extra = sorted(set(counts) - pool_ids)

    print(f"pool ids        {len(pool_ids)}")
    print(f"labelled ids    {len(counts)}")
    print(f"repeated        {len(repeated)} {repeated[:5]}")
    print(f"missing         {len(missing)} {missing[:5]}")
    print(f"not in pool     {len(extra)} {extra[:5]}")
    ok = not repeated and not missing and not extra
    print("shards partition the pool" if ok else "shards DO NOT partition the pool")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
