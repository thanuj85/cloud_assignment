# CPU-only build. Every version is pinned; the model weights are downloaded at
# start-up from object storage and are never copied into the image.
FROM python:3.11.9-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# torch from the CPU wheel index: the default wheel drags in ~2 GB of CUDA.
COPY service/requirements.txt /tmp/requirements.txt
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.1.2 \
 && pip install -r /tmp/requirements.txt

COPY service/app.py /app/app.py
COPY service/schema.json /app/schema.json

# Non-root, and no weights anywhere in the image.
RUN useradd --create-home --uid 10001 parser
USER parser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

CMD ["python", "app.py"]
