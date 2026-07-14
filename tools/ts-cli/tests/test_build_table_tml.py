"""Unit tests for _build_table_tml() and _find_guid_by_name() in ts_cli/commands/tables.py.

Tests verify the TML invariants documented in agents/shared/schemas/thoughtspot-table-tml.md.
No live ThoughtSpot connection required.
"""
import pytest
import yaml

from ts_cli.commands.tables import _build_table_tml, _find_guid_by_name, _strip_rls_rules

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_tml(tml_str: str) -> dict:
    """Parse TML YAML string and return the dict."""
    return yaml.safe_load(tml_str)


def make_spec(columns=None, **kwargs) -> dict:
    base = {
        "name": "MY_TABLE",
        "db": "MY_DB",
        "schema": "MY_SCHEMA",
        "db_table": "MY_TABLE",
        "connection_name": "My Connection",
    }
    base.update(kwargs)
    if columns is not None:
        base["columns"] = columns
    else:
        base["columns"] = [
            {"name": "ID", "data_type": "INT64", "column_type": "ATTRIBUTE"},
        ]
    return base


# ---------------------------------------------------------------------------
# Critical invariant: db_column_name is always present
# ---------------------------------------------------------------------------

class TestDbColumnName:
    def test_db_column_name_equals_name_by_default(self):
        """db_column_name must always be included, even when identical to name."""
        spec = make_spec(columns=[
            {"name": "ORDER_ID", "data_type": "INT64", "column_type": "ATTRIBUTE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert "db_column_name" in col, "db_column_name must always be present"
        assert col["db_column_name"] == col["name"]

    def test_db_column_name_present_for_measure(self):
        spec = make_spec(columns=[
            {"name": "AMOUNT", "data_type": "INT64", "column_type": "MEASURE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert "db_column_name" in col
        assert col["db_column_name"] == "AMOUNT"

    def test_db_column_name_present_for_all_columns(self):
        spec = make_spec(columns=[
            {"name": "ID", "data_type": "INT64", "column_type": "ATTRIBUTE"},
            {"name": "NAME", "data_type": "VARCHAR", "column_type": "ATTRIBUTE"},
            {"name": "AMOUNT", "data_type": "INT64", "column_type": "MEASURE"},
            {"name": "DATE", "data_type": "DATE", "column_type": "ATTRIBUTE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        for col in tml["table"]["columns"]:
            assert "db_column_name" in col, f"db_column_name missing from column '{col.get('name')}'"


# ---------------------------------------------------------------------------
# Critical invariant: connection uses name: not fqn:
# ---------------------------------------------------------------------------

class TestConnectionBlock:
    def test_connection_has_name_not_fqn(self):
        """Connection block must use name: only, never fqn:."""
        spec = make_spec()
        tml = parse_tml(_build_table_tml(spec))
        conn = tml["table"]["connection"]
        assert "name" in conn
        assert "fqn" not in conn, "fqn: must never appear in a connection block"

    def test_connection_name_preserved(self):
        spec = make_spec(connection_name="My Snowflake Connection")
        tml = parse_tml(_build_table_tml(spec))
        assert tml["table"]["connection"]["name"] == "My Snowflake Connection"

    def test_connection_name_with_special_chars(self):
        spec = make_spec(connection_name="APJ_BIRD (prod)")
        tml = parse_tml(_build_table_tml(spec))
        assert tml["table"]["connection"]["name"] == "APJ_BIRD (prod)"


# ---------------------------------------------------------------------------
# MEASURE columns get aggregation: SUM by default
# ---------------------------------------------------------------------------

class TestMeasureAggregation:
    def test_measure_gets_default_aggregation_sum(self):
        spec = make_spec(columns=[
            {"name": "REVENUE", "data_type": "INT64", "column_type": "MEASURE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert col["properties"]["aggregation"] == "SUM"

    def test_measure_respects_explicit_aggregation(self):
        spec = make_spec(columns=[
            {"name": "COUNT_COL", "data_type": "INT64", "column_type": "MEASURE",
             "aggregation": "COUNT"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert col["properties"]["aggregation"] == "COUNT"

    def test_attribute_has_no_aggregation(self):
        spec = make_spec(columns=[
            {"name": "STATUS", "data_type": "VARCHAR", "column_type": "ATTRIBUTE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert "aggregation" not in col["properties"]


# ---------------------------------------------------------------------------
# Valid ThoughtSpot data types
#
# BOOL (not BOOLEAN) is the type the live import API accepts — verified
# BL-063 PR4, 2026-07-10, se-thoughtspot: "Data type BOOLEAN is not valid
# for column ...". _build_table_tml normalizes an input of "BOOLEAN" to
# "BOOL" so specs written against the old help text keep working — see
# TestBooleanNormalization below.
# ---------------------------------------------------------------------------

VALID_DATA_TYPES = ["INT64", "DOUBLE", "VARCHAR", "DATE", "DATE_TIME", "BOOL"]

class TestDataTypes:
    @pytest.mark.parametrize("data_type", VALID_DATA_TYPES)
    def test_valid_data_type_round_trips(self, data_type):
        spec = make_spec(columns=[
            {"name": "COL", "data_type": data_type, "column_type": "ATTRIBUTE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert col["db_column_properties"]["data_type"] == data_type


class TestBooleanNormalization:
    def test_boolean_input_normalized_to_bool(self):
        spec = make_spec(columns=[
            {"name": "IS_ACTIVE", "data_type": "BOOLEAN", "column_type": "ATTRIBUTE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert col["db_column_properties"]["data_type"] == "BOOL"

    def test_bool_input_passes_through_unchanged(self):
        spec = make_spec(columns=[
            {"name": "IS_ACTIVE", "data_type": "BOOL", "column_type": "ATTRIBUTE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert col["db_column_properties"]["data_type"] == "BOOL"

    def test_other_data_types_unaffected_by_normalization(self):
        spec = make_spec(columns=[
            {"name": "COL", "data_type": "VARCHAR", "column_type": "ATTRIBUTE"},
        ])
        tml = parse_tml(_build_table_tml(spec))
        col = tml["table"]["columns"][0]
        assert col["db_column_properties"]["data_type"] == "VARCHAR"


# ---------------------------------------------------------------------------
# Output is valid YAML
# ---------------------------------------------------------------------------

class TestYamlOutput:
    def test_output_is_valid_yaml(self):
        spec = make_spec(columns=[
            {"name": "ID", "data_type": "INT64", "column_type": "ATTRIBUTE"},
            {"name": "NAME", "data_type": "VARCHAR", "column_type": "ATTRIBUTE"},
            {"name": "AMOUNT", "data_type": "DOUBLE", "column_type": "MEASURE"},
        ])
        tml_str = _build_table_tml(spec)
        tml = yaml.safe_load(tml_str)
        assert "table" in tml

    def test_table_top_level_fields(self):
        spec = make_spec()
        tml = parse_tml(_build_table_tml(spec))
        t = tml["table"]
        assert t["name"] == "MY_TABLE"
        assert t["db"] == "MY_DB"
        assert t["schema"] == "MY_SCHEMA"
        assert t["db_table"] == "MY_TABLE"


# ---------------------------------------------------------------------------
# Bug B (Task 25, two-pass RLS import): `_build_table_tml`'s optional `guid`
# param puts `guid:` at the document root — required for pass 2's
# update-in-place (`--no-create-new`) import that attaches a propagated
# `rls_rules` block onto an aggregate table created (without RLS) in pass 1.
# ---------------------------------------------------------------------------

class TestBuildTableTmlGuid:
    def test_no_guid_by_default(self):
        spec = make_spec()
        tml = parse_tml(_build_table_tml(spec))
        assert "guid" not in tml

    def test_guid_placed_at_document_root(self):
        spec = make_spec()
        tml = parse_tml(_build_table_tml(spec, guid="abc-123"))
        assert tml["guid"] == "abc-123"
        # guid: is a document-root sibling of table:, never nested inside it
        assert "guid" not in tml["table"]

    def test_guid_does_not_affect_table_body(self):
        spec = make_spec(rls_rules={"tables": [{"name": "MY_TABLE"}],
                                    "table_paths": [{"id": "MY_TABLE_1", "table": "MY_TABLE",
                                                     "column": ["ID"]}],
                                    "rules": [{"name": "r", "expr": "[MY_TABLE_1::ID] = ts_groups"}]})
        without_guid = parse_tml(_build_table_tml(spec))
        with_guid = parse_tml(_build_table_tml(spec, guid="abc-123"))
        assert with_guid["table"] == without_guid["table"]


# ---------------------------------------------------------------------------
# Bug B (Task 25): `_strip_rls_rules` — the RLS-less spec variant for pass 1
# (create). A self-referencing rls_rules block can't resolve before the
# table exists on a live cluster, so pass 1 must create without it.
# ---------------------------------------------------------------------------

class TestStripRlsRules:
    def test_removes_rls_rules_key(self):
        spec = make_spec(rls_rules={"tables": [{"name": "MY_TABLE"}], "table_paths": [],
                                    "rules": []})
        stripped = _strip_rls_rules(spec)
        assert "rls_rules" not in stripped

    def test_leaves_other_keys_untouched(self):
        spec = make_spec(rls_rules={"tables": [{"name": "MY_TABLE"}]})
        stripped = _strip_rls_rules(spec)
        assert stripped["name"] == spec["name"]
        assert stripped["columns"] == spec["columns"]
        assert stripped["connection_name"] == spec["connection_name"]

    def test_no_op_when_rls_rules_absent(self):
        spec = make_spec()
        stripped = _strip_rls_rules(spec)
        assert stripped == spec

    def test_original_spec_untouched(self):
        spec = make_spec(rls_rules={"tables": [{"name": "MY_TABLE"}]})
        _strip_rls_rules(spec)
        assert "rls_rules" in spec

    def test_stripped_spec_produces_tml_without_rls_rules(self):
        spec = make_spec(rls_rules={"tables": [{"name": "MY_TABLE"}], "table_paths": [],
                                    "rules": []})
        stripped = _strip_rls_rules(spec)
        tml = parse_tml(_build_table_tml(stripped))
        assert "rls_rules" not in tml["table"]


# ---------------------------------------------------------------------------
# _find_guid_by_name — connection-scoped GUID resolution
#
# Live finding, BL-063 PR4 (2026-07-10, se-thoughtspot): same-named
# "DM_ORDER" tables existed on both the "Power" and "APJ_BIRD" connections.
# A name-only search resolved to the wrong connection's GUID, so the built
# model referenced foreign tables and import failed with "Could not find
# column"/"different connections". _find_guid_by_name now requires an
# exact name match AND metadata_header.dataSourceName == connection_name.
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, json_data):
        self._json = json_data

    def json(self):
        return self._json


class _FakeClient:
    """Minimal stand-in for ThoughtSpotClient — only .post() is used by
    _find_guid_by_name."""
    def __init__(self, search_results):
        self.search_results = search_results
        self.calls = []

    def post(self, path, json=None, **kwargs):
        self.calls.append((path, json))
        return _FakeResp(self.search_results)


class TestFindGuidByNameConnectionScoped:
    def test_picks_matching_connection_among_same_named_items(self):
        # Two tables both named DM_ORDER, on different connections.
        results = [
            {"metadata_id": "power-guid", "metadata_name": "DM_ORDER",
             "metadata_header": {"id": "power-guid", "name": "DM_ORDER",
                                  "dataSourceName": "Power"}},
            {"metadata_id": "bird-guid", "metadata_name": "DM_ORDER",
             "metadata_header": {"id": "bird-guid", "name": "DM_ORDER",
                                  "dataSourceName": "APJ_BIRD"}},
        ]
        client = _FakeClient(results)
        guid = _find_guid_by_name(client, "DM_ORDER", "APJ_BIRD")
        assert guid == "bird-guid"

    def test_returns_none_when_no_connection_matches(self):
        results = [
            {"metadata_id": "power-guid", "metadata_name": "DM_ORDER",
             "metadata_header": {"id": "power-guid", "name": "DM_ORDER",
                                  "dataSourceName": "Power"}},
        ]
        client = _FakeClient(results)
        assert _find_guid_by_name(client, "DM_ORDER", "APJ_BIRD") is None

    def test_returns_none_when_name_matches_but_no_results(self):
        client = _FakeClient([])
        assert _find_guid_by_name(client, "DM_ORDER", "APJ_BIRD") is None

    def test_ignores_name_mismatch_even_if_connection_matches(self):
        results = [
            {"metadata_id": "other-guid", "metadata_name": "DM_OTHER",
             "metadata_header": {"id": "other-guid", "name": "DM_OTHER",
                                  "dataSourceName": "APJ_BIRD"}},
        ]
        client = _FakeClient(results)
        assert _find_guid_by_name(client, "DM_ORDER", "APJ_BIRD") is None

    def test_swallows_client_exception_and_returns_none(self):
        class _RaisingClient:
            def post(self, *a, **kw):
                raise RuntimeError("boom")
        assert _find_guid_by_name(_RaisingClient(), "DM_ORDER", "APJ_BIRD") is None
