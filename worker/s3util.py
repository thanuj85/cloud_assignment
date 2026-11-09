"""Small S3 helpers shared by the worker and the cleaning step."""
from __future__ import annotations

import io
import json
import os
from collections.abc import Iterable, Iterator

import boto3

DATASETS = os.environ.get("DATASETS_BUCKET", "datasets")
MODELS = os.environ.get("MODELS_BUCKET", "models")


def client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )


def read_jsonl(s3, bucket: str, key: str) -> Iterator[dict]:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    for line in body.decode("utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def put_jsonl(s3, bucket: str, key: str, rows: Iterable[dict]) -> None:
    buf = io.BytesIO()
    for row in rows:
        buf.write(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n")
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())


def list_keys(s3, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    token: str | None = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
        if not page.get("IsTruncated"):
            return sorted(keys)
        token = page.get("NextContinuationToken")
