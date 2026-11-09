"""The service contract: schema validation, the fault switch, and the probes."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "service"))

GOOD = '{"intent": "weather_query", "date": null, "time": null, "place": "london"}'


@pytest.fixture()
def app_module(monkeypatch):
    monkeypatch.setenv("MODEL_URI", "/tmp/does-not-exist")
    monkeypatch.setenv("MODEL_VERSION", "test")
    monkeypatch.setenv("FAULT_INJECT", "0")
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    return module


def fake_ready(module):
    """Pretend the model loaded, and give generate() a canned reply."""
    module._state["ready"] = True
    module._state["model"] = object()
    module._state["tokenizer"] = object()
    module.generate = lambda command: GOOD
    return module


def test_validate_accepts_a_schema_conforming_object(app_module):
    assert app_module.validate(GOOD)["place"] == "london"


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"intent": "weather_query", "date": null, "time": null}',
        '{"intent": "weather_query", "date": null, "time": null, "place": "london", "x": 1}',
        '{"intent": "music_play", "date": null, "time": null, "place": null}',
        '{"intent": "weather_query", "date": null, "time": null, "place": 3}',
    ],
)
def test_validate_rejects_non_conforming_output(app_module, raw):
    assert app_module.validate(raw) is None


def test_validate_recovers_json_wrapped_in_code_fences(app_module):
    assert app_module.validate("```json\n" + GOOD + "\n```")["intent"] == "weather_query"


def test_readyz_is_503_before_the_model_loads(app_module):
    app_module._state["ready"] = False
    client = TestClient(app_module.app)
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503


def test_parse_returns_the_object_and_both_headers(app_module):
    fake_ready(app_module)
    client = TestClient(app_module.app)
    response = client.post("/parse", json={"text": "what is the weather in london"})
    assert response.status_code == 200
    assert response.json() == {
        "intent": "weather_query",
        "date": None,
        "time": None,
        "place": "london",
    }
    assert response.headers["X-Model-Version"] == "test"
    assert response.headers["X-Served-By"]


def test_fault_inject_returns_500_with_the_exact_body(app_module, monkeypatch):
    fake_ready(app_module)
    monkeypatch.setattr(app_module, "FAULT_INJECT", "1")
    client = TestClient(app_module.app)
    response = client.post("/parse", json={"text": "what is the weather in london"})
    assert response.status_code == 500
    assert response.json() == {"error": "invalid_model_output"}


def test_parse_rejects_a_missing_text_field(app_module):
    fake_ready(app_module)
    client = TestClient(app_module.app)
    assert client.post("/parse", json={}).status_code == 400
