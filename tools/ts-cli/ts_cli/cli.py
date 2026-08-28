"""ts — ThoughtSpot CLI entrypoint."""
from __future__ import annotations

import typer

from ts_cli.commands import aggregate, alias, audit, auth, connections, databricks, dependency, dependency_apply, domo, groups, load, metadata, migrate, model, orgs, parameterize, powerbi, profiles, publish, publish_planning, qlik, security, security_planning, share, share_planning, sisense, snowflake, spotql, spotter, tables, tableau, tenancy, tenancy_export, tml, users, variables  # noqa: F401 -- dependency_apply registers `apply-change` on dependency.app, parameterize registers `parameterize`/`unparameterize` on metadata.app, publish_planning registers `export`/`resolve` on publish.app, share_planning registers `export`/`resolve`/`apply` on share.app, security_planning registers `resolve`/`build`/`apply`/`import` on security.column_rules_app, tenancy_export registers `export` on tenancy.app, migrate registers the `migrate` group, all at import

app = typer.Typer(
    name="ts",
    # Never render frame locals in a traceback: several commands hold credentials in
    # scope, and `typer>=0.12,<1` permits versions that default this to True (0.12.5
    # does). Explicit here rather than relying on the installed version's default.
    pretty_exceptions_show_locals=False,
    help="ThoughtSpot REST API CLI.\n\nWraps common ThoughtSpot API operations used by Claude skills.",
    no_args_is_help=True,
)

app.add_typer(audit.app, name="audit")
app.add_typer(aggregate.app, name="aggregate")
app.add_typer(alias.app, name="alias")
app.add_typer(auth.app, name="auth")
app.add_typer(connections.app, name="connections")
app.add_typer(databricks.app, name="databricks")
app.add_typer(dependency.app, name="dependency")
app.add_typer(metadata.app, name="metadata")
app.add_typer(model.app, name="model")
app.add_typer(orgs.app, name="orgs")
app.add_typer(groups.app, name="groups")
app.add_typer(tenancy.app, name="tenancy")
app.add_typer(tables.app, name="tables")
app.add_typer(tml.app, name="tml")
app.add_typer(profiles.app, name="profiles")
app.add_typer(publish.app, name="publish")
app.add_typer(share.app, name="share")
app.add_typer(security.app, name="security")
app.add_typer(spotql.app, name="agentql")
app.add_typer(spotql.app, name="spotql", hidden=True)  # deprecated alias for `ts agentql`; kept for back-compat
app.add_typer(spotter.app, name="spotter")
app.add_typer(users.app, name="users")
app.add_typer(variables.app, name="variables")
app.add_typer(tableau.app, name="tableau")
app.add_typer(sisense.app, name="sisense")
app.add_typer(qlik.app, name="qlik")
app.add_typer(powerbi.app, name="powerbi")
app.add_typer(domo.app, name="domo")
app.add_typer(load.app, name="load")
app.add_typer(snowflake.app, name="snowflake")
app.add_typer(migrate.app, name="migrate")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
