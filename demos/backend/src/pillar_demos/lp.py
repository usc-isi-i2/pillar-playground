"""Dense two-phase simplex, shared by both demos.

A port of the original pages' solver. Keep the pivot rules and tolerances exactly as they are:
when an LP has several optimal vertices, they decide which plan the demos show. Row operations
use numpy, which performs the same IEEE operations in the same order as the JS loops (each row's
update reads only the pivot row), so results are bit-identical.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

import numpy as np

Op = Literal["<=", ">=", "="]


class Row(TypedDict):
    a: dict[int, float]
    op: Op
    b: float
    tag: NotRequired[str]


def solve_lp(n: int, c: list[float], rows: list[Row], max_iter: int = 20000) -> dict[str, Any]:
    """Minimise c·x subject to ``rows`` and x >= 0, over ``n`` variables.

    Returns ``{"status": "optimal", "x", "obj", "iterations"}`` or ``{"status": ...}`` with
    ``infeasible``, ``unbounded`` or ``iteration_limit``.
    """
    m = len(rows)
    # normalize b >= 0
    R: list[Row] = []
    for r in rows:
        if r["b"] < 0:
            op = r["op"]
            R.append(
                {
                    "a": {k: -v for k, v in r["a"].items()},
                    "b": -r["b"],
                    "op": ">=" if op == "<=" else "<=" if op == ">=" else "=",
                }
            )
        else:
            R.append(r)
    n_slack = sum(1 for r in R if r["op"] != "=")
    n_art = sum(1 for r in R if r["op"] != "<=")
    n_col = n + n_slack + n_art
    W = n_col + 1
    T = np.zeros((m, W))
    basis = [0] * m
    is_art = np.zeros(n_col, dtype=bool)
    s, a = n, n + n_slack
    for i, r in enumerate(R):
        for k, v in r["a"].items():
            T[i, int(k)] = v
        T[i, n_col] = r["b"]
        if r["op"] == "<=":
            T[i, s] = 1
            basis[i] = s
            s += 1
        elif r["op"] == ">=":
            T[i, s] = -1
            s += 1
            T[i, a] = 1
            is_art[a] = True
            basis[i] = a
            a += 1
        else:
            T[i, a] = 1
            is_art[a] = True
            basis[i] = a
            a += 1
    z = np.zeros(W)
    iters = 0

    def set_objective(cost: np.ndarray) -> None:
        # z = reduced costs, z[n_col] = -objective
        z[:] = 0
        z[:n_col] = cost[:n_col]
        for i in range(m):
            cb = cost[basis[i]] if basis[i] < len(cost) else 0.0
            if cb != 0:
                z[:] -= cb * T[i]

    def pivot(pr: int, pc: int) -> None:
        T[pr] /= T[pr, pc]
        f = T[:, pc].copy()
        f[pr] = 0
        rows_to_update = np.abs(f) > 1e-13
        if rows_to_update.any():
            T[rows_to_update] -= f[rows_to_update, None] * T[pr]
        fz = z[pc]
        if abs(fz) > 1e-13:
            z[:] -= fz * T[pr]
        basis[pr] = pc

    def run(allowed: np.ndarray | None) -> str:
        nonlocal iters
        degenerate = 0
        while True:
            iters += 1
            if iters > max_iter:
                return "iteration_limit"
            bland = degenerate > 50
            zc = z[:n_col] if allowed is None else np.where(allowed, z[:n_col], np.inf)
            if bland:
                # First allowed column with a negative reduced cost.
                cands = np.flatnonzero(zc < -1e-9)
                pc = int(cands[0]) if len(cands) else -1
            else:
                # Most negative reduced cost; the first such column on ties.
                j = int(np.argmin(zc))
                pc = j if zc[j] < -1e-9 else -1
            if pc < 0:
                return "optimal"
            pr, min_r = -1, np.inf
            col, rhs = T[:, pc], T[:, n_col]
            for i in np.flatnonzero(col > 1e-11):
                ratio = rhs[i] / col[i]
                if ratio < min_r - 1e-12 or (
                    pr >= 0 and abs(ratio - min_r) <= 1e-12 and basis[i] < basis[pr]
                ):
                    min_r = ratio
                    pr = int(i)
            if pr < 0:
                return "unbounded"
            degenerate = degenerate + 1 if min_r < 1e-12 else 0
            pivot(pr, pc)

    # Phase 1
    if n_art > 0:
        set_objective(is_art.astype(float))
        st = run(None)
        if st != "optimal" or -z[n_col] > 1e-6 * max(1, *(r["b"] for r in R)):
            return {"status": "infeasible"}
        for i in range(m):
            if is_art[basis[i]]:  # drive out
                nz = np.flatnonzero(~is_art & (np.abs(T[i, :n_col]) > 1e-9))
                if len(nz):
                    pivot(i, int(nz[0]))
    c2 = np.zeros(n_col)
    c2[:n] = [v or 0 for v in c[:n]]
    set_objective(c2)
    st = run(~is_art)
    if st != "optimal":
        return {"status": st}
    x = [0.0] * n
    for i in range(m):
        if basis[i] < n:
            x[basis[i]] = float(T[i, n_col])
    obj = 0.0
    for j in range(n):
        obj += (c[j] or 0) * x[j]
    return {"status": "optimal", "x": x, "obj": obj, "iterations": iters}
