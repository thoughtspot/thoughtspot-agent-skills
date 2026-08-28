#!/usr/bin/env python3
"""
check_smoke_tests.py — verify every Claude skill has a smoke test, and vice versa.

Forward direction: every directory under agents/cli/ or agents/claude/ that contains a
tracked SKILL.md must have a corresponding tools/smoke-tests/smoke_<skill_name>.py file
(also tracked), unless the skill is on the allowlist.

The skill name is normalised: hyphens → underscores. A few skills use an abbreviated
smoke filename — those are listed explicitly in NAME_ALIASES below.

Skills on the allowlist (interactive / setup / out-of-scope for live testing)
are skipped:
  - ts-profile-thoughtspot, ts-profile-snowflake — credential setup; no API
    mutations to verify automatically without test credentials
  - ts-object-answer-promote, ts-convert-from-tableau — dated backlog items
    (BL-076, filed 2026-07-03, target 2026-09-30 — audit finding 6.3: these two
    exemptions previously had no dated backlog reference, a two-bucket-rule
    violation). Remove from the allowlist when the smoke test lands.

Reverse direction: every tools/smoke-tests/smoke_*.py file must resolve back to either
an existing skill directory (by the naming convention above) or a NAME_ALIASES target.
A smoke file that resolves to neither is orphaned — it provides no real coverage and
tends to accumulate hardcoded instance/GUID assumptions that silently rot (audit 6.2:
smoke_ts-metadata-report.py mapped to no skill, hardcoded one dev instance + GUID, and
was never run by any harness).

Usage:
    python tools/validate/check_smoke_tests.py
    python tools/validate/check_smoke_tests.py --root /path/to/repo
    python tools/validate/check_smoke_tests.py --root . --staged
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

from _git import _GitOut, git_paths, tracked_relpaths

from _dirs import CLI_RUNTIMES, CLI_RUNTIME_PATHS

# Trailing-slash prefixes for str.startswith on repo-relative paths.
_CLI_SKILL_PREFIXES = tuple(f"{p}/" for p in CLI_RUNTIME_PATHS)


# Skills exempt from the smoke-test requirement.
# Add a comment for each entry explaining why; remove when the exemption no longer applies.
#
# Two-bucket rule (audit 6.3): a non-credential-setup exemption is a deferral, not a
# permanent pass — it MUST cite a dated backlog item (`BL-NNN`) in its trailing comment.
# Credential-setup skills (`ts-profile-*`) are exempt from that citation requirement — they
# have no API mutation flow to test, so there is nothing to defer to a backlog item.
# `check_allowlist_bl_references()` below enforces this by parsing this file's own source.
ALLOWLIST = {
    "ts-profile-thoughtspot",   # interactive credential setup — no API mutation flow to test
    "ts-profile-snowflake",     # interactive credential setup
    "ts-profile-databricks",    # interactive credential setup
    "ts-profile-tableau",       # interactive credential setup — no API mutation flow to test
    "ts-profile-domo",          # interactive credential setup — no API mutation flow to test
    "ts-object-answer-promote", # legacy gap; BL-076 (filed 2026-07-03, target 2026-09-30)
    "ts-convert-from-tableau",  # requires .twb fixture file; BL-076 (filed 2026-07-03, target 2026-09-30)
    "ts-convert-from-looker",   # community contribution PR #201; smoke test deferred — BL-115 (filed 2026-07-11)
    "ts-convert-from-sisense",  # requires a captured Sisense bundle fixture; smoke test deferred — wip skill, BL-118 (filed 2026-07-17)
    "ts-convert-from-powerbi",  # requires a .pbip project fixture (TMDL + PBIR); smoke test deferred — BL-076 (filed 2026-07-03, target 2026-09-30)
    "ts-convert-from-domo",     # offline-only converter; needs a captured Domo bundle fixture on a live cluster; smoke test deferred — BL-076 (filed 2026-07-03, target 2026-09-30)
}

# Skills whose smoke test uses an abbreviated filename rather than the default convention.
# Add an entry here when the smoke test name is shortened from the skill name.
NAME_ALIASES = {
    "ts-convert-to-snowflake-sv":    "tools/smoke-tests/smoke_ts_to_snowflake.py",
    "ts-convert-from-snowflake-sv":  "tools/smoke-tests/smoke_ts_from_snowflake.py",
    # Points at the hyphenated file deliberately: it invokes the shipped
    # `ts databricks build-mv`, whereas smoke_ts_to_databricks.py re-implements
    # its own MV YAML builder and asserted against a string it had just built
    # (audit 6.1/6.2 — the emitter had zero smoke coverage while the harness
    # reported PASS).
    "ts-convert-to-databricks-mv":   "tools/smoke-tests/smoke_ts-convert-to-databricks-mv.py",
    "ts-convert-from-databricks-mv": "tools/smoke-tests/smoke_ts_from_databricks.py",
}


# Smoke files that legitimately accompany a skill's PRIMARY (aliased) smoke test
# rather than replacing it, mapped to the skill they support plus a justification.
# Excluded from the orphan and double-claim checks.
#
# Why this exists: `ts-convert-to-databricks-mv` genuinely needs two, because they
# cover disjoint paths. The aliased file is offline (local fixture -> build-mv ->
# assert shape) so pre-push can run it with no credentials; the companion is a live
# end-to-end (ThoughtSpot auth -> export real model TML -> build-mv -> execute in
# Databricks -> verify -> cleanup) and needs both platforms. Collapsing them would
# lose one path or make the credential-free gate uncredentialable.
#
# Keep this list SHORT. A companion must cover a path the aliased file cannot, not
# merely add assertions — two files covering the same path is the audit-6.1 bug.
COMPANION_SMOKE_TESTS = {
    "tools/smoke-tests/smoke_ts_to_databricks.py": (
        "ts-convert-to-databricks-mv",
        "live end-to-end (TS export -> build-mv -> execute in Databricks); the "
        "aliased file covers the same emitter offline against a fixture",
    ),
}


_BL_REF_RE = re.compile(r"BL-\d+")


def _find_allowlist_entries(source_text: str) -> list[tuple[str, int, str]]:
    """Parse ALLOWLIST out of this validator's own source and return, in source order,
    (skill_name, line_no, trailing_comment) for every entry.

    ALLOWLIST is a runtime `set` literal — by the time this module is imported, the
    trailing `# ...` justification comments are gone. Enforcing the BL-reference rule
    (audit 6.3) means re-reading the source text and pairing each element with the
    comment on its own line. Uses `ast` to find the `ALLOWLIST = {...}` assignment and
    the exact source line each string literal lives on (robust to reordering or
    reformatting of the block), then a line-scoped regex to pull the trailing comment
    off that specific line.
    """
    tree = ast.parse(source_text)
    lines = source_text.splitlines()
    entries: list[tuple[str, int, str]] = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "ALLOWLIST"):
            continue
        if not isinstance(node.value, ast.Set):
            continue  # ALLOWLIST is expected to be a set literal of skill-name strings

        for elt in node.value.elts:
            if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
                continue
            line_no = elt.lineno
            line_text = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
            comment = line_text.split("#", 1)[1].strip() if "#" in line_text else ""
            entries.append((elt.value, line_no, comment))

    return entries


def check_allowlist_bl_references(source_text: str) -> tuple[list[str], list[str]]:
    """Return (failures, info) for the ALLOWLIST BL-NNN citation rule (audit 6.3).

    Two-bucket rule: every non-credential-setup ALLOWLIST entry is a deferral, not a
    permanent pass, so it must cite a dated backlog item (`BL-\\d+`) in its trailing
    comment. Credential-setup entries are exempt from the citation requirement — they
    are classified by the `ts-profile-` prefix (not a hardcoded name list), so a future
    `ts-profile-bigquery` or similar is automatically covered without editing this check.
    """
    failures: list[str] = []
    info: list[str] = []

    for skill_name, line_no, comment in _find_allowlist_entries(source_text):
        if skill_name.startswith("ts-profile-"):
            # Credential-setup skills have no API mutation flow to test — nothing to
            # defer to a backlog item, so no BL-NNN citation is required.
            info.append(f"  PASS  {skill_name}  (line {line_no})  →  credential-setup exemption")
            continue

        if _BL_REF_RE.search(comment):
            info.append(f"  PASS  {skill_name}  (line {line_no})  →  cites {_BL_REF_RE.search(comment).group()}")
        else:
            failures.append(
                f"FAIL  ALLOWLIST entry {skill_name!r} (line {line_no}) has no dated "
                f"backlog reference in its trailing comment. Non-credential-setup "
                f"exemptions must cite a dated BL-NNN backlog item (audit 6.3 "
                f"two-bucket rule) — e.g. '# deferred — BL-123 (filed YYYY-MM-DD)'."
            )

    return failures, info


def _get_tracked_paths(repo_root: Path) -> set[str]:
    """Return set of repo-relative paths currently tracked by git."""
    return set(tracked_relpaths(repo_root))


def _get_staged_names(repo_root: Path) -> list[str]:
    result = _GitOut("\n".join(git_paths(["diff", "--cached", "--name-only", "--diff-filter=ACM"], repo_root)))
    return result.stdout.splitlines()


def _staged_touches_skills_or_smoke(staged: list[str]) -> bool:
    """Return True if staged files include anything that would change a skill or smoke test."""
    for f in staged:
        if f.startswith(_CLI_SKILL_PREFIXES) or f.startswith("tools/smoke-tests/"):
            return True
    return False


def _candidate_smoke_paths(skill_name: str) -> list[str]:
    """
    Return the candidate smoke-test filenames for a skill.

    1. If the skill is in NAME_ALIASES, that exact path is the only candidate
    2. Otherwise the default convention: `tools/smoke-tests/smoke_<skill>.py`
       (with hyphens converted to underscores)
    """
    if skill_name in NAME_ALIASES:
        return [NAME_ALIASES[skill_name]]
    base = skill_name.replace("-", "_")
    return [f"tools/smoke-tests/smoke_{base}.py"]


def _find_double_claimed_skills(repo_root: Path, tracked: set[str]) -> list[str]:
    """Fail when TWO tracked smoke files resolve to one skill.

    The failure this exists for (audit 6.1/6.2): `ts-convert-to-databricks-mv` had
    both `smoke_ts-convert-to-databricks-mv.py` (calls the shipped
    `ts databricks build-mv`) and `smoke_ts_to_databricks.py` (re-implements its own
    MV YAML builder, then asserted `"WITH METRICS LANGUAGE YAML" in ddl` against the
    string it had just built — an assertion that cannot fail). NAME_ALIASES routed the
    harness to the weaker one, so the real emitter had ZERO coverage while the gate
    reported PASS, and the stronger file was unreachable.

    Neither existing rule caught it. The per-skill loop is satisfied by any one file,
    and `_find_orphan_smoke_tests` only flags a file resolving to NO tracked skill —
    both of these resolve to a real skill, so both passed.

    Resolution is the author's call, not this validator's: delete the weaker file, or
    fold its coverage into the aliased one. Two files is always a bug, because only one
    can ever run.
    """
    smoke_dir = repo_root / "tools" / "smoke-tests"
    if not smoke_dir.is_dir():
        return []

    known_skills: set[str] = set()
    for runtime in CLI_RUNTIMES:
        runtime_dir = repo_root / "agents" / runtime
        if runtime_dir.is_dir():
            known_skills |= {d.name for d in runtime_dir.iterdir() if d.is_dir()}

    # skill -> [smoke files claiming it]
    claims: dict[str, list[str]] = {}
    for f in sorted(smoke_dir.glob("smoke_*.py")):
        rel = str(f.relative_to(repo_root))
        if rel not in tracked or rel in COMPANION_SMOKE_TESTS:
            continue
        stem = f.stem[len("smoke_"):]
        # A file claims a skill either by being its NAME_ALIASES target, or by the
        # smoke_<skill>.py convention (underscores standing in for hyphens).
        for skill in known_skills:
            if NAME_ALIASES.get(skill) == rel or stem in (skill, skill.replace("-", "_")):
                claims.setdefault(skill, []).append(rel)

    out = []
    for skill, files in sorted(claims.items()):
        if len(files) > 1:
            aliased = NAME_ALIASES.get(skill)
            detail = f" (NAME_ALIASES runs {aliased}; the other never executes)" if aliased else ""
            out.append(
                f"{skill}: {len(files)} smoke files claim this skill{detail}\n"
                + "".join(f"      - {f}\n" for f in files)
                + "      Only one can run. Delete the redundant file or merge its\n"
                  "      coverage into the aliased one (audit 6.1/6.2)."
            )
    return out


def _find_orphan_smoke_tests(repo_root: Path, tracked: set[str]) -> list[str]:
    """Return failure messages for tracked smoke_*.py files that resolve to no skill.

    The reverse of the main per-skill loop below: instead of asking "does this skill
    have a smoke test", ask "does this smoke test belong to a skill". A file that is
    neither a NAME_ALIASES target nor named after a tracked skill directory (by the
    smoke_<skill_with_underscores>.py convention) is orphaned.
    """
    smoke_dir = repo_root / "tools" / "smoke-tests"
    if not smoke_dir.is_dir():
        return []

    alias_targets = set(NAME_ALIASES.values()) | set(COMPANION_SMOKE_TESTS)

    known_skills: set[str] = set()
    for runtime in CLI_RUNTIMES:
        runtime_dir = repo_root / "agents" / runtime
        if not runtime_dir.is_dir():
            continue
        for skill_dir in runtime_dir.iterdir():
            if skill_dir.is_dir() and f"agents/{runtime}/{skill_dir.name}/SKILL.md" in tracked:
                known_skills.add(skill_dir.name)

    orphans: list[str] = []
    for py_file in sorted(smoke_dir.glob("smoke_*.py")):
        rel = f"tools/smoke-tests/{py_file.name}"
        if rel not in tracked:
            continue  # untracked local scratch file — not our concern
        if rel in alias_targets:
            continue

        candidate_skill = py_file.stem[len("smoke_"):].replace("_", "-")
        if candidate_skill in known_skills:
            continue

        orphans.append(
            f"FAIL  {rel}  →  resolves to no tracked skill "
            f"(expected a skill named {candidate_skill!r}) and is not a "
            f"NAME_ALIASES target. Delete it, fold its assertions into an "
            f"existing skill's smoke test, or add a NAME_ALIASES entry."
        )

    return orphans


def _find_undocumented_smoke_tests(repo_root: Path, tracked: set[str]) -> list[str]:
    """Every tracked smoke suite must appear in tools/smoke-tests/README.md.

    Five tracked files were missing from that table (2026-08-26 audit, finding 6.7),
    which made them invisible to anyone auditing coverage from the docs — and nothing
    checked it: `check_consistency` covers the README/SETUP *skill* tables, not this
    one. A file-not-in-table check is cheap and closes the drift for good.
    """
    readme = repo_root / "tools" / "smoke-tests" / "README.md"
    if not readme.is_file():
        return []
    text = readme.read_text(encoding="utf-8")
    missing = []
    for rel in sorted(tracked):
        if not rel.startswith("tools/smoke-tests/smoke_") or not rel.endswith(".py"):
            continue
        name = Path(rel).name
        if name not in text:
            missing.append(
                f"FAIL  {name}  →  tracked but absent from tools/smoke-tests/README.md.  "
                f"Add a row (with its tier: Pure / CLI-only / Live) so coverage is "
                f"visible from the docs."
            )
    return missing


def check(repo_root: Path, staged_only: bool = False) -> tuple[list[str], list[str]]:
    """Return (failures, info_messages)."""
    failures: list[str] = []
    info: list[str] = []

    if staged_only:
        staged = _get_staged_names(repo_root)
        if not _staged_touches_skills_or_smoke(staged):
            return failures, info  # no relevant changes; skip

    tracked = _get_tracked_paths(repo_root)

    # Canonical CLI skills live in agents/cli/; agents/claude/ holds Claude-only skills.
    for runtime in CLI_RUNTIMES:
        runtime_dir = repo_root / "agents" / runtime
        if not runtime_dir.is_dir():
            continue

        for skill_dir in sorted(runtime_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_name = skill_dir.name
            skill_md_rel = f"agents/{runtime}/{skill_name}/SKILL.md"
            if skill_md_rel not in tracked:
                continue  # untracked / wip skill; not yet enforced

            if skill_name in ALLOWLIST:
                info.append(f"  SKIP  {skill_name}  (on allowlist)")
                continue

            candidates = _candidate_smoke_paths(skill_name)
            if any(c in tracked for c in candidates):
                matched = next(c for c in candidates if c in tracked)
                info.append(f"  PASS  {skill_name}  →  {matched}")
            else:
                failures.append(
                    f"FAIL  {skill_name}  →  no smoke test found.  "
                    f"Expected one of: {', '.join(candidates)}"
                )

    failures.extend(_find_orphan_smoke_tests(repo_root, tracked))
    failures.extend(_find_double_claimed_skills(repo_root, tracked))
    failures.extend(_find_undocumented_smoke_tests(repo_root, tracked))

    return failures, info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repo root (default: cwd)")
    parser.add_argument("--staged", action="store_true",
                        help="Only run if staged changes touch skills or smoke tests")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    failures, info = check(repo_root, staged_only=args.staged)

    # ALLOWLIST BL-reference gate (audit 6.3). This parses the validator's OWN source
    # (comments are stripped from the ALLOWLIST set at import time), so it runs
    # unconditionally — it is a self-contained integrity check on this file, not tied
    # to whichever other files happen to be staged in this commit.
    self_source = Path(__file__).resolve().read_text(encoding="utf-8")
    bl_failures, bl_info = check_allowlist_bl_references(self_source)
    failures = failures + bl_failures
    info = info + bl_info

    for msg in info:
        print(msg)

    if failures:
        print()
        for f in failures:
            print(f)
        print()
        print(f"{len(failures)} problem(s): skills missing a smoke test, smoke tests "
              f"resolving to no skill (orphaned), and/or ALLOWLIST entries missing a "
              f"dated BL-NNN backlog reference.")
        print()
        print("To fix:")
        print("  1. Create tools/smoke-tests/smoke_<skill_name>.py")
        print("  2. Use tools/smoke-tests/_common.py for shared auth + cleanup helpers")
        print("  3. Mirror an existing smoke test (e.g. smoke_ts_dependency_manager.py)")
        print()
        print("If the skill genuinely cannot be smoke-tested (interactive setup, etc.),")
        print("add it to ALLOWLIST in this file with a justification comment. Non-")
        print("credential-setup exemptions must also cite a dated BL-NNN backlog item.")
        return 1

    print()
    print("All skills have smoke tests (or are on the allowlist), and all "
          "non-credential-setup ALLOWLIST entries cite a dated BL-NNN reference.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
