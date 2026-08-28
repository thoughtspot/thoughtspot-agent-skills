"""ts profiles — profile management commands (list, add, update, remove, sync-env)."""
from __future__ import annotations

import json
import platform as plat
from typing import Optional

import typer

from ts_cli.client import PROFILES_PATH, load_profiles
from ts_cli.profile_ops import (
    PROFILE_PATHS,
    SlugCollisionError,
    add_profile as ops_add_profile,
    derive_env_var,
    derive_keychain_service,
    get_profile,
    keychain_store_commands,
    keychain_verify_commands,
    load_platform_profiles,
    remove_profile as ops_remove_profile,
    slugify,
    windows_env_commands,
    zshenv_export_line,
)
from ts_cli.tableau.client import load_tableau_profiles, TABLEAU_PROFILES_PATH

app = typer.Typer(help="Profile management commands.")

# Fields that POINT AT a credential — the name of an env var, the path to a key
# file. Stripped from `list` output for tidiness; none of them is itself a secret.
_CREDENTIAL_FIELDS = {
    "token_env", "password_env", "secret_key_env", "secret_env",
    "pat_secret_env", "private_key_path", "private_key_passphrase_env",
}

# Fields whose VALUE is the secret itself.
#
# The distinction above was inverted for as long as this module existed:
# `_strip_credentials` removed `token_env` — the *name* of an environment
# variable, which is not sensitive — and kept `token`, the live credential. So
# `ts profiles list --json` echoed any literal secret a profile carried, while the
# SKILL.md files claimed credentials were stripped. Reproduced on every platform,
# not just one.
#
# Names are EXACT, deliberately. A substring rule refuses real fields: `pat_name`
# is a Tableau PAT's *name* (not its secret), and `key` appears in `primary_key`,
# `key_pair`, `sort_key`, `keychain_service`. The suffix rule below covers names
# nobody has thought of yet, and is guarded against the pointer suffixes so
# `pat_secret_env` and `private_key_path` stay allowed.
_SECRET_VALUE_FIELDS = frozenset({
    "token", "password", "secret", "secret_key", "pat_secret",
    "private_key", "private_key_passphrase", "api_key", "apikey",
    "developer_token", "client_secret", "access_token", "refresh_token",
})

_SECRET_SUFFIXES = ("_token", "_password", "_secret", "_passphrase")
_POINTER_SUFFIXES = ("_env", "_path", "_file", "_name")


def is_secret_value_field(key: str) -> bool:
    """True when `key`'s VALUE would be a live credential rather than a pointer."""
    k = str(key).strip().lower()
    if k.endswith(_POINTER_SUFFIXES):
        return False
    return k in _SECRET_VALUE_FIELDS or k.endswith(_SECRET_SUFFIXES)


def _strip_credentials(profile: dict) -> dict:
    """Copy of `profile` without credential pointers OR literal secret values.

    Belt-and-braces: `--field token=…` is refused at parse time now, so a literal
    should never reach disk — but profiles written before that refusal existed
    still carry one, and this is what stops `list` echoing it.
    """
    return {k: v for k, v in profile.items()
            if k not in _CREDENTIAL_FIELDS and not is_secret_value_field(k)}


def _strip_secret_values(profile: dict) -> dict:
    """Copy of `profile` without literal secret values, but KEEPING the pointers.

    Used by `add`/`update`, whose whole job is to tell the operator which env var to
    populate — `token_env` is the actionable half of that output and is not itself
    sensitive. Stripping it too broke `test_add_thoughtspot_token`, correctly: the
    first cut of this fix reused `_strip_credentials` and removed the one field the
    caller needs. `list` still strips both, which is its pre-existing contract.
    """
    return {k: v for k, v in profile.items() if not is_secret_value_field(k)}


def _reject_secret_fields(fields: dict) -> None:
    """Refuse `--field <secret>=…` before it can be persisted or echoed.

    Stripping output alone is not enough: the value still lands in
    `~/.claude/<platform>-profiles.json` at mode 0644, and `ts profiles add`
    echoed the whole profile to stdout — which in Claude Code means the
    conversation transcript. `.claude/rules/security.md` forbids both outright.
    Nothing reads these keys either: token resolution is env-var-then-keyring, so
    the on-disk copy bought nothing it could lose.
    """
    offenders = sorted(k for k in fields if is_secret_value_field(k))
    if not offenders:
        return
    names = ", ".join(repr(k) for k in offenders)
    typer.echo(
        f"Refusing --field for credential value(s): {names}.\n"
        f"A secret passed this way is written to the profile JSON (mode 0644), "
        f"echoed back on stdout, and — in Claude Code — captured into the "
        f"conversation transcript. Store it in the OS credential store or an "
        f"environment variable instead, and let the profile hold only the "
        f"pointer (e.g. 'token_env'). Run the relevant /ts-profile-* skill for "
        f"the exact commands.",
        err=True,
    )
    raise typer.Exit(1)


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
    if platform == "databricks" and auth_type == "oauth-m2m":
        # The OAuth secret belongs to the Service Principal, so the client_id is
        # the account it is keyed under -- matching the client_id/client_secret
        # pair the Databricks CLI reads from ~/.databrickscfg.
        return fields.get("client_id", "")
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
        help="Output profiles as JSON (credential pointers and literal secrets stripped).",
    ),
) -> None:
    """List configured profiles.

    By default lists ThoughtSpot profiles.

    Neither a credential pointer (`token_env`) nor a literal secret value (`token`)
    is shown. The literal case is belt-and-braces: `--field token=…` is refused at
    parse time, so a secret should never reach the file in the first place.
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

    _reject_secret_fields(fields)

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

    try:
        ops_add_profile(platform, profile)
    except SlugCollisionError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)

    output = {
        "profile": _strip_secret_values(profile),
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

    updates: dict[str, object] = {}
    for f in (field or []):
        if "=" not in f:
            typer.echo(f"Invalid --field format: {f!r}. Use key=value.", err=True)
            raise typer.Exit(1)
        k, v = f.split("=", 1)
        updates[k] = _coerce_field_value(v)

    _reject_secret_fields(updates)
    existing.update(updates)

    try:
        ops_add_profile(platform, existing)
    except SlugCollisionError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps({"profile": _strip_secret_values(existing)}, indent=2))


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
