# Submission checklist

Anything already done is ticked. Anything unticked is work that needs the full runs; the
commands are in the README.

## Done and measured on this machine

- [x] `cluster/k3d.yaml`, `infra/` (namespaces, SeaweedFS, bucket bootstrap)
- [x] `prompts/teacher_prompt.txt` (four-key JSON, verbatim slots, `null` rules)
- [x] `worker/label.py` — sharding by `SHARD_INDEX`/`SHARD_COUNT`, resumable shards, stop sequence
- [x] `scripts/check_shards.py` — no gaps, no repeats (verified on the smoke shards)
- [x] `worker/clean.py` — rules (a)–(e), counts identity asserted, `train.sha256`
- [x] `training/config.yaml` + `make train` / `make train SUBSET=50`, `training/loss.csv`
- [x] `training/publish.py` — `models/vN/`, Release asset, `model.sha256`
- [x] `service/` — three endpoints, both headers, schema check, `FAULT_INJECT`, S3 download
- [x] `k8s/` — Deployment (2 replicas), Service, Ingress, HPA, probes, limits, secret example
- [x] `network/subnets.md`, `network/nacl.json` — 6/6 sample packets, 4/4 extra cases
- [x] 26 tests, ruff clean, `results/` evidence, `.github/workflows/ci.yml`
- [x] Teacher validation on all 100 commands: validity 75.0%, full_frame 33.0%
- [x] `README.md`, `AI_USE.md`, `report/report.md`

## Still to run (needs hours of CPU, or a cluster)

- [ ] Full teacher labelling: `make teacher SHARD_INDEX=0..3 SHARD_COUNT=4` (~1 h with 4 shards)
- [ ] `make clean-data`, then `make train` on 1,500 records (~20–40 min per epoch on this laptop)
- [ ] Second version `make train VERSION=v2`, then `make publish VERSION=v1` and `v2`
- [ ] `python training/evaluate.py --model student --version v1` and score it
- [ ] Push the Release asset: `gh release create model-v1 release/model-v1.tar.gz`
- [ ] Deploy and take the Task 4/7 evidence: HPA 1→2→1, rolling update + `rollout undo`,
      pod deletion, three cold starts, load test, `kubectl top pods`
- [ ] `python scripts/cost.py --replicas 2 --throughput <measured> --total <n> --failed <n>`
- [ ] CI: one deliberately failing quality-gate run, link it in the report
- [ ] Tag the assessed commit: `git tag -a final -m "final submission" && git push origin final`

## Handwritten reflection (separate upload)

- [ ] 3 pages, scanned, file named `230101013.pdf` exactly
- [ ] contains name, roll number 230101013, and the GitHub link
