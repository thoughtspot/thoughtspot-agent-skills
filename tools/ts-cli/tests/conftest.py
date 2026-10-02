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

NOTE for anything added here that a test module needs to import by bare name: `conftest`
itself is NOT a safe bare-import target, even though this directory is on `sys.path`.
`scripts/pre-commit.sh` and `.github/workflows/validate.yml` both invoke
`pytest tools/ts-cli/tests/ tools/validate/tests/` as one combined run, and
`tools/validate/tests/` has its own `conftest.py`. pytest imports every `conftest.py` it
discovers, and a later bare `from conftest import plain` binds to whichever module is
already cached in `sys.modules["conftest"]` -- not necessarily this package's own file.
(Confirmed live: it resolved to `tools/validate/tests/conftest.py` and raised
`ImportError: cannot import name 'plain'`.) Anything test modules need to bare-import
belongs in a uniquely named module instead -- see `ansi.py` for the pattern.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def isolated_dbt_artifact_cache(tmp_path, monkeypatch):
    """Give every test its own dbt Cloud artifact cache directory.

    `ts_cli.dbt.cloud_api.fetch_artifact` caches a run's artifacts in the OS
    temp dir keyed on `(profile slug, run_id, artifact)`. Test fixtures reuse
    small run ids (7, 99), so without this a manifest written by one test is
    served to the next -- the second test's fake HTTP is never called and its
    call-count assertion fails, or worse, passes for the wrong reason. Autouse
    because a test that forgets it fails somewhere else entirely.
    """
    from ts_cli.dbt import cloud_api

    monkeypatch.setattr(
        cloud_api, "artifact_cache_path",
        lambda ctx, run_id, name: tmp_path / f"artifact_{ctx.slug}_{run_id}_{name}")
