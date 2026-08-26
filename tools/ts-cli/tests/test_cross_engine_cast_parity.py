"""Cross-engine construct parity for SQL CAST.

The recurrence guard BL-161 item 1 predicted but never got. That item warned that
"a tokenizer bug fixed in one engine silently persists in the other"; the
2026-08-26 audit (finding 4.1) found it had already happened —
`databricks/mv_sql_constructs._construct_cast` discarded the CAST target type
outright while `sv_sql._construct_cast` mapped it:

    SF   CAST(x AS INT)    ->  to_integer ( [T::x] )
    DBX  CAST(x AS INT)    ->  [T::x]              # type dropped

That is a silent wrong-numbers defect, not a cosmetic one: `CAST(4.7 AS INT)` must
truncate to 4 and `CAST(ts AS DATE)` must drop the time component. Both engines now
emit through `formula_common.CAST_MAP`.

This file asserts AGREEMENT rather than exact strings on purpose. A future change to
the emitted form is fine as long as both engines change together; the failure mode
worth catching is divergence.
"""
from __future__ import annotations

import pytest

from ts_cli.databricks.mv_sql import translate_sql_expr as dbx_translate
from ts_cli.formula_common import CAST_MAP
from ts_cli.sv_sql import translate_sql_expr as sf_translate


def _resolver(ident: str) -> str:
    return f"[T::{ident}]"


CAST_CORPUS = [
    "CAST(x AS INT)",
    "CAST(x AS INTEGER)",
    "CAST(x AS BIGINT)",
    "CAST(x AS SMALLINT)",
    "CAST(x AS DOUBLE)",
    "CAST(x AS FLOAT)",
    "CAST(x AS DECIMAL(10,2))",
    "CAST(x AS NUMERIC)",
    "CAST(x AS STRING)",
    "CAST(x AS VARCHAR)",
    "CAST(x AS TEXT)",
    "CAST(ts AS DATE)",
    "CAST(ts AS TIMESTAMP)",
    "CAST(b AS BOOLEAN)",
]


@pytest.mark.parametrize("expr", CAST_CORPUS)
def test_both_engines_agree_on_cast(expr):
    assert sf_translate(expr, _resolver) == dbx_translate(expr, _resolver)


@pytest.mark.parametrize("expr", CAST_CORPUS)
def test_cast_emits_a_conversion_function_not_a_bare_column(expr):
    """The specific 4.1 regression: a bare `[T::x]` means the type was dropped."""
    for name, translate in (("snowflake", sf_translate), ("databricks", dbx_translate)):
        out = translate(expr, _resolver)
        assert out != "[T::x]", f"{name}: {expr} emitted a bare column — target type dropped"
        assert "(" in out, f"{name}: {expr} emitted no conversion call: {out!r}"


def test_every_cast_map_target_is_reachable_from_both_engines():
    """Guards against one engine gaining a type the other cannot parse."""
    for sql_type, fn in sorted(CAST_MAP.items()):
        expr = f"CAST(x AS {sql_type})"
        sf_out = sf_translate(expr, _resolver)
        dbx_out = dbx_translate(expr, _resolver)
        assert sf_out == dbx_out, f"{sql_type}: {sf_out!r} != {dbx_out!r}"
        assert fn in sf_out, f"{sql_type}: expected {fn} in {sf_out!r}"


def test_unmapped_cast_target_fails_loudly_in_both_engines():
    """An unmapped type must raise, never silently emit a cast-free expression —
    that is precisely where dropping the type changes the numbers."""
    from ts_cli.formula_common import UntranslatableError
    for name, translate in (("snowflake", sf_translate), ("databricks", dbx_translate)):
        with pytest.raises(UntranslatableError):
            translate("CAST(x AS GEOGRAPHY)", _resolver)
