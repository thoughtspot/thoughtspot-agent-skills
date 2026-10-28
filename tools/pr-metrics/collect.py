#!/usr/bin/env python3
"""
collect.py — baseline PR metrics, maintainer and external PRs reported separately.

The PR-quality design (docs/superpowers/specs/2026-10-28-pr-quality-system-design.md,
§5 C7 "Measurement") commits to judging its changes by numbers stated up front. A
"before" figure taken after the changes land is worthless, so this script exists to
take the baseline first and to be rerun, unchanged, at the end of the window.

What it measures, per group (maintainer / external / bot):
  - PR count and merged count, for PRs CREATED inside [--since, --until] (UTC dates,
    both ends inclusive);
  - median days open — created to merged or closed; still-open PRs are left out
    rather than measured to an arbitrary "now", so a rerun gives the same number;
  - median changed lines (additions + deletions);
  - median review rounds — a review in state CHANGES_REQUESTED, or COMMENTED with a
    body of at least REVIEW_ROUND_MIN_BODY characters. A short COMMENTED review is
    usually a thread reply or a "thanks", not a round of requested work;
  - post-merge defects from attributions.yaml, counted against the group of the PR
    that INTRODUCED the defect, not the PR that fixed it. Counting by when a defect
    entered is the method from the spec's refute pass: counting by fix date credits a
    defect to whoever happened to notice it.

Bots (author.is_bot) are their own group. Folding dependency-bump PRs into "external"
would move the external medians on PRs no contributor wrote.

Privacy: the report is keyed by PR number only. An author login is read solely to
classify the PR and is never written — `.claude/rules/security.md`, the repo is
public. `main` also refuses to write a report in which any input login appears as a
word, so a future edit that leaks one fails closed rather than publishing it.

Usage:
    python3.12 tools/pr-metrics/collect.py --since 2026-07-01 --until 2026-10-28 \\
        --out docs/reviews/2026-10-28-pr-metrics-baseline.md

Needs the `gh` CLI (authenticated) and PyYAML. Review lists are fetched per PR, only
for PRs inside the window — the full history is several hundred API calls.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

import yaml

DEFAULT_REPO = "thoughtspot/thoughtspot-agent-skills"
DEFAULT_MAINTAINER = "djwaldo"
DEFAULT_ATTRIBUTIONS = Path(__file__).resolve().parent / "attributions.yaml"
PR_LIST_FIELDS = "number,author,state,createdAt,mergedAt,closedAt,additions,deletions,reviews"
REVIEW_ROUND_MIN_BODY = 200
FOUND_BY = ("audit", "live", "review", "ci", "self")
GROUPS = ("maintainer", "external", "bot")
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


# --- pure ---------------------------------------------------------------------------

def review_rounds(reviews: List[dict]) -> int:
    """Number of reviews that asked for work: CHANGES_REQUESTED, or a long COMMENTED."""
    count = 0
    for review in reviews:
        state = review.get("state")
        if state == "CHANGES_REQUESTED":
            count += 1
        elif state == "COMMENTED" and len(review.get("body") or "") >= REVIEW_ROUND_MIN_BODY:
            count += 1
    return count


def classify(pr: dict, maintainer: str) -> str:
    author = pr.get("author") or {}
    if author.get("is_bot"):
        return "bot"
    return "maintainer" if author.get("login") == maintainer else "external"


def _in_window(pr: dict, since: str, until: str) -> bool:
    return since <= (pr.get("createdAt") or "")[:10] <= until


def _days_open(pr: dict) -> Optional[float]:
    end = pr.get("mergedAt") or pr.get("closedAt")
    if not end:
        return None
    start = dt.datetime.strptime(pr["createdAt"], _TS_FORMAT)
    stop = dt.datetime.strptime(end, _TS_FORMAT)
    return (stop - start).total_seconds() / 86400


def _median(values: List[float], digits: int = 2) -> Optional[float]:
    return round(statistics.median(values), digits) if values else None


def _validate_attribution(entry: dict, index: int) -> dict:
    missing = [k for k in ("fix_pr", "introduced_by_pr", "introduced_on", "found_by")
               if entry.get(k) in (None, "")]
    if missing:
        raise ValueError(f"attribution #{index + 1}: missing {', '.join(missing)}")
    if entry["found_by"] not in FOUND_BY:
        raise ValueError(f"attribution #{index + 1}: found_by must be one of "
                         f"{'|'.join(FOUND_BY)}, got {entry['found_by']!r}")
    return {
        "fix_pr": int(entry["fix_pr"]),
        "introduced_by_pr": int(entry["introduced_by_pr"]),
        # YAML parses an unquoted 2026-07-10 as a date; normalise either form.
        "introduced_on": str(entry["introduced_on"]),
        "found_by": entry["found_by"],
        "note": str(entry.get("note") or ""),
    }


def collect(prs: List[dict], attributions: List[dict], since: str, until: str,
            maintainer: str = DEFAULT_MAINTAINER) -> dict:
    """Aggregate PR metrics for PRs created in [since, until]. Output holds no logins."""
    rows = []
    for pr in prs:
        if not _in_window(pr, since, until):
            continue
        rows.append({
            "number": int(pr["number"]),
            "group": classify(pr, maintainer),
            "state": pr.get("state"),
            "merged": bool(pr.get("mergedAt")),
            "days_open": _days_open(pr),
            "changed_lines": int(pr.get("additions") or 0) + int(pr.get("deletions") or 0),
            "review_rounds": review_rounds(pr.get("reviews") or []),
        })
    rows.sort(key=lambda r: r["number"])
    group_of = {r["number"]: r["group"] for r in rows}

    defects = [_validate_attribution(a, i) for i, a in enumerate(attributions)]
    placed: Dict[str, List[dict]] = {g: [] for g in GROUPS}
    outside = []
    for defect in defects:
        group = group_of.get(defect["introduced_by_pr"])
        if group is None:
            outside.append(defect)
        else:
            placed[group].append(defect)

    groups = {}
    for group in GROUPS:
        members = [r for r in rows if r["group"] == group]
        days = [r["days_open"] for r in members if r["days_open"] is not None]
        groups[group] = {
            "pr_count": len(members),
            "merged_count": sum(1 for r in members if r["merged"]),
            "open_count": sum(1 for r in members if r["state"] == "OPEN"),
            # Three places, and hours beside it: the maintainer median is minutes,
            # which two-place days would print as a flat 0.
            "median_days_open": _median(days, 3),
            "median_hours_open": round(statistics.median(days) * 24, 1) if days else None,
            "median_changed_lines": _median([r["changed_lines"] for r in members]),
            "median_review_rounds": _median([r["review_rounds"] for r in members]),
            "post_merge_defects": len(placed[group]),
            "defects_found_by": {k: sum(1 for d in placed[group] if d["found_by"] == k)
                                 for k in FOUND_BY},
        }

    return {
        "since": since,
        "until": until,
        "groups": groups,
        "prs": rows,
        "defects": sorted(defects, key=lambda d: (d["introduced_on"], d["fix_pr"])),
        "defects_outside_window": len(outside),
    }


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def render_markdown(result: dict) -> str:
    since, until = result["since"], result["until"]
    g = result["groups"]
    out = [
        f"# PR metrics baseline — {since} to {until}",
        "",
        "Generated by `tools/pr-metrics/collect.py`; do not edit by hand — rerun it.",
        "",
        "- **Window:** PRs created between "
        f"{since} and {until} (UTC, inclusive). Rerun with the same arguments to compare.",
        "- **Method:** PR data from `gh pr list`, review lists from the GitHub reviews "
        "API per PR. A *review round* is a `CHANGES_REQUESTED` review, or a `COMMENTED` "
        f"review with a body of at least {REVIEW_ROUND_MIN_BODY} characters. *Days open* "
        "runs from creation to merge or close; still-open PRs are left out of that "
        "median. *Changed lines* is additions + deletions. Bots are reported apart from "
        "external contributors.",
        "- **Post-merge defects** come from `tools/pr-metrics/attributions.yaml` and are "
        "counted against the group of the PR that *introduced* the defect, not the one "
        "that fixed it. The attributions file started empty at this baseline and is "
        "filled as fixes land, so a zero below means \"none attributed yet\", not "
        "\"none exist\".",
        "- **Privacy:** keyed by PR number only; no author is named.",
        "",
        "## Summary",
        "",
        "| Metric | " + " | ".join(GROUPS) + " |",
        "|---|" + "---:|" * len(GROUPS),
    ]
    metrics = [
        ("PRs created", "pr_count"),
        ("Merged", "merged_count"),
        ("Still open", "open_count"),
        ("Median days open", "median_days_open"),
        ("Median hours open", "median_hours_open"),
        ("Median changed lines", "median_changed_lines"),
        ("Median review rounds", "median_review_rounds"),
        ("Post-merge defects (by introducing PR)", "post_merge_defects"),
    ]
    for label, key in metrics:
        out.append(f"| {label} | " + " | ".join(_fmt(g[grp][key]) for grp in GROUPS) + " |")
    out += [
        "",
        f"Defects attributed to a PR outside this window: {result['defects_outside_window']}.",
        "",
        "## Post-merge defects",
        "",
    ]
    if result["defects"]:
        group_of = {r["number"]: r["group"] for r in result["prs"]}
        out += ["| Introduced by | Introduced on | Group | Fixed by | Found by | Note |",
                "|---:|---|---|---:|---|---|"]
        for d in result["defects"]:
            out.append(f"| #{d['introduced_by_pr']} | {d['introduced_on']} | "
                       f"{group_of.get(d['introduced_by_pr'], 'outside window')} | "
                       f"#{d['fix_pr']} | {d['found_by']} | {d['note']} |")
    else:
        out.append("None attributed yet.")
    external = [r for r in result["prs"] if r["group"] == "external"]
    out += [
        "",
        "## External PRs",
        "",
        "Per-PR rows for the group the measurement is mainly about, so a median can be "
        "traced to its inputs.",
        "",
    ]
    if external:
        out += ["| PR | State | Days open | Changed lines | Review rounds |",
                "|---:|---|---:|---:|---:|"]
        for r in external:
            days = None if r["days_open"] is None else round(r["days_open"], 2)
            out.append(f"| #{r['number']} | {r['state']} | {_fmt(days)} | "
                       f"{r['changed_lines']} | {r['review_rounds']} |")
    else:
        out.append("None in this window.")
    return "\n".join(out) + "\n"


# --- I/O ------------------------------------------------------------------------------

def _gh(args: List[str]) -> str:
    proc = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {proc.stderr.strip()}")
    return proc.stdout


def fetch_prs(repo: str) -> List[dict]:
    return json.loads(_gh(["pr", "list", "--repo", repo, "--state", "all",
                           "--limit", "1000", "--json", PR_LIST_FIELDS]))


def fetch_reviews(repo: str, number: int) -> List[dict]:
    # --paginate on a list endpoint concatenates one JSON array per page; --jq '.[]'
    # flattens that to one object per line regardless of page count.
    out = _gh(["api", f"repos/{repo}/pulls/{number}/reviews", "--paginate",
               "--jq", ".[] | {state, body}"])
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def load_attributions(path: Path) -> List[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a YAML list of attributions")
    return data


def _leaked_login(text: str, prs: List[dict]) -> bool:
    logins = {(pr.get("author") or {}).get("login") for pr in prs}
    names = {(pr.get("author") or {}).get("name") for pr in prs}
    for value in (logins | names) - {None, ""}:
        if re.search(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", text, re.IGNORECASE):
            return True
    return False


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", required=True, help="first creation date, YYYY-MM-DD")
    parser.add_argument("--until", required=True, help="last creation date, YYYY-MM-DD")
    parser.add_argument("--out", help="write the Markdown report here (default: stdout)")
    parser.add_argument("--repo", default=DEFAULT_REPO,
                        help="owner/name; explicit so a fork clone still measures upstream")
    parser.add_argument("--maintainer", default=DEFAULT_MAINTAINER,
                        help="login classified as maintainer; never written to output")
    parser.add_argument("--attributions", type=Path, default=DEFAULT_ATTRIBUTIONS)
    args = parser.parse_args(argv)

    for value in (args.since, args.until):
        dt.date.fromisoformat(value)

    attributions = load_attributions(args.attributions)
    prs = fetch_prs(args.repo)
    in_window = [pr for pr in prs if _in_window(pr, args.since, args.until)]
    print(f"{len(prs)} PRs listed, {len(in_window)} in window; fetching reviews...",
          file=sys.stderr)
    with ThreadPoolExecutor(max_workers=8) as pool:
        reviews = list(pool.map(lambda pr: fetch_reviews(args.repo, pr["number"]),
                                in_window))
    for pr, pr_reviews in zip(in_window, reviews):
        pr["reviews"] = pr_reviews

    text = render_markdown(collect(prs, attributions, args.since, args.until,
                                   maintainer=args.maintainer))
    if _leaked_login(text, prs):
        # Never name the login, not even here: stderr ends up in CI logs and transcripts.
        print("ERROR: an author login or name appears in the report; refusing to write it.",
              file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
