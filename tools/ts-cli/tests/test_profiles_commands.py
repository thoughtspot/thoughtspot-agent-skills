"""Tests for profiles Typer commands (list, add, update, remove, sync-env)."""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from ts_cli import profile_ops
from ts_cli.commands.profiles import app

runner = CliRunner()


@pytest.fixture
def profile_dir(tmp_path, monkeypatch):
    """Point PROFILE_PATHS at temp files; also patch PROFILES_PATH for list default."""
    paths = {
        "thoughtspot": tmp_path / "thoughtspot-profiles.json",
        "snowflake": tmp_path / "snowflake-profiles.json",
        "databricks": tmp_path / "databricks-profiles.json",
        "tableau": tmp_path / "tableau-profiles.json",
    }
    monkeypatch.setattr(profile_ops, "PROFILE_PATHS", paths)
    return paths


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestListCommand:
    def test_list_json_empty(self, profile_dir):
        result = runner.invoke(app, ["list", "--json", "--snowflake"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_list_json_returns_stripped_profiles(self, profile_dir):
        profile_dir["snowflake"].write_text(json.dumps([
            {"name": "Prod", "account": "acct1", "password_env": "SECRET"}
        ]))
        result = runner.invoke(app, ["list", "--json", "--snowflake"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["name"] == "Prod"
        assert "password_env" not in data[0]

    def test_list_json_databricks(self, profile_dir):
        profile_dir["databricks"].write_text(json.dumps([
            {"name": "Dev", "host": "https://dbx.example.com", "secret_env": "S"}
        ]))
        result = runner.invoke(app, ["list", "--json", "--databricks"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["name"] == "Dev"
        assert "secret_env" not in data[0]

    def test_list_json_tableau(self, profile_dir):
        profile_dir["tableau"].write_text(json.dumps([
            {"name": "Server1", "server_url": "https://tab", "pat_secret_env": "S"}
        ]))
        result = runner.invoke(app, ["list", "--json", "--tableau"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "pat_secret_env" not in data[0]

    def test_list_databricks_table_format(self, profile_dir):
        profile_dir["databricks"].write_text(json.dumps([
            {"name": "Workspace1", "auth_type": "pat", "host": "https://dbx.cloud"}
        ]))
        result = runner.invoke(app, ["list", "--databricks"])
        assert result.exit_code == 0
        assert "Workspace1" in result.output
        assert "pat" in result.output

    def test_list_snowflake_table_format(self, profile_dir):
        profile_dir["snowflake"].write_text(json.dumps([
            {"name": "Staging", "method": "python", "account": "xy12345.us-east-1"}
        ]))
        result = runner.invoke(app, ["list", "--snowflake"])
        assert result.exit_code == 0
        assert "Staging" in result.output
        assert "python" in result.output


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


class TestAddCommand:
    def test_add_thoughtspot_token(self, profile_dir):
        result = runner.invoke(app, [
            "add",
            "--platform", "thoughtspot",
            "--name", "My Staging",
            "--auth-type", "token",
            "--field", "base_url=https://ts.example.com",
            "--field", "username=admin",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["slug"] == "my-staging"
        assert data["env_var"] == "THOUGHTSPOT_TOKEN_MY_STAGING"
        assert data["keychain_service"] == "thoughtspot-my-staging"
        assert data["profile"]["token_env"] == "THOUGHTSPOT_TOKEN_MY_STAGING"
        assert data["keychain_store_commands"] is not None
        assert "security add-generic-password" in data["keychain_store_commands"]["darwin"]

    def test_add_snowflake_key_pair(self, profile_dir):
        result = runner.invoke(app, [
            "add",
            "--platform", "snowflake",
            "--name", "Partner AP",
            "--auth-type", "key_pair",
            "--field", "account=xy12345.ap-southeast-2",
            "--field", "username=SVC_USER",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["profile"]["method"] == "python"
        assert data["profile"]["auth"] == "key_pair"
        assert data["keychain_store_commands"] is None

    def test_add_databricks_pat(self, profile_dir):
        result = runner.invoke(app, [
            "add",
            "--platform", "databricks",
            "--name", "Dev",
            "--auth-type", "pat",
            "--field", "host=https://dbx.cloud.databricks.com",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["env_var"] == "DATABRICKS_TOKEN_DEV"
        assert data["profile"]["dbx_profile"] == "ts-dev"
        assert data["keychain_account"] == "token"

    def test_add_tableau_pat(self, profile_dir):
        result = runner.invoke(app, [
            "add",
            "--platform", "tableau",
            "--name", "Cloud",
            "--auth-type", "pat",
            "--field", "server_url=https://10ay.online.tableau.com",
            "--field", "pat_name=my-token",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["env_var"] == "TABLEAU_PAT_SECRET_CLOUD"
        assert data["keychain_account"] == "my-token"

    def test_add_saves_to_disk(self, profile_dir):
        runner.invoke(app, [
            "add", "--platform", "snowflake", "--name", "New",
            "--auth-type", "password", "--field", "account=acct1",
        ])
        saved = json.loads(profile_dir["snowflake"].read_text())
        assert len(saved) == 1
        assert saved[0]["name"] == "New"

    def test_add_replaces_existing(self, profile_dir):
        runner.invoke(app, [
            "add", "--platform", "snowflake", "--name", "A",
            "--auth-type", "password", "--field", "account=old",
        ])
        runner.invoke(app, [
            "add", "--platform", "snowflake", "--name", "A",
            "--auth-type", "password", "--field", "account=new",
        ])
        saved = json.loads(profile_dir["snowflake"].read_text())
        assert len(saved) == 1
        assert saved[0]["account"] == "new"

    def test_add_unknown_platform_fails(self, profile_dir):
        result = runner.invoke(app, [
            "add", "--platform", "bogus", "--name", "X",
            "--auth-type", "token",
        ])
        assert result.exit_code != 0

    def test_add_bad_field_format_fails(self, profile_dir):
        result = runner.invoke(app, [
            "add", "--platform", "thoughtspot", "--name", "X",
            "--auth-type", "token", "--field", "no_equals_sign",
        ])
        assert result.exit_code != 0

    def test_add_never_contains_credential_values(self, profile_dir):
        result = runner.invoke(app, [
            "add", "--platform", "thoughtspot", "--name", "Prod",
            "--auth-type", "token", "--field", "username=admin",
        ])
        data = json.loads(result.output)
        flat = json.dumps(data)
        assert "Bearer" not in flat
        assert "secret123" not in flat
        store_cmds = data["keychain_store_commands"]["darwin"]
        assert 'VALUE' in store_cmds


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdateCommand:
    def test_update_existing(self, profile_dir):
        profile_dir["snowflake"].write_text(json.dumps([
            {"name": "Prod", "account": "old-acct"}
        ]))
        result = runner.invoke(app, [
            "update", "--platform", "snowflake", "--name", "Prod",
            "--field", "account=new-acct",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["profile"]["account"] == "new-acct"
        saved = json.loads(profile_dir["snowflake"].read_text())
        assert saved[0]["account"] == "new-acct"

    def test_update_nonexistent_fails(self, profile_dir):
        result = runner.invoke(app, [
            "update", "--platform", "snowflake", "--name", "NoSuch",
            "--field", "account=x",
        ])
        assert result.exit_code != 0

    def test_update_bad_field_fails(self, profile_dir):
        profile_dir["snowflake"].write_text(json.dumps([{"name": "A"}]))
        result = runner.invoke(app, [
            "update", "--platform", "snowflake", "--name", "A",
            "--field", "bad_format",
        ])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


class TestRemoveCommand:
    def test_remove_existing(self, profile_dir):
        profile_dir["tableau"].write_text(json.dumps([
            {"name": "Server1", "server_url": "https://tab", "auth": "pat",
             "pat_secret_env": "TABLEAU_PAT_SECRET_SERVER1"}
        ]))
        result = runner.invoke(app, [
            "remove", "--platform", "tableau", "--name", "Server1",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["removed"]["name"] == "Server1"
        assert data["keychain_service"] == "tableau-server1"
        assert data["env_var_to_remove"] == "TABLEAU_PAT_SECRET_SERVER1"
        saved = json.loads(profile_dir["tableau"].read_text())
        assert len(saved) == 0

    def test_remove_nonexistent_fails(self, profile_dir):
        result = runner.invoke(app, [
            "remove", "--platform", "snowflake", "--name", "NoSuch",
        ])
        assert result.exit_code != 0

    def test_remove_infers_auth_type(self, profile_dir):
        profile_dir["thoughtspot"].write_text(json.dumps([
            {"name": "Staging", "token_env": "THOUGHTSPOT_TOKEN_STAGING"}
        ]))
        result = runner.invoke(app, [
            "remove", "--platform", "thoughtspot", "--name", "Staging",
        ])
        data = json.loads(result.output)
        assert data["env_var_to_remove"] == "THOUGHTSPOT_TOKEN_STAGING"


# ---------------------------------------------------------------------------
# sync-env
# ---------------------------------------------------------------------------


class TestSyncEnvCommand:
    def test_sync_env_generates_lines(self, profile_dir):
        profile_dir["thoughtspot"].write_text(json.dumps([
            {"name": "Prod", "token_env": "THOUGHTSPOT_TOKEN_PROD",
             "username": "admin", "base_url": "https://ts.example.com"}
        ]))
        result = runner.invoke(app, ["sync-env", "--platform", "thoughtspot"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["lines"]) == 1
        assert data["lines"][0]["env_var"] == "THOUGHTSPOT_TOKEN_PROD"
        assert "export" in data["lines"][0]["line"]

    def test_sync_env_all_platforms(self, profile_dir):
        profile_dir["thoughtspot"].write_text(json.dumps([
            {"name": "A", "token_env": "T", "username": "u"}
        ]))
        profile_dir["snowflake"].write_text(json.dumps([
            {"name": "B", "auth": "password", "username": "u"}
        ]))
        result = runner.invoke(app, ["sync-env"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        platforms = {line["platform"] for line in data["lines"]}
        assert "thoughtspot" in platforms
        assert "snowflake" in platforms

    def test_sync_env_skips_keyless_auth(self, profile_dir):
        profile_dir["snowflake"].write_text(json.dumps([
            {"name": "CLI", "auth": "cli", "cli_connection": "myconn"}
        ]))
        result = runner.invoke(app, ["sync-env", "--platform", "snowflake"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["lines"]) == 0
