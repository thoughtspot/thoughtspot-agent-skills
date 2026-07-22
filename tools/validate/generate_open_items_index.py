#!/usr/bin/env python3
"""
generate_open_items_index.py — scan all open-items.md files and produce a
cross-skill index at docs/open-items-index.md.

Parses item headers in the format:
    ## #N — title — STATUS [needs: tag]
    ### #N — title — STATUS [needs: tag]

The [needs: ...] tag is optional. STATUS is the first recognised keyword after
the last em-dash in the header.

Usage:
    python tools/validate/generate_open_items_index.py
    python tools/validate/generate_open_items_index.py --root /path/to/repo
    python tools/validate/generate_open_items_index.py --check   # exit 1 if index is stale
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _dirs import ALL_RUNTIMES

# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------

# Canonical base statuses — the first keyword match wins.
# Order matters: longer/more-specific tokens must come before shorter ones
# so "SPEC-VERIFIED" matches before "VERIFIED", "NOT IMPLEMENTED" before
# "IMPLEMENTED", etc.
_STATUS_TOKENS = [
    "SPEC-VERIFIED",
    "VERIFIED",
    "FIXED",
    "RESOLVED",
    "CONFIRMED",
    "IMPLEMENTED",
    "PARTIALLY IMPLEMENTED",
    "NOT IMPLEMENTED",
    "PASS-THROUGH",
    "FOLLOW-ON",
    "UNVERIFIABLE",
    "UNVERIFIED",
    "UNTESTED",
    "DEFERRED",
    "PREMATURE",
    "WIRED",
    "PARTIAL",
    "OPEN",
    "TO VERIFY",
]

_STATUS_RE = re.compile(
    r"(?<![A-Za-z])(" + "|".join(re.escape(t) for t in _STATUS_TOKENS) + r")",
    re.IGNORECASE,
)

# [needs: live-ts, mcp-check]
_NEEDS_RE = re.compile(r"\[needs:\s*([^\]]+)\]", re.IGNORECASE)

# Item header: ## #N — title — STATUS  or  ### #N — title — STATUS
# Also handles: ## Item N — title — STATUS
_HEADER_RE = re.compile(
    r"^(#{2,3})\s+#?\s*(?:Item\s+)?(\d+)\s*—\s*(.+)", re.MULTILINE
)

# Resolved statuses — items with these don't appear in the "open" section
_RESOLVED = frozenset({
    "VERIFIED", "SPEC-VERIFIED", "FIXED", "RESOLVED", "CONFIRMED",
    "IMPLEMENTED", "PASS-THROUGH", "FOLLOW-ON", "UNVERIFIABLE",
})

# Deferred/parked — separate bucket
_DEFERRED = frozenset({"DEFERRED", "PREMATURE"})


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _split_title_and_status(raw: str) -> tuple[str, str]:
    """Split a header tail into (title, status_portion).

    The status is everything after the LAST em-dash. This prevents status
    words in the title (e.g. "Verified TS growth formula — OPEN") from
    being misclassified.
    """
    parts = raw.split("—")
    if len(parts) >= 2:
        return parts[0].strip(), "—".join(parts[1:])
    return raw.strip(), ""


def _normalise_status(raw: str) -> str:
    """Extract the canonical base status from a raw header tail."""
    _, status_portion = _split_title_and_status(raw)
    m = _STATUS_RE.search(status_portion)
    if m:
        return m.group(1).upper()
    # Fallback: search the whole string if no em-dash separation
    m = _STATUS_RE.search(raw)
    return m.group(1).upper() if m else "OPEN"


def _extract_needs(raw: str) -> list[str]:
    """Extract [needs: ...] tags from a header."""
    m = _NEEDS_RE.search(raw)
    if not m:
        return []
    return [t.strip() for t in m.group(1).split(",") if t.strip()]


def _extract_title(raw: str) -> str:
    """Extract the title portion (before the status) from the header tail."""
    title, _ = _split_title_and_status(raw)
    return title


_STATUS_PRIORITY = {s: i for i, s in enumerate(_RESOLVED)}
_STATUS_PRIORITY.update({s: len(_RESOLVED) for s in _DEFERRED})


def _more_resolved(a: str, b: str) -> str:
    """Return whichever status is 'more resolved' (prefer VERIFIED over OPEN)."""
    pa = _STATUS_PRIORITY.get(a, 999)
    pb = _STATUS_PRIORITY.get(b, 999)
    return a if pa < pb else b


def parse_open_items(path: Path) -> list[dict]:
    """Parse an open-items.md file into a list of item dicts.

    Deduplicates by item number — some files have historical OPEN text
    alongside a VERIFIED copy. The most-resolved status wins.
    """
    content = path.read_text(encoding="utf-8")
    by_num: dict[int, dict] = {}
    matches = list(_HEADER_RE.finditer(content))

    for i, m in enumerate(matches):
        num = int(m.group(2))
        tail = m.group(3)
        title = _extract_title(tail)
        status = _normalise_status(tail)
        needs = _extract_needs(tail)

        if "(historical" in tail.lower():
            continue

        entry = {
            "num": num,
            "title": title,
            "status": status,
            "needs": needs,
            "raw_header": m.group(0).strip(),
        }

        if num in by_num:
            existing = by_num[num]
            winner = _more_resolved(existing["status"], status)
            if winner == status:
                by_num[num] = entry
        else:
            by_num[num] = entry

    return list(by_num.values())


def skill_from_path(path: Path, repo_root: Path) -> str:
    """Extract the skill name from an open-items.md path."""
    rel = path.relative_to(repo_root)
    # agents/cli/ts-foo/references/open-items.md → ts-foo
    parts = rel.parts
    for i, p in enumerate(parts):
        if p.startswith("ts-"):
            return p
    return parts[2] if len(parts) > 2 else str(rel)


# ---------------------------------------------------------------------------
# Index generation
# ---------------------------------------------------------------------------

def generate_index(repo_root: Path) -> str:
    """Generate the markdown index content."""
    files: list[Path] = []
    for runtime in ALL_RUNTIMES:
        files += sorted(
            repo_root.glob(f"agents/{runtime}/*/references/open-items.md")
        )

    # Deduplicate by skill name (same skill might appear in cli + coco)
    seen_skills: set[str] = set()
    unique_files: list[tuple[str, Path]] = []
    for f in files:
        skill = skill_from_path(f, repo_root)
        if skill not in seen_skills:
            seen_skills.add(skill)
            unique_files.append((skill, f))

    all_items: list[dict] = []
    skill_summaries: list[dict] = []

    for skill, path in unique_files:
        items = parse_open_items(path)
        for item in items:
            item["skill"] = skill
            item["path"] = str(path.relative_to(repo_root))
        all_items.extend(items)

        total = len(items)
        open_count = sum(
            1 for it in items
            if it["status"] not in _RESOLVED and it["status"] not in _DEFERRED
        )
        verified_count = sum(1 for it in items if it["status"] in _RESOLVED)
        deferred_count = sum(1 for it in items if it["status"] in _DEFERRED)

        skill_summaries.append({
            "skill": skill,
            "total": total,
            "open": open_count,
            "verified": verified_count,
            "deferred": deferred_count,
        })

    # Sort summaries: most open items first
    skill_summaries.sort(key=lambda s: (-s["open"], s["skill"]))

    open_items = [
        it for it in all_items
        if it["status"] not in _RESOLVED and it["status"] not in _DEFERRED
    ]

    # Group open items by needs tag
    by_needs: dict[str, list[dict]] = {}
    untagged: list[dict] = []
    for it in open_items:
        if it["needs"]:
            for tag in it["needs"]:
                by_needs.setdefault(tag, []).append(it)
        else:
            untagged.append(it)

    # Build markdown
    lines = [
        "# Open Items Index",
        "",
        "Auto-generated by `tools/validate/generate_open_items_index.py`.",
        "Re-run to refresh: `python3 tools/validate/generate_open_items_index.py`",
        "",
        "## Summary",
        "",
        f"**{len(all_items)} total items** across {len(unique_files)} skills — "
        f"**{len(open_items)} open**, "
        f"{sum(s['verified'] for s in skill_summaries)} verified, "
        f"{sum(s['deferred'] for s in skill_summaries)} deferred",
        "",
        "| Skill | Total | Open | Verified | Deferred |",
        "|---|---|---|---|---|",
    ]

    for s in skill_summaries:
        lines.append(
            f"| {s['skill']} | {s['total']} | **{s['open']}** | "
            f"{s['verified']} | {s['deferred']} |"
        )

    if by_needs:
        lines.append("")
        lines.append("## Open items by blocker")
        lines.append("")

        for tag in sorted(by_needs):
            items_for_tag = by_needs[tag]
            lines.append(f"### `{tag}` ({len(items_for_tag)} items)")
            lines.append("")
            lines.append("| Skill | # | Title | Status |")
            lines.append("|---|---|---|---|")
            for it in sorted(items_for_tag, key=lambda x: (x["skill"], x["num"])):
                lines.append(
                    f"| {it['skill']} | #{it['num']} | {it['title']} | {it['status']} |"
                )
            lines.append("")

    if untagged:
        lines.append("### Untagged ({} items)".format(len(untagged)))
        lines.append("")
        lines.append("Items without a `[needs: ...]` tag. Consider adding one to enable "
                      "batch triage.")
        lines.append("")
        lines.append("| Skill | # | Title | Status |")
        lines.append("|---|---|---|---|")
        for it in sorted(untagged, key=lambda x: (x["skill"], x["num"])):
            lines.append(
                f"| {it['skill']} | #{it['num']} | {it['title']} | {it['status']} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate cross-skill open-items index."
    )
    parser.add_argument("--root", default=".", help="Repo root")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if the index is up to date; exit 1 if stale.",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    index_path = repo_root / "docs" / "open-items-index.md"
    new_content = generate_index(repo_root)

    if args.check:
        if not index_path.exists():
            print("FAIL  docs/open-items-index.md does not exist. "
                  "Run: python3 tools/validate/generate_open_items_index.py")
            return 1
        existing = index_path.read_text(encoding="utf-8")
        if existing != new_content:
            print("FAIL  docs/open-items-index.md is stale. "
                  "Run: python3 tools/validate/generate_open_items_index.py")
            return 1
        print("PASS  docs/open-items-index.md is up to date")
        return 0

    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(new_content, encoding="utf-8")
    print(f"Generated {index_path.relative_to(repo_root)} "
          f"({sum(1 for line in new_content.splitlines() if line.startswith('|'))} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
