"""A traceback must never print frame locals.

A local can hold a credential, a token or a connection's configuration (the audit's
connection fetch parses one before reducing it to facts). Typer's
`pretty_exceptions_show_locals` defaulted to True before typer 0.13, and pyproject
allows typer>=0.12, so the root app sets it to False explicitly rather than rely on the
installed default.
"""
from __future__ import annotations

import ast
from pathlib import Path

import ts_cli
from ts_cli.cli import app

PACKAGE = Path(ts_cli.__file__).parent


def _typer_calls(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "Typer":
                yield {k.arg: k.value for k in node.keywords if k.arg}


def _hides_locals(kwargs: dict) -> bool:
    value = kwargs.get("pretty_exceptions_show_locals")
    return isinstance(value, ast.Constant) and value.value is False


def test_the_root_app_hides_frame_locals_explicitly():
    assert app.pretty_exceptions_show_locals is False
    [root] = list(_typer_calls(PACKAGE / "cli.py"))
    assert _hides_locals(root)


def test_no_typer_app_turns_pretty_exceptions_on_without_hiding_locals():
    """A sub-app given its own pretty-exception settings must hide locals too."""
    for path in sorted(PACKAGE.rglob("*.py")):
        for kwargs in _typer_calls(path):
            if any(k.startswith("pretty_exceptions") for k in kwargs):
                assert _hides_locals(kwargs), path.relative_to(PACKAGE)
