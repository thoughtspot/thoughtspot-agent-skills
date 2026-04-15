"""ts auth — verify authentication and manage cached tokens."""
from __future__ import annotations

import json
import sys
from typing import Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="Authentication commands.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")


@app.command()
def whoami(
    profile: Optional[str] = _profile_option,
) -> None:
    """Verify authentication and print the current user's details."""
    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.get("/api/rest/2.0/auth/session/user")
    print(json.dumps(resp.json()))


@app.command()
def token(
    profile: Optional[str] = _profile_option,
) -> None:
    """Print the current bearer token. Useful for debugging or passing to other tools."""
    client = ThoughtSpotClient(resolve_profile(profile))
    print(client.get_token())


@app.command()
def logout(
    profile: Optional[str] = _profile_option,
) -> None:
    """Clear the cached token so the next command re-authenticates."""
    name = resolve_profile(profile)
    client = ThoughtSpotClient(name)
    if client.clear_token_cache():
        typer.echo(f"Token cache cleared for profile '{name}'.")
    else:
        typer.echo(f"No cached token found for profile '{name}'.")
