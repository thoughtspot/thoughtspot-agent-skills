"""Tests for ts_cli.dbt_diff — ts-convert-to-dbt Case B change-set computation.

Mirrors the `ts snowflake diff` "Mode C" precedent (compute_change_set in
snowflake_ops.py): pure functions, no I/O.
"""
from __future__ import annotations

from ts_cli.dbt_diff import compute_dbt_change_set, parse_schema_yaml_columns


class TestParseSchemaYamlColumns:
    def test_blank_input_returns_empty(self):
        assert parse_schema_yaml_columns("") == {}
        assert parse_schema_yaml_columns("   \n  ") == {}

    def test_malformed_yaml_returns_empty(self):
        assert parse_schema_yaml_columns("models: [unterminated") == {}

    def test_non_dict_document_returns_empty(self):
        assert parse_schema_yaml_columns("- just\n- a\n- list\n") == {}

    def test_basic_meta_and_relationship(self):
        text = """
version: 2
models:
  - name: stg_orders
    columns:
      - name: CUSTOMER_ID
        config:
          meta:
            ts_column_type: attribute
        data_tests:
          - relationships:
              arguments:
                to: ref('stg_customers')
                field: CUSTOMER_ID
              config:
                meta:
                  ts_join_cardinality: many_to_one
      - name: AMOUNT
        config:
          meta:
            ts_column_type: measure
            ts_aggregation: sum
"""
        parsed = parse_schema_yaml_columns(text)
        assert set(parsed.keys()) == {"stg_orders"}
        cols = parsed["stg_orders"]
        assert cols["CUSTOMER_ID"]["meta"] == {"ts_column_type": "attribute"}
        assert cols["CUSTOMER_ID"]["relationship"]["arguments"]["field"] == "CUSTOMER_ID"
        assert cols["AMOUNT"]["meta"] == {"ts_column_type": "measure", "ts_aggregation": "sum"}
        assert cols["AMOUNT"]["relationship"] is None

    def test_older_tests_key_alias_also_parsed(self):
        text = """
models:
  - name: stg_orders
    columns:
      - name: CUSTOMER_ID
        tests:
          - relationships:
              to: ref('stg_customers')
              field: CUSTOMER_ID
"""
        parsed = parse_schema_yaml_columns(text)
        assert parsed["stg_orders"]["CUSTOMER_ID"]["relationship"] == {
            "to": "ref('stg_customers')", "field": "CUSTOMER_ID"}

    def test_column_with_no_meta_or_test_defaults(self):
        text = """
models:
  - name: stg_orders
    columns:
      - name: ORDER_DATE
"""
        parsed = parse_schema_yaml_columns(text)
        assert parsed["stg_orders"]["ORDER_DATE"] == {
            "meta": {}, "relationship": None, "description": ""}


class TestComputeDbtChangeSet:
    def test_no_differences_omits_table(self):
        current = {"stg_orders": {"AMOUNT": {"meta": {"ts_column_type": "measure"}, "relationship": None}}}
        new = {"stg_orders": {"AMOUNT": {"meta": {"ts_column_type": "measure"}, "relationship": None}}}
        assert compute_dbt_change_set(current, new) == {}

    def test_table_only_on_one_side_is_not_diffed(self):
        current = {"stg_orders": {"AMOUNT": {"meta": {}, "relationship": None}}}
        new = {"stg_new_table": {"AMOUNT": {"meta": {}, "relationship": None}}}
        assert compute_dbt_change_set(current, new) == {}

    def test_new_and_removed_columns(self):
        current = {"stg_orders": {
            "OLD_COL": {"meta": {}, "relationship": None},
        }}
        new = {"stg_orders": {
            "NEW_COL": {"meta": {}, "relationship": None},
        }}
        result = compute_dbt_change_set(current, new)
        assert result["stg_orders"]["new_columns"] == ["NEW_COL"]
        assert result["stg_orders"]["removed_columns"] == ["OLD_COL"]

    def test_modified_meta(self):
        current = {"stg_orders": {
            "AMOUNT": {"meta": {"ts_aggregation": "sum"}, "relationship": None},
        }}
        new = {"stg_orders": {
            "AMOUNT": {"meta": {"ts_aggregation": "avg"}, "relationship": None},
        }}
        result = compute_dbt_change_set(current, new)
        assert result["stg_orders"]["modified_meta"] == [
            {"column": "AMOUNT", "current": {"ts_aggregation": "sum"},
             "new": {"ts_aggregation": "avg"}},
        ]

    def test_new_removed_and_modified_relationship(self):
        rel_a = {"arguments": {"to": "ref('a')", "field": "ID"}}
        rel_b = {"arguments": {"to": "ref('b')", "field": "ID"}}
        current = {"stg_orders": {
            "GAINS_REL": {"meta": {}, "relationship": None},
            "LOSES_REL": {"meta": {}, "relationship": rel_a},
            "CHANGES_REL": {"meta": {}, "relationship": rel_a},
        }}
        new = {"stg_orders": {
            "GAINS_REL": {"meta": {}, "relationship": rel_a},
            "LOSES_REL": {"meta": {}, "relationship": None},
            "CHANGES_REL": {"meta": {}, "relationship": rel_b},
        }}
        result = compute_dbt_change_set(current, new)
        table = result["stg_orders"]
        assert table["new_relationship"] == ["GAINS_REL"]
        assert table["removed_relationship"] == ["LOSES_REL"]
        assert table["modified_relationship"] == [
            {"column": "CHANGES_REL", "current": rel_a, "new": rel_b},
        ]

    def test_multiple_tables_only_changed_ones_reported(self):
        current = {
            "stg_orders": {"AMOUNT": {"meta": {"ts_aggregation": "sum"}, "relationship": None}},
            "stg_customers": {"NAME": {"meta": {}, "relationship": None}},
        }
        new = {
            "stg_orders": {"AMOUNT": {"meta": {"ts_aggregation": "avg"}, "relationship": None}},
            "stg_customers": {"NAME": {"meta": {}, "relationship": None}},
        }
        result = compute_dbt_change_set(current, new)
        assert set(result.keys()) == {"stg_orders"}



class TestExcludedColumnsInvisibleToDiff:
    def test_excluded_column_not_reported_as_removed(self):
        import yaml
        from ts_cli.dbt_diff import compute_dbt_change_set, parse_schema_yaml_columns
        current = yaml.safe_dump({"version": 2, "models": [{"name": "appointments", "columns": [
            {"name": "APPOINTMENT_ID", "config": {"meta": {"ts_column_type": "attribute"}}},
            {"name": "INTERNAL_NOTES", "config": {"meta": {"ts_column_type": "attribute",
                                                            "ts_column_exclude": True}}}]}]})
        fresh = yaml.safe_dump({"version": 2, "models": [{"name": "appointments", "columns": [
            {"name": "APPOINTMENT_ID", "config": {"meta": {"ts_column_type": "attribute"}}}]}]})
        cur, new = parse_schema_yaml_columns(current), parse_schema_yaml_columns(fresh)
        assert "INTERNAL_NOTES" not in cur["appointments"]
        assert compute_dbt_change_set(cur, new) == {}


class TestDescriptionDiff:
    """`modified_description` — the reporting gap found in the 2026-09-09 live
    round trip: `sync --update-metadata` applied a description edited in
    ThoughtSpot, but `diff` never listed it (only the synonym showed up under
    `modified_meta`)."""

    def _entry(self, desc, meta=None):
        return {"meta": meta or {}, "relationship": None, "description": desc}

    def test_parse_captures_description(self):
        text = """
version: 2
models:
  - name: transactions
    columns:
      - name: TIP_AMOUNT
        description: Tip left by the customer in dollars.
        config:
          meta:
            ts_column_type: measure
      - name: NO_DESC
        config:
          meta:
            ts_column_type: attribute
"""
        cols = parse_schema_yaml_columns(text)["transactions"]
        assert cols["TIP_AMOUNT"]["description"] == "Tip left by the customer in dollars."
        assert cols["NO_DESC"]["description"] == ""

    def test_changed_description_is_reported(self):
        current = {"transactions": {"TIP_AMOUNT": self._entry("Tip left by the customer in dollars.")}}
        new = {"transactions": {"TIP_AMOUNT": self._entry(
            "Gratuity left by the customer, in US dollars. Updated in ThoughtSpot.")}}
        result = compute_dbt_change_set(current, new)
        assert result["transactions"]["modified_description"] == [{
            "column": "TIP_AMOUNT",
            "current": "Tip left by the customer in dollars.",
            "new": "Gratuity left by the customer, in US dollars. Updated in ThoughtSpot.",
        }]
        assert result["transactions"]["modified_meta"] == []

    def test_description_only_change_makes_the_table_changed(self):
        current = {"t": {"C": self._entry("old")}}
        new = {"t": {"C": self._entry("new")}}
        assert "t" in compute_dbt_change_set(current, new)

    def test_added_description_is_reported(self):
        current = {"t": {"C": self._entry("")}}
        new = {"t": {"C": self._entry("now documented")}}
        assert compute_dbt_change_set(current, new)["t"]["modified_description"] == [
            {"column": "C", "current": "", "new": "now documented"}]

    def test_cleared_description_is_not_reported(self):
        """sync keeps the dbt text when ThoughtSpot has none — so diff must not
        promise a change sync then ignores."""
        current = {"t": {"C": self._entry("keep me")}}
        new = {"t": {"C": self._entry("")}}
        assert compute_dbt_change_set(current, new) == {}

    def test_identical_descriptions_are_silent(self):
        current = {"t": {"C": self._entry("same")}}
        new = {"t": {"C": self._entry("same")}}
        assert compute_dbt_change_set(current, new) == {}

    def test_entries_without_description_key_still_diff(self):
        """Older callers/tests build entries with only meta+relationship."""
        current = {"t": {"C": {"meta": {}, "relationship": None}}}
        new = {"t": {"C": {"meta": {}, "relationship": None}}}
        assert compute_dbt_change_set(current, new) == {}
