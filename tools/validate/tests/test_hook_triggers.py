"""Tripwire: every pre-commit trigger regex must match >=1 tracked path.

A regex that matches nothing means a gate that never fires (audit C8: the
agents/claude -> agents/cli rename silently killed four gates for a month)."""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# Keep in sync with scripts/pre-commit.sh — the test fails loudly if either side drifts.
TRIGGERS = {
    "tml_lint": r"\.md$",
    "smoke_gate": r"agents/(cli|claude)/.*/SKILL\.md",
    "depmgr_nudge": r"^agents/cli/ts-dependency-manager/",
    "main_audit": r"^agents/(cli|claude|coco-snowsight)/",
    "naming_coverage": r"agents/(cli|claude|coco-snowsight)/.*/SKILL\.md",
}


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    return out.stdout.splitlines()


def test_every_trigger_matches_a_tracked_path():
    files = tracked_files()
    for name, pattern in TRIGGERS.items():
        rx = re.compile(pattern)
        assert any(rx.search(f) for f in files), (
            f"trigger '{name}' ({pattern}) matches no tracked file — dead gate")


def test_hook_script_contains_each_trigger():
    hook = (REPO / "scripts" / "pre-commit.sh").read_text()
    for name, pattern in TRIGGERS.items():
        assert pattern in hook, (
            f"trigger '{name}' pattern not found in pre-commit.sh — "
            "update TRIGGERS here AND the hook together")
