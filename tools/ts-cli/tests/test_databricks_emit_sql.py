import pytest
from ts_cli.databricks.mv_emit_expr import parse_formula
from ts_cli.databricks.mv_emit_sql import emit_sql
from ts_cli.databricks.mv_emit_expr import UntranslatableError


def _res(node):
    # test resolver: source.<col>, ignore table
    return f"source.{node['column']}"


def e(expr):
    return emit_sql(parse_formula(expr), _res)


class TestScalarEmit:
    def test_sum(self):
        assert e("sum ( [T::a] )") == "SUM(source.a)"

    def test_unique_count(self):
        assert e("unique count ( [T::id] )") == "COUNT(DISTINCT source.id)"

    def test_arithmetic(self):
        assert e("[T::a] + [T::b] * [T::c]") == "source.a + source.b * source.c"

    def test_safe_divide(self):
        assert e("safe_divide ( sum ( [T::a] ) , sum ( [T::b] ) )") == \
            "COALESCE(SUM(source.a) / NULLIF(SUM(source.b), 0), 0)"

    def test_ifelse_to_case(self):
        assert e("if ( [T::x] > 0 ) then [T::a] else 0") == \
            "CASE WHEN source.x > 0 THEN source.a ELSE 0 END"

    def test_null_comparison(self):
        assert e("[T::x] != null") == "source.x IS NOT NULL"
        assert e("[T::x] = null") == "source.x IS NULL"

    def test_string_literal_requote(self):
        assert e("[T::s] = 'Active'") == "source.s = 'Active'"

    def test_conditional_agg_filter(self):
        assert e("sum_if ( [T::x] > 0 , [T::a] )") == \
            "SUM(source.a) FILTER (WHERE source.x > 0)"

    def test_unmapped_fn_raises(self):
        with pytest.raises(UntranslatableError, match=r"no Databricks"):
            e("some_unknown_fn ( [T::a] )")

    # -- Step 5: remaining mapped scalars (exact strings from
    # agents/shared/mappings/ts-databricks/ts-databricks-formula-translation.md) --

    def test_concat(self):
        # concat(a, b) -> CONCAT(a, b)
        assert e("concat ( [T::a] , [T::b] )") == "CONCAT(source.a, source.b)"

    def test_if_null(self):
        # if_null(x, default) -> COALESCE(x, default)
        assert e("if_null ( [T::x] , 0 )") == "COALESCE(source.x, 0)"

    def test_zero_if_null(self):
        # zero_if_null(x) -> COALESCE(x, 0)
        assert e("zero_if_null ( [T::x] )") == "COALESCE(source.x, 0)"

    def test_null_if_zero(self):
        # null_if_zero(x) -> NULLIF(x, 0)
        assert e("null_if_zero ( [T::x] )") == "NULLIF(source.x, 0)"

    def test_sql_str_op_passthrough(self):
        # sql_str_op(expr) -> expr (unwrap, emit inner SQL directly)
        assert e("sql_str_op ( 'UPPER(source_col)' )") == "UPPER(source_col)"

    def test_count_star(self):
        # count(1) -> COUNT(*) (TS has no COUNT(*) syntax)
        assert e("count ( 1 )") == "COUNT(*)"

    def test_in(self):
        # in(x, a, b, c) -> x IN (a, b, c)
        #
        # NOTE: constructed as a raw AST dict rather than via e()/parse_formula.
        # mv_emit_expr.py (Task 3) reserves "in" as a keyword in _KW but has no
        # parse path that consumes it -- neither the function-call shorthand
        # in(x, a, b, c) used in the mapping table, nor TS's actual infix syntax
        # `[col] in ( 'a' , 'b' )` (agents/shared/schemas/thoughtspot-formula-patterns.md
        # line 134). Both currently raise UntranslatableError from parse_formula
        # before reaching emit_sql (verified: "unexpected token kw 'in'" / "trailing
        # tokens" respectively). This test isolates emit_sql's mapping logic, which
        # is correct; the parser-side gap is a Task 3 follow-up (see task-4-report.md).
        node = {"node": "call", "fn": "in", "args": [
            {"node": "col", "table": "T", "column": "x"},
            {"node": "lit", "kind": "number", "value": "1"},
            {"node": "lit", "kind": "number", "value": "2"},
            {"node": "lit", "kind": "number", "value": "3"},
        ]}
        assert emit_sql(node, _res) == "source.x IN (1, 2, 3)"

    def test_between(self):
        # between(x, lo, hi) -> x BETWEEN lo AND hi
        #
        # NOTE: same parser-front-end gap as test_in above -- "between" is reserved
        # in mv_emit_expr._KW but never wired into a parse path (neither the
        # function-call shorthand nor TS's real infix syntax
        # `[col] between [a] and [b]`, thoughtspot-formula-patterns.md line 135).
        # Constructed as a raw AST dict for the same reason; see test_in.
        node = {"node": "call", "fn": "between", "args": [
            {"node": "col", "table": "T", "column": "x"},
            {"node": "lit", "kind": "number", "value": "1"},
            {"node": "lit", "kind": "number", "value": "10"},
        ]}
        assert emit_sql(node, _res) == "source.x BETWEEN 1 AND 10"
