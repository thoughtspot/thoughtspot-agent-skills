from ts_cli.databricks.mv_emit_expr import tokenize, UntranslatableError
import pytest


class TestModuleContract:
    def test_untranslatable_error_is_exception(self):
        assert issubclass(UntranslatableError, Exception)


class TestTokenize:
    def test_bracket_column_ref(self):
        assert tokenize("[FACT::AMOUNT]") == [("bracket", "[FACT::AMOUNT]")]

    def test_agg_call(self):
        assert tokenize("sum ( [T::a] )") == [
            ("ident", "sum"), ("op", "("), ("bracket", "[T::a]"), ("op", ")")]

    def test_string_and_number_and_ops(self):
        assert tokenize("[T::x] = 'Active'") == [
            ("bracket", "[T::x]"), ("op", "="), ("string", "'Active'")]
        assert tokenize("[T::x] >= 10") == [
            ("bracket", "[T::x]"), ("op", ">="), ("number", "10")]

    def test_keywords_and_lodset(self):
        assert tokenize("if ( [T::x] != null ) then 1 else 0") == [
            ("kw", "if"), ("op", "("), ("bracket", "[T::x]"), ("op", "!="),
            ("kw", "null"), ("op", ")"), ("kw", "then"), ("number", "1"),
            ("kw", "else"), ("number", "0")]
        assert tokenize("{ [A::x] , [B::y] }") == [
            ("op", "{"), ("bracket", "[A::x]"), ("op", ","), ("bracket", "[B::y]"), ("op", "}")]

    def test_unrecognized_char_raises(self):
        with pytest.raises(UntranslatableError, match=r"unrecognized"):
            tokenize("[T::x] @ 1")
