"""ts — ThoughtSpot CLI entrypoint."""
from __future__ import annotations

import typer

from ts_cli.commands import auth, connections, metadata, orgs, profiles, spotql, tables, tml, users, variables

app = typer.Typer(
    name="ts",
    help="ThoughtSpot REST API CLI.\n\nWraps common ThoughtSpot API operations used by Claude skills.",
    no_args_is_help=True,
)

app.add_typer(auth.app, name="auth")
app.add_typer(connections.app, name="connections")
app.add_typer(metadata.app, name="metadata")
app.add_typer(orgs.app, name="orgs")
app.add_typer(tables.app, name="tables")
app.add_typer(tml.app, name="tml")
app.add_typer(profiles.app, name="profiles")
app.add_typer(spotql.app, name="spotql")
app.add_typer(users.app, name="users")
app.add_typer(variables.app, name="variables")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
