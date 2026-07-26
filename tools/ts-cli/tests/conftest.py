"""Shared pytest setup for tools/ts-cli/tests.

`tests/__init__.py` makes this directory a package (deliberately -- see the comment in
`scripts/pre-commit.sh` / `.github/workflows/validate.yml` about disambiguating same-named
"tests" packages across the repo in one pytest invocation). That packaging means pytest's
default import mode does NOT put this directory itself on `sys.path`; only
`tools/ts-cli` (the parent with no `__init__.py`) gets inserted, so test modules import as
`tests.test_x`, not `test_x`.

Some test modules import a sibling test module by its bare name (e.g.
`from test_security_commands import FakeClient, FakeResponse` in
test_security_planning.py) rather than `from tests.test_security_commands import ...`,
matching the `from fixtures import ...` convention in test_worked_examples.py. Inserting
this directory directly onto `sys.path` here makes that bare import resolve, without
every test file repeating the `sys.path.insert` boilerplate.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
