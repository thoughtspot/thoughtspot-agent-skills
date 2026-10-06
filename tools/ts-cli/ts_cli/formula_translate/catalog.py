"""ThoughtSpot formula function names the output guard accepts (review item 2).

``CATALOG`` is the set ``tools/validate/check_formula_catalog.py`` parses out of
``agents/shared/schemas/thoughtspot-formula-patterns.md`` (its first-column table rows),
vendored here so the installed CLI does not need the repo on disk.
``tests/test_formula_translate.py::TestCatalog`` fails if it drifts from the document.

``EXTRAS`` are functions documented elsewhere in that file (prose and examples the table
parser does not see) or in a mapping doc that records them live-verified — each with its
source. ``NONEXISTENT`` is the document's strikethrough list. Anything a translator emits
that is in neither set makes the result NEEDS_REVIEW: an unknown name is not evidence of a
function.
"""
from __future__ import annotations

CATALOG = frozenset({
    "abs", "add_days", "add_minutes", "add_months", "add_seconds", "add_weeks",
    "add_years", "average", "average_if", "between", "ceil", "concat", "contains", "count",
    "count_if", "cumulative_average", "cumulative_max", "cumulative_min", "cumulative_sum",
    "date", "day", "day_number_of_quarter", "day_number_of_week", "day_number_of_year",
    "day_of_week", "diff_days", "diff_hours", "diff_minutes", "diff_months",
    "diff_quarters", "diff_time", "diff_weeks", "diff_years", "floor", "greatest",
    "hour_of_day", "ifnull", "in", "is_weekend", "isnull", "least", "left", "ln",
    "log10", "log2", "max", "max_if", "median", "min", "min_if", "mod", "month",
    "month_number", "month_number_of_quarter", "moving_average", "moving_max",
    "moving_min", "moving_sum", "not", "now", "pow", "quarter_number", "right",
    "round", "safe_divide", "sqrt", "start_of_hour", "start_of_min", "start_of_month",
    "start_of_quarter", "start_of_week", "start_of_year", "stddev", "stddev_if", "strlen",
    "strpos", "substr", "sum", "sum_if", "time", "to_double", "to_integer", "to_string",
    "today", "ts_email_domain", "ts_groups", "ts_groups_int", "ts_org", "ts_username",
    "unique count", "unique_count_if", "variance", "variance_if", "week_number_of_month",
    "week_number_of_quarter", "week_number_of_year", "year", "year_name",
})

NONEXISTENT = frozenset({
    "date_trunc", "day_number_of_month", "ends_with", "isnotnull", "lower", "ltrim", "nullif",
    "replace",
    "rtrim", "starts_with", "trim", "upper",
})

EXTRAS = {
    "if": "formula-patterns: if / then / else",
    "to_date": "formula-patterns: date literals, to_date ( '2024-05-01' , 'yyyy-MM-dd' )",
    "ts_var": "formula-patterns: variables",
    "group_aggregate": "formula-patterns: group_aggregate / query_groups",
    "query_groups": "formula-patterns: group_aggregate / query_groups",
    "query_filters": "formula-patterns: group_aggregate / query_filters",
    "rank": "formula-patterns: rank",
    "rank_percentile": "formula-patterns: rank_percentile",
    "last_value": "formula-patterns: semi-additive last_value",
    "first_value": "formula-patterns: first_value",
    "exp": "qlik mapping N09: exp() live-confirmed",
    "sin": "tableau mapping: trigonometry (degrees)",
    "cos": "tableau mapping: trigonometry (degrees)",
    "tan": "tableau mapping: trigonometry (degrees)",
    "asin": "tableau mapping: trigonometry (degrees)",
    "acos": "tableau mapping: trigonometry (degrees)",
    "atan": "tableau mapping: trigonometry (degrees)",
    "atan2": "tableau mapping: trigonometry (degrees)",
    "sql_string_op": "formula-patterns: SQL pass-through",
    "sql_int_op": "formula-patterns: SQL pass-through",
    "sql_double_op": "formula-patterns: SQL pass-through; live-accepted 2026-10-06 (OI-5)",
    "sql_bool_op": "formula-patterns: SQL pass-through; live-accepted 2026-10-06 (OI-4)",
    "sql_date_op": "formula-patterns: SQL pass-through",
    "sql_date_time_op": "formula-patterns: SQL pass-through",
    "sql_string_aggregate_op": "formula-patterns: SQL pass-through",
    "sql_int_aggregate_op": "formula-patterns; live-accepted 2026-10-06 (OI-5)",
    "sql_double_aggregate_op": "tableau mapping; live-accepted 2026-10-06 (OI-5)",
    "sql_date_time_aggregate_op": "formula-patterns; live-accepted 2026-10-06 (BL-335)",
    "sql_date_aggregate_op": "formula-patterns; live-accepted 2026-10-06 (BL-335)",
    "sql_bool_aggregate_op": "formula-patterns; live-accepted 2026-10-06 (BL-335)",
}
# NOT accepted although the shared references list it: rejected live 2026-10-06 (OI-5).
REJECTED_LIVE = frozenset({"sql_number_aggregate_op", "sql_number_op",  # BL-335
                           # nullif is struck through in the reference (NONEXISTENT); its
                           # underscore spelling was rejected in the same probe (§7, BL-339).
                           "null_if"})

# Prefixes of documented function families (cumulative_*, moving_*, group_*).
FAMILY_PREFIXES = ("cumulative_", "moving_", "group_")


def is_known(name: str) -> bool:
    """True if ``name`` (case-sensitive: ThoughtSpot output is lower case) is a known
    ThoughtSpot formula function."""
    if name in REJECTED_LIVE or name in NONEXISTENT:
        return False
    return name in CATALOG or name in EXTRAS or name.startswith(FAMILY_PREFIXES)
