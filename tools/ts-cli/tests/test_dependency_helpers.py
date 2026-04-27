"""
test_dependency_helpers.py — unit tests for ts-dependency-manager helper functions.

These functions are defined inline in agents/claude/ts-dependency-manager/SKILL.md
and executed by Claude at runtime. The implementations are duplicated here so they
can be tested without a live ThoughtSpot instance.

If the skill's helper functions are updated, keep these definitions in sync.
"""
from __future__ import annotations

import re
import copy
import pytest


# ---------------------------------------------------------------------------
# Helpers under test — duplicated from SKILL.md
# These are the pure-Python functions Claude runs during a dependency session.
# ---------------------------------------------------------------------------

def sanitize_search_query(query_str: str, cols_to_remove: list[str]) -> str:
    """Remove [Column Name] references from search_query for columns being removed."""
    for col in cols_to_remove:
        query_str = re.sub(r"\s*\[" + re.escape(col) + r"\]\s*", " ", query_str)
    return query_str.strip()


def rename_in_search_query(query_str: str, old_name: str, new_name: str) -> str:
    """Replace [Old Name] with [New Name] in a search_query string."""
    return re.sub(r"\[" + re.escape(old_name) + r"\]", f"[{new_name}]", query_str)


def remove_columns_from_answer(answer_dict: dict, cols_to_remove: list[str]) -> dict:
    """
    Remove column references from an answer dict.
    Modifies in-place and returns the dict (caller is responsible for deepcopy).
    Handles: answer_columns, search_query, table view, chart (color/size/shape only),
    formulas that reference removed columns, and answer-level cohorts.
    """
    a = answer_dict

    # search_query — sanitize first so removed col refs don't linger
    if a.get("search_query"):
        a["search_query"] = sanitize_search_query(a["search_query"], cols_to_remove)

    # answer_columns[]
    a["answer_columns"] = [
        c for c in a.get("answer_columns", [])
        if c.get("name") not in cols_to_remove
    ]

    # table view: ordered_column_ids and table_columns
    tbl = a.get("table", {})
    if tbl.get("ordered_column_ids"):
        tbl["ordered_column_ids"] = [
            c for c in tbl["ordered_column_ids"] if c not in cols_to_remove
        ]
    tbl["table_columns"] = [
        c for c in tbl.get("table_columns", [])
        if c.get("column_id") not in cols_to_remove
    ]

    # chart view: chart_columns and axis_configs
    # Only strip color/size/shape bindings — x/y axis removal requires removing
    # the entire chart visualization (REMOVE_CHART path, handled in Step 6).
    chart = a.get("chart", {})
    chart["chart_columns"] = [
        c for c in chart.get("chart_columns", [])
        if c.get("column_id") not in cols_to_remove
    ]
    for axis in chart.get("axis_configs", []):
        for key in ("color", "size", "shape"):  # x/y excluded — see REMOVE_CHART path
            if key in axis and isinstance(axis[key], list):
                axis[key] = [v for v in axis[key] if v not in cols_to_remove]

    # formulas that reference the removed column
    formula_ids_to_remove = {
        f["id"] for f in a.get("formulas", [])
        if any(col in f.get("expr", "") for col in cols_to_remove)
    }
    if formula_ids_to_remove:
        formula_names = {
            f["name"] for f in a.get("formulas", []) if f["id"] in formula_ids_to_remove
        }
        a["formulas"] = [f for f in a.get("formulas", []) if f["id"] not in formula_ids_to_remove]
        a["answer_columns"] = [
            c for c in a.get("answer_columns", [])
            if c.get("formula_id") not in formula_ids_to_remove
            and c.get("name") not in formula_names
        ]

    # answer-level cohorts (sets) whose anchor_column_id is being removed
    set_names_to_remove = {
        c["name"] for c in a.get("cohorts", [])
        if c.get("config", {}).get("anchor_column_id") in cols_to_remove
    }
    if set_names_to_remove:
        a["cohorts"] = [c for c in a.get("cohorts", []) if c["name"] not in set_names_to_remove]
        a["answer_columns"] = [
            c for c in a.get("answer_columns", []) if c.get("name") not in set_names_to_remove
        ]
        if a.get("search_query"):
            a["search_query"] = sanitize_search_query(a["search_query"], list(set_names_to_remove))

    return a


def rename_column_in_answer(answer_section: dict, old_name: str, new_name: str) -> dict:
    """
    Rename a column in an Answer TML section (answer_columns + search_query).
    Returns a modified copy.
    """
    section = copy.deepcopy(answer_section)

    for col in section.get("answer_columns", []):
        if col.get("name") == old_name:
            col["name"] = new_name
        if col.get("column_id") == old_name:
            col["column_id"] = new_name

    if "search_query" in section:
        section["search_query"] = rename_in_search_query(
            section["search_query"], old_name, new_name
        )

    return section


def remove_columns_from_view(view_section: dict, cols_to_remove: list[str]) -> dict:
    """
    Remove columns from a View TML section.
    Removes view_columns entries, sanitizes search_query, and drops joins that
    reference removed columns.
    Returns a modified copy.
    """
    section = copy.deepcopy(view_section)

    # Remove from view_columns[]
    section["view_columns"] = [
        c for c in section.get("view_columns", [])
        if c.get("name") not in cols_to_remove
        and c.get("column_id") not in cols_to_remove
    ]

    # Sanitize search_query
    if "search_query" in section:
        section["search_query"] = sanitize_search_query(
            section["search_query"], cols_to_remove
        )

    # Drop joins whose 'on' expression references a removed column
    section["joins"] = [
        j for j in section.get("joins", [])
        if not any(col in j.get("on", "") for col in cols_to_remove)
    ]

    return section


def rename_column_in_view(view_section: dict, old_name: str, new_name: str) -> dict:
    """
    Rename a column in a View TML section.
    Returns a modified copy.
    """
    section = copy.deepcopy(view_section)

    for col in section.get("view_columns", []):
        if col.get("name") == old_name:
            col["name"] = new_name
        if col.get("column_id") == old_name:
            col["column_id"] = new_name

    if "search_query" in section:
        section["search_query"] = rename_in_search_query(
            section["search_query"], old_name, new_name
        )

    return section


def remove_model_joins(model_section: dict, cols_to_remove: list[str]) -> tuple[dict, list[str]]:
    """
    Remove joins from a Model TML that reference columns being deleted.
    Returns (modified_section, list_of_removed_join_names).
    """
    section = copy.deepcopy(model_section)
    removed = []

    for tbl in section.get("model_tables", []):
        before = tbl.get("joins_with", [])
        after = [
            j for j in before
            if not any(col in j.get("on", "") for col in cols_to_remove)
        ]
        dropped = [j.get("name", "unnamed") for j in before if j not in after]
        removed.extend(dropped)
        tbl["joins_with"] = after

    return section, removed


# ---------------------------------------------------------------------------
# sanitize_search_query
# ---------------------------------------------------------------------------

class TestSanitizeSearchQuery:
    def test_removes_single_column(self):
        result = sanitize_search_query("[Revenue] by [Region]", ["Revenue"])
        assert result == "by [Region]"

    def test_removes_multiple_columns(self):
        result = sanitize_search_query("[Revenue] [Cost] by [Date]", ["Revenue", "Cost"])
        assert result == "by [Date]"

    def test_leaves_unrelated_columns(self):
        result = sanitize_search_query("[Revenue] by [Region]", ["Cost"])
        assert result == "[Revenue] by [Region]"

    def test_handles_extra_whitespace(self):
        result = sanitize_search_query("  [Revenue]  by  [Region]  ", ["Revenue"])
        assert "[Revenue]" not in result
        assert "[Region]" in result

    def test_empty_query(self):
        assert sanitize_search_query("", ["Revenue"]) == ""

    def test_column_not_in_query(self):
        result = sanitize_search_query("[Revenue] by [Region]", ["NoSuchCol"])
        assert result == "[Revenue] by [Region]"

    def test_special_regex_chars_in_column_name(self):
        # Column names with dots, parens, etc. must be escaped
        result = sanitize_search_query("[Revenue (USD)] by [Region]", ["Revenue (USD)"])
        assert "[Revenue (USD)]" not in result
        assert "[Region]" in result


# ---------------------------------------------------------------------------
# rename_in_search_query
# ---------------------------------------------------------------------------

class TestRenameInSearchQuery:
    def test_basic_rename(self):
        result = rename_in_search_query("[Revenue] by [Region]", "Revenue", "Net Revenue")
        assert result == "[Net Revenue] by [Region]"

    def test_renames_all_occurrences(self):
        result = rename_in_search_query("[Revenue] [Revenue] by [Date]", "Revenue", "Net Revenue")
        assert result.count("[Net Revenue]") == 2

    def test_leaves_unrelated_columns(self):
        result = rename_in_search_query("[Revenue] by [Region]", "Cost", "Net Cost")
        assert result == "[Revenue] by [Region]"

    def test_special_chars_in_old_name(self):
        result = rename_in_search_query("[Revenue (USD)]", "Revenue (USD)", "Revenue USD")
        assert result == "[Revenue USD]"


# ---------------------------------------------------------------------------
# remove_columns_from_answer
# ---------------------------------------------------------------------------

class TestRemoveColumnsFromAnswer:
    def _sample_answer(self):
        return {
            "answer_columns": [
                {"name": "Revenue", "column_id": "Revenue"},
                {"name": "Cost", "column_id": "Cost"},
                {"name": "Region", "column_id": "Region"},
            ],
            "search_query": "[Revenue] [Cost] by [Region]",
        }

    def test_removes_column_from_list(self):
        result = remove_columns_from_answer(self._sample_answer(), ["Revenue"])
        names = [c["name"] for c in result["answer_columns"]]
        assert "Revenue" not in names
        assert "Cost" in names
        assert "Region" in names

    def test_sanitizes_search_query(self):
        result = remove_columns_from_answer(self._sample_answer(), ["Revenue"])
        assert "[Revenue]" not in result["search_query"]
        assert "[Region]" in result["search_query"]

    def test_removes_multiple_columns(self):
        result = remove_columns_from_answer(self._sample_answer(), ["Revenue", "Cost"])
        names = [c["name"] for c in result["answer_columns"]]
        assert "Revenue" not in names
        assert "Cost" not in names

    def test_mutates_in_place(self):
        # New implementation mutates the dict in-place — caller must deepcopy before calling
        original = self._sample_answer()
        result = remove_columns_from_answer(original, ["Revenue"])
        assert result is original  # same object
        assert len(original["answer_columns"]) == 2  # mutated

    def test_no_search_query_key(self):
        section = {"answer_columns": [{"name": "Revenue", "column_id": "Revenue"}]}
        result = remove_columns_from_answer(section, ["Revenue"])
        assert "search_query" not in result  # not added if absent

    def test_chart_strips_color_binding(self):
        section = {
            "answer_columns": [{"name": "Region", "column_id": "Region"}],
            "chart": {
                "chart_columns": [
                    {"column_id": "Revenue", "type": "MEASURE"},
                    {"column_id": "Region", "type": "ATTRIBUTE"},
                ],
                "axis_configs": [
                    {"x": ["Date"], "y": ["Revenue"], "color": ["Region"]},
                ],
            },
        }
        result = remove_columns_from_answer(section, ["Region"])
        assert {"column_id": "Region", "type": "ATTRIBUTE"} not in result["chart"]["chart_columns"]
        assert result["chart"]["axis_configs"][0]["color"] == []

    def test_chart_does_not_strip_x_y_axis(self):
        # x/y axis removal requires REMOVE_CHART path — this function leaves them intact
        section = {
            "answer_columns": [{"name": "Revenue"}],
            "chart": {
                "chart_columns": [{"column_id": "Revenue"}],
                "axis_configs": [{"x": ["Date"], "y": ["Revenue"]}],
            },
        }
        result = remove_columns_from_answer(section, ["Revenue"])
        # Revenue removed from chart_columns and answer_columns, but NOT from y axis
        chart_col_ids = [c["column_id"] for c in result["chart"]["chart_columns"]]
        assert "Revenue" not in chart_col_ids
        assert result["chart"]["axis_configs"][0]["y"] == ["Revenue"]  # x/y untouched

    def test_strips_table_columns(self):
        section = {
            "answer_columns": [],
            "table": {
                "ordered_column_ids": ["Revenue", "Region"],
                "table_columns": [
                    {"column_id": "Revenue"},
                    {"column_id": "Region"},
                ],
            },
        }
        result = remove_columns_from_answer(section, ["Revenue"])
        assert "Revenue" not in result["table"]["ordered_column_ids"]
        assert "Region" in result["table"]["ordered_column_ids"]
        col_ids = [c["column_id"] for c in result["table"]["table_columns"]]
        assert "Revenue" not in col_ids

    def test_strips_answer_level_cohort(self):
        section = {
            "answer_columns": [
                {"name": "Revenue"},
                {"name": "Zipcode Ranges"},  # cohort display col
            ],
            "search_query": "[Revenue] [Zipcode Ranges]",
            "cohorts": [
                {
                    "name": "Zipcode Ranges",
                    "config": {"anchor_column_id": "Customer Zipcode"},
                },
            ],
        }
        result = remove_columns_from_answer(section, ["Customer Zipcode"])
        assert result["cohorts"] == []
        names = [c["name"] for c in result["answer_columns"]]
        assert "Zipcode Ranges" not in names
        assert "[Zipcode Ranges]" not in result["search_query"]

    def test_cohort_not_removed_when_anchor_not_in_cols_to_remove(self):
        section = {
            "answer_columns": [{"name": "Revenue"}, {"name": "Zipcode Ranges"}],
            "cohorts": [
                {
                    "name": "Zipcode Ranges",
                    "config": {"anchor_column_id": "Customer Zipcode"},
                },
            ],
        }
        result = remove_columns_from_answer(section, ["Revenue"])
        assert len(result["cohorts"]) == 1  # cohort unchanged
        assert "Zipcode Ranges" in [c["name"] for c in result["answer_columns"]]


# ---------------------------------------------------------------------------
# rename_column_in_answer
# ---------------------------------------------------------------------------

class TestRenameColumnInAnswer:
    def _sample_answer(self):
        return {
            "answer_columns": [
                {"name": "Revenue", "column_id": "Revenue"},
                {"name": "Region", "column_id": "Region"},
            ],
            "search_query": "[Revenue] by [Region]",
        }

    def test_renames_in_columns_list(self):
        result = rename_column_in_answer(self._sample_answer(), "Revenue", "Net Revenue")
        names = [c["name"] for c in result["answer_columns"]]
        assert "Net Revenue" in names
        assert "Revenue" not in names

    def test_renames_in_search_query(self):
        result = rename_column_in_answer(self._sample_answer(), "Revenue", "Net Revenue")
        assert "[Net Revenue]" in result["search_query"]
        assert "[Revenue]" not in result["search_query"]

    def test_leaves_other_columns_unchanged(self):
        result = rename_column_in_answer(self._sample_answer(), "Revenue", "Net Revenue")
        names = [c["name"] for c in result["answer_columns"]]
        assert "Region" in names

    def test_does_not_mutate_input(self):
        original = self._sample_answer()
        rename_column_in_answer(original, "Revenue", "Net Revenue")
        assert original["answer_columns"][0]["name"] == "Revenue"


# ---------------------------------------------------------------------------
# remove_columns_from_view
# ---------------------------------------------------------------------------

class TestRemoveColumnsFromView:
    def _sample_view(self):
        return {
            "view_columns": [
                {"name": "Revenue", "column_id": "Orders_1::Revenue"},
                {"name": "Region", "column_id": "Region_1::Region"},
            ],
            "search_query": "[Revenue] by [Region]",
            "joins": [
                {"name": "Orders_Region_join", "on": "[Revenue] = [Orders_1::Revenue]"},
                {"name": "Safe_join", "on": "[Region] = [Region_1::Region]"},
            ],
        }

    def test_removes_column_from_view_columns(self):
        result = remove_columns_from_view(self._sample_view(), ["Revenue"])
        names = [c["name"] for c in result["view_columns"]]
        assert "Revenue" not in names
        assert "Region" in names

    def test_sanitizes_search_query(self):
        result = remove_columns_from_view(self._sample_view(), ["Revenue"])
        assert "[Revenue]" not in result["search_query"]

    def test_drops_join_referencing_removed_column(self):
        result = remove_columns_from_view(self._sample_view(), ["Revenue"])
        join_names = [j["name"] for j in result["joins"]]
        assert "Orders_Region_join" not in join_names  # references Revenue
        assert "Safe_join" in join_names               # does not reference Revenue

    def test_keeps_joins_not_referencing_removed_column(self):
        result = remove_columns_from_view(self._sample_view(), ["Revenue"])
        assert len(result["joins"]) == 1

    def test_does_not_mutate_input(self):
        original = self._sample_view()
        remove_columns_from_view(original, ["Revenue"])
        assert len(original["view_columns"]) == 2
        assert len(original["joins"]) == 2


# ---------------------------------------------------------------------------
# remove_model_joins
# ---------------------------------------------------------------------------

class TestRemoveModelJoins:
    def _sample_model(self):
        return {
            "model_tables": [
                {
                    "name": "Orders",
                    "joins_with": [
                        {"name": "Orders_Region", "on": "[Revenue] = [Orders::Revenue]"},
                        {"name": "Orders_Date", "on": "[Date] = [Orders::Date]"},
                    ],
                },
                {
                    "name": "Region",
                    "joins_with": [
                        {"name": "Region_Country", "on": "[Country] = [Region::Country]"},
                    ],
                },
            ]
        }

    def test_removes_join_referencing_deleted_column(self):
        result, removed = remove_model_joins(self._sample_model(), ["Revenue"])
        joins = result["model_tables"][0]["joins_with"]
        join_names = [j["name"] for j in joins]
        assert "Orders_Region" not in join_names
        assert "Orders_Date" in join_names

    def test_returns_list_of_removed_join_names(self):
        _, removed = remove_model_joins(self._sample_model(), ["Revenue"])
        assert "Orders_Region" in removed

    def test_unaffected_tables_unchanged(self):
        result, removed = remove_model_joins(self._sample_model(), ["Revenue"])
        region_joins = result["model_tables"][1]["joins_with"]
        assert len(region_joins) == 1

    def test_no_joins_removed_when_column_not_referenced(self):
        result, removed = remove_model_joins(self._sample_model(), ["NoSuchCol"])
        assert removed == []
        assert len(result["model_tables"][0]["joins_with"]) == 2

    def test_does_not_mutate_input(self):
        original = self._sample_model()
        remove_model_joins(original, ["Revenue"])
        assert len(original["model_tables"][0]["joins_with"]) == 2


# ---------------------------------------------------------------------------
# classify_chart_role — duplicated from SKILL.md Step 4
# ---------------------------------------------------------------------------

def classify_chart_role(answer_section: dict, col_name: str) -> str:
    """
    Returns: 'X_AXIS' | 'Y_AXIS' | 'COLOR_BINDING' | 'NOT_VISUALISED' | 'NOT_IN_CHART'
    - X_AXIS / Y_AXIS   → REMOVE_CHART required (cannot auto-fix)
    - COLOR_BINDING     → REMOVE_COLOR_BINDING (strip binding; chart stays intact)
    - NOT_VISUALISED    → REMOVE_COLUMN (in chart_columns[] but not mapped to any axis)
    - NOT_IN_CHART      → REMOVE_COLUMN (only in answer_columns/table, or not present)
    """
    chart = answer_section.get("chart", {})
    in_chart = any(
        c.get("column_id") == col_name for c in chart.get("chart_columns", [])
    )
    if not in_chart:
        return "NOT_IN_CHART"
    for axis in chart.get("axis_configs", []):
        if col_name in axis.get("x", []):
            return "X_AXIS"
        if col_name in axis.get("y", []):
            return "Y_AXIS"
        for role in ("color", "size", "shape"):
            if col_name in axis.get(role, []):
                return "COLOR_BINDING"
    return "NOT_VISUALISED"


class TestClassifyChartRole:
    def _answer_with_chart(self, chart_columns, axis_configs):
        return {
            "chart": {
                "chart_columns": chart_columns,
                "axis_configs": axis_configs,
            }
        }

    def test_not_in_chart(self):
        # Column is not in chart_columns at all
        answer = self._answer_with_chart(
            chart_columns=[{"column_id": "Revenue"}],
            axis_configs=[{"x": ["Date"], "y": ["Revenue"]}],
        )
        assert classify_chart_role(answer, "Region") == "NOT_IN_CHART"

    def test_x_axis(self):
        answer = self._answer_with_chart(
            chart_columns=[{"column_id": "Date"}],
            axis_configs=[{"x": ["Date"], "y": ["Revenue"]}],
        )
        assert classify_chart_role(answer, "Date") == "X_AXIS"

    def test_y_axis(self):
        answer = self._answer_with_chart(
            chart_columns=[{"column_id": "Revenue"}],
            axis_configs=[{"x": ["Date"], "y": ["Revenue"]}],
        )
        assert classify_chart_role(answer, "Revenue") == "Y_AXIS"

    def test_color_binding(self):
        answer = self._answer_with_chart(
            chart_columns=[{"column_id": "Region"}],
            axis_configs=[{"x": ["Date"], "y": ["Revenue"], "color": ["Region"]}],
        )
        assert classify_chart_role(answer, "Region") == "COLOR_BINDING"

    def test_size_binding(self):
        answer = self._answer_with_chart(
            chart_columns=[{"column_id": "Quantity"}],
            axis_configs=[{"x": ["Date"], "y": ["Revenue"], "size": ["Quantity"]}],
        )
        assert classify_chart_role(answer, "Quantity") == "COLOR_BINDING"

    def test_shape_binding(self):
        answer = self._answer_with_chart(
            chart_columns=[{"column_id": "Category"}],
            axis_configs=[{"x": ["Date"], "y": ["Revenue"], "shape": ["Category"]}],
        )
        assert classify_chart_role(answer, "Category") == "COLOR_BINDING"

    def test_not_visualised(self):
        # Column is in chart_columns but not assigned to any axis role
        answer = self._answer_with_chart(
            chart_columns=[{"column_id": "Revenue"}, {"column_id": "Tooltip"}],
            axis_configs=[{"x": ["Date"], "y": ["Revenue"]}],
        )
        assert classify_chart_role(answer, "Tooltip") == "NOT_VISUALISED"

    def test_no_chart_key(self):
        # Answer with no chart key at all — column is not in a chart
        assert classify_chart_role({}, "Revenue") == "NOT_IN_CHART"

    def test_empty_chart(self):
        assert classify_chart_role({"chart": {}}, "Revenue") == "NOT_IN_CHART"


# ---------------------------------------------------------------------------
# rename_column_in_set — duplicated from SKILL.md Step 9b
# ---------------------------------------------------------------------------

def rename_column_in_set(set_tml: dict, old_name: str, new_name: str) -> dict:
    """Update all column references in a reusable set (cohort) TML dict.
    Returns a deep-copied modified version; does not mutate the input."""
    s = copy.deepcopy(set_tml)
    cohort = s.get("cohort", {})
    config = cohort.get("config", {})

    # anchor_column_id — the primary column reference
    if config.get("anchor_column_id") == old_name:
        config["anchor_column_id"] = new_name

    # return_column_id (COLUMN_BASED query sets)
    if config.get("return_column_id") == old_name:
        config["return_column_id"] = new_name

    # group conditions (GROUP_BASED sets)
    for group in config.get("groups", []):
        for cond in group.get("conditions", []):
            if cond.get("column_name") == old_name:
                cond["column_name"] = new_name

    # pass_thru_filter column lists (COLUMN_BASED sets)
    ptf = config.get("pass_thru_filter", {})
    ptf["include_column_ids"] = [
        new_name if c == old_name else c for c in ptf.get("include_column_ids", [])
    ]
    ptf["exclude_column_ids"] = [
        new_name if c == old_name else c for c in ptf.get("exclude_column_ids", [])
    ]

    # embedded answer (COLUMN_BASED query sets only)
    if "answer" in cohort:
        cohort["answer"] = rename_column_in_answer(cohort["answer"], old_name, new_name)

    return s


class TestRenameColumnInSet:
    def _bin_based_set(self):
        return {
            "cohort": {
                "name": "Zipcode Bins",
                "config": {
                    "anchor_column_id": "Customer Zipcode",
                    "type": "BIN_BASED",
                    "bins": [
                        {"name": "Low", "low": "10000", "high": "29999"},
                        {"name": "High", "low": "30000", "high": "99999"},
                    ],
                },
            }
        }

    def _group_based_set(self):
        return {
            "cohort": {
                "name": "Zipcode Groups",
                "config": {
                    "anchor_column_id": "Customer Zipcode",
                    "type": "GROUP_BASED",
                    "groups": [
                        {
                            "name": "Northeast",
                            "conditions": [
                                {"column_name": "Customer Zipcode", "operator": "STARTS_WITH", "value": "01"},
                            ],
                        },
                    ],
                },
            }
        }

    def _column_based_set(self):
        return {
            "cohort": {
                "name": "Zipcode Set",
                "config": {
                    "anchor_column_id": "Customer Zipcode",
                    "return_column_id": "Customer Zipcode",
                    "type": "COLUMN_BASED",
                    "pass_thru_filter": {
                        "include_column_ids": ["Customer Zipcode", "State"],
                        "exclude_column_ids": ["Customer Zipcode"],
                    },
                },
                "answer": {
                    "answer_columns": [{"name": "Customer Zipcode"}],
                    "search_query": "[Customer Zipcode]",
                },
            }
        }

    def test_bin_based_renames_anchor_column_id(self):
        result = rename_column_in_set(
            self._bin_based_set(), "Customer Zipcode", "Postal Code"
        )
        assert result["cohort"]["config"]["anchor_column_id"] == "Postal Code"

    def test_bin_based_does_not_mutate_input(self):
        original = self._bin_based_set()
        rename_column_in_set(original, "Customer Zipcode", "Postal Code")
        assert original["cohort"]["config"]["anchor_column_id"] == "Customer Zipcode"

    def test_group_based_renames_condition_column_name(self):
        result = rename_column_in_set(
            self._group_based_set(), "Customer Zipcode", "Postal Code"
        )
        cond = result["cohort"]["config"]["groups"][0]["conditions"][0]
        assert cond["column_name"] == "Postal Code"

    def test_group_based_renames_anchor_column_id(self):
        result = rename_column_in_set(
            self._group_based_set(), "Customer Zipcode", "Postal Code"
        )
        assert result["cohort"]["config"]["anchor_column_id"] == "Postal Code"

    def test_column_based_renames_return_column_id(self):
        result = rename_column_in_set(
            self._column_based_set(), "Customer Zipcode", "Postal Code"
        )
        assert result["cohort"]["config"]["return_column_id"] == "Postal Code"

    def test_column_based_renames_pass_thru_include(self):
        result = rename_column_in_set(
            self._column_based_set(), "Customer Zipcode", "Postal Code"
        )
        ptf = result["cohort"]["config"]["pass_thru_filter"]
        assert "Postal Code" in ptf["include_column_ids"]
        assert "Customer Zipcode" not in ptf["include_column_ids"]
        assert "State" in ptf["include_column_ids"]  # unrelated entry preserved

    def test_column_based_renames_pass_thru_exclude(self):
        result = rename_column_in_set(
            self._column_based_set(), "Customer Zipcode", "Postal Code"
        )
        ptf = result["cohort"]["config"]["pass_thru_filter"]
        assert "Postal Code" in ptf["exclude_column_ids"]
        assert "Customer Zipcode" not in ptf["exclude_column_ids"]

    def test_column_based_renames_embedded_answer(self):
        result = rename_column_in_set(
            self._column_based_set(), "Customer Zipcode", "Postal Code"
        )
        answer = result["cohort"]["answer"]
        names = [c["name"] for c in answer["answer_columns"]]
        assert "Postal Code" in names
        assert "Customer Zipcode" not in names
        assert "[Postal Code]" in answer["search_query"]

    def test_unrelated_name_unchanged(self):
        result = rename_column_in_set(
            self._bin_based_set(), "NonExistentCol", "New Name"
        )
        assert result["cohort"]["config"]["anchor_column_id"] == "Customer Zipcode"


# ---------------------------------------------------------------------------
# diff_scan — duplicated from SKILL.md Step 5 (re-scan action)
# ---------------------------------------------------------------------------

def diff_scan(previous_plan: dict, new_dependents: list[dict]) -> tuple[list, list]:
    """Compare a fresh scan against a saved plan. Returns (resolved, added)."""
    prev_guids = {d["guid"] for d in previous_plan["dependents"]}
    curr_guids = {d["guid"] for d in new_dependents}
    resolved = [d for d in previous_plan["dependents"] if d["guid"] not in curr_guids]
    added    = [d for d in new_dependents              if d["guid"] not in prev_guids]
    return resolved, added


class TestDiffScan:
    def _plan(self, guids):
        return {"dependents": [{"guid": g, "name": f"Object {g}"} for g in guids]}

    def _deps(self, guids):
        return [{"guid": g, "name": f"Object {g}"} for g in guids]

    def test_no_change(self):
        plan = self._plan(["aaa", "bbb"])
        resolved, added = diff_scan(plan, self._deps(["aaa", "bbb"]))
        assert resolved == []
        assert added == []

    def test_resolved_item(self):
        plan = self._plan(["aaa", "bbb"])
        resolved, added = diff_scan(plan, self._deps(["bbb"]))
        assert len(resolved) == 1
        assert resolved[0]["guid"] == "aaa"
        assert added == []

    def test_added_item(self):
        plan = self._plan(["aaa"])
        resolved, added = diff_scan(plan, self._deps(["aaa", "ccc"]))
        assert resolved == []
        assert len(added) == 1
        assert added[0]["guid"] == "ccc"

    def test_resolved_and_added(self):
        plan = self._plan(["aaa", "bbb"])
        resolved, added = diff_scan(plan, self._deps(["bbb", "ccc"]))
        assert len(resolved) == 1
        assert resolved[0]["guid"] == "aaa"
        assert len(added) == 1
        assert added[0]["guid"] == "ccc"

    def test_all_resolved(self):
        plan = self._plan(["aaa", "bbb"])
        resolved, added = diff_scan(plan, [])
        assert len(resolved) == 2
        assert added == []

    def test_empty_plan(self):
        plan = self._plan([])
        resolved, added = diff_scan(plan, self._deps(["aaa"]))
        assert resolved == []
        assert len(added) == 1

    def test_returns_full_dep_objects(self):
        # resolved / added should return the full dep dict, not just guids
        plan = self._plan(["aaa"])
        resolved, added = diff_scan(plan, self._deps(["bbb"]))
        assert resolved[0]["name"] == "Object aaa"
        assert added[0]["name"] == "Object bbb"
