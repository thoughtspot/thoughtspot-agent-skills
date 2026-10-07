"""BL-365: ThoughtSpot string literals and `a * b / c` grouping, across every translator.

The facts (live, se-thoughtspot 2026-10-07, probe record §7 "Quotes and grouping"):
``'it''s'`` is read as two quotes; ``'it\\'s'`` fails to parse when a space follows the
escape; the double-quoted ``"it's"`` is exact in every position probed; ``a * b / c`` is
read as ``a * ( b / c )``; ``a / b / c``, ``a / b * c``, ``a - b + c`` stay left to right.
"""
from __future__ import annotations

import json

import pytest

from ts_cli.formula_common import UntranslatableError
from ts_cli.formula_text import (
    sql_literal_text,
    sql_std_literal,
    ts_bracket_product_divisions,
    ts_finalize_formula,
    ts_finalize_string_literals,
    ts_literal_token_text,
    ts_string_literal,
)
from ts_cli.formula_translate.context import ColumnContext, parse_columns_json
from ts_cli.formula_translate.engine import translate

TEXTS = ["O'Brien", "it's", "", "a'b'c", "'", "it's here", "x's "]


# ---------------------------------------------------------------------------
# The shared helpers
# ---------------------------------------------------------------------------

class TestStringLiteral:
    @pytest.mark.parametrize("text,out", [
        ("plain", "'plain'"),
        ("", "''"),
        ("O'Brien", '"O\'Brien"'),
        ("it's here", '"it\'s here"'),
        ("a'b'c", '"a\'b\'c"'),
        ("'", '"\'"'),
        ("a\\b", '"a\\\\b"'),
        ('say "hi"', "'say \"hi\"'"),
        ('say "hi" it\'s', "concat ( 'say ' , '\"' , 'hi' , '\"' , \" it's\" )"),
    ])
    def test_forms(self, text, out):
        assert ts_string_literal(text) == out

    @pytest.mark.parametrize("text", TEXTS + ["a\\b", 'q"\'', '"', "a\\'b"])
    def test_reads_back_as_the_text(self, text):
        # a literal token is read back by ThoughtSpot's rules (ts_literal_token_text)
        out = ts_string_literal(text)
        if out.startswith("concat"):
            return  # several tokens; covered by the value tests
        assert ts_literal_token_text(out) == text

    @pytest.mark.parametrize("text", TEXTS + ["a\\b", 'say "hi" it\'s'])
    def test_fixed_point_of_finalize(self, text):
        out = ts_string_literal(text)
        assert ts_finalize_string_literals(out) == out

    def test_finalize_rewrites_only_misread_literals(self):
        src = "concat ( 'a' , 'it''s' , [T::it's] , sql_string_op ( \"'x''y'\" ) , 'a\\b' )"
        assert ts_finalize_string_literals(src) == (
            "concat ( 'a' , \"it's\" , [T::it's] , sql_string_op ( \"'x''y'\" ) , \"a\\\\b\" )")

    def test_finalize_leaves_comments(self):
        src = "/* TODO review: If(s = 'it''s', 1, 0) */"
        assert ts_finalize_formula(src) == src

    def test_sql_std_round_trip(self):
        for t in TEXTS:
            assert ts_finalize_string_literals(sql_std_literal(t)) == ts_string_literal(t)


class TestSqlLiteralText:
    @pytest.mark.parametrize("tok,text", [
        ("'it''s'", "it's"), ("'it\\'s'", "it's"), ("'a\\\\b'", "a\\b"), ("''", ""),
        ("''''", "'"), ("'a\\\"b'", 'a"b'),
    ])
    def test_snowflake(self, tok, text):
        assert sql_literal_text(tok, "snowflake") == text

    @pytest.mark.parametrize("tok,text", [
        ("'it\\'s'", "it's"), ("'a\\\\b'", "a\\b"), ("''", "")])
    def test_databricks(self, tok, text):
        assert sql_literal_text(tok, "databricks") == text

    @pytest.mark.parametrize("dialect", ["snowflake", "databricks"])
    def test_unproven_escape_refused(self, dialect):
        with pytest.raises(UntranslatableError, match="escape"):
            sql_literal_text("'a\\nb'", dialect)


class TestBracketProductDivisions:
    @pytest.mark.parametrize("src,out", [
        ("[a] * 4 / 3", "( [a] * 4 ) / 3"),
        ("[a] * [b] * 5 / 3", "( [a] * [b] * 5 ) / 3"),
        ("- [a] * 3 / 7", "( - [a] * 3 ) / 7"),
        ("sum ( [a] ) * 100 / sum ( [b] )", "( sum ( [a] ) * 100 ) / sum ( [b] )"),
        ("unique count ( [a] ) * 100 / count ( [b] )",
         "( unique count ( [a] ) * 100 ) / count ( [b] )"),
        ("[a] * 2 / 3 * 4 / 5", "( ( [a] * 2 ) / 3 * 4 ) / 5"),
        ("if ( [x] > 1 ) then [a] * 2 / [b] else 0",
         "if ( [x] > 1 ) then ( [a] * 2 ) / [b] else 0"),
        ("[a] - [b] * 2 / 3", "[a] - ( [b] * 2 ) / 3"),
        ("[a] * ( [b] * 2 / 3 )", "[a] * ( ( [b] * 2 ) / 3 )"),
    ])
    def test_bracketed(self, src, out):
        assert ts_bracket_product_divisions(src) == out
        assert ts_bracket_product_divisions(out) == out  # idempotent

    @pytest.mark.parametrize("src", [
        "[a] / 3 * 7", "[a] / [b] / 7", "[a] - 3 + 7", "[a] - [b] - 7", "( [a] * 4 ) / 3",
        "[a] / [b]", "sql_double_op ( \"{0} * 2 / 3\" , [a] )", "[a * b] / [c]",
        "[a] + [b] / 3", "'x * y / z'",
    ])
    def test_unchanged(self, src):
        assert ts_bracket_product_divisions(src) == src


# ---------------------------------------------------------------------------
# Every translator: literals with a quote, and the percent-of-total shape
# ---------------------------------------------------------------------------

_COLS = json.dumps([{"source": c, "table": "T", "column": c.upper(), "data_type": t,
                     "column_type": k}
                    for c, t, k in [("s", "VARCHAR", "ATTRIBUTE"), ("x", "DOUBLE", "MEASURE"),
                                    ("y", "DOUBLE", "MEASURE")]])


def _tr(src, dialect):
    r = translate(src, dialect, ColumnContext(parse_columns_json(_COLS), level=1))
    assert r["formula"] is not None, r["notes"]
    return r["formula"]


def _sq(t):  # SQL-standard / Tableau / Qlik spelling
    return "'" + t.replace("'", "''") + "'"


def _dax(t):
    return '"' + t.replace('"', '""') + '"'


def _sf(t):  # Snowflake: either '' or \'
    return "'" + t.replace("'", "\\'") + "'"


SOURCES = {
    "tableau": lambda t: f"IF [s] = {_sq(t)} THEN 1 ELSE 0 END",
    "dax": lambda t: f"IF([s] = {_dax(t)}, 1, 0)",
    "qlik": lambda t: f"If(s = {_sq(t)}, 1, 0)",
    "snowflake": lambda t: f"IFF(s = {_sq(t)}, 1, 0)",
    "databricks": lambda t: f"CASE WHEN s = {_sf(t)} THEN 1 ELSE 0 END",
}


@pytest.mark.parametrize("dialect", sorted(SOURCES))
@pytest.mark.parametrize("text", ["O'Brien", "it's", "", "a'b'c"])
def test_quote_literal_per_translator(dialect, text):
    out = _tr(SOURCES[dialect](text), dialect)
    assert ts_string_literal(text) in out, out
    if "'" in text:  # no doubled quote (two quotes) and no backslash escape (fails on a space)
        assert "''" not in out and "\\'" not in out


@pytest.mark.parametrize("dialect,src", [
    ("tableau", "SUM([x]) * 100 / SUM([y])"),
    ("dax", "SUM([x]) * 100 / SUM([y])"),
    ("qlik", "Sum(x) * 100 / Sum(y)"),
    ("sisense", "SUM([x]) * 100 / SUM([y])"),
    ("snowflake", "SUM(x) * 100 / SUM(y)"),
    ("databricks", "SUM(x) * 100 / SUM(y)"),
    ("excel", "=SUM(Table1[x])*100/SUM(Table1[y])"),
])
def test_percent_of_total_is_bracketed(dialect, src):
    if dialect == "excel":
        cols = json.dumps([{"source": "Table1[x]", "table": "T", "column": "X",
                            "data_type": "DOUBLE", "column_type": "MEASURE"},
                           {"source": "Table1[y]", "table": "T", "column": "Y",
                            "data_type": "DOUBLE", "column_type": "MEASURE"}])
        r = translate(src, dialect, ColumnContext(parse_columns_json(cols), level=1))
        out = r["formula"] or ""
    elif dialect == "sisense":
        out = translate(src, dialect)["formula"]
    else:
        out = _tr(src, dialect)
    assert " ) * 100 ) /" in out.replace("])", "] )"), out


def test_sisense_literal():
    from ts_cli.sisense.functions import translate_jaql
    out, _status, _note = translate_jaql("IF([s] = 'it''s', 1, 0)")
    assert '"it\'s"' in out, out


def test_databricks_adjacent_literals_are_one():
    # Databricks reads 'it''s' as 'it' 's' = its (live 2026-10-07)
    assert _tr("CASE WHEN s = 'it''s' THEN 1 ELSE 0 END", "databricks").count("'its'") == 1


@pytest.mark.parametrize("dialect", ["snowflake", "databricks"])
def test_like_with_a_quote_binds_the_pattern(dialect):
    out = _tr("s LIKE 'O\\'B%'", dialect)
    assert out == 'sql_bool_op ( "{0} LIKE {1}" , [T::S] , "O\'B%" )'


@pytest.mark.parametrize("dialect", ["snowflake", "databricks"])
def test_passthrough_binds_a_quote_literal(dialect):
    out = _tr("REPLACE(s, '\\'', '-')", dialect)
    assert out == 'sql_string_op ( "REPLACE({0}, {1}, {2})" , [T::S] , "\'" , \'-\' )'


class TestReverseDirection:
    """ThoughtSpot → Excel and → Databricks read a literal as ThoughtSpot does."""

    @pytest.mark.parametrize("ts,text", [
        ("'it''s'", "it''s"), ('"it\'s"', "it's"), ("'a\\\\b'", "a\\b"), ("'o\\'neil'", "o'neil"),
    ])
    def test_to_excel(self, ts, text):
        from ts_cli.excel.to_excel import to_excel
        assert to_excel(f"[T::s] = {ts}").formula == '=[@s]="' + text + '"'

    @pytest.mark.parametrize("ts,sql", [
        ("'it''s'", "'it\\'\\'s'"), ('"it\'s"', "'it\\'s'"), ("'a\\\\b'", "'a\\\\b'"),
        ("'Active'", "'Active'"),
    ])
    def test_to_databricks(self, ts, sql):
        from ts_cli.databricks.mv_emit_expr import parse_formula
        from ts_cli.databricks.mv_emit_sql import emit_sql
        out = emit_sql(parse_formula(f"[T::s] = {ts}"), lambda n: "source." + n["column"])
        assert out == f"source.s = {sql}"


@pytest.mark.parametrize("dialect", ["snowflake", "databricks"])
def test_bound_literal_keeps_the_unprobed_character_refusal(dialect):
    """#579 review: binding a quote-bearing literal must not skip the refusal of a double
    quote, brace or backslash, which no bound-literal probe covers (main refused it too)."""
    r = translate("s LIKE 'it\\'s\\\\_%'", dialect,
                  ColumnContext(parse_columns_json(_COLS), level=1))
    assert r["status"] == "NEEDS_REVIEW"
    assert "backslash" in " ".join(r["notes"])


def test_bound_passthrough_keeps_the_refusal():
    from ts_cli.formula_common import sql_passthrough_call
    with pytest.raises(UntranslatableError, match="backslash"):
        sql_passthrough_call("sql_string_op", "TO_CHAR", ["[T::D]", "'it''s\\'"])
    assert sql_passthrough_call("sql_string_op", "TO_CHAR", ["[T::D]", "'it''s'"]) == \
        'sql_string_op ( "TO_CHAR({0}, {1})" , [T::D] , \'it\'\'s\' )'


class TestQlikAmpersand:
    """Qlik `&` is string concatenation; it was rewritten to ThoughtSpot `+` (numeric only),
    including inside literals (#579 review)."""

    @pytest.mark.parametrize("src,out", [
        ("s & ' - ' & s", "concat ( [T::S] , ' - ' , [T::S] )"),
        ("s & 'it''s \"x\"'", "concat ( [T::S] , concat ( \"it's \" , '\"' , 'x' , '\"' ) )"),
        ("If(x > 1, s & 'a', 'b')", "if ([T::X] > 1) then concat ( [T::S] , 'a' ) else 'b'"),
        ("'A&B'", "'A&B'"),
    ])
    def test_concat(self, src, out):
        assert _tr(src, "qlik") == out

    def test_concat_beside_a_comparison_is_reviewed(self):
        r = translate("s & 'a' = 'xa'", "qlik", ColumnContext(parse_columns_json(_COLS), level=1))
        assert r["status"] == "NEEDS_REVIEW"

    def test_plus_next_to_concat_is_guarded(self):
        from ts_cli.formula_translate.traps import _PLUS_STRING, _code
        assert _PLUS_STRING.search(_code("[T::S] + concat ( 'a' , 'b' )"))
        assert _PLUS_STRING.search(_code("concat ( 'a' , [T::B] ) + [T::S]"))
        assert not _PLUS_STRING.search(_code("[T::A] + [T::B]"))


def test_finalize_leaves_a_backslash_escaped_quote_whole_and_the_guard_reports_it():
    """#579 review: `[a] = 'it\\'s'` was rewritten to an unbalanced `"it\\\\"s'`. The scanner's
    precondition is SQL-standard literals; text that breaks it is returned unchanged."""
    from ts_cli.formula_text import ts_literals_unbalanced
    from ts_cli.formula_translate.traps import output_guard
    src = "[T::A] = 'it\\'s'"
    assert ts_literals_unbalanced(src)
    assert ts_finalize_formula(src) == src
    assert "double-quoted literal" in output_guard(src)
    # a SQL-standard literal that ends in a backslash still converts
    assert ts_finalize_formula("concat ( 'a\\' , 'b' )") == "concat ( \"a\\\\\" , 'b' )"
    assert output_guard("[T::A] = \"it's\"") is None
