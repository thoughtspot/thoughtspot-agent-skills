#!/usr/bin/env bash
# scripts/lib/python-bin.sh
#
# Sourced, not run: sets PYTHON_BIN for the caller. Shared by scripts/pre-commit.sh
# and scripts/pr-ready.sh so both pick the same interpreter the same way (moved
# here unchanged from pre-commit.sh). No `set` options of its own: it inherits the
# caller's.

# ── Python interpreter resolution ───────────────────────────────────────────
# ts-cli's own floor is Python >=3.10 (tools/ts-cli/pyproject.toml), but some
# machines only expose an EOL system `python3` (e.g. macOS ships 3.9.6). Prefer
# the newest 3.10+ interpreter on PATH that actually has this repo's tooling
# installed — pytest is a hard requirement for both callers, with no graceful
# fallback, so picking a bare interpreter with nothing installed would turn every
# check into a false FAIL. Fall back to plain `python3` with a warning rather than
# hard-failing the commit (or the pr-ready run) over interpreter selection itself.
PYTHON_BIN=""
# Newest first. Must stay in step with requires-python in tools/ts-cli/pyproject.toml
  # (>=3.10,<3.15) and the CI pytest-matrix. Omitting 3.13/3.14 sent contributors on
  # those interpreters to bare `python3` — the 3.9 system Python with no pytest — so
  # every unit-test check reported a false FAIL (audit 6.x).
  for _candidate in python3.14 python3.13 python3.12 python3.11 python3.10; do
  if command -v "$_candidate" >/dev/null 2>&1 && "$_candidate" -c "import pytest" >/dev/null 2>&1; then
    PYTHON_BIN="$_candidate"
    break
  fi
done
unset _candidate

if [ -z "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
  echo "Warning: no python3.10+ interpreter with pytest installed found on PATH"
  echo "  (checked python3.14, python3.13, python3.12, python3.11, python3.10). Falling back to '$PYTHON_BIN'"
  echo "  ($($PYTHON_BIN --version 2>&1)) — ts-cli requires Python >=3.10."
  echo ""
fi
