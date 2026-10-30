"""Shared helpers: write numbers and names as ProbLog, and run a program through tddlog."""

from __future__ import annotations

import sys
from pathlib import Path

import tddlog

# The ported demo engines (demos/backend/src/pillar_demos). They are pure Python plus numpy.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "demos" / "backend" / "src"))

CALLS = {"n": 0}  # how many tddlog runs, for the report


def num(v: float) -> str:
    """A number as ProbLog reads it, exactly: repr keeps every digit, and ProbLog wants a point
    before an exponent (1.0e-07, not 1e-07)."""
    if isinstance(v, bool):
        raise TypeError("a Boolean is not a number here")
    if isinstance(v, int) or float(v).is_integer() and abs(v) < 1e15:
        return str(int(v))
    r = repr(float(v))
    mantissa, _, exponent = r.partition("e")
    if exponent and "." not in mantissa:
        r = f"{mantissa}.0e{exponent}"
    return r


def atom(name: str) -> str:
    """A name as a ProbLog constant: lower case, letters, digits and underscores."""
    out = "".join(ch if ch.isalnum() else "_" for ch in name.lower())
    return out if out[:1].isalpha() else "k_" + out


def solve(program: str) -> dict[str, float] | None:
    """Every query's probability given the evidence; None when the evidence is impossible."""
    CALLS["n"] += 1
    return tddlog.solve(program).answers
