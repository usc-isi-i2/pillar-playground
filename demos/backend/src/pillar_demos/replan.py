"""PILLAR Replan engine: LP solver + exact inference over a latent-mixture model.

The probability model is a mixture over latent configurations k (storm, surge, emergency), with
store-category demands independent given k: p(D|e) = sum_k w_k prod_sc p_k(D_sc). That is the
structure of a sum-product circuit; the queries below evaluate it exactly.

Demand keys are "store|category" (the toy preset has one category, "units"). Models, plans and
evaluations are plain dicts whose keys match the JSON the frontend reads.

A port of the original page's engine; results match it exactly (see tests/test_replan.py).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

from .js import js_locale_int, js_number, js_round, js_str, js_sum, mulberry32
from .lp import Row, solve_lp

Model = dict[str, Any]
Atoms = list[list[float]]

# ---------- Helpers


def _merge_atoms(items: Atoms) -> Atoms:
    """Sort atoms by value and merge equal values (rounded to 1/1000)."""
    m: dict[float, float] = {}
    for v, p in items:
        key = js_round(v * 1000) / 1000
        m[key] = m.get(key, 0) + p
    return sorted(([v, p] for v, p in m.items() if p > 1e-15), key=lambda e: e[0])


# Five-point noise distribution in standard-deviation units.
EPS_Z = [-1.6, -0.7, 0, 0.7, 1.6]
EPS_P = [0.1, 0.2, 0.4, 0.2, 0.1]
EPS_SD = math.sqrt(2 * (0.1 * 2.56 + 0.2 * 0.49))

# ---------- Scenario presets

_STORM_STORES = [
    ("CA_1", 21000),
    ("CA_2", 17500),
    ("CA_3", 30000),
    ("CA_4", 12000),
    ("TX_1", 16500),
    ("TX_2", 21000),
    ("TX_3", 18500),
    ("WI_1", 15500),
    ("WI_2", 20500),
    ("WI_3", 19000),
]

PRESETS: dict[str, dict[str, Any]] = {
    "toy": {
        "id": "toy",
        "title": "Toy instance from the September tag-up",
        "dcs": [{"id": "A", "state": "-", "cap": 130}, {"id": "B", "state": "-", "cap": 50}],
        "stores": [{"id": s, "state": "-"} for s in ("S1", "S2", "S3", "S4")],
        "cats": ["units"],
        "cost": {"A": {"S1": 1, "S2": 2, "S3": 5, "S4": 6}, "B": {"S1": 6, "S2": 5, "S3": 2, "S4": 1}},
        "forecast": {"S1": 50, "S2": 40, "S3": 45, "S4": 55},
        "defaultSpec": {
            "priority": [{"stores": ["S1", "S4"], "category": "units", "fraction": 0.9}],
            "floor": {"fraction": 0.6},
            "exception": None,
            "crossStateMultiplier": None,
            "penalties": {"priority": 20, "other": 10},
            "tau": 0.9,
            "joint": False,
        },
        "knowledge": (
            "We have two DCs. A has capacity 130 and B has lost capacity, down to 50. S1 and S4 are"
            " priority stores: serve at least 90% of realized demand. Every store gets at least 60% of"
            " its forecast. Shortfall costs 20 per unit at priority stores and 10 elsewhere."
        ),
    },
    "storm": {
        "id": "storm",
        "title": "Gulf storm week (M5-shaped network)",
        "states": ["CA", "TX", "WI"],
        "stores": [{"id": i, "state": i[:2], "weekly": w} for i, w in _STORM_STORES],
        "cats": ["FOODS", "HOUSEHOLD", "HOBBIES"],
        "share": {"FOODS": 0.68, "HOUSEHOLD": 0.22, "HOBBIES": 0.10},
        "cv": {"FOODS": 0.07, "HOUSEHOLD": 0.10, "HOBBIES": 0.15},
        "capFactor": 1.35,
        "laneCost": {
            "CA": {"CA": 1, "TX": 4, "WI": 6},
            "TX": {"CA": 4, "TX": 1, "WI": 4.5},
            "WI": {"CA": 6, "TX": 4.5, "WI": 1},
        },
        "defaultSpec": {
            "priority": [{"stores": ["TX_1", "TX_2", "TX_3"], "category": "FOODS", "fraction": 0.9}],
            "floor": {"fraction": 0.6},
            "exception": {"when": "emergency_declared", "fraction": 0.8},
            "crossStateMultiplier": 4,
            "penalties": {"priority": 8, "other": 6},
            "tau": None,
            "joint": True,
        },
        "knowledge": (
            "We run three distribution centers, one per state. Each normally ships only to its own"
            " state’s stores; cross-state shipments cost about four times as much. During a storm,"
            " FOODS at Texas stores is priority: serve at least 90% of actual demand. Every store gets"
            " at least 60% of its forecast in every category. If the state declares an emergency, the"
            " Texas FOODS floor drops to 80%. Shortfall costs 8 per unit on priority items and 6"
            " elsewhere. The Texas rule counts as met only if all three Texas stores meet it."
        ),
        # Disruption model (illustrative parameters)
        "Z": ["miss", "graze", "landfall"],
        "pZ": [0.35, 0.45, 0.20],
        "pAdv": {"none": [0.6, 0.15, 0.05], "watch": [0.3, 0.55, 0.25], "warning": [0.1, 0.30, 0.70]},
        "U": ["low", "medium", "high"],
        "pU": [[0.75, 0.2, 0.05], [0.3, 0.5, 0.2], [0.1, 0.35, 0.55]],
        "surge": [0.04, 0.18, 0.38],
        "pSales": {"flat": [0.7, 0.25, 0.08], "up": [0.25, 0.55, 0.37], "sharp": [0.05, 0.20, 0.55]},
        # Keyed by String(txCap), as in the original object literal.
        "pCap": {"1": [0.85, 0.35, 0.10], "0.7": [0.12, 0.50, 0.40], "0.4": [0.03, 0.15, 0.50]},
        "pLaneClosed": [0.03, 0.15, 0.45],
        "pEmerg": [0.02, 0.25, 0.80],
    },
}

DEFAULT_EVIDENCE = {
    "advisory": "watch",
    "sales": "unknown",
    "txCap": 0.7,
    "caLane": "open",
    "emergency": "unknown",
    "week": "normal",
}

# ---------- Build the model for (preset, spec, evidence)


def build_model(
    preset_id: str,
    spec: dict[str, Any],
    ev: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    custom: dict[str, Any] | None = None,
) -> Model:
    """``custom`` is normal-week demand loaded from a CSV of M5 aggregates: {"base": {...}, "cv": {...}}."""
    overrides = overrides or {}
    P = PRESETS[preset_id]
    M: Model = {
        "presetId": preset_id,
        "spec": spec,
        "ev": ev,
        "stores": [s["id"] for s in P["stores"]],
        "cats": list(P["cats"]),
        "notes": [],
    }
    M["sc"] = [s + "|" + c for s in M["stores"] for c in M["cats"]]
    M["storeState"] = {s["id"]: s["state"] for s in P["stores"]}
    M["tau"] = 0.9 if spec.get("tau") is None else spec["tau"]
    # priority set
    prio: dict[str, float] = {}
    for r in spec.get("priority") or []:
        for s in r["stores"]:
            if s in M["stores"] and r["category"] in M["cats"]:
                prio[s + "|" + r["category"]] = r["fraction"]
    M["prio"] = prio
    pen = spec["penalties"]
    M["pen"] = {k: pen["priority"] if k in prio else pen["other"] for k in M["sc"]}

    if preset_id == "toy":
        M["dcs"] = [dict(d) for d in P["dcs"]]
        M["lanes"] = [
            {"dc": d["id"], "store": s, "cost": P["cost"][d["id"]][s]} for d in M["dcs"] for s in M["stores"]
        ]
        M["forecast"] = {s + "|units": P["forecast"][s] for s in M["stores"]}
        atoms = {
            "S1|units": [[50, 1]],
            "S2|units": [[40, 1]],
            "S3|units": [[45, 1]],
            "S4|units": [[60, 0.15], [70, 0.55], [80, 0.30]],
        }
        M["configs"] = [{"w": 1, "label": {"z": "-", "u": "-", "e": False}, "atoms": atoms}]
        M["latentNames"] = []
    else:
        mult = spec.get("crossStateMultiplier") or 4
        base_mean: dict[str, float] = {}
        cap_base = {"CA": 0.0, "TX": 0.0, "WI": 0.0}
        for s in P["stores"]:
            for c in P["cats"]:
                ck = s["id"] + "|" + c
                if custom and custom["base"].get(ck) is not None:
                    m = custom["base"][ck]
                else:
                    m = s["weekly"] * P["share"][c]
                if ev["week"] == "snap" and c == "FOODS":
                    m *= 1.06
                base_mean[ck] = js_round(m)
                cap_base[s["state"]] += m
        M["forecast"] = base_mean
        M["dcs"] = [
            {
                "id": "DC_" + st,
                "state": st,
                "cap": js_round(cap_base[st] * P["capFactor"] * (ev["txCap"] if st == "TX" else 1)),
            }
            for st in P["states"]
        ]
        if overrides.get("capDelta"):
            for d in M["dcs"]:
                d["cap"] += overrides["capDelta"].get(d["id"]) or 0
        ca_lane = overrides.get("caLane") or ev["caLane"]
        lanes = []
        for d in M["dcs"]:
            for s in P["stores"]:
                if d["state"] == "CA" and s["state"] == "TX" and ca_lane == "closed":
                    continue
                base = P["laneCost"][d["state"]][s["state"]]
                cost = base if d["state"] == s["state"] else base * (mult / 4)
                lanes.append({"dc": d["id"], "store": s["id"], "cost": cost})
        M["lanes"] = lanes
        # latent configurations and posterior weights
        configs = []
        p_cap = P["pCap"][js_str(ev["txCap"])]
        for zi in range(3):
            for ui in range(3):
                for e in (False, True):
                    w = P["pZ"][zi] * P["pU"][zi][ui]
                    if ev["advisory"] != "unknown":
                        w *= P["pAdv"][ev["advisory"]][zi]
                    if ev["sales"] != "unknown":
                        w *= P["pSales"][ev["sales"]][ui]
                    w *= p_cap[zi]
                    w *= P["pLaneClosed"][zi] if ca_lane == "closed" else 1 - P["pLaneClosed"][zi]
                    pe = P["pEmerg"][zi]
                    w *= pe if e else 1 - pe
                    if ev["emergency"] == "declared" and not e:
                        w = 0
                    if ev["emergency"] == "not_declared" and e:
                        w = 0
                    configs.append((zi, ui, e, w))
        zs = js_sum(k[3] for k in configs)
        M["configs"] = []
        for zi, ui, e, w0 in configs:
            if not w0 > 0:
                continue
            atoms = {}
            for s in P["stores"]:
                for c in P["cats"]:
                    key = s["id"] + "|" + c
                    mu = base_mean[key]
                    if s["state"] == "TX":
                        sg = P["surge"][ui]
                        mu *= 1 + sg if c == "FOODS" else 1 + 0.8 * sg if c == "HOUSEHOLD" else 1 - 0.5 * sg
                    if custom and custom["cv"].get(key) is not None:
                        cv = custom["cv"][key]
                    else:
                        cv = P["cv"][c]
                    atoms[key] = [
                        [js_round(mu * (1 + cv * zz / EPS_SD)), EPS_P[i]] for i, zz in enumerate(EPS_Z)
                    ]
            M["configs"].append(
                {"w": w0 / zs, "label": {"z": P["Z"][zi], "u": P["U"][ui], "e": e}, "atoms": atoms}
            )
    # policy fraction per config (exception fires under declared emergency)
    exc = spec.get("exception")
    for k in M["configs"]:
        k["frac"] = {
            key: min(f, exc["fraction"]) if exc and k["label"]["e"] else f for key, f in prio.items()
        }
    # marginals
    M["marg"] = {
        key: _merge_atoms([[v, k["w"] * p] for k in M["configs"] for v, p in k["atoms"][key]])
        for key in M["sc"]
    }
    return M


# ---------- Queries on a discrete distribution


def _cdf_le(atoms: Atoms, x: float) -> float:
    s = 0.0
    for v, p in atoms:
        if v <= x + 1e-9:
            s += p
    return s


def _exp_short(atoms: Atoms, q: float) -> float:
    s = 0.0
    for v, p in atoms:
        if v > q:
            s += p * (v - q)
    return s


def mean(atoms: Atoms) -> float:
    return js_sum(v * p for v, p in atoms)


def quantile(atoms: Atoms, a: float) -> float:
    s = 0.0
    for v, p in atoms:
        s += p
        if s >= a - 1e-12:
            return v
    return atoms[-1][0]


def _p_rule_met(M: Model, key: str, q: float) -> float:
    """p(rule at key met | q): sum_k w_k P_k(D <= q / f_k)."""
    s = 0.0
    for k in M["configs"]:
        s += k["w"] * _cdf_le(k["atoms"][key], q / k["frac"][key])
    return s


def _p_all_met(M: Model, qmap: dict[str, float]) -> float:
    s = 0.0
    for k in M["configs"]:
        pr = k["w"]
        for key in M["prio"]:
            pr *= _cdf_le(k["atoms"][key], qmap[key] / k["frac"][key])
        s += pr
    return s


def _chance_threshold(M: Model, key: str, tau: float) -> float:
    """Smallest q with p_rule_met >= tau."""
    cands = dict.fromkeys(v * k["frac"][key] for k in M["configs"] for v, _ in k["atoms"][key])
    ordered = sorted(cands)
    for q in ordered:
        if _p_rule_met(M, key, q) >= tau - 1e-12:
            return q
    return ordered[-1]


# ---------- Solve a plan: 'mmap' (average over demand, chance constraints) or 'mpe' (most likely world)


def solve_plan(M: Model, mode: str = "mmap") -> dict[str, Any]:
    keys = M["sc"]
    prio_keys = list(M["prio"])
    atoms_for = M["marg"]
    mpe = None
    if mode == "mpe":
        mpe = mpe_query(M)
        atoms_for = {key: [[mpe["demand"][key], 1]] for key in keys}
    tau_each = M["tau"]
    if M["spec"].get("joint") and len(prio_keys) > 1:
        tau_each = 1 - (1 - M["tau"]) / len(prio_keys)
    threshold = {
        key: mpe["frac"][key] * mpe["demand"][key] if mpe else _chance_threshold(M, key, tau_each)
        for key in prio_keys
    }
    # variables: x (lane × category shipments), t (expected shortfall), h (floor slack), g (priority slack)
    x_vars: list[tuple[dict[str, Any], str, str]] = []
    lanes_of: dict[str, list[int]] = {k: [] for k in keys}
    for L in M["lanes"]:
        for c in M["cats"]:
            key = L["store"] + "|" + c
            lanes_of[key].append(len(x_vars))
            x_vars.append((L, c, key))
    nx = len(x_vars)
    t_idx = {key: nx + i for i, key in enumerate(keys)}
    h_idx = {key: nx + len(keys) + i for i, key in enumerate(keys)}
    g_idx = {key: nx + 2 * len(keys) + i for i, key in enumerate(prio_keys)}
    n = nx + 2 * len(keys) + len(prio_keys)
    c = [0.0] * n
    for j, (L, _, _) in enumerate(x_vars):
        c[j] = L["cost"]
    for key in keys:
        c[t_idx[key]] = M["pen"][key]
        c[h_idx[key]] = 1e4
    for key in prio_keys:
        c[g_idx[key]] = 1e5
    rows: list[Row] = []
    for d in M["dcs"]:
        rows.append(
            {
                "a": {j: 1 for j, v in enumerate(x_vars) if v[0]["dc"] == d["id"]},
                "op": "<=",
                "b": d["cap"],
                "tag": "cap:" + d["id"],
            }
        )
    floor_f = M["spec"]["floor"]["fraction"] if M["spec"].get("floor") else 0
    for key in keys:
        a = {j: 1.0 for j in lanes_of[key]}
        a[h_idx[key]] = 1
        rows.append({"a": a, "op": ">=", "b": floor_f * M["forecast"][key], "tag": "floor:" + key})
        # expected shortfall epigraph: t >= sum_{j>=m} p_j v_j - (sum_{j>=m} p_j) q
        at = atoms_for[key]
        for m_i in range(len(at)):
            P = C = 0.0
            for j in range(m_i, len(at)):
                P += at[j][1]
                C += at[j][1] * at[j][0]
            a2 = {t_idx[key]: 1.0}
            for j in lanes_of[key]:
                a2[j] = P
            rows.append({"a": a2, "op": ">=", "b": C, "tag": "epi"})
    for key in prio_keys:
        a = {j: 1.0 for j in lanes_of[key]}
        a[g_idx[key]] = 1
        rows.append({"a": a, "op": ">=", "b": threshold[key], "tag": "chance:" + key})
    t0 = time.perf_counter()
    res = solve_lp(n, c, rows)
    ms = round((time.perf_counter() - t0) * 1000)
    if res["status"] != "optimal":
        return {"status": res["status"], "mode": mode, "ms": ms}
    x = res["x"]
    ship = []
    q = dict.fromkeys(keys, 0.0)
    for j, (L, cat, key) in enumerate(x_vars):
        if x[j] > 1e-6:
            ship.append({"dc": L["dc"], "store": L["store"], "cat": cat, "qty": x[j], "cost": L["cost"]})
            q[key] += x[j]
    relaxed = [{"rule": "floor", "key": key, "units": x[h_idx[key]]} for key in keys if x[h_idx[key]] > 1e-4]
    relaxed += [
        {"rule": "priority", "key": key, "units": x[g_idx[key]]} for key in prio_keys if x[g_idx[key]] > 1e-4
    ]
    return {
        "status": "optimal",
        "mode": mode,
        "ship": ship,
        "q": q,
        "threshold": threshold,
        "tauEach": tau_each,
        "mpe": mpe,
        "relaxed": relaxed,
        "ms": ms,
        "iterations": res["iterations"],
        "nVars": n,
        "nRows": len(rows),
    }


# ---------- MPE query: most likely latent configuration and demand values (max-product)


def mpe_query(M: Model) -> dict[str, Any]:
    best = None
    for k in M["configs"]:
        score = math.log(k["w"])
        demand = {}
        for key in M["sc"]:
            bv, bp = None, -1.0
            for v, p in k["atoms"][key]:
                if p > bp + 1e-12:
                    bp, bv = p, v
            demand[key] = bv
            score += math.log(bp)
        if best is None or score > best["score"]:
            best = {"score": score, "label": k["label"], "demand": demand, "frac": k["frac"], "w": k["w"]}
    assert best is not None
    return best


# ---------- Posterior over named latents and leave-one-out evidence attribution


def diagnose(preset_id: str, spec: dict[str, Any], ev: dict[str, Any], custom: dict[str, Any] | None = None):
    M = build_model(preset_id, spec, ev, {}, custom)
    if preset_id == "toy":
        return {"M": M, "posterior": None, "mpe": mpe_query(M), "attribution": []}
    P = PRESETS["storm"]

    def post(MM: Model) -> dict[str, Any]:
        z, u, e = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], 0.0
        for k in MM["configs"]:
            z[P["Z"].index(k["label"]["z"])] += k["w"]
            u[P["U"].index(k["label"]["u"])] += k["w"]
            if k["label"]["e"]:
                e += k["w"]
        return {"z": z, "u": u, "e": e}

    full = post(M)
    attribution = []
    for field, label in (
        ("advisory", "Storm advisory"),
        ("sales", "TX sales signal"),
        ("emergency", "Emergency status"),
    ):
        if ev.get(field) == "unknown":
            continue
        without = post(build_model(preset_id, spec, {**ev, field: "unknown"}, {}, custom))
        attribution.append(
            {
                "label": label,
                "value": ev.get(field),
                "landfallWithout": without["z"][2],
                "landfallWith": full["z"][2],
                "highWithout": without["u"][2],
                "highWith": full["u"][2],
            }
        )
    return {"M": M, "posterior": full, "mpe": mpe_query(M), "attribution": attribution}


# ---------- Evaluate any plan (from solver, LLM, or operator) exactly under the model


def evaluate_plan(M: Model, ship: list[dict[str, Any]]) -> dict[str, Any]:
    q: dict[str, float] = dict.fromkeys(M["sc"], 0.0)
    issues: list[str] = []
    lane_cost = {L["dc"] + ">" + L["store"]: L["cost"] for L in M["lanes"]}
    used = {d["id"]: 0.0 for d in M["dcs"]}
    transport = 0.0
    for s in ship:
        cost = lane_cost.get(s["dc"] + ">" + s["store"])
        if cost is None:
            issues.append(f"Uses closed or unknown lane {s['dc']} to {s['store']}")
            continue
        if not s["qty"] >= 0:
            continue
        key = s["store"] + "|" + s["cat"]
        q[key] = (q.get(key) or 0) + s["qty"]
        used[s["dc"]] += s["qty"]
        transport += s["qty"] * cost
    for d in M["dcs"]:
        if used[d["id"]] > d["cap"] + 1e-6:
            issues.append(
                f"{d['id']} over capacity by {js_locale_int(js_round(used[d['id']] - d['cap']))} units"
            )
    floor_f = M["spec"]["floor"]["fraction"] if M["spec"].get("floor") else 0
    floor_short = [
        {"key": key, "units": floor_f * M["forecast"][key] - q[key]}
        for key in M["sc"]
        if q[key] < floor_f * M["forecast"][key] - 1e-6
    ]
    short_pen = exp_short_total = 0.0
    per_key = {}
    for key in M["sc"]:
        es = _exp_short(M["marg"][key], q[key])
        per_key[key] = es
        exp_short_total += es
        short_pen += es * M["pen"][key]
    rules = [
        {"key": key, "frac": f, "q": q[key], "p": _p_rule_met(M, key, q[key])} for key, f in M["prio"].items()
    ]
    p_all = _p_all_met(M, q) if M["prio"] else 1
    binding = [f"{d['id']} capacity" for d in M["dcs"] if used[d["id"]] >= d["cap"] - 0.5]
    floor_label = js_str(js_round(floor_f * 100)) + "%"
    for key in M["sc"]:
        if abs(q[key] - floor_f * M["forecast"][key]) < 0.5:
            binding.append(f"{floor_label} floor at {key.replace('|', ' ', 1)}")
    return {
        "q": q,
        "used": used,
        "transport": transport,
        "shortPen": short_pen,
        "expShortTotal": exp_short_total,
        "expCost": transport + short_pen,
        "rules": rules,
        "pAll": p_all,
        "issues": issues,
        "floorShort": floor_short,
        "binding": binding,
        "perKey": per_key,
        "feasible": not issues and not floor_short,
    }


# ---------- Monte Carlo backtest: draw realized weeks from the posterior, score each plan


def sample_world(M: Model, rnd: Callable[[], float]) -> dict[str, Any]:
    r = rnd()
    k = M["configs"][-1]
    for kk in M["configs"]:
        r -= kk["w"]
        if r <= 0:
            k = kk
            break
    d = {}
    for key in M["sc"]:
        r2 = rnd()
        at = k["atoms"][key]
        d[key] = at[-1][0]
        for v, p in at:
            r2 -= p
            if r2 <= 0:
                d[key] = v
                break
    return {"k": k, "d": d}


def backtest(M: Model, plans: list[dict[str, Any]], n: int = 2000, seed: int = 7) -> list[dict[str, float]]:
    rnd = mulberry32(seed)
    met = [0] * len(plans)
    cost = [0.0] * len(plans)
    evals = [evaluate_plan(M, p["ship"]) for p in plans]
    for _ in range(n):
        w = sample_world(M, rnd)
        for pi, ev in enumerate(evals):
            ok = True
            pen = 0.0
            for key in M["sc"]:
                short = max(0, w["d"][key] - ev["q"][key])
                pen += short * M["pen"][key]
                if key in M["prio"] and ev["q"][key] < w["k"]["frac"][key] * w["d"][key] - 1e-9:
                    ok = False
            if ok:
                met[pi] += 1
            cost[pi] += ev["transport"] + pen
    return [{"rate": met[i] / n, "avgCost": cost[i] / n} for i in range(len(plans))]


# ---------- Spec checks: missing parameters (the agent never invents them) and validation


def missing_params(spec: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    if spec.get("tau") is None:
        out.append(
            {
                "param": "tau",
                "q": "How sure must the priority rule be?",
                "opts": [[0.8, "80%"], [0.9, "90%"], [0.95, "95%"]],
            }
        )
    if spec.get("penalties") is None:
        out.append(
            {
                "param": "penalties",
                "q": "What does a unit of shortfall cost (priority / other)?",
                "opts": [
                    [{"priority": 8, "other": 6}, "8 / 6"],
                    [{"priority": 20, "other": 10}, "20 / 10"],
                    [{"priority": 5, "other": 4}, "5 / 4"],
                ],
            }
        )
    return out


_MISSING = object()


def _field(o: Any, key: str) -> Any:
    """``o.key`` in JS: a missing field (or a field of a non-object) is undefined."""
    return o.get(key, _MISSING) if isinstance(o, dict) else _MISSING


def _num(v: Any) -> float:
    """Unary ``+v`` in JS, for the JSON values a spec can hold."""
    if v is _MISSING:
        return math.nan
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        return js_number(v)
    if isinstance(v, list) and len(v) <= 1:
        return _num(v[0]) if v else 0.0
    return math.nan


def _truthy(v: Any) -> bool:
    if v is _MISSING or v is None or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v != 0 and not math.isnan(v)
    if isinstance(v, str):
        return v != ""
    return True


def _text(v: Any) -> str:
    """``${v}`` in JS."""
    if v is _MISSING:
        return "undefined"
    if v is None:
        return "null"
    if isinstance(v, (bool, int, float)):
        return js_str(v)
    return str(v)


def validate_spec(preset: str, raw: Any) -> dict[str, Any]:
    """What the compiler accepts. Unusable parts are dropped with a message in ``errs``."""
    P = PRESETS[preset]
    stores = [s["id"] for s in P["stores"]]
    errs: list[str] = []
    if not _truthy(raw) or not isinstance(raw, (dict, list)):
        return {"spec": None, "errs": ["The spec is not an object."]}
    spec: dict[str, Any] = {
        "priority": [],
        "floor": None,
        "exception": None,
        "crossStateMultiplier": None,
        "penalties": None,
        "tau": None,
        "joint": _truthy(_field(raw, "joint")),
    }
    priority = _field(raw, "priority")
    for r in priority if isinstance(priority, list) else []:
        category = _field(r, "category")
        if category in P["cats"]:
            cat = category
        else:
            cat = P["cats"][0] if len(P["cats"]) == 1 else None
        if not cat:
            errs.append(f"Unknown category “{_text(category)}” in a priority rule.")
            continue
        r_stores = _field(r, "stores")
        r_stores = r_stores if isinstance(r_stores, list) else []
        ss = [s for s in r_stores if s in stores]
        bad = [s for s in r_stores if s not in stores]
        if bad:
            errs.append(f"Unknown stores dropped: {', '.join(_text(s) for s in bad)}.")
        f = _num(_field(r, "fraction"))
        if not (f > 0 and f <= 1):
            errs.append("A priority fraction must be between 0 and 1.")
            continue
        if ss:
            spec["priority"].append({"stores": ss, "category": cat, "fraction": f})
    floor = _field(raw, "floor")
    if _truthy(floor) and 0 <= _num(_field(floor, "fraction")) <= 1:
        spec["floor"] = {"fraction": _num(floor["fraction"])}
    exception = _field(raw, "exception")
    if _truthy(exception) and 0 < _num(_field(exception, "fraction")) <= 1:
        spec["exception"] = {"when": "emergency_declared", "fraction": _num(exception["fraction"])}
    mult = _field(raw, "crossStateMultiplier")
    if mult is not _MISSING and mult is not None:
        m = _num(mult)
        if m >= 1:
            spec["crossStateMultiplier"] = m
        else:
            errs.append("Cross-state multiplier must be at least 1.")
    penalties = _field(raw, "penalties")
    if (
        _truthy(penalties)
        and _num(_field(penalties, "priority")) > 0
        and _num(_field(penalties, "other")) > 0
    ):
        spec["penalties"] = {"priority": _num(penalties["priority"]), "other": _num(penalties["other"])}
    tau = _field(raw, "tau")
    if tau is not _MISSING and tau is not None:
        t = _num(tau)
        if 0.5 < t <= 1:
            spec["tau"] = t
        else:
            errs.append("Confidence τ must be greater than 0.5 and at most 1.")
    if not spec["priority"]:
        errs.append("No priority rule was compiled.")
    return {"spec": spec, "errs": errs}


# ---------- Everything the page shows for one (preset, spec, evidence)


def compute_replan(
    preset: str,
    spec: dict[str, Any],
    ev: dict[str, Any],
    llm_plan: dict[str, Any] | None = None,
    custom: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Condition on the evidence, solve both plans, score them (and any LLM plan), backtest them,
    and value one more step of capacity at each DC.

    Missing tau or penalties are filled with 0.9 and 8/6 for the diagnosis only; nothing is solved
    until the operator supplies them.
    """
    missing = missing_params(spec)
    spec_for_model = spec
    if missing:
        spec_for_model = {
            **spec,
            "tau": 0.9 if spec.get("tau") is None else spec["tau"],
            "penalties": {"priority": 8, "other": 6} if spec.get("penalties") is None else spec["penalties"],
        }
    diag = diagnose(preset, spec_for_model, ev, custom)
    M = diag["M"]
    out: dict[str, Any] = {
        "missing": missing,
        "diag": diag,
        "plans": {},
        "evals": {},
        "bt": None,
        "shadow": None,
    }
    if missing:
        return out
    plans, evals = out["plans"], out["evals"]
    plans["mmap"] = solve_plan(M, "mmap")
    plans["mpe"] = solve_plan(M, "mpe")
    for pid in ("mmap", "mpe"):
        if plans[pid]["status"] == "optimal":
            evals[pid] = evaluate_plan(M, plans[pid]["ship"])
    if llm_plan:
        plans["llm"] = llm_plan
        evals["llm"] = evaluate_plan(M, llm_plan["ship"])
    ids = list(evals)
    bt = backtest(M, [plans[i] for i in ids], 2000, 11)
    out["bt"] = dict(zip(ids, bt, strict=True))
    # marginal value of capacity, by re-solving with more capacity at each DC
    if "mmap" in evals:
        step = 1 if preset == "toy" else 1000
        shadow: dict[str, Any] = {"step": step, "dc": {}}
        for d in M["dcs"]:
            M2 = build_model(preset, spec_for_model, ev, {"capDelta": {d["id"]: step}}, custom)
            if preset == "toy":
                next(x for x in M2["dcs"] if x["id"] == d["id"])["cap"] += step
            p2 = solve_plan(M2, "mmap")
            if p2["status"] == "optimal":
                shadow["dc"][d["id"]] = evaluate_plan(M2, p2["ship"])["expCost"] - evals["mmap"]["expCost"]
        out["shadow"] = shadow
    return out


def verify_lane(
    preset: str,
    spec: dict[str, Any],
    ev: dict[str, Any],
    cur: dict[str, Any] | None,
    custom: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """If the CA→TX lane closed: what the current plan keeps, and what a replan achieves."""
    if not cur or not cur.get("ship"):
        return None
    Mc = build_model(preset, spec, {**ev, "caLane": "closed"}, {}, custom)

    def lost(s: dict[str, Any]) -> bool:
        return s["dc"] == "DC_CA" and s["store"].startswith("TX")

    kept = [s for s in cur["ship"] if not lost(s)]
    lost_lanes = [s for s in cur["ship"] if lost(s)]
    e_kept = evaluate_plan(Mc, kept)
    re = solve_plan(Mc, "mmap")
    e_re = evaluate_plan(Mc, re["ship"]) if re["status"] == "optimal" else None
    return {
        "lostUnits": js_sum(s["qty"] for s in lost_lanes),
        "keptP": e_kept["pAll"],
        "replanP": e_re["pAll"] if e_re else None,
        "replanCost": e_re["expCost"] if e_re else None,
        "replanRelaxed": re.get("relaxed") or [],
    }
