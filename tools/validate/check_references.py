#!/usr/bin/env python3
"""
check_references.py — verify all file paths referenced in SKILL.md, references/*.md,
and docs/**/*.md files exist.

Scans:
  - every SKILL.md in agents/cli/, agents/claude/, and agents/coco-snowsight/
  - every references/*.md under those same three skill runtimes
  - every docs/**/*.md file, excluding docs/audit/, docs/superpowers/, and any
    *backlog-archive* path (historical / generated content, not maintained links)

for markdown links [text](path) and maps runtime-specific path prefixes back to
repo paths before checking existence.

ALSO scans backtick-quoted repo-relative paths — `docs/backlog.md`,
`tools/validate/check_x.py` — because the markdown-link check alone was blind to
the citation style this repo actually uses for code and doc paths. That hole let
22 dead `docs/reviews/...` citations pass green on one branch while every gate
reported PASS (2026-09-08). A backtick token is treated as a repo path only when
it is unambiguous: first segment is a git-tracked top-level directory, last
segment has a file extension, no whitespace / glob / placeholder characters. See
"Backtick path resolution" below.

Path mappings (SKILL.md only — see "Per-file-class link resolution" below):
  Claude / CLI skills  (~/.claude/...):
    ~/.claude/shared/         → agents/shared/
    ~/.claude/mappings/       → agents/shared/mappings/
    ~/.claude/skills/         → agents/cli/ (or agents/claude/ for Claude-only skills)

  CoCo skills (relative ../../shared/...):
    ../../shared/             → agents/shared/   (from skill dir two levels deep)

Per-file-class link resolution:
  SKILL.md files keep the exact behaviour above (prefix maps first, else resolve
  relative to the SKILL.md's own directory) — unchanged from before this file's
  scope was extended.

  references/*.md files sit ONE level deeper than SKILL.md (agents/<runtime>/<skill>/
  references/foo.md vs agents/<runtime>/<skill>/SKILL.md), so the SKILL.md prefix
  maps — which are depth-sensitive shorthand written for SKILL.md's specific
  location (e.g. CoCo's "../../shared/" assumes exactly two levels up from the
  skill dir) — would misresolve a relative link from this deeper location. These
  files instead resolve plain relative links against their own directory (which is
  depth-correct by construction via Path.resolve()), while still honouring the
  ~/.claude/... prefixes (CLAUDE_PREFIX_MAP) since those are absolute-style
  shorthand that map straight to a repo path regardless of the caller's depth.

  docs/**/*.md files live outside agents/<runtime>/<skill>/ entirely, so none of
  the skill prefix maps apply. These resolve plain relative links against the
  docs file's own directory, same as references/*.md.

Usage:
    python tools/validate/check_references.py
    python tools/validate/check_references.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from _git import git_paths, tracked_relpaths

from _dirs import runtime_globs

LINK_PATTERN = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')

# ── Backtick path resolution ─────────────────────────────────────────────────
# A backtick token is a candidate repo path only if ALL of these hold:
#   - no whitespace inside the backticks (so `grep -o 'x' */y.sql` never matches)
#   - no glob / placeholder / shell metacharacters
#   - contains a "/" and its last segment has a "." (an extension)
#   - its FIRST segment is a git-tracked top-level directory of this repo
# The last condition is what keeps the check conservative: `ts_cli/commands/x.py`
# (a module path written relative to tools/ts-cli/) is skipped rather than
# guessed at, and so is any prose token that happens to contain a slash.
BACKTICK_PATTERN = re.compile(r'`([^`\s]+)`')

# Trailing locators that are part of the CITATION, not the path:
#   file.py:67          file.py:67,130         file.md:45,68-70
#   file.py::symbol     tests/t.py::TestClass
_LOCATOR_SUFFIX = re.compile(r'(?:::[A-Za-z_][\w.]*|:\d+(?:[,-]\d+)*)$')

_FENCE = re.compile(r'^\s*(```|~~~)')

# Backtick paths that legitimately do not resolve. Each entry needs a reason.
# Reviewed 2026-09-08. Categories, and why each is not rot:
#
#   (a) EXTERNAL REPO — the path is correct, in another repository named in the
#       surrounding prose. Rewriting these would corrupt correct documentation.
#   (b) FORWARD REFERENCE — a file the item proposes to CREATE, marked "new" /
#       "Produce" / "Write" at the citation site. A backlog that may not name an
#       unwritten deliverable cannot describe its own work.
#   (c) COMPLETED DELETION — the item's whole purpose was to remove the file, and
#       it is DONE. The citation is the historical record of what was retired.
#
# Not a category: a path that simply moved. Those are rot — fix the citation.
KNOWN_MISSING_BACKTICK_PATHS: dict[str, str] = {
    # (a) external repo — `djwaldo/spotql-testing` `main`, named on the same line
    # of docs/backlog.md as the reference-docs list these five belong to.
    "docs/spotql-backing-comparison.md": "external repo: djwaldo/spotql-testing",
    "docs/spotql-snowflake-sv-findings.md": "external repo: djwaldo/spotql-testing",
    "docs/spotql-sv-backing-rules-PLAN.md": "external repo: djwaldo/spotql-testing",
    "docs/search-data-probe-findings.md": "external repo: djwaldo/spotql-testing",
    "docs/spotql-limitations.md": "external repo: djwaldo/spotql-testing",
    "docs/cross-model-stitching-analysis.md":
        "external repo: djwaldo/spotql-testing, listed 'In flight' in the same block",
    "docs/test-inventory.md": "external repo: the spotQL-testing repo's own test inventory",
    # (a) external repo — apache/ossie. The review states it verified these by
    # listing that checkout's .github/workflows/ directory, not this one's.
    ".github/workflows/converter-databricks-ci.yml": "external repo: apache/ossie",
    ".github/workflows/converter-snowflake-ci.yml": "external repo: apache/ossie",
    # (b) forward references — deliverables the citing item proposes to create
    "docs/mv-to-ts-gap-analysis.md": "forward ref: BL-014 deliverable, cited as NEW",
    "tools/smoke-tests/smoke_ts_convert_from_looker.py": "forward ref: cited as '(new)'",
    "tools/smoke-tests/smoke_ts_convert_from_sisense.py": "forward ref: cited as '(new)'",
    "tools/validate/check_backlog_index.py": "forward ref: cited as 'a new'",
    "tools/validate/generate_skill_personas.py": "forward ref: cited as 'a new' / 'Write'",
    "tools/validate/check_sv_emitter_selfconsistency.py":
        "forward ref: proposed validator promotion",
    "tools/ts-cli/ts_cli/sv_lint_ddl.py":
        "forward ref: proposed module for `ts snowflake lint-ddl`",
    "agents/shared/mappings/analytics/kpi-library.md":
        "forward ref: design doc for an unbuilt skill (ts-object-liveboard-builder)",
    "agents/shared/mappings/analytics/chart-selection.md":
        "forward ref: design doc for an unbuilt skill (ts-object-liveboard-builder)",
    # (c) completed deletion — BL-109 is DONE and the file was the thing deleted
    "agents/claude/references/direct-api-auth.md":
        "completed deletion: BL-109 retired this file (DONE 2026-07-11)",
}

# Links whose targets exist locally but are deliberately untracked / gitignored at
# HEAD — dead links for cloners. Tracked as acknowledged debt so the checker lands
# green; remove in Plan 6 (verification-auditability) once these docs are committed
# or the links are dropped.
KNOWN_UNTRACKED_DEBT: set[str] = set()  # remove in Plan 6 (verification-auditability)

# Maps path prefixes used at runtime to repo-relative paths
CLAUDE_PREFIX_MAP = {
    "~/.claude/shared/": "agents/shared/",
    "~/.claude/mappings/": "agents/shared/mappings/",
    "~/.claude/skills/": "agents/cli/",
}

COCO_PREFIX_MAP = {
    "../../shared/": "agents/shared/",
}

def _prefix_map_for(skill_file: Path) -> dict:
    path_str = str(skill_file)
    if "agents/coco" in path_str:
        return COCO_PREFIX_MAP
    return CLAUDE_PREFIX_MAP


def _file_class(source_file: Path, repo_root: Path) -> str:
    """Classify a source .md file so resolve_path() applies the right base path.

    - "skill": agents/<runtime>/<skill>/SKILL.md — the original, depth-sensitive
      prefix-map behaviour applies (unchanged).
    - "reference": any references/*.md file (one level deeper than SKILL.md) —
      resolve relative links from the file's own directory instead.
    - "doc": anything under docs/ — also resolves relative to its own directory;
      none of the skill prefix maps are meaningful outside agents/.
    """
    try:
        rel_parts = source_file.relative_to(repo_root).parts
    except ValueError:
        rel_parts = source_file.parts

    if source_file.name == "SKILL.md":
        return "skill"
    if "references" in rel_parts:
        return "reference"
    if rel_parts and rel_parts[0] == "docs":
        return "doc"
    # Anything else falls back to the original skill-style resolution rather
    # than silently changing behaviour for an unanticipated file class.
    return "skill"


def resolve_path(link_target: str, skill_file: Path, repo_root: Path) -> Path | None:
    """Resolve a markdown link target to a repo-absolute path. Returns None if unresolvable."""
    # Skip HTTP links, anchors, and empty paths
    if link_target.startswith(("http://", "https://", "#", "mailto:")) or not link_target.strip():
        return None

    # Strip fragment from path
    path_part = link_target.split("#")[0]
    if not path_part:
        return None

    # Skip template placeholders — link targets that contain {var} tokens are
    # emitted-output examples (e.g. MIGRATION_REPORT.md rows: [name]({link})),
    # not real repo paths.
    if "{" in path_part or "}" in path_part:
        return None

    file_class = _file_class(skill_file, repo_root)

    if file_class == "skill":
        prefix_map = _prefix_map_for(skill_file)
    else:
        # references/*.md and docs/**/*.md: only the absolute-style ~/.claude/...
        # shorthand is safe to apply regardless of depth. The CoCo "../../shared/"
        # convention is depth-sensitive and written for SKILL.md's location —
        # applying it here would misresolve a legit relative link from a deeper
        # (references/) or differently-rooted (docs/) file. See module docstring.
        prefix_map = CLAUDE_PREFIX_MAP

    # Apply prefix mappings (longest-prefix-first to avoid partial matches)
    resolved = path_part
    for prefix, replacement in sorted(prefix_map.items(), key=lambda x: -len(x[0])):
        if resolved.startswith(prefix):
            resolved = replacement + resolved[len(prefix):]
            return repo_root / resolved

    # Relative path — resolve from the source file's own directory. This is
    # depth-correct by construction (Path.resolve() walks the actual ../ segments),
    # which is why references/*.md and docs/*.md rely on it rather than a prefix map.
    if not resolved.startswith("/"):
        return (skill_file.parent / resolved).resolve()

    # Absolute path starting with / — unusual, skip
    return None


def _git_tracked(repo_root: Path) -> set[str]:
    """Repo-relative paths currently tracked by git."""
    # NUL-split via _git: `.splitlines()` dropped octal-quoted paths, so a
    # non-ASCII filename read as untracked (audit 4.2).
    return set(tracked_relpaths(repo_root))


def tracked_top_level_dirs(tracked: set[str]) -> set[str]:
    """Top-level directories that contain at least one git-tracked file.

    Deliberately derived from TRACKED paths, not from os.listdir: an untracked
    working directory (a scratch dir such as a study's .svrt/) must not become a
    recognised path root, or every citation into it reports as a broken
    reference when it is gitignored by design.
    """
    return {p.split("/")[0] for p in tracked if "/" in p}


def backtick_candidates(line: str, top_dirs: set[str]) -> list[str]:
    """Repo-relative path candidates from the backtick tokens on one line."""
    out = []
    for token in BACKTICK_PATTERN.findall(line):
        # Strip trailing citation locators, possibly stacked (file.py:12::sym).
        prev = None
        while prev != token:
            prev = token
            token = _LOCATOR_SUFFIX.sub("", token)
        if any(c in token for c in '{}<>*?[]()|$"\'') or token.endswith("/"):
            continue
        if token.startswith(("http://", "https://", "#", "~", "/", "mailto:")):
            continue
        if "/" not in token:
            continue
        segments = token.split("/")
        if segments[0] not in top_dirs:
            continue
        if "." not in segments[-1]:
            continue
        out.append(token)
    return out


def _strip_fenced_blocks(lines: list[str]) -> list[tuple[int, str]]:
    """(line_no, text) for lines outside ``` / ~~~ fenced code blocks.

    Fenced blocks hold example commands and sample output, where a path that does
    not exist is often the point.
    """
    out = []
    in_fence = False
    for line_num, line in enumerate(lines, 1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append((line_num, line))
    return out


def collect_backtick_candidates(
    md_file: Path, repo_root: Path, top_dirs: set[str]
) -> list[tuple[int, str]]:
    """All (line_num, candidate_path) backtick citations in one markdown file."""
    lines = md_file.read_text(encoding="utf-8").splitlines()
    found = []
    for line_num, line in _strip_fenced_blocks(lines):
        for candidate in backtick_candidates(line, top_dirs):
            found.append((line_num, candidate))
    return found


def git_ignored(paths: set[str], repo_root: Path) -> set[str]:
    """Subset of `paths` that .gitignore excludes — never expected to resolve."""
    if not paths:
        return set()
    ordered = sorted(paths)
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            input="\n".join(ordered), cwd=repo_root,
            capture_output=True, text=True,
        )
    except OSError:
        return set()
    # exit 1 simply means "nothing matched" — not an error.
    if result.returncode not in (0, 1):
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def check_skill_file(
    skill_file: Path, repo_root: Path, tracked: set[str] | None = None
) -> list[tuple[int, str, str]]:
    """Return list of (line_num, link_target, resolved_path) for broken references.

    Two failure modes:
      - target does not exist on disk (classic broken link)
      - target exists but is untracked/gitignored while the source file IS tracked —
        a dead link for anyone who clones the repo (audit 4.1)
    """
    broken = []
    src_rel = str(skill_file.relative_to(repo_root)) if skill_file.is_absolute() else str(skill_file)
    src_tracked = tracked is not None and src_rel in tracked
    content = skill_file.read_text(encoding="utf-8")
    for line_num, line in enumerate(content.splitlines(), 1):
        for _text, target in LINK_PATTERN.findall(line):
            resolved = resolve_path(target, skill_file, repo_root)
            if resolved is None:
                continue
            if not resolved.exists():
                rel_resolved = resolved.relative_to(repo_root) if resolved.is_absolute() else resolved
                broken.append((line_num, target, str(rel_resolved)))
                continue
            # Exists on disk — but is it tracked? Only enforce when the source is tracked
            # (untracked source files are WIP and not yet cloners' concern).
            if tracked is not None and src_tracked and resolved.is_absolute():
                try:
                    rel_resolved = str(resolved.relative_to(repo_root))
                except ValueError:
                    continue  # outside repo — not our concern
                if rel_resolved not in tracked and rel_resolved not in KNOWN_UNTRACKED_DEBT:
                    broken.append((line_num, target, rel_resolved + "  [untracked]"))
    return broken


# docs/ subtrees excluded from validation entirely:
#   docs/audit/          — dated audit reports; historical snapshots, not maintained links
#   docs/superpowers/     — generated plan/spec scratch docs from the superpowers skill workflow
#   *backlog-archive*    — archived backlog content, not maintained
DOCS_EXCLUDED_PREFIXES = ("docs/audit/", "docs/superpowers/")


def _is_excluded_doc(doc_file: Path, repo_root: Path) -> bool:
    rel = str(doc_file.relative_to(repo_root))
    if rel.startswith(DOCS_EXCLUDED_PREFIXES):
        return True
    if "backlog-archive" in doc_file.name:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check SKILL.md / references/*.md / docs/**/*.md file references."
    )
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    skill_files = runtime_globs(repo_root, "*/SKILL.md")
    reference_files = runtime_globs(repo_root, "*/references/*.md")
    doc_files = [
        p for p in repo_root.glob("docs/**/*.md")
        if not _is_excluded_doc(p, repo_root)
    ]

    all_files = skill_files + reference_files + doc_files

    if not all_files:
        print("No SKILL.md / references / docs files found.")
        return 1

    tracked = _git_tracked(repo_root)
    top_dirs = tracked_top_level_dirs(tracked)

    # Pass 1 — gather every backtick path candidate, so .gitignore is consulted
    # once for the whole set rather than per line.
    backtick_hits: dict[Path, list[tuple[int, str]]] = {}
    all_candidates: set[str] = set()
    for md_file in all_files:
        hits = collect_backtick_candidates(md_file, repo_root, top_dirs)
        if hits:
            backtick_hits[md_file] = hits
            all_candidates.update(candidate for _line, candidate in hits)
    ignored = git_ignored(all_candidates, repo_root)

    # Pass 2 — report. Markdown links and backtick paths share one exit code.
    total_broken = 0
    exempted = 0
    for skill_file in sorted(all_files):
        rel = skill_file.relative_to(repo_root)
        broken = check_skill_file(skill_file, repo_root, tracked)
        file_bad = False
        if broken:
            file_bad = True
            for line_num, target, resolved in broken:
                if resolved.endswith("[untracked]"):
                    clean = resolved.removesuffix("  [untracked]")
                    print(f"FAIL  {rel}:{line_num}  →  {target}  "
                          f"(resolved: {clean})  link target exists locally but is "
                          "untracked/gitignored — dead link for cloners")
                else:
                    print(f"FAIL  {rel}:{line_num}  →  {target}  (resolved: {resolved})")
                total_broken += 1

        for line_num, candidate in backtick_hits.get(skill_file, []):
            if candidate in ignored:
                continue
            if candidate in KNOWN_MISSING_BACKTICK_PATHS:
                exempted += 1
                continue
            target = repo_root / candidate
            if not target.exists():
                print(f"FAIL  {rel}:{line_num}  →  `{candidate}`  "
                      "backtick-cited repo path does not exist")
                total_broken += 1
                file_bad = True
            elif candidate not in tracked:
                print(f"FAIL  {rel}:{line_num}  →  `{candidate}`  "
                      "backtick-cited repo path exists locally but is untracked "
                      "— dead reference for cloners")
                total_broken += 1
                file_bad = True

        if not file_bad:
            print(f"PASS  {rel}")

    print()
    if exempted:
        print(f"{exempted} backtick citation(s) matched "
              "KNOWN_MISSING_BACKTICK_PATHS (see the table for each reason).")
    if total_broken:
        print(f"{total_broken} broken reference(s) found.")
        return 1
    else:
        print("All references resolved.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
