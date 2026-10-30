"""Run the M5-CLARA baseline and save every LP/MILP it solves as an MPS file, with a reference .sol.

The benchmark (M5_CLARA_Benchmark_v1/src/m5clara.py) builds its planners in memory and solves
them with scipy's linprog and milp. This wrapper replaces those two functions with versions that
first write the model to <out>/<planner>.mps, then solve it exactly (HiGHS through scipy, MIP gap
0, whereas the benchmark accepts 1%) and write the objective to <out>/<planner>.sol in the HiGHS
format compile_lp.py reads. Arguments after the output folder go to m5clara.py unchanged.

    uv run --with lightgbm --with pandas --with scikit-learn --with scipy \\
        python m5_export.py path/to/M5_CLARA_Benchmark_v1 out_dir --data ... --saa-milp ...
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import scipy.optimize as so

INF = np.inf


def write_mps(path: Path, c, rows, lo, hi, lb, ub, integer) -> None:
    """rows: list of {column: coefficient}. Rows with lo == hi are equalities; rows bounded on
    both sides get a range."""
    n = len(c)
    col = [f"x{j}" for j in range(n)]
    lines = [f"NAME        {path.stem}", "ROWS", " N  obj"]
    kinds = []
    for i, (l, h) in enumerate(zip(lo, hi)):
        kind = "E" if l == h else "L" if l == -INF else "G"
        kinds.append(kind)
        lines.append(f" {kind}  r{i}")
    by_col: list[list[tuple[str, float]]] = [[] for _ in range(n)]
    for i, r in enumerate(rows):
        for j, v in r.items():
            if v:
                by_col[j].append((f"r{i}", v))
    lines.append("COLUMNS")
    in_int = False
    for j in range(n):
        if integer[j] != in_int:
            lines.append(f"    M{j}  'MARKER'  '{'INTORG' if integer[j] else 'INTEND'}'")
            in_int = bool(integer[j])
        if c[j]:
            lines.append(f"    {col[j]}  obj  {float(c[j])!r}")
        for r, v in by_col[j]:
            lines.append(f"    {col[j]}  {r}  {float(v)!r}")
    if in_int:
        lines.append(f"    M{n}  'MARKER'  'INTEND'")
    lines.append("RHS")
    for i, (kind, l, h) in enumerate(zip(kinds, lo, hi)):
        b = h if kind == "L" else l
        if b:
            lines.append(f"    RHS  r{i}  {float(b)!r}")
    lines.append("RANGES")
    for i, (kind, l, h) in enumerate(zip(kinds, lo, hi)):
        if kind == "G" and h != INF:
            lines.append(f"    RNG  r{i}  {float(h - l)!r}")
    lines.append("BOUNDS")
    for j in range(n):
        if lb[j] == -INF:
            lines.append(f" MI BND  {col[j]}")
        elif lb[j]:
            lines.append(f" LO BND  {col[j]}  {float(lb[j])!r}")
        if ub[j] != INF:
            lines.append(f" UP BND  {col[j]}  {float(ub[j])!r}")
    lines.append("ENDATA")
    path.write_text("\n".join(lines) + "\n")


def write_sol(path: Path, status: str, objective: float | None) -> None:
    text = f"Model status\n{status}\n"
    if objective is not None:
        text += f"\n# Primal solution values\nFeasible\nObjective {float(objective)!r}\n"
    path.write_text(text)


def main() -> None:
    bench, out, rest = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(bench / "src"))
    import m5clara

    real_linprog, real_milp = so.linprog, so.milp
    counter = {"lp": 0}

    def linprog(c, A_ub=None, b_ub=None, bounds=(0, None), method="highs", **kw):
        c = np.asarray(c, float)
        A = np.asarray(A_ub, float)
        rows = [{j: v for j, v in enumerate(r) if v} for r in A]
        lb, ub = bounds
        name = ["nominal_lp", "chance_lp"][counter["lp"]] if counter["lp"] < 2 else f"lp{counter['lp']}"
        counter["lp"] += 1
        write_mps(out / f"{name}.mps", c, rows, [-INF] * len(rows), list(b_ub), [lb or 0.0] * len(c),
                  [INF if ub is None else ub] * len(c), [0] * len(c))
        res = real_linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method=method, **kw)
        write_sol(out / f"{name}.sol", "Optimal" if res.success else "Infeasible", res.fun if res.success else None)
        return res

    def milp(c, integrality=None, bounds=None, constraints=None, options=None):
        A = constraints.A.tocsr()
        rows = [dict(zip(A.indices[A.indptr[i] : A.indptr[i + 1]], A.data[A.indptr[i] : A.indptr[i + 1]])) for i in range(A.shape[0])]
        write_mps(out / "saa_milp.mps", list(c), rows, list(constraints.lb), list(constraints.ub),
                  list(bounds.lb), list(bounds.ub), list(integrality))
        exact = real_milp(c, integrality=integrality, bounds=bounds, constraints=constraints,
                          options={"time_limit": 600, "mip_rel_gap": 0})
        status = "Optimal" if exact.status == 0 else "Infeasible" if exact.status == 2 else f"status {exact.status}"
        write_sol(out / "saa_milp.sol", status, exact.fun if exact.x is not None else None)
        return real_milp(c, integrality=integrality, bounds=bounds, constraints=constraints, options=options)

    m5clara.linprog, m5clara.milp = linprog, milp
    m5clara.run(m5clara.parser().parse_args(rest))


if __name__ == "__main__":
    main()
