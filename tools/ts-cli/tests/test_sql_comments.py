"""BL-382 — SQL comments in the from-direction SQL translators.

The Snowflake translator (``sv_sql``) tokenised comments as operators and identifiers:
``CASE WHEN b = 0 /* x */ THEN 0 -- y`` became ``[T::B] = 0 / * [T::X] * /``. Both
translators now strip comments with the one quote-aware ``sql_forms.strip_sql_comments``.
"""
from __future__ import annotations

import pytest

from ts_cli.databricks.mv_expr import strip_sql_comments as mv_expr_strip
from ts_cli.databricks.mv_sql import translate_sql_expr as dbx
from ts_cli.formula_translate.engine import translate
from ts_cli.sql_forms import strip_sql_comments
from ts_cli.sv_sql import translate_sql_expr as sf


def r(c: str) -> str:
    return f"[T::{c.split('.')[-1]}]"


BOTH = pytest.mark.parametrize("t", [dbx, sf], ids=["databricks", "snowflake"])


def test_databricks_reexport_is_the_shared_function():
    assert mv_expr_strip is strip_sql_comments


@BOTH
@pytest.mark.parametrize("src,want", [
    ("CASE WHEN b = 0 /* x */ THEN 0 -- y\n ELSE a / b END", "safe_divide ( [T::a] , [T::b] )"),
    ("a + b -- trailing", "[T::a] + [T::b]"),
    ("a /* one */ + /* two */ b", "[T::a] + [T::b]"),
    ("a +\n-- a whole line\nb", "[T::a] + [T::b]"),
    ("SUM(/* the amount */ x)", "sum ( [T::x] )"),
    ("a /* -- not a line comment */ + b", "[T::a] + [T::b]"),
])
def test_comments_are_stripped(t, src, want):
    assert t(src, r) == want


@BOTH
@pytest.mark.parametrize("src,want", [
    ("s = 'a -- b'", "[T::s] = 'a -- b'"),
    ("s = '/* not a comment */'", "[T::s] = '/* not a comment */'"),
    ("s = 'x' -- real comment", "[T::s] = 'x'"),
])
def test_markers_inside_string_literals_are_data(t, src, want):
    assert t(src, r) == want


def test_snowflake_double_slash_comment():
    assert sf("a + b // Snowflake line comment", r) == "[T::a] + [T::b]"
    assert sf("s = 'http://x'", r) == "[T::s] = 'http://x'"


def test_snowflake_quoted_identifier_keeps_its_markers():
    assert sf('"a--b" + 1', r) == "[T::a--b] + 1"
    assert strip_sql_comments('"a/*b*/" + 1', ident_quote='"') == '"a/*b*/" + 1'


def test_snowflake_backslash_escaped_quote_does_not_end_the_literal():
    out = strip_sql_comments(r"s = 'it\'s -- fine' -- gone", line_markers=("--", "//"),
                             ident_quote='"', backslash=True)
    assert out == r"s = 'it\'s -- fine'"


@BOTH
def test_backslash_escaped_quote_keeps_the_literal_whole(t):
    # Databricks (and Snowflake) read 'a\' -- b' as ONE literal, a\' -- b: ignoring the
    # escape would close the literal early and strip "-- b'" as a comment
    assert strip_sql_comments(r"s = 'a\' -- b' -- gone") == r"s = 'a\' -- b'"
    assert strip_sql_comments(r"s = 'it\'s' -- c") == r"s = 'it\'s'"
    assert t(r"s = 'a\' -- b' -- gone", r) == t(r"s = 'a\' -- b'", r)
    assert t(r"s = 'it\'s' -- c", r) == t(r"s = 'it\'s'", r)
    assert "it's" in t(r"s = 'it\'s'", r)


def test_databricks_stripper_and_tokenizer_agree_on_literal_spans():
    # every span the stripper keeps as a literal is one string token to mv_sql
    from ts_cli.databricks.mv_sql import tokenize
    for src in [r"'a\' -- b'", r"'it\'s'", r"'x\\'", "'a -- b'", "'/* c */'"]:
        assert strip_sql_comments(src) == src
        assert [k for k, _ in tokenize(src)] == ["string"]


def test_doubled_quote_escape():
    assert strip_sql_comments("col = 'it''s -- fine'") == "col = 'it''s -- fine'"


@pytest.mark.parametrize("dialect", ["snowflake", "databricks"])
def test_formula_translate_path(dialect):
    res = translate("CASE WHEN N2 = 0 /* guard */ THEN 0 -- zero\n ELSE N1 / NULLIF(N2, 0) END",
                    dialect)
    assert res["status"] == "TRANSLATED"
    assert res["formula"] == "safe_divide ( [TABLE::N1] , [TABLE::N2] )"
