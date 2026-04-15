"""ts — ThoughtSpot CLI entrypoint."""
from __future__ import annotations

import typer

from ts_cli.commands import auth, connections, metadata, profiles, tables, tml

app = typer.Typer(
    name="ts",
    help="ThoughtSpot REST API CLI.\n\nWraps common ThoughtSpot API operations used by Claude skills.",
    no_args_is_help=True,
)

app.add_typer(auth.app, name="auth")
app.add_typer(connections.app, name="connections")
app.add_typer(metadata.app, name="metadata")
app.add_typer(tables.app, name="tables")
app.add_typer(tml.app, name="tml")
app.add_typer(profiles.app, name="profiles")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
