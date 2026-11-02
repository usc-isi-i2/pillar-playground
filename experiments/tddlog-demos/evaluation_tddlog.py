"""The forecast comparison's probabilities as a ProbLog program, answered by tddlog.

The page stocks three stores so that all three cover a floor fraction of demand (90%, or 80% in
an emergency) with probability at least 95%, at the least stock plus expected shortage cost. Its
demand model is the training days, in ProbLog:

- point forecast: one certain day whose demands are the training means;
- empirical distribution, joint: one of the n training days, each with probability 1/n, so the
  three stores' demands move together as they did on that day;
- empirical distribution, independent: each store draws its own day, so the stores' demands are
  independent with the same marginals.

A store covers its demand at stock A when A + 1e-8 >= floor * demand. tddlog returns each
store's coverage at every candidate stock level, each store's demand distribution (for the
expected shortage), and the probability that all three cover at once for the stock combinations
that can still qualify. The search over combinations and the held-out scoring stay as they were;
the search asks tddlog instead of counting training days.
"""

from __future__ import annotations

import math
from typing import Any

from problog_text import num, solve as run
from pillar_demos import evaluation as E
from pillar_demos.js import js_sum


def program(samples: list[list[float]], floor: float, independent: bool) -> list[str]:
    n = len(samples)
    lines = []
    if n == 1:
        lines.append("day(0).")
    elif independent:
        lines.append("% Each store draws its own day: independent demands, the same marginals.")
        for j in range(3):
            lines.append("; ".join(f"{num(1 / n)}::day({j}, {i})" for i in range(n)) + ".")
    else:
        lines.append("% One training day, each equally likely: the stores' demands move together.")
        lines.append("; ".join(f"{num(1 / n)}::day({i})" for i in range(n)) + ".")
    lines += [f"obs({i}, {j}, {num(x[j])})." for i, x in enumerate(samples) for j in range(3)]
    lines.append("demand(J, D) :- day(J, I), obs(I, J, D)." if independent and n > 1
                 else "demand(J, D) :- day(I), obs(I, J, D).")
    lines += [
        f"floor({num(floor)}).",
        "% A store covers its demand at stock A.",
        "cover(J, A) :- level(J, A), demand(J, D), floor(F), A + 1.0e-8 >= F * D.",
        "all_cover(A, B, C) :- combo(A, B, C), cover(0, A), cover(1, B), cover(2, C).",
    ]
    return lines


def solve(f: dict[str, Any], rules: dict[str, Any], uncertain: bool, capacity: float, dependence: str = "joint"):
    """The page's solve, with every probability and expectation from tddlog."""
    floor = 0.8 if rules["emergency"] else rules["priority_floor"]
    samples = [r["x"] for r in f["train"]] if uncertain else [f["mean"]]
    independent = dependence == "independent" and uncertain
    levels = []
    for j in range(3):  # the candidate stock levels, as the page builds them
        least = math.ceil(rules["base_floor"] * f["mean"][j])
        vals = {least}
        for x in samples:
            for v in (math.ceil(floor * x[j]), math.floor(x[j]), math.ceil(x[j])):
                vals.add(max(least, v))
        levels.append(sorted(vals))
    base = program(samples, floor, independent)
    facts = [f"level({j}, {num(a)})." for j in range(3) for a in levels[j]]

    # 1. Each store's coverage at each level, and its demand distribution.
    a1 = run("\n".join(base + facts + [f"query(cover({j}, {num(a)}))." for j in range(3) for a in levels[j]]
                       + [f"query(demand({j}, _))." for j in range(3)]), "forecast-coverage")
    cover = [{a: a1.get(f"cover({j},{num(a)})", 0.0) for a in levels[j]} for j in range(3)]
    demand = [{float(k[len(f"demand({j},"):-1]): p for k, p in a1.items() if k.startswith(f"demand({j},")}
              for j in range(3)]

    # 2. P(all three cover) where it matters: every combination whose stores each cover with
    # probability >= 0.95 (any other is below 0.95, as all three covering implies each does), and,
    # for the best probability reachable within capacity, the largest third level that fits.
    ok = [[a for a in levels[j] if cover[j][a] >= 0.95 - 1e-9] for j in range(3)]
    combos = {(a, b, c) for a in ok[0] for b in ok[1] for c in ok[2] if a + b + c <= capacity}
    for a in levels[0]:
        for b in levels[1]:
            fits = [c for c in levels[2] if a + b + c <= capacity]
            if fits:
                combos.add((a, b, fits[-1]))
    combos = sorted(combos)
    a2 = run("\n".join(base + facts + [f"combo({num(a)}, {num(b)}, {num(c)})." for a, b, c in combos]
                       + [f"query(all_cover({num(a)}, {num(b)}, {num(c)}))." for a, b, c in combos]), "forecast-joint")
    joint = {t: a2.get(f"all_cover({num(t[0])},{num(t[1])},{num(t[2])})", 0.0) for t in combos}
    max_p = max(joint.values(), default=0.0)

    # 3. The page's search, in its order, asking tddlog's answers instead of counting days.
    best = None
    for t in (t for t in combos if all(t[j] in ok[j] for j in range(3))):
        prob = joint[t]
        if prob < 0.95 - 1e-9:
            continue
        exp_short = sum(p * max(0.0, v - t[j]) for j in range(3) for v, p in demand[j].items())
        cost = sum(t) + 8 * exp_short
        if best is None or cost < best["cost"] - 1e-8:
            best = {"x": list(t), "cost": cost, "prob": prob}
    if best is None:
        return {"best": None, "maxP": max_p}
    # Held-out scoring: counted on the test days, as the page does (data, not inference).
    chosen, test = best["x"], f["test"]
    violated = sum(1 for r in test if any(chosen[j] + 1e-8 < 0.9 * d for j, d in enumerate(r["x"])))
    shortfall = sum(sum(max(0, d - chosen[j]) for j, d in enumerate(r["x"])) for r in test)
    return {"best": best, "maxP": max_p, "violation": violated / len(test),
            "realCost": js_sum(chosen) + 8 * shortfall / len(test)}


class Patched:
    """Within this block, the forecast comparison takes its probabilities from tddlog."""

    def __enter__(self):
        self.saved = E.solve
        E.solve = solve
        return self

    def __exit__(self, *exc):
        E.solve = self.saved
