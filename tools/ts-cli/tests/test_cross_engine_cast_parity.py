"""Cross-engine construct parity for SQL CAST — LOAD-BEARING types only.

The recurrence guard BL-161 item 1 predicted the need for but never got: "a
tokenizer bug fixed in one engine silently persists in the other". The 2026-08-26
audit (finding 4.1) found it had already happened — `mv_sql_constructs._construct_cast`
discarded the CAST target type outright (`tk, _ttext = cur.advance()  # dropped`)
while `sv_sql._construct_cast` mapped it:

    SF   CAST(x AS INT)   ->  to_integer ( [T::x] )
    DBX  CAST(x AS INT)   ->  [T::x]                  # value silently changed

Scope matters here, and the scope is narrower than the finding implied.

LOAD-BEARING casts (int truncation, date time-drop, bool coercion) change the
VALUE, so dropping one is a wrong-numbers bug and both engines must agree. Those
are what this file asserts.

WIDENING casts are a DOCUMENTED divergence and deliberately not asserted:

  * Snowflake emits the conversion — `CAST(x AS DOUBLE)` -> `to_double([x])` — per
    ts-snowflake-formula-translation.md, and `to_double` is a valid ThoughtSpot
    formula function per thoughtspot-formula-patterns.md.
  * Databricks unwraps it, per the ts-from-databricks worked example. Verified live
    on se-thoughtspot 2026-08-26:
        SELECT SUM("UNITS_SOLD") / COUNT("ORDER_ID")  ->  type DOUBLE, 5128.71
    Both operands are INT64, so ThoughtSpot promotes integer division on its own and
    the cast around a numerator is genuinely redundant.

Asserting agreement on widening types would force one engine to abandon its
documented behaviour, which is why this file does not.
"""
from __future__ import annotations

import pytest

from ts_cli.databricks.mv_sql import translate_sql_expr as dbx_translate
from ts_cli.formula_common import (CAST_MAP_LOAD_BEARING, CAST_TYPES_WIDENING,
                                   UntranslatableError)
from ts_cli.sv_sql import translate_sql_expr as sf_translate


def _resolver(ident: str) -> str:
    return f"[T::{ident}]"


@pytest.mark.parametrize("sql_type", sorted(CAST_MAP_LOAD_BEARING))
def test_load_bearing_casts_agree_across_engines(sql_type):
    expr = f"CAST(x AS {sql_type})"
    assert sf_translate(expr, _resolver) == dbx_translate(expr, _resolver)


@pytest.mark.parametrize("sql_type", sorted(CAST_MAP_LOAD_BEARING))
def test_load_bearing_cast_is_never_dropped(sql_type):
    """The specific 4.1 regression: a bare `[T::x]` means the type was discarded."""
    expr = f"CAST(x AS {sql_type})"
    fn = CAST_MAP_LOAD_BEARING[sql_type]
    for name, translate in (("snowflake", sf_translate), ("databricks", dbx_translate)):
        out = translate(expr, _resolver)
        assert out != "[T::x]", f"{name}: {expr} dropped the target type"
        assert fn in out, f"{name}: expected {fn} in {out!r}"


@pytest.mark.parametrize("sql_type", sorted(CAST_TYPES_WIDENING))
def test_widening_cast_never_raises_in_either_engine(sql_type):
    """Both must ACCEPT widening types; what they emit is allowed to differ."""
    expr = f"CAST(x AS {sql_type})"
    for name, translate in (("snowflake", sf_translate), ("databricks", dbx_translate)):
        out = translate(expr, _resolver)
        assert out, f"{name}: {expr} produced nothing"


def test_databricks_unwraps_widening_per_worked_example():
    """ts-from-databricks Measure 6 — the golden shape this must not change."""
    assert dbx_translate("CAST(SUM(x) AS DOUBLE) / COUNT(*)", _resolver) == \
        "sum ( [T::x] ) / count ( 1 )"


def test_unknown_cast_target_fails_loudly_in_both_engines():
    """Neither engine may silently unwrap a type it does not recognise — that is
    exactly where dropping it changes the answer."""
    for name, translate in (("snowflake", sf_translate), ("databricks", dbx_translate)):
        with pytest.raises(UntranslatableError):
            translate("CAST(x AS GEOGRAPHY)", _resolver)
