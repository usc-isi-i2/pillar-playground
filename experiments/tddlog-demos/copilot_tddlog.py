"""Circuit Copilot's probabilities as a ProbLog program, answered by tddlog.

The model, in ProbLog:

- one of three worlds holds, Normal, Surge or Storm, with the priors the page derives from the
  storm probability; reported evidence names the world that was observed;
- S4's demand is 60, 70 or 80 in those worlds, and in the storm scenario depot A's shipment to S4
  arrives late in the Storm world;
- a plan's shipments are facts, and the priority rule holds in a world when S1 receives at least
  alpha * 50 and S4 at least alpha * its demand there.

tddlog returns each world's posterior and, for each plan, the probability that the rule holds
given the evidence. These replace the page's hand-built arithmetic circuit (compile_circuit,
world_weights, evaluate); the LPs that propose the plans are unchanged.
"""

from __future__ import annotations

from typing import Any

from problog_text import atom, num, solve
from pillar_demos import copilot as C

WORLDS = ["Normal", "Surge", "Storm"]


def model(p: dict[str, Any]) -> list[str]:
    """The worlds, the evidence and the rule, without any plan."""
    q = p["stormProbability"]
    prior = [(1 - q) * 0.15 / 0.7, (1 - q) * 0.55 / 0.7, q]
    lines = [
        "% One of three worlds; priors from the storm probability.",
        "; ".join(f"{num(pr)}::world({atom(w)})" for pr, w in zip(prior, WORLDS)) + ".",
        *(f"demand({atom(w)}, {d})." for w, d in zip(WORLDS, C.DEMAND)),
        "% Depot A's shipment to S4 arrives late in the Storm world of the storm scenario.",
        "late(storm)." if p["scenario"] == "storm" else "late(no_world).",
        f"alpha({num(C.alpha(p))}).",
        "% Units each plan delivers to S1 and S4 in each world.",
        "recv(P, W, s1, Y) :- world(W), ship(P, a, s1, A), ship(P, b, s1, B), Y is A + B.",
        "a_s4(P, W, A) :- world(W), \\+ late(W), ship(P, a, s4, A).",
        "a_s4(P, W, 0) :- world(W), late(W).",
        "recv(P, W, s4, Y) :- a_s4(P, W, A), ship(P, b, s4, B), backup(P, L), Y is A + B + L.",
        "% The priority rule holds in the world that occurs.",
        "holds(P) :- world(W), demand(W, D), alpha(Al),",
        "    recv(P, W, s1, Y1), Y1 + 1.0e-7 >= Al * 50,",
        "    recv(P, W, s4, Y4), Y4 + 1.0e-7 >= Al * D.",
    ]
    if p["evidence"] != "all":
        lines.append(f"evidence(world({atom(p['evidence'])}), true).")
    return lines


def plan_facts(i: int, x: list[float]) -> list[str]:
    names = ["s1", "s2", "s3", "s4"]
    return [
        *(f"ship(p{i}, a, {s}, {num(x[j])})." for j, s in enumerate(names)),
        *(f"ship(p{i}, b, {s}, {num(x[4 + j])})." for j, s in enumerate(names)),
        f"backup(p{i}, {num(x[8])}).",
    ]


def world_weights(c: dict[str, Any], p: dict[str, Any]) -> list[float]:
    answers = solve("\n".join(model(p) + ["query(world(_))."]), f"copilot-{p['scenario']}-worlds")
    if answers is None:
        raise C.ValidationError("The selected evidence has zero probability under this model.")
    return [answers.get(f"world({atom(w)})", 0.0) for w in WORLDS]


def evaluate(c: dict[str, Any], x: list[float], p: dict[str, Any]) -> dict[str, Any]:
    answers = solve("\n".join(model(p) + plan_facts(0, x) + ["query(holds(p0))."]), f"copilot-{p['scenario']}-plan")
    if answers is None:
        raise C.ValidationError("Evidence has zero probability.")
    return {"probability": answers["holds(p0)"], "values": []}


def independence_contrast() -> dict[str, Any]:
    """The page's fixed example, both ways in ProbLog: once with the late delivery tied to the
    Storm world, once with it an independent 30% chance."""
    x = [50, 40, 31, 9, 0, 0, 0, 50, 13]
    p = {**C.BASE, "scenario": "storm", "backupEnabled": True, "tau": 0.9}
    joint = evaluate(None, x, p)["probability"]
    independent = solve("\n".join([
        "0.15::d(60); 0.55::d(70); 0.3::d(80).",
        "0.7::timely.",
        "a_s4(9) :- timely.",
        "a_s4(0) :- \\+ timely.",
        "holds :- d(D), a_s4(A), 50 + 13 + A >= 0.9 * D - 1.0e-7.",
        "query(holds).",
    ]), "copilot-independent-delay")["holds"]
    return {"x": x, "joint": joint, "independent": independent,
            "failureJoint": 1 - joint, "failureIndependent": 1 - independent}


class Patched:
    """Within this block, the Copilot engine takes every probability from tddlog."""

    def __enter__(self):
        self.saved = C.world_weights, C.evaluate
        C.world_weights, C.evaluate = world_weights, evaluate
        return self

    def __exit__(self, *exc):
        C.world_weights, C.evaluate = self.saved
