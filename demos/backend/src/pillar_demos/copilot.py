"""Circuit Copilot engine: finite-domain reference compiler and decision engine.

Two depots (A, B) ship to four sites (S1–S4), plus an optional local backup at S4. Three joint
worlds (Normal, Surge, Storm) set S4 demand; in the storm scenario A→S4 arrives late in the Storm
world. A plan is nine quantities: A→S1..S4, B→S1..S4, backup→S4.

A port of the original page's engine; results match it exactly (see tests/test_golden.py).
"""

from __future__ import annotations

import math
from typing import Any

from .js import js_round, js_str, js_sum
from .lp import Op, Row, solve_lp

Params = dict[str, Any]
Circuit = dict[str, Any]

BASE: Params = {
    "scenario": "demand",
    "capacityA": 130,
    "capacityB": 50,
    "service": 0.9,
    "tau": 0.95,
    "floor": 0.6,
    "penaltyPriority": 20,
    "penaltyOther": 10,
    "backupEnabled": False,
    "backupLimit": 30,
    "backupCost": 12,
    "exceptionAuthorized": False,
    "exceptionService": 0.8,
    "stormProbability": 0.3,
    "evidence": "all",
}
COST = [1, 2, 5, 6, 6, 5, 2, 1]
FORECAST = [50, 40, 45, 55]
NAMES = ["Normal", "Surge", "Storm"]
DEMAND = [60, 70, 80]

LIMITS: dict[str, tuple[float, float]] = {
    "capacityA": (0, 400),
    "capacityB": (0, 400),
    "service": (0.1, 1),
    "tau": (0.01, 1),
    "floor": (0, 1),
    "penaltyPriority": (0, 1000),
    "penaltyOther": (0, 1000),
    "backupLimit": (0, 100),
    "backupCost": (0, 1000),
    "exceptionService": (0.1, 1),
    "stormProbability": (0, 1),
}


class ValidationError(ValueError):
    """A parameter object the engine does not accept. The message is shown to the operator."""


def alpha(p: Params) -> float:
    """The service level in force: the exception level only under explicit authorization."""
    return p["exceptionService"] if p["exceptionAuthorized"] else p["service"]


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(raw: Any) -> Params:
    # Any object is accepted, including {} (truthy in JS); null, arrays and scalars are not.
    if not isinstance(raw, dict):
        raise ValidationError("Expected a parameter object.")
    p = {**BASE, **raw}
    for k, (lo, hi) in LIMITS.items():
        v = p[k]
        if not _is_number(v) or not math.isfinite(v) or v < lo or v > hi:
            raise ValidationError(f"{k} must be a number between {js_str(lo)} and {js_str(hi)}.")
    for k in ("backupEnabled", "exceptionAuthorized"):
        if not isinstance(p[k], bool):
            raise ValidationError(f"{k} must be true or false.")
    if p["scenario"] not in ("demand", "storm"):
        raise ValidationError("Unknown scenario.")
    if p["evidence"] not in ("all", "Normal", "Surge", "Storm"):
        raise ValidationError("Unknown evidence value.")
    if p["exceptionAuthorized"] and p["exceptionService"] > p["service"]:
        raise ValidationError("The exception level must not exceed the standard service level.")
    unknown = [k for k in raw if k not in BASE]
    if unknown:
        raise ValidationError("Unsupported fields: " + ", ".join(unknown))
    return p


def compile_circuit(p: Params) -> Circuit:
    worlds = [
        {"id": i, "name": name, "demand": DEMAND[i], "timely": not (p["scenario"] == "storm" and i == 2)}
        for i, name in enumerate(NAMES)
    ]
    nodes: list[dict[str, Any]] = []

    def add(n: dict[str, Any]) -> int:
        nodes.append({"id": len(nodes), **n})
        return len(nodes) - 1

    terms: list[int] = []
    den: list[int] = []
    for w in worlds:
        a = add({"op": "weight", "world": w["id"], "label": f"P({w['name']})"})
        e = add({"op": "evidence", "world": w["id"], "label": f"Evidence allows {w['name']}"})
        r = add({"op": "policy", "world": w["id"], "label": f"S1 and S4 service in {w['name']}"})
        den.append(add({"op": "product", "children": [a, e], "label": f"Active mass {w['name']}"}))
        terms.append(add({"op": "product", "children": [a, e, r], "label": f"Passing mass {w['name']}"}))
    numerator = add({"op": "sum", "children": terms, "label": "Policy and evidence"})
    denominator = add({"op": "sum", "children": den, "label": "Evidence probability"})
    return {
        "version": "finite-arithmetic-v1",
        "signature": p["scenario"],
        "worlds": worlds,
        "nodes": nodes,
        "numerator": numerator,
        "denominator": denominator,
    }


def _priors(p: Params) -> list[float]:
    q = p["stormProbability"]
    return [(1 - q) * 0.15 / 0.7, (1 - q) * 0.55 / 0.7, q]


def world_weights(c: Circuit, p: Params) -> list[float]:
    """Posterior probability of each world given the evidence."""
    prior = _priors(p)
    mass = [prior[w["id"]] * (1 if p["evidence"] in ("all", w["name"]) else 0) for w in c["worlds"]]
    z = js_sum(mass)
    if z <= 1e-12:
        raise ValidationError("The selected evidence has zero probability under this model.")
    return [v / z for v in mass]


def _deliveries(x: list[float], w: dict[str, Any]) -> list[float]:
    return [x[0] + x[4], x[1] + x[5], x[2] + x[6], (x[3] if w["timely"] else 0) + x[7] + x[8]]


def evaluate(c: Circuit, x: list[float], p: Params) -> dict[str, Any]:
    """Evaluate the circuit for plan ``x``: the conditional probability the policy holds, and every gate."""
    prior = _priors(p)
    values: list[float] = []
    for n in c["nodes"]:
        op = n["op"]
        if op == "weight":
            values.append(prior[n["world"]])
        elif op == "evidence":
            values.append(1 if p["evidence"] in ("all", c["worlds"][n["world"]]["name"]) else 0)
        elif op == "policy":
            w = c["worlds"][n["world"]]
            y = _deliveries(x, w)
            ok = y[0] + 1e-7 >= alpha(p) * 50 and y[3] + 1e-7 >= alpha(p) * w["demand"]
            values.append(1 if ok else 0)
        elif op == "product":
            acc = 1
            for i in n["children"]:
                acc = acc * values[i]
            values.append(acc)
        else:
            values.append(js_sum(values[i] for i in n["children"]))
    if values[c["denominator"]] <= 1e-12:
        raise ValidationError("Evidence has zero probability.")
    return {"probability": values[c["numerator"]] / values[c["denominator"]], "values": values}


def score(c: Circuit, x: list[Any], p: Params) -> dict[str, Any]:
    if (
        not isinstance(x, list)
        or len(x) != 9
        or any(not _is_number(v) or not math.isfinite(v) or v < -1e-7 for v in x)
    ):
        raise ValidationError("A plan must contain nine finite nonnegative shipment quantities.")
    probs = world_weights(c, p)
    issues: list[str] = []
    used_a = js_sum(x[0:4])
    used_b = js_sum(x[4:8])
    limit = p["backupLimit"] if p["backupEnabled"] else 0
    if used_a > p["capacityA"] + 1e-5:
        issues.append("Depot A capacity exceeded")
    if used_b > p["capacityB"] + 1e-5:
        issues.append("Depot B capacity exceeded")
    if x[8] > limit + 1e-5:
        issues.append("Local backup limit exceeded")
    shortage = 0.0
    states = []
    for i, w in enumerate(c["worlds"]):
        y = _deliveries(x, w)
        d = [50, 40, 45, w["demand"]]
        loss = 0.0
        for j in range(4):
            loss += max(0, d[j] - y[j]) * (p["penaltyPriority"] if j in (0, 3) else p["penaltyOther"])
            if probs[i] > 1e-12 and y[j] + 1e-5 < p["floor"] * FORECAST[j]:
                issues.append(f"{w['name']}: S{j + 1} forecast floor missed")
        shortage += probs[i] * loss
        states.append(
            {
                **w,
                "p": probs[i],
                "delivered": y,
                "requiredS4": alpha(p) * w["demand"],
                "policy": y[0] + 1e-7 >= alpha(p) * 50 and y[3] + 1e-7 >= alpha(p) * w["demand"],
            }
        )
    transport = 0.0
    for i, v in enumerate(COST):
        transport += v * x[i]
    backup_cost = x[8] * p["backupCost"]
    probability = evaluate(c, x, p)["probability"]
    return {
        "x": x,
        "probability": probability,
        "transport": transport,
        "backupCost": backup_cost,
        "shortage": shortage,
        "total": transport + backup_cost + shortage,
        "usedA": used_a,
        "usedB": used_b,
        "issues": list(dict.fromkeys(issues)),
        "feasible": len(issues) == 0,
        "meetsPolicy": probability + 1e-7 >= p["tau"],
        "states": states,
    }


def solve(c: Circuit, p: Params) -> dict[str, Any]:
    """Cheapest plan meeting the chance constraint.

    For each of the 8 subsets of worlds in which the priority rule is enforced, solve an LP; keep
    the cheapest plan whose circuit probability is at least tau.
    """
    ps = world_weights(c, p)
    N = 21
    candidates: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    max_probability = 0.0
    pivots = 0
    for mask in range(8):
        objective = [0.0] * N
        for i, v in enumerate(COST):
            objective[i] = v
        objective[8] = p["backupCost"]
        for s in range(3):
            for j in range(4):
                objective[9 + s * 4 + j] = ps[s] * (
                    p["penaltyPriority"] if j in (0, 3) else p["penaltyOther"]
                )
        rows: list[Row] = []

        def row(a: dict[int, float], op: Op, b: float, rows: list[Row] = rows) -> None:
            rows.append({"a": a, "op": op, "b": b})

        row({0: 1, 1: 1, 2: 1, 3: 1}, "<=", p["capacityA"])
        row({4: 1, 5: 1, 6: 1, 7: 1}, "<=", p["capacityB"])
        row({8: 1}, "<=", p["backupLimit"] if p["backupEnabled"] else 0)

        def co(s: int, j: int) -> dict[int, float]:
            # Units reaching site j in world s.
            a: dict[int, float] = {j: 0 if j == 3 and not c["worlds"][s]["timely"] else 1, j + 4: 1}
            if j == 3:
                a[8] = 1
            return a

        for s in range(3):
            w = c["worlds"][s]
            d = [50, 40, 45, w["demand"]]
            for j in range(4):
                a = co(s, j)
                if ps[s] > 1e-12:
                    row(dict(a), ">=", p["floor"] * FORECAST[j])
                a[9 + s * 4 + j] = 1
                row(a, ">=", d[j])
            if mask & (1 << s) and ps[s] > 1e-12:
                row(co(s, 0), ">=", alpha(p) * 50)
                row(co(s, 3), ">=", alpha(p) * w["demand"])
        lp = solve_lp(N, objective, rows)
        if lp["status"] != "optimal":
            continue
        pivots += lp["iterations"]
        x = [0 if abs(v) < 1e-7 else v for v in lp["x"][:9]]
        sc = score(c, x, p)
        if not sc["feasible"]:
            continue
        max_probability = max(max_probability, sc["probability"])
        candidates.append({"mask": mask, **sc})
        if sc["meetsPolicy"] and (best is None or sc["total"] < best["total"] - 1e-6):
            best = {"mask": mask, **sc}
    return {
        "best": best,
        "maxProbability": max_probability,
        "hardFeasible": len(candidates) > 0,
        "candidates": candidates,
        "pivots": pivots,
        "subsets": 8,
        "status": "feasible" if best else "infeasible",
    }


def analyze(c: Circuit, p: Params) -> dict[str, Any]:
    """The decision plus the most-likely-world plan.

    The second solves as if the most probable world were observed, then scores that plan under
    the real evidence.
    """
    result = solve(c, p)
    ps = world_weights(c, p)
    best_world = ps.index(max(ps))
    pr = solve(c, {**p, "evidence": c["worlds"][best_world]["name"]})
    mpe = score(c, pr["best"]["x"], p) if pr["best"] else None
    return {"result": result, "mpe": mpe}


def independence_contrast() -> dict[str, Any]:
    """Fixed example: the same plan scored with storm-linked versus independent delay."""
    x = [50, 40, 31, 9, 0, 0, 0, 50, 13]
    p = {**BASE, "scenario": "storm", "backupEnabled": True, "tau": 0.9}
    joint = score(compile_circuit(p), x, p)
    independent = 0.0
    for d, pd in ((60, 0.15), (70, 0.55), (80, 0.3)):
        for t, pt in ((True, 0.7), (False, 0.3)):
            if 50 + 13 + (9 if t else 0) >= 0.9 * d - 1e-7:
                independent += pd * pt
    return {
        "x": x,
        "joint": joint["probability"],
        "independent": independent,
        "failureJoint": 1 - joint["probability"],
        "failureIndependent": 1 - independent,
    }


def minimum_backup(c: Circuit, p: Params) -> dict[str, Any] | None:
    """Smallest backup limit that makes the current requirement feasible, by bisection on [0, 100]."""

    def at(limit: float) -> dict[str, Any]:
        return solve(c, {**p, "backupEnabled": True, "backupLimit": limit})

    zero = at(0)
    if zero["best"]:
        return {"units": 0, "plan": zero["best"]}
    if not at(100)["best"]:
        return None
    lo, hi = 0.0, 100.0
    for _ in range(32):
        mid = (lo + hi) / 2
        if at(mid)["best"]:
            hi = mid
        else:
            lo = mid
    units = js_round(hi * 1e5) / 1e5
    final = at(units)
    if not final["best"]:
        units = hi
        final = at(units)
    return {"units": units, "plan": final["best"]}
