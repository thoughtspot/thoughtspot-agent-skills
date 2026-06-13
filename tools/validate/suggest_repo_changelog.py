#!/usr/bin/env python3
"""
suggest_repo_changelog.py — interactively propose a CHANGELOG.md entry for significant
staged changes.

Triggered by the pre-commit hook when any of these are staged:
  - A new SKILL.md file (new skill being added)
  - A ts-cli version bump (pyproject.toml or __init__.py)
  - A new file in agents/shared/

If CHANGELOG.md is itself staged in this commit, exits silently — the developer
already wrote the entry for this change. (The gate is per-commit, not per-day:
a pre-existing same-day section from an earlier commit does NOT satisfy it.)

Skips silently in non-TTY environments (CI, GUI git clients) in suggestion mode;
--check mode runs everywhere and blocks the commit.

Usage:
    python tools/validate/suggest_repo_changelog.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

CHANGELOG = "CHANGELOG.md"
TODAY = str(date.today())


# ── git helpers ───────────────────────────────────────────────────────────────

def get_staged_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-status"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return result.stdout.splitlines()


def restage_file(path: Path, repo_root: Path) -> None:
    subprocess.run(
        ["git", "add", str(path.relative_to(repo_root))],
        cwd=repo_root, check=True,
    )


# ── change detection ──────────────────────────────────────────────────────────

# Top row of a skill's "## Changelog" table: | X.Y.Z | YYYY-MM-DD | summary |
_SKILL_VER_RE = re.compile(r"^\|\s*(\d+)\.(\d+)\.(\d+)\s*\|")


def _git_show(ref: str, repo_root: Path) -> str:
    """Return file contents at a git ref (e.g. ':path' for staged, 'HEAD:path'). '' if absent."""
    result = subprocess.run(
        ["git", "show", ref], capture_output=True, text=True, cwd=repo_root,
    )
    return result.stdout if result.returncode == 0 else ""


def _skill_changelog_version(text: str) -> tuple[int, int, int] | None:
    """Extract (major, minor, patch) from the top row of a SKILL.md '## Changelog' table."""
    if "## Changelog" not in text:
        return None
    body = text.split("## Changelog", 1)[1]
    for line in body.splitlines():
        m = _SKILL_VER_RE.match(line.strip())
        if m:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def detect_significant_changes(staged_lines: list[str], repo_root: Path) -> list[tuple[str, str]]:
    """
    Return a list of (type, description) tuples for significant staged changes.
    type is one of: 'new-skill', 'ts-cli-bump', 'new-shared', 'skill-bump'
    """
    changes = []
    for line in staged_lines:
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        status, path = parts[0].strip(), parts[1].strip()

        # New SKILL.md added
        if status == "A" and path.endswith("/SKILL.md") and path.startswith(
            ("agents/cli/", "agents/claude/", "agents/coco-snowsight/")
        ):
            skill_name = path.split("/")[2]
            changes.append(("new-skill", f"feat: add {skill_name} skill"))

        # Significant change to an existing skill — the top changelog version's MAJOR or
        # MINOR increased (patch-only bumps stay in the skill's own changelog, per the repo
        # convention). Catches large skill evolutions that warrant a repo-level note.
        elif status == "M" and path.endswith("/SKILL.md") and "/" in path:
            skill_name = path.split("/")[2] if len(path.split("/")) > 2 else Path(path).parent.name
            new_v = _skill_changelog_version(_git_show(f":{path}", repo_root))
            old_v = _skill_changelog_version(_git_show(f"HEAD:{path}", repo_root))
            if new_v and old_v and new_v[:2] > old_v[:2]:
                nv = ".".join(map(str, new_v))
                changes.append(("skill-bump", f"feat: update {skill_name} to v{nv}"))

        # ts-cli version bump
        elif status == "M" and path in (
            "tools/ts-cli/pyproject.toml",
            "tools/ts-cli/ts_cli/__init__.py",
        ):
            # Read the new version from the staged file
            m = re.search(r'version\s*=\s*["\']([^"\']+)["\']', _git_show(f":{path}", repo_root))
            ver = m.group(1) if m else "?"
            changes.append(("ts-cli-bump", f"chore: bump ts-cli to v{ver}"))

        # New shared reference file
        elif status == "A" and path.startswith("agents/shared/"):
            filename = Path(path).stem
            changes.append(("new-shared", f"docs: add {filename} shared reference"))

    return changes


# ── changelog helpers ─────────────────────────────────────────────────────────

def changelog_already_staged(staged_lines: list[str]) -> bool:
    """Return True if CHANGELOG.md is already in the staged changes."""
    return any(
        line.split("\t", 1)[-1].strip() == CHANGELOG
        for line in staged_lines
    )


def insert_today_section(changelog_path: Path, entries: list[str]) -> None:
    """Prepend a new dated section to CHANGELOG.md."""
    text = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else ""
    separator_pos = text.find("---")
    if separator_pos == -1:
        separator_pos = text.find("## ")
    if separator_pos == -1:
        separator_pos = len(text)

    entry_lines = "\n".join(f"- {e}" for e in entries)
    new_section = f"\n## {TODAY}\n{entry_lines}\n"

    updated = text[:separator_pos] + new_section + "\n" + text[separator_pos:]
    changelog_path.write_text(updated, encoding="utf-8")


# ── interactive prompt ────────────────────────────────────────────────────────

def prompt_user(entries: list[str]) -> tuple[bool, list[str]]:
    """Prompt the user to accept, edit, or skip the proposed changelog entries."""
    print()
    print(f"  Repo changelog: {TODAY}")
    for e in entries:
        print(f"    - {e}")
    print()
    print("  [A]ccept  [E]dit  [S]kip  ", end="", flush=True)

    try:
        choice = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False, entries

    if choice in ("a", ""):
        return True, entries

    if choice == "e":
        print("  Enter entries one per line. Blank line to finish:")
        edited: list[str] = []
        try:
            while True:
                line = input("    > ").strip()
                if not line:
                    break
                edited.append(line)
        except (EOFError, KeyboardInterrupt):
            pass
        return (True, edited) if edited else (False, entries)

    return False, entries


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest CHANGELOG.md entries interactively.")
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    parser.add_argument(
        "--check", action="store_true",
        help="Gating mode: exit non-zero (no prompt) if a significant staged change has no "
             "same-day CHANGELOG.md entry. Works in non-TTY (CI / agent commits).",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    changelog_path = repo_root / CHANGELOG
    staged_lines = get_staged_files(repo_root)

    # The gate is PER-COMMIT, not per-day: a significant change must carry its own
    # staged CHANGELOG.md hunk. A pre-existing "## <today>" section from an earlier
    # commit no longer satisfies it (audit F2 — that per-day escape let later commits
    # ship significant changes with no changelog line of their own).
    if changelog_already_staged(staged_lines):
        return 0

    changes = detect_significant_changes(staged_lines, repo_root)
    if not changes:
        return 0

    entries = [desc for _, desc in changes]

    # ── Gating mode: block the commit instead of prompting ──
    if args.check:
        print("  Significant change(s) staged with no CHANGELOG.md entry for today:")
        for e in entries:
            print(f"    - {e}")
        print()
        print(f"  Add a '## {TODAY}' section to CHANGELOG.md (run interactively to auto-insert),")
        print("  then re-stage. To bypass in an emergency: git commit --no-verify")
        return 1

    # ── Interactive suggestion (TTY only) ──
    if not sys.stdin.isatty():
        return 0

    should_apply, final_entries = prompt_user(entries)

    if should_apply and final_entries:
        insert_today_section(changelog_path, final_entries)
        restage_file(changelog_path, repo_root)
        print(f"  ✓ CHANGELOG.md updated and re-staged.")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
