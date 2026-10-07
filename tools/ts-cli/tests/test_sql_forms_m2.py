"""Formula fidelity M2 fixes (BL-357..362) in both SQL translators, and the shared forms.

Every expected string here is the form the live M2 / M0 re-runs scored (see
docs/reviews/2026-10-07-fidelity-m2-databricks.md, "After fixes"); the reasons are in
ts_cli/sql_forms.py.
"""
from __future__ import annotations

import pytest

from ts_cli.databricks.mv_sql import translate_sql_expr as dbx
from ts_cli.formula_common import UntranslatableError
from ts_cli.formula_translate.engine import translate
from ts_cli.sql_forms import sqlf_group, sqlf_is_atomic, sqlf_scaled_floor_ceil
from ts_cli.sv_sql import translate_sql_expr as sf


def r(c: str) -> str:
    return f"[T::{c}]"


BOTH = pytest.mark.parametrize("t", [dbx, sf], ids=["databricks", "snowflake"])


class TestDivision:
    """BL-357: zero only when the source asks for zero."""

    @BOTH
    def test_nullif_divisor_is_plain_division(self, t):
        assert t("N1 / NULLIF(N2, 0)", r) == "[T::N1] / [T::N2]"
        assert t("SUM(N1) / NULLIF(MIN(N2), 0)", r) == "sum ( [T::N1] ) / min ( [T::N2] )"

    @BOTH
    def test_compound_divisor_is_grouped(self, t):
        assert t("a + b / NULLIF(c + d, 0)", r) == "[T::a] + [T::b] / ( [T::c] + [T::d] )"

    @BOTH
    @pytest.mark.parametrize("src", ["COALESCE(N1 / NULLIF(N2, 0), 0)",
                                     "IFNULL(N1 / NULLIF(N2, 0), 0)",
                                     "NVL(N1 / NULLIF(N2, 0), 0)",
                                     "ZEROIFNULL(N1 / NULLIF(N2, 0))"])
    def test_zero_default_is_ifnull_safe_divide(self, t, src):
        assert t(src, r) == "ifnull ( safe_divide ( [T::N1] , [T::N2] ) , 0 )"

    @BOTH
    def test_product_numerator(self, t):
        assert t("COALESCE(a * b / NULLIF(c, 0), 0)", r) == \
            "ifnull ( safe_divide ( [T::a] * [T::b] , [T::c] ) , 0 )"

    @BOTH
    def test_other_default_is_ifnull_division(self, t):
        assert t("COALESCE(N1 / NULLIF(N2, 0), -1)", r) == "ifnull ( [T::N1] / [T::N2] , - 1 )"

    @BOTH
    def test_sum_then_divide_is_not_the_division_form(self, t):
        # the first argument is a sum, not one division: the generic chain
        assert t("COALESCE(a + b / NULLIF(c, 0), 0)", r) == (
            "if ( [T::a] + [T::b] / [T::c] != null ) then [T::a] + [T::b] / [T::c] else 0")

    def test_snowflake_div0_guards_a_null_dividend(self):
        assert sf("DIV0(N1, N2)", r) == \
            "( if ( isnull ( [T::N1] ) ) then null else safe_divide ( [T::N1] , [T::N2] ) )"
        assert sf("DIV0NULL(N1, N2)", r) == ("( if ( isnull ( [T::N1] ) ) then null else "
                                             "safe_divide ( [T::N1] , ifnull ( [T::N2] , 0 ) ) )")

    def test_databricks_try_divide_and_nullifzero(self):
        assert dbx("try_divide(N1, N2)", r) == "( [T::N1] / [T::N2] )"
        assert dbx("2 / try_divide(N1, N2)", r) == "2 / ( [T::N1] / [T::N2] )"
        assert dbx("N1 / nullifzero(N2)", r) == "[T::N1] / [T::N2]"
        assert dbx("nullifzero(I1)", r) == "( if ( [T::I1] = 0 ) then null else [T::I1] )"

    @BOTH
    def test_zeroifnull_is_ifnull(self, t):
        assert t("ZEROIFNULL(N1)", r) == "ifnull ( [T::N1] , 0 )"


class TestCasts:
    """BL-359."""

    @pytest.mark.parametrize("ty", ["BIGINT", "LONG"])
    def test_databricks_bigint_is_64_bit(self, ty):
        assert dbx(f"CAST(N1 * 1000000 AS {ty})", r) == \
            'sql_int_op ( "CAST({0} AS BIGINT)" , ( [T::N1] * 1000000 ) )'

    def test_databricks_bigint_over_an_aggregate_truncates_natively(self):
        assert dbx("CAST(SUM(N1) AS BIGINT)", r) == ("( if ( sum ( [T::N1] ) >= 0 ) then floor "
                                                     "( sum ( [T::N1] ) ) else ceil ( sum ( [T::N1] ) ) )")

    def test_databricks_int_stays_to_integer(self):
        assert dbx("CAST(N1 AS INT)", r) == "to_integer ( [T::N1] )"

    def test_databricks_decimal_rounds(self):
        assert dbx("CAST(N1 AS DECIMAL)", r) == 'sql_int_op ( "CAST({0} AS DECIMAL(10,0))" , [T::N1] )'
        assert dbx("CAST(N1 AS DECIMAL(10,2))", r) == \
            'sql_double_op ( "CAST({0} AS DECIMAL(10,2))" , [T::N1] )'
        assert dbx("CAST(SUM(N1) AS DECIMAL(18,2))", r) == "round ( sum ( [T::N1] ) , 0.01 )"
        with pytest.raises(UntranslatableError, match="rounds"):
            dbx("CAST(SUM(N1) AS DECIMAL(18,0))", r)

    @pytest.mark.parametrize("ty", ["NUMBER", "NUMBER(38,0)", "NUMBER(10)", "DECIMAL", "BIGINT"])
    def test_snowflake_integral_number(self, ty):
        assert sf(f"CAST(N1 AS {ty})", r) == "to_integer ( [T::N1] )"

    def test_snowflake_scaled_number(self):
        assert sf("CAST(N1 AS NUMBER(10,2))", r) == \
            'sql_double_op ( "CAST({0} AS NUMBER(10,2))" , [T::N1] )'


class TestIntegerDivisionAndOperators:
    """BL-360, BL-362."""

    def test_databricks_div_truncates_toward_zero(self):
        q = "[T::I1] / 2"
        assert dbx("I1 DIV 2", r) == f"( if ( {q} >= 0 ) then floor ( {q} ) else ceil ( {q} ) )"

    def test_databricks_div_precedence(self):
        out = dbx("a * b DIV c + 1", r)
        assert out.startswith("( if ( ( [T::a] * [T::b] ) / [T::c] >= 0 )") and out.endswith(" + 1")

    def test_snowflake_has_no_div(self):
        with pytest.raises(UntranslatableError, match="no DIV operator"):
            sf("I1 DIV 2", r)

    @BOTH
    def test_unknown_operator_is_never_a_column(self, t):
        with pytest.raises(UntranslatableError, match="no operator between"):
            t("a SIMILAR b", r)

    @BOTH
    def test_modulo(self, t):
        assert t("I1 % 3", r) == "mod ( [T::I1] , 3 )"
        assert t("a * b % c + 1", r) == "mod ( ( [T::a] * [T::b] ) , [T::c] ) + 1"
        assert t("x - a % b", r) == "[T::x] - mod ( [T::a] , [T::b] )"

    @BOTH
    def test_modulo_left_operand_guard(self, t):
        with pytest.raises(UntranslatableError, match="compound left operand"):
            t("a % b IS NULL", r)

    @BOTH
    def test_concat_operator(self, t):
        assert t("S1 || '-' || S2", r) == "concat ( [T::S1] , '-' , [T::S2] )"
        assert t("S1 || S2 = 'ab'", r) == "concat ( [T::S1] , [T::S2] ) = 'ab'"
        with pytest.raises(UntranslatableError, match="mixed"):
            t("S1 || S2 + 1", r)

    @BOTH
    @pytest.mark.parametrize("op", ["LIKE", "ILIKE", "RLIKE"])
    def test_like_family(self, t, op):
        assert t(f"S1 {op} 'a%'", r) == f'sql_bool_op ( "{{0}} {op} \'a%\'" , [T::S1] )'
        assert t(f"S1 NOT {op} 'a%'", r) == f'sql_bool_op ( "{{0}} NOT {op} \'a%\'" , [T::S1] )'

    @BOTH
    def test_like_refusals(self, t):
        for src in ("S1 LIKE S2", "S1 LIKE 'a\"b'", "S1 LIKE 'a!%' ESCAPE '!'"):
            with pytest.raises(UntranslatableError):
                t(src, r)


class TestScaledFloorCeil:
    """BL-361: Databricks snaps (DECIMAL semantics), Snowflake does not (double semantics)."""

    def test_databricks(self):
        assert dbx("FLOOR(N1, -1)", r) == "( floor ( round ( [T::N1] / 10 , 0.000000001 ) ) * 10 )"
        assert dbx("CEIL(N1, 2)", r) == "( ceil ( round ( [T::N1] * 100 , 0.000000001 ) ) * 0.01 )"
        assert dbx("CEILING(N1)", r) == "ceil ( [T::N1] )"
        assert dbx("FLOOR(N1, 0)", r) == "floor ( [T::N1] )"

    def test_snowflake(self):
        assert sf("FLOOR(N1, -1)", r) == "( floor ( [T::N1] / 10 ) * 10 )"
        assert sf("CEIL(N1, 2)", r) == "( ceil ( [T::N1] * 100 ) * 0.01 )"
        assert sf("CEILING(N1, 1)", r) == "( ceil ( [T::N1] * 10 ) * 0.1 )"

    @BOTH
    def test_refusals(self, t):
        with pytest.raises(UntranslatableError, match="non-literal scale"):
            t("FLOOR(N1, N2)", r)
        with pytest.raises(UntranslatableError, match="15 digits"):
            t("FLOOR(N1, 16)", r)

    def test_compound_operand_grouped(self):
        assert sqlf_scaled_floor_ceil("floor", "[T::a] + 1", "1", snap=False) == \
            "( floor ( ( [T::a] + 1 ) * 10 ) * 0.1 )"


class TestDatabricksCoverage:
    """BL-362 forms implemented."""

    @pytest.mark.parametrize("src,out", [
        ("NVL(N1, -1)", "ifnull ( [T::N1] , - 1 )"),
        ("NVL2(N1, 1, 0)", "( if ( [T::N1] != null ) then 1 else 0 )"),
        ("COALESCE(N1, N2, 0)", "if ( [T::N1] != null ) then [T::N1] else "
                                "if ( [T::N2] != null ) then [T::N2] else 0"),
        ("zeroifnull(N1)", "ifnull ( [T::N1] , 0 )"),
        ("concat_ws('-', S1, S2)", 'sql_string_op ( "concat_ws(\'-\', {0}, {1})" , [T::S1] , [T::S2] )'),
        ("INSTR(S1, 'a')", 'sql_int_op ( "instr({0}, \'a\')" , [T::S1] )'),
        ("BROUND(N2, 0)", 'sql_double_op ( "bround({0}, 0)" , [T::N2] )'),
        ("trunc(D1, 'MM')", "start_of_month ( [T::D1] )"),
        ("trunc(D1, 'YEAR')", "start_of_year ( [T::D1] )"),
        ("trunc(D1, 'QUARTER')", "start_of_quarter ( [T::D1] )"),
        ("trunc(D1, 'WEEK')", 'sql_date_op ( "trunc({0}, \'WEEK\')" , [T::D1] )'),
        ("last_day(D1)", "add_days ( add_months ( start_of_month ( [T::D1] ) , 1 ) , -1 )"),
        ("to_date(Z1)", 'sql_date_op ( "to_date({0})" , [T::Z1] )'),
        ("to_date('2024-01-01')", "to_date ( '2024-01-01' )"),
    ])
    def test_form(self, src, out):
        assert dbx(src, r) == out

    @pytest.mark.parametrize("src", ["INSTR(SUM(S1), 'a')", "BROUND(SUM(N2), 0)",
                                     "trunc(D1, fmt)", "trunc(D1, 'DD')"])
    def test_refused(self, src):
        with pytest.raises(UntranslatableError):
            dbx(src, r)


class TestGrouping:
    @pytest.mark.parametrize("expr,atomic", [
        ("[T::a]", True), ("[T::Order Date]", True), ("5", True), ("'a b'", True),
        ("sum ( [T::a] )", True), ("unique count ( [T::a] )", True), ("( a + b )", True),
        ("a + b", False), ("- 1", False), ("( a ) + ( b )", False),
        ("sum ( a ) / sum ( b )", False), ("if ( c ) then a else b", False),
    ])
    def test_atomic(self, expr, atomic):
        assert sqlf_is_atomic(expr) is atomic
        assert sqlf_group(expr) == (expr if atomic else f"( {expr} )")


class TestNonAnsiTraps:
    """BL-358: documentation, plus a downgrade where the answer can be a wrong number."""

    def test_overflow_literal_downgrades(self):
        res = translate("I1 + 9223372036854775800", "databricks")
        assert res["status"] == "APPROXIMATED"
        assert any(t.startswith("integer overflow wraps") for t in res["traps"])

    def test_cast_is_noted_not_downgraded(self):
        res = translate("CAST(S2 AS INT)", "databricks")
        assert res["status"] == "TRANSLATED"
        assert any("non-ANSI" in t and "CAST" in t for t in res["traps"])

    def test_snowflake_and_plain_arithmetic_untouched(self):
        assert not any("BL-358" in t for t in translate("I1 + 9223372036854775800",
                                                          "snowflake")["traps"])
        assert translate("N1 + N2", "databricks")["traps"] == []

    def test_passthrough_trap_names_the_dialect(self):
        res = translate("INSTR(S1, 'a')", "databricks")
        assert any("Databricks syntax assumed" in t for t in res["traps"])
