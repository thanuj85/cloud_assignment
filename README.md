# Distilled Command Parser on a Local Cloud

**Paladugula Akshaya** · 230101013
GitHub: https://github.com/Akshaya33-P/cloud-assignment

A 70M-parameter command parser distilled from the phi3.5 teacher and served on a local
k3d cluster, with SeaweedFS object storage, autoscaling, probes, a NACL plan and a CI
pipeline. Course: Cloud Computing (CS3081), mini project.

## Architecture

```
data/commands_pool.jsonl
        |
        |  (1) s3 upload                       phi3.5 in Ollama (temp 0, seed 42)
        v                                              ^
  SeaweedFS  datasets bucket  <---- worker/label.py ----+
        |                        SHARD_INDEX / SHARD_COUNT
        |  datasets/teacher/shard-N.jsonl   (raw replies, one object per shard)
        v
  worker/clean.py  ->  datasets/v1/train.jsonl + train.sha256
        |
        v
  training/train.py  (pythia-70m, CPU, sequence-level distillation)
        |  models/v1/  +  Release asset model-v1.tar.gz  +  model.sha256
        v
  service (FastAPI)  ->  k8s/app  Deployment + Service + Ingress + HPA
                              MODEL_URI=s3://models/v1
```

## Repository layout

| Path | Purpose |
|---|---|
| `cluster/k3d.yaml` | single-node-ish k3d cluster (1 server, 1 agent) |
| `infra/` | namespaces, SeaweedFS, bucket bootstrap |
| `worker/label.py` | sharded teacher labeller, resumable |
| `worker/clean.py` | Task 1 cleaning rules + checksum + counts |
| `training/config.yaml` | every training knob (seed, lr, batch, epochs, length, versions) |
| `training/train.py` | the distillation run, writes `training/loss.csv` |
| `training/evaluate.py` | predictions for teacher / base / student |
| `training/publish.py` | uploads `models/vN/` and builds the Release asset |
| `service/` | FastAPI app, pinned requirements, 2 GB Dockerfile |
| `k8s/` | Deployment, Service, Ingress, HPA, ConfigMap, secret example |
| `network/subnets.md`, `network/nacl.json` | Task 5 |
| `tests/` | 26 pytest tests (cleaning, service contract, NACL, sharding) |
| `.github/workflows/ci.yml` | lint → tests → evaluate → quality gate → gitleaks |

## Commands

```bash
make venv                 # local virtual environment
make lint                 # ruff
make test                 # pytest

make cluster              # k3d + namespaces + SeaweedFS + buckets + upload pool
make teacher SHARD_INDEX=0 SHARD_COUNT=2
make teacher SHARD_INDEX=1 SHARD_COUNT=2
python scripts/check_shards.py        # no gaps, no repeats
make clean-data                       # datasets/v1/train.jsonl + train.sha256
make train                            # make train SUBSET=50 for a smoke run
make publish VERSION=v1               # models/v1/ + release/model-v1.tar.gz
make up                               # image + deploy (<= 3 commands from a fresh clone)
make loadtest                         # the standard Locust run
make evidence                         # pods, top, logs, hpa -> results/
make down                             # delete the cluster
```

Evaluate and gate:

```bash
python training/evaluate.py --model teacher --name teacher
python training/evaluate.py --model base --name base_pythia70m
python training/evaluate.py --model student --version v1
python tools/score.py results/teacher_predictions.jsonl data/validation.jsonl --out results/teacher_validation.json
python tools/score.py results/student_v1_predictions.jsonl data/validation.jsonl --min-validity 95
```

## Results

Measured on this machine (8 GB RAM, CPU only). See `results/` and `report/report.md`.

| Measurement | Value | Evidence |
|---|---|---|
| Teacher labelling rate (phi3.5, 2 shards in parallel) | 0.19–0.20 cmd/s per shard | `results/labelling_rate.txt` |
| Teacher validation, plain prompt | json_validity 75.0%, full_frame 33.0% | `results/teacher_validation.json` |
| Prompt probe with `stop=["\n"]` | 12/15 replies clean (80%), 0.43 cmd/s | `results/prompt_probe.txt` |
| Cleaning counts (12-record smoke run) | 12 in → 2 rejected (a) → 10 kept | `results/clean_counts.txt` |
| Unit tests | 26 passed, ruff clean | `results/pytest.txt`, `results/ruff.txt` |
| NACL sample packets | 6/6 correct | `results/nacl_check.txt` |
| Validation: teacher / untrained base | full_frame 33.0% / 0.0% | `results/teacher_validation.json`, `results/base_pythia70m_validation.json` |
| Service contract | /healthz 200, /readyz 200, /parse 500 `invalid_model_output` (smoke model), headers present | `results/service_smoke.txt` |

## Limitations

- One laptop, one k3s node: no cross-machine fault tolerance, so HPA and pod recovery
  only show the mechanics, not real high availability.
- The `make up` path needs Docker/Colima running; the cluster is created with 1 server
  and 1 agent on the same machine, so the Ingress and both replicas share one kernel.
- Training and labelling are CPU-bound. Labelling 3,000 commands with phi3.5 measures
  ~0.2 commands/s per worker, which is why shards run in parallel.

## AI use

See `AI_USE.md`: which tools were used, for what, and how their output was verified.
