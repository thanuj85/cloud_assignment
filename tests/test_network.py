"""The NACL file and the subnet plan, checked against the kit simulators."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NACL = REPO / "network" / "nacl.json"
PACKETS = REPO / "network" / "packets_sample.jsonl"


def simulate(rules: Path, packets: Path) -> str:
    result = subprocess.run(
        [sys.executable, "tools/nacl_sim.py", str(rules), str(packets), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def test_sample_packets_are_all_decided_correctly():
    out = simulate(NACL, PACKETS)
    assert "Correct: 6 / 6" in out, out


def test_abusive_range_is_denied_before_the_https_allow():
    rules = json.loads(NACL.read_text())["inbound"]
    deny = next(r for r in rules if r["cidr"] == "198.51.100.0/24")
    https = next(r for r in rules if r["port_from"] == 443 and r["cidr"] == "0.0.0.0/0")
    assert deny["action"] == "deny"
    assert deny["rule"] < https["rule"]
    assert deny["protocol"] == "all"


def test_ssh_is_limited_to_the_management_subnet():
    rules = json.loads(NACL.read_text())["inbound"]
    ssh = next(r for r in rules if r["port_from"] == 22)
    assert ssh["cidr"] == "10.20.5.128/27"
    assert ssh["action"] == "allow"


def test_outbound_allows_only_the_service_port_and_replies():
    outbound = json.loads(NACL.read_text())["outbound"]
    ports = {(r["port_from"], r["port_to"], r["cidr"]) for r in outbound}
    assert (8000, 8000, "10.20.0.0/22") in ports
    assert (1024, 65535, "0.0.0.0/0") in ports
    assert len(outbound) == 2


def test_custom_packets_for_reply_traffic():
    """Replies are checked as packets, so the reply rules must exist."""
    packets = [
        {"id": "T1", "direction": "inbound", "protocol": "tcp", "port": 49152,
         "address": "10.20.1.7", "expected": "allow"},
        {"id": "T2", "direction": "inbound", "protocol": "tcp", "port": 22,
         "address": "10.20.5.130", "expected": "allow"},
        {"id": "T3", "direction": "inbound", "protocol": "udp", "port": 443,
         "address": "198.51.100.4", "expected": "deny"},
        {"id": "T4", "direction": "outbound", "protocol": "tcp", "port": 443,
         "address": "10.20.0.9", "expected": "deny"},
    ]
    path = Path("/tmp/nacl_test_packets.jsonl")
    path.write_text("".join(json.dumps(p) + "\n" for p in packets))
    assert "Correct: 4 / 4" in simulate(NACL, path)
