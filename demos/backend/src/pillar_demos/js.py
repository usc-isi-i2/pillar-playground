"""JavaScript number semantics the engines depend on.

The engines were written in JavaScript, and their results are pinned by golden files captured from
the original pages. These helpers reproduce the JS behaviour where Python differs:

- ``Math.round`` rounds halves up; Python's ``round`` rounds them to even.
- The random generators use 32-bit integer arithmetic (``Math.imul``, ``|0``, ``>>>``).
- ``String(number)`` and ``toLocaleString()`` format numbers differently from ``str``.
- Python 3.12's ``sum`` compensates float rounding; JS ``reduce`` does not. Use ``js_sum``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable


def js_round(x: float) -> float:
    """``Math.round``: nearest integer, halves toward +infinity."""
    if not math.isfinite(x):
        return x
    r = math.floor(x)
    return float(r + 1 if x - r >= 0.5 else r)


def js_sum(values: Iterable[float], start: float = 0) -> float:
    """Left-to-right addition, like ``reduce((a, b) => a + b, start)``."""
    total = start
    for v in values:
        total += v
    return total


def i32(x: int) -> int:
    """ToInt32."""
    return ((x + 0x80000000) & 0xFFFFFFFF) - 0x80000000


def u32(x: int) -> int:
    """ToUint32 (the result of ``x >>> 0``)."""
    return x & 0xFFFFFFFF


def imul(a: int, b: int) -> int:
    """``Math.imul``."""
    return i32(u32(a) * u32(b))


def mulberry32(seed: int) -> Callable[[], float]:
    """The mulberry32 generator, as written in both demo engines."""
    state = i32(seed)

    def rnd() -> float:
        nonlocal state
        state = i32(state + 0x6D2B79F5)
        s = state
        t = imul(s ^ (u32(s) >> 15), 1 | s)
        t = i32(t + imul(t ^ (u32(t) >> 7), 61 | t)) ^ t
        return u32(t ^ (u32(t) >> 14)) / 4294967296

    return rnd


def js_str(x: float | int) -> str:
    """``String(number)``: shortest round-trip digits, JS exponent rules."""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        return str(x)
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    mantissa, _, exp = repr(abs(x)).partition("e")
    int_part, _, frac = mantissa.partition(".")
    digits = (int_part + frac).lstrip("0")
    # Decimal exponent n such that the value is 0.d1d2... * 10**n.
    shift = int(exp) if exp else 0
    if int_part == "0":
        n = shift - (len(frac) - len(frac.lstrip("0")))
    else:
        n = shift + len(int_part)
    digits = digits.rstrip("0")
    k = len(digits)
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * -n + digits
    e = n - 1
    body = digits[0] + ("." + digits[1:] if k > 1 else "")
    return f"{sign}{body}e{'+' if e > 0 else '-'}{abs(e)}"


def js_locale_int(x: float) -> str:
    """``Math.round(x).toLocaleString('en-US')`` for an already-integral number."""
    return f"{int(x):,}"


# The whitespace String.prototype.trim removes.
_JS_WS = (
    " \t\n\v\f\r\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


def js_number(s: str) -> float:
    """``Number(string)``: whitespace-trimmed decimal, ``Infinity``, or 0x/0o/0b integer; else NaN."""
    t = js_trim(s)
    if not t:
        return 0.0
    if t in ("Infinity", "+Infinity"):
        return math.inf
    if t == "-Infinity":
        return -math.inf
    if len(t) > 2 and t[0] == "0" and t[1] in "xXoObB":
        try:
            return float(int(t[2:], {"x": 16, "o": 8, "b": 2}[t[1].lower()]))
        except ValueError:
            return math.nan
    # Python's float() also accepts "nan", "inf", "infinity" and digit underscores; JS does not.
    if not all(ch in "0123456789+-.eE" for ch in t):
        return math.nan
    try:
        return float(t)
    except ValueError:
        return math.nan


def js_trim(s: str) -> str:
    """``String.prototype.trim``."""
    return s.strip(_JS_WS)
