"""Unit tests for the v2 connection-fetch adapter in connections.py.

Covers _adapt_v2_databases() (v2 connection/search shape → legacy
dataWarehouseInfo shape) and _fetch_connection_v2() (request shape + response
unwrapping). No live ThoughtSpot connection required — the client is mocked.
"""
from unittest.mock import MagicMock

from ts_cli.commands.connections import _adapt_v2_databases, _fetch_connection_v2


# ---------------------------------------------------------------------------
# _adapt_v2_databases — key renaming v2 → legacy
# ---------------------------------------------------------------------------

class TestAdaptV2Databases:
    def test_empty(self):
        assert _adapt_v2_databases([]) == []
        assert _adapt_v2_databases(None) == []

    def test_renames_keys_to_legacy(self):
        v2 = [{
            "name": "DB1",
            "auto_created": True,
            "schemas": [{
                "name": "SCH1",
                "tables": [{
                    "name": "T1",
                    "type": "TABLE",
                    "columns": [
                        {"name": "C1", "data_type": "INT64", "is_linked_active": True},
                        {"name": "C2", "data_type": "VARCHAR"},
                    ],
                }],
            }],
        }]
        out = _adapt_v2_databases(v2)
        db = out[0]
        assert db["name"] == "DB1"
        assert db["isAutoCreated"] is True            # auto_created → isAutoCreated
        col1, col2 = db["schemas"][0]["tables"][0]["columns"]
        assert col1 == {"name": "C1", "type": "INT64", "selected": True, "isLinkedActive": True}
        # data_type → type; missing is_linked_active defaults True
        assert col2["type"] == "VARCHAR" and col2["isLinkedActive"] is True

    def test_table_defaults(self):
        out = _adapt_v2_databases([{"name": "D", "schemas": [{"name": "S", "tables": [{"name": "T"}]}]}])
        t = out[0]["schemas"][0]["tables"][0]
        assert t["type"] == "TABLE" and t["selected"] is True and t["linked"] is True
        assert t["columns"] == []

    def test_adapted_output_roundtrips_through_merge(self):
        # The whole point: adapted output must be mergeable by _merge_tables.
        from ts_cli.commands.connections import _merge_tables
        v2 = [{"name": "D", "schemas": [{"name": "S", "tables": [
            {"name": "EXISTING", "columns": [{"name": "C1", "data_type": "INT64"}]}]}]}]
        fetch = {"dataWarehouseInfo": {"databases": _adapt_v2_databases(v2)}}
        merged = _merge_tables(fetch, [
            {"db": "D", "schema": "S", "table": "NEW", "columns": [{"name": "X", "type": "VARCHAR"}]}
        ])
        names = {t["name"] for db in merged for s in db["schemas"] for t in s["tables"]}
        assert names == {"EXISTING", "NEW"}            # existing preserved + new added


# ---------------------------------------------------------------------------
# _fetch_connection_v2 — request shape + response unwrapping
# ---------------------------------------------------------------------------

def _client_returning(body):
    client = MagicMock()
    resp = MagicMock()
    resp.json.return_value = body
    client.post.return_value = resp
    return client


class TestFetchConnectionV2:
    def test_posts_to_v2_search_endpoint(self):
        client = _client_returning([])
        _fetch_connection_v2(client, "conn-1")
        path, = client.post.call_args[0]
        assert path == "/api/rest/2.0/connection/search"
        body = client.post.call_args[1]["json"]
        assert body["connections"] == [{"identifier": "conn-1"}]
        assert body["data_warehouse_object_type"] == "COLUMN"
        assert body["record_size"] == -1

    def test_unwraps_list_response(self):
        body = [{"name": "C", "data_warehouse_objects": {"databases": [
            {"name": "D", "schemas": [{"name": "S", "tables": [
                {"name": "T", "columns": [{"name": "C1", "data_type": "INT64"}]}]}]}]}}]
        out = _fetch_connection_v2(_client_returning(body), "c")
        assert out["dataWarehouseInfo"]["databases"][0]["name"] == "D"

    def test_empty_hierarchy_for_oauth_connection(self):
        # OAuth/PKCE connection: 200 but no data_warehouse_objects → empty.
        body = [{"name": "APJ_TAB", "data_warehouse_type": "SNOWFLAKE"}]
        out = _fetch_connection_v2(_client_returning(body), "c")
        assert out == {"dataWarehouseInfo": {"databases": []}}
