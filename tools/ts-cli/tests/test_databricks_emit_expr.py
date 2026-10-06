from ts_cli.databricks.mv_emit_expr import tokenize_formula, UntranslatableError, parse_formula
import pytest


class TestModuleContract:
    def test_untranslatable_error_is_exception(self):
        assert issubclass(UntranslatableError, Exception)


class TestTokenize:
    def test_bracket_column_ref(self):
        assert tokenize_formula("[FACT::AMOUNT]") == [("bracket", "[FACT::AMOUNT]")]

    def test_agg_call(self):
        assert tokenize_formula("sum ( [T::a] )") == [
            ("ident", "sum"), ("op", "("), ("bracket", "[T::a]"), ("op", ")")]

    def test_string_and_number_and_ops(self):
        assert tokenize_formula("[T::x] = 'Active'") == [
            ("bracket", "[T::x]"), ("op", "="), ("string", "'Active'")]
        assert tokenize_formula("[T::x] >= 10") == [
            ("bracket", "[T::x]"), ("op", ">="), ("number", "10")]

    def test_keywords_and_lodset(self):
        assert tokenize_formula("if ( [T::x] != null ) then 1 else 0") == [
            ("kw", "if"), ("op", "("), ("bracket", "[T::x]"), ("op", "!="),
            ("kw", "null"), ("op", ")"), ("kw", "then"), ("number", "1"),
            ("kw", "else"), ("number", "0")]
        assert tokenize_formula("{ [A::x] , [B::y] }") == [
            ("op", "{"), ("bracket", "[A::x]"), ("op", ","), ("bracket", "[B::y]"), ("op", "}")]

    def test_unrecognized_char_raises(self):
        with pytest.raises(UntranslatableError, match=r"unrecognized"):
            tokenize_formula("[T::x] @ 1")

    def test_multiword_function_ident(self):
        assert tokenize_formula("unique count ( [T::a] )") == [
            ("ident", "unique count"), ("op", "("), ("bracket", "[T::a]"), ("op", ")")]


class TestParse:
    def test_column(self):
        assert parse_formula("[FACT::AMOUNT]") == {"node": "col", "table": "FACT", "column": "AMOUNT"}

    def test_bare_ref(self):
        assert parse_formula("[Category Quantity]") == {"node": "ref", "name": "Category Quantity"}

    def test_agg_call(self):
        assert parse_formula("sum ( [T::a] )") == {
            "node": "call", "fn": "sum",
            "args": [{"node": "col", "table": "T", "column": "a"}]}

    def test_binop_precedence(self):
        # a + b * c  ->  a + (b * c)
        ast = parse_formula("[T::a] + [T::b] * [T::c]")
        assert ast["node"] == "binop" and ast["op"] == "+"
        assert ast["right"]["node"] == "binop" and ast["right"]["op"] == "*"

    def test_ifelse(self):
        ast = parse_formula("if ( [T::x] > 0 ) then [T::a] else 0")
        assert ast["node"] == "ifelse"
        assert ast["branches"][0][0]["op"] == ">"
        assert ast["else"] == {"node": "lit", "kind": "number", "value": "0"}

    def test_lodset(self):
        ast = parse_formula("group_aggregate ( sum ( [T::q] ) , { [C::name] } , query_filters ( ) )")
        assert ast["fn"] == "group_aggregate"
        assert ast["args"][1] == {"node": "lodset",
                                  "cols": [{"node": "col", "table": "C", "column": "name"}]}


class TestKeywordBeforeCall:
    """A keyword directly before a call (`else if (`, `or contains (`, `then sum (`) was read
    as one two-word function name, so `else if` chains and `a or f ( x )` failed to parse
    (found by the Excel translator's round trips, BL-339 PR). Only `unique count` is a
    two-word function."""

    def test_else_if_chain(self):
        node = parse_formula("if ( [T::a] < 1 ) then 'x' else if ( [T::a] < 2 ) then 'y' else 'z'")
        assert node["node"] == "ifelse" and node["else"]["node"] == "ifelse"

    def test_or_before_call(self):
        node = parse_formula("contains ( [T::a] , 'x' ) or contains ( [T::a] , 'y' )")
        assert node["op"] == "or" and node["right"]["fn"] == "contains"

    def test_then_before_aggregate(self):
        node = parse_formula("if ( [T::a] > 0 ) then sum ( [T::b] ) else 0")
        assert node["branches"][0][1]["fn"] == "sum"

    def test_unique_count_stays_one_function(self):
        assert parse_formula("unique count ( [T::a] )")["fn"] == "unique count"

    def test_curly_in_list(self):
        node = parse_formula("[T::a] in { 'x' , 'y' }")
        assert node["fn"] == "in" and len(node["args"]) == 3

    def test_number_inside_a_keyword_run(self):
        """PR #570 review M4: `then 1 else if (` / `then 0 else sum (` swept the number into
        the identifier run."""
        node = parse_formula("if ( [T::a] > 1 ) then 1 else if ( [T::a] > 0 ) then 2 else 3")
        assert node["branches"][0][1] == {"node": "lit", "kind": "number", "value": "1"}
        assert node["else"]["node"] == "ifelse"
        node = parse_formula("if ( [T::a] > 1 ) then 0 else sum ( [T::b] )")
        assert node["else"]["fn"] == "sum"
