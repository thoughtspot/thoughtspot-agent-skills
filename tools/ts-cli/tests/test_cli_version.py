"""`ts --version` prints the package version (skills gate on it, e.g. ts-dependency-cleanup)."""
from typer.testing import CliRunner

from ts_cli import __version__
from ts_cli.cli import app


def test_version_prints_the_package_version():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_version_does_not_shadow_subcommands():
    assert CliRunner().invoke(app, ["dependency", "rollback", "--help"]).exit_code == 0
