"""Run both demos with tddlog answering every probability, and compare with the golden outputs
captured from the original pages (demos/golden). Numbers must agree to 1e-9 (relative); every
other value must be equal. Prints one line per suite and every mismatch."""

from __future__ import annotations

import copy
import json
import math
import time
from pathlib import Path

import copilot_tddlog as CT
import replan_tddlog as RT
from problog_text import CALLS
from pillar_demos import copilot as C
from pillar_demos import replan as R

GOLDEN = Path(__file__).resolve().parents[2] / "demos" / "golden"
G = {name: json.loads((GOLDEN / f"{name}.json").read_text()) for name in ("copilot", "replan", "random")}


def plain(v):
    return json.loads(json.dumps(v))


def diff(a, b, path="", out=None, tol=1e-9):
    """Paths where a and b differ: numbers beyond a relative tol, anything else at all."""
    out = [] if out is None else out
    if isinstance(a, bool) or isinstance(b, bool) or not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in a.keys() | b.keys():
                if k not in a or k not in b:
                    out.append(f"{path}/{k}: only in {'ours' if k in a else 'golden'}")
                else:
                    diff(a[k], b[k], f"{path}/{k}", out, tol)
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for i, (x, y) in enumerate(zip(a, b)):
                diff(x, y, f"{path}/{i}", out, tol)
        elif a != b:
            out.append(f"{path}: {str(a)[:80]} != {str(b)[:80]}")
    elif not math.isclose(a, b, rel_tol=tol, abs_tol=1e-12):
        out.append(f"{path}: {a!r} != {b!r}")
    return out


def report(name, results, start):
    bad = [(case, d) for case, d in results if d]
    print(f"{name:34s} {len(results) - len(bad):3d}/{len(results)} match   {time.perf_counter() - start:6.1f}s")
    for case, d in bad:
        print(f"   {case}: {len(d)} differences, e.g. {d[:3]}")


def copilot_case(inp):
    p = C.validate(inp)
    c = C.compile_circuit(p)
    return plain({"p": p, "circuit": c, **C.analyze(c, p)})


def replan_case(inp, full):
    inp = copy.deepcopy(inp)
    out = plain(R.compute_replan(inp["preset"], inp["spec"], inp["ev"], inp.get("llmPlan"), inp.get("custom")))
    for plan in out["plans"].values():
        plan.pop("ms", None)
    if not full:
        M = out["diag"]["M"]
        out["diag"]["M"] = plain({"dcs": M["dcs"], "forecast": M["forecast"], "prio": M["prio"],
                                  "nConfigs": len(M["configs"]), "weights": [k["w"] for k in M["configs"]]})
    return out


def replan_decision(ours, golden):
    """What a plan decides: for each solved plan, its chance thresholds, expected cost, probability
    that every priority store meets the rule, and what was relaxed. Two plans the LP finds equally
    cheap (a tie it breaks by pivot order) agree on all of these, though their shipments differ."""
    out = []
    for pid, plan in golden["plans"].items():
        if plan.get("status") != "optimal":
            out += diff(ours["plans"].get(pid, {}).get("status"), plan.get("status"), f"/plans/{pid}/status")
            continue
        mine = ours["plans"][pid]
        out += diff(mine["threshold"], plan["threshold"], f"/plans/{pid}/threshold")
        out += diff(sorted((r["rule"], r["key"]) for r in mine["relaxed"]),
                    sorted((r["rule"], r["key"]) for r in plan["relaxed"]), f"/plans/{pid}/relaxed")
        for field in ("expCost", "pAll"):
            out += diff(ours["evals"][pid][field], golden["evals"][pid][field], f"/evals/{pid}/{field}")
    return out


def replan_same_plans(inp, golden):
    """The golden plans, scored on a model whose probabilities come from tddlog."""
    inp = copy.deepcopy(inp)
    spec = inp["spec"]
    from pillar_demos.replan import missing_params
    if missing_params(spec):
        return []
    M = R.build_model(inp["preset"], spec, inp["ev"], {}, inp.get("custom"))
    out = []
    for pid, ev in golden["evals"].items():
        plan = golden["plans"][pid]
        mine = plain(R.evaluate_plan(M, plan["ship"]))
        for field in ("expCost", "pAll", "shortPen", "transport"):
            out += diff(mine[field], ev[field], f"/evals/{pid}/{field}")
        out += diff([r["p"] for r in mine["rules"]], [r["p"] for r in ev["rules"]], f"/evals/{pid}/rules")
    return out


def posterior_case(inp, golden):
    """The storm posterior and the evidence attribution, from tddlog alone."""
    if inp["preset"] != "storm" or golden["diag"]["posterior"] is None:
        return []
    spec, ev, custom = inp["spec"], inp["ev"], inp.get("custom")
    full = RT.Program("storm", spec, ev, None, custom).posterior()
    ours = {"posterior": full, "attribution": []}
    for field, label in (("advisory", "Storm advisory"), ("sales", "TX sales signal"), ("emergency", "Emergency status")):
        if ev.get(field) == "unknown":
            continue
        without = RT.Program("storm", spec, {**ev, field: "unknown"}, None, custom).posterior()
        ours["attribution"].append({"label": label, "value": ev.get(field), "landfallWithout": without["z"][2],
                                    "landfallWith": full["z"][2], "highWithout": without["u"][2], "highWith": full["u"][2]})
    return diff(plain(ours), {"posterior": golden["diag"]["posterior"], "attribution": golden["diag"]["attribution"]})


def main():
    full_model = {"toy_default", "storm_default", "storm_worst"}
    with CT.Patched():
        t = time.perf_counter()
        report("Copilot: page cases", [(n, diff(copilot_case(c["input"]), c["output"])) for n, c in G["copilot"]["cases"].items()], t)
        t = time.perf_counter()
        report("Copilot: random cases", [(i, diff(copilot_case(c["input"]), c["output"])) for i, c in enumerate(G["random"]["copilot"])], t)
        t = time.perf_counter()
        results = []
        for name, golden in G["copilot"]["minimumBackup"].items():
            raw = {**C.BASE, **({"scenario": "storm"} if name.startswith("storm") else {})}
            if name == "storm_tau90":
                raw["tau"] = 0.9
            p = C.validate(raw)
            results.append((name, diff(plain(C.minimum_backup(C.compile_circuit(p), p)), golden)))
        report("Copilot: minimum backup", results, t)
    t = time.perf_counter()
    report("Copilot: independence contrast", [("contrast", diff(plain(CT.independence_contrast()), G["copilot"]["independenceContrast"]))], t)

    with RT.Patched():
        t = time.perf_counter()
        report("Replan: page cases", [(n, diff(replan_case(c["input"], n in full_model), c["output"])) for n, c in G["replan"]["cases"].items()], t)
        t = time.perf_counter()
        report("Replan: random cases", [(i, diff(replan_case(c["input"], False), c["output"])) for i, c in enumerate(G["random"]["replan"])], t)
        cases = [(n, c, n in full_model) for n, c in G["replan"]["cases"].items()] + [(i, c, False) for i, c in enumerate(G["random"]["replan"])]
        t = time.perf_counter()
        report("Replan: decisions (cost, chance)", [(n, replan_decision(replan_case(c["input"], f), c["output"])) for n, c, f in cases], t)
        t = time.perf_counter()
        report("Replan: golden plans re-scored", [(n, replan_same_plans(c["input"], c["output"])) for n, c, f in cases], t)
    t = time.perf_counter()
    cases = list(G["replan"]["cases"].items()) + [(i, c) for i, c in enumerate(G["random"]["replan"])]
    report("Replan: posterior and attribution", [(n, posterior_case(c["input"], c["output"])) for n, c in cases], t)
    print(f"tddlog runs: {CALLS['n']}")


if __name__ == "__main__":
    main()
