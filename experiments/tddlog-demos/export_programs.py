"""Write example ProbLog programs, one per demo scenario, to programs/*.pl, so the models can be
read, run with the tddlog command line (`tddlog programs/replan_storm.pl`) or checked with
ProbLog. Each program carries the queries the engines ask of it."""

from __future__ import annotations

from pathlib import Path

import copilot_tddlog as CT
import replan_tddlog as RT
from pillar_demos import copilot as C
from pillar_demos import replan as R

OUT = Path(__file__).resolve().parent / "programs"


def write(name: str, header: str, lines: list[str]) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.pl").write_text("\n".join([f"% {line}" for line in header.splitlines()] + [""] + lines) + "\n")


def main() -> None:
    # Copilot: the storm scenario with the page's fixed example plan.
    p = {**C.BASE, "scenario": "storm", "backupEnabled": True, "tau": 0.9}
    x = [50, 40, 31, 9, 0, 0, 0, 50, 13]
    write("copilot_storm", "Circuit Copilot, storm scenario, no evidence: the plan A 50/40/31/9, B 0/0/0/50,\n"
          "backup 13. holds(p0) is the probability the priority rule holds (0.7).",
          CT.model(p) + CT.plan_facts(0, x) + ["query(world(_)).", "query(holds(p0))."])

    for preset, ev in (("toy", R.DEFAULT_EVIDENCE), ("storm", R.DEFAULT_EVIDENCE)):
        spec = {**R.PRESETS[preset]["defaultSpec"]}
        spec["tau"] = spec["tau"] or 0.9
        prog = RT.Program(preset, spec, ev)
        names = [prog.name[k] for k in prog.prio]
        q = {k: prog.threshold(k, 1 - (1 - spec["tau"]) / len(prog.prio) if spec.get("joint") else spec["tau"]) for k in prog.prio}
        queries = ([] if preset == "toy" else ["query(z(_)).", "query(u(_)).", "query(emerg)."]) + [
            *(f"recv({prog.name[k]}, {v})." for k, v in q.items()),
            "all_met :- " + ", ".join(f"met({n})" for n in names) + ".",
            *(f"query(met({n}))." for n in names),
            "query(all_met).",
        ]
        write(f"replan_{preset}", f"PILLAR Replan, {preset} preset, default rules and evidence. recv/2 gives each\n"
              "priority store its chance threshold; met/1 and all_met are the rule's probabilities there.",
              prog.text + queries)
    print("wrote", ", ".join(sorted(f.name for f in OUT.glob("*.pl"))))


if __name__ == "__main__":
    main()
