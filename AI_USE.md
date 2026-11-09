# AI_USE.md

Assignment: Cloud Computing (CS3081) mini project — knowledge distillation and deployment of a
lightweight command parser.
Student: Paladugula Akshaya, 230101013.

## Tools used

| Tool | Role | How its output was checked |
|---|---|---|
| phi3.5 via Ollama (2.2 GB, `phi3.5:latest`) | the **teacher**. It generated the training targets from `prompts/teacher_prompt.txt` at temperature 0, seed 42, `num_ctx 2048` | replies are stored verbatim in `datasets/teacher/shard-N.jsonl`; `worker/clean.py` validates every reply against `data/schema.json` and rejects JSON that does not parse, has the wrong keys, an unknown intent, or an ungrounded slot |
| AI coding assistant (Claude, in the `pi` agent harness) | scaffolding and reviewing the code: the worker, cleaning rules, training loop, FastAPI service, Dockerfile, k8s manifests, tests, CI workflow and the first draft of these documents | every file was re-read, run locally, and checked by `make lint`, `make test`, `tools/nacl_sim.py --check`, `tools/score.py`; anything that did not run was rewritten rather than kept. The measured numbers in `results/` come from real runs, not from the assistant |
| Locust 2.47 | load test | `results/loadtest_stats.csv` and `results/loadtest_headers.json` from the kit's `tools/locustfile.py` |
| ruff, pytest | linting and unit tests | `results/pytest.txt`, `results/ruff.txt` |

No paid cloud, no paid inference API, and no other model was used to produce training
targets. The student model (`EleutherAI/pythia-70m`) is trained **only** on the teacher's
replies.

## What the AI did not decide

- The prompt in `prompts/teacher_prompt.txt` was iterated until the teacher produced
  parseable JSON at a usable rate; the final wording and the decision to ask for a single
  line were checked against the observed replies.
- The subnet plan in `network/subnets.md` and the rule order in `network/nacl.json` were
  derived by hand from Section 7.5 and then verified with `nacl_sim.py --check` (6/6 on the
  sample packets, 4/4 on the extra reply-traffic packets in `tests/test_network.py`).
- All measured results were produced by running the code on the machine described in the
  report. Where a full run was not finished, the report says so instead of inventing a
  number.

## Limitations of this use

- Generating a whole file with an assistant makes it easy to accept code that is
  plausible but untested. Mitigation: every module has a test or a simulator check, and
  anything without one is marked as untested in the report.
- The assistant has no access to a real cluster from inside the sandbox, so the k3d and
  Kubernetes steps were validated by `kubectl --dry-run=client` and by reading the
  manifests, not by a green CI run on the cluster. This is recorded as a limitation.
