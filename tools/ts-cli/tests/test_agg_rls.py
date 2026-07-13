"""Tests for ts_cli.aggregate.rls — RLS extraction, grain-conflict detection,
and propagation onto an aggregate table (Task 22, pure engine only).
"""
from __future__ import annotations

import pytest
import yaml

from ts_cli.aggregate.rls import (
    add_rls_columns_to_candidate,
    candidate_rls_conflict,
    extract_rls,
    propagate_rls,
    rls_filter_columns,
)
from ts_cli.tml_common import dump_tml_yaml
from ts_cli.tml_lint import lint_tml

# ── fixtures ────────────────────────────────────────────────────────────────

_NESTED_TABLE_TML = {
    "table": {
        "name": "Source Table",
        "rls_rules": {
            "table_paths": [
                {"id": "T_1", "table": "Source Table", "column": ["ZIPCODE"]},
            ],
            "rules": [
                {"name": "geo_rule", "expr": "[T_1::ZIPCODE] = ts_groups_int"},
            ],
        },
    }
}

_FLAT_TABLE_TML = {
    "table": {
        "name": "Flat Table",
        "rls_rules": [
            {"name": "flat_rule", "expr": "[Flat Table::REGION] = ts_groups"},
        ],
    }
}

_MULTI_RULE_MULTI_COL_TABLE_TML = {
    "table": {
        "name": "Multi Table",
        "rls_rules": {
            "table_paths": [
                {"id": "T_1", "table": "Multi Table", "column": ["ZIPCODE", "STATE"]},
            ],
            "rules": [
                {"name": "geo_rule", "expr": "[T_1::ZIPCODE] = ts_groups_int"},
                {"name": "state_rule", "expr": "[T_1::STATE] = ts_var('state')"},
            ],
        },
    }
}

_NO_RLS_TABLE_TML = {"table": {"name": "Plain Table"}}

_SECOND_TABLE_TML = {
    "table": {
        "name": "Second Table",
        "rls_rules": {
            "table_paths": [
                {"id": "T_2", "table": "Second Table", "column": ["REGION"]},
            ],
            "rules": [
                {"name": "region_rule", "expr": "[T_2::REGION] = ts_groups"},
            ],
        },
    }
}

_MODEL_TML = {
    "model": {
        "name": "Customer 360",
        "columns": [
            {"name": "Customer Zipcode", "column_id": "Source Table::ZIPCODE",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "State", "column_id": "Source Table::STATE",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Region", "column_id": "Second Table::REGION",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Order Date", "column_id": "Source Table::ORDER_DT",
             "data_type": "DATE", "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Sales", "column_id": "Source Table::AMOUNT",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        ],
    }
}


# ── extract_rls ───────────────────────────────────────────────────────────

class TestExtractRls:
    def test_nested_shape(self):
        rules = extract_rls({"Source Table": _NESTED_TABLE_TML})
        assert len(rules) == 1
        r = rules[0]
        assert r["table"] == "Source Table"
        assert r["name"] == "geo_rule"
        assert r["expr"] == "[T_1::ZIPCODE] = ts_groups_int"
        assert r["columns"] == ["ZIPCODE"]
        assert r["path_ids"]["T_1"] == ("Source Table", ["ZIPCODE"])

    def test_flat_shape(self):
        rules = extract_rls({"Flat Table": _FLAT_TABLE_TML})
        assert len(rules) == 1
        r = rules[0]
        assert r["table"] == "Flat Table"
        assert r["name"] == "flat_rule"
        assert r["columns"] == ["REGION"]
        # flat shape has no table_paths — resolved via the own-table fallback
        assert r["path_ids"]["Flat Table"][0] == "Flat Table"

    def test_multi_rule_multi_column_path(self):
        rules = extract_rls({"Multi Table": _MULTI_RULE_MULTI_COL_TABLE_TML})
        assert len(rules) == 2
        by_name = {r["name"]: r for r in rules}
        assert by_name["geo_rule"]["columns"] == ["ZIPCODE"]
        assert by_name["state_rule"]["columns"] == ["STATE"]
        # both rules share the same resolved path
        assert by_name["geo_rule"]["path_ids"]["T_1"] == ("Multi Table", ["ZIPCODE", "STATE"])

    def test_no_rls_returns_empty(self):
        assert extract_rls({"Plain Table": _NO_RLS_TABLE_TML}) == []

    def test_no_tables_returns_empty(self):
        assert extract_rls({}) == []

    def test_multiple_tables_combined(self):
        rules = extract_rls({
            "Source Table": _NESTED_TABLE_TML,
            "Second Table": _SECOND_TABLE_TML,
        })
        tables = {r["table"] for r in rules}
        assert tables == {"Source Table", "Second Table"}


# ── rls_filter_columns ──────────────────────────────────────────────────────

class TestRlsFilterColumns:
    def test_single_ref(self):
        rules = extract_rls({"Source Table": _NESTED_TABLE_TML})
        assert rls_filter_columns(rules) == {("Source Table", "ZIPCODE")}

    def test_multi_ref_expr_across_rules(self):
        rules = extract_rls({"Multi Table": _MULTI_RULE_MULTI_COL_TABLE_TML})
        assert rls_filter_columns(rules) == {
            ("Multi Table", "ZIPCODE"),
            ("Multi Table", "STATE"),
        }

    def test_multi_table(self):
        rules = extract_rls({
            "Source Table": _NESTED_TABLE_TML,
            "Second Table": _SECOND_TABLE_TML,
        })
        assert rls_filter_columns(rules) == {
            ("Source Table", "ZIPCODE"),
            ("Second Table", "REGION"),
        }

    def test_no_rules_returns_empty_set(self):
        assert rls_filter_columns([]) == set()

    def test_undeclared_path_id_surfaces_fail_closed(self):
        # SECURITY (fail-closed): a rule ref whose path_id is neither declared
        # in table_paths nor the owning table name must NOT be silently dropped
        # — it must surface (using the raw ref_id as the pseudo-table) so it
        # flows through as a required-but-unresolvable filter column.
        table_tml = {
            "table": {
                "name": "Source Table",
                "rls_rules": {
                    "table_paths": [
                        {"id": "T_1", "table": "Source Table", "column": ["ZIPCODE"]},
                    ],
                    "rules": [
                        {"name": "geo", "expr": "[T_1::ZIPCODE] = ts_groups_int"},
                        {"name": "leak", "expr": "[T_9::SECRET] = ts_groups"},
                    ],
                },
            }
        }
        rules = extract_rls({"Source Table": table_tml})
        cols = rls_filter_columns(rules)
        assert ("Source Table", "ZIPCODE") in cols
        # undeclared T_9 surfaces (raw ref_id as pseudo-table), never dropped
        assert ("T_9", "SECRET") in cols


# ── candidate_rls_conflict ──────────────────────────────────────────────────

class TestCandidateRlsConflict:
    def _rules(self):
        return extract_rls({"Source Table": _NESTED_TABLE_TML})

    def test_rls_column_in_grain_missing_empty(self):
        cand = {"dimensions": ["Customer Zipcode", "State"]}
        result = candidate_rls_conflict(cand, {}, _MODEL_TML, self._rules())
        assert result["required"] == ["Customer Zipcode"]
        assert result["present"] == ["Customer Zipcode"]
        assert result["missing"] == []

    def test_rls_column_omitted_from_grain(self):
        cand = {"dimensions": ["State"]}
        result = candidate_rls_conflict(cand, {}, _MODEL_TML, self._rules())
        assert result["required"] == ["Customer Zipcode"]
        assert result["present"] == []
        assert result["missing"] == ["Customer Zipcode"]

    def test_date_column_rls(self):
        date_table_tml = {
            "table": {
                "name": "Source Table",
                "rls_rules": {
                    "table_paths": [
                        {"id": "T_1", "table": "Source Table", "column": ["ORDER_DT"]},
                    ],
                    "rules": [
                        {"name": "date_rule", "expr": "[T_1::ORDER_DT] > ts_var('cutoff')"},
                    ],
                },
            }
        }
        rules = extract_rls({"Source Table": date_table_tml})

        cand_with_date = {"dimensions": [], "date_grains": [{"column": "Order Date", "bucket": "MONTHLY"}]}
        result = candidate_rls_conflict(cand_with_date, {}, _MODEL_TML, rules)
        assert result["missing"] == []
        assert result["present"] == ["Order Date"]

        cand_without_date = {"dimensions": ["State"]}
        result2 = candidate_rls_conflict(cand_without_date, {}, _MODEL_TML, rules)
        assert result2["missing"] == ["Order Date"]

    def test_multi_table_rls(self):
        rules = extract_rls({
            "Source Table": _NESTED_TABLE_TML,
            "Second Table": _SECOND_TABLE_TML,
        })
        cand = {"dimensions": ["Customer Zipcode"]}  # Region omitted
        result = candidate_rls_conflict(cand, {}, _MODEL_TML, rules)
        assert result["required"] == ["Customer Zipcode", "Region"]
        assert result["present"] == ["Customer Zipcode"]
        assert result["missing"] == ["Region"]

    def test_unmodeled_filter_column_falls_back_to_column_id(self):
        # RLS references a physical column the model doesn't expose at all —
        # must still surface as required/missing, not be silently dropped.
        table_tml = {
            "table": {
                "name": "Source Table",
                "rls_rules": {
                    "table_paths": [
                        {"id": "T_1", "table": "Source Table", "column": ["SECRET_COL"]},
                    ],
                    "rules": [{"name": "r", "expr": "[T_1::SECRET_COL] = ts_groups"}],
                },
            }
        }
        rules = extract_rls({"Source Table": table_tml})
        cand = {"dimensions": ["Customer Zipcode"]}
        result = candidate_rls_conflict(cand, {}, _MODEL_TML, rules)
        assert result["required"] == ["Source Table::SECRET_COL"]
        assert result["missing"] == ["Source Table::SECRET_COL"]

    def test_no_rules_no_conflict(self):
        cand = {"dimensions": []}
        result = candidate_rls_conflict(cand, {}, _MODEL_TML, [])
        assert result == {"required": [], "present": [], "missing": []}

    def test_undeclared_path_id_is_never_securable(self):
        # SECURITY (fail-closed): a candidate must never be reported securable
        # (missing == []) while an unresolvable RLS ref exists — the unresolved
        # ref surfaces in required and missing regardless of grain.
        table_tml = {
            "table": {
                "name": "Source Table",
                "rls_rules": {
                    "table_paths": [
                        {"id": "T_1", "table": "Source Table", "column": ["ZIPCODE"]},
                    ],
                    "rules": [
                        {"name": "leak", "expr": "[T_9::SECRET] = ts_groups"},
                    ],
                },
            }
        }
        rules = extract_rls({"Source Table": table_tml})
        # grain contains everything the model exposes — still not securable.
        cand = {"dimensions": ["Customer Zipcode", "State", "Region"]}
        result = candidate_rls_conflict(cand, {}, _MODEL_TML, rules)
        assert "T_9::SECRET" in result["required"]
        assert "T_9::SECRET" in result["missing"]


# ── add_rls_columns_to_candidate ────────────────────────────────────────────

class TestAddRlsColumnsToCandidate:
    def test_adds_missing_columns(self):
        cand = {"id": "cand_1", "dimensions": ["State"]}
        new_cand = add_rls_columns_to_candidate(cand, ["Customer Zipcode"])
        assert new_cand["dimensions"] == ["Customer Zipcode", "State"]

    def test_original_candidate_untouched(self):
        cand = {"id": "cand_1", "dimensions": ["State"]}
        add_rls_columns_to_candidate(cand, ["Customer Zipcode"])
        assert cand["dimensions"] == ["State"]

    def test_deterministic_no_duplicates(self):
        cand = {"id": "cand_1", "dimensions": ["State", "Customer Zipcode"]}
        new_cand = add_rls_columns_to_candidate(cand, ["Customer Zipcode", "Region"])
        assert new_cand["dimensions"] == ["Customer Zipcode", "Region", "State"]

    def test_other_keys_untouched(self):
        cand = {"id": "cand_1", "dimensions": ["State"], "measure_columns": ["Sales"]}
        new_cand = add_rls_columns_to_candidate(cand, ["Customer Zipcode"])
        assert new_cand["measure_columns"] == ["Sales"]
        assert new_cand["id"] == "cand_1"


# ── propagate_rls ────────────────────────────────────────────────────────

class TestPropagateRls:
    def test_basic_remap_preserves_ts_var(self):
        rules = extract_rls({"Source Table": _NESTED_TABLE_TML})
        out = propagate_rls(rules, "SALES_AGG", {("Source Table", "ZIPCODE"): "ZIPCODE"})

        assert out["table_paths"] == [
            {"id": "SALES_AGG_1", "table": "SALES_AGG", "column": ["ZIPCODE"]}
        ]
        assert len(out["rules"]) == 1
        assert out["rules"][0]["name"] == "geo_rule"
        assert out["rules"][0]["expr"] == "[SALES_AGG_1::ZIPCODE] = ts_groups_int"

    def test_renamed_aggregate_column(self):
        rules = extract_rls({"Source Table": _NESTED_TABLE_TML})
        out = propagate_rls(rules, "SALES_AGG", {("Source Table", "ZIPCODE"): "ZIP_CD"})
        assert out["table_paths"][0]["column"] == ["ZIP_CD"]
        assert out["rules"][0]["expr"] == "[SALES_AGG_1::ZIP_CD] = ts_groups_int"

    def test_multi_rule_merges_into_one_path(self):
        rules = extract_rls({"Multi Table": _MULTI_RULE_MULTI_COL_TABLE_TML})
        out = propagate_rls(rules, "MULTI_AGG",
                            {("Multi Table", "ZIPCODE"): "ZIPCODE",
                             ("Multi Table", "STATE"): "STATE"})
        assert len(out["table_paths"]) == 1
        assert out["table_paths"][0]["column"] == ["STATE", "ZIPCODE"]
        exprs = {r["name"]: r["expr"] for r in out["rules"]}
        assert exprs["geo_rule"] == "[MULTI_AGG_1::ZIPCODE] = ts_groups_int"
        assert exprs["state_rule"] == "[MULTI_AGG_1::STATE] = ts_var('state')"

    def test_cross_table_same_physical_col_maps_to_distinct_agg_cols(self):
        # SECURITY regression: two base tables each RLS-filter on a same-named
        # physical column (REGION). Keying by bare column name would collapse
        # both onto ONE aggregate column → silent mis-securing (a lint-clean
        # rule enforcing the WRONG row restriction). Tuple keys (table, col)
        # must map them to DISTINCT aggregate columns.
        table_a = {
            "table": {
                "name": "Sales Fact",
                "rls_rules": {
                    "table_paths": [{"id": "A_1", "table": "Sales Fact", "column": ["REGION"]}],
                    "rules": [{"name": "sales_region", "expr": "[A_1::REGION] = ts_groups"}],
                },
            }
        }
        table_b = {
            "table": {
                "name": "Cost Dim",
                "rls_rules": {
                    "table_paths": [{"id": "B_1", "table": "Cost Dim", "column": ["REGION"]}],
                    "rules": [{"name": "cost_region", "expr": "[B_1::REGION] = ts_groups"}],
                },
            }
        }
        rules = extract_rls({"Sales Fact": table_a, "Cost Dim": table_b})
        out = propagate_rls(rules, "COMBO_AGG", {
            ("Sales Fact", "REGION"): "SALES_REGION",
            ("Cost Dim", "REGION"): "COST_REGION",
        })
        # both distinct aggregate columns appear on the merged path
        assert out["table_paths"][0]["column"] == ["COST_REGION", "SALES_REGION"]
        exprs = {r["name"]: r["expr"] for r in out["rules"]}
        assert exprs["sales_region"] == "[COMBO_AGG_1::SALES_REGION] = ts_groups"
        assert exprs["cost_region"] == "[COMBO_AGG_1::COST_REGION] = ts_groups"

    def test_missing_mapping_raises_clear_error(self):
        rules = extract_rls({"Source Table": _NESTED_TABLE_TML})
        with pytest.raises(ValueError, match="ZIPCODE"):
            propagate_rls(rules, "SALES_AGG", {})

    def test_no_base_rules_returns_empty_dict(self):
        assert propagate_rls([], "SALES_AGG", {}) == {}

    def test_round_trips_through_dump_and_lint_clean(self):
        rules = extract_rls({"Source Table": _NESTED_TABLE_TML})
        rls_block = propagate_rls(rules, "SALES_AGG", {("Source Table", "ZIPCODE"): "ZIPCODE"})

        table_tml = {
            "table": {
                "name": "SALES_AGG",
                "columns": [
                    {"name": "ZIPCODE", "db_column_name": "ZIPCODE",
                     "data_type": "VARCHAR", "column_type": "ATTRIBUTE"},
                ],
                "rls_rules": rls_block,
            }
        }

        yaml_text = dump_tml_yaml(table_tml)
        round_tripped = yaml.safe_load(yaml_text)
        assert lint_tml(round_tripped) == []
        assert round_tripped["table"]["rls_rules"]["rules"][0]["expr"] == (
            "[SALES_AGG_1::ZIPCODE] = ts_groups_int"
        )
        assert round_tripped["table"]["rls_rules"]["table_paths"][0]["table"] == "SALES_AGG"
