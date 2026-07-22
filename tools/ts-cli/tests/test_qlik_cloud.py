"""Unit tests for ts_cli.qlik.cloud — the Qlik Cloud (SaaS) REST + Engine path.

No network: pure helpers are tested directly; extract() is exercised with
live_engine.extract and the REST data-connections fetch monkeypatched, feeding
recorded Qlik Cloud responses.
"""
import pytest

from ts_cli.qlik import cloud, live_engine
from ts_cli.qlik.ir import Connection, QlikApp


class TestUrlHelpers:
    def test_host_strips_scheme_and_slash(self):
        assert cloud._host("https://acme.us.qlikcloud.com/") == "acme.us.qlikcloud.com"

    def test_engine_url(self):
        assert cloud.engine_url("https://acme.us.qlikcloud.com", "g1") == \
            "wss://acme.us.qlikcloud.com/app/g1"

    def test_rest_base(self):
        assert cloud.rest_base("http://acme.qlikcloud.com") == \
            "https://acme.qlikcloud.com/api/v1"


class TestParseDataConnections:
    def test_maps_recorded_items_tolerantly(self):
        items = [
            {"qName": "Snowflake_Sales", "qType": "SNOWFLAKE",
             "qConnectStatement": "CUSTOM CONNECT ...", "space": "shared"},
            {"name": "Folder_A", "datasourceID": "folder", "id": "abc"},
            {"qType": "orphan"},  # no name -> skipped
        ]
        conns = cloud.parse_data_connections(items)
        assert [c.name for c in conns] == ["Snowflake_Sales", "Folder_A"]
        sf = conns[0]
        assert sf.qlik_type == "SNOWFLAKE"
        assert sf.properties["space"] == "shared"
        assert "qConnectStatement" in sf.properties

    def test_empty(self):
        assert cloud.parse_data_connections([]) == []


class TestResolveAppId:
    def test_guid_passthrough(self):
        guid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert cloud.resolve_app_id("t", "k", guid) == guid

    def test_resolves_name_via_rest(self, monkeypatch):
        monkeypatch.setattr(cloud, "list_apps", lambda t, k: [
            {"name": "Sales", "id": "id-1", "resourceId": "res-1"},
        ])
        assert cloud.resolve_app_id("t", "k", "Sales") == "res-1"

    def test_unknown_name_raises(self, monkeypatch):
        monkeypatch.setattr(cloud, "list_apps", lambda t, k: [])
        with pytest.raises(ValueError):
            cloud.resolve_app_id("t", "k", "Nope")


class TestExtract:
    def _fake_engine_app(self):
        app = QlikApp(app_name="Sales", extraction_mode="engine")
        app.connections.append(Connection(name="Snowflake_Sales", qlik_type="SNOWFLAKE"))
        return app

    def test_extract_enriches_connections(self, monkeypatch):
        guid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        monkeypatch.setattr(live_engine, "extract",
                            lambda url, app_id, headers=None: self._fake_engine_app())
        monkeypatch.setattr(cloud, "fetch_data_connections", lambda t, k: [
            {"qName": "Snowflake_Sales", "qType": "SNOWFLAKE"},   # dup -> not re-added
            {"qName": "Folder_Extra", "qType": "Folder"},         # new -> added
        ])
        app = cloud.extract("https://acme.qlikcloud.com", guid, "the-key")
        names = [c.name for c in app.connections]
        assert names == ["Snowflake_Sales", "Folder_Extra"]
        assert app.source_file.endswith(f"app {guid}")
        assert any(n.area == "connection" and n.severity == "info" for n in app.notes)

    def test_rest_failure_is_a_warning_not_a_crash(self, monkeypatch):
        guid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        monkeypatch.setattr(live_engine, "extract",
                            lambda url, app_id, headers=None: self._fake_engine_app())

        def boom(t, k):
            raise RuntimeError("403 forbidden")

        monkeypatch.setattr(cloud, "fetch_data_connections", boom)
        app = cloud.extract("https://acme.qlikcloud.com", guid, "the-key")
        assert any(n.severity == "warning" and n.area == "connection" for n in app.notes)

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("QLIK_API_KEY", raising=False)
        with pytest.raises(ValueError) as exc:
            cloud.extract("https://acme.qlikcloud.com", "some-app")
        assert "API key" in str(exc.value)

    def test_api_key_from_env(self, monkeypatch):
        guid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        monkeypatch.setenv("QLIK_API_KEY", "env-key")
        captured = {}

        def fake_engine_extract(url, app_id, headers=None):
            captured["auth"] = (headers or {}).get("Authorization")
            return self._fake_engine_app()

        monkeypatch.setattr(live_engine, "extract", fake_engine_extract)
        monkeypatch.setattr(cloud, "fetch_data_connections", lambda t, k: [])
        cloud.extract("https://acme.qlikcloud.com", guid)  # no explicit key
        assert captured["auth"] == "Bearer env-key"
