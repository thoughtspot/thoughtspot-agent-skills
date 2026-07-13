"""Tests for profile_ops — the deterministic profile substrate."""
from __future__ import annotations

import json

import pytest

from ts_cli import profile_ops
from ts_cli.profile_ops import (
    add_profile,
    derive_env_var,
    derive_keychain_service,
    get_profile,
    keychain_store_commands,
    keychain_verify_commands,
    load_platform_profiles,
    remove_profile,
    remove_zshenv_line,
    save_platform_profiles,
    slug_to_upper,
    slugify,
    upsert_zshenv,
    windows_env_commands,
    zshenv_export_line,
)


class TestSlugify:
    def test_simple_name(self):
        assert slugify("production") == "production"

    def test_spaces_become_hyphens(self):
        assert slugify("My Staging") == "my-staging"

    def test_special_chars_collapse(self):
        assert slugify("Acme (US-West)") == "acme-us-west"

    def test_multiple_specials_collapse_to_single_hyphen(self):
        assert slugify("a!!!b") == "a-b"

    def test_leading_trailing_stripped(self):
        assert slugify("--hello--") == "hello"

    def test_mixed_case(self):
        assert slugify("ThoughtSpot Partner (AP)") == "thoughtspot-partner-ap"

    def test_empty_string(self):
        assert slugify("") == ""

    def test_digits_preserved(self):
        assert slugify("env2-test") == "env2-test"


class TestSlugToUpper:
    def test_converts_hyphens_to_underscores_and_uppercases(self):
        assert slug_to_upper("my-staging") == "MY_STAGING"

    def test_single_word(self):
        assert slug_to_upper("production") == "PRODUCTION"

    def test_already_upper(self):
        assert slug_to_upper("MY-STAGING") == "MY_STAGING"


class TestDeriveEnvVar:
    def test_thoughtspot_token(self):
        assert derive_env_var("thoughtspot", "token", "my-staging") == "THOUGHTSPOT_TOKEN_MY_STAGING"

    def test_thoughtspot_password(self):
        assert derive_env_var("thoughtspot", "password", "prod") == "THOUGHTSPOT_PASSWORD_PROD"

    def test_thoughtspot_secret_key(self):
        assert derive_env_var("thoughtspot", "secret_key", "prod") == "THOUGHTSPOT_SECRET_KEY_PROD"

    def test_snowflake_password(self):
        assert derive_env_var("snowflake", "password", "partner-ap") == "SNOWFLAKE_PASSWORD_PARTNER_AP"

    def test_databricks_sp(self):
        assert derive_env_var("databricks", "oauth-m2m", "my-ws") == "DATABRICKS_SP_SECRET_MY_WS"

    def test_databricks_pat(self):
        assert derive_env_var("databricks", "pat", "dev") == "DATABRICKS_TOKEN_DEV"

    def test_tableau_password(self):
        assert derive_env_var("tableau", "password", "server1") == "TABLEAU_PASSWORD_SERVER1"

    def test_tableau_pat(self):
        assert derive_env_var("tableau", "pat", "cloud") == "TABLEAU_PAT_SECRET_CLOUD"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown platform/auth_type"):
            derive_env_var("unknown", "token", "slug")


class TestDeriveKeychainService:
    def test_thoughtspot(self):
        assert derive_keychain_service("thoughtspot", "my-staging") == "thoughtspot-my-staging"

    def test_snowflake(self):
        assert derive_keychain_service("snowflake", "partner") == "snowflake-partner"

    def test_databricks(self):
        assert derive_keychain_service("databricks", "ws1") == "databricks-ws1"

    def test_tableau(self):
        assert derive_keychain_service("tableau", "server1") == "tableau-server1"


class TestKeychainStoreCommands:
    def test_darwin_uses_security_cli(self):
        cmds = keychain_store_commands("thoughtspot-staging", "user@example.com")
        assert "security add-generic-password" in cmds["darwin"]
        assert "-s \"thoughtspot-staging\"" in cmds["darwin"]
        assert "-a \"user@example.com\"" in cmds["darwin"]

    def test_linux_uses_keyring(self):
        cmds = keychain_store_commands("thoughtspot-staging", "user@example.com")
        assert "keyring.set_password" in cmds["linux"]
        assert "thoughtspot-staging" in cmds["linux"]

    def test_windows_uses_keyring(self):
        cmds = keychain_store_commands("thoughtspot-staging", "user@example.com")
        assert "keyring.set_password" in cmds["windows"]

    def test_all_three_platforms_present(self):
        cmds = keychain_store_commands("svc", "acct")
        assert set(cmds.keys()) == {"darwin", "linux", "windows"}


class TestKeychainVerifyCommands:
    def test_darwin_no_dash_w(self):
        cmds = keychain_verify_commands("thoughtspot-staging", "user@example.com")
        assert "-w" not in cmds["darwin"]
        assert "find-generic-password" in cmds["darwin"]

    def test_linux_uses_get_password(self):
        cmds = keychain_verify_commands("svc", "acct")
        assert "get_password" in cmds["linux"]

    def test_verify_never_prints_value(self):
        cmds = keychain_verify_commands("svc", "acct")
        for platform, cmd in cmds.items():
            assert "print(v" not in cmd or "Stored" in cmd or "Found" in cmd, \
                f"{platform} verify command may leak credential value"


class TestZshenvExportLine:
    def test_darwin_uses_security(self):
        line = zshenv_export_line(
            "THOUGHTSPOT_TOKEN_STAGING", "thoughtspot-staging", "user@x.com", "darwin"
        )
        assert line.startswith("export THOUGHTSPOT_TOKEN_STAGING=")
        assert "security find-generic-password" in line
        assert "-s \"thoughtspot-staging\"" in line
        assert "-a \"user@x.com\"" in line

    def test_linux_uses_keyring(self):
        line = zshenv_export_line(
            "SNOWFLAKE_PASSWORD_PROD", "snowflake-prod", "admin", "linux"
        )
        assert line.startswith("export SNOWFLAKE_PASSWORD_PROD=")
        assert "keyring.get_password" in line


class TestWindowsEnvCommands:
    def test_contains_set_environment_variable(self):
        snippet = windows_env_commands("MY_VAR", "svc", "acct")
        assert "SetEnvironmentVariable" in snippet
        assert "'MY_VAR'" in snippet


class TestUpsertZshenv:
    def test_append_to_empty(self):
        result = upsert_zshenv("", "MY_VAR", "export MY_VAR=new")
        assert result == "export MY_VAR=new\n"

    def test_append_to_existing_content(self):
        result = upsert_zshenv("export OTHER=1\n", "MY_VAR", "export MY_VAR=new")
        assert result == "export OTHER=1\n\nexport MY_VAR=new\n"

    def test_replace_existing_line(self):
        original = "export MY_VAR=old\nexport OTHER=1\n"
        result = upsert_zshenv(original, "MY_VAR", "export MY_VAR=new")
        assert result == "export MY_VAR=new\nexport OTHER=1\n"

    def test_replace_preserves_surrounding_lines(self):
        original = "export A=1\nexport MY_VAR=old\nexport B=2\n"
        result = upsert_zshenv(original, "MY_VAR", "export MY_VAR=new")
        assert result == "export A=1\nexport MY_VAR=new\nexport B=2\n"

    def test_no_double_blank_line_on_append(self):
        result = upsert_zshenv("export A=1\n\n", "MY_VAR", "export MY_VAR=new")
        assert "\n\n\n" not in result


class TestRemoveZshenvLine:
    def test_removes_matching_line(self):
        original = "export A=1\nexport MY_VAR=old\nexport B=2\n"
        result = remove_zshenv_line(original, "MY_VAR")
        assert "MY_VAR" not in result
        assert "export A=1\n" in result
        assert "export B=2\n" in result

    def test_noop_when_not_present(self):
        original = "export A=1\n"
        result = remove_zshenv_line(original, "MY_VAR")
        assert result == original

    def test_removes_blank_line_left_behind(self):
        original = "export A=1\n\nexport MY_VAR=old\n\nexport B=2\n"
        result = remove_zshenv_line(original, "MY_VAR")
        assert "\n\n\n" not in result


# ---------------------------------------------------------------------------
# Profile JSON CRUD (Task 2)
# ---------------------------------------------------------------------------

from ts_cli.profile_ops import (
    load_platform_profiles, save_platform_profiles,
    add_profile, remove_profile, get_profile,
)
from ts_cli import profile_ops


@pytest.fixture
def profile_dir(tmp_path, monkeypatch):
    """Point all PROFILE_PATHS at temp files."""
    paths = {
        "thoughtspot": tmp_path / "thoughtspot-profiles.json",
        "snowflake": tmp_path / "snowflake-profiles.json",
        "databricks": tmp_path / "databricks-profiles.json",
        "tableau": tmp_path / "tableau-profiles.json",
    }
    monkeypatch.setattr(profile_ops, "PROFILE_PATHS", paths)
    return paths


class TestLoadPlatformProfiles:
    def test_missing_file_returns_empty_list(self, profile_dir):
        assert load_platform_profiles("thoughtspot") == []

    def test_bare_list(self, profile_dir):
        profile_dir["snowflake"].write_text(json.dumps([{"name": "A"}]))
        assert load_platform_profiles("snowflake") == [{"name": "A"}]

    def test_wrapped_list(self, profile_dir):
        profile_dir["thoughtspot"].write_text(
            json.dumps({"profiles": [{"name": "A"}, {"name": "B"}]})
        )
        result = load_platform_profiles("thoughtspot")
        assert len(result) == 2
        assert result[0]["name"] == "A"

    def test_name_keyed_dict(self, profile_dir):
        profile_dir["thoughtspot"].write_text(
            json.dumps({"A": {"name": "A", "base_url": "https://a"}})
        )
        result = load_platform_profiles("thoughtspot")
        assert len(result) == 1
        assert result[0]["name"] == "A"


class TestSavePlatformProfiles:
    def test_saves_as_bare_list(self, profile_dir):
        save_platform_profiles("snowflake", [{"name": "X"}])
        raw = json.loads(profile_dir["snowflake"].read_text())
        assert isinstance(raw, list)
        assert raw == [{"name": "X"}]


class TestAddProfile:
    def test_add_to_empty(self, profile_dir):
        result = add_profile("snowflake", {"name": "New", "account": "acct"})
        assert result["name"] == "New"
        saved = load_platform_profiles("snowflake")
        assert len(saved) == 1

    def test_add_replaces_existing_by_name(self, profile_dir):
        add_profile("snowflake", {"name": "A", "account": "old"})
        add_profile("snowflake", {"name": "A", "account": "new"})
        saved = load_platform_profiles("snowflake")
        assert len(saved) == 1
        assert saved[0]["account"] == "new"

    def test_add_preserves_other_profiles(self, profile_dir):
        add_profile("snowflake", {"name": "A"})
        add_profile("snowflake", {"name": "B"})
        saved = load_platform_profiles("snowflake")
        assert len(saved) == 2


class TestRemoveProfile:
    def test_remove_existing(self, profile_dir):
        add_profile("snowflake", {"name": "A"})
        removed = remove_profile("snowflake", "A")
        assert removed["name"] == "A"
        assert load_platform_profiles("snowflake") == []

    def test_remove_nonexistent_returns_none(self, profile_dir):
        assert remove_profile("snowflake", "X") is None


class TestGetProfile:
    def test_get_existing(self, profile_dir):
        add_profile("tableau", {"name": "Server1", "server_url": "https://tab"})
        p = get_profile("tableau", "Server1")
        assert p is not None
        assert p["server_url"] == "https://tab"

    def test_get_nonexistent_returns_none(self, profile_dir):
        assert get_profile("tableau", "X") is None


# ---------------------------------------------------------------------------
# Profile JSON CRUD
# ---------------------------------------------------------------------------


@pytest.fixture
def profile_dir(tmp_path, monkeypatch):
    """Point all PROFILE_PATHS at temp files."""
    paths = {
        "thoughtspot": tmp_path / "thoughtspot-profiles.json",
        "snowflake": tmp_path / "snowflake-profiles.json",
        "databricks": tmp_path / "databricks-profiles.json",
        "tableau": tmp_path / "tableau-profiles.json",
    }
    monkeypatch.setattr(profile_ops, "PROFILE_PATHS", paths)
    return paths


class TestLoadPlatformProfiles:
    def test_missing_file_returns_empty_list(self, profile_dir):
        assert load_platform_profiles("thoughtspot") == []

    def test_bare_list(self, profile_dir):
        profile_dir["snowflake"].write_text(json.dumps([{"name": "A"}]))
        assert load_platform_profiles("snowflake") == [{"name": "A"}]

    def test_wrapped_list(self, profile_dir):
        profile_dir["thoughtspot"].write_text(
            json.dumps({"profiles": [{"name": "A"}, {"name": "B"}]})
        )
        result = load_platform_profiles("thoughtspot")
        assert len(result) == 2
        assert result[0]["name"] == "A"

    def test_name_keyed_dict(self, profile_dir):
        profile_dir["thoughtspot"].write_text(
            json.dumps({"A": {"name": "A", "base_url": "https://a"}})
        )
        result = load_platform_profiles("thoughtspot")
        assert len(result) == 1
        assert result[0]["name"] == "A"


class TestSavePlatformProfiles:
    def test_saves_as_bare_list(self, profile_dir):
        save_platform_profiles("snowflake", [{"name": "X"}])
        raw = json.loads(profile_dir["snowflake"].read_text())
        assert isinstance(raw, list)
        assert raw == [{"name": "X"}]


class TestAddProfile:
    def test_add_to_empty(self, profile_dir):
        result = add_profile("snowflake", {"name": "New", "account": "acct"})
        assert result["name"] == "New"
        saved = load_platform_profiles("snowflake")
        assert len(saved) == 1

    def test_add_replaces_existing_by_name(self, profile_dir):
        add_profile("snowflake", {"name": "A", "account": "old"})
        add_profile("snowflake", {"name": "A", "account": "new"})
        saved = load_platform_profiles("snowflake")
        assert len(saved) == 1
        assert saved[0]["account"] == "new"

    def test_add_preserves_other_profiles(self, profile_dir):
        add_profile("snowflake", {"name": "A"})
        add_profile("snowflake", {"name": "B"})
        saved = load_platform_profiles("snowflake")
        assert len(saved) == 2


class TestRemoveProfile:
    def test_remove_existing(self, profile_dir):
        add_profile("snowflake", {"name": "A"})
        removed = remove_profile("snowflake", "A")
        assert removed["name"] == "A"
        assert load_platform_profiles("snowflake") == []

    def test_remove_nonexistent_returns_none(self, profile_dir):
        assert remove_profile("snowflake", "X") is None


class TestGetProfile:
    def test_get_existing(self, profile_dir):
        add_profile("tableau", {"name": "Server1", "server_url": "https://tab"})
        p = get_profile("tableau", "Server1")
        assert p is not None
        assert p["server_url"] == "https://tab"

    def test_get_nonexistent_returns_none(self, profile_dir):
        assert get_profile("tableau", "X") is None
