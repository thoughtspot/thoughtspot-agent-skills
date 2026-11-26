"""BL-632: every conditional a translator emits is grouped, so an operator after it cannot
fall into the else branch.

ThoughtSpot's `else` is greedy (live-verified 2026-11-26): `if ( c ) then a else b = x`
compiles to `CASE WHEN c THEN a ELSE (b = x) END`. An MV filter
`COALESCE(is_deleted, false) = false` therefore kept only the deleted and NULL rows.
"""
import pytest

from ts_cli.databricks.mv_sql import translate_sql_expr as dbx
from ts_cli.sql_forms import sqlf_if_chain, sqlf_unwrap_conditional
from ts_cli.sv_sql import translate_sql_expr as sv


def _res(name: str) -> str:
    return f"[T::{name}]"


BOTH = pytest.mark.parametrize("translate", [dbx, sv], ids=["databricks", "snowflake"])


def _else_swallows(ts: str) -> bool:
    """True if an `else` branch reaches an operator outside the conditional's group."""
    depth_at_if, depth = [], 0
    toks = ts.split()
    for i, t in enumerate(toks):
        if t == "(":
            depth += 1
        elif t == ")":
            depth -= 1
            while depth_at_if and depth_at_if[-1] > depth:
                depth_at_if.pop()
        elif t == "if":
            depth_at_if.append(depth)
        elif t in ("=", "!=", "+", "-", "*", "/", ">", "<", ">=", "<=", "and", "or") \
                and depth_at_if and depth_at_if[-1] == depth and "else" in toks[:i]:
            return True
    return False


@BOTH
@pytest.mark.parametrize("sql", [
    "COALESCE(a, false) = false",
    "COALESCE(a, b, 0) + 1",
    "CASE WHEN a > 1 THEN 'x' ELSE 'y' END = 'x'",
    "CASE WHEN a > 1 THEN 1 WHEN a > 0 THEN 2 ELSE 0 END * 2",
    "IFF(a > 1, 1, 0) + 1",
    "1 + COALESCE(a, 0) + 1",
])
def test_conditional_followed_by_an_operator_is_grouped(translate, sql):
    out = translate(sql, _res)
    assert not _else_swallows(out), out


@BOTH
def test_the_deleted_row_filter_compares_the_whole_conditional(translate):
    assert translate("COALESCE(d, false) = false", _res) == \
        "( if ( [T::d] != null ) then [T::d] else false ) = false"


def test_snowflake_nvl2_is_grouped():
    assert sv("NVL2(a, 1, 0) + 1", _res) == "( if ( [T::a] != null ) then 1 else 0 ) + 1"


@BOTH
def test_a_whole_call_argument_needs_no_brackets(translate):
    assert translate("SUM(CASE WHEN a = 1 THEN 1 ELSE 0 END)", _res) == \
        "sum ( if ( [T::a] = 1 ) then 1 else 0 )"


def test_unwrap_leaves_a_group_that_continues():
    assert sqlf_unwrap_conditional("( if ( c ) then 1 else 0 ) + 1") == \
        "( if ( c ) then 1 else 0 ) + 1"
    assert sqlf_unwrap_conditional(sqlf_if_chain([("c", "1")], "0")) == \
        "if ( c ) then 1 else 0"


def test_the_detector_fires_on_the_old_bare_form():
    # proves the check above can fail: this is what the translators used to emit
    assert _else_swallows("if ( [T::d] != null ) then [T::d] else false = false")
