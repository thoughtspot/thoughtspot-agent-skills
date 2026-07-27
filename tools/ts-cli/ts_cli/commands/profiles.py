"""ts profiles — profile management commands (list, add, update, remove, sync-env)."""
from __future__ import annotations

import json
import platform as plat
from typing import Optional

import typer

from ts_cli.client import PROFILES_PATH, load_profiles
from ts_cli.profile_ops import (
    PROFILE_PATHS,
    add_profile as ops_add_profile,
    derive_env_var,
    derive_keychain_service,
    get_profile,
    keychain_store_commands,
    keychain_verify_commands,
    load_platform_profiles,
    remove_profile as ops_remove_profile,
    slugify,
    upsert_zshenv,
    windows_env_commands,
    zshenv_export_line,
)
from ts_cli.tableau.client import load_tableau_profiles, TABLEAU_PROFILES_PATH

app = typer.Typer(help="Profile management commands.")

_CREDENTIAL_FIELDS = {
    "token_env", "password_env", "secret_key_env", "secret_env",
    "pat_secret_env", "private_key_path", "private_key_passphrase_env",
}


def _strip_credentials(profile: dict) -> dict:
    """Return a copy of the profile with credential-related fields removed."""
    return {k: v for k, v in profile.items() if k not in _CREDENTIAL_FIELDS}


def _coerce_field_value(value: str):
    """Coerce a --field string value to its natural JSON type.

    ``--field key=value`` always arrives as a string, but some profile fields
    (e.g. ``verify_ssl``) are consumed as booleans — ``client.py`` assigns
    ``verify_ssl`` straight to ``requests.Session.verify``, where the string
    ``"false"`` is truthy and gets treated as a CA-bundle path, breaking every
    request to a self-signed/private cluster. Convert the literals ``true`` and
    ``false`` (case-insensitive) to real booleans; leave everything else as a
    string so URLs, usernames, accounts, etc. are untouched.
    """
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value


def _infer_auth_type(profile: dict) -> str | None:
    """Infer auth_type from a profile dict's fields."""
    return (
        profile.get("auth_type")
        or profile.get("auth")
        or ("token" if "token_env" in profile
            else "password" if "password_env" in profile
            else "secret_key" if "secret_key_env" in profile
            else None)
    )


def _keychain_account(platform: str, auth_type: str, fields: dict) -> str | None:
    """Determine the keychain account name for a platform/auth_type."""
    if auth_type in ("key_pair", "cli", "databricks-cli"):
        return None
    if platform == "databricks" and auth_type == "pat":
        return "token"
    if platform == "tableau" and auth_type == "pat":
        return fields.get("pat_name", "")
    return fields.get("username", "")


def _apply_auth_fields(profile: dict, platform: str, auth_type: str, slug: str) -> dict:
    """Add platform-specific auth metadata fields to the profile dict."""
    if platform == "thoughtspot":
        field_map = {"token": "token_env", "password": "password_env", "secret_key": "secret_key_env"}
        if auth_type in field_map:
            profile[field_map[auth_type]] = derive_env_var(platform, auth_type, slug)

    elif platform == "snowflake":
        profile["method"] = "python" if auth_type != "cli" else "cli"
        profile["auth"] = auth_type
        if auth_type == "password":
            profile["password_env"] = derive_env_var(platform, auth_type, slug)

    elif platform == "databricks":
        profile["auth_type"] = auth_type
        profile["dbx_profile"] = f"ts-{slug}"
        if auth_type in ("oauth-m2m", "pat"):
            profile["secret_env"] = derive_env_var(platform, auth_type, slug)

    elif platform == "tableau":
        profile["auth"] = auth_type
        if auth_type == "password":
            profile["password_env"] = derive_env_var(platform, auth_type, slug)
        elif auth_type == "pat":
            profile["pat_secret_env"] = derive_env_var(platform, auth_type, slug)

    return profile


# ---------------------------------------------------------------------------
# list — per-platform formatters
# ---------------------------------------------------------------------------

_PLATFORM_SKILLS = {
    "thoughtspot": "ts-profile-thoughtspot",
    "snowflake": "ts-profile-snowflake",
    "databricks": "ts-profile-databricks",
    "tableau": "ts-profile-tableau",
}


def _list_or_exit(platform: str, profiles: list) -> None:
    if not profiles:
        path = PROFILE_PATHS.get(platform, "~/.claude/<platform>-profiles.json")
        typer.echo(
            f"No {platform.title()} profiles found in {path}.\n"
            f"Run /{_PLATFORM_SKILLS[platform]} to add a profile."
        )
        raise typer.Exit(1)


def _list_tableau(profiles: list) -> None:
    for p in profiles:
        auth_method = p.get("auth", "unknown")
        server = p.get("server_url", "")
        site = p.get("site_content_url", "")
        identity = p.get("username", "") or p.get("pat_name", "")
        typer.echo(f"  {p['name']:30s}  {auth_method:10s}  {identity:30s}  {server}  site={site}")


def _list_databricks(profiles: list) -> None:
    for p in profiles:
        auth_type = p.get("auth_type", "unknown")
        host = p.get("host", "")
        typer.echo(f"  {p['name']:30s}  {auth_type:12s}  {host}")


def _list_snowflake(profiles: list) -> None:
    for p in profiles:
        method = p.get("method", "unknown")
        account = p.get("account") or p.get("cli_connection", "")
        warehouse = p.get("default_warehouse", "")
        typer.echo(f"  {p['name']:30s}  {method:8s}  {account:40s}  {warehouse}")


def _list_thoughtspot() -> None:
    profiles = load_profiles()
    if not profiles:
        typer.echo(
            f"No profiles found in {PROFILES_PATH}.\n"
            "Run /ts-profile-thoughtspot to add a profile."
        )
        raise typer.Exit(1)
    for name, p in profiles.items():
        auth = (
            "token" if p.get("token_env")
            else "password" if p.get("password_env")
            else "secret_key" if p.get("secret_key_env")
            else "unknown"
        )
        typer.echo(f"  {name:20s}  {auth:12s}  {p.get('base_url', '')}")


def _resolve_platform(snowflake: bool, tableau: bool, databricks: bool) -> str:
    if databricks:
        return "databricks"
    if snowflake:
        return "snowflake"
    if tableau:
        return "tableau"
    return "thoughtspot"


# ---------------------------------------------------------------------------
# list command
# ---------------------------------------------------------------------------

@app.command("list")
def list_profiles(
    snowflake: bool = typer.Option(
        False, "--snowflake",
        help="List Snowflake profiles instead of ThoughtSpot profiles.",
    ),
    tableau: bool = typer.Option(
        False, "--tableau",
        help="List Tableau profiles instead of ThoughtSpot profiles.",
    ),
    databricks: bool = typer.Option(
        False, "--databricks",
        help="List Databricks profiles instead of ThoughtSpot profiles.",
    ),
    json_output: bool = typer.Option(
        False, "--json",
        help="Output profiles as JSON (credentials stripped).",
    ),
) -> None:
    """List configured profiles.

    By default lists ThoughtSpot profiles. Credentials are never shown.
    """
    platform = _resolve_platform(snowflake, tableau, databricks)

    if json_output:
        profiles = load_platform_profiles(platform)
        stripped = [_strip_credentials(p) for p in profiles]
        typer.echo(json.dumps(stripped, indent=2))
        return

    if platform == "tableau":
        tab_profiles = load_tableau_profiles()
        _list_or_exit("tableau", tab_profiles)
        _list_tableau(tab_profiles)
    elif platform == "databricks":
        dbx_profiles = load_platform_profiles("databricks")
        _list_or_exit("databricks", dbx_profiles)
        _list_databricks(dbx_profiles)
    elif platform == "snowflake":
        sf_profiles = load_platform_profiles("snowflake")
        _list_or_exit("snowflake", sf_profiles)
        _list_snowflake(sf_profiles)
    else:
        _list_thoughtspot()


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

@app.command("add")
def add_cmd(
    platform: str = typer.Option(..., help="Platform: thoughtspot, snowflake, databricks, tableau."),
    name: str = typer.Option(..., help="Profile display name."),
    auth_type: str = typer.Option(..., "--auth-type", help="Auth method (token, password, key_pair, pat, oauth-m2m, databricks-cli, cli)."),
    field: Optional[list[str]] = typer.Option(None, "--field", help="Profile field as key=value. Repeatable."),
) -> None:
    """Add or replace a profile. Derives slug, env var, keychain commands.

    Credential values are NEVER passed through this command — the output
    includes keychain commands for the user to run in their own terminal.
    """
    if platform not in PROFILE_PATHS:
        typer.echo(f"Unknown platform: {platform!r}. Use: {sorted(PROFILE_PATHS)}", err=True)
        raise typer.Exit(1)

    fields: dict[str, object] = {}
    for f in (field or []):
        if "=" not in f:
            typer.echo(f"Invalid --field format: {f!r}. Use key=value.", err=True)
            raise typer.Exit(1)
        k, v = f.split("=", 1)
        fields[k] = _coerce_field_value(v)

    slug = slugify(name)
    service = derive_keychain_service(platform, slug)
    account = _keychain_account(platform, auth_type, fields)

    profile = {"name": name, **fields}
    profile = _apply_auth_fields(profile, platform, auth_type, slug)

    try:
        env_var = derive_env_var(platform, auth_type, slug)
    except ValueError:
        env_var = None

    zshenv = None
    if env_var and account:
        system = plat.system().lower()
        if system in ("darwin", "linux"):
            method = "darwin" if system == "darwin" else "linux"
            zshenv = zshenv_export_line(env_var, service, account, method)

    ops_add_profile(platform, profile)

    output = {
        "profile": profile,
        "slug": slug,
        "env_var": env_var,
        "keychain_service": service,
        "keychain_account": account,
        "keychain_store_commands": keychain_store_commands(service, account) if account else None,
        "keychain_verify_commands": keychain_verify_commands(service, account) if account else None,
        "zshenv_line": zshenv,
        "windows_env_commands": windows_env_commands(env_var, service, account) if env_var and account else None,
    }
    typer.echo(json.dumps(output, indent=2))


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

@app.command("update")
def update_cmd(
    platform: str = typer.Option(..., help="Platform: thoughtspot, snowflake, databricks, tableau."),
    name: str = typer.Option(..., help="Profile name to update."),
    field: Optional[list[str]] = typer.Option(None, "--field", help="Field to update as key=value. Repeatable."),
) -> None:
    """Update fields on an existing profile."""
    if platform not in PROFILE_PATHS:
        typer.echo(f"Unknown platform: {platform!r}.", err=True)
        raise typer.Exit(1)

    existing = get_profile(platform, name)
    if existing is None:
        typer.echo(f"Profile {name!r} not found for platform {platform!r}.", err=True)
        raise typer.Exit(1)

    for f in (field or []):
        if "=" not in f:
            typer.echo(f"Invalid --field format: {f!r}. Use key=value.", err=True)
            raise typer.Exit(1)
        k, v = f.split("=", 1)
        existing[k] = _coerce_field_value(v)

    ops_add_profile(platform, existing)
    typer.echo(json.dumps({"profile": existing}, indent=2))


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------

@app.command("remove")
def remove_cmd(
    platform: str = typer.Option(..., help="Platform: thoughtspot, snowflake, databricks, tableau."),
    name: str = typer.Option(..., help="Profile name to remove."),
) -> None:
    """Remove a profile and report cleanup info."""
    if platform not in PROFILE_PATHS:
        typer.echo(f"Unknown platform: {platform!r}.", err=True)
        raise typer.Exit(1)

    removed = ops_remove_profile(platform, name)
    if removed is None:
        typer.echo(f"Profile {name!r} not found for platform {platform!r}.", err=True)
        raise typer.Exit(1)

    slug = slugify(name)
    service = derive_keychain_service(platform, slug)
    auth_type = _infer_auth_type(removed)

    env_var = None
    if auth_type:
        try:
            env_var = derive_env_var(platform, auth_type, slug)
        except ValueError:
            pass

    typer.echo(json.dumps({
        "removed": removed,
        "keychain_service": service,
        "env_var_to_remove": env_var,
    }, indent=2))


# ---------------------------------------------------------------------------
# sync-env
# ---------------------------------------------------------------------------

@app.command("sync-env")
def sync_env_cmd(
    platform: Optional[str] = typer.Option(
        None, help="Sync only this platform. Omit to sync all."
    ),
) -> None:
    """Regenerate ~/.zshenv export lines from all profiles."""
    system = plat.system().lower()
    if system not in ("darwin", "linux"):
        typer.echo(json.dumps({
            "lines": [],
            "note": "sync-env is for macOS/Linux only. Windows uses SetEnvironmentVariable.",
        }, indent=2))
        return

    method = "darwin" if system == "darwin" else "linux"
    platforms = [platform] if platform else sorted(PROFILE_PATHS)
    lines = []

    for plf in platforms:
        if plf not in PROFILE_PATHS:
            continue
        for p in load_platform_profiles(plf):
            auth_type = _infer_auth_type(p)
            if not auth_type:
                continue
            slug = slugify(p["name"])
            try:
                env_var = derive_env_var(plf, auth_type, slug)
            except ValueError:
                continue
            service = derive_keychain_service(plf, slug)
            account = _keychain_account(plf, auth_type, p)
            if not account:
                continue
            line = zshenv_export_line(env_var, service, account, method)
            lines.append({"platform": plf, "name": p["name"], "env_var": env_var, "line": line})

    typer.echo(json.dumps({"lines": lines}, indent=2))
