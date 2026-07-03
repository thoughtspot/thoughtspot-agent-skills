#!/usr/bin/env python3
"""
check_slash_command_refs.py — fail if a `/ts-<skill>` slash-command mention in
skill docs points at a skill directory that doesn't exist.

2026-07-03 audit finding 1.1: `ts-object-model-builder` was recommended by name in
three shipped skills (model-coach, answer-promote, ai-asset-review-rules.md) for
weeks — a nonexistent skill that any user or executing agent following the doc would
hit a dead end on. `check_references.py` validates file links, not prose `/slash-command`
mentions, so nothing caught it. This validator closes that gap.

Scope: every `.md` file under `agents/` (SKILL.md and reference docs alike — the
phantom mention that prompted this validator was itself in a `references/*.md` file,
not just SKILL.md). Repo-root docs/, .claude/, and CHANGELOG.md are a different
surface (internal tooling docs, not user-facing skill instructions) and are out of
scope by construction — this validator never looks outside agents/.

Matching a genuine command mention vs. a file path or URL: a slash-command mention is
`/ts-<name>` where the `/` is NOT itself part of a longer path or URL — i.e. the
character immediately before the `/` is not a word character, `.`, another `/`, or `#`
(anchors). This lets `` `/ts-audit` `` (backtick before the slash) or "the /ts-audit
skill" (space before the slash) match, while `agents/cli/ts-audit/SKILL.md`,
`../ts-object-answer-promote/SKILL.md`, and `~/.claude/skills/ts-variable-timezone`
(all preceded by a word character or `.`) do not.

ALLOWLIST: skills that are legitimately referenced as future/planned work, not as an
already-shipped command. Each entry needs a justification.

Exit codes:
  0 — every non-allowlisted slash-command mention resolves to a real skill directory
  1 — at least one dangling mention found

Run manually:
    python3 tools/validate/check_slash_command_refs.py --root .
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Runtimes whose skill directories are valid resolution targets.
RUNTIMES = ("cli", "claude", "coco-snowsight")

# `/ts-foo-bar` not immediately preceded by a word char, `.`, `/`, or `#` — the
# character classes that show up in file paths, relative links, and markdown anchors.
SLASH_CMD_RE = re.compile(r'(?<![\w./#])/ts-[a-z0-9]+(?:-[a-z0-9]+)*')

# Skills named as planned/future work, not yet shipped. Each needs a justification —
# this list should stay short; a growing list is a sign docs are over-promising.
ALLOWLIST: dict[str, str] = {
    "ts-object-model-builder":
        "Planned — not yet shipped (audit finding 1.1). All instructional mentions "
        "were softened to 'planned, not shipped' after PR #168; the name still "
        "appears in changelog entries describing that fix and in skill-naming.md's "
        "family table.",
    "ts-object-connection-create":
        "Planned — ts-load-source-data's example CLI output hedges this pointer as "
        "'(when available)', not asserting it exists today.",
    "ts-recipe-parameter-sync":
        "Planned — ts-convert-from-tableau's example CLI output offers this as a "
        "forward-looking 'Consider ... for ongoing refresh' suggestion, not an "
        "instruction to run an existing command.",
}


def _get_tracked_paths(repo_root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "ls-files", "agents"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return set(result.stdout.splitlines())


def _known_skill_names(repo_root: Path, tracked: set[str]) -> set[str]:
    """A skill "exists" if agents/<runtime>/<name>/SKILL.md is tracked by git —
    matches the convention check_smoke_tests.py already uses (untracked/wip skill
    dirs aren't yet real from a doc-reference point of view either)."""
    names: set[str] = set()
    for runtime in RUNTIMES:
        runtime_dir = repo_root / "agents" / runtime
        if not runtime_dir.is_dir():
            continue
        for skill_dir in runtime_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            if f"agents/{runtime}/{skill_dir.name}/SKILL.md" in tracked:
                names.add(skill_dir.name)
    return names


def find_mentions(text: str) -> list[tuple[int, str]]:
    """Return (lineno, name) for every slash-command mention (name without the
    leading '/'), one per line the mention starts on."""
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in SLASH_CMD_RE.finditer(line):
            hits.append((lineno, m.group(0)[1:]))
    return hits


def iter_md_files(root: Path, tracked: set[str]) -> list[Path]:
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return []
    return sorted(
        p for p in agents_dir.rglob("*.md")
        if str(p.relative_to(root)) in tracked
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    all_tracked = set(
        subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=root)
        .stdout.splitlines()
    )
    known_skills = _known_skill_names(root, all_tracked)

    failures: list[str] = []
    scanned = 0
    for path in iter_md_files(root, all_tracked):
        rel = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        scanned += 1
        for lineno, name in find_mentions(text):
            if name in known_skills or name in ALLOWLIST:
                continue
            failures.append(
                f"  ✗ {rel}:{lineno}: /{name} does not resolve to any skill directory "
                f"under agents/{{{','.join(RUNTIMES)}}}"
            )

    if failures:
        print(f"\n{len(failures)} dangling slash-command reference(s) found:\n")
        print("\n".join(failures))
        print()
        print("Either the skill needs to be shipped, the reference needs correcting,")
        print("or — if it's a deliberate forward-looking pointer to planned work —")
        print("add it to ALLOWLIST in this file with a one-line justification.")
        return 1

    print(f"All slash-command references resolve in {scanned} doc(s) "
          f"({len(known_skills)} known skill(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
