#!/usr/bin/env python3
"""
suggest_skill_version.py — interactively propose a changelog entry for staged SKILL.md changes.

Called from pre-commit when a SKILL.md is staged without a new changelog row.
  1. Analyses the diff to classify the change (major / minor / patch)
  2. Proposes a complete changelog row with today's date
  3. Prompts the user to accept, edit, or skip
  4. If accepted/edited: inserts the row into the file and re-stages it

Exits silently (code 0) when:
  - No SKILL.md files are staged with content changes
  - The staged diff already includes a new changelog row
  - stdin is not a TTY (non-interactive environments: CI, GUI clients)

Usage:
    python tools/validate/suggest_skill_version.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


# ── diff classification ────────────────────────────────────────────────────────

MAJOR_PATTERNS = [
    re.compile(r"^-## ", re.MULTILINE),                # removed any h2 section
    re.compile(r"^-\*\*Step \d+", re.MULTILINE),       # removed bold step header
    re.compile(r"^-### .*(required|mandatory)", re.MULTILINE | re.IGNORECASE),
]
MINOR_PATTERNS = [
    re.compile(r"^\+## ", re.MULTILINE),               # added any h2 section
    re.compile(r"^\+\*\*Step \d+", re.MULTILINE),      # added bold step header
    re.compile(r"^\+### ", re.MULTILINE),               # added a subsection
    re.compile(r"^\+.*Option [A-Z]\b", re.MULTILINE),  # added an option
]


def classify_diff(diff: str) -> str:
    """Return 'major', 'minor', or 'patch' based on diff content."""
    for pattern in MAJOR_PATTERNS:
        if pattern.search(diff):
            return "major"
    for pattern in MINOR_PATTERNS:
        if pattern.search(diff):
            return "minor"
    return "patch"


def bump_version(current: str, bump: str) -> str:
    """Return the next version string given a bump type."""
    parts = current.split(".")
    if len(parts) != 3:
        return "1.0.0"
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ── summary generation ─────────────────────────────────────────────────────────

def extract_summary(diff: str, bump: str) -> str:
    """Generate a one-line summary from the diff."""
    # Strip markdown markers from section names
    added_sections = [
        re.sub(r"^#+\s*", "", s).strip()
        for s in re.findall(r"^\+##+ (.+)", diff, re.MULTILINE)
    ]
    removed_sections = [
        re.sub(r"^#+\s*", "", s).strip()
        for s in re.findall(r"^-##+ (.+)", diff, re.MULTILINE)
    ]

    if bump == "major" and removed_sections:
        names = ", ".join(removed_sections[:2])
        return f"Remove {names}"
    if bump == "minor" and added_sections:
        names = ", ".join(added_sections[:2])
        return f"Add {names}"

    # Fall back: find the nearest section header to the first changed line
    context_header = None
    for line in diff.splitlines():
        if line.startswith(" ##") or line.startswith("+##") or line.startswith("-##"):
            context_header = re.sub(r"^[+\- ]+##+ *", "", line).strip()
        elif (line.startswith("+") or line.startswith("-")) \
                and not line.startswith("+++") and not line.startswith("---") \
                and line[1:].strip():
            if context_header:
                return f"Update {context_header}"
            break

    return "Update skill instructions"


# ── changelog helpers ─────────────────────────────────────────────────────────

CHANGELOG_HEADER = "## Changelog"
ROW_RE = re.compile(r"^\|\s*(\d+\.\d+\.\d+)\s*\|")


def get_current_version(text: str) -> str:
    """Return the most recent version from the ## Changelog table."""
    if CHANGELOG_HEADER not in text:
        return "1.0.0"
    body = text.split(CHANGELOG_HEADER, 1)[1]
    for line in body.splitlines():
        m = ROW_RE.match(line.strip())
        if m:
            return m.group(1)
    return "1.0.0"


def changelog_already_updated(diff: str) -> bool:
    """Return True if the staged diff already adds a changelog row."""
    for line in diff.splitlines():
        if line.startswith("+") and ROW_RE.match(line[1:].strip()):
            return True
    return False


def insert_changelog_row(text: str, row: str) -> str:
    """Insert a new row at the top of the ## Changelog table."""
    header_marker = "| Version | Date | Summary |"
    separator = "|---|---|---|"
    if header_marker in text and separator in text:
        insert_after = text.index(separator) + len(separator)
        return text[:insert_after] + "\n" + row + text[insert_after:]
    # Fallback: append at end of changelog section
    return text + "\n" + row + "\n"


# ── git helpers ───────────────────────────────────────────────────────────────

def get_staged_diff(skill_md: Path, repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "--cached", "--", str(skill_md.relative_to(repo_root))],
        capture_output=True, text=True, cwd=repo_root,
    )
    return result.stdout


def restage_file(skill_md: Path, repo_root: Path) -> None:
    subprocess.run(
        ["git", "add", str(skill_md.relative_to(repo_root))],
        cwd=repo_root, check=True,
    )


# ── interactive prompt ────────────────────────────────────────────────────────

def prompt_user(skill_name: str, bump: str, proposed_row: str) -> tuple[bool, str]:
    """
    Prompt the user to accept, edit, or skip.
    Returns (should_apply, final_row).
    """
    bump_label = bump.upper()
    print()
    print(f"  Skill changelog: {skill_name}")
    print(f"  Suggested bump:  {bump_label}")
    print(f"  Proposed entry:  {proposed_row}")
    print()
    print("  [A]ccept  [E]dit  [S]kip  ", end="", flush=True)

    try:
        choice = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False, proposed_row

    if choice in ("a", ""):
        return True, proposed_row

    if choice == "e":
        # Extract parts for guided editing
        parts = [p.strip() for p in proposed_row.strip("|").split("|")]
        version_part = parts[0] if len(parts) > 0 else ""
        date_part = parts[1] if len(parts) > 1 else str(date.today())
        summary_part = parts[2] if len(parts) > 2 else ""

        print(f"  Version [{version_part}]: ", end="", flush=True)
        try:
            v = input().strip() or version_part
            print(f"  Date    [{date_part}]: ", end="", flush=True)
            d = input().strip() or date_part
            print(f"  Summary [{summary_part}]: ", end="", flush=True)
            s = input().strip() or summary_part
        except (EOFError, KeyboardInterrupt):
            print()
            return False, proposed_row

        edited_row = f"| {v} | {d} | {s} |"
        return True, edited_row

    # skip
    return False, proposed_row


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest skill changelog entries interactively.")
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    args = parser.parse_args()

    # Non-interactive environments (CI, GUI git clients) — skip silently
    if not sys.stdin.isatty():
        return 0

    repo_root = Path(args.root).resolve()
    skills_dir = repo_root / "agents" / "claude"

    # Find staged SKILL.md files
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True, text=True, cwd=repo_root,
    )
    staged = result.stdout.splitlines()
    staged_skills = [
        repo_root / p for p in staged
        if p.startswith("agents/claude/") and p.endswith("/SKILL.md")
    ]

    if not staged_skills:
        return 0

    any_prompted = False
    for skill_md in staged_skills:
        diff = get_staged_diff(skill_md, repo_root)
        if not diff:
            continue

        # Already has a changelog row in this diff — nothing to do
        if changelog_already_updated(diff):
            continue

        # Count meaningful changed lines (ignore blank lines and changelog table)
        changed = [
            l for l in diff.splitlines()
            if (l.startswith("+") or l.startswith("-"))
            and not l.startswith("+++") and not l.startswith("---")
            and l[1:].strip()
            and "Changelog" not in l
            and not ROW_RE.match(l[1:].strip())
        ]
        if len(changed) < 3:
            # Trivial change — not worth prompting
            continue

        text = skill_md.read_text(encoding="utf-8")
        current_version = get_current_version(text)
        bump = classify_diff(diff)
        next_version = bump_version(current_version, bump)
        today = str(date.today())
        summary = extract_summary(diff, bump)
        proposed_row = f"| {next_version} | {today} | {summary} |"

        skill_name = skill_md.parent.name
        any_prompted = True

        should_apply, final_row = prompt_user(skill_name, bump, proposed_row)

        if should_apply:
            updated = insert_changelog_row(text, final_row)
            skill_md.write_text(updated, encoding="utf-8")
            restage_file(skill_md, repo_root)
            print(f"  ✓ Changelog updated and re-staged.")

    if any_prompted:
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
