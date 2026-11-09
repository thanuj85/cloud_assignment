#!/usr/bin/env python3
"""Task 7 cost estimate, computed from measured numbers.

    python scripts/cost.py --replicas 2 --throughput 3.2
    python scripts/cost.py --replicas 2 --throughput 3.2 --failed 4 --total 380

Each replica is billed for its CPU limit and its memory limit for every hour it runs,
whether or not it is busy (rate_card.json, billing_rule).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RATES = json.loads((REPO / "data" / "rate_card.json").read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicas", type=int, default=2, help="replicas running during the test")
    parser.add_argument("--cpu-limit", type=float, default=1.0, help="CPU limit per replica, in vCPU")
    parser.add_argument("--mem-limit", type=float, default=1.0, help="memory limit per replica, in GiB")
    parser.add_argument("--throughput", type=float, required=True, help="measured requests per second")
    parser.add_argument("--total", type=int, default=0, help="total requests in the run (for the error budget)")
    parser.add_argument("--failed", type=int, default=0, help="failed requests in the run")
    parser.add_argument("--slo", type=float, default=99.0, help="success SLO, in percent")
    args = parser.parse_args()

    per_replica_hour = args.cpu_limit * RATES["vcpu_hour"] + args.mem_limit * RATES["gib_memory_hour"]
    hourly = per_replica_hour * args.replicas
    served_per_hour = args.throughput * 3600
    per_1000 = hourly / served_per_hour * 1000

    print(f"rate card: {RATES['vcpu_hour']} {RATES['currency']}/vCPU-hour, "
          f"{RATES['gib_memory_hour']} {RATES['currency']}/GiB-hour")
    print(f"per replica per hour   {args.cpu_limit}*{RATES['vcpu_hour']} + "
          f"{args.mem_limit}*{RATES['gib_memory_hour']} = {per_replica_hour:.4f} {RATES['currency']}")
    print(f"all replicas per hour  {per_replica_hour:.4f} * {args.replicas} = {hourly:.4f} {RATES['currency']}")
    print(f"requests served/hour   {args.throughput:.3f} * 3600 = {served_per_hour:.0f}")
    print(f"cost per 1000 requests {hourly:.4f} / {served_per_hour:.0f} * 1000 = {per_1000:.4f} {RATES['currency']}")

    if args.total:
        budget = (100 - args.slo) / 100 * args.total
        used = args.failed / args.total * 100 if args.total else 0.0
        print()
        print(f"SLO                    {args.slo:.1f}% success over one load-test run")
        print(f"error budget           (100-{args.slo:.1f})/100 * {args.total} = {budget:.2f} requests")
        if budget:
            print(f"used                   {args.failed} failed of {args.total} = {used:.2f}% "
                  f"({args.failed / budget:.1%} of the budget)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
