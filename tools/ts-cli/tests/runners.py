"""The two `CliRunner`s the ts-cli tests share, defined once (BL-139).

## Why two runners

They are not interchangeable, and picking the wrong one produces a passing test that
proves nothing:

- **`runner`** is **stream-separated**, so `result.stdout` is parseable JSON. Use it for
  any assertion on a command's structured output. It DROPS manually-printed stderr.
- **`msg_runner`** **mixes** the streams, which is the only way to see a manual
  `print(..., file=sys.stderr)`. Use it for diagnostics, warnings and refusal messages.

Never assert parsed stdout and stderr text in the same test — no single runner supports
both, and a test that appears to do so is reading one stream while believing it read the
other.

## Why this module exists at all

22 test modules each repeated:

```python
try:
    runner = CliRunner(mix_stderr=False)
except TypeError:          # Click >= 8.2 removed the parameter
    runner = CliRunner()
```

Click 8.2 removed `mix_stderr` entirely, and it raises `TypeError` at CONSTRUCTION, not at
call time. Click is pinned at 8.1.8 today so the `try` branch always wins. The moment that
pin moves past 8.1.x, every one of those runners silently becomes a *mixing* runner —
**and no test fails at the point of upgrade**. What breaks instead is every
`json.loads(result.stdout)` assertion across those modules, each surfacing as a confusing
JSON-decode error with no hint that an unrelated Click bump is the cause.

Defining both here turns that eventual fix — reconstructing `msg_runner`'s mixing
behaviour once `mix_stderr` is gone — from a 22-file sweep into a one-file change.

## Why here and not `conftest.py`

BL-139 proposed `conftest.py`. That is wrong for this repo, for the reason its own
docstring records: `scripts/pre-commit.sh` and CI both run
`pytest tools/ts-cli/tests/ tools/validate/tests/` as ONE invocation, and both directories
have a `conftest.py`. A bare `from conftest import runner` binds to whichever is already
in `sys.modules["conftest"]` — confirmed live to resolve to the wrong one. A uniquely
named module has no such collision, which is exactly why `ansi.py` exists.
"""
from __future__ import annotations

from typing import Any

# typer, not click: typer 0.26+ dropped its click dependency and vendored the
# command layer, so `import click` is not guaranteed in this environment.
from typer.testing import CliRunner


def _separated() -> Any:
    """A stream-separated runner, or the best available on this Click."""
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        # Click >= 8.2: the parameter is gone and streams are always separated, so a
        # bare CliRunner already gives what `mix_stderr=False` used to. Nothing to do.
        return CliRunner()


def _mixing() -> Any:
    """A runner whose `result.output` includes manually-printed stderr.

    On Click 8.1.x a bare `CliRunner()` mixes by default. On 8.2+ it does not, and there
    is no parameter to ask for it — so this will need reconstructing (most likely by
    capturing `result.stderr` separately and asserting against that instead). Kept as its
    own function so that change lands in one place rather than across 22 modules.
    """
    return CliRunner()


runner = _separated()
msg_runner = _mixing()
