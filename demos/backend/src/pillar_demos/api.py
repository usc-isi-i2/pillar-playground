"""HTTP API for the demos: the engines, plus the optional ChatGPT connection.

Run with ``uvicorn pillar_demos.api:app``. When ``demos/frontend/dist`` exists (``npm run build``),
the built pages are served too, so one process runs the whole app.

Engine errors the operator should see come back as 400 ``{"error": message}``.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import chatgpt
from . import copilot as C
from . import evaluation as EV
from . import replan as R

app = FastAPI(title="PILLAR demos")


@app.exception_handler(C.ValidationError)
@app.exception_handler(EV.EvaluationError)
async def _operator_error(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=400)


# ---------- ChatGPT


@app.get("/api/config")
def config() -> dict[str, bool]:
    return {"connected": chatgpt.configured()}


class ChatGPTRequest(BaseModel):
    prompt: str
    json_mode: bool = Field(False, alias="json")


@app.post("/api/chatgpt")
async def ask_chatgpt(body: ChatGPTRequest) -> JSONResponse:
    try:
        return JSONResponse({"text": await chatgpt.respond(body.prompt, body.json_mode)})
    except chatgpt.ChatGPTError as e:
        return JSONResponse({"error": str(e), "code": e.code}, status_code=e.status)


# ---------- Circuit Copilot


@app.get("/api/copilot/setup")
def copilot_setup() -> dict[str, Any]:
    return {"base": C.BASE, "independence": C.independence_contrast()}


class CopilotRequest(BaseModel):
    params: Any


@app.post("/api/copilot/analyze")
def copilot_analyze(body: CopilotRequest) -> dict[str, Any]:
    """The decision and most-likely-world plan for one parameter object, with what the page shows."""
    t0 = time.perf_counter()
    p = C.validate(body.params)
    c = C.compile_circuit(p)
    compile_ms = (time.perf_counter() - t0) * 1000
    out = C.analyze(c, p)
    shown = out["result"]["best"] or out["mpe"]
    return {
        "p": p,
        "circuit": c,
        "alpha": C.alpha(p),
        "worldWeights": C.world_weights(c, p),
        **out,
        # Gate values for the plan the page shows (the decision, else the most-likely-world plan).
        "circuitValues": C.evaluate(c, shown["x"], p)["values"] if shown else None,
        "compileMs": compile_ms,
        "ms": (time.perf_counter() - t0) * 1000,
    }


@app.post("/api/copilot/minimum-backup")
def copilot_minimum_backup(body: CopilotRequest) -> dict[str, Any] | None:
    p = C.validate(body.params)
    return C.minimum_backup(C.compile_circuit(p), p)


# ---------- Replan


def _slide_check() -> list[dict[str, float]]:
    """The toy plan at τ = 70% and 90%, which slide 20 reports as transport 421 and 429."""
    out = []
    for tau in (0.7, 0.9):
        M = R.build_model("toy", {**R.PRESETS["toy"]["defaultSpec"], "tau": tau}, {})
        e = R.evaluate_plan(M, R.solve_plan(M, "mmap")["ship"])
        out.append({"tau": tau, "transport": e["transport"], "s4": e["q"]["S4|units"]})
    return out


@app.get("/api/replan/setup")
def replan_setup() -> dict[str, Any]:
    return {"presets": R.PRESETS, "defaultEvidence": R.DEFAULT_EVIDENCE, "slideCheck": _slide_check()}


class ReplanModel(BaseModel):
    preset: str
    spec: dict[str, Any]
    ev: dict[str, Any]
    custom: dict[str, Any] | None = None


class ComputeRequest(ReplanModel):
    llmPlan: dict[str, Any] | None = None


@app.post("/api/replan/compute")
def replan_compute(body: ComputeRequest) -> dict[str, Any]:
    out = R.compute_replan(body.preset, body.spec, body.ev, body.llmPlan, body.custom)
    marg = out["diag"]["M"]["marg"]
    # Per-key demand summaries the page prints.
    out["stats"] = {
        key: {"mean": R.mean(a), "p10": R.quantile(a, 0.1), "p90": R.quantile(a, 0.9)}
        for key, a in marg.items()
    }
    return out


class ValidateSpecRequest(BaseModel):
    preset: str
    raw: Any


@app.post("/api/replan/validate-spec")
def replan_validate_spec(body: ValidateSpecRequest) -> dict[str, Any]:
    return R.validate_spec(body.preset, body.raw)


class VerifyLaneRequest(ReplanModel):
    plan: dict[str, Any] | None = None


@app.post("/api/replan/verify-lane")
def replan_verify_lane(body: VerifyLaneRequest) -> dict[str, Any] | None:
    return R.verify_lane(body.preset, body.spec, body.ev, body.plan, body.custom)


class SampleWorldRequest(ReplanModel):
    # Uniform draws from the page, one for the configuration and one per demand key, so the
    # draw comes from the browser's random source as it did originally.
    uniforms: list[float]


@app.post("/api/replan/sample-world")
def replan_sample_world(body: SampleWorldRequest) -> dict[str, Any]:
    M = R.build_model(body.preset, body.spec, body.ev, {}, body.custom)
    draws = iter(body.uniforms)
    return R.sample_world(M, lambda: next(draws))


# ---------- Forecast comparison


class SyntheticRequest(BaseModel):
    kind: str


@app.post("/api/evaluation/synthetic")
def evaluation_synthetic(body: SyntheticRequest) -> dict[str, Any]:
    return EV.synthetic(body.kind)


class ParseRequest(BaseModel):
    csv: str


@app.post("/api/evaluation/parse")
def evaluation_parse(body: ParseRequest) -> dict[str, Any]:
    return EV.parse(body.csv)


class CompareRequest(BaseModel):
    data: dict[str, Any]
    # The pasted translation, already parsed from JSON by the page; null when none was pasted.
    rules: Any = None
    # null when the field is empty or not a finite number
    capacity: float | None
    dependence: str


REFERENCE_RULES = {"priority_floor": 0.9, "base_floor": 0.6, "emergency": False}


@app.post("/api/evaluation/compare")
def evaluation_compare(body: CompareRequest) -> dict[str, Any]:
    """Reference and ChatGPT rules, each planned on the point mean and on the empirical distribution."""
    if body.capacity is None or not math.isfinite(body.capacity) or body.capacity <= 0:
        raise EV.EvaluationError("Enter a positive finite capacity.")
    f = EV.fit(body.data)
    rules = EV.rules(body.rules) if body.rules is not None else None
    rows = []
    for name, r in (("Reference", REFERENCE_RULES), ("ChatGPT", rules)):
        for uncertain in (False, True):
            rows.append(
                {
                    "name": name,
                    "demand": "Empirical distribution" if uncertain else "Point mean",
                    "result": EV.solve(f, r, uncertain, body.capacity, body.dependence) if r else None,
                }
            )
    test = f["test"]
    abs_err = 0.0
    for r in test:
        b = 0.0
        for j, d in enumerate(r["x"]):
            b += abs(d - f["mean"][j])
        abs_err += b
    best = rows[1]["result"]["best"]
    failure_dates = (
        [r["date"] for r in test if any(best["x"][j] < 0.9 * d - 1e-8 for j, d in enumerate(r["x"]))]
        if best
        else None
    )
    return {
        "referenceRules": REFERENCE_RULES,
        "rules": rules,
        "matchesReference": rules is not None and all(rules[k] == v for k, v in REFERENCE_RULES.items()),
        "trainDates": [r["date"] for r in f["train"]],
        "testDates": [r["date"] for r in test],
        "rows": rows,
        "mae": abs_err / (3 * len(test)),
        "failureDates": failure_dates,
    }


# ---------- The built pages, when present

_DIST = Path(os.environ.get("PILLAR_DEMOS_DIST", Path(__file__).resolve().parents[3] / "frontend" / "dist"))
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="pages")
