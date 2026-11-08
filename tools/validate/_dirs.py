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
======================  ===================================================

Both use the ``ts`` CLI, so every validator scans both. The CoCo Snowsight and
Databricks Genie runtimes were retired on 2026-11-08 (archived at git tag
``runtimes-archive-2026-11-08``; see ``.claude/rules/runtime-coverage.md``). With
them went the split between "every runtime" and "the runtimes that have the ``ts``
CLI", so there is one tuple. Adding a runtime here is the single edit a future
rename or new runtime needs, and the validators pick it up automatically; a runtime
without the ``ts`` CLI would need that split back, so add one deliberately.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

CLI = "cli"
CLAUDE = "claude"

#: Every skill-serving runtime, in canonical order (cli, claude).
ALL_RUNTIMES = (CLI, CLAUDE)


def agents_path(runtime: str) -> str:
    """Repo-relative ``agents/<runtime>`` path for a runtime short name."""
    return f"agents/{runtime}"


#: ``("agents/cli", "agents/claude")``.
ALL_RUNTIME_PATHS = tuple(agents_path(r) for r in ALL_RUNTIMES)


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
