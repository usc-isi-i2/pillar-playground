"""Compile a mixed-integer linear program (an MPS file) into a tididi circuit and minimise on it.

The general version of compile.py: no per-model code. Steps:

1. Read the MPS file.
2. Tighten bounds from the rows, so that every variable gets a finite range.
3. Fold auxiliary variables into costs. A continuous variable z with a nonnegative cost, whose
   rows only push it up (z >= b_k - lambda_k * e for one linear expression e), equals
   max(lb, max_k(b_k - lambda_k * e)) at any optimum. It is removed with its rows and its cost
   moves onto e: onto the variable itself if e is one variable, otherwise onto a new integer
   variable y with the row y = e. Shortage, penalty and relaxation slacks all take this shape.
4. Tighten bounds again, now also by cost (dual bound tightening): a variable is not raised past
   the point where raising it stops helping any row and stops lowering its cost. Then check what
   is left: every variable integer (or --integral, which treats continuous ones as integers and
   so solves the integer version), bounded, with coefficients that scale to whole numbers, and
   few enough Boolean variables in the unit encoding (--max-bits). Every live tididi circuit
   costs memory and time in proportion to the vtree, so this limit is what keeps a model from
   running out of memory: a few thousand compiles in seconds, ~18k did not finish in 5 minutes.
5. Compile with compile.IntProgram under tididi memory and time limits, trying a few vtrees in
   turn (see vtree_candidates), minimise in the (min, +) semiring, and check the decoded plan
   against every original row (and against a .sol file next to the model, if there is one).

    python compile_lp.py model.mps [more.mps ...] [--integral] [--max-bits N] [--memory-gb G] [--timeout S]
                         [--node-cap N] [--no-dual] [--verbose]
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import goatd
import networkx as nx
import tididi as T

from compile import IntProgram

INF = math.inf


class NotSupported(Exception):
    """The model is outside what this compiler handles; the message says why."""


class Infeasible(Exception):
    """Bound tightening proved that no solution exists."""


# ---------- 1. reading

@dataclass
class Model:
    name: str
    names: list[str] = field(default_factory=list)
    cost: dict[str, float] = field(default_factory=dict)
    integer: set[str] = field(default_factory=set)
    lb: dict[str, float] = field(default_factory=dict)
    ub: dict[str, float] = field(default_factory=dict)
    rows: list[tuple[str, dict[str, float], float, float]] = field(default_factory=list)  # name, coefs, lo, hi
    constant: float = 0.0
    sense: int = 1  # 1 minimise, -1 maximise


def read_mps(path: Path) -> Model:
    m = Model(path.stem)
    obj, kinds, coefs, rhs, ranges = None, {}, {}, {}, {}
    section, in_int = None, False

    def pairs(tok):  # RHS/RANGES lines may start with a set name
        return zip(tok[len(tok) % 2 :: 2], tok[len(tok) % 2 + 1 :: 2])

    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("*"):
            continue
        tok = line.split()
        if not line[0].isspace():
            section = tok[0]
            if section == "OBJSENSE" and len(tok) > 1:
                m.sense = -1 if tok[1].upper().startswith("MAX") else 1
            continue
        if section == "OBJSENSE":
            m.sense = -1 if tok[0].upper().startswith("MAX") else 1
        elif section == "ROWS":
            kind, r = tok
            if kind == "N":
                obj = obj or r  # extra N rows are free rows; ignored
            else:
                kinds[r], coefs[r] = kind, {}
        elif section == "COLUMNS":
            if len(tok) >= 3 and tok[1] == "'MARKER'":
                in_int = tok[2] == "'INTORG'"
                continue
            c = tok[0]
            if c not in m.lb:
                m.names.append(c)
                m.lb[c], m.ub[c], m.cost[c] = 0.0, INF, 0.0
                if in_int:
                    m.integer.add(c)
            for r, v in zip(tok[1::2], tok[2::2]):
                if r == obj:
                    m.cost[c] = float(v)
                elif r in coefs:
                    coefs[r][c] = float(v)
        elif section == "RHS":
            for r, v in pairs(tok):
                if r == obj:
                    m.constant = -float(v)
                else:
                    rhs[r] = float(v)
        elif section == "RANGES":
            for r, v in pairs(tok):
                ranges[r] = float(v)
        elif section == "BOUNDS":
            kind = tok[0]
            c, val = (tok[2], tok[3:]) if len(tok) >= 3 and tok[2] in m.lb else (tok[1], tok[2:])
            v = float(val[0]) if val else None
            if kind in ("UP", "UI"):
                m.ub[c] = v
            elif kind in ("LO", "LI"):
                m.lb[c] = v
            elif kind == "FX":
                m.lb[c] = m.ub[c] = v
            elif kind == "FR":
                m.lb[c], m.ub[c] = -INF, INF
            elif kind == "MI":
                m.lb[c] = -INF
            elif kind == "PL":
                m.ub[c] = INF
            elif kind == "BV":
                m.lb[c], m.ub[c] = 0.0, 1.0
            else:
                raise NotSupported(f"bound type {kind} is not supported")
            if kind in ("UI", "LI", "BV"):
                m.integer.add(c)
    for r, kind in kinds.items():
        b, R = rhs.get(r, 0.0), ranges.get(r)
        lo, hi = {"L": (-INF, b), "G": (b, INF), "E": (b, b)}[kind]
        if R is not None:
            if kind == "L":
                lo = b - abs(R)
            elif kind == "G":
                hi = b + abs(R)
            else:
                lo, hi = (b + R, b) if R < 0 else (b, b + R)
        m.rows.append((r, coefs[r], lo, hi))
    return m


def read_sol_objective(path: Path) -> tuple[str, float | None] | None:
    """Status and objective from a HiGHS .sol file next to the model, if there is one."""
    if not path.exists():
        return None
    lines = path.read_text().splitlines()
    status = lines[1].strip() if len(lines) > 1 and lines[0].startswith("Model status") else "?"
    obj = next((float(l.split()[1]) for l in lines if l.startswith("Objective ")), None)
    return status, obj


# ---------- 2. bounds

def propagate(m: Model, rounds: int = 100) -> None:
    """Tighten variable bounds from row activity bounds until nothing changes."""
    for _ in range(rounds):
        changed = False
        for _, a, lo, hi in m.rows:
            terms = [(x, c) for x, c in a.items() if c]
            mins = [min(c * m.lb[x], c * m.ub[x]) for x, c in terms]
            maxs = [max(c * m.lb[x], c * m.ub[x]) for x, c in terms]
            fin_min, n_min = sum(v for v in mins if not math.isinf(v)), sum(math.isinf(v) for v in mins)
            fin_max, n_max = sum(v for v in maxs if not math.isinf(v)), sum(math.isinf(v) for v in maxs)
            for (x, c), vmin, vmax in zip(terms, mins, maxs):
                # activity bounds of the other terms (an infinite one makes the bound useless)
                rest_min = -INF if n_min - math.isinf(vmin) else fin_min - (0 if math.isinf(vmin) else vmin)
                rest_max = INF if n_max - math.isinf(vmax) else fin_max - (0 if math.isinf(vmax) else vmax)
                up, down = hi - rest_min, lo - rest_max  # down <= c * x <= up
                new_l, new_u = (down / c, up / c) if c > 0 else (up / c, down / c)
                if x in m.integer:
                    new_l = math.ceil(new_l - 1e-9) if not math.isinf(new_l) and not math.isnan(new_l) else new_l
                    new_u = math.floor(new_u + 1e-9) if not math.isinf(new_u) and not math.isnan(new_u) else new_u
                if not math.isnan(new_l) and new_l > m.lb[x] + 1e-9:
                    m.lb[x], changed = new_l, True
                if not math.isnan(new_u) and new_u < m.ub[x] - 1e-9:
                    m.ub[x], changed = new_u, True
                if m.lb[x] > m.ub[x] + 1e-6:
                    raise Infeasible(f"the bounds of {x} cross ({m.lb[x]:g} > {m.ub[x]:g})")
        if not changed:
            return


def activity(m: Model, a: dict[str, float], skip: str) -> tuple[float, float]:
    """Least and greatest value of sum(a[x] * x) over the variables other than `skip`."""
    lo = sum(min(c * m.lb[x], c * m.ub[x]) for x, c in a.items() if x != skip and c)
    hi = sum(max(c * m.lb[x], c * m.ub[x]) for x, c in a.items() if x != skip and c)
    return lo, hi


def dual_tighten(m: Model, cost: dict) -> bool:
    """Dual bound tightening for integer variables with a convex cost function cost[x].

    If raising x above T cannot help any row (every row that x helps by rising already holds at
    T, whatever the other variables do) and does not lower the cost, some optimal solution has
    x <= T: lower x to T in any solution and every row still holds. Likewise for lowering x.
    Returns whether a bound moved."""
    rows_of: dict[str, list] = {x: [] for x in m.names}
    for r in m.rows:
        for x, c in r[1].items():
            if c:
                rows_of[x].append(r)
    moved = False
    for x in m.names:
        if x not in m.integer or math.isinf(m.lb[x]) or math.isinf(m.ub[x]) or not 0 < m.ub[x] - m.lb[x] <= 10**6:
            continue
        lb, ub = int(m.lb[x]), int(m.ub[x])
        diffs = [cost[x](v + 1) - cost[x](v) for v in range(lb, ub)]
        tol = 1e-9 * max(1.0, max(abs(d) for d in diffs))
        need_up = ub  # cost nondecreasing on [need_up, ub]
        while need_up > lb and diffs[need_up - 1 - lb] >= -tol:
            need_up -= 1
        need_down = lb  # cost nonincreasing on [lb, need_down]
        while need_down < ub and diffs[need_down - lb] <= tol:
            need_down += 1
        for _, a, lo, hi in rows_of[x]:
            c = a[x]
            rest_lo, rest_hi = activity(m, a, x)
            if not math.isinf(lo):  # c*x + rest >= lo holds whatever the rest once c*x >= lo - rest_lo
                t = (lo - rest_lo) / c
                if c > 0:
                    need_up = max(need_up, ub if math.isinf(t) else math.ceil(t - 1e-9))
                else:
                    need_down = min(need_down, lb if math.isinf(t) else math.floor(t + 1e-9))
            if not math.isinf(hi):  # c*x + rest <= hi holds whatever the rest once c*x <= hi - rest_hi
                t = (hi - rest_hi) / c
                if c > 0:
                    need_down = min(need_down, lb if math.isinf(t) else math.floor(t + 1e-9))
                else:
                    need_up = max(need_up, ub if math.isinf(t) else math.ceil(t - 1e-9))
        if lb <= need_up < ub:
            m.ub[x], moved = need_up, True
        if lb < need_down <= m.ub[x]:
            m.lb[x], moved = need_down, True
    return moved


# ---------- 3. folding auxiliary variables into costs

def to_fraction(v: float) -> Fraction:
    f = Fraction(v).limit_denominator(10**6)
    if abs(float(f) - v) > 1e-9 * max(1.0, abs(v)):
        raise NotSupported(f"coefficient {v!r} is not a ratio of small integers")
    return f


def integer_form(coefs: dict[str, float], first_positive: bool = True) -> tuple[dict[str, int], Fraction]:
    """coefs = scale * e with e integer and gcd 1; the first coefficient of e is positive if
    first_positive (a canonical form for comparing expressions), else scale is positive."""
    fr = {x: to_fraction(c) for x, c in coefs.items()}
    den = math.lcm(*(f.denominator for f in fr.values()))
    ints = {x: int(f * den) for x, f in fr.items()}
    g = math.gcd(*ints.values())
    first = next(iter(ints.values()))
    g = g if (first > 0 or not first_positive) else -g
    return {x: v // g for x, v in ints.items()}, Fraction(g, den)


@dataclass
class Folded:
    """z = max(floor, max_k(beta_k + lam_k * E)) where E = sum(e[x] * x); cost per unit of z."""
    z: str
    e: dict[str, int]
    pieces: list[tuple[float, float]]  # (beta_k, lam_k)
    floor: float
    cost: float

    def value(self, E: float) -> float:
        return max([self.floor] + [b + l * E for b, l in self.pieces])


def fold_auxiliaries(m: Model) -> list[Folded]:
    """Find and remove auxiliary variables (see step 3 of the module docstring)."""
    rows_of: dict[str, list[int]] = {x: [] for x in m.names}
    for i, (_, a, _, _) in enumerate(m.rows):
        for x, c in a.items():
            if c:
                rows_of[x].append(i)
    candidates = {
        z for z in m.names
        if z not in m.integer and m.sense * m.cost[z] >= 0 and math.isinf(m.ub[z]) and not math.isinf(m.lb[z])
        and all((m.rows[i][1][z] > 0 and math.isinf(m.rows[i][3])) or (m.rows[i][1][z] < 0 and math.isinf(m.rows[i][2]))
                for i in rows_of[z])
    }
    folded, rows_gone = [], set()
    for z in sorted(candidates, key=m.names.index):
        pieces, e = [], None
        for i in rows_of[z]:
            _, a, lo, hi = m.rows[i]
            az = a[z]
            b = lo if az > 0 else hi
            rest = {x: -c / az for x, c in a.items() if x != z and c}  # z >= b / az + sum(rest * x)
            if any(x in candidates for x in rest):
                break  # two auxiliaries in one row: not a simple max
            if not rest:
                pieces.append((b / az, 0.0))
                continue
            ek, scale = integer_form(rest)
            if e is None:
                e = ek
            elif ek != e:
                break  # the rows bound z by different expressions
            pieces.append((b / az, float(scale)))
        else:
            folded.append(Folded(z, e or {}, pieces, m.lb[z], m.sense * m.cost[z]))
            rows_gone |= set(rows_of[z])
    m.rows = [r for i, r in enumerate(m.rows) if i not in rows_gone]
    gone = {f.z for f in folded}
    m.names = [x for x in m.names if x not in gone]
    return folded


# ---------- 4 and 5. building, compiling, minimising

def vtree_candidates(P: IntProgram, rows: list[list[str]]):
    """Candidate vtrees, most promising first, as (label, build) where build() returns the vtree
    and each variable's left-to-right position. Every variable is a linear vtree over its bits.

    - flags | integers: 0/1 variables in one subtree, wider integers in the other, each split by
      recursive bisection. Flags such as "world w may break the rule" switch rows on and off; kept
      together, the circuit branches once on which flags are set.
    - tree decomposition: goatd decomposes the constraint graph (one vertex per integer, an edge
      between integers that share a row) and the decomposition is read as a vtree the way vitri
      does: rooted at its centre bag, each variable placed at the highest bag that holds it, the
      variables placed at a bag above the subtrees of its children.
    - bisection: recursive Kernighan-Lin bisection of the whole constraint graph.
    - creation order: a right-linear chain of variables in the order the file lists them."""
    named = [n for n, (lo, hi, bits) in P.ints.items() if bits]
    G = nx.Graph()
    G.add_nodes_from(named)
    for names in rows:
        names = [n for n in names if P.ints[n][2]]
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                G.add_edge(a, b, weight=G.get_edge_data(a, b, {"weight": 0})["weight"] + 1)

    def make(order_fn):
        def build():
            position: dict[str, int] = {}

            def leaf(n):
                position[n] = len(position)
                bits = P.ints[n][2]
                return T.Vtree.linear(bits) if len(bits) > 1 else T.Vtree.leaf(bits[0])

            def bisect(nodes):
                if len(nodes) == 1:
                    return leaf(next(iter(nodes)))
                a, b = nx.algorithms.community.kernighan_lin_bisection(G.subgraph(nodes), weight="weight", seed=0)
                left = bisect(a)
                return T.Vtree.join(left, bisect(b))

            return order_fn(leaf, bisect), position

        return build

    flags = {n for n in named if len(P.ints[n][2]) == 1}
    wide = set(named) - flags

    def balanced(ts):
        while len(ts) > 1:
            ts = [T.Vtree.join(*ts[i : i + 2]) if i + 1 < len(ts) else ts[i] for i in range(0, len(ts), 2)]
        return ts[0]

    def decomposition(leaf, bisect, incidence=False):
        index = {n: i for i, n in enumerate(named)}
        if incidence:  # rows are vertices too, joined to their variables (vitri's incidence graph)
            used = [[index[n] for n in names if n in index] for names in rows]
            used = [r for r in used if r]
            graph = goatd.Graph(len(named) + len(used),
                                [(v, len(named) + i) for i, r in enumerate(used) for v in r])
        else:
            graph = goatd.Graph(len(named), [(index[a], index[b]) for a, b in G.edges])
        td = goatd.decompose(graph, seed=0, budget_ms=2000)
        bags, adj = td.bags, {i: [] for i in range(len(td.bags))}
        for a, b in td.edges:
            adj[a].append(b)
            adj[b].append(a)

        def farthest(start):  # (bag, parent map) of a breadth-first walk from start
            parent, queue = {start: None}, [start]
            for u in queue:
                for v in adj[u]:
                    if v not in parent:
                        parent[v] = u
                        queue.append(v)
            return queue[-1], parent

        end, _ = farthest(0)  # the centre bag: the middle of a longest path
        other, parent = farthest(end)
        path = [other]
        while parent[path[-1]] is not None:
            path.append(parent[path[-1]])
        root = path[len(path) // 2]
        _, parent = farthest(root)
        children = {u: [v for v in adj[u] if parent.get(v) == u] for u in adj}
        placed: dict[int, list[str]] = {}
        seen: set[int] = set()
        for u in sorted(parent, key=lambda b: _depth(parent, b)):  # top down: highest bag first
            for v in bags[u]:
                if v < len(named) and v not in seen:
                    seen.add(v)
                    placed.setdefault(u, []).append(named[v])

        def tree(u):
            subs = [t for t in (tree(c) for c in children[u]) if t is not None]
            here = [leaf(n) for n in placed.get(u, [])]
            if here and subs:
                return T.Vtree.join(balanced(here), balanced(subs))
            return balanced(here or subs) if (here or subs) else None

        return tree(root)

    def chain(leaf, bisect):
        trees = [leaf(n) for n in named]
        tree = trees[-1]
        for t in reversed(trees[:-1]):
            tree = T.Vtree.join(t, tree)
        return tree

    out = []
    if len(named) > 1:
        out.append(("tree decomposition (primal)", make(decomposition)))
        out.append(("tree decomposition (incidence)", make(lambda leaf, bisect: decomposition(leaf, bisect, True))))
    if flags and wide:
        out.append(("flags | integers", make(lambda leaf, bisect: T.Vtree.join(bisect(flags), bisect(wide)))))
    if len(named) > 1:
        out.append(("bisection", make(lambda leaf, bisect: bisect(set(named)))))
    out.append(("creation order", make(chain)))
    return out


def vtree_score(P: IntProgram, vt: T.Vtree) -> float:
    """log10 of an estimate of the circuit's size under vt: at every vtree node, the number of
    running-total states the circuit must keep, multiplied over the rows that have variables on
    both sides of the node, summed over the nodes. Each row's count is the number of values its
    inside part can take, an upper bound that ignores rows sharing state. Crude: on the PILLAR
    models it ranks the vtrees that run out of memory 5+ orders of magnitude below the usable
    ones, but it does not reliably order the usable ones."""
    owner = {b: n for n, (lo, hi, bits) in P.ints.items() for b in bits}
    inside: dict[int, set[str]] = {}
    kids: dict[int, tuple[int, int]] = {}
    for line in vt.to_text().splitlines()[1:]:
        t = line.split()
        if t[0] == "L":
            inside[int(t[1])] = {owner[int(t[2])]}
        else:
            kids[int(t[1])] = (int(t[2]), int(t[3]))
    for i in sorted(kids):  # children are numbered before their parent
        inside[i] = inside[kids[i][0]] | inside[kids[i][1]]
    logs = []
    for i in kids:
        log_states = 0.0
        for terms, _, _ in P.rows:
            ins = [(c, x) for c, x in terms if x in inside[i]]
            if ins and len(ins) < len(terms):
                lo = sum(min(c * P.ints[x][0], c * P.ints[x][1]) for c, x in ins)
                hi = sum(max(c * P.ints[x][0], c * P.ints[x][1]) for c, x in ins)
                log_states += math.log10(hi - lo + 1)
        logs.append(log_states)
    top = max(logs, default=0.0)  # sum in log space: the counts can pass 10^308
    return top + math.log10(sum(10 ** (v - top) for v in logs)) if logs else 0.0


def _depth(parent: dict, u) -> int:
    d = 0
    while parent[u] is not None:
        u, d = parent[u], d + 1
    return d


def compile_and_minimise(program, names: list[list[str]], memory_bytes: int, timeout: float,
                         node_cap: int, verbose: bool, only: str | None = None):
    """Pick a vtree and compile under it, then minimise. program(limits) builds a fresh
    IntProgram. Returns (cost, values); values is None if the circuit is false.

    The candidates are scored (vtree_score). Those within two orders of magnitude of the best
    score race: each compiles with a node cap equal to the smallest circuit so far (node_cap for
    the first), and the smallest circuit wins. The score cannot order such close candidates; on
    the PILLAR models the runner-up was sometimes 3 to 8 times smaller. If none of them compiles,
    the others within 5 orders of magnitude are tried in score order, the last without a cap.
    Candidates scored worse than that are the ones that ran out of memory, and are skipped."""
    P, _ = program(None)
    scored = sorted((vtree_score(P, build()[0]), i, label) for i, (label, build) in enumerate(vtree_candidates(P, names))
                    if only is None or label.startswith(only))
    if not scored:
        raise NotSupported(f"no vtree candidate starts with {only!r}")
    if verbose:
        print("    vtree scores (log10):", ", ".join(f"{label} {sc:.1f}" for sc, _, label in scored))
    best_score = scored[0][0]
    close = [(i, label) for sc, i, label in scored if sc <= best_score + 2]
    fallback = [(i, label) for sc, i, label in scored if best_score + 2 < sc <= best_score + 5]
    winner = None  # (nodes, program, circuit, label, compile seconds)
    for k, (i, label) in enumerate(close + fallback):
        if winner and k >= len(close):
            break
        last = k == len(close) + len(fallback) - 1 and winner is None
        cap = winner[0] if winner else None if last else node_cap
        P, _ = program(T.Limits(memory_bytes=memory_bytes, timeout=timeout if last else timeout / 3, output_nodes=cap))
        vt, position = vtree_candidates(P, names)[i][1]()
        P.rows = [(sorted(t, key=lambda cx: position.get(cx[1], -1)), K, u) for t, K, u in P.rows]  # vtree order
        t0 = time.perf_counter()
        try:
            _, circuit = P.compile(vt, verbose)
        except (MemoryError, T.ResourceLimitError) as err:
            if last:
                raise
            why = f"larger than {winner[3]}" if winner else str(err)
            print(f"  vtree {label}: gave up after {time.perf_counter() - t0:.1f}s ({why})")
            continue
        if verbose:
            print(f"    vtree {label}: {circuit.node_count()} nodes in {time.perf_counter() - t0:.2f}s")
        if winner is None or circuit.node_count() < winner[0]:
            winner = (circuit.node_count(), P, circuit, label, time.perf_counter() - t0)
    nodes, P, circuit, label, seconds = winner
    t1 = time.perf_counter()
    best, values = P.minimise(circuit)
    print(f"  vtree {label}: circuit nodes {nodes}, compile {seconds:.2f}s, minimise {time.perf_counter() - t1:.2f}s")
    return best, values


def reference(path: Path) -> str:
    ref = read_sol_objective(path.with_suffix(".sol"))
    return f"; reference .sol: {ref[0]} {ref[1]}" if ref else ""


def solve(path: Path, integral: bool, max_bits: int, memory_bytes: int, timeout: float,
          node_cap: int, verbose: bool = False, dual: bool = True, only: str | None = None) -> None:
    m = read_mps(path)
    original = Model(m.name, list(m.names), dict(m.cost), set(m.integer), dict(m.lb), dict(m.ub), list(m.rows), m.constant, m.sense)
    print(f"{m.name}: {len(m.names)} variables ({len(m.integer)} integer), {len(m.rows)} rows")
    propagate(m)
    folded = fold_auxiliaries(m)
    if folded:
        print(f"  folded {len(folded)} auxiliary variables into costs (with {len(original.rows) - len(m.rows)} rows)")

    for x in m.names:  # a variable fixed at a whole number is an integer
        if m.lb[x] == m.ub[x] and float(m.lb[x]).is_integer():
            m.integer.add(x)
    continuous = [x for x in m.names if x not in m.integer]
    if continuous and not integral:
        raise NotSupported(f"{len(continuous)} continuous variables are not auxiliary, e.g. {continuous[:4]}; "
                           "pass --integral to solve the integer version")
    if continuous:
        print(f"  --integral: {len(continuous)} continuous variables solved as integers")
        m.integer |= set(continuous)
        propagate(m)

    # Folded costs go on a variable: the expression's own variable if it is one, otherwise a new
    # integer variable y. If every folded cost on y can only fall as y grows (shortages), y <= e
    # is enough: the optimum raises y to e. If they can only rise, y >= e; otherwise y = e.
    by_expr: dict[tuple, list[Folded]] = {}
    for f in folded:
        if f.e:
            by_expr.setdefault(tuple(sorted(f.e.items())), []).append(f)
    extra_cost: dict[str, list[Folded]] = {}
    for key, fs in by_expr.items():
        e = dict(key)
        if len(e) == 1:
            extra_cost.setdefault(next(iter(e)), []).extend(fs)
            continue
        y = f"expr{len([k for k in extra_cost if k.startswith('expr')])}"
        slopes = [f.cost * l for f in fs for _, l in f.pieces]
        lo, hi = (-INF, 0.0) if all(s <= 0 for s in slopes) else (0.0, INF) if all(s >= 0 for s in slopes) else (0.0, 0.0)
        m.names.append(y)
        m.integer.add(y)
        m.lb[y], m.ub[y], m.cost[y] = activity(m, e, y)[0], activity(m, e, y)[1], 0.0
        m.rows.append((f"{y}_def", {y: 1.0, **{x: -float(c) for x, c in e.items()}}, lo, hi))
        extra_cost[y] = fs
    n_expr = sum(k.startswith("expr") for k in extra_cost)
    if n_expr:
        print(f"  {n_expr} new integer variables for folded expressions")

    cost = {x: (lambda v, lin=m.sense * m.cost[x], fs=extra_cost.get(x, []): lin * v + sum(f.cost * f.value(v) for f in fs))
            for x in m.names}
    for _ in range(50):
        propagate(m)
        if not dual or not dual_tighten(m, cost):
            break

    unbounded = [x for x in m.names if math.isinf(m.lb[x]) or math.isinf(m.ub[x])]
    if unbounded:
        raise NotSupported(f"no finite range after bound tightening: {unbounded[:6]}")
    widths = {x: int(m.ub[x]) - int(m.lb[x]) for x in m.names}
    bits = sum(widths.values())
    widest = sorted(widths, key=widths.get, reverse=True)[:3]
    widest_text = ", ".join(f"{x} [{m.lb[x]:g}, {m.ub[x]:g}]" for x in widest)
    if bits > max_bits:
        raise NotSupported(f"unit encoding needs {bits} Boolean variables (limit --max-bits {max_bits}); widest: {widest_text}")
    print(f"  {len(m.names)} integer variables, {bits} Boolean variables; widest: {widest_text}")

    def program(limits):
        P = IntProgram(limits)
        for x in m.names:
            P.int_var(x, int(m.lb[x]), int(m.ub[x]), cost[x])
        names = []
        for _, a, lo, hi in m.rows:
            a = {x: c for x, c in a.items() if c}
            if not a:
                continue
            ints, scale = integer_form(a, first_positive=False)
            terms = [(c, x) for x, c in ints.items()]
            if not math.isinf(hi):
                P.le(terms, math.floor(float(Fraction(hi).limit_denominator(10**9) / scale) + 1e-9))
            if not math.isinf(lo):
                P.ge(terms, math.ceil(float(Fraction(lo).limit_denominator(10**9) / scale) - 1e-9))
            names.append(list(a))
        return P, names

    _, names = program(None)
    if bits == 0:  # bound tightening fixed every variable: nothing left to compile
        values = {x: int(m.lb[x]) for x in m.names}
        best = sum(cost[x](values[x]) for x in m.names)
        print("  every variable fixed by bound tightening; no circuit needed")
    else:
        best, values = compile_and_minimise(program, names, memory_bytes, timeout, node_cap, verbose, only)
    if values is None:
        print(f"  RESULT no integer solution (circuit is false){reference(path)}")
        return

    # Decode: original variables, folded ones from their expressions, and check every row.
    x = {n: float(values[n]) for n in original.names if n in values}
    for f in folded:
        x[f.z] = f.value(sum(c * values[v] for v, c in f.e.items()))
    bad = []
    for name, a, lo, hi in original.rows:
        act = sum(c * x[v] for v, c in a.items())
        if act < lo - 1e-6 * max(1, abs(lo)) or act > hi + 1e-6 * max(1, abs(hi)):
            bad.append(f"{name}: {act:g} not in [{lo:g}, {hi:g}]")
    for v in original.names:
        if x[v] < original.lb[v] - 1e-6 or x[v] > original.ub[v] + 1e-6:
            bad.append(f"bound {v}={x[v]:g}")
    objective = original.constant + sum(original.cost[v] * x[v] for v in original.names)
    constant = sum(f.cost * f.value(0) for f in folded if not f.e)  # auxiliaries fixed by constants
    check = "all rows hold" if not bad else f"VIOLATED {len(bad)}: {bad[:3]}"
    print(f"  RESULT objective {objective:.6f} (circuit min {m.sense * (best + constant) + original.constant:.6f}); "
          f"{check}{reference(path)}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("models", nargs="+", type=Path)
    p.add_argument("--integral", action="store_true", help="solve continuous variables as integers")
    p.add_argument("--max-bits", type=int, default=4000, help="refuse models needing more Boolean variables")
    p.add_argument("--memory-gb", type=float, default=4.0, help="tididi memory budget")
    p.add_argument("--node-cap", type=int, default=2_000_000, help="give up on a vtree past this many nodes and try the next")
    p.add_argument("--no-dual", action="store_true", help="skip dual bound tightening (to see the circuit do the work)")
    p.add_argument("--vtree", help="use only the vtree candidates whose name starts with this")
    p.add_argument("--verbose", action="store_true", help="print circuit sizes while compiling")
    p.add_argument("--timeout", type=float, default=300.0, help="tididi time limit per model, seconds")
    args = p.parse_args(argv)
    for path in args.models:
        try:
            solve(path, args.integral, args.max_bits, int(args.memory_gb * 2**30), args.timeout, args.node_cap, args.verbose, not args.no_dual, args.vtree)
        except NotSupported as e:
            print(f"  NOT SUPPORTED: {e}")
        except Infeasible as e:
            print(f"  RESULT infeasible, proved by bound tightening: {e}{reference(path)}")
        except (MemoryError, T.ResourceLimitError) as e:
            print(f"  STOPPED by tididi limits: {e}")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
