"""ts — ThoughtSpot CLI entrypoint."""
from __future__ import annotations

import typer

from ts_cli.commands import aggregate, audit, auth, connections, databricks, dependency, dependency_apply, load, metadata, model, orgs, powerbi, profiles, qlik, sisense, snowflake, spotql, spotter, tables, tableau, tml, users, variables  # noqa: F401 — dependency_apply registers `apply-change` on dependency.app at import

app = typer.Typer(
    name="ts",
    help="ThoughtSpot REST API CLI.\n\nWraps common ThoughtSpot API operations used by Claude skills.",
    no_args_is_help=True,
)

app.add_typer(audit.app, name="audit")
app.add_typer(aggregate.app, name="aggregate")
app.add_typer(auth.app, name="auth")
app.add_typer(connections.app, name="connections")
app.add_typer(databricks.app, name="databricks")
app.add_typer(dependency.app, name="dependency")
app.add_typer(metadata.app, name="metadata")
app.add_typer(model.app, name="model")
app.add_typer(orgs.app, name="orgs")
app.add_typer(tables.app, name="tables")
app.add_typer(tml.app, name="tml")
app.add_typer(profiles.app, name="profiles")
app.add_typer(spotql.app, name="spotql")
app.add_typer(spotter.app, name="spotter")
app.add_typer(users.app, name="users")
app.add_typer(variables.app, name="variables")
app.add_typer(tableau.app, name="tableau")
app.add_typer(sisense.app, name="sisense")
app.add_typer(qlik.app, name="qlik")
app.add_typer(powerbi.app, name="powerbi")
app.add_typer(load.app, name="load")
app.add_typer(snowflake.app, name="snowflake")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
