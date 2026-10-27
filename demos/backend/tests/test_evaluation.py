"""Forecast comparison against the golden outputs captured from the original pages."""

import pytest

from conftest import load, plain
from pillar_demos import evaluation as API

G = load("evaluation.json")


def attempt(f):
    try:
        return {"ok": plain(f())}
    except API.EvaluationError as e:
        return {"error": str(e)}


@pytest.mark.parametrize("kind", list(G["datasets"]))
def test_synthetic(kind):
    assert plain(API.synthetic(kind)) == G["datasets"][kind]


@pytest.mark.parametrize("name", list(G["runs"]))
def test_run(name):
    inp = G["runs"][name]["input"]
    out = API.run(API.synthetic(inp["dataset"]), inp["rules"], inp["capacity"], inp["dependence"])
    assert plain(out) == G["runs"][name]["output"]


@pytest.mark.parametrize("name", list(G["parse"]))
def test_parse(name):
    case = dict(G["parse"][name])
    raw = case.pop("input")
    assert attempt(lambda: API.parse(raw)) == case


@pytest.mark.parametrize("name", list(G["rules"]))
def test_rules(name):
    case = dict(G["rules"][name])
    raw = case.pop("input")
    assert attempt(lambda: API.rules(raw)) == case
