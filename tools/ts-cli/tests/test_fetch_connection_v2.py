"""Unit tests for the v2 connection-fetch adapter in connections.py.

Covers _adapt_v2_databases() (v2 connection/search shape → legacy
dataWarehouseInfo shape), _extract_auth_type() (best-effort auth type
extraction from connection response), and _fetch_connection_v2() (request
shape + response unwrapping + auth type pass-through). No live ThoughtSpot
connection required — the client is mocked.
"""
from unittest.mock import MagicMock

from ts_cli.commands.connections import (
    _adapt_v2_databases,
    _extract_auth_type,
    _fetch_connection_v2,
)


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
        assert out["dataWarehouseInfo"] == {"databases": []}
        assert "authenticationType" not in out

    def test_passes_through_auth_type_from_top_level(self):
        body = [{"name": "C", "authentication_type": "KEY_PAIR"}]
        out = _fetch_connection_v2(_client_returning(body), "c")
        assert out["authenticationType"] == "KEY_PAIR"

    def test_passes_through_auth_type_from_details(self):
        body = [{"name": "C", "details": {"authenticationType": "OAUTH"}}]
        out = _fetch_connection_v2(_client_returning(body), "c")
        assert out["authenticationType"] == "OAUTH"

    def test_no_auth_type_when_absent(self):
        body = [{"name": "C", "data_warehouse_type": "SNOWFLAKE"}]
        out = _fetch_connection_v2(_client_returning(body), "c")
        assert "authenticationType" not in out


# ---------------------------------------------------------------------------
# _extract_auth_type — best-effort extraction
# ---------------------------------------------------------------------------

class TestExtractAuthType:
    def test_top_level_snake_case(self):
        assert _extract_auth_type({"authentication_type": "KEY_PAIR"}) == "KEY_PAIR"

    def test_top_level_camel_case(self):
        assert _extract_auth_type({"authenticationType": "SERVICE_ACCOUNT"}) == "SERVICE_ACCOUNT"

    def test_details_camel_case(self):
        assert _extract_auth_type({"details": {"authenticationType": "OAUTH"}}) == "OAUTH"

    def test_details_snake_case(self):
        assert _extract_auth_type({"details": {"authentication_type": "IAM"}}) == "IAM"

    def test_none_when_absent(self):
        assert _extract_auth_type({"name": "foo"}) is None

    def test_none_when_details_is_none(self):
        assert _extract_auth_type({"details": None}) is None

    def test_top_level_wins_over_details(self):
        conn = {"authentication_type": "KEY_PAIR", "details": {"authenticationType": "OAUTH"}}
        assert _extract_auth_type(conn) == "KEY_PAIR"


# ---------------------------------------------------------------------------
# add_tables update payload — authenticationType inclusion (BL-095)
# ---------------------------------------------------------------------------

class TestAddTablesUpdatePayload:
    """Verify that ``add_tables`` includes ``authenticationType`` in the
    ``data_warehouse_config`` sent to ``updateConnectionV2``.

    These tests mock the client and stdin to capture the update POST body
    without needing a live ThoughtSpot instance.
    """

    def _run(self, *, fetch_body, stdin_json, auth_type_option=None):
        """Run add_tables with mocked I/O and return the update POST body."""
        import io
        from unittest.mock import patch

        from ts_cli.commands.connections import add_tables

        client = MagicMock()
        fetch_resp = MagicMock()
        fetch_resp.json.return_value = fetch_body
        update_resp = MagicMock()
        update_resp.json.return_value = {}
        client.post.side_effect = [fetch_resp, update_resp]

        with patch("ts_cli.commands.connections.ThoughtSpotClient", return_value=client), \
             patch("ts_cli.commands.connections.resolve_profile", return_value={}), \
             patch("sys.stdin", io.StringIO(stdin_json)):
            ctx = MagicMock()
            add_tables(connection_id="conn-1", profile="test", auth_type=auth_type_option)

        update_call = client.post.call_args_list[1]
        return update_call[1]["json"]

    def test_auth_type_from_fetch_included_in_payload(self):
        body = [{"name": "C", "authentication_type": "KEY_PAIR"}]
        payload = self._run(
            fetch_body=body,
            stdin_json='[{"db":"D","schema":"S","table":"T","columns":[]}]',
        )
        assert payload["data_warehouse_config"]["authenticationType"] == "KEY_PAIR"

    def test_cli_option_overrides_fetched_auth_type(self):
        body = [{"name": "C", "authentication_type": "SERVICE_ACCOUNT"}]
        payload = self._run(
            fetch_body=body,
            stdin_json='[{"db":"D","schema":"S","table":"T","columns":[]}]',
            auth_type_option="KEY_PAIR",
        )
        assert payload["data_warehouse_config"]["authenticationType"] == "KEY_PAIR"

    def test_auth_type_omitted_when_undetectable(self):
        body = [{"name": "C"}]
        payload = self._run(
            fetch_body=body,
            stdin_json='[{"db":"D","schema":"S","table":"T","columns":[]}]',
        )
        assert "authenticationType" not in payload["data_warehouse_config"]

    def test_cli_option_used_when_fetch_has_no_auth_type(self):
        body = [{"name": "C"}]
        payload = self._run(
            fetch_body=body,
            stdin_json='[{"db":"D","schema":"S","table":"T","columns":[]}]',
            auth_type_option="OAUTH",
        )
        assert payload["data_warehouse_config"]["authenticationType"] == "OAUTH"

    def test_validate_is_true(self):
        body = [{"name": "C", "authentication_type": "SERVICE_ACCOUNT"}]
        payload = self._run(
            fetch_body=body,
            stdin_json='[{"db":"D","schema":"S","table":"T","columns":[]}]',
        )
        assert payload["validate"] is True
