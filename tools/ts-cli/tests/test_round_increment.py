"""BL-331 — ThoughtSpot round(x, n): n is a rounding INCREMENT, not a digit count.

Live-probed on se-thoughtspot 2026-10-06 (`ts agentql generate-sql`): ThoughtSpot
compiles round(x, n) to `n * round(x / NULLIF(n, 0))`. On 1234.5678, round(x, 2)
is 1234 and round(x, 0.01) is 1234.57; round(x, 0) is NULL. Every SQL dialect
(Snowflake, Databricks, Tableau, DAX) takes a digit count, so a translator that
copies the 2nd argument across returns a silently wrong number. These tests pin
the conversion in both directions, for every translator that carries it.
"""
from __future__ import annotations

import re

import pytest

from ts_cli.databricks.mv_emit_expr import parse_formula
from ts_cli.databricks.mv_emit_sql import emit_sql
from ts_cli.databricks.mv_sql import translate_sql_expr as dbx_to_ts
from ts_cli.formula_common import (
    UntranslatableError,
    sql_digits_to_ts_increment,
    ts_increment_to_sql_digits,
    ts_round_from_sql_digits,
)
from ts_cli.powerbi.functions import translate_dax
from ts_cli.sv_sql import translate_sql_expr as sf_to_ts
from ts_cli.tableau.functions import map_functions
from ts_cli.tableau_translate import translate_single


def _sf_res(ident: str) -> str:
    return f"[T::{ident.split('.')[-1]}]"


def _dbx_res(path: str) -> str:
    return f"[T::{path.split('.')[-1]}]"


def _emit(expr: str) -> str:
    return emit_sql(parse_formula(expr), lambda n: f"source.{n['column']}")


# A TS round() whose 2nd arg is a bare integer >= 2 is the bug's exact signature:
# SQL ROUND(x, 2) copied across. (round(x, 1) is the correct form of ROUND(x, 0).)
_DIGIT_COPY = re.compile(r"round\s*\(\s*[^,()]+,\s*(?:-\s*)?[2-9]\d*\s*\)")


# --- shared helpers ---------------------------------------------------------

class TestSharedHelpers:
    @pytest.mark.parametrize("d, inc", [
        ("0", "1"), ("2", "0.01"), ("-2", "100"), ("- 2", "100"), ("1", "0.1"),
        ("12", "0.000000000001"), ("+3", "0.001"), ("(2)", "0.01"),
    ])
    def test_digits_to_increment(self, d, inc):
        assert sql_digits_to_ts_increment(d) == inc

    @pytest.mark.parametrize("d", ["[T::p]", "2.5", "a + 1", "", "'2'"])
    def test_non_literal_digits(self, d):
        assert sql_digits_to_ts_increment(d) is None

    @pytest.mark.parametrize("inc, d", [
        ("0.01", 2), ("1", 0), ("100", -2), ("10", -1), ("0.1", 1), ("1.0", 0),
        (".001", 3),
    ])
    def test_increment_to_digits(self, inc, d):
        assert ts_increment_to_sql_digits(inc) == d

    @pytest.mark.parametrize("inc", ["0.5", "25", "2", "0.25", "-0.01", "x"])
    def test_non_power_of_ten_increment(self, inc):
        assert ts_increment_to_sql_digits(inc) is None

    def test_zero_increment_raises(self):
        with pytest.raises(ValueError, match="NULL"):
            ts_increment_to_sql_digits("0")

    def test_round_trip(self):
        for d in range(-4, 8):
            assert ts_increment_to_sql_digits(sql_digits_to_ts_increment(str(d))) == d

    def test_non_literal_over_aggregate_is_refused_when_strict(self):
        with pytest.raises(UntranslatableError, match="BL-331"):
            ts_round_from_sql_digits("sum ( [T::a] )", "[T::p]")
        assert ts_round_from_sql_digits("sum ( [T::a] )", "[T::p]", strict=False) \
            .startswith("sql_double_op")


# --- Snowflake -> ThoughtSpot (sv_sql) --------------------------------------

class TestSnowflakeRound:
    @pytest.mark.parametrize("sql, ts", [
        ("ROUND(a, 0)", "round ( [T::a] , 1 )"),
        ("ROUND(a, 2)", "round ( [T::a] , 0.01 )"),
        ("ROUND(a, -2)", "round ( [T::a] , 100 )"),
        ("ROUND(a)", "round ( [T::a] )"),
        ("ROUND(SUM(a), 2)", "round ( sum ( [T::a] ) , 0.01 )"),
    ])
    def test_literal_digits(self, sql, ts):
        assert sf_to_ts(sql, _sf_res) == ts

    def test_non_literal_digits_pass_through(self):
        assert sf_to_ts("ROUND(a, p)", _sf_res) == \
            'sql_double_op ( "ROUND({0}, {1})" , [T::a] , [T::p] )'

    def test_non_literal_digits_over_aggregate_refused(self):
        with pytest.raises(UntranslatableError):
            sf_to_ts("ROUND(SUM(a), p)", _sf_res)

    def test_never_copies_digit_count(self):
        out = sf_to_ts("ROUND(a, 2)", _sf_res)
        assert out != "round ( [T::a] , 2 )"
        assert not _DIGIT_COPY.search(out)


class TestSnowflakeTrunc:
    @pytest.mark.parametrize("sql, ts", [
        ("TRUNC(a, 0)", 'sql_double_op ( "TRUNC({0}, 0)" , [T::a] )'),
        ("TRUNC(a, 2)", 'sql_double_op ( "TRUNC({0}, 2)" , [T::a] )'),
        ("TRUNC(a, -2)", 'sql_double_op ( "TRUNC({0}, -2)" , [T::a] )'),
        ("TRUNC(a)", 'sql_double_op ( "TRUNC({0}, 0)" , [T::a] )'),
        ("TRUNCATE(a, 2)", 'sql_double_op ( "TRUNC({0}, 2)" , [T::a] )'),
        ("TRUNC(a, p)", 'sql_double_op ( "TRUNC({0}, {1})" , [T::a] , [T::p] )'),
    ])
    def test_row_level_passes_through(self, sql, ts):
        assert sf_to_ts(sql, _sf_res) == ts

    def test_aggregate_uses_sign_split(self):
        assert sf_to_ts("TRUNC(SUM(a), 2)", _sf_res) == (
            "( if ( sum ( [T::a] ) >= 0 ) then floor ( sum ( [T::a] ) / 0.01 ) * 0.01 "
            "else ceil ( sum ( [T::a] ) / 0.01 ) * 0.01 )")
        assert sf_to_ts("TRUNC(SUM(a), 0)", _sf_res) == (
            "( if ( sum ( [T::a] ) >= 0 ) then floor ( sum ( [T::a] ) ) "
            "else ceil ( sum ( [T::a] ) ) )")

    def test_aggregate_non_literal_refused(self):
        with pytest.raises(UntranslatableError):
            sf_to_ts("TRUNC(SUM(a), p)", _sf_res)

    def test_date_trunc_form(self):
        assert sf_to_ts("TRUNC(d, 'MONTH')", _sf_res) == "start_of_month ( [T::d] )"

    def test_never_emits_round(self):
        for sql in ("TRUNC(a, 0)", "TRUNC(a, 2)", "TRUNC(SUM(a), 2)"):
            assert "round" not in sf_to_ts(sql, _sf_res)


# --- Databricks -> ThoughtSpot (mv_sql) -------------------------------------

class TestDatabricksRound:
    @pytest.mark.parametrize("sql, ts", [
        ("ROUND(a, 0)", "round ( [T::a] , 1 )"),
        ("ROUND(a, 2)", "round ( [T::a] , 0.01 )"),
        ("ROUND(a, -2)", "round ( [T::a] , 100 )"),
        ("ROUND(a)", "round ( [T::a] )"),
    ])
    def test_literal_digits(self, sql, ts):
        assert dbx_to_ts(sql, _dbx_res) == ts

    def test_non_literal_digits_pass_through(self):
        assert dbx_to_ts("ROUND(a, p)", _dbx_res) == \
            'sql_double_op ( "ROUND({0}, {1})" , [T::a] , [T::p] )'

    def test_non_literal_digits_over_aggregate_refused(self):
        with pytest.raises(UntranslatableError):
            dbx_to_ts("ROUND(SUM(a), p)", _dbx_res)

    def test_never_copies_digit_count(self):
        assert not _DIGIT_COPY.search(dbx_to_ts("ROUND(a, 2)", _dbx_res))


# --- Tableau -> ThoughtSpot ---------------------------------------------------

class TestTableauRound:
    @pytest.mark.parametrize("tab, ts", [
        ("ROUND([a], 0)", "round ( [a] , 1 )"),
        ("ROUND([a], 2)", "round ( [a] , 0.01 )"),
        ("ROUND([a], -2)", "round ( [a] , 100 )"),
        ("ROUND([a])", "round ( [a] )"),
        ("ROUND([a], [p])", 'sql_double_op ( "ROUND({0}, {1})" , [a] , [p] )'),
    ])
    def test_map_functions(self, tab, ts):
        assert map_functions(tab) == ts

    def test_nested(self):
        assert map_functions("ROUND(ROUND([a], 2) * 3, 1)") == \
            "round ( round ( [a] , 0.01 ) * 3 , 0.1 )"

    def test_full_pipeline_never_copies_digit_count(self):
        out, _errs, _notes = translate_single("ROUND(SUM([Sales]), 2)")
        assert "0.01" in out
        assert not _DIGIT_COPY.search(out)


# --- Power BI (moved onto the shared helper) ---------------------------------

class TestPowerBIRound:
    @pytest.mark.parametrize("dax, ts", [
        ("ROUND(T[x], 0)", "round([T::x], 1)"),
        ("ROUND(T[x], 2)", "round([T::x], 0.01)"),
        ("ROUND(T[x], -2)", "round([T::x], 100)"),
        ("ROUND(T[x], 12)", "round([T::x], 0.000000000001)"),
    ])
    def test_literal_digits(self, dax, ts):
        expr, status, _ = translate_dax(dax)
        assert (expr, status) == (ts, "Migrated")

    def test_non_literal_needs_review(self):
        expr, status, _ = translate_dax("ROUND(T[x], T[p])")
        assert expr is None and status == "NEEDS REVIEW"


# --- ThoughtSpot -> Databricks (mv_emit_sql) ---------------------------------

class TestEmitDatabricksRound:
    @pytest.mark.parametrize("ts, sql", [
        ("round ( [T::a] , 0.01 )", "ROUND(source.a, 2)"),
        ("round ( [T::a] , 1 )", "ROUND(source.a, 0)"),
        ("round ( [T::a] , 100 )", "ROUND(source.a, -2)"),
        ("round ( [T::a] , 0.5 )", "(0.5 * ROUND(source.a / 0.5))"),
        ("round ( [T::a] )", "ROUND(source.a)"),
        ("round ( [T::a] + [T::b] , 0.25 )", "(0.25 * ROUND((source.a + source.b) / 0.25))"),
        ("round ( [T::a] , [T::p] )", "(source.p * ROUND(source.a / NULLIF(source.p, 0)))"),
    ])
    def test_increment_to_sql(self, ts, sql):
        assert _emit(ts) == sql

    def test_zero_increment_refused(self):
        with pytest.raises(UntranslatableError, match="NULL"):
            _emit("round ( [T::a] , 0 )")

    def test_increment_never_copied_as_digits(self):
        assert _emit("round ( [T::a] , 0.01 )") != "ROUND(source.a, 0.01)"
