"""ANSI-escape stripping for CliRunner output asserted against Rich-rendered text.

Rich highlights option-like tokens (e.g. `--add`) and splits them into separately
styled segments with escapes between them, so a literal-substring assertion on
`result.output` fails whenever colour is on -- which CI forces via `FORCE_COLOR`, even
though the identical assertion passes locally, where colour is off and the raw text
matches. Assert against `plain(result)` instead of `result.output` for any Typer usage
error or `BadParameter` message.

A dedicated, uniquely named module here, not a home in `conftest.py`: pytest imports
every `conftest.py` it discovers, and a run that combines sibling test packages in one
invocation -- as `tools/ts-cli/tests/` + `tools/validate/tests/` does in
`scripts/pre-commit.sh` and `.github/workflows/validate.yml` -- ends up with more than
one `conftest.py` competing for the bare module name `conftest`; a later
`from conftest import plain` binds to whichever one pytest happened to import first,
not necessarily this package's own (confirmed live: it resolved to
`tools/validate/tests/conftest.py` and raised `ImportError: cannot import name
'plain'`). A uniquely named module has no such collision. `tests/conftest.py` already
inserts this directory onto `sys.path`, so this module is bare-importable the same way
`fixtures.py` is (see `from fixtures import ...` in test_worked_examples.py, and
`from test_security_commands import ...` in test_security_planning.py) -- just under a
name nothing else in the repo also uses.
"""
from __future__ import annotations

import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def plain(result) -> str:
    """`result.output` with ANSI escapes removed. See module docstring for why."""
    return _ANSI_RE.sub("", result.output or "")
