# tools/ts-cli/tests/test_databricks_parse.py
"""Unit tests for ts_cli/databricks/mv_parse.py (BL-063 PR2 — ts databricks parse-mv).

One class per transform, mirroring test_tableau_translate.py. Pure functions
only until the CLI-command class at the bottom — no live connection anywhere.
"""
from __future__ import annotations

from ts_cli.databricks.mv_parse import classify_source, strip_sql_comments


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
