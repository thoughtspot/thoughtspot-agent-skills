#!/usr/bin/env python3
"""
check_patterns.py — detect known anti-patterns in .md and .py files.

Run after any rule or code change to catch regressions before committing.

Patterns detected:
  1. fqn: adjacent to connection: in TML examples (should be name: only)
  2. aggregation: inside formulas[] blocks (belongs in columns[] only)
  3. connection_fqn in Python files (should be connection_name)
  4. %% in Python help strings (should be % — Typer doubles %)

Usage:
    python tools/validate/check_patterns.py
    python tools/validate/check_patterns.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple


class Pattern(NamedTuple):
    name: str
    regex: re.Pattern
    glob: str          # file glob to search
    message: str       # human-readable description of what's wrong


PATTERNS: list[Pattern] = [
    Pattern(
        name="connection-fqn-in-tml",
        # Looks for fqn: appearing within a few lines after connection:
        # We check line-by-line and track context
        regex=re.compile(r'^\s+fqn:\s+'),
        glob="**/*.md",
        message="fqn: found — connection blocks in table TML must use name: only, not fqn:",
    ),
    Pattern(
        name="aggregation-in-formulas",
        regex=re.compile(r'^\s+aggregation:\s+'),
        glob="**/*.md",
        message="aggregation: found — this field belongs in columns[] entries, never in formulas[] entries",
    ),
    Pattern(
        name="connection-fqn-in-python",
        regex=re.compile(r'connection_fqn'),
        glob="**/*.py",
        message="connection_fqn found — use connection_name (string display name, not GUID)",
    ),
    Pattern(
        name="double-percent-in-help",
        regex=re.compile(r'help\s*=\s*["\'].*%%'),
        glob="**/*.py",
        message="%% in help string — use % (Typer escapes % automatically; %% shows literally as %% to users)",
    ),
]


def check_connection_fqn_in_tml(file_path: Path) -> list[tuple[int, str]]:
    """
    More precise check: flag fqn: that appears directly inside a connection: block.
    A connection: block looks like:
      connection:
        fqn: ...      ← bad
        name: ...     ← good
    We track when we enter a connection: context and flag fqn: within it.
    """
    hits = []
    content = file_path.read_text(encoding="utf-8")
    in_code_block = False
    in_connection_block = False
    connection_indent = -1

    for line_num, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()

        # Track fenced code blocks (``` ... ```)
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            in_connection_block = False
            continue

        if not in_code_block:
            continue  # only check inside code blocks where TML appears

        # Detect connection: key
        m_conn = re.match(r'^(\s*)connection:\s*$', line)
        if m_conn:
            in_connection_block = True
            connection_indent = len(m_conn.group(1))
            continue

        if in_connection_block:
            if not line.strip():
                continue
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= connection_indent:
                # Exited connection block
                in_connection_block = False
            elif re.match(r'^\s+fqn:\s+', line):
                hits.append((line_num, line.strip()))

    return hits


def get_staged_files(repo_root: Path, suffix: str, skip_dirs: set | None = None) -> list[Path]:
    """Return staged files with the given suffix, excluding skip_dirs."""
    import subprocess
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=repo_root
    )
    paths = [repo_root / f for f in result.stdout.splitlines()
             if f.endswith(suffix) and (repo_root / f).exists()]
    if skip_dirs:
        paths = [p for p in paths if not any(part in p.parts for part in skip_dirs)]
    return paths


def get_staged_added_lines(repo_root: Path, file_path: Path) -> set[str]:
    """
    Return the set of lines that are NEW (added) in the staged diff for file_path.
    Lines from the git diff that start with '+' (excluding the '+++' header).
    Used to distinguish pre-existing violations from newly introduced ones.
    """
    import subprocess
    result = subprocess.run(
        ["git", "diff", "--cached", "-U0", "--", str(file_path)],
        capture_output=True, text=True, cwd=repo_root,
    )
    added = set()
    for line in result.stdout.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.add(line[1:])  # strip the leading '+'
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect known anti-patterns.")
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    parser.add_argument("--staged", action="store_true",
                        help="Only check files staged in git (for use in pre-commit hook)")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()

    # Directories to skip (tools/validate excluded — it legitimately references bad patterns)
    skip_dirs = {".git", "__pycache__", ".venv", "venv", "dist", "build", "validate"}

    # When --staged, only scan staged files; otherwise scan the full repo
    if args.staged:
        all_md_files = get_staged_files(repo_root, ".md", skip_dirs)
        all_py_files = get_staged_files(repo_root, ".py", skip_dirs)
        # Checks 1 & 2 only make sense for md files; checks 3–5 are scoped separately
        md_files_for_tml = all_md_files
        py_files = all_py_files
        skill_md_files = [f for f in all_md_files
                          if "agents/claude" in str(f) and f.name == "SKILL.md"]
    else:
        md_files_for_tml = sorted(
            f for f in repo_root.glob("**/*.md")
            if not any(p in f.parts for p in skip_dirs)
        )
        py_files = sorted(
            f for f in repo_root.glob("**/*.py")
            if not any(p in f.parts for p in skip_dirs)
        )
        # Only check SKILL.md files that are tracked by git (skip gitignored pending skills)
        import subprocess as _sp
        _tracked = set(
            _sp.run(["git", "ls-files", "agents/claude"],
                    capture_output=True, text=True, cwd=repo_root).stdout.splitlines()
        )
        skill_md_files = sorted(
            f for f in repo_root.glob("agents/claude/*/SKILL.md")
            if str(f.relative_to(repo_root)) in _tracked
        )

    total_hits = 0

    # Check 1: connection fqn in TML (context-aware)
    for md_file in md_files_for_tml:
        if any(p in md_file.parts for p in skip_dirs):
            continue
        hits = check_connection_fqn_in_tml(md_file)
        for line_num, text in hits:
            rel = md_file.relative_to(repo_root)
            print(f"FAIL  {rel}:{line_num}  connection-fqn-in-tml  →  {text!r}")
            total_hits += 1

    # Check 2: aggregation in formulas (heuristic — flag for review)
    # We look for aggregation: inside a formulas: yaml block
    for md_file in md_files_for_tml:
        if any(p in md_file.parts for p in skip_dirs):
            continue
        content = md_file.read_text(encoding="utf-8")
        in_code_block = False
        in_formulas_block = False
        formulas_indent = -1

        for line_num, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                in_formulas_block = False
                continue
            if not in_code_block:
                continue

            m_form = re.match(r'^(\s*)formulas:\s*$', line)
            if m_form:
                in_formulas_block = True
                formulas_indent = len(m_form.group(1))
                continue

            if in_formulas_block:
                if not stripped:
                    continue
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= formulas_indent and stripped and not stripped.startswith("-"):
                    in_formulas_block = False
                elif re.match(r'^\s+aggregation:\s+', line):
                    rel = md_file.relative_to(repo_root)
                    print(f"FAIL  {rel}:{line_num}  aggregation-in-formulas  →  {stripped!r}")
                    total_hits += 1

    # Check 3: connection_fqn in Python
    for py_file in py_files:
        for line_num, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
            if "connection_fqn" in line:
                rel = py_file.relative_to(repo_root)
                print(f"FAIL  {rel}:{line_num}  connection-fqn-in-python  →  {line.strip()!r}")
                total_hits += 1

    # Check 4: %% in Python help strings
    help_re = re.compile(r'help\s*=\s*["\'].*%%')
    for py_file in py_files:
        for line_num, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
            if help_re.search(line):
                rel = py_file.relative_to(repo_root)
                print(f"FAIL  {rel}:{line_num}  double-percent-in-help  →  {line.strip()!r}")
                total_hits += 1

    # Check 5: direct requests calls in Claude SKILL.md files (should use ts CLI instead)
    # Legitimate exceptions: references/ subdirs (open-items test scripts) and agents/coco/ (no CLI available)
    # In --staged mode: only flag lines that are NEW in this commit (not pre-existing violations)
    requests_re = re.compile(r'\brequests\.(get|post|put|delete|patch|Session)\b')
    for md_file in skill_md_files:
        # When staged, only flag newly-added lines to avoid blocking commits that
        # touch files with pre-existing violations unrelated to this change
        added_lines = (
            get_staged_added_lines(repo_root, md_file) if args.staged else None
        )
        for line_num, line in enumerate(md_file.read_text(encoding="utf-8").splitlines(), 1):
            if requests_re.search(line):
                if added_lines is not None and line not in added_lines:
                    continue  # pre-existing violation — skip in staged mode
                rel = md_file.relative_to(repo_root)
                print(
                    f"FAIL  {rel}:{line_num}  direct-api-call-in-skill  →  {line.strip()!r}\n"
                    f"      Claude skills must use `ts` CLI commands, not direct requests calls.\n"
                    f"      Move test scripts to references/open-items.md; add a ts-cli command for production use."
                )
                total_hits += 1

    print()
    if total_hits:
        print(f"{total_hits} anti-pattern(s) found.")
        return 1
    else:
        print("No anti-patterns found.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
