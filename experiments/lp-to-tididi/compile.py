"""Compile the PILLAR demo LPs into tididi circuits and solve them on the circuit.

Reads the solver-ready models (models.json in the PILLAR_Solver_Models folder) and, per demo:

- Circuit Copilot: the exact joint-chance MILPs (`copilot_*_exact_milp`).
- PILLAR Replan: the toy LPs (`replan_toy_tau070`, `replan_toy_tau095`). The storm LPs are not
  compiled: about 100k units of demand across 30 store items and three DC capacities in the tens of
  thousands, so a unit encoding needs ~100k Boolean variables and a triple of partial sums at
  every cut. They are continuous LPs with a fractional optimum and no discrete choice to exploit.
- Stocking: `stocking_point_integer` and the joint-chance MILP `stocking_joint_integer_milp` (56
  equally likely worlds, at most 2 may break the priority rule).

Method. tididi circuits are Boolean, so shipments are integer units, order-encoded: an integer
x in [lo, hi] becomes bits b_t = [x >= t]. Each LP row becomes a circuit (a dynamic program over
partial sums); the circuits are conjoined into one, over a vtree that keeps each site's variables
together. tididi weights live on literals, so the
objective must be a sum of per-variable costs. Shortage costs depend on what a store receives in
total, so the plan is written in coordinates where that holds: per store, units received Y and
units from DC A (B's share is Y - A). Evaluating the circuit in the (min, +) semiring gives the
cheapest plan; it is decoded and checked against the original LP rows.

    PILLAR_SOLVER_MODELS=path/to/PILLAR_Solver_Models python compile.py
"""

from __future__ import annotations

import json
import math
import os
import time
from fractions import Fraction
from pathlib import Path

import tididi as T

PKG = Path(os.environ.get("PILLAR_SOLVER_MODELS", "~/Downloads/PILLAR_Solver_Models")).expanduser()
MODELS = {m["id"]: m for m in json.loads((PKG / "models.json").read_text())}
VALIDATION = {v["model"]: v for v in json.loads((PKG / "validation_results.json").read_text())}


class IntProgram:
    """Bounded integer and Boolean variables, linear constraints with integer coefficients (each
    optionally switched off by a Boolean guard), and a separable objective sum_i f_i(x_i)."""

    def __init__(self, limits: T.Limits | None = None):
        self.limits = limits  # tididi memory/time limits for every operation; None means none
        self.next_var = 1
        self.ints: dict[str, tuple[int, int, list[int]]] = {}  # name -> (lo, hi, bit variables)
        self.bools: dict[str, int] = {}
        self.order: list[int] = []  # all Boolean variables, in creation order
        self.costs: dict[str, object] = {}
        self.rows: list[tuple[list[tuple[int, str]], int, str | None]] = []  # (terms, K, guard)
        self.patterns: list[tuple[list[str], list[tuple[bool, ...]]]] = []  # allowed Boolean rows
        self.groups: list[list[str]] = []  # integer variables kept together in the vtree

    def int_var(self, name: str, lo: int, hi: int, cost=None) -> None:
        bits = list(range(self.next_var, self.next_var + hi - lo))
        self.next_var += hi - lo
        self.ints[name] = (lo, hi, bits)
        self.order += bits
        self.costs[name] = cost or (lambda v: 0.0)

    def bool_var(self, name: str) -> None:
        self.bools[name] = self.next_var
        self.order.append(self.next_var)
        self.next_var += 1

    def le(self, terms: list[tuple[int, str]], K: int, unless: str | None = None) -> None:
        """sum(coef * x) <= K, or the Boolean `unless` is true. A Boolean x counts as 0 or 1."""
        self.rows.append((terms, K, unless))

    def ge(self, terms, K, unless=None):
        self.le([(-c, x) for c, x in terms], -K, unless)

    def group(self, names: list[str]) -> None:
        """Keep these integer variables (typically one site's) together in the vtree."""
        self.groups.append(names)

    def allowed(self, names: list[str], rows: list[tuple[bool, ...]]) -> None:
        """The Boolean variables `names` must take one of these value patterns."""
        self.patterns.append((names, rows))

    # ---------- compilation

    def _and(self, a, b):
        return T.and_(a, b, limits=self.limits)

    def _domain(self, name):
        """(lo, hi, bits) of an integer, or of a Boolean read as an integer in [0, 1]."""
        return (0, 1, [self.bools[name]]) if name in self.bools else self.ints[name]

    def _interval(self, vt, name, v1, v2):
        """v1 <= x <= v2 over valid order encodings only. The bits outside the interval are fixed
        and the bits inside are chained, so the circuit is false on non-monotone bit patterns.
        Without that, the rows disagree on invalid patterns and a row's circuit has to remember
        which subset of a variable's bits is set: exponential in the bit count."""
        lo, hi, bits = self._domain(name)
        inside = bits[v1 - lo : v2 - lo]  # x >= t for v1 < t <= v2
        c = T.cube(vt, bits[: v1 - lo] + [-b for b in bits[v2 - lo :]])  # x >= v1, not x >= v2 + 1
        for a, b in zip(inside, inside[1:]):
            c = self._and(c, T.clause(vt, [-b, a]))
        return c

    def _row(self, vt, terms, K):
        """sum(c * x) <= K as a circuit: a walk over the terms carrying the running sum s. A state
        (i, s) is decided ("T"/"F") once the remaining terms cannot change the outcome. Built one
        layer at a time from the last term back, so only two layers of circuits are alive at once:
        every live circuit costs memory in proportion to the vtree."""
        n = len(terms)
        lo_sum, hi_sum = [0] * (n + 1), [0] * (n + 1)
        for i in reversed(range(n)):
            c, x = terms[i]
            lo, hi, _ = self._domain(x)
            lo_sum[i] = lo_sum[i + 1] + min(c * lo, c * hi)
            hi_sum[i] = hi_sum[i + 1] + max(c * lo, c * hi)

        def status(i, s):
            return "T" if s + hi_sum[i] <= K else "F" if s + lo_sum[i] > K else None

        layers = [{0}]  # undecided running sums reachable before term i
        for i, (c, x) in enumerate(terms):
            lo, hi, _ = self._domain(x)
            layers.append({s + c * v for s in layers[i] for v in range(lo, hi + 1) if status(i + 1, s + c * v) is None})
        below: dict[int, T.Circuit] = {}
        for i in reversed(range(n)):
            c, x = terms[i]
            lo, hi, _ = self._domain(x)
            here = {}
            for s in layers[i]:
                if status(i, s) is not None:
                    continue
                groups: list[list] = []  # consecutive values with the same continuation
                for v in range(lo, hi + 1):
                    k = status(i + 1, s + c * v) or s + c * v
                    if groups and groups[-1][2] == k:
                        groups[-1][1] = v
                    else:
                        groups.append([v, v, k])
                parts = []
                for v1, v2, k in groups:
                    if k == "F":
                        continue
                    part = self._interval(vt, x, v1, v2)
                    if k != "T":
                        part = self._and(part, below[k].copy())  # operations consume operands
                    parts.append(part)
                here[s] = T.or_many(parts, limits=self.limits) if parts else T.zero(vt)
            below = here
        k = status(0, 0)
        return T.one(vt) if k == "T" else T.zero(vt) if k == "F" else below[0]

    def vtree(self):
        """Booleans on the left; on the right, a balanced tree of groups, each a balanced tree of
        its variables, each variable a linear vtree over its bits. With one linear vtree over all
        bits instead, every cut carries the partial sums of both capacity rows and the Copilot
        circuits grow to millions of nodes; grouped by site, they are tens of thousands."""

        def balanced(ts):
            while len(ts) > 1:
                ts = [T.Vtree.join(*ts[i : i + 2]) if i + 1 < len(ts) else ts[i] for i in range(0, len(ts), 2)]
            return ts[0]

        def bits(name):
            b = self.ints[name][2]
            return T.Vtree.linear(b) if len(b) > 1 else T.Vtree.leaf(b[0])

        grouped = {n for g in self.groups for n in g}
        groups = self.groups + [[n] for n in self.ints if n not in grouped]
        trees = [balanced([bits(n) for n in g if self.ints[n][2]]) for g in groups if any(self.ints[n][2] for n in g)]
        rest = balanced(trees)
        return T.Vtree.join(balanced([T.Vtree.leaf(b) for b in self.bools.values()]), rest) if self.bools else rest

    def compile(self, vt=None, verbose=False):
        """Conjoin the order-encoding clauses, the Boolean patterns and the rows into one circuit.
        Each part is conjoined as soon as it is built, so only one is alive at a time."""
        vt = vt or self.vtree()

        def parts():
            for lo, hi, bits in self.ints.values():  # order encoding: x >= t+1 implies x >= t
                for a, b in zip(bits, bits[1:]):
                    yield T.clause(vt, [-b, a])
            for names, rows in self.patterns:
                yield T.from_models(vt, [self.bools[n] for n in names], rows)
            for terms, K, unless in self.rows:
                c = self._row(vt, terms, K)
                if unless:
                    c = T.or_(c, T.literal(vt, self.bools[unless]), limits=self.limits)
                yield c

        circuit = T.one(vt)
        for i, p in enumerate(parts()):
            circuit = self._and(circuit, p)
            if verbose and i % 50 == 0:
                print(f"    after part {i}: {circuit.node_count()} nodes", flush=True)
        return vt, circuit

    # ---------- optimisation in the (min, +) semiring

    def minimise(self, circuit):
        weight = {}  # Boolean variable -> cost when true (cost when false is 0)
        constant = 0.0
        for name, (lo, hi, bits) in self.ints.items():
            f = self.costs[name]
            constant += f(lo)
            for t, b in zip(range(lo + 1, hi + 1), bits):
                weight[b] = f(t) - f(t - 1)
        for name, b in self.bools.items():
            weight[b] = self.costs.get(name, 0.0) if not callable(self.costs.get(name)) else 0.0

        class MinPlus:
            # Values are (cost, witness); the witness is a tree of the true literals chosen.
            def zero(self):
                return (math.inf, None)

            def leaf(self, var, sign):
                w = weight.get(var, 0.0)
                if sign is None:  # variable free here: take the cheaper value
                    sign = w < 0
                return (w, ("L", var)) if sign else (0.0, None)

            def add(self, a, b):
                return a if a[0] <= b[0] else b

            def mul(self, a, b):
                return (a[0] + b[0], ("M", a[1], b[1]))

        cost, witness = circuit.evaluate(MinPlus())
        if math.isinf(cost):
            return None, None
        true_vars, stack = set(), [witness]
        while stack:
            w = stack.pop()
            if w is None:
                continue
            if w[0] == "L":
                true_vars.add(w[1])
            else:
                stack += [w[1], w[2]]
        values = {n: lo + sum(b in true_vars for b in bits) for n, (lo, hi, bits) in self.ints.items()}
        values |= {n: b in true_vars for n, b in self.bools.items()}
        return cost + constant, values


# ---------- reading the LP files


def term_vars(model, row):
    return {model["names"][int(j)]: v for j, v in row["a"].items() if v}


def check_against_lp(model, x):
    """Plug a full LP solution into the original rows and objective."""
    vals = [x[n] for n in model["names"]]
    for r in model["rows"]:
        lhs = sum(v * vals[int(j)] for j, v in r["a"].items())
        ok = lhs <= r["b"] + 1e-6 if r["op"] == "<=" else lhs >= r["b"] - 1e-6 if r["op"] == ">=" else abs(lhs - r["b"]) < 1e-6
        if not ok:
            return None, f"violates {r.get('name')}: {lhs} {r['op']} {r['b']}"
    for n, ub in model.get("upper", {}).items():
        if x[n] > ub + 1e-9:
            return None, f"violates bound {n} <= {ub}"
    return sum(c * v for c, v in zip(model["c"], vals)), "all rows hold"


def copilot_program(model):
    """The Copilot joint-chance MILP in coordinates Y_j = units reaching site j in time (A + B, and
    the backup for S4), A_j = units from depot A; for S4 also U4 = B4 + L (what still arrives when
    A->S4 is late) and L = backup."""
    rows = {r["name"]: r for r in model["rows"]}
    cost = dict(zip(model["names"], model["c"]))
    worlds = sorted({int(n[len("violate_w")]) for n in model["names"] if n.startswith("violate_w")})
    sites = [1, 2, 3, 4]
    late_world = [w for w in worlds if "x_A_S4" not in term_vars(model, rows[f"floor_w{w}_S4"])]
    demand = {(w, j): rows[f"shortage_w{w}_S{j}"]["b"] for w in worlds for j in sites}
    floor = {(w, j): rows[f"floor_w{w}_S{j}"]["b"] for w in worlds for j in sites}
    penalty = {(w, j): cost[f"shortage_w{w}_S{j}"] for w in worlds for j in sites}  # pi_w * rho_j
    budget = rows["joint_violation_budget"]
    prob = {int(model["names"][int(k)][len("violate_w")]): v for k, v in budget["a"].items()}
    backup_ub = int(model.get("upper", {}).get("backup_S4", 0))

    def shortage_cost(j, ws):
        return lambda y: sum(penalty[(w, j)] * max(0.0, demand[(w, j)] - y) for w in ws)

    P = IntProgram()
    for w in worlds:
        P.bool_var(f"v{w}")
    allowed = [p for p in __import__("itertools").product([False, True], repeat=len(worlds))
               if sum(prob[w] for w, on in zip(worlds, p) if on) <= budget["b"] + 1e-12]
    P.allowed([f"v{w}" for w in worlds], allowed)
    on_time = [w for w in worlds if w not in late_world]
    for j in sites[:3]:
        hi = int(max(demand[(w, j)] for w in worlds))  # shipping more never lowers cost
        lo = int(math.ceil(max(floor[(w, j)] for w in worlds)))
        cA, cB = cost[f"x_A_S{j}"], cost[f"x_B_S{j}"]
        sc = shortage_cost(j, worlds)
        P.int_var(f"Y{j}", lo, hi, lambda y, cB=cB, sc=sc: cB * y + sc(y))
        P.int_var(f"A{j}", 0, hi, lambda a, cA=cA, cB=cB: (cA - cB) * a)
        P.le([(1, f"A{j}"), (-1, f"Y{j}")], 0)  # B_j = Y_j - A_j >= 0
        P.group([f"Y{j}", f"A{j}"])
    hi4 = int(max(demand[(w, 4)] for w in worlds))
    cA4, cB4, cL = cost["x_A_S4"], cost["x_B_S4"], cost["backup_S4"]
    sY, sU = shortage_cost(4, on_time), shortage_cost(4, late_world)
    P.int_var("Y4", int(math.ceil(max(floor[(w, 4)] for w in on_time))), hi4, lambda y: cA4 * y + sY(y))
    u_lo = int(math.ceil(max([floor[(w, 4)] for w in late_world], default=0)))
    P.int_var("U4", u_lo, hi4, lambda u: (cB4 - cA4) * u + sU(u))
    P.int_var("L", 0, backup_ub, lambda l: (cL - cB4) * l)
    P.le([(1, "U4"), (-1, "Y4")], 0)  # A4 = Y4 - U4 >= 0
    P.le([(1, "L"), (-1, "U4")], 0)  # B4 = U4 - L >= 0
    P.group(["Y4", "U4", "L"])
    capA, capB = rows["capacity_A"]["b"], rows["capacity_B"]["b"]
    P.le([(1, "A1"), (1, "A2"), (1, "A3"), (1, "Y4"), (-1, "U4")], int(capA))
    P.le([(1, "Y1"), (-1, "A1"), (1, "Y2"), (-1, "A2"), (1, "Y3"), (-1, "A3"), (1, "U4"), (-1, "L")], int(capB))
    for w in worlds:  # priority rule in world w, unless w is one of the tolerated violations
        for j in (1, 4):
            thr = rows[f"priority_w{w}_S{j}"]["b"]
            timely = "U4" if (j == 4 and w in late_world) else f"Y{j}"
            P.ge([(1, timely)], int(math.ceil(thr - 1e-9)), unless=f"v{w}")

    def to_lp(v):
        x = {n: 0.0 for n in model["names"]}
        for j in (1, 2, 3):
            x[f"x_A_S{j}"], x[f"x_B_S{j}"] = v[f"A{j}"], v[f"Y{j}"] - v[f"A{j}"]
        x["x_A_S4"], x["x_B_S4"], x["backup_S4"] = v["Y4"] - v["U4"], v["U4"] - v["L"], v["L"]
        for w in worlds:
            x[f"violate_w{w}"] = float(v[f"v{w}"])
            for j in sites:
                got = sum(x[n] * c for n, c in term_vars(model, rows[f"floor_w{w}_S{j}"]).items())
                x[f"shortage_w{w}_S{j}"] = max(0.0, demand[(w, j)] - got)
        return x

    return P, to_lp


def replan_toy_program(model):
    """The Replan toy LP with its relaxation slacks fixed at zero, in coordinates Y_s = units
    received by store s and A_s = units from DC A."""
    rows = model["rows"]
    cost = dict(zip(model["names"], model["c"]))
    stores = ["S1", "S2", "S3", "S4"]
    lower = {s: 0.0 for s in stores}
    pieces = {s: [] for s in stores}  # (P_m, C_m): t_s >= C_m - P_m * Y_s
    for r in rows:
        tv = term_vars(model, r)
        s = next((st for st in stores if f"x_A_{st}_units" in tv), None)
        tag = r.get("tag", "")
        if tag.startswith(("floor:", "chance:")):
            lower[s] = max(lower[s], r["b"])  # slack fixed at zero: a hard lower bound
        elif tag == "epi":
            pieces[s].append((tv[f"x_A_{s}_units"], r["b"]))
    caps = {r["tag"]: r["b"] for r in rows if r.get("tag", "").startswith("cap:")}
    P = IntProgram()
    for s in stores:
        hi = int(max(C / Pm for Pm, C in pieces[s] if Pm > 0))  # beyond this, no expected shortage
        rho = cost[f"expected_shortage_{s}_units"]
        cA, cB = cost[f"x_A_{s}_units"], cost[f"x_B_{s}_units"]
        es = lambda y, s=s: max([0.0] + [C - Pm * y for Pm, C in pieces[s]])
        P.int_var(f"Y{s}", int(math.ceil(lower[s] - 1e-9)), max(hi, int(math.ceil(lower[s]))),
                  lambda y, cB=cB, rho=rho, es=es: cB * y + rho * es(y))
        P.int_var(f"A{s}", 0, max(hi, int(math.ceil(lower[s]))), lambda a, cA=cA, cB=cB: (cA - cB) * a)
        P.le([(1, f"A{s}"), (-1, f"Y{s}")], 0)
        P.group([f"Y{s}", f"A{s}"])
    P.le([(1, f"A{s}") for s in stores], int(caps["cap:A"]))
    P.le([t for s in stores for t in ((1, f"Y{s}"), (-1, f"A{s}"))], int(caps["cap:B"]))

    def to_lp(v):
        x = {n: 0.0 for n in model["names"]}
        for s in stores:
            x[f"x_A_{s}_units"], x[f"x_B_{s}_units"] = v[f"A{s}"], v[f"Y{s}"] - v[f"A{s}"]
            x[f"expected_shortage_{s}_units"] = max([0.0] + [C - Pm * v[f"Y{s}"] for Pm, C in pieces[s]])
        return x

    return P, to_lp


def stocking_program(model):
    """The three-store stocking MILP: integer stock per store, and per world w a flag violate_w
    that switches off that world's priority rule, with the flags' probability within budget. The
    shortage variables are dropped: their optimal value is max(0, d_wj - stock_j), which is a cost
    per stock level. Without worlds (the point forecast) every priority rule is hard."""
    rows = {r["name"]: r for r in model["rows"]}
    cost = dict(zip(model["names"], model["c"]))
    stores = [n[len("stock_") :] for n in model["names"] if n.startswith("stock_")]
    worlds = sorted({int(n[len("shortage_w") :].split("_")[0]) for n in model["names"] if n.startswith("shortage_w")})
    flags = [w for w in worlds if f"violate_w{w}" in model["names"]]
    demand = {(w, j): rows[f"shortage_w{w}_{j}"]["b"] for w in worlds for j in stores}
    P = IntProgram()
    for w in flags:
        P.bool_var(f"v{w}")
    if flags:  # sum_w p_w * v_w <= budget, scaled to integer coefficients
        budget = rows["joint_violation_budget"]
        prob = {w: Fraction(budget["a"][str(model["names"].index(f"violate_w{w}"))]).limit_denominator(10**6) for w in flags}
        scale = math.lcm(*(p.denominator for p in prob.values()))
        bound = Fraction(budget["b"]).limit_denominator(10**6)
        P.le([(int(prob[w] * scale), f"v{w}") for w in flags], math.floor(bound * scale))
    for j in stores:
        lo = int(math.ceil(rows[f"forecast_floor_{j}"]["b"] - 1e-9))
        hi = max(lo, int(math.ceil(max(demand[(w, j)] for w in worlds))))  # stocking more only costs
        pen = {w: cost[f"shortage_w{w}_{j}"] for w in worlds}
        P.int_var(f"stock_{j}", lo, hi,
                  lambda s, j=j, pen=pen: cost[f"stock_{j}"] * s + sum(pen[w] * max(0.0, demand[(w, j)] - s) for w in worlds))
    P.le([(1, f"stock_{j}") for j in stores], int(rows["inventory_capacity"]["b"]))
    for w in worlds:
        for j in stores:
            P.ge([(1, f"stock_{j}")], int(math.ceil(rows[f"priority_w{w}_{j}"]["b"] - 1e-9)),
                 unless=f"v{w}" if w in flags else None)

    def to_lp(v):
        x = {n: 0.0 for n in model["names"]}
        for j in stores:
            x[f"stock_{j}"] = float(v[f"stock_{j}"])
            for w in worlds:
                x[f"shortage_w{w}_{j}"] = max(0.0, demand[(w, j)] - v[f"stock_{j}"])
        for w in flags:
            x[f"violate_w{w}"] = float(v[f"v{w}"])
        return x

    return P, to_lp


def run(mid, build):
    model = MODELS[mid]
    P, to_lp = build(model)
    t0 = time.perf_counter()
    vt, circuit = P.compile()
    t1 = time.perf_counter()
    best, values = P.minimise(circuit)
    t2 = time.perf_counter()
    ref = VALIDATION[mid]
    if values is None:
        verdict = f"circuit is FALSE (no plan); HiGHS: {ref['status']}"
    else:
        lp_obj, msg = check_against_lp(model, to_lp(values))
        verdict = f"min {best:.6f}; LP objective of the decoded plan {lp_obj}; {msg}; HiGHS {ref['status']} {ref.get('objective')}"
    print(f"{mid}\n  Boolean vars {len(P.order)}, circuit nodes {circuit.node_count()}, pairs {circuit.pair_count()}, "
          f"compile {t1 - t0:.2f}s, (min,+) evaluate {t2 - t1:.2f}s\n  {verdict}")
    if values:
        print("  plan:", {k: v for k, v in values.items() if v is not False})  # Booleans: only those set
    return circuit, values


if __name__ == "__main__":
    for mid in ["copilot_demand_tau070_exact_milp", "copilot_storm_tau095_exact_milp", "copilot_storm_tau095_backup_exact_milp"]:
        run(mid, copilot_program)
    for mid in ["replan_toy_tau070", "replan_toy_tau095"]:
        run(mid, replan_toy_program)
    for mid in ["stocking_point_integer", "stocking_joint_integer_milp"]:
        run(mid, stocking_program)
