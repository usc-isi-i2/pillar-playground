"""Replan engine against the golden outputs captured from the original page."""

import copy

import pytest

from conftest import load, plain
from pillar_demos import replan as R

G = load("replan.json")
FULL_MODEL = {"toy_default", "storm_default", "storm_worst"}


def summary(M):
    return {
        "dcs": M["dcs"],
        "forecast": M["forecast"],
        "prio": M["prio"],
        "nConfigs": len(M["configs"]),
        "weights": [k["w"] for k in M["configs"]],
    }


def shaped(out, full):
    """solve_plan reports wall-clock time, which the capture dropped; most cases keep a model summary."""
    out = plain(out)
    for plan in out["plans"].values():
        plan.pop("ms", None)
    if not full:
        out["diag"]["M"] = plain(summary(out["diag"]["M"]))
    return out


def test_presets():
    assert plain(R.PRESETS) == G["presets"]
    assert R.DEFAULT_EVIDENCE == G["defaultEvidence"]


@pytest.mark.parametrize("name", list(G["cases"]))
def test_case(name):
    inp = copy.deepcopy(G["cases"][name]["input"])
    out = R.compute_replan(inp["preset"], inp["spec"], inp["ev"], inp.get("llmPlan"))
    assert shaped(out, name in FULL_MODEL) == G["cases"][name]["output"]


def test_custom_demand():
    inp = copy.deepcopy(G["customDemand"]["input"])
    out = R.compute_replan(inp["preset"], inp["spec"], inp["ev"], None, inp["custom"])
    assert shaped(out, True) == G["customDemand"]["output"]


@pytest.mark.parametrize("name", list(G["specs"]))
def test_validate_spec(name):
    case = G["specs"][name]
    assert plain(R.validate_spec(case["input"]["preset"], case["input"]["raw"])) == case["output"]
