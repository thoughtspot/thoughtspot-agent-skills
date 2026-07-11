#!/usr/bin/env python3
"""
check_audit_freshness.py — nudge when a repo audit is due (see .claude/rules/repo-audit.md).

Two cadences, surfaced as SOFT nudges (never blocks a commit):

  - External sweep (angles 13/14/16): due when the more recent of the latest
    docs/audit/*-external.md AND docs/audit/*-full.md report is older than
    EXTERNAL_MAX_AGE_DAYS. A full audit runs all angles (external ones included), so
    it is a superset of an external sweep and resets the external clock too — without
    this, every full audit leaves a stale external nudge firing until a separate
    external-only run happens.
  - Full deep audit (all angles): due on EITHER trigger —
      * time:     latest docs/audit/*-full.md older than FULL_MAX_AGE_DAYS, OR
      * activity: the audit surface grew since the last full audit (new skill, new
                  runtime, N+ new shared refs, or N+ commits). Measured from the
                  report's COMMIT (git log <report-sha>..HEAD), not its date, so the
                  audit's own same-day routing wave isn't counted as new drift.

It prints nothing when nothing is due, so it is safe to run on every commit / at
session start. A full audit is NEVER auto-run — many agents, human-routed findings —
this only tells you to run `Workflow({name:"repo-audit", args:{scope:"full"}})`.

Portability: the only repo-specific knobs are the CONFIG constants below. To reuse in
another repo, copy this file and adjust them — the date/age/activity logic is generic.

Usage:
    python3 tools/validate/check_audit_freshness.py --root .
    python3 tools/validate/check_audit_freshness.py --root . --check   # exit 1 if due
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

# ── CONFIG (repo-specific — the only part to change when porting) ─────────────
AUDIT_DIR = "docs/audit"
EXTERNAL_MAX_AGE_DAYS = 7
FULL_MAX_AGE_DAYS = 90
# Activity thresholds — any one trips the "consider a full audit" nudge.
# Each is a signal that the AUDIT SURFACE grew: new skills/runtimes/shared references
# are new things to check for consistency and currency; a high commit count is a proxy
# for "a lot changed". A ts-cli version bump is deliberately NOT here — the internal CLI
# version isn't audit surface (audits examine skills, mappings, product currency,
# security), bumps are too frequent to signal anything at a low threshold, and real
# churn they ride along with is already caught by `commits`.
ACTIVITY = {
    "new_skills": 1,       # a new SKILL.md in any runtime
    "new_runtimes": 1,     # a new agents/<runtime>/ tree
    "new_shared": 2,       # new agents/shared/ reference files
    "commits": 40,         # raw commit count since the last full audit
}
# ─────────────────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _report_dates(audit_dir: Path, kind: str) -> list[date]:
    """Dates parsed from docs/audit/YYYY-MM-DD-<kind>.md filenames."""
    dates: list[date] = []
    if not audit_dir.is_dir():
        return dates
    for f in audit_dir.glob(f"*-{kind}.md"):
        m = _DATE_RE.search(f.name)
        if m:
            try:
                dates.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            except ValueError:
                pass
    return sorted(dates)


def _age_days(d: date, today: date) -> int:
    return (today - d).days


def _is_due(latest: date | None, max_age: int, today: date) -> bool:
    """Due if there is no prior report, or the latest is older than max_age."""
    return latest is None or _age_days(latest, today) > max_age


def _effective_external_date(latest_ext: date | None, latest_full: date | None) -> date | None:
    """Date the external cadence measures from: the more recent of the last
    external-only sweep and the last full audit.

    A full audit runs ALL angles (the external ones included), so it is a superset
    of an external sweep and resets the external clock too. Returns None only when
    neither has ever run.
    """
    candidates = [d for d in (latest_ext, latest_full) if d is not None]
    return max(candidates) if candidates else None


def _git(args: list[str], root: Path) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=root)
    return r.stdout if r.returncode == 0 else ""


def _parse_activity(log_text: str) -> dict[str, int]:
    """Count substantive changes from `git log --name-status --pretty=format:%x00%H`.

    Commit boundaries are the NUL-prefixed header lines (used to count commits). Pure —
    no I/O — so the counting logic is unit-tested git-free. ts-cli version bumps are
    deliberately not counted (see the ACTIVITY comment — not audit surface).
    """
    new_skills = new_shared = commits = 0
    runtimes: set[str] = set()
    for line in log_text.splitlines():
        if line.startswith("\x00"):
            commits += 1
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0].strip(), parts[-1].strip()
        if status == "A" and path.endswith("/SKILL.md"):
            new_skills += 1
            seg = path.split("/")
            if len(seg) >= 2 and seg[0] == "agents":
                runtimes.add(seg[1])
        elif status == "A" and path.startswith("agents/shared/"):
            new_shared += 1
    return {
        "new_skills": new_skills,
        "new_runtimes": len(runtimes),
        "new_shared": new_shared,
        "commits": commits,
    }


def _latest_full_audit_commit(audit_dir: Path, root: Path) -> str | None:
    """SHA of the commit that ADDED the latest docs/audit/*-full.md report.

    This is the activity baseline — NOT the report's calendar date. A date baseline
    (`git log --since <date>`) wrongly counts everything committed on the report's day,
    including work that landed *before* the report and the audit's own same-day routing
    wave; measuring from the report's commit counts only what came strictly after it.
    Returns None if there is no report or git can't resolve the adding commit.
    """
    if not audit_dir.is_dir():
        return None
    full_files = sorted(audit_dir.glob("*-full.md"))  # YYYY-MM-DD names sort chronologically
    if not full_files:
        return None
    latest = full_files[-1]
    rel = latest.relative_to(root) if latest.is_absolute() else latest
    out = _git(["log", "--diff-filter=A", "--format=%H", "--", str(rel)], root)
    shas = [l for l in out.splitlines() if l.strip()]
    return shas[-1] if shas else None  # oldest add == the true creating commit


def _activity_since(since_ref: str | None, root: Path) -> dict[str, int]:
    """Count substantive changes in `since_ref`..HEAD (or all-time if None).

    `since_ref` is a commit SHA (see _latest_full_audit_commit), not a date.
    """
    rng = f"{since_ref}..HEAD" if since_ref else "HEAD"
    log_text = _git(["log", rng, "--name-status", "--pretty=format:%x00%H"], root)
    return _parse_activity(log_text)


def _activity_reasons(counts: dict[str, int]) -> list[str]:
    """Human-readable reasons for each threshold that was crossed."""
    labels = {
        "new_skills": "new skill(s)",
        "new_runtimes": "new runtime(s)",
        "new_shared": "new shared reference(s)",
        "commits": "commit(s)",
    }
    return [
        f"{counts[k]} {labels[k]}"
        for k in ACTIVITY
        if counts.get(k, 0) >= ACTIVITY[k]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Nudge when a repo audit is due.")
    parser.add_argument("--root", default=".", help="Repo root (default: cwd)")
    parser.add_argument(
        "--check", action="store_true",
        help="Exit 1 if any audit is due (default: warn-only, exit 0).",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    audit_dir = root / AUDIT_DIR
    today = datetime.now().date()

    nudges: list[str] = []

    ext_dates = _report_dates(audit_dir, "external")
    full_dates = _report_dates(audit_dir, "full")
    latest_ext = ext_dates[-1] if ext_dates else None
    latest_full = full_dates[-1] if full_dates else None

    # External sweep cadence. A full audit runs ALL angles — the external ones
    # (13 product-currency, 14 performance, 16 deps) included — so it is a superset
    # of an external-only sweep and satisfies the external cadence too. Take the more
    # recent of the two: otherwise every full audit leaves a stale "external sweep
    # due" nudge firing until a separate external-only run happens, which is exactly
    # the false nudge that showed "~13d overdue" the day after the 2026-07-11 full audit.
    latest_ext_effective = _effective_external_date(latest_ext, latest_full)
    if _is_due(latest_ext_effective, EXTERNAL_MAX_AGE_DAYS, today):
        age = f"{_age_days(latest_ext_effective, today)}d ago" if latest_ext_effective else "never run"
        nudges.append(
            f"External sweep due ({age}) — "
            'Workflow({name:"repo-audit", args:{scope:"external"}})'
        )

    # Full audit cadence: time OR activity
    time_due = _is_due(latest_full, FULL_MAX_AGE_DAYS, today)
    # Activity is measured from the report's COMMIT, not its date — the audit's own
    # same-day routing wave must not read as "substantial work since the audit".
    counts = _activity_since(_latest_full_audit_commit(audit_dir, root), root)
    reasons = _activity_reasons(counts)
    if time_due or reasons:
        if latest_full is None:
            why = "no full audit on record"
        elif time_due:
            why = f"last full audit {_age_days(latest_full, today)}d ago"
        else:
            why = "substantial work since last full audit: " + ", ".join(reasons)
        nudges.append(
            f"Full audit worth considering ({why}) — "
            'Workflow({name:"repo-audit", args:{scope:"full"}})'
        )

    if nudges:
        print("  Audit freshness:")
        for n in nudges:
            print(f"    • {n}")
        return 1 if args.check else 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
