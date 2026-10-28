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
#
# CHECKS_PYTHON overrides the search (BL-436): the search takes the NEWEST Python with
# pytest, so a CI-equivalent virtual environment lost to any newer one on PATH. When
# set (a path, relative to the checkout root both callers cd to, or a command name
# looked up on PATH), it must run as Python 3.10+ and import pytest; anything else
# stops the caller here. The probe must PRINT `ok`: an exit status alone accepts
# `true`, `:` or `echo`, and the callers would then read every check's exit 0 as
# PASS. It never falls back to the search: that would run the checks on an
# interpreter the user just said not to use. `exit`, not `return`: both callers must
# stop, whatever their `set` options. Status 2 is pr-ready's "the run could not start".
PYTHON_BIN=""
if [ -n "${CHECKS_PYTHON+set}" ]; then
  _checks_python="$(command -v "$CHECKS_PYTHON" 2>/dev/null || true)"
  if [ -z "$_checks_python" ]; then
    echo "Error: CHECKS_PYTHON='$CHECKS_PYTHON' is not an executable file or a command on PATH." >&2
    echo "  Point it at the interpreter to run the checks with (see .github/CONTRIBUTING.md)," >&2
    echo "  or unset it to use the newest python3.1x with pytest on PATH." >&2
    exit 2
  fi
  # "old" before pytest is imported, so a 3.9 with pytest is told apart from no pytest.
  _probe="$("$_checks_python" -c 'import sys; print("old" if sys.version_info < (3, 10) else ("ok" if __import__("pytest") else ""))' 2>/dev/null || true)"
  if [ "$_probe" = "old" ]; then
    echo "Error: CHECKS_PYTHON='$CHECKS_PYTHON' ($_checks_python) is older than Python 3.10," >&2
    echo "  which ts-cli requires. Point CHECKS_PYTHON at a 3.10+ interpreter with CI's packages" >&2
    echo "  (see .github/CONTRIBUTING.md), or unset it to search PATH." >&2
    exit 2
  fi
  if [ "$_probe" != "ok" ]; then
    echo "Error: CHECKS_PYTHON='$CHECKS_PYTHON' ($_checks_python) did not run as a Python that" >&2
    echo "  can import pytest. Install CI's packages into it (see .github/CONTRIBUTING.md), point" >&2
    echo "  CHECKS_PYTHON at an interpreter that has them, or unset it to search PATH." >&2
    exit 2
  fi
  PYTHON_BIN="$_checks_python"
  unset _checks_python _probe
  return 0
fi
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
  echo "  Remedy: a virtual environment with CI's packages, named by CHECKS_PYTHON (.github/CONTRIBUTING.md)."
  echo ""
fi
