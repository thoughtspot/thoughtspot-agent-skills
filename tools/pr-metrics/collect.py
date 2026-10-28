#!/usr/bin/env python3
"""
collect.py — baseline PR metrics, maintainer and external PRs reported separately.

The PR-quality design (docs/superpowers/specs/2026-10-28-pr-quality-system-design.md,
§5 C7 "Measurement") commits to judging its changes by numbers stated up front. A
"before" figure taken after the changes land is worthless, so this script exists to
take the baseline first and to be run again, unchanged, at the end of the window.

What it measures, per group (maintainer / external / bot):
  - PR count, merged count and still-open count, for PRs CREATED inside
    [--since, --until] (UTC dates, both ends inclusive);
  - median days open — created to merged or closed. Still-open PRs are left out of
    this median (and only this one) rather than measured to an arbitrary "now";
  - median changed lines (additions + deletions);
  - median review rounds — a review in state CHANGES_REQUESTED, or COMMENTED with a
    body of at least REVIEW_ROUND_MIN_BODY characters, written by someone other than
    the PR's author and not by a bot. A short COMMENTED review is usually a thread
    reply or a "thanks", not a round of requested work. Reviews posted as ordinary
    conversation comments are invisible to the reviews API, so those PRs carry a
    hand-kept count in rounds_overrides.yaml that REPLACES the computed one;
  - post-merge defects from attributions.yaml, counted against the group of the PR
    that INTRODUCED the defect, not the PR that fixed it. Counting by when a defect
    entered is the method from the spec's refute pass: counting by fix date credits a
    defect to whoever happened to notice it.

Not measured: the spec's "blocker findings per first-round review" needs each
first-round review classified by hand, which no API field records.

Bots (author.is_bot) are their own group. Folding dependency-bump PRs into "external"
would move the external medians on PRs no contributor wrote.

The maintainer is the single owner named in .github/CODEOWNERS unless --maintainer
is given; logins compare case-insensitively. Nothing in the repo spells the login
out for this script, so it cannot drift from who actually owns the repo.

Privacy: the report is keyed by PR number only. Logins (authors, reviewers) and
display names are read solely to classify and are never written —
`.claude/rules/security.md`, the repo is public. `main` also refuses to write a
report in which any login or name seen during collection appears as a word, so a
future edit — or an attribution note — that leaks one fails closed.

Reproducibility: the report records when it was collected. PRs still open then can
gain reviews and lines or close later, so the same arguments run later will not give
the same numbers; compare against the snapshot, not a rerun.

Usage:
    python3 tools/pr-metrics/collect.py --since 2026-07-01 --until 2026-10-28 \\
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
from typing import Dict, Iterable, List, Optional, Set

import yaml

_HERE = Path(__file__).resolve().parent
DEFAULT_REPO = "thoughtspot/thoughtspot-agent-skills"
DEFAULT_CODEOWNERS = _HERE.parents[1] / ".github" / "CODEOWNERS"
DEFAULT_ATTRIBUTIONS = _HERE / "attributions.yaml"
DEFAULT_OVERRIDES = _HERE / "rounds_overrides.yaml"
PR_LIST_FIELDS = "number,author,state,createdAt,mergedAt,closedAt,additions,deletions,reviews"
PR_LIST_LIMIT = 1000
REVIEW_ROUND_MIN_BODY = 200
FOUND_BY = ("audit", "live", "review", "ci", "self")
GROUPS = ("maintainer", "external", "bot")
_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


# --- pure ---------------------------------------------------------------------------

def maintainer_from_codeowners(text: str) -> str:
    """The one distinct owner named in a CODEOWNERS file, '@' stripped, lower-cased."""
    owners: Set[str] = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        owners.update(tok[1:].lower() for tok in line.split()[1:] if tok.startswith("@"))
    if len(owners) != 1:
        # The count only: stderr reaches CI logs and transcripts, logins must not.
        raise ValueError(f"CODEOWNERS names {len(owners)} distinct owners, expected "
                         "exactly 1; pass --maintainer")
    return owners.pop()


def _login(obj: Optional[dict]) -> str:
    return ((obj or {}).get("login") or "").lower()


def _review_login(review: dict) -> str:
    # The reviews API gives a flat login (see fetch_reviews); `gh pr list` nests it.
    return (review.get("login") or _login(review.get("author"))).lower()


def _review_is_bot(review: dict) -> bool:
    return review.get("type") == "Bot" or _review_login(review).endswith("[bot]")


def review_rounds(reviews: List[dict], author: str = "") -> int:
    """Reviews that asked for work: CHANGES_REQUESTED, or a long COMMENTED.

    A review by the PR's own author (a reply to a thread is filed as a COMMENTED
    review) or by a bot is not a round of review.
    """
    author = author.lower()
    count = 0
    for review in reviews:
        if (author and _review_login(review) == author) or _review_is_bot(review):
            continue
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
    return "maintainer" if _login(author) == maintainer.lower() else "external"


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
    where = f"attribution #{index + 1}"
    missing = [k for k in ("fix_pr", "introduced_by_pr", "introduced_on", "found_by")
               if entry.get(k) in (None, "")]
    if missing:
        raise ValueError(f"{where}: missing {', '.join(missing)}")
    if entry["found_by"] not in FOUND_BY:
        raise ValueError(f"{where}: found_by must be one of "
                         f"{'|'.join(FOUND_BY)}, got {entry['found_by']!r}")
    # YAML parses an unquoted 2026-07-10 as a date; a quoted one stays a string.
    try:
        introduced_on = dt.date.fromisoformat(str(entry["introduced_on"])).isoformat()
    except ValueError:
        raise ValueError(f"{where}: introduced_on must be a YYYY-MM-DD date, "
                         f"got {entry['introduced_on']!r}") from None
    return {
        "fix_pr": int(entry["fix_pr"]),
        "introduced_by_pr": int(entry["introduced_by_pr"]),
        "introduced_on": introduced_on,
        "found_by": entry["found_by"],
        "note": str(entry.get("note") or ""),
    }


def _validate_overrides(overrides: List[dict]) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    for index, entry in enumerate(overrides):
        where = f"rounds override #{index + 1}"
        if not isinstance(entry, dict) or entry.get("pr") is None or entry.get("rounds") is None:
            raise ValueError(f"{where}: needs pr and rounds")
        pr, rounds = int(entry["pr"]), int(entry["rounds"])
        if rounds < 0:
            raise ValueError(f"{where}: rounds must be >= 0")
        if pr in out:
            raise ValueError(f"{where}: PR #{pr} is listed twice")
        out[pr] = {"rounds": rounds, "note": str(entry.get("note") or "")}
    return out


def collect(prs: List[dict], attributions: List[dict], since: str, until: str, *,
            maintainer: str, overrides: Optional[List[dict]] = None,
            collected_at: Optional[str] = None) -> dict:
    """Aggregate PR metrics for PRs created in [since, until]. Output holds no logins."""
    override_by_pr = _validate_overrides(overrides or [])
    rows = []
    for pr in prs:
        if not _in_window(pr, since, until):
            continue
        number = int(pr["number"])
        auto = review_rounds(pr.get("reviews") or [], _login(pr.get("author")))
        override = override_by_pr.get(number)
        rows.append({
            "number": number,
            "group": classify(pr, maintainer),
            "state": pr.get("state"),
            "merged": bool(pr.get("mergedAt")),
            "days_open": _days_open(pr),
            "changed_lines": int(pr.get("additions") or 0) + int(pr.get("deletions") or 0),
            "review_rounds_auto": auto,
            # Applied after the automatic count and replacing it, never added to it:
            # the override records the PR's whole review history.
            "review_rounds": override["rounds"] if override else auto,
            "rounds_overridden": override is not None,
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
        "collected_at": collected_at,
        "groups": groups,
        "prs": rows,
        "overridden_prs": [r["number"] for r in rows if r["rounds_overridden"]],
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
    overridden = ", ".join(f"#{n}" for n in result["overridden_prs"]) or "none"
    out = [
        f"# PR metrics baseline — {since} to {until}",
        "",
        "Generated by `tools/pr-metrics/collect.py`; do not edit by hand — rerun it.",
        "",
        f"- **Window:** PRs created between {since} and {until} (UTC, inclusive), "
        f"collected at {result.get('collected_at') or 'an unrecorded time'}. PRs still "
        "open at collection can gain reviews and lines or close later, so the same "
        "arguments run later give different numbers: compare against this snapshot, "
        "not a rerun.",
        "- **Method:** PR data from `gh pr list`, review lists from the GitHub reviews "
        "API per PR. A *review round* is a `CHANGES_REQUESTED` review, or a `COMMENTED` "
        f"review with a body of at least {REVIEW_ROUND_MIN_BODY} characters, by someone "
        "other than the PR's author and not a bot. *Days open* runs from creation to "
        "merge or close; still-open PRs are left out of that median only, and are "
        "included in the PR counts, changed lines and review rounds. *Changed lines* is "
        "additions + deletions. Bots are reported apart from external contributors.",
        "- **Reviews posted as conversation comments** are invisible to the reviews API "
        "and are counted only through the hand-kept `tools/pr-metrics/rounds_overrides.yaml`, "
        "whose count replaces the computed one for the PRs it lists. Overridden here: "
        f"{overridden}.",
        "- **Post-merge defects** come from `tools/pr-metrics/attributions.yaml` and are "
        "counted against the group of the PR that *introduced* the defect, not the one "
        "that fixed it. The attributions file started empty at this baseline and is "
        "filled as fixes land, so a zero below means \"none attributed yet\", not "
        "\"none exist\".",
        "- **Not measured:** the spec's *blocker findings per first-round review* "
        "(§5 C7). It needs each first-round review classified by hand; this tool does "
        "not compute it.",
        "- **Privacy:** keyed by PR number only; no author or reviewer is named.",
        "",
        "## Summary",
        "",
        "| Metric | " + " | ".join(GROUPS) + " |",
        "|---|" + "---:|" * len(GROUPS),
    ]
    metrics = [
        ("PRs created", "pr_count"),
        ("Merged", "merged_count"),
        ("Still open at collection", "open_count"),
        ("Median days open (closed PRs)", "median_days_open"),
        ("Median hours open (closed PRs)", "median_hours_open"),
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
        "traced to its inputs. *Review rounds* marked † come from "
        "`rounds_overrides.yaml`; the computed count is in brackets.",
        "",
    ]
    if external:
        out += ["| PR | State | Days open | Changed lines | Review rounds |",
                "|---:|---|---:|---:|---:|"]
        for r in external:
            days = None if r["days_open"] is None else round(r["days_open"], 2)
            rounds = (f"{r['review_rounds']} † ({r['review_rounds_auto']})"
                      if r["rounds_overridden"] else str(r["review_rounds"]))
            out.append(f"| #{r['number']} | {r['state']} | {_fmt(days)} | "
                       f"{r['changed_lines']} | {rounds} |")
    else:
        out.append("None in this window.")
    return "\n".join(out) + "\n"


def identities(prs: List[dict], extra: Iterable[str] = ()) -> Set[str]:
    """Every login and display name seen during collection — what the report must not hold."""
    found: Set[str] = set(extra)
    for pr in prs:
        author = pr.get("author") or {}
        found.update((author.get("login"), author.get("name")))
        for review in pr.get("reviews") or []:
            found.add(_review_login(review))
    return {v for v in found if v}


def leaks_identity(text: str, names: Iterable[str]) -> bool:
    for value in names:
        if re.search(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", text, re.IGNORECASE):
            return True
    return False


# --- I/O ------------------------------------------------------------------------------

def _gh(args: List[str]) -> str:
    proc = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {proc.stderr.strip()}")
    return proc.stdout


def fetch_prs(repo: str) -> List[dict]:
    prs = json.loads(_gh(["pr", "list", "--repo", repo, "--state", "all",
                          "--limit", str(PR_LIST_LIMIT), "--json", PR_LIST_FIELDS]))
    if len(prs) >= PR_LIST_LIMIT:
        # gh stops at the limit without saying so, newest first: the oldest PRs —
        # the start of the window — would silently fall out of the baseline.
        raise RuntimeError(f"gh pr list returned {len(prs)} PRs, the --limit; the "
                           "result may be truncated. Raise PR_LIST_LIMIT.")
    return prs


def fetch_reviews(repo: str, number: int) -> List[dict]:
    # --paginate on a list endpoint concatenates one JSON array per page; --jq '.[]'
    # flattens that to one object per line regardless of page count. login and type
    # are kept in memory only, to drop self-reviews and bots and to feed the leak guard.
    out = _gh(["api", f"repos/{repo}/pulls/{number}/reviews", "--paginate",
               "--jq", ".[] | {state, body, login: .user.login, type: .user.type}"])
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def _load_yaml_list(path: Path, what: str) -> List[dict]:
    # A missing or mistyped path must fail: silently reading it as empty would print
    # "None attributed yet" for defects that were attributed. An empty file is fine.
    if not path.is_file():
        raise FileNotFoundError(f"{what} file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a YAML list")
    return data


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", required=True, help="first creation date, YYYY-MM-DD")
    parser.add_argument("--until", required=True, help="last creation date, YYYY-MM-DD")
    parser.add_argument("--out", help="write the Markdown report here (default: stdout)")
    parser.add_argument("--repo", default=DEFAULT_REPO,
                        help="owner/name; explicit so a fork clone still measures upstream")
    parser.add_argument("--maintainer",
                        help="login classified as maintainer (default: the one owner in "
                             "--codeowners); never written to output")
    parser.add_argument("--codeowners", type=Path, default=DEFAULT_CODEOWNERS)
    parser.add_argument("--attributions", type=Path, default=DEFAULT_ATTRIBUTIONS)
    parser.add_argument("--rounds-overrides", type=Path, default=DEFAULT_OVERRIDES)
    args = parser.parse_args(argv)

    try:
        for value in (args.since, args.until):
            dt.date.fromisoformat(value)
        maintainer = args.maintainer
        if not maintainer:
            if not args.codeowners.is_file():
                raise FileNotFoundError(f"CODEOWNERS not found: {args.codeowners}; "
                                        "pass --maintainer")
            maintainer = maintainer_from_codeowners(
                args.codeowners.read_text(encoding="utf-8"))
        attributions = _load_yaml_list(args.attributions, "attributions")
        overrides = _load_yaml_list(args.rounds_overrides, "rounds overrides")
        collected_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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
                                       maintainer=maintainer, overrides=overrides,
                                       collected_at=collected_at))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if leaks_identity(text, identities(prs, [maintainer])):
        # Never name the login, not even here: stderr ends up in CI logs and transcripts.
        print("ERROR: a login or display name appears in the report; refusing to write it.",
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
