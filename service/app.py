#!/usr/bin/env python3
"""Inference service for the distilled command parser.

Endpoints
    POST /parse    {"text": "..."} -> the four-key JSON object
    GET  /healthz  liveness, 200 while the process is alive
    GET  /readyz   readiness, 503 until the model is loaded, then 200

Configuration (all four required, plus FAULT_INJECT for testing):
    MODEL_URI      s3://models/v1, s3://models/v2, or a local directory
    MODEL_VERSION  written to the X-Model-Version response header
    S3_ENDPOINT    object-storage endpoint the model is downloaded from
    MAX_NEW_TOKENS generation cap
    FAULT_INJECT   1 replaces the model output with the text `not json`

Credentials are never read from a file in the image; they come from the
environment, which Kubernetes fills from a Secret.
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import tempfile
import threading
from pathlib import Path

import torch
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from transformers import AutoModelForCausalLM, AutoTokenizer

logger = logging.getLogger("parser")

SCHEMA = json.loads((Path(__file__).parent / "schema.json").read_text(encoding="utf-8"))
KEYS = set(SCHEMA["keys"])
INTENTS = set(SCHEMA["intents"])
SLOTS = ("date", "time", "place")

MODEL_URI = os.environ.get("MODEL_URI", "")
MODEL_VERSION = os.environ.get("MODEL_VERSION", "dev")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "")
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "64"))
FAULT_INJECT = os.environ.get("FAULT_INJECT", "0")
PORT = int(os.environ.get("PORT", "8000"))
POD_NAME = os.environ.get("POD_NAME") or socket.gethostname()

app = FastAPI(title="command parser", version=MODEL_VERSION)

_state: dict[str, object] = {"ready": False, "model": None, "tokenizer": None}
_lock = threading.Lock()


# --------------------------------------------------------------------------- model
def materialise_model(uri: str) -> Path:
    """Return a local directory holding the model, downloading it if needed."""
    if not uri.startswith("s3://"):
        return Path(uri)

    import boto3

    bucket, _, prefix = uri[5:].partition("/")
    prefix = prefix.rstrip("/")
    if not S3_ENDPOINT:
        raise RuntimeError("S3_ENDPOINT is required to download the model")
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
    )
    target = Path(tempfile.mkdtemp(prefix="model-"))
    listed = s3.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}/").get("Contents", [])
    if not listed:
        raise RuntimeError(f"no objects under {uri}")
    for item in listed:
        name = item["Key"][len(prefix) + 1 :]
        if not name or name.endswith((".tar.gz", ".sha256")):
            continue  # the release asset is not needed for serving
        body = s3.get_object(Bucket=bucket, Key=item["Key"])["Body"].read()
        (target / name).write_bytes(body)
        logger.info("downloaded %s (%d bytes)", name, len(body))
    return target


def load_model() -> None:
    if not MODEL_URI:
        raise RuntimeError("MODEL_URI is not set")
    model_dir = materialise_model(MODEL_URI)
    logger.info("loading model from %s", model_dir)
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_dir).eval()
    _state["model"], _state["tokenizer"] = model, tokenizer
    _state["ready"] = True
    logger.info("model %s ready", MODEL_VERSION)


@app.on_event("startup")
def startup() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        load_model()
    except Exception:  # keep the process up so /healthz answers and logs show the cause
        logger.exception("model failed to load; readiness stays 503")


# --------------------------------------------------------------------------- output checks
def balanced_object(text: str) -> str | None:
    """Return the first complete {...} block in `text`, if there is one."""
    start = text.find("{")
    while start != -1:
        depth, in_string, escaped = 0, False, False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("{", start + 1)
    return None


def validate(raw: str) -> dict | None:
    """Return the parsed object if it matches schema.json exactly, else None."""
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\n?", "", candidate)
        candidate = re.sub(r"\n?```$", "", candidate).strip()
    for text in (candidate, balanced_object(candidate)):
        if not text:
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or set(obj) != KEYS:
            continue
        if obj["intent"] not in INTENTS:
            continue
        if any(obj[slot] is not None and not isinstance(obj[slot], str) for slot in SLOTS):
            continue
        return {key: obj[key] for key in SCHEMA["keys"]}
    return None


def generate(command: str) -> str:
    model = _state["model"]
    tokenizer = _state["tokenizer"]
    prompt = f"Command: {command}\nJSON: "
    inputs = tokenizer(prompt, return_tensors="pt")
    with _lock, torch.no_grad():
        produced = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    new_tokens = produced[0][inputs["input_ids"].shape[1] :]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


# --------------------------------------------------------------------------- routes
@app.get("/healthz")
def healthz() -> dict:
    return {"status": "alive"}


@app.get("/readyz")
def readyz():
    if not _state["ready"]:
        return JSONResponse(status_code=503, content={"status": "loading"})
    return {"status": "ready"}


@app.post("/parse")
async def parse(request: Request):
    payload = await request.json()
    command = payload.get("text")
    if not isinstance(command, str) or not command.strip():
        return JSONResponse(status_code=400, content={"error": "text_required"})
    if not _state["ready"]:
        return JSONResponse(status_code=503, content={"error": "model_not_ready"})

    headers = {"X-Model-Version": MODEL_VERSION, "X-Served-By": POD_NAME}
    raw = "not json" if FAULT_INJECT == "1" else generate(command)
    parsed = validate(raw)
    if parsed is None:
        logger.warning("invalid model output for %r: %r", command, raw[:200])
        return JSONResponse(status_code=500, content={"error": "invalid_model_output"}, headers=headers)
    return JSONResponse(status_code=200, content=parsed, headers=headers)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, workers=1)
