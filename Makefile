SHELL := /bin/bash
PY ?= .venv/bin/python
IMAGE ?= akshaya33/command-parser
TAG ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)
SUBSET ?= 0
VERSION ?= v1
K3D ?= k3d
KUBECTL ?= kubectl
S3_LOCAL ?= http://localhost:8333

export AWS_ACCESS_KEY_ID ?= any
export AWS_SECRET_ACCESS_KEY ?= any
export S3_ENDPOINT ?= $(S3_LOCAL)
export AWS_DEFAULT_REGION ?= us-east-1

.PHONY: help venv lint test train train-subset publish up down cluster storage teacher clean-data image deploy loadtest subnet nacl evidence

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## create the local virtual environment
	python3.11 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch==2.1.2
	.venv/bin/pip install -r service/requirements.txt -r requirements-dev.txt

lint: ## ruff over all Python
	$(PY) -m ruff check worker training service infra tests

test: ## unit tests
	$(PY) -m pytest tests -q

train: ## train the student from training/config.yaml (SUBSET=50 for a smoke run)
	$(PY) training/train.py --subset $(SUBSET) --version $(VERSION)

publish: ## push the trained model to the models bucket and build the Release asset
	$(PY) training/publish.py --version $(VERSION)

teacher: ## label the command pool with phi3.5, one shard per invocation
	SHARD_INDEX=$(SHARD_INDEX) SHARD_COUNT=$(SHARD_COUNT) $(PY) worker/label.py

clean-data: ## clean the shards into datasets/v1/train.jsonl + checksum
	$(PY) worker/clean.py

cluster: ## create the k3d cluster
	$(K3D) cluster create --config cluster/k3d.yaml
	$(KUBECTL) apply -f infra/namespaces.yaml
	$(KUBECTL) apply -f infra/seaweedfs.yaml
	$(KUBECTL) -n data rollout status deploy/seaweedfs --timeout=180s
	$(KUBECTL) -n data port-forward svc/seaweedfs 8333:8333 >/dev/null 2>&1 &
	sleep 3
	$(PY) infra/make_buckets.py --endpoint $(S3_LOCAL)

image: ## build the service image without model weights
	docker build -f service/Dockerfile -t $(IMAGE):$(TAG) .
	$(K3D) image import $(IMAGE):$(TAG) -c kdcloud

deploy: ## apply the app manifests, the HPA and the secret
	$(KUBECTL) create secret generic s3-credentials -n app \
		--from-literal=AWS_ACCESS_KEY_ID=$(AWS_ACCESS_KEY_ID) \
		--from-literal=AWS_SECRET_ACCESS_KEY=$(AWS_SECRET_ACCESS_KEY) \
		--dry-run=client -o yaml | $(KUBECTL) apply -f -
	sed "s|IMAGE_TAG|$(TAG)|" k8s/app.yaml | $(KUBECTL) apply -f -
	$(KUBECTL) apply -f k8s/hpa.yaml
	$(KUBECTL) -n app rollout status deploy/parser --timeout=300s

up: cluster image deploy ## build and deploy everything from a fresh clone
	@echo "service: http://parser.localhost:8080/parse"

down: ## delete the cluster
	$(K3D) cluster delete kdcloud

image-size: ## report the image size (must be <= 2 GB)
	docker image inspect $(IMAGE):$(TAG) --format '{{.Size}}' | awk '{printf "%.2f GB\n", $$1/1e9}'

loadtest: ## the standard Locust run through the Ingress
	mkdir -p results
	$(PY) -m locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 \
		--run-time 2m --host http://localhost:8080 --csv results/loadtest

subnet: ## show the subnet plan
	@cat network/subnets.md

nacl: ## check the NACL against the sample packets
	$(PY) tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check

evidence: ## collect pod, cluster and resource evidence into results/
	$(KUBECTL) -n app get pods -o wide > results/pods.txt
	$(KUBECTL) -n app top pods > results/top_pods.txt
	$(KUBECTL) -n app logs -l app=parser --tail=200 > results/service_logs.txt
	$(KUBECTL) -n app get hpa > results/hpa.txt
