"""Unit tests for ts_cli/tableau/parsing.py — low-level expression scanners.

These are the shared string-scanning primitives (bracket/brace/paren-depth
tracking, top-level comma/colon splitting) used by every higher-level
Tableau transform. Covers the branches not otherwise exercised indirectly
through functions.py / lod.py / conditionals.py callers: nested CASE/END,
unbalanced input, and literal-quote skipping.
"""
from __future__ import annotations

from ts_cli.tableau.parsing import (
    _extract_function_args,
    _find_last_top_level_else,
    _find_matching_brace,
    _find_matching_end,
    _find_top_level_colon,
    _split_args,
)


# ---------------------------------------------------------------------------
# _find_matching_end
# ---------------------------------------------------------------------------

class TestFindMatchingEnd:
    def test_nested_case_end_pair_does_not_close_outer(self):
        # The inner CASE/END pair increments then decrements depth back to 1;
        # only the second, outer-matching END should close the block.
        text = "WHEN 1 THEN CASE WHEN 2 THEN 'x' END END"
        assert _find_matching_end(text) == len(text)

    def test_unmatched_case_returns_none(self):
        # No END anywhere in the text — depth never reaches 0.
        assert _find_matching_end("WHEN 1 THEN 'x'") is None


# ---------------------------------------------------------------------------
# _split_args
# ---------------------------------------------------------------------------

class TestSplitArgs:
    def test_comma_inside_braces_not_split(self):
        # A comma nested inside {} (e.g. LOD dimension braces) must not be
        # treated as a top-level argument separator.
        assert _split_args("a{b,c}d, e") == ["a{b,c}d", " e"]


# ---------------------------------------------------------------------------
# _extract_function_args
# ---------------------------------------------------------------------------

class TestExtractFunctionArgs:
    def test_start_pos_not_an_open_paren_returns_none(self):
        assert _extract_function_args("abc", 0) is None

    def test_start_pos_past_end_of_string_returns_none(self):
        assert _extract_function_args("abc", 10) is None

    def test_braces_inside_args_tracked_correctly(self):
        # A { } pair nested inside the parens must not confuse paren-depth
        # counting (relevant for LOD expressions nested in function calls).
        assert _extract_function_args("({a},b)", 0) == (["{a}", "b"], 7)

    def test_unbalanced_parens_returns_none(self):
        assert _extract_function_args("(abc", 0) is None


# ---------------------------------------------------------------------------
# _find_matching_brace
# ---------------------------------------------------------------------------

class TestFindMatchingBrace:
    def test_brace_inside_double_quoted_string_skipped(self):
        expr = '{a "b}c" d}'
        assert _find_matching_brace(expr, 0) == len(expr) - 1

    def test_nested_braces_tracked(self):
        expr = "{a{b}c}"
        assert _find_matching_brace(expr, 0) == len(expr) - 1

    def test_unbalanced_brace_returns_negative_one(self):
        assert _find_matching_brace("{abc", 0) == -1


# ---------------------------------------------------------------------------
# _find_top_level_colon
# ---------------------------------------------------------------------------

class TestFindTopLevelColon:
    def test_colon_inside_single_quotes_skipped(self):
        assert _find_top_level_colon("'a:b' : c") == 6

    def test_colon_inside_double_quotes_skipped(self):
        assert _find_top_level_colon('"a:b" : c') == 6

    def test_colon_inside_parens_skipped(self):
        assert _find_top_level_colon("(a:b) : c") == 6

    def test_colon_inside_braces_skipped(self):
        assert _find_top_level_colon("{a:b} : c") == 6

    def test_no_colon_returns_negative_one(self):
        assert _find_top_level_colon("[A] + [B]") == -1


# ---------------------------------------------------------------------------
# _find_last_top_level_else
# ---------------------------------------------------------------------------

class TestFindLastTopLevelElse:
    def test_else_inside_string_literal_skipped(self):
        # The quoted 'else' must not be mistaken for the keyword — only the
        # real, top-level else that follows should be returned.
        s = "'else' else"
        assert _find_last_top_level_else(s) == 7

    def test_no_else_returns_negative_one(self):
        assert _find_last_top_level_else("[A] + [B]") == -1
