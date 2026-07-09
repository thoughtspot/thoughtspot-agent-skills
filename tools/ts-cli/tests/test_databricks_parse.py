# tools/ts-cli/tests/test_databricks_parse.py
"""Unit tests for ts_cli/databricks/mv_parse.py (BL-063 PR2 — ts databricks parse-mv).

One class per transform, mirroring test_tableau_translate.py. Pure functions
only until the CLI-command class at the bottom — no live connection anywhere.
"""
from __future__ import annotations

from ts_cli.databricks.mv_parse import (
    classify_source,
    parse_offset,
    parse_range,
    parse_window,
    strip_sql_comments,
)


class TestStripSqlComments:
    def test_line_comment_stripped(self):
        assert strip_sql_comments("SUM(x) -- total") == "SUM(x)"

    def test_block_comment_stripped(self):
        assert strip_sql_comments("SUM(/* the amount */ x)") == "SUM(  x)"

    def test_multiline_block_comment(self):
        assert strip_sql_comments("SUM(x)\n/* a\nb */\n+ 1") == "SUM(x)\n \n+ 1"

    def test_no_comment_untouched(self):
        assert strip_sql_comments("a - b") == "a - b"


class TestClassifySource:
    def test_table_fqn(self):
        src = classify_source("catalog.schema.fact_table")
        assert src == {
            "kind": "table_fqn",
            "raw": "catalog.schema.fact_table",
            "parts": ["catalog", "schema", "fact_table"],
            "needs_live_check": True,
        }

    def test_backtick_fqn_parts_unquoted(self):
        src = classify_source("`my-cat`.`my sch`.`fact`")
        assert src["kind"] == "table_fqn"
        assert src["parts"] == ["my-cat", "my sch", "fact"]

    def test_backtick_fqn_with_dot_inside_segment(self):
        src = classify_source("`c.dev`.sch.fact")
        assert src["parts"] == ["c.dev", "sch", "fact"]

    def test_two_part_fqn_has_null_parts(self):
        src = classify_source("schema.table_only")
        assert src["kind"] == "table_fqn"
        assert src["parts"] is None
        assert src["needs_live_check"] is True

    def test_parenthesized_sql(self):
        src = classify_source("(SELECT a, b FROM t)")
        assert src == {"kind": "sql_query", "raw": "(SELECT a, b FROM t)",
                       "parenthesized": True}

    def test_bare_sql(self):
        src = classify_source("SELECT a, b FROM t")
        assert src["kind"] == "sql_query"
        assert src["parenthesized"] is False

    def test_bare_with_cte(self):
        assert classify_source("WITH c AS (SELECT 1) SELECT * FROM c")["kind"] == "sql_query"

    def test_parenthesized_cte_case_insensitive(self):
        assert classify_source("(with c as (select 1) select * from c)")["kind"] == "sql_query"

    def test_leading_whitespace_stripped(self):
        assert classify_source("  select 1 ")["kind"] == "sql_query"

    def test_unrecognized_returns_none(self):
        assert classify_source("???not a source") is None

    def test_empty_returns_none(self):
        assert classify_source("") is None


class TestParseRange:
    def test_current(self):
        assert parse_range("current") == {"type": "current", "n": None,
                                          "unit": None, "anchor": None}

    def test_cumulative(self):
        assert parse_range("cumulative")["type"] == "cumulative"

    def test_all(self):
        assert parse_range("all")["type"] == "all"

    def test_trailing_default_anchor_is_exclusive(self):
        assert parse_range("trailing 7 day") == {"type": "trailing", "n": 7,
                                                 "unit": "day", "anchor": "exclusive"}

    def test_trailing_inclusive(self):
        assert parse_range("trailing 30 day inclusive")["anchor"] == "inclusive"

    def test_leading_exclusive_explicit(self):
        assert parse_range("leading 7 day exclusive") == {"type": "leading", "n": 7,
                                                          "unit": "day", "anchor": "exclusive"}

    def test_case_and_whitespace_insensitive(self):
        assert parse_range("  Trailing 7 DAY  ")["type"] == "trailing"

    def test_month_unit(self):
        assert parse_range("trailing 3 month")["unit"] == "month"

    def test_modifier_on_current_rejected(self):
        assert parse_range("current inclusive") is None

    def test_modifier_on_all_rejected(self):
        assert parse_range("all exclusive") is None

    def test_garbage_rejected(self):
        assert parse_range("trailing seven day") is None

    def test_missing_unit_rejected(self):
        assert parse_range("trailing 7") is None


class TestParseOffset:
    def test_negative_month(self):
        assert parse_offset("-1 month") == {"n": -1, "unit": "month"}

    def test_negative_year(self):
        assert parse_offset("-1 year") == {"n": -1, "unit": "year"}

    def test_positive_rejected(self):
        assert parse_offset("1 month") is None

    def test_garbage_rejected(self):
        assert parse_offset("last month") is None


class TestParseWindow:
    def _win(self, **overrides):
        w = {"order": "order_month", "range": "current", "semiadditive": "last"}
        w.update(overrides)
        return [w]

    def test_valid_current_window(self):
        win, problems = parse_window(self._win(), "m")
        assert problems == []
        assert win["order"] == "order_month"
        assert win["range"]["type"] == "current"
        assert win["semiadditive"] == "last"
        assert win["offset"] is None
        assert win["density_check_required"] is False

    def test_offset_parsed(self):
        win, problems = parse_window(self._win(offset="-1 month"), "m")
        assert problems == []
        assert win["offset"] == {"n": -1, "unit": "month"}
        assert win["raw_offset"] == "-1 month"

    def test_trailing_sets_density_flag(self):
        win, problems = parse_window(self._win(range="trailing 7 day"), "m")
        assert problems == []
        assert win["density_check_required"] is True

    def test_leading_sets_density_flag(self):
        win, _ = parse_window(self._win(range="leading 7 day inclusive"), "m")
        assert win["density_check_required"] is True

    def test_cumulative_no_density_flag(self):
        win, _ = parse_window(self._win(range="cumulative"), "m")
        assert win["density_check_required"] is False

    def test_missing_semiadditive_fails(self):
        w = [{"order": "d", "range": "current"}]
        win, problems = parse_window(w, "m")
        assert win is None
        assert any("semiadditive" in p for p in problems)

    def test_bad_semiadditive_value_fails(self):
        win, problems = parse_window(self._win(semiadditive="sum"), "m")
        assert win is None and problems

    def test_missing_order_fails(self):
        w = [{"range": "current", "semiadditive": "last"}]
        win, problems = parse_window(w, "m")
        assert win is None
        assert any("order" in p for p in problems)

    def test_bad_range_fails_with_measure_name(self):
        win, problems = parse_window(self._win(range="sideways 3 day"), "m1")
        assert win is None
        assert any("m1" in p for p in problems)

    def test_bad_offset_fails(self):
        win, problems = parse_window(self._win(offset="next month"), "m")
        assert win is None and problems

    def test_multi_entry_window_fails(self):
        win, problems = parse_window(self._win() + self._win(), "m")
        assert win is None
        assert any("single-entry" in p for p in problems)

    def test_non_list_window_fails(self):
        win, problems = parse_window({"order": "d"}, "m")
        assert win is None and problems

    def test_unknown_window_key_fails(self):
        win, problems = parse_window(self._win(frame="rows"), "m")
        assert win is None
        assert any("frame" in p for p in problems)
