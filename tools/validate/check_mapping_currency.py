#!/usr/bin/env python3
"""
check_mapping_currency.py — soft-warn when a shared mapping OR schema file lacks a
current currency anchor (see .claude/rules/repo-audit.md, angle 13 "Product currency").

Cross-platform mappings AND the platform schema files encode assumptions about products
that move (a function that "can't" translate may gain a native equivalent; a construct
may be deprecated; a new chart library or semantic-view feature may appear). A validator
can't know the product's current state — but it CAN nudge when an assumption hasn't been
re-checked in a while. The 2026-06-17 audit found every drift lived in an *anchorless
schema file*, so schemas are covered here too, not just mappings.

Each file under agents/shared/mappings/ and agents/shared/schemas/ should carry an
anchor near the top:

    <!-- currency: <platform> — <YYYY-MM> (<context>) -->

This is a NUDGE, never a block: external knowledge can't gate a PR. It warns when a
changed mapping has no anchor, or one older than STALE_MONTHS. The weekly external sweep
is what actually re-validates and bumps the anchors.

Usage:
    python3 tools/validate/check_mapping_currency.py --root .            # all mappings
    python3 tools/validate/check_mapping_currency.py --root . --staged   # staged only (pre-commit)
    python3 tools/validate/check_mapping_currency.py --root . --check    # exit 1 if any issue
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from _git import git_paths

# ── CONFIG (repo-specific) ───────────────────────────────────────────────────
# `worked-examples` was added 2026-08-26 (audit 13.3). Worked examples encode
# product-shaped assumptions exactly as mappings and schemas do — input TML shapes,
# DDL forms, chart config — but sat outside this net, so nothing nudged them and no
# sweep was pointed at them. 11 of 17 carried no anchor, which is why the canonical
# to-Snowflake example still taught Worksheet TML as the BASIC path three majors
# after Worksheet import was blocked at 10.13.0.cl (audit 13.2).
ANCHORED_DIRS = (
    "agents/shared/mappings",
    "agents/shared/schemas",
    "agents/shared/worked-examples",
    # The Ossie mapping documents pin a specific apache/ossie commit and cite it by
    # path:line throughout. Upstream renamed osi-schema.json and corrected its ICLA
    # policy while these sat unwatched for four weeks and nothing nudged (2026-08-31).
    "docs/ossie",
)
# Individual files (outside the dirs above) that also carry a currency anchor — e.g. a
# skill reference encoding external product behaviour that moves (AgentQL limitations),
# or a rule whose content is pinned to a moving external lineup (model-routing's tier
# table goes stale the same way a product mapping does — audit 18.7).
ANCHORED_FILES = (
    "agents/cli/ts-object-model-agentql-query/references/limitations.md",
    ".claude/rules/model-routing.md",
)
STALE_MONTHS = 6

#: Paths in an upstream repo whose movement makes an anchor citing that repo
#: suspect. An anchor on `docs/ossie/*` pins a spec commit and cites it by
#: path:line throughout, so a converter landing upstream is irrelevant to it
#: while a `core-spec/` change is not. Counting raw commits would cry wolf --
#: apache/ossie ran 54 commits ahead of the anchored SHA while `core-spec/`
#: moved only a handful of times.
UPSTREAM_WATCHED_PATHS = ("core-spec/",)
# ─────────────────────────────────────────────────────────────────────────────

# <!-- currency: snowflake — 2026-06 (Cortex Analyst GA) -->   (en/em dash or hyphen)
# The platform group deliberately allows `-`: it previously excluded it to
# disambiguate from a plain-hyphen separator, which silently broke every
# hyphenated platform name. `.claude/rules/model-routing.md` carried a valid
# `claude-harness — 2026-07` anchor that this regex could not parse, so the file
# reported "no currency anchor" while being anchored (found 2026-08-26). The
# separator is disambiguated by what FOLLOWS it instead — a 4-digit year — which
# a platform name never is.
ANCHOR_RE = re.compile(
    r"<!--\s*currency:\s*(?P<platform>.+?)\s*[—–-]\s*(?P<year>\d{4})-(?P<month>\d{2})\b",
    re.IGNORECASE,
)


#: `apache/ossie @ b5da5d6` inside an anchor's context parenthetical. Optional --
#: an anchor that cites no upstream commit is checked on age alone, as before.
UPSTREAM_REF_RE = re.compile(
    r"(?P<repo>[\w.-]+/[\w.-]+)\s*@\s*(?P<sha>[0-9a-f]{7,40})\b"
)


def upstream_drift(repo: str, sha: str, timeout: int = 15) -> tuple[int, int] | None:
    """`(commits ahead, of those touching a watched path)`, or None if unknown.

    Two calls, because the obvious one call does not work. `compare/{sha}...HEAD`
    returns a `files` list capped at **300 entries**, ordered by path -- and in
    apache/ossie the sixteen `converters/` directories exhaust that cap before
    reaching `core-spec/`. The first version of this function used it and
    reported "0 files touched core-spec" against a range that certainly touched
    it, which would have read as "no drift" forever. So: ask for the anchored
    commit's date, then ask for commits on the watched paths since that date.

    Returns None rather than raising for every reason this can fail -- offline,
    rate-limited, unknown SHA, GitHub down. A currency nudge must never turn a
    network hiccup into a failed commit, which is also why it is opt-in.

    `GITHUB_TOKEN` is used when present, purely for the rate limit.
    """
    import json
    import os
    import urllib.error
    import urllib.parse
    import urllib.request

    token = os.environ.get("GITHUB_TOKEN")

    def _get(path: str):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/{path}",
            headers={"Accept": "application/vnd.github+json"},
        )
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    try:
        comparison = _get(f"compare/{sha}...HEAD")
        ahead = comparison.get("ahead_by")
        if ahead is None:
            return None
        anchored = _get(f"commits/{sha}")
        since = (anchored.get("commit") or {}).get("committer", {}).get("date")
        if not since:
            return None
        watched = 0
        for watched_path in UPSTREAM_WATCHED_PATHS:
            query = urllib.parse.urlencode(
                {"path": watched_path.rstrip("/"), "since": since, "per_page": 100}
            )
            # `since` is inclusive of the anchored commit itself when that commit
            # touched the path, so it is discounted by sha rather than by date.
            watched += sum(
                1 for c in _get(f"commits?{query}") or [] if not c.get("sha", "").startswith(sha)
            )
    except (urllib.error.URLError, OSError, ValueError, TimeoutError, KeyError, AttributeError):
        return None
    return ahead, watched


def _months_between(anchor: date, today: date) -> int:
    return (today.year - anchor.year) * 12 + (today.month - anchor.month)


# A missing/malformed anchor is a presence failure (BLOCKING — a new shared file must
# carry one); a stale anchor is a soft nudge (external knowledge can't gate a PR, and
# staleness must not block unrelated PRs as anchors age).
BLOCKING_KINDS = {"missing", "malformed"}


def check_file(
    path: Path, today: date, *, check_upstream: bool = False
) -> tuple[str, str] | None:
    """Return (kind, message) for a missing/malformed/stale/drifted anchor, else None.
    kind ∈ {"missing", "malformed", "stale", "drifted"}.

    `check_upstream` adds the network half: an anchor citing `<repo> @ <sha>` is
    compared against that repo's HEAD. It is opt-in because the age check must
    keep working offline in pre-commit, and because a nudge that needs GitHub to
    be reachable would otherwise fail commits on a train.

    Age alone was not enough. `docs/ossie/*` sat anchored at `apache/ossie @
    b5da5d6` while upstream ran 54 commits ahead -- including the merge of the
    converter those documents describe -- and the anchor read `2026-08`, so the
    six-month age test stayed silent and would have until February. The anchor
    recorded a SHA that nothing ever checked.
    """
    try:
        # only need the head of the file — the anchor lives near the top
        head = "".join(path.read_text(encoding="utf-8").splitlines(keepends=True)[:15])
    except OSError:
        return None
    m = ANCHOR_RE.search(head)
    if not m:
        return ("missing", "no currency anchor — add `<!-- currency: <platform> — YYYY-MM (context) -->` near the top")
    try:
        anchor = date(int(m.group("year")), int(m.group("month")), 1)
    except ValueError:
        return ("malformed", f"malformed currency anchor date: {m.group('year')}-{m.group('month')}")
    age = _months_between(anchor, today)
    if age > STALE_MONTHS:
        return ("stale", f"currency anchor is {age} months old ({m.group('year')}-{m.group('month')}) — re-validate against the current product")

    if check_upstream:
        ref = UPSTREAM_REF_RE.search(head)
        if ref:
            drift = upstream_drift(ref.group("repo"), ref.group("sha"))
            if drift is None:
                return ("unknown", f"could not reach {ref.group('repo')} to check drift from {ref.group('sha')} — network, rate limit, or unknown commit")
            ahead, watched = drift
            if watched:
                return ("drifted", f"anchored at {ref.group('repo')} @ {ref.group('sha')}, now {ahead} commit(s) behind — {watched} touched {', '.join(UPSTREAM_WATCHED_PATHS)}; re-validate and re-anchor")
    return None


def _is_anchored_path(rel: str) -> bool:
    if rel in ANCHORED_FILES:
        return True
    return rel.endswith(".md") and any(rel.startswith(d + "/") for d in ANCHORED_DIRS)


def _staged_anchored_files(repo_root: Path) -> list[Path]:
    return [
        repo_root / f
        for f in git_paths(["diff", "--cached", "--name-only", "--diff-filter=ACM"], repo_root)
        if _is_anchored_path(f) and (repo_root / f).exists()
    ]


def _all_anchored_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for d in ANCHORED_DIRS:
        base = repo_root / d
        if base.is_dir():
            files.extend(base.rglob("*.md"))
    for f in ANCHORED_FILES:
        p = repo_root / f
        if p.exists():
            files.append(p)
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description="Nudge on stale mapping/schema currency anchors.")
    parser.add_argument("--root", default=".", help="Repo root (default: cwd)")
    parser.add_argument("--staged", action="store_true", help="Only staged mapping/schema files")
    parser.add_argument("--check", action="store_true", help="Exit 1 if any issue (default: warn-only)")
    parser.add_argument("--check-upstream", action="store_true",
                        help="Also compare anchors citing `<repo> @ <sha>` against that "
                             "repo's HEAD. Needs network; off by default so pre-commit "
                             "stays offline. For the external/weekly sweep.")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    today = date.today()
    files = _staged_anchored_files(repo_root) if args.staged else _all_anchored_files(repo_root)

    issues: list[tuple[Path, str, str]] = []  # (rel, kind, msg)
    for f in files:
        res = check_file(f, today, check_upstream=args.check_upstream)
        if res:
            issues.append((f.relative_to(repo_root), res[0], res[1]))

    if issues:
        print("  Currency anchors:")
        for rel, kind, msg in issues:
            tag = "FAIL" if kind in BLOCKING_KINDS else "nudge"
            print(f"    • [{tag}] {rel}: {msg}")
        blocking = [i for i in issues if i[1] in BLOCKING_KINDS]
        # --check fails ONLY on presence (missing/malformed); staleness is always soft so
        # it never blocks an unrelated PR as anchors age.
        return 1 if (args.check and blocking) else 0

    if not args.staged:
        suffix = "" if args.check_upstream else " (age only — pass --check-upstream to check drift)"
        print(f"All {len(files)} anchored file(s) have a current currency anchor{suffix}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
