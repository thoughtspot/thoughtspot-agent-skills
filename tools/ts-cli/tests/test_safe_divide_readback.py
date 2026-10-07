"""BL-374 — the compiled ``safe_divide`` form reads back as ``safe_divide``.

Since BL-366 both to-direction converters emit ``safe_divide ( a , b )`` as
``CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) END``. These tests pin the from-direction
recognition of that shape in both SQL translators (Snowflake ``sv_sql``, Databricks
``mv_sql``), through both CLI paths (the converters' ``translate-formulas`` and
``ts formula translate``), and the NULL / zero grid that makes the recognition exact.
"""
from __future__ import annotations

import sqlite3

import pytest

from ts_cli.databricks.mv_emit_expr import parse_formula
from ts_cli.databricks.mv_emit_sql import emit_sql
from ts_cli.databricks.mv_sql import translate_sql_expr as dbx
from ts_cli.databricks.mv_translate import translate_measure
from ts_cli.formula_translate.engine import translate
from ts_cli.sql_forms import sqlf_safe_divide_form
from ts_cli.sv_sql import translate_sql_expr as sf
from ts_cli.sv_translate import translate_sv_formulas


def r(c: str) -> str:
    return f"[T::{c.split('.')[-1]}]"


BOTH = pytest.mark.parametrize("t", [dbx, sf], ids=["databricks", "snowflake"])
SD = "safe_divide ( [T::a] , [T::b] )"


class TestRecognised:
    @BOTH
    @pytest.mark.parametrize("src", [
        "CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) END",
        "case   when b=0 then 0 else a/nullif(b,0) end",
        "CASE WHEN (b) = 0 THEN 0 ELSE (a) / NULLIF((b), 0) END",
        "CASE WHEN (b = 0) THEN (0) ELSE (a / NULLIF(b, 0)) END",
        "CASE WHEN t.b = 0 THEN 0 ELSE t.a / NULLIF(b, 0) END",  # same column, other spelling
        # the ELSE written without NULLIF: unreachable at b = 0, so the same value
        "CASE WHEN b = 0 THEN 0 ELSE a / b END",
        "IF(b = 0, 0, a / NULLIF(b, 0))",
        "IFF(b = 0, 0, a / NULLIF(b, 0))",
    ])
    def test_simple(self, t, src):
        assert t(src, r) == SD

    @BOTH
    @pytest.mark.parametrize("src,want", [
        ("CASE WHEN (b - c) = 0 THEN 0 ELSE a / NULLIF((b - c), 0) END",
         "safe_divide ( [T::a] , [T::b] - [T::c] )"),
        ("CASE WHEN b - c = 0 THEN 0 ELSE a / NULLIF(b - c, 0) END",
         "safe_divide ( [T::a] , [T::b] - [T::c] )"),
        ("CASE WHEN (N2 * 0) = 0 THEN 0 ELSE N1 / NULLIF((N2 * 0), 0) END",
         "safe_divide ( [T::N1] , [T::N2] * 0 )"),
        ("CASE WHEN SUM(b) = 0 THEN 0 ELSE SUM(a) / NULLIF(SUM(b), 0) END",
         "safe_divide ( sum ( [T::a] ) , sum ( [T::b] ) )"),
        ("CASE WHEN b = 0 THEN 0 ELSE (a + c) / NULLIF(b, 0) END",
         "safe_divide ( [T::a] + [T::c] , [T::b] )"),
        ("CASE WHEN b = 0 THEN 0 ELSE a * c / NULLIF(b, 0) END",
         "safe_divide ( [T::a] * [T::c] , [T::b] )"),
        ("CASE WHEN b = 0 THEN 0 ELSE -a / NULLIF(b, 0) END",
         "safe_divide ( - [T::a] , [T::b] )"),
        ("(CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) END) * 2",
         f"( {SD} ) * 2"),
    ])
    def test_compound(self, t, src, want):
        assert t(src, r) == want


class TestNotRecognised:
    """Near misses keep today's literal translation."""

    @BOTH
    @pytest.mark.parametrize("src", [
        "CASE WHEN b = 0 THEN NULL ELSE a / NULLIF(b, 0) END",   # NULL arm: plain a / b
        "CASE WHEN b = 0 THEN 1 ELSE a / NULLIF(b, 0) END",
        "CASE WHEN c = 0 THEN 0 ELSE a / NULLIF(b, 0) END",      # different b
        "CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(c, 0) END",
        "CASE WHEN (b - c) = 0 THEN 0 ELSE a / NULLIF((c - b), 0) END",
        "CASE WHEN b <> 0 THEN a / NULLIF(b, 0) ELSE 0 END",    # NULL b takes the 0 arm
        "CASE WHEN b != 0 THEN a / b ELSE 0 END",
        "CASE WHEN 0 = b THEN 0 ELSE a / NULLIF(b, 0) END",
        "CASE WHEN b = 0 THEN 0 WHEN a = 1 THEN 1 ELSE a / NULLIF(b, 0) END",
        "CASE WHEN b = 0 AND c = 1 THEN 0 ELSE a / NULLIF(b, 0) END",
        "CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) + 1 END",
        "CASE WHEN b = 0 THEN 0 ELSE c + a / NULLIF(b, 0) END",
        "CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) / c END",
        "CASE WHEN b = 0 THEN 0 ELSE a * b END",
        "CASE WHEN b = 0 THEN 0 END",
        "IF(b = 0, NULL, a / NULLIF(b, 0))",
    ])
    def test_near_miss(self, t, src):
        assert "safe_divide" not in t(src, r)

    def test_near_miss_is_the_literal_translation(self):
        assert sf("CASE WHEN b <> 0 THEN a / NULLIF(b, 0) ELSE 0 END", r) == \
            "if ( [T::b] != 0 ) then [T::a] / [T::b] else 0"
        assert dbx("CASE WHEN c = 0 THEN 0 ELSE a / NULLIF(b, 0) END", r) == \
            "if ( [T::c] = 0 ) then 0 else [T::a] / [T::b]"

    @BOTH
    def test_reference_case_is_significant(self, t):
        # the resolver decides what an identifier names; differently-cased references are
        # not assumed equal (Snowflake quoted "b" and "B" are distinct columns)
        assert "safe_divide" not in t("CASE WHEN B = 0 THEN 0 ELSE a / NULLIF(b, 0) END", r)

    @pytest.mark.parametrize("dialect", ["snowflake", "databricks"])
    def test_reference_case_is_significant_with_the_real_resolver(self, dialect):
        res = translate("CASE WHEN n2 = 0 THEN 0 ELSE N1 / NULLIF(N2, 0) END", dialect)
        assert res["formula"] == "if ( [TABLE::n2] = 0 ) then 0 else [TABLE::N1] / [TABLE::N2]"

    def test_helper_ignores_brackets_and_strings(self):
        # an operator or parenthesis inside a [ref] or a string is not structure
        assert sqlf_safe_divide_form("[T::x / y] = 0", "0", "[T::a] / [T::x / y]") == \
            "safe_divide ( [T::a] , [T::x / y] )"
        assert sqlf_safe_divide_form("[T::b] = 0", "0", "strlen ( 'a ) /' ) / [T::b]") == \
            "safe_divide ( strlen ( 'a ) /' ) , [T::b] )"
        assert sqlf_safe_divide_form("[T::b] = 0", "0", "'x' / [T::c]") is None


class TestGrid:
    """The NULL / zero grid. ``safe_divide`` semantics are stated from the live probe
    (BL-366), not derived from either SQL shape."""

    @staticmethod
    def _safe_divide(a, b):
        if b == 0:
            return 0
        if a is None or b is None:
            return None
        return a / b

    @pytest.mark.parametrize("sql", [
        "CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) END",
        "CASE WHEN b = 0 THEN 0 ELSE a / b END",
    ])
    @pytest.mark.parametrize("a", [None, 0.0, 2.0])
    @pytest.mark.parametrize("b", [None, 0.0, 4.0])
    def test_both_shapes_equal_safe_divide(self, sql, a, b):
        row = sqlite3.connect(":memory:").execute(
            f"SELECT {sql} FROM (SELECT ? AS a, ? AS b)", (a, b)).fetchone()
        assert row[0] == self._safe_divide(a, b)

    @pytest.mark.parametrize("a", [None, 0.0, 2.0])
    @pytest.mark.parametrize("b", [None, 0.0, 4.0])
    def test_reversed_form_differs_on_a_null_divisor(self, a, b):
        # why `CASE WHEN b <> 0 THEN a / b ELSE 0 END` is not recognised
        row = sqlite3.connect(":memory:").execute(
            "SELECT CASE WHEN b <> 0 THEN a / b ELSE 0 END FROM (SELECT ? AS a, ? AS b)",
            (a, b)).fetchone()
        assert (row[0] == self._safe_divide(a, b)) == (b is not None)


class TestCliPaths:
    @pytest.mark.parametrize("dialect", ["snowflake", "databricks"])
    @pytest.mark.parametrize("src,want", [
        ("CASE WHEN N2 = 0 THEN 0 ELSE N1 / NULLIF(N2, 0) END",
         "safe_divide ( [TABLE::N1] , [TABLE::N2] )"),
        ("CASE WHEN (N2 * 0) = 0 THEN 0 ELSE N1 / NULLIF((N2 * 0), 0) END",
         "safe_divide ( [TABLE::N1] , [TABLE::N2] * 0 )"),
    ])
    def test_formula_translate(self, dialect, src, want):
        res = translate(src, dialect)
        assert res["status"] == "TRANSLATED"
        assert res["formula"] == want

    def test_snowflake_translate_formulas(self):
        metric = {"source_table": "ORDERS", "source_column": "MARGIN", "alias_table": "orders",
                  "alias_name": "MARGIN", "block": "metrics", "comment": None,
                  "synonyms": None, "sample_values": None, "is_enum": False,
                  "is_filter": False, "is_private": False, "cortex_search_service": None,
                  "expr": "CASE WHEN SUM(orders.COST) = 0 THEN 0 "
                          "ELSE SUM(orders.AMOUNT) / NULLIF(SUM(orders.COST), 0) END"}
        parsed = {
            "view_name": "T.P.ORD", "database": "T", "schema": "P", "name": "ORD",
            "comment": None, "relationships": [], "dimensions": [], "facts": [],
            "tables": [{"fqn": "T.P.ORDERS", "name": "ORDERS", "alias": "orders",
                        "primary_key": ["ID"], "comment": None, "synonyms": None,
                        "sample_values": None, "is_enum": False, "subquery": None,
                        "range_constraints": None}],
            "metrics": [metric], "custom_instructions": None, "verified_queries": [],
            "extension": None, "warnings": [], "unsupported": [],
        }
        out = translate_sv_formulas(parsed)["translated"][0]
        assert out["ts_expr"] == \
            "safe_divide ( sum ( [ORDERS::AMOUNT] ) , sum ( [ORDERS::COST] ) )"

    def test_databricks_translate_formulas(self):
        m = {"name": "margin", "kind": "complex", "expr_kind": "complex",
             "expr": "CASE WHEN SUM(cost) = 0 THEN 0 ELSE SUM(amount) / NULLIF(SUM(cost), 0) END",
             "agg_function": None, "physical_ref": None, "distinct": False, "cross_refs": [],
             "lod_refs": [], "display_name": None, "comment": None, "synonyms": [],
             "format": None, "window": None}
        out = translate_measure(m, {"source": "TRANSACTIONS"})
        assert out["ts_expr"] == \
            "safe_divide ( sum ( [TRANSACTIONS::amount] ) , sum ( [TRANSACTIONS::cost] ) )"


class TestRoundTrip:
    """TS → Databricks SQL (the BL-366 emitter) → TS keeps the idiom."""

    @pytest.mark.parametrize("formula", [
        "safe_divide ( [T::a] , [T::b] )",
        "safe_divide ( [T::a] , [T::b] - [T::c] )",
        "safe_divide ( sum ( [T::a] ) , sum ( [T::b] ) )",
        "safe_divide ( [T::a] + [T::c] , [T::b] * [T::c] )",
    ])
    def test_databricks(self, formula):
        sql = emit_sql(parse_formula(formula), lambda n: n["column"])
        assert dbx(sql, r) == formula
