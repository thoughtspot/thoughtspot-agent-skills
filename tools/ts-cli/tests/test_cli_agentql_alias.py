"""The AgentQL query commands are registered as `ts agentql` (primary), with
`ts spotql` kept as a hidden, deprecated back-compat alias.

The product was renamed SpotQL -> AgentQL; the CLI command followed. `ts spotql`
must keep working (existing scripts/skills) but must not be advertised in help.
Both names route to the same subcommands (generate-sql / fetch-data /
classify-columns). The server contract (`/data/spotql/*` endpoints, the
`spotql_query` field) is unrelated to the command name and is not exercised here.
"""
from typer.testing import CliRunner

from ts_cli.cli import app

runner = CliRunner()

SUBCOMMANDS = ("generate-sql", "fetch-data", "classify-columns")


def test_agentql_is_the_primary_command():
    res = runner.invoke(app, ["agentql", "--help"])
    assert res.exit_code == 0
    for sub in SUBCOMMANDS:
        assert sub in res.output, f"{sub} missing from `ts agentql` help"


def test_spotql_alias_still_works():
    res = runner.invoke(app, ["spotql", "--help"])
    assert res.exit_code == 0
    for sub in SUBCOMMANDS:
        assert sub in res.output, f"{sub} missing from `ts spotql` alias help"


def test_top_level_help_shows_agentql_and_hides_spotql():
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "agentql" in res.output
    # spotql is registered hidden=True, so it must not appear in the command list
    assert "spotql" not in res.output


def test_both_names_reach_each_subcommand():
    for name in ("agentql", "spotql"):
        for sub in SUBCOMMANDS:
            res = runner.invoke(app, [name, sub, "--help"])
            assert res.exit_code == 0, f"`ts {name} {sub} --help` failed"
