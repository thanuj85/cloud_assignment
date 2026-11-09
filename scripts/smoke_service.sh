#!/usr/bin/env bash
# Local smoke test of the service contract, without Kubernetes.
#   MODEL_URI=training/out/v1 scripts/smoke_service.sh
set -u
MODEL_URI="${MODEL_URI:-training/out/v1}"
PORT="${PORT:-8000}"
export MODEL_URI MODEL_VERSION="${MODEL_VERSION:-v1}" MAX_NEW_TOKENS="${MAX_NEW_TOKENS:-64}" PORT="$PORT" FAULT_INJECT=0
${PYTHON:-python} service/app.py > /tmp/service.log 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null' EXIT
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/readyz")
  [ "$code" = "200" ] && break
  sleep 1
done

echo "--- GET /healthz"; curl -s -w '\nHTTP %{http_code}\n' "http://127.0.0.1:$PORT/healthz"
echo "--- GET /readyz";  curl -s -w '\nHTTP %{http_code}\n' "http://127.0.0.1:$PORT/readyz"
echo "--- POST /parse (what is the weather in london)"
curl -s -i -X POST "http://127.0.0.1:$PORT/parse" -H 'content-type: application/json' \
  -d '{"text": "what is the weather in london"}' | grep -Ei '^(HTTP|X-Model-Version|X-Served-By)|^\{'
echo "--- POST /parse with FAULT_INJECT=1"
kill $PID 2>/dev/null; sleep 1
FAULT_INJECT=1 PORT="$PORT" ${PYTHON:-python} service/app.py > /tmp/service_fault.log 2>&1 &
PID=$!
for i in $(seq 1 60); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/readyz")" = "200" ] && break
  sleep 1
done
curl -s -i -X POST "http://127.0.0.1:$PORT/parse" -H 'content-type: application/json' \
  -d '{"text": "what is the weather in london"}' | grep -Ei '^HTTP|^\{'
