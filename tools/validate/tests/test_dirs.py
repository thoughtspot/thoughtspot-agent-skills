"""Unit tests for the shared runtime-directory registry (`_dirs.py`, BL-110).

`_dirs` is the single source of truth ~15 validators now import instead of each
hard-coding `("agents/cli", "agents/claude", "agents/coco-snowsight")`. These tests
pin the constant shapes those validators rely on and assert the listed runtimes
actually exist on disk — so a directory rename fails loudly here rather than
silently turning a downstream validator into a no-op (the exact failure mode
BL-110 set out to prevent).
"""
from __future__ import annotations

from pathlib import Path

import _dirs

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_all_runtimes_canonical_order():
    assert _dirs.ALL_RUNTIMES == ("cli", "claude", "coco-snowsight")


def test_cli_runtimes_excludes_coco():
    # CoCo runs inside Snowsight with no `ts` CLI — the CLI-family scans
    # (direct-requests, flag usage, smoke tests) must never include it.
    assert _dirs.CLI_RUNTIMES == ("cli", "claude")
    assert _dirs.COCO not in _dirs.CLI_RUNTIMES


def test_cli_runtimes_is_prefix_of_all_runtimes():
    # Preserves the (cli, claude) ordering shared between the two tuples so a
    # validator can swap CLI_RUNTIMES for ALL_RUNTIMES without reordering output.
    assert _dirs.ALL_RUNTIMES[: len(_dirs.CLI_RUNTIMES)] == _dirs.CLI_RUNTIMES


def test_named_constants_match_tuples():
    assert (_dirs.CLI, _dirs.CLAUDE, _dirs.COCO) == _dirs.ALL_RUNTIMES


def test_path_tuples_are_agents_prefixed():
    assert _dirs.ALL_RUNTIME_PATHS == (
        "agents/cli",
        "agents/claude",
        "agents/coco-snowsight",
    )
    assert _dirs.CLI_RUNTIME_PATHS == ("agents/cli", "agents/claude")
    assert _dirs.agents_path("cli") == "agents/cli"


def test_every_listed_runtime_dir_exists():
    # The load-bearing guard: if someone renames a runtime dir but forgets to
    # update _dirs, this fails — instead of a downstream validator silently
    # scanning a non-existent directory and reporting PASS.
    for runtime in _dirs.ALL_RUNTIMES:
        assert (REPO_ROOT / "agents" / runtime).is_dir(), (
            f"agents/{runtime} listed in _dirs.ALL_RUNTIMES but missing on disk"
        )


def test_runtime_globs_concatenates_in_runtime_order(tmp_path):
    # Two runtimes, one SKILL.md each; runtime order must be preserved.
    (tmp_path / "agents" / "cli" / "skill-a").mkdir(parents=True)
    (tmp_path / "agents" / "cli" / "skill-a" / "SKILL.md").write_text("x")
    (tmp_path / "agents" / "coco-snowsight" / "skill-b").mkdir(parents=True)
    (tmp_path / "agents" / "coco-snowsight" / "skill-b" / "SKILL.md").write_text("x")

    got = _dirs.runtime_globs(tmp_path, "*/SKILL.md", runtimes=("cli", "coco-snowsight"))
    names = [p.parent.name for p in got]
    assert names == ["skill-a", "skill-b"]


def test_runtime_globs_defaults_to_all_runtimes(tmp_path):
    (tmp_path / "agents" / "claude" / "only").mkdir(parents=True)
    (tmp_path / "agents" / "claude" / "only" / "SKILL.md").write_text("x")
    got = _dirs.runtime_globs(tmp_path, "*/SKILL.md")
    assert [p.parent.name for p in got] == ["only"]


def test_runtime_globs_missing_dir_is_skipped(tmp_path):
    # No agents/ tree at all — glob yields nothing, no error.
    assert _dirs.runtime_globs(tmp_path, "*/SKILL.md") == []
