#!/usr/bin/env python3
"""Package a trained model and publish it to object storage.

    python training/publish.py --version v1              # upload to s3://models/v1/
    python training/publish.py --version v1 --asset-dir release   # also build the Release asset

Layout produced:
    s3://models/v1/                 model.safetensors, config.json, tokenizer files, training_meta.json
    s3://models/v1/model-v1.tar.gz  the same files, for the GitHub Release
    s3://models/v1/model.sha256     sha256 of model-v1.tar.gz

The service downloads models/v1/, so the weights never enter the image or Git.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "worker"))
import s3util

PT_NAMES = ("model.safetensors", "pytorch_model.bin")


def build_asset(model_dir: Path, asset_dir: Path, version: str) -> Path:
    asset_dir.mkdir(parents=True, exist_ok=True)
    asset = asset_dir / f"model-{version}.tar.gz"
    with tarfile.open(asset, "w:gz") as tar:
        for path in sorted(model_dir.iterdir()):
            if path.is_file():
                tar.add(path, arcname=path.name)
    return asset


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="v1")
    parser.add_argument("--model-dir", default=None)
    parser.add_argument("--asset-dir", default=str(REPO / "release"))
    parser.add_argument("--local", action="store_true", help="only build the asset, do not upload")
    args = parser.parse_args()

    version = args.version
    model_dir = Path(args.model_dir or REPO / "training" / "out" / version)
    if not model_dir.is_dir():
        raise SystemExit(f"no model at {model_dir}; run `make train` first")
    if not any((model_dir / name).exists() for name in PT_NAMES):
        raise SystemExit(f"{model_dir} has no weights file")

    asset = build_asset(model_dir, Path(args.asset_dir), version)
    digest = sha256_of(asset)
    print(f"asset {asset.relative_to(REPO) if asset.is_relative_to(REPO) else asset} sha256={digest}")
    if args.local:
        return 0

    s3 = s3util.client()
    bucket = s3util.MODELS
    for path in sorted(model_dir.iterdir()):
        if path.is_file():
            s3.upload_file(str(path), bucket, f"{version}/{path.name}")
    s3.upload_file(str(asset), bucket, f"{version}/{asset.name}")
    s3.put_object(Bucket=bucket, Key=f"{version}/model.sha256", Body=f"{digest}  {asset.name}\n".encode())
    print(f"published s3://{bucket}/{version}/ ({len(list(model_dir.iterdir()))} files + asset)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
