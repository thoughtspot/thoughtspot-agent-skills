"""Unit tests for ts_cli.snowflake_ops — pure helpers behind `ts snowflake diff`
and `ts snowflake lint-ddl` (BL-063 codification quick wins).

Pure-function tests — no ThoughtSpot or Snowflake connection required.
"""
import pytest

from ts_cli.snowflake_ops import (
    compute_change_set,
    exprs_differ,
    lint_sv_ddl,
    normalise_expr,
    parse_var_assignment,
    substitute_sql_vars,
)


# ---------------------------------------------------------------------------
# normalise_expr / exprs_differ
# ---------------------------------------------------------------------------

def test_normalise_expr_is_case_insensitive_outside_stashed_tokens():
    assert normalise_expr("SUM(Amount)") == normalise_expr("sum(amount)")


def test_normalise_expr_collapses_whitespace_runs():
    # Multiple internal spaces collapse to one — but only whitespace *runs*, so
    # keep the padding pattern identical around punctuation on both sides.
    a = "sum(x,   y)"
    b = "sum(x, y)"
    assert normalise_expr(a) == normalise_expr(b)


def test_normalise_expr_preserves_double_quoted_identifier_case():
    # The double-quoted identifier "Date" must survive lowercasing untouched, while
    # SUM outside the quotes still lowers normally. This is the historical bug fix:
    # the original SKILL.md inline helper stashed under an uppercase __REFN__ key,
    # which .lower() mangled, so the restore loop below it never matched and the
    # placeholder itself leaked into the "normalised" output.
    result = normalise_expr('SUM("Date")')
    assert result == 'sum("Date")'
    assert "__normref" not in result


def test_normalise_expr_preserves_bracket_reference_case():
    result = normalise_expr("SUM([Amount])")
    assert result == "sum([Amount])"
    assert "__normref" not in result


def test_normalise_expr_preserves_brace_reference_case():
    # Both [Revenue] (bracket) and {Target} (brace) are stashed tokens, so neither
    # is lowered — only surrounding syntax (here, none but whitespace) would be.
    result = normalise_expr("[Revenue] / {Target}")
    assert result == "[Revenue] / {Target}"
    assert "__normref" not in result


def test_exprs_differ_true_for_bracket_content_case_change():
    # Bracket content is a real ThoughtSpot column reference — case matters.
    assert exprs_differ("sum([Amount])", "sum([amount])") is True


def test_exprs_differ_false_for_case_and_whitespace_run_only():
    assert exprs_differ("SUM(x,   y)", "sum(x, y)") is False


def test_exprs_differ_true_for_real_difference():
    assert exprs_differ("sum([Amount])", "avg([Amount])") is True


# ---------------------------------------------------------------------------
# compute_change_set
# ---------------------------------------------------------------------------

def test_change_set_detects_new_and_removed_columns():
    current = {"A": {"expr": "sum(x)"}, "B": {"expr": "sum(y)"}}
    new = {"A": {"expr": "sum(x)"}, "C": {"expr": "sum(z)"}}
    change_set = compute_change_set(current, new)
    assert change_set["new_columns"] == ["C"]
    assert change_set["removed_columns"] == ["B"]
    assert change_set["modified_expressions"] == []


def test_change_set_detects_modified_expression():
    current = {"A": {"expr": "sum(x)"}}
    new = {"A": {"expr": "avg(x)"}}
    change_set = compute_change_set(current, new)
    assert change_set["modified_expressions"] == [
        {"column": "A", "current": "sum(x)", "new": "avg(x)"}
    ]


def test_change_set_ignores_expression_unchanged_after_normalisation():
    current = {"A": {"expr": "SUM(x)"}}
    new = {"A": {"expr": "sum(x)"}}
    change_set = compute_change_set(current, new)
    assert change_set["modified_expressions"] == []


def test_change_set_default_flags_any_description_difference():
    # Default (to-side behaviour): any difference is flagged, including going blank.
    current = {"A": {"expr": "x", "description": "old desc"}}
    new = {"A": {"expr": "x", "description": ""}}
    change_set = compute_change_set(current, new)
    assert change_set["modified_descriptions"] == [
        {"column": "A", "current": "old desc", "new": ""}
    ]


def test_change_set_ignore_empty_new_description_skips_blank_new_value():
    # from-side behaviour: a blank new description means "no opinion", not "clear it".
    current = {"A": {"expr": "x", "description": "old desc"}}
    new = {"A": {"expr": "x", "description": ""}}
    change_set = compute_change_set(current, new, ignore_empty_new_description=True)
    assert change_set["modified_descriptions"] == []


def test_change_set_ignore_empty_new_description_still_flags_nonempty_change():
    current = {"A": {"expr": "x", "description": "old desc"}}
    new = {"A": {"expr": "x", "description": "new desc"}}
    change_set = compute_change_set(current, new, ignore_empty_new_description=True)
    assert change_set["modified_descriptions"] == [
        {"column": "A", "current": "old desc", "new": "new desc"}
    ]


def test_change_set_modified_synonyms_only_when_both_sides_have_synonyms():
    current = {"A": {"expr": "x", "synonyms": ["Alpha"]}}
    new = {"A": {"expr": "x", "synonyms": ["Alpha", "Beta"]}}
    change_set = compute_change_set(current, new)
    assert change_set["modified_synonyms"] == [{
        "column": "A",
        "current": ["Alpha"],
        "new": ["Alpha", "Beta"],
        "added": ["Beta"],
        "removed": [],
    }]


def test_change_set_modified_synonyms_skipped_when_one_side_lacks_synonym_data():
    # Mirrors the to-side call site, which never tracks synonyms at all.
    current = {"A": {"expr": "x", "synonyms": ["Alpha"]}}
    new = {"A": {"expr": "x"}}
    change_set = compute_change_set(current, new)
    assert change_set["modified_synonyms"] == []


def test_change_set_no_changes_is_all_empty():
    current = {"A": {"expr": "sum(x)", "description": "d", "synonyms": ["s"]}}
    new = {"A": {"expr": "SUM(x)", "description": "d", "synonyms": ["s"]}}
    change_set = compute_change_set(current, new)
    assert change_set == {
        "new_columns": [],
        "removed_columns": [],
        "modified_expressions": [],
        "modified_descriptions": [],
        "modified_synonyms": [],
    }


# ---------------------------------------------------------------------------
# lint_sv_ddl
# ---------------------------------------------------------------------------

_CLEAN_DDL = """
CREATE OR REPLACE SEMANTIC VIEW SALES_SV
  tables (
    DM.PUBLIC.ORDERS primary key (ORDER_ID),
    DM.PUBLIC.CUSTOMERS primary key (CUSTOMER_ID)
  )
  relationships (
    orders_to_customers as ORDERS(CUSTOMER_ID) references CUSTOMERS(CUSTOMER_ID)
  )
  dimensions (
    ORDERS.ORDER_ID as orders.ORDER_ID with synonyms=('Order Number', 'U.S. Order No.'),
    CUSTOMERS.CUSTOMER_NAME as customers.CUSTOMER_NAME
  )
  metrics (
    ORDERS.TOTAL_REVENUE as SUM(orders.AMOUNT) comment='total revenue',
    ORDERS.AVG_ORDER_VALUE as DIV0(orders.TOTAL_REVENUE, orders.ORDER_COUNT)
  )
  comment='Sales semantic view'
  with extension (CA='{"tables": []}');
"""


def _findings_by_check(ddl: str, check: str):
    return [f for f in lint_sv_ddl(ddl) if f["check"] == check]


def test_clean_ddl_has_no_findings():
    assert lint_sv_ddl(_CLEAN_DDL) == []


def test_check1_invalid_view_name_is_flagged():
    ddl = _CLEAN_DDL.replace("SALES_SV", "SALES-SV")
    findings = _findings_by_check(ddl, "identifier-format")
    assert any("SALES-SV" in f["message"] for f in findings)


def test_check1_invalid_alias_is_flagged():
    ddl = _CLEAN_DDL.replace(
        "ORDERS.ORDER_ID as orders.ORDER_ID with synonyms=('Order Number', 'U.S. Order No.')",
        "ORDERS.1BAD as orders.ORDER_ID",
    )
    findings = _findings_by_check(ddl, "identifier-format")
    assert any("1BAD" in f["message"] for f in findings)


def test_check1_valid_identifiers_produce_no_finding():
    assert _findings_by_check(_CLEAN_DDL, "identifier-format") == []


def test_check2_duplicate_alias_across_dimensions_and_metrics_is_flagged():
    ddl = """
    CREATE OR REPLACE SEMANTIC VIEW SALES_SV
      tables (
        DM.PUBLIC.ORDERS primary key (ORDER_ID),
        DM.PUBLIC.CUSTOMERS primary key (CUSTOMER_ID)
      )
      relationships (
        orders_to_customers as ORDERS(CUSTOMER_ID) references CUSTOMERS(CUSTOMER_ID)
      )
      dimensions (
        ORDERS.TOTAL as orders.ORDER_ID
      )
      metrics (
        CUSTOMERS.TOTAL as SUM(customers.SPEND)
      )
      comment='x';
    """
    findings = _findings_by_check(ddl, "duplicate-alias")
    assert any("TOTAL" in f["message"] for f in findings)


def test_check2_unique_aliases_produce_no_finding():
    assert _findings_by_check(_CLEAN_DDL, "duplicate-alias") == []


def test_check3_undeclared_table_in_relationship_is_flagged():
    ddl = _CLEAN_DDL.replace(
        "orders_to_customers as ORDERS(CUSTOMER_ID) references CUSTOMERS(CUSTOMER_ID)",
        "orders_to_nowhere as ORDERS(CUSTOMER_ID) references NOWHERE(CUSTOMER_ID)",
    )
    findings = _findings_by_check(ddl, "undeclared-table")
    assert any("NOWHERE" in f["message"] for f in findings)


def test_check3_undeclared_table_in_metric_expression_is_flagged():
    ddl = _CLEAN_DDL.replace(
        "ORDERS.TOTAL_REVENUE as SUM(orders.AMOUNT) comment='total revenue',",
        "ORDERS.TOTAL_REVENUE as SUM(ghost_table.AMOUNT) comment='total revenue',",
    )
    findings = _findings_by_check(ddl, "undeclared-table")
    assert any("ghost_table" in f["message"] for f in findings)


def test_check3_all_declared_tables_produce_no_finding():
    assert _findings_by_check(_CLEAN_DDL, "undeclared-table") == []


def test_check3_synonym_text_with_dots_is_not_mistaken_for_a_table_reference():
    # 'U.S. Order No.' inside the synonyms=(...) string literal must not be parsed
    # as a table.column reference — this is the false-positive guard on
    # _strip_string_literals.
    assert _findings_by_check(_CLEAN_DDL, "undeclared-table") == []


def test_check4_metric_forward_reference_is_flagged():
    ddl = """
    CREATE OR REPLACE SEMANTIC VIEW SALES_SV
      tables ( DM.PUBLIC.ORDERS primary key (ORDER_ID) )
      relationships ()
      dimensions ( ORDERS.ORDER_ID as orders.ORDER_ID )
      metrics (
        ORDERS.RATIO as DIV0(orders.total_revenue, orders.order_count),
        ORDERS.TOTAL_REVENUE as SUM(orders.amount)
      )
      comment='x';
    """
    findings = _findings_by_check(ddl, "metric-forward-reference")
    assert any("total_revenue" in f["message"] for f in findings)


def test_check4_metric_referencing_earlier_alias_is_not_flagged():
    # Same reference, but TOTAL_REVENUE now comes first — this is the valid,
    # correctly-ordered form the checklist item requires; must not false-positive.
    assert _findings_by_check(_CLEAN_DDL, "metric-forward-reference") == []


def test_check5_dashdash_todo_placeholder_is_flagged():
    ddl = _CLEAN_DDL + "\n-- TODO: fix this later\n"
    findings = _findings_by_check(ddl, "untranslatable-placeholder")
    assert any("TODO" in f["message"] for f in findings)


def test_check5_cast_null_as_text_placeholder_is_flagged():
    ddl = _CLEAN_DDL.replace(
        "ORDERS.TOTAL_REVENUE as SUM(orders.AMOUNT) comment='total revenue',",
        "ORDERS.TOTAL_REVENUE as CAST(NULL AS TEXT),",
    )
    findings = _findings_by_check(ddl, "untranslatable-placeholder")
    assert any("CAST(NULL AS TEXT)" in f["message"] for f in findings)


def test_check5_placeholder_text_inside_a_string_literal_is_not_flagged():
    # A synonym/comment that merely *mentions* "TODO" in prose is not a real
    # untranslatable placeholder — must not fire once it's inside a quoted literal.
    ddl = _CLEAN_DDL.replace(
        "comment='total revenue'",
        "comment='revenue -- TODO check this figure'",
    )
    assert _findings_by_check(ddl, "untranslatable-placeholder") == []


def test_check5_clean_ddl_has_no_placeholder_finding():
    assert _findings_by_check(_CLEAN_DDL, "untranslatable-placeholder") == []


def test_check6_unescaped_apostrophe_in_comment_is_flagged():
    ddl = _CLEAN_DDL.replace(
        "CUSTOMERS.CUSTOMER_NAME as customers.CUSTOMER_NAME",
        "CUSTOMERS.CUSTOMER_NAME as customers.CUSTOMER_NAME comment='Manager's report'",
    )
    findings = _findings_by_check(ddl, "unescaped-comment-quote")
    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"


def test_check6_properly_escaped_apostrophe_is_not_flagged():
    # Correctly doubled '' — the valid Snowflake escape for an embedded quote —
    # must not be mistaken for the broken case above.
    ddl = _CLEAN_DDL.replace(
        "CUSTOMERS.CUSTOMER_NAME as customers.CUSTOMER_NAME",
        "CUSTOMERS.CUSTOMER_NAME as customers.CUSTOMER_NAME comment='Manager''s report'",
    )
    assert _findings_by_check(ddl, "unescaped-comment-quote") == []


def test_check6_clean_ddl_has_no_comment_quote_finding():
    assert _findings_by_check(_CLEAN_DDL, "unescaped-comment-quote") == []


def test_findings_are_deduplicated():
    # The same undeclared table referenced twice in one expression should not
    # produce two identical findings.
    ddl = """
    CREATE OR REPLACE SEMANTIC VIEW SALES_SV
      tables ( DM.PUBLIC.ORDERS primary key (ORDER_ID) )
      relationships ()
      dimensions ( ORDERS.ORDER_ID as orders.ORDER_ID )
      metrics ( ORDERS.RATIO as DIV0(ghost.a, ghost.b) )
      comment='x';
    """
    findings = _findings_by_check(ddl, "undeclared-table")
    # ghost.a and ghost.b both reference the same undeclared table "ghost" from the
    # same entry -- messages differ per referenced identifier name, so expect one
    # finding per distinct message rather than a single collapsed one.
    messages = {f["message"] for f in findings}
    assert len(findings) == len(messages)


# ---------------------------------------------------------------------------
# parse_var_assignment / substitute_sql_vars (BL-079 — `ts snowflake exec`)
# ---------------------------------------------------------------------------

def test_parse_var_assignment_basic():
    assert parse_var_assignment("target_db=ANALYTICS") == ("target_db", "ANALYTICS")


def test_parse_var_assignment_splits_on_first_equals_only():
    # A value may legitimately contain '=' (e.g. a predicate fragment).
    assert parse_var_assignment("clause=a=b") == ("clause", "a=b")


def test_parse_var_assignment_allows_empty_value():
    assert parse_var_assignment("suffix=") == ("suffix", "")


def test_parse_var_assignment_rejects_missing_equals():
    with pytest.raises(ValueError):
        parse_var_assignment("target_db")


def test_parse_var_assignment_rejects_empty_key():
    with pytest.raises(ValueError):
        parse_var_assignment("=ANALYTICS")


def test_parse_var_assignment_rejects_non_identifier_key():
    with pytest.raises(ValueError):
        parse_var_assignment("target-db=ANALYTICS")


def test_substitute_sql_vars_replaces_all_occurrences():
    sql = "CREATE FUNCTION {db}.{sc}.f() ... {db}.{sc}.g()"
    out = substitute_sql_vars(sql, {"db": "ANALYTICS", "sc": "PUBLIC"})
    assert out == "CREATE FUNCTION ANALYTICS.PUBLIC.f() ... ANALYTICS.PUBLIC.g()"


def test_substitute_sql_vars_leaves_sql_without_placeholders_untouched():
    sql = "SELECT DATEADD('day', 2, ts)"  # braces-free SQL must survive verbatim
    assert substitute_sql_vars(sql, {}) == sql


def test_substitute_sql_vars_raises_on_unsubstituted_placeholder():
    # A placeholder with no matching --var is the dangerous case: silently
    # emitting `{target_schema}` into Snowflake would fail confusingly.
    with pytest.raises(ValueError) as exc:
        substitute_sql_vars("... {target_db}.{target_schema} ...", {"target_db": "DB"})
    assert "target_schema" in str(exc.value)


def test_substitute_sql_vars_does_not_flag_dollar_quoted_body():
    # UDF bodies use $$ ... $$ and SQL punctuation, not {ident} braces — must
    # not be mistaken for placeholders.
    sql = "AS\n$$\n  LPAD(MOD(seconds, 60), 2, '0')\n$$"
    assert substitute_sql_vars(sql, {}) == sql
