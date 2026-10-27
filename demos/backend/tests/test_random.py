"""Seeded random cases captured from the original pages (demos/golden/capture.mjs)."""

import copy

import pytest

from conftest import load, plain
from pillar_demos import copilot as E
from pillar_demos import evaluation as API
from pillar_demos import replan as R
from test_replan import summary

G = load("random.json")


@pytest.mark.parametrize("i", range(len(G["copilot"])))
def test_copilot(i):
    case = G["copilot"][i]
    p = E.validate(case["input"])
    c = E.compile_circuit(p)
    assert plain({"p": p, "circuit": c, **E.analyze(c, p)}) == case["output"]
    if "minimumBackup" in case:
        assert plain(E.minimum_backup(c, p)) == case["minimumBackup"]


@pytest.mark.parametrize("i", range(len(G["replan"])))
def test_replan(i):
    inp = copy.deepcopy(G["replan"][i]["input"])
    out = plain(R.compute_replan(inp["preset"], inp["spec"], inp["ev"], inp["llmPlan"], inp["custom"]))
    for plan in out["plans"].values():
        plan.pop("ms", None)
    out["diag"]["M"] = plain(summary(out["diag"]["M"]))
    assert out == G["replan"][i]["output"]


@pytest.mark.parametrize("i", range(len(G["evaluation"])))
def test_evaluation(i):
    inp = G["evaluation"][i]["input"]
    out = API.run(API.parse(inp["csv"]), inp["rules"], inp["capacity"], inp["dependence"])
    assert plain(out) == G["evaluation"][i]["output"]
