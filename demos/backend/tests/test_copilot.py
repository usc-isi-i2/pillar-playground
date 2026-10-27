"""Circuit Copilot engine against the golden outputs captured from the original page."""

import pytest

from conftest import load, plain
from pillar_demos import copilot as E
from pillar_demos.lp import solve_lp

G = load("copilot.json")


@pytest.mark.parametrize("name", list(G["cases"]))
def test_case(name):
    case = G["cases"][name]
    p = E.validate(case["input"])
    c = E.compile_circuit(p)
    out = E.analyze(c, p)
    assert plain({"p": p, "circuit": c, **out}) == case["output"]


@pytest.mark.parametrize("name", list(G["minimumBackup"]))
def test_minimum_backup(name):
    raw = {**E.BASE, **({"scenario": "storm"} if name.startswith("storm") else {})}
    if name == "storm_tau90":
        raw["tau"] = 0.9
    p = E.validate(raw)
    assert plain(E.minimum_backup(E.compile_circuit(p), p)) == G["minimumBackup"][name]


def test_independence_contrast():
    assert plain(E.independence_contrast()) == G["independenceContrast"]


@pytest.mark.parametrize("name", list(G["invalid"]))
def test_rejects(name):
    case = G["invalid"][name]
    with pytest.raises(E.ValidationError) as err:
        E.validate(case["input"])
    assert str(err.value) == case["error"]


@pytest.mark.parametrize("name", list(G["lp"]))
def test_lp(name):
    case = G["lp"][name]
    rows = [{**r, "a": {int(k): v for k, v in r["a"].items()}} for r in case["input"]["rows"]]
    assert plain(solve_lp(case["input"]["n"], case["input"]["c"], rows)) == case["output"]


def test_empty_object_takes_defaults():
    # JS treats {} as truthy, so the original accepts it and fills in the defaults.
    assert E.validate({}) == E.BASE
