"""The cleaning rules from Task 1, tested on small hand-written shards."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "worker"))

from clean import clean, reject_reason, serialise

TOKYO = '{"intent": "datetime_query", "date": null, "time": null, "place": "tokyo"}'
GOOD = '{"intent": "weather_query", "date": null, "time": null, "place": "london"}'
BAD_INTENT = '{"intent": "music_play", "date": null, "time": null, "place": null}'
UNGROUNDED = '{"intent": "weather_query", "date": null, "time": null, "place": "paris"}'
ALARM = '{"intent": "alarm_set", "date": null, "time": "six am", "place": null}'


def row(rid: str, text: str, raw: str) -> dict:
    return {"id": rid, "text": text, "teacher_raw": raw}


def test_accepts_a_valid_reply():
    assert reject_reason(GOOD, "what is the weather in london") is None


def test_reason_a_invalid_json():
    assert reject_reason("not json", "anything") == "a"
    assert reject_reason('{"intent": "alarm_set", "date": null', "anything") == "a"


def test_reason_b_extra_or_missing_keys():
    extra = '{"intent": "alarm_set", "date": null, "time": null, "place": null, "note": "x"}'
    missing = '{"intent": "alarm_set", "date": null, "time": null}'
    assert reject_reason(extra, "set an alarm") == "b"
    assert reject_reason(missing, "set an alarm") == "b"


def test_reason_c_unknown_intent():
    raw = '{"intent": "music_play", "date": null, "time": null, "place": null}'
    assert reject_reason(raw, "play some music") == "c"


def test_reason_d_slot_not_in_command():
    raw = '{"intent": "weather_query", "date": null, "time": null, "place": "paris"}'
    assert reject_reason(raw, "what is the weather in london") == "d"


def test_reason_d_rejects_non_string_slot():
    raw = '{"intent": "weather_query", "date": 20240101, "time": null, "place": null}'
    assert reject_reason(raw, "weather on 20240101") == "d"


def test_duplicate_commands_keep_the_smallest_id():
    rows = [
        row("C0009", "what is the weather in london", GOOD),
        row("C0002", "What is the weather in London", GOOD),
        row("C0005", "set an alarm for six am", ALARM),
    ]
    kept, counts = clean(rows)
    assert [r["id"] for r in kept] == ["C0002", "C0005"]
    assert counts["duplicates"] == 1
    assert counts["kept"] == 2


def test_counts_add_up_to_the_input():
    rows = [
        row("C0001", "what is the weather in london", GOOD),
        row("C0002", "broken", "not json"),
        row("C0003", "missing keys", '{"intent": "alarm_set"}'),
        row("C0004", "bad intent", BAD_INTENT),
        row("C0005", "weather in london", UNGROUNDED),
        row("C0006", "what is the weather in london", GOOD),
    ]
    kept, counts = clean(rows)
    headings = counts["a"] + counts["b"] + counts["c"] + counts["d"] + counts["duplicates"] + counts["kept"]
    assert headings == counts["input"] == 6
    headings_seen = (counts["a"], counts["b"], counts["c"], counts["d"], counts["duplicates"], counts["kept"])
    assert headings_seen == (1, 1, 1, 1, 1, 1)
    assert len(kept) == 1


def test_kept_records_are_in_id_order():
    rows = [
        row("C0003", "what is the weather in london", GOOD),
        row("C0001", "set an alarm for six am", ALARM),
        row("C0002", "what time is it in tokyo", TOKYO),
    ]
    kept, _ = clean(rows)
    assert [r["id"] for r in kept] == ["C0001", "C0002", "C0003"]


def test_local_run_writes_matching_checksum(tmp_path):
    shard = tmp_path / "shard-0.jsonl"
    shard.write_text(json.dumps(row("C0001", "what is the weather in london", GOOD)) + "\n", encoding="utf-8")
    train = tmp_path / "train.jsonl"
    subprocess.run(
        [sys.executable, "worker/clean.py", "--local-in", str(tmp_path), "--local-out", str(train)],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    digest = hashlib.sha256(train.read_bytes()).hexdigest()
    assert (tmp_path / "train.sha256").read_text().split()[0] == digest
    assert serialise([json.loads(train.read_text().splitlines()[0])])
