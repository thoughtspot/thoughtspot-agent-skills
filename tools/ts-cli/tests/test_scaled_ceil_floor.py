"""formula_common.scaled_ceil_floor / nudged — directed rounding at a decimal scale (#577 review).

The 0.161.0 snap ``round ( v , 1e-9 )`` compiled to ``1.0E-9 * round ( v / 1.0E-9 )`` and made
``ceil`` jump a step on exact grid values (live 2026-10-07, probe record §7). These pin the
nudge forms and check them by value, in IEEE doubles as the warehouse computes them.
"""
from __future__ import annotations

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext

import pytest

from ts_cli.formula_common import nudged, scaled_ceil_floor


def test_forms():
    assert scaled_ceil_floor("[x]", 2, "ceil", True) == "ceil ( [x] * 100 - 0.000000001 ) / 100"
    assert scaled_ceil_floor("[x]", 1, "floor", True) == "floor ( [x] * 10 + 0.000000001 ) / 10"
    assert scaled_ceil_floor("[x]", 0, "ceil", True) == "ceil ( [x] - 0.000000001 )"
    assert scaled_ceil_floor("[x]", -1, "floor", True) == "floor ( [x] / 10 + 0.000000001 ) * 10"
    assert scaled_ceil_floor("[x]", 2, "ceil", False) == "ceil ( [x] * 100 ) / 100"
    # beyond 6 digits an integer quotient is cut to scale 6: the increment is used instead
    assert scaled_ceil_floor("[x]", 8, "floor", False) == \
        "floor ( [x] * 100000000 ) * 0.00000001"
    with pytest.raises(ValueError):
        nudged("[x]", "round", True)


def _excel(x: float, n: int, mode) -> Decimal:
    with localcontext() as c:
        c.prec = 15
        v = +Decimal(repr(x))                       # Excel's 15-significant-digit reading
    return (v * Decimal(10) ** n).to_integral_value(rounding=mode) / Decimal(10) ** n


def _ts(x: float, n: int, fn: str) -> float:
    f = 10.0 ** abs(n)
    g = math.ceil if fn == "ceil" else math.floor
    eps = -1e-9 if fn == "ceil" else 1e-9
    if n >= 0:
        return g(x * f + eps) / f
    return g(x / f + eps) * f


GRID = [3.0, 0.15, 0.29, 2.5, 1.1, -200.0, 0.57, 40.955, 3.00000001, -0.57, 1.101, -1.1]


@pytest.mark.parametrize("x", GRID)
@pytest.mark.parametrize("n", [0, 1, 2, -1])
@pytest.mark.parametrize("fn,mode", [("ceil", ROUND_CEILING), ("floor", ROUND_FLOOR)])
def test_grid_matches_excel(x, n, fn, mode):
    assert Decimal(repr(_ts(x, n, fn))) == _excel(x, n, mode)


def test_the_tradeoff_is_a_value_within_1e9_of_a_step():
    # documented: 3.000000000001 rounded up reads as 3 (Excel, at 15 digits, gives 4)
    assert _ts(3.000000000001, 0, "ceil") == 3
    assert _excel(3.000000000001, 0, ROUND_CEILING) == 4
