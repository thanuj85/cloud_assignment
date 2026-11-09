#!/usr/bin/env python3
"""Create the two buckets and upload the command pool.

Runs as a Job in the cluster (infra/bootstrap-job.yaml) or locally:

    python infra/make_buckets.py --endpoint http://localhost:8333
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[1]
BUCKETS = ("datasets", "models")

# Files that must exist in the datasets bucket before the pipeline starts.
UPLOADS = [("data/commands_pool.jsonl", "commands_pool.jsonl")]


def client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "any"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "any"),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )


def ensure_bucket(s3, name: str) -> None:
    try:
        s3.head_bucket(Bucket=name)
        print(f"bucket {name}: exists")
        return
    except ClientError:
        pass
    s3.create_bucket(Bucket=name)
    print(f"bucket {name}: created")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("S3_ENDPOINT", "http://localhost:8333"))
    parser.add_argument("--skip-upload", action="store_true")
    args = parser.parse_args()

    s3 = client(args.endpoint)
    for bucket in BUCKETS:
        ensure_bucket(s3, bucket)

    if args.skip_upload:
        return 0

    for local, key in UPLOADS:
        path = REPO / local
        if not path.exists():
            print(f"missing {path}", file=sys.stderr)
            return 1
        s3.upload_file(str(path), "datasets", key)
        print(f"uploaded {local} -> s3://datasets/{key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
