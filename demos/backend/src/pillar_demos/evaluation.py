"""Forecasting and decision evaluation for a three-store stocking problem.

Shared by both demos. A point forecast (per-store training mean) and an empirical distribution
(the training vectors) each pick stock levels; both are scored on the same held-out dates.

A port of the original pages' module; results match it exactly (see tests/test_evaluation.py).
"""

from __future__ import annotations

import math
import re
from typing import Any

from .js import js_number, js_round, js_sum, js_trim, mulberry32

Dataset = dict[str, Any]
STORES = ["Store A", "Store B", "Store C"]


class EvaluationError(ValueError):
    """Bad input data or rules. The message is shown to the operator."""


def synthetic(kind: str) -> Dataset:
    r = mulberry32(42)
    rows = []
    for t in range(80):
        common = 1.5 if r() < 0.2 else 0.9
        x = []
        for m in (40, 55, 65):
            factor = (1.5 if r() < 0.2 else 0.9) if kind == "independent" else common
            x.append(js_round(m * factor * (0.95 + 0.1 * r()) * (1.35 if kind == "shift" and t >= 56 else 1)))
        rows.append({"date": str(t + 1).zfill(3), "x": x})
    return {"rows": rows, "stores": list(STORES), "source": f"Synthetic {kind} demand, seed 42"}


def parse(raw: str) -> Dataset:
    """Parse a date,store_id,demand CSV with exactly three stores.

    Dates are ordered by plain string comparison. The original used ``localeCompare``, which
    orders ISO dates and zero-padded numbers the same way.
    """
    lines = [[js_trim(v) for v in line.split(",")] for line in re.split(r"\r?\n", js_trim(raw))]
    h = lines.pop(0)
    if any(name not in h for name in ("date", "store_id", "demand")):
        raise EvaluationError(
            "CSV needs date,store_id,demand columns."
            " Aggregate one category to one observation per date/store."
        )
    d, s, v = h.index("date"), h.index("store_id"), h.index("demand")

    def cell(line: list[str], i: int) -> str | None:
        return line[i] if i < len(line) else None

    stores = sorted({cell(line, s) for line in lines}, key=lambda x: (x is None, x or ""))
    if len(stores) != 3:
        raise EvaluationError("This reference evaluation supports exactly three stores.")
    by: dict[str, dict[Any, float]] = {}
    for line in lines:
        date, store, demand = cell(line, d), cell(line, s), cell(line, v)
        value = js_number(demand) if demand is not None else math.nan
        if not date or not math.isfinite(value) or value < 0:
            raise EvaluationError("Invalid date or nonnegative demand.")
        if store in by.setdefault(date, {}):
            raise EvaluationError("Duplicate date/store. Aggregate categories before upload.")
        by[date][store] = value
    rows = []
    for date in sorted(by):
        o = by[date]
        if any(st not in o for st in stores):
            raise EvaluationError("Each date needs all three stores.")
        rows.append({"date": date, "x": [o[st] for st in stores]})
    if len(rows) < 20 or len(rows) > 160:
        raise EvaluationError("Use 20–160 dates for this small exact reference model.")
    return {
        "rows": rows,
        "stores": stores,
        "source": "Uploaded demand observations (provenance supplied by user)",
    }


def rules(o: Any) -> dict[str, Any]:
    """Check a rule translation: exactly these three fields, fractions in (0,1]."""

    def fraction(n: Any) -> bool:
        return isinstance(n, (int, float)) and not isinstance(n, bool) and 0 < n <= 1

    if (
        not isinstance(o, dict)
        or ",".join(sorted(o)) != "base_floor,emergency,priority_floor"
        or not isinstance(o["emergency"], bool)
        or not (fraction(o["base_floor"]) and fraction(o["priority_floor"]))
    ):
        raise EvaluationError(
            "Rules require only priority_floor and base_floor in (0,1], and boolean emergency."
        )
    return o


def fit(data: Dataset) -> dict[str, Any]:
    """First 70% of dates train, the rest test."""
    cut = math.floor(len(data["rows"]) * 0.7)
    train, test = data["rows"][:cut], data["rows"][cut:]
    mean = [js_sum(r["x"][j] for r in train) / len(train) for j in range(3)]
    return {"train": train, "test": test, "mean": mean, "cut": cut}


def solve(
    f: dict[str, Any], rules: dict[str, Any], uncertain: bool, capacity: float, dependence: str = "joint"
):
    """Exhaustive search over demand breakpoints for the cheapest plan meeting the floor with p >= 0.95."""
    floor = 0.8 if rules["emergency"] else rules["priority_floor"]
    samples = [r["x"] for r in f["train"]] if uncertain else [f["mean"]]
    n = len(samples)
    levels = []
    for j in range(3):
        least = math.ceil(rules["base_floor"] * f["mean"][j])
        vals = {least}
        for x in samples:
            for v in (math.ceil(floor * x[j]), math.floor(x[j]), math.ceil(x[j])):
                vals.add(max(least, v))
        levels.append(sorted(vals))

    # For each store and level: which samples it covers (as a bitset), and how many.
    covers = [
        {a: sum(1 << i for i, x in enumerate(samples) if a + 1e-8 >= floor * x[j]) for a in levels[j]}
        for j in range(3)
    ]
    independent = dependence == "independent" and uncertain

    best: dict[str, Any] | None = None
    max_p = 0.0
    for a in levels[0]:
        for b in levels[1]:
            for c in levels[2]:
                x = [a, b, c]
                total = a + b + c
                if total > capacity:
                    continue
                if independent:
                    prob = 1.0
                    for j in range(3):
                        prob = prob * covers[j][x[j]].bit_count() / n
                else:
                    prob = (covers[0][a] & covers[1][b] & covers[2][c]).bit_count() / n
                max_p = max(max_p, prob)
                if prob < 0.95 - 1e-9:
                    continue
                z = 0.0
                for v in samples:
                    q = 0.0
                    for j in range(3):
                        q += max(0, v[j] - x[j])
                    z += q
                cost = total + 8 * (z / n)
                if best is None or cost < best["cost"] - 1e-8:
                    best = {"x": x, "cost": cost, "prob": prob}
    if best is None:
        return {"best": None, "maxP": max_p}
    chosen = best["x"]
    test = f["test"]
    violated = sum(1 for r in test if any(chosen[j] + 1e-8 < 0.9 * d for j, d in enumerate(r["x"])))
    shortfall = 0.0
    for r in test:
        s = 0.0
        for j, d in enumerate(r["x"]):
            s += max(0, d - chosen[j])
        shortfall += s
    return {
        "best": best,
        "maxP": max_p,
        "violation": violated / len(test),
        "realCost": js_sum(chosen) + 8 * shortfall / len(test),
    }


def run(data: Dataset, rules: dict[str, Any], capacity: float, dependence: str) -> dict[str, Any]:
    f = fit(data)
    return {
        "f": f,
        "point": solve(f, rules, False, capacity),
        "uncertain": solve(f, rules, True, capacity, dependence),
    }
