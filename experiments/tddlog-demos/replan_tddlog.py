"""PILLAR Replan's probabilities as a ProbLog program, answered by tddlog.

The model, in ProbLog (storm preset; the toy has only S4's three demands):

- the storm misses, grazes or makes landfall;
- given the storm, the Texas sales surge is low, medium or high, an emergency is declared or not,
  the advisory reads none, watch or warning, the Texas DC runs at 100%, 70% or 40% of capacity, and
  the CA-to-TX lane closes or not;
- the operator's evidence observes some of these (the advisory, the sales signal, the emergency;
  capacity and lane status always);
- each store and category has a five-point demand, raised in Texas by the surge;
- a priority store meets the rule when demand times its service fraction (lowered under a
  declared emergency by the exception rule) is at most what it receives.

tddlog returns the posterior of the storm, surge and emergency, each store's demand marginal,
the probability of the rule at every candidate amount (which gives the chance thresholds), and a
plan's probability that every priority store meets the rule. These replace the page's
enumeration of the 18 configurations (build_model's weights, _chance_threshold, _p_rule_met,
_p_all_met). The LP that picks the shipments, the most-likely-world plan (tddlog has no MPE query)
and the sampled backtest are unchanged.
"""

from __future__ import annotations

from typing import Any

from problog_text import atom, num, solve
from pillar_demos import replan as R
from pillar_demos.js import js_round, js_str

Z = ["miss", "graze", "landfall"]
U = ["low", "medium", "high"]
CAPS = {"1": "full", "0.7": "reduced", "0.4": "low"}


def ad(pairs: list[tuple[float, str]], body: str = "") -> str:
    """An annotated disjunction; equal heads are merged (their probabilities add)."""
    merged: dict[str, float] = {}
    for p, head in pairs:
        merged[head] = merged.get(head, 0.0) + p
    text = "; ".join(f"{num(p)}::{head}" for head, p in merged.items() if p > 0)
    return f"{text} :- {body}." if body else f"{text}."


def demand_atoms(mu: float, cv: float) -> list[tuple[float, int]]:
    return [(R.EPS_P[i], js_round(mu * (1 + cv * zz / R.EPS_SD))) for i, zz in enumerate(R.EPS_Z)]


class Program:
    """The ProbLog text of one (preset, spec, evidence) model, and the queries asked of it."""

    def __init__(self, preset_id: str, spec: dict[str, Any], ev: dict[str, Any],
                 overrides: dict[str, Any] | None = None, custom: dict[str, Any] | None = None):
        overrides = overrides or {}
        P = R.PRESETS[preset_id]
        self.storm = preset_id == "storm"
        stores, cats = [s["id"] for s in P["stores"]], list(P["cats"])
        self.keys = [s + "|" + c for s in stores for c in cats]
        self.name = {k: atom(k) for k in self.keys}
        self.prio = {s + "|" + r["category"]: r["fraction"] for r in spec.get("priority") or []
                     for s in r["stores"] if s in stores and r["category"] in cats}
        exc = spec.get("exception")
        lines: list[str] = []
        self.values: dict[str, set[float]] = {k: set() for k in self.keys}  # demand values per key
        if not self.storm:
            lines.append("% Toy: S1-S3 demand is known; S4's is 60, 70 or 80.")
            fixed = {"S1|units": 50, "S2|units": 40, "S3|units": 45}
            for k, v in fixed.items():
                lines.append(f"demand({self.name[k]}, {v}).")
                self.values[k].add(v)
            lines.append(ad([(0.15, f"demand({self.name['S4|units']}, 60)"), (0.55, f"demand({self.name['S4|units']}, 70)"),
                             (0.30, f"demand({self.name['S4|units']}, 80)")]))
            self.values["S4|units"] |= {60, 70, 80}
        else:
            lines.append("% The storm, and what it influences.")
            lines.append(ad([(p, f"z({z})") for p, z in zip(P["pZ"], Z)]))
            for zi, z in enumerate(Z):
                lines.append(ad([(P["pU"][zi][ui], f"u({u})") for ui, u in enumerate(U)], f"z({z})"))
                lines.append(f"{num(P['pEmerg'][zi])}::emerg :- z({z}).")
                lines.append(ad([(P["pAdv"][a][zi], f"adv({a})") for a in P["pAdv"]], f"z({z})"))
                lines.append(ad([(P["pCap"][c][zi], f"cap({CAPS[c]})") for c in P["pCap"]], f"z({z})"))
                lines.append(f"{num(P['pLaneClosed'][zi])}::lane_closed :- z({z}).")
            for ui, u in enumerate(U):
                lines.append(ad([(P["pSales"][s][ui], f"sales({s})") for s in P["pSales"]], f"u({u})"))
            lines.append("% What the operator observed.")
            if ev["advisory"] != "unknown":
                lines.append(f"evidence(adv({ev['advisory']}), true).")
            if ev["sales"] != "unknown":
                lines.append(f"evidence(sales({ev['sales']}), true).")
            lines.append(f"evidence(cap({CAPS[js_str(ev['txCap'])]}), true).")
            closed = (overrides.get("caLane") or ev["caLane"]) == "closed"
            lines.append(f"evidence(lane_closed, {'true' if closed else 'false'}).")
            if ev["emergency"] == "declared":
                lines.append("evidence(emerg, true).")
            if ev["emergency"] == "not_declared":
                lines.append("evidence(emerg, false).")
            lines.append("% Each store and category: a five-point demand, Texas raised by the surge.")
            for s in P["stores"]:
                for c in cats:
                    k = s["id"] + "|" + c
                    m = custom["base"][k] if custom and custom["base"].get(k) is not None else s["weekly"] * P["share"][c]
                    if ev["week"] == "snap" and c == "FOODS":
                        m *= 1.06
                    base = js_round(m)
                    cv = custom["cv"][k] if custom and custom["cv"].get(k) is not None else P["cv"][c]
                    if s["state"] != "TX":
                        atoms = demand_atoms(base, cv)
                        lines.append(ad([(p, f"demand({self.name[k]}, {num(v)})") for p, v in atoms]))
                        self.values[k] |= {v for _, v in atoms}
                        continue
                    for ui, u in enumerate(U):
                        sg = P["surge"][ui]
                        mu = base * (1 + sg if c == "FOODS" else 1 + 0.8 * sg if c == "HOUSEHOLD" else 1 - 0.5 * sg)
                        atoms = demand_atoms(mu, cv)
                        lines.append(ad([(p, f"demand({self.name[k]}, {num(v)})") for p, v in atoms], f"u({u})"))
                        self.values[k] |= {v for _, v in atoms}
        lines.append("% The service fraction of each priority store; the exception rule lowers it.")
        self.fracs: dict[str, list[float]] = {}
        for k, f in self.prio.items():
            if self.storm and exc and min(f, exc["fraction"]) != f:
                lines.append(f"frac({self.name[k]}, {num(min(f, exc['fraction']))}) :- emerg.")
                lines.append(f"frac({self.name[k]}, {num(f)}) :- \\+ emerg.")
                self.fracs[k] = [f, min(f, exc["fraction"])]
            else:
                lines.append(f"frac({self.name[k]}, {num(f)}).")
                self.fracs[k] = [f]
        lines += [
            "% A priority store meets the rule when its demand times the fraction fits what it gets.",
            "met_at(K, Q) :- cand(K, Q), demand(K, D), frac(K, F), D =< Q / F + 1.0e-9.",
            "met(K) :- recv(K, Q), demand(K, D), frac(K, F), D =< Q / F + 1.0e-9.",
        ]
        self.text = lines
        self._answers: dict[str, dict[str, float]] = {}

    def ask(self, extra: list[str]) -> dict[str, float]:
        program = "\n".join(self.text + extra)
        if program not in self._answers:
            answers = solve(program)
            if answers is None:
                raise ValueError("The evidence has zero probability under this model.")
            self._answers[program] = answers
        return self._answers[program]

    # ---------- the queries

    def posterior(self) -> dict[str, Any]:
        a = self.ask(["query(z(_)).", "query(u(_)).", "query(emerg)."])
        return {"z": [a.get(f"z({z})", 0.0) for z in Z], "u": [a.get(f"u({u})", 0.0) for u in U],
                "e": a.get("emerg", 0.0)}

    def marginals(self) -> dict[str, list[list[float]]]:
        """Each key's demand distribution, as build_model's M["marg"]: [value, probability] by value."""
        a = self.ask([f"query(demand({self.name[k]}, _))." for k in self.keys])
        return {k: [[v, a[f"demand({self.name[k]},{num(v)})"]] for v in sorted(self.values[k])
                    if a.get(f"demand({self.name[k]},{num(v)})", 0.0) > 1e-15] for k in self.keys}

    def threshold(self, key: str, tau: float) -> float:
        """The smallest candidate amount q with P(rule met at key | q) >= tau."""
        fracs = list(self.fracs[key])
        if len(fracs) > 1:  # drop a fraction whose condition the evidence rules out
            e = self.posterior()["e"]
            fracs = [f for f, w in zip(fracs, (1 - e, e)) if w > 0]
        values = [v for v, _ in self.marginals()[key]]
        cands = sorted({v * f for v in values for f in fracs})
        n = self.name[key]
        a = self.ask([f"cand({n}, {num(q)})." for q in cands] + [f"query(met_at({n}, {num(q)}))." for q in cands])
        for q in cands:
            if a.get(f"met_at({n},{num(q)})", 0.0) >= tau - 1e-12:
                return q
        return cands[-1]

    def rules_met(self, q: dict[str, float]) -> dict[str, float]:
        """P(met) at each priority key and P(all met), for the amounts q a plan delivers."""
        names = [self.name[k] for k in self.prio]
        a = self.ask([f"recv({self.name[k]}, {num(q[k])})." for k in self.prio]
                     + ["all_met :- " + ", ".join(f"met({n})" for n in names) + "."]
                     + [f"query(met({n}))." for n in names] + ["query(all_met)."])
        out = {k: a.get(f"met({self.name[k]})", 0.0) for k in self.prio}
        out["*all*"] = a.get("all_met", 0.0)
        return out


class Patched:
    """Within this block, the Replan engine takes its demand marginals, chance thresholds and rule
    probabilities from tddlog. Each model build gets its own Program."""

    def __enter__(self):
        self.saved = R.build_model, R._chance_threshold, R._p_rule_met, R._p_all_met
        build = self.saved[0]

        programs: dict[int, Program] = {}  # by id of the model; the model itself is JSON, so not on it

        def build_model(preset_id, spec, ev, overrides=None, custom=None):
            M = build(preset_id, spec, ev, overrides, custom)
            programs[id(M)] = prog = Program(preset_id, spec, ev, overrides, custom)
            self.models.append(M)  # keeps M alive, so its id is not reused
            M["marg"] = prog.marginals()
            return M

        self.models: list = []
        R.build_model = build_model
        R._chance_threshold = lambda M, key, tau: programs[id(M)].threshold(key, tau)
        R._p_rule_met = lambda M, key, q: programs[id(M)].rules_met({**dict.fromkeys(M["prio"], 0.0), key: q})[key]
        R._p_all_met = lambda M, qmap: programs[id(M)].rules_met(qmap)["*all*"]
        return self

    def __exit__(self, *exc):
        R.build_model, R._chance_threshold, R._p_rule_met, R._p_all_met = self.saved
