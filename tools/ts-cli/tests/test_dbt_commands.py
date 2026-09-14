"""Command-level tests for `ts dbt` (dbt connection management + TML generation).

Covers: multipart form assembly for create/update, DBT_CLOUD vs ZIP_FILE
required-field validation, the access-token-env credential pattern (never a
literal flag value), and the plain-JSON list/delete/generate-tml/generate-sync-tml
calls.
"""
from __future__ import annotations

import json

import ts_cli.commands.dbt as dbt_mod
import ts_cli.dbt.cloud_api as cloud_api_mod
from ts_cli.dbt_build_export import build_model_tml_from_manifest
from ts_cli.cli import app

# Profile resolution, run lookup and artifact download moved out of
# `commands/dbt.py` into `ts_cli/dbt/cloud_api.py` (one implementation for
# list-models / inspect / build-model / trigger-job instead of three). Patch
# there, not on the command module -- a patch on `dbt_mod` now silently misses
# and the test hits the real dbt Cloud API.


def patch_dbt_cloud(monkeypatch, *, profiles=None, token="fake-token", get=None):
    """Point cloud_api's profile store, token lookup and HTTP at fakes."""
    if profiles is not None:
        monkeypatch.setattr(cloud_api_mod, "load_platform_profiles", lambda _p: profiles)
    monkeypatch.setattr(cloud_api_mod, "token_from_keychain",
                        lambda slug, profile=None: token)
    if get is not None:
        monkeypatch.setattr(cloud_api_mod, "_requests",
                            type("M", (), {"get": staticmethod(get)})())

from runners import runner  # noqa: E402  (BL-139: one definition, see runners.py)

# Sentinel for endpoints that return HTTP 204 with no body (e.g. dbt delete) —
# calling .json() on a real empty-body response raises, same as requests does.
NO_BODY = object()


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    @property
    def text(self):
        if self._payload is NO_BODY:
            return ""
        import json
        return json.dumps(self._payload)

    def json(self):
        if self._payload is NO_BODY:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


def _make_client(calls: list, payload=None):
    if payload is None:
        payload = {"dbt_connection_identifier": "conn-1"}

    class FakeClient:
        def __init__(self, profile_name):
            pass

        def post(self, path, **kwargs):
            # Mirror requests' real multipart behaviour: the body (incl. any
            # open file handle in `files`) is fully read before the call
            # returns, since dbt.py's `with open(...) as fh:` closes the
            # handle right after post() returns.
            files = kwargs.get("files")
            if files:
                materialized = {}
                for key, value in files.items():
                    if isinstance(value, tuple) and len(value) == 3 and hasattr(value[1], "read"):
                        filename, fh, content_type = value
                        materialized[key] = (filename, fh.read(), content_type)
                    else:
                        materialized[key] = value
                kwargs = {**kwargs, "files": materialized}
            calls.append((path, kwargs))
            return _FakeResp(payload)

    return FakeClient


def _patch(monkeypatch, calls, payload=None):
    monkeypatch.setattr(dbt_mod, "ThoughtSpotClient", _make_client(calls, payload))
    monkeypatch.setattr(dbt_mod, "resolve_profile", lambda p: "test-profile")


class TestCreateConnection:
    def test_dbt_cloud_requires_token_source(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        result = runner.invoke(app, [
            "dbt", "create",
            "--connection-name", "my_conn", "--database-name", "MY_DB",
            "--import-type", "DBT_CLOUD",
            "--dbt-url", "https://cloud.getdbt.com", "--account-id", "1", "--project-id", "2",
        ])
        assert result.exit_code != 0
        assert "--access-token-env or --dbt-cloud-profile is required" in result.output
        assert calls == []

    def test_dbt_cloud_errors_when_env_var_unset(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        result = runner.invoke(app, [
            "dbt", "create",
            "--connection-name", "my_conn", "--database-name", "MY_DB",
            "--import-type", "DBT_CLOUD", "--access-token-env", "DOES_NOT_EXIST_TOKEN_VAR",
        ])
        assert result.exit_code != 0
        assert "DOES_NOT_EXIST_TOKEN_VAR" in result.output
        assert calls == []

    def test_dbt_cloud_success_sends_multipart_fields_and_reads_token_from_env(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        monkeypatch.setenv("MY_DBT_TOKEN", "super-secret-token")
        result = runner.invoke(app, [
            "dbt", "create",
            "--connection-name", "my_conn", "--database-name", "MY_DB",
            "--import-type", "dbt_cloud", "--access-token-env", "MY_DBT_TOKEN",
            "--dbt-url", "https://cloud.getdbt.com", "--account-id", "1", "--project-id", "2",
        ])
        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        path, kwargs = calls[0]
        assert path == "/api/rest/2.0/dbt/dbt-connection"
        form = kwargs["files"]
        assert form["connection_name"] == (None, "my_conn")
        assert form["import_type"] == (None, "DBT_CLOUD")
        assert form["access_token"] == (None, "super-secret-token")
        # the token value itself must never appear in the CLI invocation
        assert "super-secret-token" not in result.output

    def test_dbt_cloud_profile_resolves_token_via_keyring(self, monkeypatch):
        """--dbt-cloud-profile reads the token from the OS credential store (no env var needed)."""
        import ts_cli.commands.dbt as dbt_mod_local
        calls = []
        _patch(monkeypatch, calls)

        # Stub get_profile to return a profile with keychain coordinates
        monkeypatch.setattr(
            dbt_mod_local, "get_profile",
            lambda platform, name: {
                "name": name,
                "keychain_service": "dbt-cloud-my-proj",
                "keychain_account": "token",
                "token_env": "DBT_CLOUD_TOKEN_MY_PROJ",
            } if name == "my-proj" else None,
        )

        # Stub keyring to return a token from the OS credential store
        import types
        fake_keyring = types.ModuleType("keyring")
        fake_keyring.get_password = lambda service, account: (
            "keychain-token-value" if service == "dbt-cloud-my-proj" and account == "token" else None
        )
        monkeypatch.setitem(__import__("sys").modules, "keyring", fake_keyring)

        result = runner.invoke(app, [
            "dbt", "create",
            "--connection-name", "my_conn", "--database-name", "MY_DB",
            "--import-type", "DBT_CLOUD",
            "--dbt-url", "https://cloud.getdbt.com", "--account-id", "1", "--project-id", "2",
            "--dbt-cloud-profile", "my-proj",
        ])
        assert result.exit_code == 0, result.output
        form = calls[0][1]["files"]
        assert form["access_token"] == (None, "keychain-token-value")
        # token value must not leak into CLI output
        assert "keychain-token-value" not in result.output

    def test_dbt_cloud_profile_falls_back_to_env_when_keyring_unavailable(self, monkeypatch):
        """When keyring is not installed, --dbt-cloud-profile falls back to token_env."""
        import ts_cli.commands.dbt as dbt_mod_local
        calls = []
        _patch(monkeypatch, calls)

        monkeypatch.setattr(
            dbt_mod_local, "get_profile",
            lambda platform, name: {
                "name": name,
                "keychain_service": "dbt-cloud-my-proj",
                "keychain_account": "token",
                "token_env": "FALLBACK_TOKEN_ENV",
            } if name == "my-proj" else None,
        )
        monkeypatch.setenv("FALLBACK_TOKEN_ENV", "env-fallback-token")
        # Simulate keyring not installed
        monkeypatch.setitem(__import__("sys").modules, "keyring", None)

        result = runner.invoke(app, [
            "dbt", "create",
            "--connection-name", "my_conn", "--database-name", "MY_DB",
            "--import-type", "DBT_CLOUD",
            "--dbt-url", "https://cloud.getdbt.com", "--account-id", "1", "--project-id", "2",
            "--dbt-cloud-profile", "my-proj",
        ])
        assert result.exit_code == 0, result.output
        form = calls[0][1]["files"]
        assert form["access_token"] == (None, "env-fallback-token")

    def test_zip_file_requires_file(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        result = runner.invoke(app, [
            "dbt", "create",
            "--connection-name", "my_conn", "--database-name", "MY_DB",
            "--import-type", "ZIP_FILE",
        ])
        assert result.exit_code != 0
        assert "--file is required" in result.output
        assert calls == []

    def test_zip_file_success_uploads_file_content(self, monkeypatch, tmp_path):
        calls = []
        _patch(monkeypatch, calls)
        zip_path = tmp_path / "manifest_catalog.zip"
        zip_path.write_bytes(b"PK\x03\x04fake-zip-bytes")
        result = runner.invoke(app, [
            "dbt", "create",
            "--connection-name", "my_conn", "--database-name", "MY_DB",
            "--import-type", "ZIP_FILE", "--file", str(zip_path),
        ])
        assert result.exit_code == 0, result.output
        path, kwargs = calls[0]
        form = kwargs["files"]
        assert form["import_type"] == (None, "ZIP_FILE")
        filename, fh, content_type = form["file_content"]
        assert filename == "manifest_catalog.zip"
        assert content_type == "application/zip"
        assert fh == b"PK\x03\x04fake-zip-bytes"

    def test_target_dir_is_packed_and_uploaded(self, monkeypatch, tmp_path):
        """--file target/ zips manifest+catalog for you. Requiring the user to
        make the archive by hand was a listed prerequisite of the ZIP_FILE
        path; it is a two-file operation over paths dbt already fixes."""
        import json as _json, zipfile as _zip
        calls = []
        _patch(monkeypatch, calls)
        target = tmp_path / "proj" / "target"
        target.mkdir(parents=True)
        (target / "manifest.json").write_text(_json.dumps({"nodes": {}}))
        (target / "catalog.json").write_text(_json.dumps({"nodes": {}}))

        result = runner.invoke(app, [
            "dbt", "create",
            "--connection-name", "my_conn", "--database-name", "MY_DB",
            "--import-type", "ZIP_FILE", "--file", str(target),
        ])
        assert result.exit_code == 0, result.output
        _path, kwargs = calls[0]
        filename, fh, content_type = kwargs["files"]["file_content"]
        assert content_type == "application/zip"
        assert filename.endswith(".zip")
        # The bytes that went up are a real archive holding both artifacts flat.
        import io
        with _zip.ZipFile(io.BytesIO(fh)) as zf:
            assert sorted(zf.namelist()) == ["catalog.json", "manifest.json"]

    def test_project_root_works_too(self, monkeypatch, tmp_path):
        import json as _json
        calls = []
        _patch(monkeypatch, calls)
        target = tmp_path / "proj" / "target"
        target.mkdir(parents=True)
        (target / "manifest.json").write_text(_json.dumps({"nodes": {}}))
        (target / "catalog.json").write_text(_json.dumps({"nodes": {}}))
        result = runner.invoke(app, [
            "dbt", "create",
            "--connection-name", "my_conn", "--database-name", "MY_DB",
            "--import-type", "ZIP_FILE", "--file", str(tmp_path / "proj"),
        ])
        assert result.exit_code == 0, result.output
        assert calls

    def test_missing_catalog_refuses_before_any_upload(self, monkeypatch, tmp_path):
        """A manifest-only archive imports with no column types rather than
        erroring, so the refusal has to happen here."""
        import json as _json
        calls = []
        _patch(monkeypatch, calls)
        target = tmp_path / "proj" / "target"
        target.mkdir(parents=True)
        (target / "manifest.json").write_text(_json.dumps({"nodes": {}}))
        result = runner.invoke(app, [
            "dbt", "create",
            "--connection-name", "my_conn", "--database-name", "MY_DB",
            "--import-type", "ZIP_FILE", "--file", str(target),
        ])
        assert result.exit_code != 0
        assert "dbt docs generate" in result.output
        assert calls == [], "nothing may be uploaded when catalog.json is missing"

    def test_invalid_import_type_rejected(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        result = runner.invoke(app, [
            "dbt", "create",
            "--connection-name", "my_conn", "--database-name", "MY_DB",
            "--import-type", "BOGUS",
        ])
        assert result.exit_code != 0
        assert "DBT_CLOUD" in result.output and "ZIP_FILE" in result.output
        assert calls == []


class TestUpdateConnection:
    def test_update_sends_connection_identifier_and_changed_fields_only(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        result = runner.invoke(app, [
            "dbt", "update",
            "--connection-id", "conn-123", "--project-name", "renamed_project",
        ])
        assert result.exit_code == 0, result.output
        path, kwargs = calls[0]
        assert path == "/api/rest/2.0/dbt/update-dbt-connection"
        form = kwargs["files"]
        assert form["dbt_connection_identifier"] == (None, "conn-123")
        assert form["project_name"] == (None, "renamed_project")
        assert "connection_name" not in form  # unset fields are omitted, not sent as empty


class TestListAndDelete:
    def test_list_posts_empty_body_to_search(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls, payload=[{"connection_id": "conn-1"}])
        result = runner.invoke(app, ["dbt", "list"])
        assert result.exit_code == 0, result.output
        path, kwargs = calls[0]
        assert path == "/api/rest/2.0/dbt/search"
        assert kwargs["json"] == {}
        assert json.loads(result.output) == [{"connection_id": "conn-1"}]

    def test_delete_hits_path_scoped_endpoint(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls, payload=NO_BODY)
        result = runner.invoke(app, ["dbt", "delete", "--connection-id", "conn-9"])
        assert result.exit_code == 0, result.output
        assert result.output == ""
        path, _ = calls[0]
        assert path == "/api/rest/2.0/dbt/conn-9/delete"


class TestGenerateTml:
    _MODEL_TABLES = '[{"model_name": "orders", "model_path": "models/orders.sql", "tables": ["orders"]}]'

    def test_generate_tml_without_file_for_dbt_cloud_connection(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        result = runner.invoke(app, [
            "dbt", "generate-tml", "--connection-id", "conn-1", "--model-tables", self._MODEL_TABLES,
        ])
        assert result.exit_code == 0, result.output
        path, kwargs = calls[0]
        assert path == "/api/rest/2.0/dbt/generate-tml"
        form = kwargs["files"]
        assert form["dbt_connection_identifier"] == (None, "conn-1")
        assert form["model_tables"] == (None, self._MODEL_TABLES)
        assert form["import_worksheets"] == (None, "ALL")  # default
        assert "worksheets" not in form
        assert "file_content" not in form
        assert "include_semantic_report" not in form  # None (unset) omitted, not "false"

    def test_generate_tml_with_semantic_report_flag(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        result = runner.invoke(app, [
            "dbt", "generate-tml", "--connection-id", "conn-1", "--model-tables", self._MODEL_TABLES,
            "--include-semantic-report",
        ])
        assert result.exit_code == 0, result.output
        _, kwargs = calls[0]
        assert kwargs["files"]["include_semantic_report"] == (None, "true")

    def test_generate_tml_requires_model_tables(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        result = runner.invoke(app, ["dbt", "generate-tml", "--connection-id", "conn-1"])
        assert result.exit_code != 0
        assert calls == []

    def test_generate_tml_rejects_invalid_import_worksheets(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        result = runner.invoke(app, [
            "dbt", "generate-tml", "--connection-id", "conn-1", "--model-tables", self._MODEL_TABLES,
            "--import-worksheets", "BOGUS",
        ])
        assert result.exit_code != 0
        assert "ALL" in result.output and "NONE" in result.output and "SELECTED" in result.output
        assert calls == []

    def test_generate_tml_selected_requires_worksheets(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        result = runner.invoke(app, [
            "dbt", "generate-tml", "--connection-id", "conn-1", "--model-tables", self._MODEL_TABLES,
            "--import-worksheets", "SELECTED",
        ])
        assert result.exit_code != 0
        assert "--worksheets is required" in result.output
        assert calls == []

    def test_generate_tml_selected_worksheets_sent(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        result = runner.invoke(app, [
            "dbt", "generate-tml", "--connection-id", "conn-1", "--model-tables", self._MODEL_TABLES,
            "--import-worksheets", "selected", "--worksheets", '["orders_worksheet"]',
        ])
        assert result.exit_code == 0, result.output
        _, kwargs = calls[0]
        form = kwargs["files"]
        assert form["import_worksheets"] == (None, "SELECTED")
        assert form["worksheets"] == (None, '["orders_worksheet"]')

    def test_generate_sync_tml_uploads_refreshed_zip(self, monkeypatch, tmp_path):
        calls = []
        _patch(monkeypatch, calls)
        zip_path = tmp_path / "refresh.zip"
        zip_path.write_bytes(b"PK\x03\x04refreshed")
        result = runner.invoke(app, [
            "dbt", "generate-sync-tml", "--connection-id", "conn-1", "--file", str(zip_path),
        ])
        assert result.exit_code == 0, result.output
        path, kwargs = calls[0]
        assert path == "/api/rest/2.0/dbt/generate-sync-tml"
        filename, fh, content_type = kwargs["files"]["file_content"]
        assert filename == "refresh.zip"
        assert fh == b"PK\x03\x04refreshed"

    def test_generate_tml_missing_file_errors_clearly(self, monkeypatch):
        calls = []
        _patch(monkeypatch, calls)
        result = runner.invoke(app, [
            "dbt", "generate-tml", "--connection-id", "conn-1", "--model-tables", self._MODEL_TABLES,
            "--file", "/no/such/path.zip",
        ])
        assert result.exit_code != 0
        assert "not found" in result.output
        assert calls == []


class TestGroupManifestModels:
    def _manifest(self, nodes):
        return {"nodes": {f"model.pkg.{n['name']}": n for n in nodes}}

    def test_groups_by_directory_uppercases_and_sorts(self):
        manifest = self._manifest([
            {"resource_type": "model", "name": "orders",    "original_file_path": "models/marts/core/orders.sql"},
            {"resource_type": "model", "name": "customers", "original_file_path": "models/marts/core/customers.sql"},
            {"resource_type": "model", "name": "stg_orders","original_file_path": "models/staging/stg_orders.sql"},
        ])
        result = dbt_mod._group_manifest_models(manifest)
        core = next(r for r in result if r["model_path"] == "models/marts/core")
        assert core["model_name"] == "core"
        assert core["tables"] == ["CUSTOMERS", "ORDERS"]
        staging = next(r for r in result if r["model_path"] == "models/staging")
        assert staging["tables"] == ["STG_ORDERS"]

    def test_skips_non_model_resource_types(self):
        manifest = self._manifest([
            {"resource_type": "test",   "name": "assert_positive", "original_file_path": "models/tests.sql"},
            {"resource_type": "model",  "name": "orders",          "original_file_path": "models/orders.sql"},
            {"resource_type": "source", "name": "raw_orders",      "original_file_path": "models/sources.yml"},
        ])
        result = dbt_mod._group_manifest_models(manifest)
        assert len(result) == 1
        assert result[0]["tables"] == ["ORDERS"]

    def test_empty_manifest_returns_empty_list(self):
        assert dbt_mod._group_manifest_models({}) == []
        assert dbt_mod._group_manifest_models({"nodes": {}}) == []


class TestListModels:
    _RUN_PAYLOAD = {"data": [{"id": 99}]}
    _MANIFEST_PAYLOAD = {
        "nodes": {
            "model.pkg.orders":    {"resource_type": "model", "name": "orders",    "original_file_path": "models/marts/core/orders.sql"},
            "model.pkg.customers": {"resource_type": "model", "name": "customers", "original_file_path": "models/marts/core/customers.sql"},
        }
    }

    def _fake_requests(self, monkeypatch, calls=None):
        """Patch _requests.get to return run + manifest payloads in sequence."""
        if calls is None:
            calls = []

        class _FakeResp2:
            def __init__(self, payload):
                self.ok = True
                self._payload = payload
            def json(self):
                return self._payload

        def fake_get(url, **kwargs):
            calls.append(url)
            if "runs" in url and "artifacts" not in url:
                return _FakeResp2(self._RUN_PAYLOAD)
            return _FakeResp2(self._MANIFEST_PAYLOAD)

        monkeypatch.setattr(cloud_api_mod, "_requests",
                            type("M", (), {"get": staticmethod(fake_get)})())
        return calls

    def test_errors_without_profile_or_access_token_env(self, monkeypatch):
        result = runner.invoke(app, [
            "dbt", "list-models", "--account-id", "1", "--project-id", "2",
        ])
        assert result.exit_code != 0
        assert "--dbt-cloud-profile" in result.output or "env var" in result.output.lower()

    def test_errors_when_access_token_env_unset(self, monkeypatch):
        result = runner.invoke(app, [
            "dbt", "list-models",
            "--account-id", "1", "--project-id", "2",
            "--access-token-env", "DOES_NOT_EXIST_DBT_TOKEN",
        ])
        assert result.exit_code != 0
        assert "DOES_NOT_EXIST_DBT_TOKEN" in result.output

    def test_outputs_model_tables_json_via_access_token_env(self, monkeypatch):
        monkeypatch.setenv("MY_DBT_TOKEN", "tok")
        calls = self._fake_requests(monkeypatch)
        result = runner.invoke(app, [
            "dbt", "list-models",
            "--account-id", "43692", "--project-id", "130012",
            "--access-token-env", "MY_DBT_TOKEN", "--dbt-env-id", "218891",
        ])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data[0]["model_name"] == "core"
        assert data[0]["tables"] == ["CUSTOMERS", "ORDERS"]
        assert any("runs" in c and "artifacts" not in c for c in calls)
        assert any("manifest.json" in c for c in calls)

    def test_dbt_cloud_profile_reads_coords_and_token_from_keychain(self, monkeypatch, tmp_path):
        profile_file = tmp_path / "dbt-cloud-profiles.json"
        profile_file.write_text(json.dumps([{
            "name": "my-test-proj",
            "account_id": "43692", "project_id": "130012",
            "dbt_env_id": "218891", "dbt_url": "https://cloud.getdbt.com",
            "auth_type": "token",
        }]))
        monkeypatch.setattr(cloud_api_mod, "load_platform_profiles",
                            lambda platform: json.loads(profile_file.read_text()))
        monkeypatch.setattr(
            cloud_api_mod, "token_from_keychain",
            lambda slug, profile=None: "keychain-tok" if slug == "my-test-proj" else None)
        calls = self._fake_requests(monkeypatch)
        result = runner.invoke(app, ["dbt", "list-models", "--dbt-cloud-profile", "my-test-proj"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data[0]["tables"] == ["CUSTOMERS", "ORDERS"]
        # project_id is in query params; verify both API calls were made
        assert len(calls) == 2

    def test_dbt_cloud_profile_not_found_errors(self, monkeypatch):
        monkeypatch.setattr(cloud_api_mod, "load_platform_profiles", lambda platform: [])
        result = runner.invoke(app, ["dbt", "list-models", "--dbt-cloud-profile", "ghost"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_dbt_cloud_profile_missing_keychain_token_errors(self, monkeypatch, tmp_path):
        profile_file = tmp_path / "dbt-cloud-profiles.json"
        profile_file.write_text(json.dumps([{
            "name": "my-test-proj", "account_id": "1", "project_id": "2", "auth_type": "token",
        }]))
        monkeypatch.setattr(cloud_api_mod, "load_platform_profiles",
                            lambda platform: json.loads(profile_file.read_text()))
        monkeypatch.setattr(cloud_api_mod, "token_from_keychain",
                            lambda slug, profile=None: None)
        result = runner.invoke(app, ["dbt", "list-models", "--dbt-cloud-profile", "my-test-proj"])
        assert result.exit_code != 0
        assert "keychain" in result.output.lower() or "token" in result.output.lower()

    def test_errors_when_no_successful_runs(self, monkeypatch):
        monkeypatch.setenv("MY_DBT_TOKEN", "tok")

        class _NoRuns:
            ok = True
            def json(self): return {"data": []}

        monkeypatch.setattr(cloud_api_mod, "_requests",
                            type("M", (), {"get": staticmethod(lambda url, **kw: _NoRuns())})())
        result = runner.invoke(app, [
            "dbt", "list-models",
            "--account-id", "1", "--project-id", "2", "--access-token-env", "MY_DBT_TOKEN",
        ])
        assert result.exit_code != 0
        assert "No successful runs" in result.output

    def test_alias_wins_over_model_name_by_default(self, monkeypatch):
        """open-items #15: a model with `alias:` materialises under the alias,
        and that is the only name ThoughtSpot's generate-tml matches. Emitting
        `name` 400s the whole call with "table(s) not found"."""
        monkeypatch.setenv("MY_DBT_TOKEN", "tok")
        aliased = {"nodes": {"model.pkg.stg_appointments": {
            "resource_type": "model", "name": "stg_appointments",
            "alias": "appointments",
            "original_file_path": "models/staging/barbershop/stg_appointments.sql"}}}
        monkeypatch.setattr(self, "_MANIFEST_PAYLOAD", aliased, raising=False)
        self._fake_requests(monkeypatch)
        args = ["dbt", "list-models", "--account-id", "1", "--project-id", "2",
                "--access-token-env", "MY_DBT_TOKEN"]
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)[0]["tables"] == ["APPOINTMENTS"]

        result = runner.invoke(app, args + ["--no-alias"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)[0]["tables"] == ["STG_APPOINTMENTS"]

    def test_manifest_flag_reads_local_file_without_any_http(self, monkeypatch, tmp_path):
        """The ZIP_FILE path: no dbt Cloud profile, no token, no network."""
        def _boom(*_a, **_k):
            raise AssertionError("--manifest must not touch the dbt Cloud API")
        monkeypatch.setattr(cloud_api_mod, "_requests",
                            type("M", (), {"get": staticmethod(_boom)})())
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(self._MANIFEST_PAYLOAD))
        result = runner.invoke(app, ["dbt", "list-models", "--manifest", str(mf)])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)[0]["tables"] == ["CUSTOMERS", "ORDERS"]

    def test_manifest_flag_accepts_a_target_dir_and_a_zip(self, tmp_path):
        import zipfile
        target = tmp_path / "proj" / "target"
        target.mkdir(parents=True)
        (target / "manifest.json").write_text(json.dumps(self._MANIFEST_PAYLOAD))
        result = runner.invoke(app, ["dbt", "list-models", "--manifest", str(tmp_path / "proj")])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)[0]["tables"] == ["CUSTOMERS", "ORDERS"]

        zpath = tmp_path / "proj.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("target/manifest.json", json.dumps(self._MANIFEST_PAYLOAD))
        result = runner.invoke(app, ["dbt", "list-models", "--manifest", str(zpath)])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)[0]["tables"] == ["CUSTOMERS", "ORDERS"]


class TestBuildModelFromManifest:
    """Unit tests for build_model_tml_from_manifest."""

    def _make_manifest(self, model_path="models/staging/barbershop"):
        """Minimal manifest with two fact tables sharing a dimension (chasm join)."""
        nodes = {}
        for name in ("stg_appointments", "stg_bs_customers", "stg_product_sales"):
            uid = f"model.proj.{name}"
            nodes[uid] = {
                "resource_type": "model",
                "name": name,
                "original_file_path": f"{model_path}/{name}.sql",
                "columns": {
                    "CUSTOMER_ID": {
                        "name": "CUSTOMER_ID",
                        "description": "Customer FK",
                        "meta": {"ts_column_type": "attribute"},
                    },
                    "AMOUNT": {
                        "name": "AMOUNT",
                        "meta": {"ts_column_type": "measure", "ts_aggregation": "sum"},
                    },
                },
            }
        nodes["test.proj.rel_appt_cust"] = {
            "resource_type": "test",
            "original_file_path": f"{model_path}/schema.yml",
            "test_metadata": {
                "name": "relationships",
                "kwargs": {
                    "column_name": "CUSTOMER_ID",
                    "to": "ref('stg_bs_customers')",
                    "field": "CUSTOMER_ID",
                    "model": "{{ get_where_subquery(ref('stg_appointments')) }}",
                },
            },
            "config": {"meta": {
                "ts_join_name": "appt_to_cust",
                "ts_join_cardinality": "many_to_one",
                "ts_join_type": "left_outer",
            }},
        }
        nodes["test.proj.rel_ps_cust"] = {
            "resource_type": "test",
            "original_file_path": f"{model_path}/schema.yml",
            "test_metadata": {
                "name": "relationships",
                "kwargs": {
                    "column_name": "CUSTOMER_ID",
                    "to": "ref('stg_bs_customers')",
                    "field": "CUSTOMER_ID",
                    "model": "{{ get_where_subquery(ref('stg_product_sales')) }}",
                },
            },
            "config": {"meta": {
                "ts_join_name": "ps_to_cust",
                "ts_join_cardinality": "many_to_one",
                "ts_join_type": "left_outer",
            }},
        }
        return {"nodes": nodes}

    def test_join_graph_assembled(self):
        manifest = self._make_manifest()
        result = build_model_tml_from_manifest(manifest, {}, "models/staging/barbershop", "BARBERSHOP")
        model = result["model"]
        assert model["name"] == "BARBERSHOP"
        mt_by_name = {mt["name"]: mt for mt in model["model_tables"]}
        assert "STG_APPOINTMENTS" in mt_by_name
        assert "STG_PRODUCT_SALES" in mt_by_name
        assert "STG_BS_CUSTOMERS" in mt_by_name

        appt_joins = mt_by_name["STG_APPOINTMENTS"].get("joins", [])
        assert any(j["with"] == "STG_BS_CUSTOMERS" for j in appt_joins)
        assert appt_joins[0]["type"] == "LEFT_OUTER"
        assert appt_joins[0]["cardinality"] == "MANY_TO_ONE"
        assert appt_joins[0]["name"] == "appt_to_cust"

    def test_shared_dimension_both_fact_tables_join_it(self):
        manifest = self._make_manifest()
        result = build_model_tml_from_manifest(manifest, {}, "models/staging/barbershop", "BARBERSHOP")
        mt_by_name = {mt["name"]: mt for mt in result["model"]["model_tables"]}
        appt_joins = mt_by_name["STG_APPOINTMENTS"].get("joins", [])
        ps_joins = mt_by_name["STG_PRODUCT_SALES"].get("joins", [])
        assert any(j["with"] == "STG_BS_CUSTOMERS" for j in appt_joins)
        assert any(j["with"] == "STG_BS_CUSTOMERS" for j in ps_joins)

    def test_column_metadata_from_manifest(self):
        manifest = self._make_manifest()
        result = build_model_tml_from_manifest(manifest, {}, "models/staging/barbershop", "BARBERSHOP")
        columns = result["model"]["columns"]
        amount_cols = [c for c in columns if "AMOUNT" in c["name"]]
        assert amount_cols, "AMOUNT column missing"
        for c in amount_cols:
            assert c["properties"]["column_type"] == "MEASURE"
            assert c["properties"]["aggregation"] == "SUM"

    def test_excludes_models_outside_model_path(self):
        manifest = self._make_manifest()
        manifest["nodes"]["model.proj.other"] = {
            "resource_type": "model",
            "name": "other",
            "original_file_path": "models/marts/core/other.sql",
            "columns": {},
        }
        result = build_model_tml_from_manifest(manifest, {}, "models/staging/barbershop", "BARBERSHOP")
        mt_names = {mt["name"] for mt in result["model"]["model_tables"]}
        assert "OTHER" not in mt_names

    def test_empty_manifest_returns_empty_model(self):
        result = build_model_tml_from_manifest({}, {}, "models/staging/barbershop", "BARBERSHOP")
        model = result["model"]
        assert model["name"] == "BARBERSHOP"
        assert model["model_tables"] == []
        assert model["columns"] == []


class TestTriggerJob:
    """Tests for ts dbt trigger-job command helpers."""

    _PROFILE = {"name": "test-profile", "account_id": "12345", "project_id": "67890",
                "dbt_url": "https://cloud.getdbt.com"}

    def _mock_platform_profiles(self, monkeypatch):
        monkeypatch.setattr(
            "ts_cli.dbt.cloud_api.load_platform_profiles",
            lambda _: [self._PROFILE])

    def _mock_keychain(self, monkeypatch, token="fake-token"):
        monkeypatch.setattr(
            "ts_cli.dbt.cloud_api.token_from_keychain",
            lambda _slug, profile=None: token)

    def test_list_jobs_when_no_job_id(self, monkeypatch, capsys):
        self._mock_platform_profiles(monkeypatch)
        self._mock_keychain(monkeypatch)

        jobs_data = {"data": [{"id": 100, "name": "Daily Run", "description": "prod"}]}
        runs_data = {"data": [{"job_definition_id": 100, "status": 10, "finished_at": "2026-09-04T10:00:00Z"}]}

        call_count = {"n": 0}

        def mock_get(url, **kwargs):
            r = type("R", (), {})()
            r.ok = True
            call_count["n"] += 1
            if "jobs" in url:
                r.json = lambda: jobs_data
            else:
                r.json = lambda: runs_data
            return r

        monkeypatch.setattr("ts_cli.commands.dbt._requests.get", mock_get)

        from typer.testing import CliRunner
        from ts_cli.commands.dbt import app
        runner = CliRunner()
        result = runner.invoke(app, ["trigger-job", "--dbt-cloud-profile", "test-profile"])
        assert result.exit_code == 0
        import json
        jobs = json.loads(result.stdout)
        assert jobs[0]["id"] == 100
        assert jobs[0]["name"] == "Daily Run"
        assert jobs[0]["last_successful_run"] == "2026-09-04T10:00:00Z"
        assert call_count["n"] == 2  # jobs + runs

    def test_trigger_and_wait_success(self, monkeypatch, capsys):
        self._mock_platform_profiles(monkeypatch)
        self._mock_keychain(monkeypatch)

        call_count = {"n": 0}

        def mock_get(url, **kwargs):
            r = type("R", (), {})()
            r.ok = True
            # First poll: Running (3), second poll: Success (10)
            call_count["n"] += 1
            if call_count["n"] == 1:
                r.json = lambda: {"data": {"id": 999, "status": 3, "finished_at": None}}
            else:
                r.json = lambda: {"data": {"id": 999, "status": 10, "finished_at": "2026-09-04T12:00:00Z"}}
            return r

        def mock_post(url, **kwargs):
            r = type("R", (), {})()
            r.ok = True
            r.json = lambda: {"data": {"id": 999, "status": 1}}
            return r

        monkeypatch.setattr("ts_cli.commands.dbt._requests.get", mock_get)
        monkeypatch.setattr("ts_cli.commands.dbt._requests.post", mock_post)
        monkeypatch.setattr("time.sleep", lambda _: None)

        from typer.testing import CliRunner
        from ts_cli.commands.dbt import app
        import json
        runner = CliRunner()
        result = runner.invoke(
            app, ["trigger-job", "--dbt-cloud-profile", "test-profile",
                  "--job-id", "42", "--poll-interval", "1"])
        assert result.exit_code == 0
        out = json.loads(result.stdout)
        assert out["run_id"] == 999
        assert out["status"] == "Success"
        assert out["finished_at"] == "2026-09-04T12:00:00Z"

    def test_trigger_no_wait(self, monkeypatch):
        self._mock_platform_profiles(monkeypatch)
        self._mock_keychain(monkeypatch)

        def mock_post(url, **kwargs):
            r = type("R", (), {})()
            r.ok = True
            r.json = lambda: {"data": {"id": 888, "status": 1}}
            return r

        monkeypatch.setattr("ts_cli.commands.dbt._requests.post", mock_post)

        from typer.testing import CliRunner
        from ts_cli.commands.dbt import app
        import json
        runner = CliRunner()
        result = runner.invoke(
            app, ["trigger-job", "--dbt-cloud-profile", "test-profile",
                  "--job-id", "42", "--no-wait"])
        assert result.exit_code == 0
        out = json.loads(result.stdout)
        assert out["run_id"] == 888
        assert out["status"] == "triggered"

    def test_trigger_error_run_exits_nonzero(self, monkeypatch):
        self._mock_platform_profiles(monkeypatch)
        self._mock_keychain(monkeypatch)

        def mock_get(url, **kwargs):
            r = type("R", (), {})()
            r.ok = True
            data = {"id": 777, "status": 20, "finished_at": "2026-09-04T12:00:00Z"}
            if "include_related" in (kwargs.get("params") or {}):
                data["run_steps"] = [
                    {"index": 1, "name": "Clone git repository", "status": 10,
                     "status_humanized": "Success", "logs": "ok"},
                    {"index": 4, "name": "Invoke dbt with `dbt build`", "status": 20,
                     "status_humanized": "Error",
                     "logs": "22:17:28  Running dbt...\n"
                             "22:17:30  Sending event: {'category': 'dbt'}\n"
                             "22:17:30  Invalid name `TRANSACTION_DATE` - names may only contain "
                             "lower case letters, numbers, and underscores.\n"
                             "22:17:30  Encountered an error:\nParsing Error\n"
                             "  Semantic Manifest validation failed.\ndbt command failed"},
                ]
            r.json = lambda: {"data": data}
            return r

        def mock_post(url, **kwargs):
            r = type("R", (), {})()
            r.ok = True
            r.json = lambda: {"data": {"id": 777, "status": 1}}
            return r

        monkeypatch.setattr("ts_cli.commands.dbt._requests.get", mock_get)
        monkeypatch.setattr("ts_cli.commands.dbt._requests.post", mock_post)
        monkeypatch.setattr("time.sleep", lambda _: None)

        from typer.testing import CliRunner
        from ts_cli.commands.dbt import app
        runner = CliRunner()
        result = runner.invoke(
            app, ["trigger-job", "--dbt-cloud-profile", "test-profile",
                  "--job-id", "42", "--poll-interval", "1"])
        assert result.exit_code != 0
        assert "Error" in result.output
        # The failed step's log is surfaced so the user never has to open dbt Cloud
        assert "Failed step: Invoke dbt with `dbt build`" in result.output
        assert "Invalid name `TRANSACTION_DATE`" in result.output
        assert "Semantic Manifest validation failed" in result.output
        assert "Sending event" not in result.output
        assert "See the failed-step log above." in result.output

    def test_missing_profile_errors(self, monkeypatch):
        monkeypatch.setattr(
            "ts_cli.commands.dbt.load_platform_profiles",
            lambda _: [])

        from typer.testing import CliRunner
        from ts_cli.commands.dbt import app
        runner = CliRunner()
        result = runner.invoke(
            app, ["trigger-job", "--dbt-cloud-profile", "nonexistent"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# _resolve_table_guids — fqn pinning for build-model when an Org holds
# same-named Tables (e.g. raw source tables registered alongside the dbt views)
# ---------------------------------------------------------------------------

class TestResolveTableGuids:
    _LOCS = {
        "BARBERS": {"database": "DL_TEST", "schema": "dbt_dlee_prod", "db_table": "barbers"},
        "SERVICES": {"database": "DL_TEST", "schema": "dbt_dlee_prod", "db_table": "services"},
    }

    @staticmethod
    def _hit(name, guid):
        return {"metadata_id": guid, "metadata_header": {"name": name}}

    @staticmethod
    def _edoc(guid, db, schema, db_table):
        return {
            "info": {"id": guid},
            "edoc": f"table:\n  name: X\n  db: {db}\n  schema: {schema}\n  db_table: {db_table}\n",
        }

    def _client(self, search_by_name, export_items):
        calls = []

        class C:
            def post(self, path, **kwargs):
                calls.append((path, kwargs))
                body = kwargs["json"]
                if path.endswith("/metadata/search"):
                    return _FakeResp(search_by_name.get(body["metadata"][0]["identifier"], []))
                if path.endswith("/metadata/tml/export"):
                    wanted = {m["identifier"] for m in body["metadata"]}
                    return _FakeResp([i for i in export_items if i["info"]["id"] in wanted])
                raise AssertionError(path)

        return C(), calls

    def test_single_hit_resolves_without_export(self):
        client, calls = self._client({"SERVICES": [self._hit("SERVICES", "g-svc")]}, [])
        out = dbt_mod._resolve_table_guids(client, self._LOCS, ["SERVICES"])
        assert out == {"SERVICES": "g-svc"}
        assert all(p.endswith("/metadata/search") for p, _ in calls)

    def test_duplicates_disambiguated_by_manifest_location(self, capsys):
        client, calls = self._client(
            {"BARBERS": [self._hit("BARBERS", "g-old"), self._hit("BARBERS", "g-new")]},
            [self._edoc("g-old", "DL_TEST", "BARBERSHOP_DEMO", "BARBERS"),
             self._edoc("g-new", "DL_TEST", "DBT_DLEE_PROD", "BARBERS")],
        )
        out = dbt_mod._resolve_table_guids(client, self._LOCS, ["BARBERS"])
        assert out == {"BARBERS": "g-new"}
        export_call = next(k for p, k in calls if p.endswith("/tml/export"))
        assert {m["identifier"] for m in export_call["json"]["metadata"]} == {"g-old", "g-new"}
        assert export_call["json"]["export_fqn"] is False
        assert "picked g-new" in capsys.readouterr().err

    def test_duplicates_with_no_location_match_exit_with_listing(self):
        client, _ = self._client(
            {"BARBERS": [self._hit("BARBERS", "g-a"), self._hit("BARBERS", "g-b")]},
            [self._edoc("g-a", "DL_TEST", "OTHER_A", "BARBERS"),
             self._edoc("g-b", "DL_TEST", "OTHER_B", "BARBERS")],
        )
        import pytest
        with pytest.raises(SystemExit) as ei:
            dbt_mod._resolve_table_guids(client, self._LOCS, ["BARBERS"])
        msg = str(ei.value)
        assert "g-a" in msg and "g-b" in msg and "DL_TEST.DBT_DLEE_PROD.BARBERS" in msg

    def test_no_hit_warns_and_leaves_unresolved(self, capsys):
        client, _ = self._client({}, [])
        out = dbt_mod._resolve_table_guids(client, self._LOCS, ["SERVICES"])
        assert out == {}
        assert "no LOGICAL_TABLE named 'SERVICES'" in capsys.readouterr().err

    def test_substring_hits_are_ignored(self):
        # metadata/search may return PRODUCT_SALES for identifier PRODUCTS — only
        # exact (case-insensitive) name matches count as candidates.
        client, _ = self._client(
            {"PRODUCTS": [self._hit("PRODUCT_SALES", "g-ps"), self._hit("products", "g-p")]}, [])
        assert dbt_mod._resolve_table_guids(client, {}, ["PRODUCTS"]) == {"PRODUCTS": "g-p"}


# ---------------------------------------------------------------------------
# build-model: --pretty-names and --model-guid (update in place)
# ---------------------------------------------------------------------------

class TestBuildModelFlags:
    _RUN = {"data": [{"id": 7}]}
    _MANIFEST = {"nodes": {
        "model.p.barbers": {"resource_type": "model", "name": "barbers",
                            "database": "DL_TEST", "schema": "dbt", "alias": "barbers",
                            "original_file_path": "models/staging/barbershop/barbers.sql",
                            "columns": {"HOURLY_RATE": {"config": {"meta": {"ts_column_type": "measure"}}}}},
    }}

    def _setup(self, monkeypatch, tmp_path):
        import yaml
        profile_file = tmp_path / "dbt-cloud-profiles.json"
        profile_file.write_text(json.dumps([{
            "name": "p", "account_id": "1", "project_id": "2", "dbt_env_id": "3",
            "dbt_url": "https://cloud.getdbt.com", "auth_type": "token"}]))
        monkeypatch.setattr(cloud_api_mod, "load_platform_profiles",
                            lambda plat: json.loads(profile_file.read_text()))
        monkeypatch.setattr(cloud_api_mod, "token_from_keychain",
                            lambda slug, profile=None: "tok")

        class _R:
            def __init__(self, p): self.ok, self._p = True, p
            def json(self): return self._p
        def fake_get(url, **kw):
            if "artifacts" not in url: return _R(self._RUN)
            return _R(self._MANIFEST if "manifest" in url else {})
        monkeypatch.setattr(cloud_api_mod, "_requests",
                            type("M", (), {"get": staticmethod(fake_get)})())

        calls = []
        class C:
            def __init__(self, *_): pass
            def post(self, path, **kw):
                calls.append((path, kw))
                if path.endswith("/metadata/search"):
                    return _FakeResp([{"metadata_id": "g-barbers", "metadata_header": {"name": "BARBERS"}}])
                return _FakeResp([{"response": {"status": {"status_code": "OK"}}}])
        monkeypatch.setattr(dbt_mod, "ThoughtSpotClient", C)
        monkeypatch.setattr(dbt_mod, "resolve_profile", lambda p: "tp")
        return calls, yaml

    def _imported_tml(self, calls, yaml):
        path, kw = next((p, k) for p, k in calls if p.endswith("/tml/import"))
        return yaml.safe_load(kw["json"]["metadata_tmls"][0]), kw["json"]

    def test_pretty_names_and_fqn_in_imported_tml(self, monkeypatch, tmp_path):
        calls, yaml = self._setup(monkeypatch, tmp_path)
        result = runner.invoke(app, ["dbt", "build-model", "--dbt-cloud-profile", "p",
                                     "--model-path", "models/staging/barbershop",
                                     "--model-name", "M", "--pretty-names"])
        assert result.exit_code == 0, result.output
        tml, body = self._imported_tml(calls, yaml)
        assert "guid" not in tml and body["create_new"] is True
        assert tml["model"]["model_tables"][0]["fqn"] == "g-barbers"
        col = tml["model"]["columns"][0]
        assert col["name"] == "Hourly Rate" and col["column_id"] == "BARBERS::HOURLY_RATE"

    def test_model_guid_updates_in_place(self, monkeypatch, tmp_path):
        calls, yaml = self._setup(monkeypatch, tmp_path)
        result = runner.invoke(app, ["dbt", "build-model", "--dbt-cloud-profile", "p",
                                     "--model-path", "models/staging/barbershop",
                                     "--model-name", "M", "--model-guid", "m-123"])
        assert result.exit_code == 0, result.output
        tml, body = self._imported_tml(calls, yaml)
        assert tml["guid"] == "m-123" and list(tml)[0] == "guid"   # root-level guid, first key
        assert body["create_new"] is False
        assert tml["model"]["columns"][0]["name"] == "HOURLY_RATE"  # no --pretty-names → verbatim


# ---------------------------------------------------------------------------
# Token resolution order: env var (from ~/.zshenv) before a Python-side Keychain
# read, which prompts for the keychain password on every call.
# ---------------------------------------------------------------------------

class TestTokenResolutionPrefersEnv:
    _PROFILE = {"name": "my-test-proj", "token_env": "DBT_CLOUD_TOKEN_MY_TEST_PROJ",
                "keychain_service": "dbt-cloud-my-test-proj", "keychain_account": "token"}

    def _fake_keyring(self, monkeypatch, calls):
        class K:
            @staticmethod
            def get_password(svc, acct):
                calls.append((svc, acct)); return "from-keychain"
        monkeypatch.setitem(__import__("sys").modules, "keyring", K)

    def test_read_access_token_uses_env_without_touching_keychain(self, monkeypatch):
        calls = []; self._fake_keyring(monkeypatch, calls)
        monkeypatch.setenv("DBT_CLOUD_TOKEN_MY_TEST_PROJ", "from-env")
        assert dbt_mod._read_access_token(None, self._PROFILE) == "from-env"
        assert calls == []

    def test_read_access_token_falls_back_to_keychain(self, monkeypatch):
        calls = []; self._fake_keyring(monkeypatch, calls)
        monkeypatch.delenv("DBT_CLOUD_TOKEN_MY_TEST_PROJ", raising=False)
        assert dbt_mod._read_access_token(None, self._PROFILE) == "from-keychain"
        assert calls == [("dbt-cloud-my-test-proj", "token")]

    def test_token_from_keychain_prefers_derived_env_var(self, monkeypatch):
        calls = []; self._fake_keyring(monkeypatch, calls)
        monkeypatch.setenv("DBT_CLOUD_TOKEN_MY_TEST_PROJ", "from-env")
        assert dbt_mod._token_from_keychain("my-test-proj") == "from-env"
        assert calls == []
        monkeypatch.delenv("DBT_CLOUD_TOKEN_MY_TEST_PROJ")
        assert dbt_mod._token_from_keychain("my-test-proj") == "from-keychain"


class TestBuildModelFailsFast:
    # Reuse the fixture plumbing without inheriting TestBuildModelFlags' tests
    # (they would re-run against this colliding manifest and fail).
    _RUN = TestBuildModelFlags._RUN
    _setup = TestBuildModelFlags._setup
    _MANIFEST = {"nodes": {
        "model.p.appointments": {"resource_type": "model", "name": "appointments",
            "database": "DL_TEST", "schema": "dbt", "alias": "appointments",
            "original_file_path": "models/staging/barbershop/appointments.sql",
            "columns": {
                "APPOINTMENT_DATETIME": {"config": {"meta": {"ts_column_type": "attribute",
                                                              "ts_display_name": "Appointment Time"}}},
                "APPOINTMENT_TIME": {"config": {"meta": {"ts_column_type": "attribute"}}},
            }},
    }}

    def test_display_name_collision_exits_before_import(self, monkeypatch, tmp_path):
        calls, _ = self._setup(monkeypatch, tmp_path)
        result = runner.invoke(app, ["dbt", "build-model", "--dbt-cloud-profile", "p",
                                     "--model-path", "models/staging/barbershop",
                                     "--model-name", "M", "--pretty-names"])
        assert result.exit_code != 0
        assert "APPOINTMENTS::APPOINTMENT_DATETIME" in result.output
        assert "APPOINTMENTS::APPOINTMENT_TIME" in result.output
        assert not any(p.endswith("/tml/import") for p, _ in calls)

    def test_error_status_from_import_exits_nonzero_and_skips_rls(self, monkeypatch, tmp_path):
        calls, _ = self._setup(monkeypatch, tmp_path)
        # no --pretty-names → APPOINTMENT_TIME stays verbatim, no collision; force an API ERROR instead
        client_cls = dbt_mod.ThoughtSpotClient
        class Failing(client_cls):
            def post(self, path, **kw):
                if path.endswith("/tml/import"):
                    calls.append((path, kw))
                    return _FakeResp([{"response": {"status": {"status_code": "ERROR",
                                                                "error_message": "boom"}}}])
                return super().post(path, **kw)
        monkeypatch.setattr(dbt_mod, "ThoughtSpotClient", Failing)
        result = runner.invoke(app, ["dbt", "build-model", "--dbt-cloud-profile", "p",
                                     "--model-path", "models/staging/barbershop", "--model-name", "M"])
        assert result.exit_code != 0 and "boom" in result.output
        assert not any(p.endswith("/tml/export") for p, _ in calls)   # RLS step not reached


class TestFailedStepLogExcerpt:
    """Pure-function tests for ts_cli.commands.dbt.failed_step_log_excerpt."""

    def test_returns_empty_when_no_step_failed(self):
        from ts_cli.commands.dbt import failed_step_log_excerpt
        steps = [{"index": 1, "name": "Clone", "status": 10, "status_humanized": "Success", "logs": "x"}]
        assert failed_step_log_excerpt(steps) == ""
        assert failed_step_log_excerpt([]) == ""
        assert failed_step_log_excerpt(None) == ""

    def test_picks_first_failed_step_and_strips_ansi_and_noise(self):
        from ts_cli.commands.dbt import failed_step_log_excerpt
        steps = [
            {"index": 1, "name": "Clone", "status": 10, "status_humanized": "Success", "logs": "ok"},
            {"index": 4, "name": "dbt build", "status": 20, "status_humanized": "Error",
             "logs": "a\n\n\x1b[33mWARNING\x1b[0m deprecated\nSending event: {x}\n"
                     "Observability Metric: y\nInvalid name `STATUS`\ndbt command failed"},
            {"index": 5, "name": "docs", "status": 20, "status_humanized": "Error", "logs": "later"},
        ]
        out = failed_step_log_excerpt(steps)
        assert out.startswith("Failed step: dbt build\n")
        assert "\x1b" not in out and "WARNING deprecated" in out
        assert "Sending event" not in out and "Observability" not in out
        assert "Invalid name `STATUS`" in out and out.endswith("dbt command failed")
        assert "later" not in out

    def test_tail_is_capped_and_uses_status_humanized_fallback(self):
        from ts_cli.commands.dbt import failed_step_log_excerpt
        logs = "\n".join(f"line {i}" for i in range(100))
        steps = [{"index": 4, "name": "dbt build", "status_humanized": "Cancelled", "logs": logs}]
        out = failed_step_log_excerpt(steps, max_lines=5)
        body = out.split("\n")[1:]
        assert body == [f"line {i}" for i in range(95, 100)]

    def test_failed_step_without_logs_is_named(self):
        from ts_cli.commands.dbt import failed_step_log_excerpt
        steps = [{"index": 4, "name": "dbt build", "status": 20, "status_humanized": "Error", "logs": ""}]
        assert failed_step_log_excerpt(steps) == "Failed step: dbt build (no log text returned)"
