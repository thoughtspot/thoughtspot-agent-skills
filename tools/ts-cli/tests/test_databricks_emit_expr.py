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
