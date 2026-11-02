"""Run one scenario of each demo with tddlog and write every ProbLog program the code builds, as
sent to tddlog and with tddlog's answers, to a folder for review (default programs/review).

    uv run --project ../../demos/backend --with <tddlog wheel> python review_run.py [folder]

The scenarios: Replan's storm preset with the default rules and evidence, Copilot's storm scenario
with its default settings, and the forecast comparison on the correlated sample data at capacity
240. Any run can be dumped the same way by setting TDDLOG_DUMP=<folder> (see problog_text.py).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

folder = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent / "programs" / "review")
shutil.rmtree(folder, ignore_errors=True)  # only this run's programs
os.environ["TDDLOG_DUMP"] = str(folder)  # read when problog_text is imported, below

import copilot_tddlog as CT  # noqa: E402
import evaluation_tddlog as ET  # noqa: E402
import replan_tddlog as RT  # noqa: E402
from pillar_demos import copilot as C  # noqa: E402
from pillar_demos import evaluation as E  # noqa: E402
from pillar_demos import replan as R  # noqa: E402

with RT.Patched():
    R.compute_replan("storm", {**R.PRESETS["storm"]["defaultSpec"], "tau": 0.9}, R.DEFAULT_EVIDENCE)
with CT.Patched():
    p = C.validate({"scenario": "storm"})
    C.analyze(C.compile_circuit(p), p)
with ET.Patched():
    E.run(E.synthetic("correlated"), {"priority_floor": 0.9, "base_floor": 0.6, "emergency": False}, 240, "joint")

files = sorted(folder.glob("*.pl"))
groups: dict[str, int] = {}
for f in files:
    stem = f.stem.rsplit("-", 1)[0]
    groups[stem] = groups.get(stem, 0) + 1
print(f"wrote {len(files)} programs to {folder}:")
for stem, n in groups.items():
    print(f"  {n:3d} x {stem}")
