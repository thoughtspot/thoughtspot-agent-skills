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

    def test_median(self):
        assert e("median ( [T::a] )") == "MEDIAN(source.a)"

    def test_arithmetic(self):
        assert e("[T::a] + [T::b] * [T::c]") == "source.a + source.b * source.c"

    def test_safe_divide(self):
        assert e("safe_divide ( sum ( [T::a] ) , sum ( [T::b] ) )") == \
            "CASE WHEN SUM(source.b) = 0 THEN 0 ELSE SUM(source.a) / NULLIF(SUM(source.b), 0) END"

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

    def test_strlen(self):
        # FIX 4: strlen(s) -> LENGTH(s)
        assert e("strlen ( [T::s] )") == "LENGTH(source.s)"

    def test_raw_literal_passthrough(self):
        # Task 6: {"node":"lit","kind":"raw","value": X} emits X verbatim.
        # Used by mv_emit.resolve_refs, which substitutes a resolved `ref`
        # node with a raw-SQL literal so emit_sql never meets a bare ref.
        # Constructed as a raw AST dict -- parse_formula never produces
        # kind == "raw" (it's a post-parse substitution), same pattern as
        # test_in/test_between above.
        node = {"node": "call", "fn": "sum", "args": [
            {"node": "lit", "kind": "raw", "value": "MEASURE(net_amount)"},
        ]}
        assert emit_sql(node, _res) == "SUM(MEASURE(net_amount))"


class TestPrecedenceParens:
    # FIX 1: precedence-aware parenthesization -- a child expression must be
    # wrapped in parens exactly when its precedence would otherwise be lost.
    def test_paren_group_times_col(self):
        assert e("( [T::a] + [T::b] ) * [T::c]") == "(source.a + source.b) * source.c"

    def test_unary_minus_over_binop(self):
        assert e("- ( [T::a] + [T::b] )") == "-(source.a + source.b)"

    def test_unary_minus_single_unchanged(self):
        # confirm single negation still emits `-source.x` with no separator
        assert e("-[T::x]") == "-source.x"

    def test_double_negation_no_line_comment_parens(self):
        # FINAL REVIEW FIX 1: nested unary minus must never concatenate to
        # `--`, which Databricks SQL reads as a line comment.
        result = e("-(-[T::x])")
        assert "--" not in result
        assert result == "- -source.x"

    def test_double_negation_no_line_comment_spaced(self):
        result = e("- -[T::x]")
        assert "--" not in result
        assert result == "- -source.x"

    def test_safe_divide_numerator_binop(self):
        assert e("safe_divide ( [T::a] + [T::b] , [T::c] )") == \
            "CASE WHEN source.c = 0 THEN 0 ELSE (source.a + source.b) / NULLIF(source.c, 0) END"

    def test_or_group_and_cmp(self):
        assert e("( [T::x] = 1 or [T::y] = 2 ) and [T::z] = 3") == \
            "(source.x = 1 OR source.y = 2) AND source.z = 3"

    def test_arithmetic_unchanged(self):
        # re-confirm existing precedence-correct output is unaffected
        assert e("[T::a] + [T::b] * [T::c]") == "source.a + source.b * source.c"

    def test_safe_divide_unchanged(self):
        # re-confirm existing safe_divide output (non-binop numerator) is unaffected
        assert e("safe_divide ( sum ( [T::a] ) , sum ( [T::b] ) )") == \
            "CASE WHEN SUM(source.b) = 0 THEN 0 ELSE SUM(source.a) / NULLIF(SUM(source.b), 0) END"


class TestSafeDivideExact:
    """BL-366: ``safe_divide`` compiles to ``CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) END``
    (probe record §7). The emitted SQL must be that form, with a compound divisor bracketed
    identically in both of its occurrences."""

    def test_compound_divisor_bracketed_in_both_places(self):
        assert e("safe_divide ( [T::a] , [T::b] - [T::c] )") == (
            "CASE WHEN (source.b - source.c) = 0 THEN 0 "
            "ELSE source.a / NULLIF((source.b - source.c), 0) END")

    def test_compound_both_sides(self):
        assert e("safe_divide ( [T::a] * [T::d] , [T::b] + [T::c] )") == (
            "CASE WHEN (source.b + source.c) = 0 THEN 0 "
            "ELSE (source.a * source.d) / NULLIF((source.b + source.c), 0) END")

    def test_call_divisor_not_bracketed(self):
        assert e("safe_divide ( [T::a] , abs ( [T::b] ) )") == (
            "CASE WHEN ABS(source.b) = 0 THEN 0 ELSE source.a / NULLIF(ABS(source.b), 0) END")

    @staticmethod
    def _safe_divide_semantics(a, b):
        # ThoughtSpot safe_divide, stated from the live probe — not from the emitted SQL
        if b == 0:
            return 0
        if a is None or b is None:
            return None
        return a / b

    @pytest.mark.parametrize("a", [None, 0.0, 2.0])
    @pytest.mark.parametrize("b", [None, 0.0, 4.0])
    def test_null_zero_grid_matches_safe_divide(self, a, b):
        # Evaluate the emitted SQL (SQLite reads CASE / NULLIF / = the same way) on
        # every NULL / zero combination; the former COALESCE form was 0 on (NULL, 4)
        # and (2, NULL), where safe_divide is NULL.
        import sqlite3
        sql = e("safe_divide ( [T::a] , [T::b] )").replace("source.", "")
        row = sqlite3.connect(":memory:").execute(f"SELECT {sql} FROM (SELECT ? AS a, ? AS b)",
                                                  (a, b)).fetchone()
        assert row[0] == self._safe_divide_semantics(a, b)


class TestPassthroughArity:
    # FIX 2: a sql_*_op pass-through call with anything other than exactly
    # one argument must raise, never emit the un-substituted `{0}` template.
    def test_two_arg_passthrough_raises(self):
        with pytest.raises(UntranslatableError, match=r"exactly one argument"):
            e("sql_str_op ( 'LOWER({0})' , [T::s] )")


class TestInBetweenParse:
    # FIX 3 (cross-task): mv_emit_expr now parses TS's real infix `in`/`between`
    # syntax, so these go end-to-end through parse_formula -> emit_sql.
    def test_in_infix(self):
        assert e("[T::s] in ( 'A' , 'B' )") == "source.s IN ('A', 'B')"

    def test_between_infix(self):
        assert e("[T::x] between 1 and 10") == "source.x BETWEEN 1 AND 10"
