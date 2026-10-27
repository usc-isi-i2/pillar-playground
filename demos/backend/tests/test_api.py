"""The HTTP layer: routing, error mapping and the ChatGPT proxy. Engine results are covered elsewhere."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from pillar_demos import chatgpt
from pillar_demos import replan as R
from pillar_demos.api import app

client = TestClient(app)


def test_copilot_analyze_and_errors():
    r = client.post("/api/copilot/analyze", json={"params": {"tau": 0.7}})
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["best"]["x"][3] + body["result"]["best"]["x"][7] == pytest.approx(70)
    assert len(body["circuitValues"]) == len(body["circuit"]["nodes"])
    r = client.post("/api/copilot/analyze", json={"params": {"tau": 2}})
    assert r.status_code == 400
    assert r.json() == {"error": "tau must be a number between 0.01 and 1."}
    r = client.post("/api/copilot/analyze", json={"params": {"evidence": "Storm", "stormProbability": 0}})
    assert r.json() == {"error": "The selected evidence has zero probability under this model."}


def test_copilot_minimum_backup():
    r = client.post("/api/copilot/minimum-backup", json={"params": {"scenario": "storm"}})
    assert r.json()["units"] == pytest.approx(22, abs=1e-4)


def test_replan_setup_slide_check():
    check = client.get("/api/replan/setup").json()["slideCheck"]
    assert [round(c["transport"]) for c in check] == [421, 429]


def test_replan_compute_and_sample_world():
    spec = {**R.PRESETS["storm"]["defaultSpec"], "tau": 0.9}
    body = {"preset": "storm", "spec": spec, "ev": R.DEFAULT_EVIDENCE}
    out = client.post("/api/replan/compute", json=body).json()
    assert set(out["evals"]) == {"mmap", "mpe"}
    assert set(out["stats"]) == set(out["diag"]["M"]["sc"])
    n = 1 + len(out["diag"]["M"]["sc"])
    world = client.post("/api/replan/sample-world", json={**body, "uniforms": [0.5] * n}).json()
    assert set(world["d"]) == set(out["diag"]["M"]["sc"])
    lane = client.post("/api/replan/verify-lane", json={**body, "plan": out["plans"]["mmap"]}).json()
    assert lane["replanP"] is not None


def test_evaluation_flow():
    data = client.post("/api/evaluation/synthetic", json={"kind": "correlated"}).json()
    ref = {"priority_floor": 0.9, "base_floor": 0.6, "emergency": False}
    out = client.post(
        "/api/evaluation/compare", json={"data": data, "rules": ref, "capacity": 240, "dependence": "joint"}
    ).json()
    assert out["matchesReference"] is True
    assert [r["name"] for r in out["rows"]] == ["Reference", "Reference", "ChatGPT", "ChatGPT"]
    r = client.post("/api/evaluation/compare", json={"data": data, "capacity": -1, "dependence": "joint"})
    assert r.json() == {"error": "Enter a positive finite capacity."}
    r = client.post("/api/evaluation/parse", json={"csv": "date,store,demand\n1,a,2"})
    assert r.status_code == 400


def test_config_reports_unconfigured(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert client.get("/api/config").json() == {"connected": False}
    r = client.post("/api/chatgpt", json={"prompt": "hi"})
    assert r.status_code == 503 and r.json()["code"] == "not_configured"


def test_chatgpt_proxy(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        reply = {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"a": 1}'}]}]}
        return httpx.Response(200, json=reply)

    text = asyncio.run(chatgpt.respond("Reply in JSON", True, httpx.MockTransport(handler)))
    assert text == '{"a": 1}'
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"] == {
        "model": "test-model",
        "input": "Reply in JSON",
        "text": {"format": {"type": "json_object"}},
    }

    def failing(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "Rate limited", "code": "rate_limit_exceeded"}})

    with pytest.raises(chatgpt.ChatGPTError) as err:
        asyncio.run(chatgpt.respond("x", False, httpx.MockTransport(failing)))
    assert (str(err.value), err.value.code) == ("Rate limited", "rate_limit_exceeded")
