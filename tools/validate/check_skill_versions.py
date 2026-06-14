#!/usr/bin/env python3
"""
check_skill_versions.py — verify every skill file across all runtimes has a
## Changelog section with at least one valid semver entry.

Covers:
  agents/cli/*/SKILL.md             — Canonical CLI skills (Claude Code + Cortex Code CLI)
  agents/claude/*/SKILL.md          — Claude Code-only skills
  agents/coco-snowsight/*/SKILL.md  — Snowflake Cortex (CoCo) skills

Every file must have:
  ## Changelog
  | Version | Date | Summary |
  |---|---|---|
  | X.Y.Z | YYYY-MM-DD | ... |

Usage:
    python tools/validate/check_skill_versions.py
    python tools/validate/check_skill_versions.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROW_RE = re.compile(
    r"^\|\s*(\d+\.\d+\.\d+)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|.+\|"
)

# Top semver from a "## Changelog" table (first matching row wins).
_TOP_VER_RE = re.compile(r"^\|\s*(\d+\.\d+\.\d+)\s*\|")


def _git_show(repo_root: Path, ref: str) -> str | None:
    """Return file contents at a git ref (e.g. ':path' staged, 'HEAD:path'). None if absent."""
    result = subprocess.run(
        ["git", "show", ref], capture_output=True, text=True, cwd=repo_root,
    )
    return result.stdout if result.returncode == 0 else None


def _staged_skill_files(repo_root: Path) -> list[str]:
    """Repo-relative paths of staged SKILL.md skill files (added/modified)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=repo_root,
    )
    out = []
    for f in result.stdout.splitlines():
        if f.endswith("/SKILL.md") and f.startswith(
            ("agents/cli/", "agents/claude/", "agents/coco-snowsight/")
        ):
            out.append(f)
    return out


def _body_and_top_version(text: str) -> tuple[str, str | None]:
    """Split a skill file into (body-before-## Changelog, top changelog version)."""
    parts = text.split("## Changelog", 1)
    body = parts[0]
    version = None
    if len(parts) == 2:
        for line in parts[1].splitlines():
            m = _TOP_VER_RE.match(line.strip())
            if m:
                version = m.group(1)
                break
    return body, version


def check_staged_bump(repo_root: Path) -> list[str]:
    """For each staged SKILL.md whose BODY differs from HEAD, require the top changelog
    version to differ from HEAD's. Changelog-only edits and brand-new files pass.
    Returns a list of FAIL message strings (empty = ok)."""
    errors: list[str] = []
    for rel in _staged_skill_files(repo_root):
        head_text = _git_show(repo_root, f"HEAD:{rel}")
        if head_text is None:
            continue  # newly added file — nothing to compare against
        staged_text = _git_show(repo_root, f":{rel}")
        if staged_text is None:
            continue
        head_body, head_ver = _body_and_top_version(head_text)
        staged_body, staged_ver = _body_and_top_version(staged_text)
        if head_body == staged_body:
            continue  # body unchanged (changelog-only edit) — no bump required
        if staged_ver is not None and staged_ver == head_ver:
            errors.append(
                f"FAIL {rel}: body changed but top changelog row still "
                f"v{staged_ver} — add a new row"
            )
    return errors


def check_skill(skill_file: Path) -> list[str]:
    """Return a list of error strings for this file, or [] if valid."""
    text = skill_file.read_text(encoding="utf-8")
    errors: list[str] = []

    if "## Changelog" not in text:
        errors.append("missing ## Changelog section")
        return errors

    changelog_body = text.split("## Changelog", 1)[1]
    rows = [line for line in changelog_body.splitlines() if ROW_RE.match(line.strip())]
    if not rows:
        errors.append("## Changelog has no valid version rows (expected | X.Y.Z | YYYY-MM-DD | ... |)")

    return errors


def get_tracked_files(repo_root: Path, path: str) -> set[str]:
    """Return git-tracked file paths under the given path (relative to repo root)."""
    result = subprocess.run(
        ["git", "ls-files", path],
        capture_output=True, text=True, cwd=repo_root,
    )
    return set(result.stdout.splitlines())


def collect_skill_files(repo_root: Path) -> list[Path]:
    """Return all tracked skill files across all runtimes."""
    files: list[Path] = []

    # Canonical CLI skills: agents/cli/*/SKILL.md
    tracked_cli = get_tracked_files(repo_root, "agents/cli")
    files += sorted(
        f for f in (repo_root / "agents" / "cli").glob("*/SKILL.md")
        if str(f.relative_to(repo_root)) in tracked_cli
    )

    # Claude Code-only skills: agents/claude/*/SKILL.md
    tracked_claude = get_tracked_files(repo_root, "agents/claude")
    files += sorted(
        f for f in (repo_root / "agents" / "claude").glob("*/SKILL.md")
        if str(f.relative_to(repo_root)) in tracked_claude
    )

    # CoCo skills: agents/coco-snowsight/*/SKILL.md
    tracked_coco = get_tracked_files(repo_root, "agents/coco-snowsight")
    files += sorted(
        f for f in (repo_root / "agents" / "coco-snowsight").glob("*/SKILL.md")
        if str(f.relative_to(repo_root)) in tracked_coco
    )

    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check all skill files across all runtimes have a changelog."
    )
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    parser.add_argument(
        "--staged", action="store_true",
        help="Compare staged SKILL.md bodies against HEAD; require a version bump when "
             "the body changed (in addition to the changelog-presence check).",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()

    if args.staged:
        bump_errors = check_staged_bump(repo_root)
        if bump_errors:
            for err in bump_errors:
                print(err)
            print()
            print(f"{len(bump_errors)} staged skill(s) changed without a version bump.")
            return 1
        # Fall through to the changelog-presence check on the full set so a staged
        # commit still validates every skill has a valid changelog.

    skill_files = collect_skill_files(repo_root)

    if not skill_files:
        print("ERROR: no tracked skill files found — is --root pointing to the repo root?")
        return 1

    failed = 0
    current_runtime = None

    for skill_file in skill_files:
        rel = skill_file.relative_to(repo_root)
        # Print a header when runtime changes
        runtime = rel.parts[1]  # agents/<runtime>/...
        if runtime != current_runtime:
            current_runtime = runtime
            print(f"\n  [{runtime}]")

        errors = check_skill(skill_file)
        if errors:
            for err in errors:
                print(f"  FAIL  {rel}: {err}")
            failed += 1
        else:
            text = skill_file.read_text(encoding="utf-8")
            changelog_body = text.split("## Changelog", 1)[1]
            rows = [l.strip() for l in changelog_body.splitlines() if ROW_RE.match(l.strip())]
            version = rows[0].split("|")[1].strip() if rows else "?"
            print(f"  PASS  {rel}: v{version}")

    print()
    if failed:
        print(f"{failed} skill file(s) missing a valid changelog.")
        print("Add a ## Changelog section with at least one row: | X.Y.Z | YYYY-MM-DD | summary |")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
