#!/usr/bin/env python3
"""
check_repo_hygiene.py — guard against two recurring classes of repo-root litter
(2026-07-29 audit findings 1.1 and 1.2).

1.2 — Tracked-but-ignored files: `docs/superpowers/plans/` is a gitignored convention
(implementation-plan scratch files), but two real plan files were tracked anyway
(added in PRs #139/#140) and stayed invisible to every commit and review since —
`.gitignore` said "ignore this," `git status` agreed, and nobody noticed they were
tracked. `git ls-files -ci --exclude-standard` is the exact query for "tracked files
that .gitignore (or any exclude source) also declares ignored"; this validator asserts
it returns nothing.

1.1 — Unexpected top-level tracked files: `err.txt`, a 27-line urllib3 stderr capture,
was accidentally committed at the repo root (PR #350) — referenced nowhere, and
leaking an internal host IP. Every legitimate top-level entry today is either one of a
small, known set of files (README, CLAUDE.md, LICENSE, ...) or a directory (agents/,
docs/, tools/, ...) — directories never appear as their own line in `git ls-files`, so
checking bare filenames (no "/") against an explicit allowlist catches exactly this
class of accidental commit.

Why both live in one validator: they're the same finding class (a file that should
never have been tracked, caught only by manual review) with two different detection
queries — no reason to split them into sibling scripts.

Exit codes:
  0 — no tracked-but-ignored files, no unexpected top-level tracked files
  1 — at least one of either

Run manually:
    python3 tools/validate/check_repo_hygiene.py --root .
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _git import git_paths, tracked_relpaths

# Finding 1.1: the only files legitimately tracked at the repo root (verified
# 2026-07-29, after this same audit round's PR removes err.txt). Anything else
# tracked directly at root needs either removal or a deliberate, reviewed addition
# to this allowlist.
ALLOWED_TOP_LEVEL_FILES = {
    ".gitignore",
    ".gitattributes",  # not present today, but a legitimate root file if ever added
    ".mcp.json",
    "CHANGELOG.md",
    "CLAUDE.md",
    "LICENSE",
    "README.md",
}


def _git(args: list[str], repo_root: Path) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=repo_root, check=False,
    )
    return result.stdout


def tracked_but_ignored(repo_root: Path) -> list[str]:
    """Finding 1.2 — files git tracks that an exclude source (.gitignore, etc.) also
    declares ignored. Empty list = clean."""
    return sorted(git_paths(["ls-files", "-ci", "--exclude-standard"], repo_root))


def unexpected_top_level_files(repo_root: Path) -> list[str]:
    """Finding 1.1 — a bare filename (no "/") tracked at the repo root that isn't on
    ALLOWED_TOP_LEVEL_FILES. Empty list = clean."""
    out = "\n".join(git_paths(["ls-files"], repo_root))
    unexpected = []
    for line in out.splitlines():
        line = line.strip()
        if not line or "/" in line:
            continue  # a directory entry, or not top-level
        if line not in ALLOWED_TOP_LEVEL_FILES:
            unexpected.append(line)
    return sorted(unexpected)


# Directory names that hold RUNTIME OUTPUT, never source. `ts migrate audit -o ./plan/`
# is the documented example. Nothing tracked should ever live under one of these.
RUNTIME_OUTPUT_DIRS = {
    "plan",       # ts migrate audit / plan output
    "out",        # converter output (ts tableau build-model, qlik, powerbi, sisense)
}


def tracked_runtime_output(repo_root: Path) -> list[str]:
    """Finding 1.1 (2026-08-26) — a tracked file under a runtime-output directory.

    Three files (`audit-report.md`, `audit-report.json`, `column-mapping.csv`) were
    committed in f48a179 while staging the migrate runbook and sat in
    `tools/ts-cli/plan/` ever since, carrying real instance GUIDs and an org column
    layout from that run. No test or validator referenced the path.

    Both pre-existing queries here were structurally blind to it:
    `tracked_but_ignored` needs a matching exclude rule, and `.gitignore` had no
    `plan/` entry; `unexpected_top_level_files` is root-only by design, so the same
    class one directory deeper was unguarded. This is the query that closes it — the
    `.gitignore` entry alone would not, because git keeps tracking a file already in
    the index regardless of a later ignore rule.
    """
    hits = []
    for rel in git_paths(["ls-files"], repo_root):
        parts = rel.split("/")
        if any(seg in RUNTIME_OUTPUT_DIRS for seg in parts[:-1]):
            hits.append(rel)
    return sorted(hits)


def unparseable_claude_json(repo_root: Path) -> list[str]:
    """Finding 18.2 — every `.json` / `.json.example` under `.claude/` must parse.

    `settings.local.json.example` was a JSON object followed by ~30 lines of `//`
    prose, so `json.load` failed with `Extra data: line 12`. Its own step 1 is
    `cp … .claude/settings.local.json`, and settings files are strict JSON — so a
    contributor following the documented flow got a Settings Error on next launch and
    lost their local settings file until they hand-stripped the comments.

    A `.json.example` is checked as strictly as a `.json` precisely because it is
    consumed by `cp`: being an example is what makes it dangerous, not what excuses it.
    """
    import json

    claude_dir = repo_root / ".claude"
    if not claude_dir.is_dir():
        return []
    bad = []
    for path in sorted(claude_dir.rglob("*.json")) + sorted(claude_dir.rglob("*.json.example")):
        rel = path.relative_to(repo_root)
        # settings.local.json is gitignored and personal; not ours to police.
        if path.name == "settings.local.json":
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            bad.append(f"{rel}: {exc}")
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    sections: list[str] = []

    ignored_tracked = tracked_but_ignored(root)
    if ignored_tracked:
        sections.append(
            f"{len(ignored_tracked)} tracked-but-gitignored file(s) found (audit finding 1.2):"
        )
        sections.extend(f"  ✗ {f}" for f in ignored_tracked)

    bad_json = unparseable_claude_json(root)
    if bad_json:
        sections.append(
            f"{len(bad_json)} unparseable JSON file(s) under .claude/ "
            f"(audit finding 18.2) — settings files are STRICT JSON, and a "
            f".json.example is copied straight into one:"
        )
        sections.extend(f"  ✗ {b}" for b in bad_json)

    runtime_output = tracked_runtime_output(root)
    if runtime_output:
        sections.append(
            f"{len(runtime_output)} tracked file(s) under a runtime-output directory "
            f"(audit finding 1.1) — these are command output, not source:"
        )
        sections.extend(f"  ✗ {f}" for f in runtime_output)
        sections.append(
            "  Delete them and keep the directory gitignored. A .gitignore entry alone "
            "does NOT help: git keeps tracking a file already in the index."
        )

    stray = unexpected_top_level_files(root)
    if stray:
        sections.append(
            f"{len(stray)} unexpected top-level tracked file(s) found (audit finding 1.1):"
        )
        sections.extend(f"  ✗ {f}" for f in stray)

    if sections:
        print("\n" + "\n".join(sections))
        print()
        print("Tracked-but-ignored: `git rm --cached <path>` (keep it on disk if still")
        print("needed locally) — a file matching an exclude rule has no business staying")
        print("tracked. Unexpected top-level: `git rm <path>` if accidental, or add the")
        print("name to ALLOWED_TOP_LEVEL_FILES in this validator if it's a deliberate,")
        print("reviewed addition.")
        return 1

    print("Repo hygiene clean: no tracked-but-ignored files, no tracked runtime output, no unexpected top-level files, all .claude/ JSON parses.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
