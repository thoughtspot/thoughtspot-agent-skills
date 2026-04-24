#!/usr/bin/env python3
"""
suggest_repo_changelog.py — interactively propose a CHANGELOG.md entry for significant
staged changes.

Triggered by the pre-commit hook when any of these are staged:
  - A new SKILL.md file (new skill being added)
  - A ts-cli version bump (pyproject.toml or __init__.py)
  - A new file in agents/shared/

If CHANGELOG.md already has today's date as the latest entry, exits silently —
assumes the developer already updated it for this commit.

Skips silently in non-TTY environments (CI, GUI git clients).

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

def detect_significant_changes(staged_lines: list[str]) -> list[tuple[str, str]]:
    """
    Return a list of (type, description) tuples for significant staged changes.
    type is one of: 'new-skill', 'ts-cli-bump', 'new-shared'
    """
    changes = []
    for line in staged_lines:
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        status, path = parts[0].strip(), parts[1].strip()

        # New SKILL.md added (any runtime)
        if status == "A" and path.endswith("/SKILL.md") and path.startswith("agents/"):
            skill_name = path.split("/")[2]
            runtime = path.split("/")[1]
            label = f"feat: add {skill_name} skill" + (f" [{runtime}]" if runtime != "claude" else "")
            changes.append(("new-skill", label))

        # New .mdc Cursor rule added
        elif status == "A" and path.startswith("agents/cursor/rules/") and path.endswith(".mdc"):
            skill_name = Path(path).stem
            changes.append(("new-skill", f"feat: add {skill_name} Cursor rule"))

        # ts-cli version bump
        elif status == "M" and path in (
            "tools/ts-cli/pyproject.toml",
            "tools/ts-cli/ts_cli/__init__.py",
        ):
            # Read the new version from the staged file
            result = subprocess.run(
                ["git", "show", f":{path}"],
                capture_output=True, text=True,
            )
            m = re.search(r'version\s*=\s*["\']([^"\']+)["\']', result.stdout)
            ver = m.group(1) if m else "?"
            changes.append(("ts-cli-bump", f"chore: bump ts-cli to v{ver}"))

        # New shared reference file
        elif status == "A" and path.startswith("agents/shared/"):
            filename = Path(path).stem
            changes.append(("new-shared", f"docs: add {filename} shared reference"))

    return changes


# ── changelog helpers ─────────────────────────────────────────────────────────

def changelog_has_today(changelog_path: Path) -> bool:
    """Return True if CHANGELOG.md already has today's date as the most recent entry."""
    if not changelog_path.exists():
        return False
    text = changelog_path.read_text(encoding="utf-8")
    # Find the first ## date line
    m = re.search(r"^## (\d{4}-\d{2}-\d{2})", text, re.MULTILINE)
    return bool(m and m.group(1) == TODAY)


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
    args = parser.parse_args()

    if not sys.stdin.isatty():
        return 0

    repo_root = Path(args.root).resolve()
    changelog_path = repo_root / CHANGELOG
    staged_lines = get_staged_files(repo_root)

    # Already updated CHANGELOG.md in this commit — nothing to do
    if changelog_already_staged(staged_lines):
        return 0

    # Today's section already exists — assume developer updated it earlier today
    if changelog_has_today(changelog_path):
        return 0

    changes = detect_significant_changes(staged_lines)
    if not changes:
        return 0

    entries = [desc for _, desc in changes]
    should_apply, final_entries = prompt_user(entries)

    if should_apply and final_entries:
        insert_today_section(changelog_path, final_entries)
        restage_file(changelog_path, repo_root)
        print(f"  ✓ CHANGELOG.md updated and re-staged.")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
