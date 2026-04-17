"""ts profiles — list configured ThoughtSpot profiles."""
from __future__ import annotations

import json

import typer

from ts_cli.client import PROFILES_PATH, load_profiles

app = typer.Typer(help="Profile management commands.")


@app.command("list")
def list_profiles() -> None:
    """List all configured ThoughtSpot profiles.

    Shows profile names, URLs, usernames, and auth methods.
    Credentials are never shown.
    """
    profiles = load_profiles()
    if not profiles:
        typer.echo(
            f"No profiles found in {PROFILES_PATH}.\n"
            "Run /ts-profile-setup to add a profile."
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
