"""ts profiles — list configured ThoughtSpot and Snowflake profiles."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from ts_cli.client import PROFILES_PATH, load_profiles

app = typer.Typer(help="Profile management commands.")

SNOWFLAKE_PROFILES_PATH = Path.home() / ".claude" / "snowflake-profiles.json"


def load_snowflake_profiles() -> list:
    """Load Snowflake profiles from ~/.claude/snowflake-profiles.json."""
    if not SNOWFLAKE_PROFILES_PATH.exists():
        return []
    raw = json.loads(SNOWFLAKE_PROFILES_PATH.read_text())
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "profiles" in raw:
        return raw["profiles"]
    return []


@app.command("list")
def list_profiles(
    snowflake: bool = typer.Option(
        False, "--snowflake",
        help="List Snowflake profiles instead of ThoughtSpot profiles.",
    ),
) -> None:
    """List configured profiles.

    By default lists ThoughtSpot profiles (from ~/.claude/thoughtspot-profiles.json).
    Use --snowflake to list Snowflake profiles (from ~/.claude/snowflake-profiles.json).
    Credentials are never shown.
    """
    if snowflake:
        sf_profiles = load_snowflake_profiles()
        if not sf_profiles:
            typer.echo(
                f"No Snowflake profiles found in {SNOWFLAKE_PROFILES_PATH}.\n"
                "Run /ts-profile-snowflake to add a profile."
            )
            raise typer.Exit(1)
        for p in sf_profiles:
            method = p.get("method", "unknown")
            account = p.get("account") or p.get("cli_connection", "")
            warehouse = p.get("default_warehouse", "")
            typer.echo(f"  {p['name']:30s}  {method:8s}  {account:40s}  {warehouse}")
        return

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
