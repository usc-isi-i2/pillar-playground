# Experiments

Work that goes beyond the learning material and the demos: solving the PILLAR demos' problems
with tididi circuits and with tddlog. Nothing here changes `demos/`; the experiments read the
solver-ready models and the ported engines, and check every answer against HiGHS, the original
pages' captured outputs, or ProbLog.

| Folder | What it does | Result |
|---|---|---|
| [`lp-to-tididi/`](lp-to-tididi/) | Compiles linear and mixed-integer programs into tididi circuits and finds the cheapest plan on the circuit. `compile.py` builds the Copilot, Replan toy and stocking models by hand; `compile_lp.py` reads any `.mps` file (bound and cost tightening, helper variables folded into costs, vtrees from goatd tree decompositions and bisection, scored and raced); `m5_export.py` exports M5-CLARA's planners as `.mps` | Matches HiGHS on every Copilot, Replan toy and stocking model. Refuses the Replan storm LPs (about 972,000 yes/no variables) and M5-CLARA (about 18,700) |
| [`tddlog-demos/`](tddlog-demos/) | Writes both demos as ProbLog programs and has [tddlog](https://github.com/Tractables/tddlog) compute every probability; the LP still picks the shipments. See its [README](tddlog-demos/README.md) | Matches the original pages on every Copilot case and on every Replan decision (74/74); tddlog agrees with ProbLog to 8e-15 on 15,264 queries |

`lp-to-tididi/probe.py` and `small.py` are early size probes from before the out-of-memory fix,
kept for the record.

## Write-ups (Claude docs)

From this work:

- [PILLAR Replan, explained simply](https://claude.ai/artifact/KxAAikLnPRcHSAt7NTiJWK): the
  Replan problem, how the HTML demo solves it as an LP, and what the tididi version does.
- [Solving the Replan toy two ways](https://claude.ai/artifact/8GYWiNb3XaooYs8veLYndz): the toy
  solved as an LP with the working and the shadow-price proof, then with tididi step by step,
  with a drawn slice of the real circuit.
- [Replan storm case with tddlog](https://claude.ai/artifact/MjVrwepnf85GYGCq5rn5MA): the storm
  case with tddlog computing the probabilities; the ProbLog model, results and checks.

Related, on the playground's learning material:

- [Learning guide: from ProbLog to probabilistic circuits](https://claude.ai/artifact/GmCdv73J9y5RrgeZVfh8tc)
- [Practice guide: DeepProbLog problems as tididi circuits](https://claude.ai/artifact/XJBwUQR1FPiDnAchgkatKj)
- [How the digit-addition example works](https://claude.ai/artifact/4AREZadC4HaG4bb9UJqJxH)

## Running

- `lp-to-tididi` uses the playground's `.venv` (tididi built from `../tididi`, plus goatd from
  PyPI) and reads the models from `~/Downloads/PILLAR_Solver_Models` (`PILLAR_SOLVER_MODELS`
  overrides it). Run large models under a memory watchdog: a model past tididi's limits can still
  use several gigabytes before they stop it.
- `tddlog-demos` runs in the demos backend's Python 3.12 environment with tddlog's wheel added
  for the run; its README has the build and run commands.
