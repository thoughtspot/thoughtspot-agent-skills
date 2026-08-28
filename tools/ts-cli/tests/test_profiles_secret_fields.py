"""`ts profiles` must never persist or echo a literal credential.

The bug these pin: `_CREDENTIAL_FIELDS` held env-var POINTER names (`token_env`), so
`_strip_credentials` removed the *name* of an environment variable — not sensitive —
and kept `token`, the live credential. `add` and `update` did not strip at all. So a
`--field token=…` landed in `~/.claude/<platform>-profiles.json` at mode 0644, was
echoed to stdout, and in Claude Code was captured into the conversation transcript —
three copies from one mistake, against an explicit `.claude/rules/security.md` rule,
while the SKILL.md files claimed credentials were stripped.

The false-positive half matters as much as the refusal: `pat_name` is a Tableau PAT's
*name*, not its secret, and `key` appears in `primary_key` / `key_pair` / `sort_key` /
`keychain_service`. A substring rule would refuse real fields, so the denylist is
exact names plus a pointer-guarded suffix rule.
"""
import json

import pytest
from typer.testing import CliRunner

from ts_cli import client as client_module, profile_ops
from ts_cli.commands.profiles import app, is_secret_value_field

runner = CliRunner()


@pytest.fixture
def profile_dir(tmp_path, monkeypatch):
    """Point PROFILE_PATHS + PROFILES_PATH at temp files.

    Patching `$HOME` is NOT enough and is actively dangerous: both constants are
    resolved at import time, so a HOME-only fixture writes to the developer's real
    `~/.claude/*-profiles.json`. The first draft of this file did exactly that.
    Mirrors the fixture in test_profiles_commands.py.
    """
    paths = {
        "thoughtspot": tmp_path / "thoughtspot-profiles.json",
        "snowflake": tmp_path / "snowflake-profiles.json",
        "databricks": tmp_path / "databricks-profiles.json",
        "tableau": tmp_path / "tableau-profiles.json",
    }
    monkeypatch.setattr(profile_ops, "PROFILE_PATHS", paths)
    monkeypatch.setattr(client_module, "PROFILES_PATH", paths["thoughtspot"])
    return paths


# --- the predicate ----------------------------------------------------------

@pytest.mark.parametrize("key", [
    "token", "password", "secret", "secret_key", "pat_secret", "private_key",
    "private_key_passphrase", "api_key", "developer_token", "client_secret",
    "access_token", "refresh_token",
    # suffix rule, for names nobody has enumerated yet
    "some_new_token", "vendor_password", "weird_secret", "kdf_passphrase",
    # case and whitespace must not be an escape
    "TOKEN", "  Token  ",
])
def test_secret_bearing_keys_are_recognised(key):
    assert is_secret_value_field(key) is True


@pytest.mark.parametrize("key", [
    # pointers: the NAME of an env var or the PATH to a key file
    "token_env", "password_env", "secret_key_env", "secret_env", "pat_secret_env",
    "private_key_path", "private_key_passphrase_env",
    # `pat_name` is the PAT's name, not its secret -- a substring rule breaks this
    "pat_name", "token_name",
    # `key` is everywhere and is not a credential on its own
    "primary_key", "key_pair", "sort_key", "keychain_service", "key",
    # ordinary profile fields
    "url", "username", "account", "instance", "server", "site_id", "auth_type",
    "verify_ssl", "client_id", "warehouse", "role", "database", "schema",
])
def test_non_secret_keys_are_left_alone(key):
    assert is_secret_value_field(key) is False


# --- the CLI refusal --------------------------------------------------------

@pytest.mark.parametrize("secret_field", [
    "token", "password", "secret_key", "pat_secret", "api_key", "developer_token",
])
def test_add_refuses_a_literal_secret(profile_dir, secret_field):
    path = profile_dir["thoughtspot"]
    result = runner.invoke(app, [
        "add", "--platform", "thoughtspot", "--name", "Acme",
        "--auth-type", "token", "--field", "url=https://acme.example",
        "--field", f"{secret_field}=LITERAL_SECRET_VALUE",
    ])
    assert result.exit_code == 1
    assert "Refusing --field" in result.output
    assert secret_field in result.output
    # The refusal must not echo the value it is refusing.
    assert "LITERAL_SECRET_VALUE" not in result.output
    assert not path.exists(), "a refused add must write nothing at all"


def test_add_accepts_pointers_and_ordinary_fields(profile_dir):
    """The refusal must not break the flow the /ts-profile-* skills actually use."""
    result = runner.invoke(app, [
        "add", "--platform", "thoughtspot", "--name", "Acme",
        "--auth-type", "token", "--field", "url=https://acme.example",
        "--field", "username=svc", "--field", "token_env=THOUGHTSPOT_TOKEN_ACME",
    ])
    assert result.exit_code == 0, result.output
    assert "svc" in result.output


def test_update_refuses_a_literal_secret_and_changes_nothing(profile_dir):
    path = profile_dir["thoughtspot"]
    runner.invoke(app, [
        "add", "--platform", "thoughtspot", "--name", "Acme",
        "--auth-type", "token", "--field", "url=https://acme.example",
    ])
    before = path.read_text()

    result = runner.invoke(app, [
        "update", "--platform", "thoughtspot", "--name", "Acme",
        "--field", "token=LATE_SECRET",
    ])
    assert result.exit_code == 1
    assert "Refusing --field" in result.output
    assert path.read_text() == before, "a refused update must not partially apply"


def test_update_applies_all_or_nothing(profile_dir):
    """One bad field must not let its siblings through.

    The refusal happens after the whole `--field` set is parsed and before any of it
    is merged, so a mixed invocation writes nothing.
    """
    path = profile_dir["thoughtspot"]
    runner.invoke(app, [
        "add", "--platform", "thoughtspot", "--name", "Acme",
        "--auth-type", "token", "--field", "url=https://acme.example",
    ])
    result = runner.invoke(app, [
        "update", "--platform", "thoughtspot", "--name", "Acme",
        "--field", "username=svc", "--field", "token=LATE_SECRET",
    ])
    assert result.exit_code == 1
    assert "username" not in path.read_text()


# --- output stripping, for profiles written before the refusal existed ------

def test_list_strips_a_pre_existing_literal_secret(profile_dir):
    """A profile already carrying `token` on disk must not be echoed back.

    This is the case the old `_strip_credentials` got exactly backwards.
    """
    path = profile_dir["thoughtspot"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{
        "name": "Legacy", "url": "https://acme.example",
        "token": "PRE_EXISTING_SECRET", "password": "ALSO_SECRET",
        "token_env": "THOUGHTSPOT_TOKEN_LEGACY",
    }]))

    result = runner.invoke(app, ["list", "--json"])
    assert result.exit_code == 0, result.output
    assert "PRE_EXISTING_SECRET" not in result.output
    assert "ALSO_SECRET" not in result.output
    assert "Legacy" in result.output


def test_add_output_keeps_the_pointer_but_would_drop_a_secret(profile_dir):
    """`add` must strip secret VALUES and keep POINTERS — they are not the same.

    The first cut of this fix reused the `list` stripper for `add` and removed
    `token_env`, which is the one field the operator needs in order to know which
    env var to populate. Both halves are asserted so neither regresses.
    """
    result = runner.invoke(app, [
        "add", "--platform", "thoughtspot", "--name", "My Staging",
        "--auth-type", "token", "--field", "url=https://acme.example",
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["profile"]["token_env"] == "THOUGHTSPOT_TOKEN_MY_STAGING"


def test_update_output_strips_a_legacy_secret_but_keeps_the_pointer(profile_dir):
    """A profile written before the refusal still carries a literal on disk."""
    path = profile_dir["thoughtspot"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{
        "name": "Legacy", "url": "https://acme.example",
        "token": "PRE_EXISTING_SECRET", "token_env": "THOUGHTSPOT_TOKEN_LEGACY",
    }]))
    result = runner.invoke(app, [
        "update", "--platform", "thoughtspot", "--name", "Legacy",
        "--field", "username=svc",
    ])
    assert result.exit_code == 0, result.output
    assert "PRE_EXISTING_SECRET" not in result.output
    assert "THOUGHTSPOT_TOKEN_LEGACY" in result.output
