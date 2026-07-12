"""Single source of truth for the repo's runtime skill-directory layout.

Before BL-110 (2026-07-11 full-audit finding 4.4) ~18 validators each hard-coded
the runtime dir list — ``("agents/cli", "agents/claude", "agents/coco-snowsight")``
or its short-name / CoCo-excluded variants. A directory rename meant editing every
one, and a missed edit silently reported PASS. Import the constants here instead.

Runtimes (directory names under ``agents/``):

======================  ===================================================
Runtime                 Serves
======================  ===================================================
``cli``                 Canonical CLI skills (Claude Code + Cortex Code CLI)
``claude``              Claude-only annex (currently just ts-profile-snowflake)
``coco-snowsight``      Snowflake Cortex / CoCo (Snowsight stored-proc runtime)
======================  ===================================================

The ``agents/databricks/`` Genie runtime is deliberately NOT represented here — it
sits outside the mirror/coverage tooling by design (see
``.claude/rules/runtime-coverage.md``). Adding a runtime here is the single edit a
future rename or new runtime needs; the validators pick it up automatically.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

CLI = "cli"
CLAUDE = "claude"
COCO = "coco-snowsight"

#: Every skill-serving runtime, in canonical order (cli, claude, coco-snowsight).
ALL_RUNTIMES = (CLI, CLAUDE, COCO)

#: The CLI family only — cli + its Claude-only annex. CoCo is deliberately
#: excluded: it runs inside Snowsight with no ``ts`` CLI, so direct-``requests``,
#: flag-usage and smoke-test scans do not apply to it.
CLI_RUNTIMES = (CLI, CLAUDE)


def agents_path(runtime: str) -> str:
    """Repo-relative ``agents/<runtime>`` path for a runtime short name."""
    return f"agents/{runtime}"


#: ``("agents/cli", "agents/claude", "agents/coco-snowsight")``.
ALL_RUNTIME_PATHS = tuple(agents_path(r) for r in ALL_RUNTIMES)

#: ``("agents/cli", "agents/claude")``.
CLI_RUNTIME_PATHS = tuple(agents_path(r) for r in CLI_RUNTIMES)


def runtime_globs(
    repo_root: Path, suffix: str, runtimes: Iterable[str] = ALL_RUNTIMES
) -> List[Path]:
    """Concatenate ``repo_root.glob(f"agents/{rt}/{suffix}")`` across ``runtimes``.

    Runtime order is preserved (the concatenation order the per-runtime glob
    blocks this replaces relied on); within a runtime the order is the
    filesystem-defined glob order, unchanged from those blocks.
    """
    out: List[Path] = []
    for runtime in runtimes:
        out.extend(repo_root.glob(f"agents/{runtime}/{suffix}"))
    return out
