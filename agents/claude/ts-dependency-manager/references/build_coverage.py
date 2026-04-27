#!/usr/bin/env python3
"""Generate the skill's coverage summary from dependency-types.md and open-items.md.

Two outputs:
  --summary        compact 3-line coverage line for Step 0 (before user confirms mode)
  --scan-coverage  the full Scan Coverage block for the Step 5 impact report

Both come from a single source of truth — section A's "Status" column in
dependency-types.md, with cross-checks against open-items.md statuses.

Why this exists: the previous hardcoded Scan Coverage block in SKILL.md drifted
out of sync as open items were verified. Driving the block from the canonical
files removes the duplication. When a status changes, update only
dependency-types.md / open-items.md — the skill output follows.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REFERENCES_DIR = Path(__file__).resolve().parent
DEP_TYPES_PATH = REFERENCES_DIR / "dependency-types.md"
OPEN_ITEMS_PATH = REFERENCES_DIR / "open-items.md"

# Map a status (the leading keyword of the Status column) to a coverage bucket.
# Buckets ordered by priority for the user — what they can rely on first,
# then partials, then anything that needs manual review.
STATUS_TO_BUCKET = {
    "Implementable": "auto",          # discovered + actionable in the skill
    "GUID-stable":   "no_action",     # nothing for the skill to do
    "Informational": "informational", # surfaced but never modified
    "Partial":       "partial",       # structure known, retrieval gap or work-in-progress
    "Manual":        "manual",        # cannot be programmatically discovered
}


def _parse_section_a(md: str) -> list[dict]:
    """Extract rows from the status table in section A of dependency-types.md.

    The table has 9 columns; we keep just (#, name, status_keyword, full_status).
    """
    # Find section A and the table within it
    section_a_match = re.search(
        r"## A\. Dependency-type status[^\n]*\n(.*?)(?=\n## )",
        md, re.DOTALL,
    )
    if not section_a_match:
        raise SystemExit("dependency-types.md: section A not found")
    section = section_a_match.group(1)

    rows = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]  # trim leading/trailing empties
        if len(cells) < 9:
            continue
        # Skip header and divider rows
        if cells[0] in ("#", ""):
            continue
        if cells[0].startswith("---") or set(cells[0]) <= set("-"):
            continue
        # Idx, Name (with bolds), ..., Status (last col)
        idx_text = cells[0]
        if not idx_text.isdigit():
            continue
        name = re.sub(r"^\*\*|\*\*$", "", cells[1].split("**")[1] if "**" in cells[1] else cells[1])
        # Strip emphasis from "**Model / Worksheet**"
        name = re.sub(r"\*+", "", name).strip()
        full_status = cells[-1].strip()
        # Leading keyword — first word, but "GUID-stable" is hyphenated
        kw_match = re.match(r"(GUID-stable|[A-Z][A-Za-z]+)", full_status)
        kw = kw_match.group(1) if kw_match else "Manual"
        rows.append({
            "idx":         int(idx_text),
            "name":        name,
            "status_kw":   kw,
            "status_full": full_status,
            "bucket":      STATUS_TO_BUCKET.get(kw, "manual"),
        })
    return rows


def _parse_open_items_status(md: str) -> dict[int, str]:
    """Parse the status keyword from each '## #N — ... — STATUS' header.
    Returns {item_number: short_status_label}.
    """
    out = {}
    for m in re.finditer(r"^## #(\d+)\s+—\s+.+?\s+—\s+(.+?)$", md, re.MULTILINE):
        num = int(m.group(1))
        rest = m.group(2).strip()
        # Take just the leading keyword(s) — VERIFIED / CONFIRMED / OPEN / DEFERRED / etc.
        # plus optional date qualifier
        out[num] = rest
    return out


def _format_summary(rows: list[dict]) -> str:
    """3-line summary for Step 0."""
    auto = [r["name"] for r in rows if r["bucket"] == "auto"]
    partial = [r["name"] for r in rows if r["bucket"] == "partial"]
    manual = [r["name"] for r in rows if r["bucket"] == "manual"]
    info = [r["name"] for r in rows if r["bucket"] == "informational"]
    no_action = [r["name"] for r in rows if r["bucket"] == "no_action"]

    def _join(xs: list[str]) -> str:
        return ", ".join(xs) if xs else "none"

    lines = []
    lines.append(f"Coverage:  auto-detected ({len(auto)}): {_join(auto)}")
    if partial:
        lines.append(f"           partial ({len(partial)}): {_join(partial)}")
    if manual:
        lines.append(f"           manual review ({len(manual)}): {_join(manual)}")
    if info or no_action:
        extras = []
        if info:
            extras.append(f"informational ({len(info)}): {_join(info)}")
        if no_action:
            extras.append(f"no skill action ({len(no_action)}): {_join(no_action)}")
        lines.append("           " + " | ".join(extras))
    lines.append("           Full breakdown in references/dependency-types.md")
    return "\n".join(lines)


def _format_scan_coverage(rows: list[dict], oi_statuses: dict[int, str]) -> str:
    """Full Scan Coverage block for Step 5 — designed to be pasted into the
    impact report verbatim. Counts of FOUND items are filled in by the skill at
    runtime (placeholders {found_X} match Python str.format keys).
    """

    # --- CHECKED block — discoverable types we actively scan ---
    checked_lines = []
    for r in rows:
        if r["bucket"] not in ("auto", "partial", "no_action", "informational"):
            continue
        # Map the dep-type name to a count placeholder name
        slug = re.sub(r"[^a-z0-9]+", "_", r["name"].lower()).strip("_")
        placeholder = "{found_" + slug + "}"
        # Suffix annotations
        suffix = ""
        if r["bucket"] == "partial":
            suffix = "  ⚠ partial — see notes below"
        elif r["bucket"] == "no_action":
            suffix = "  (no skill action — GUID-stable)"
        elif r["bucket"] == "informational":
            suffix = "  (informational only)"
        checked_lines.append(f"  {r['name']:30}  {placeholder:>8}{suffix}")

    # --- NOT CHECKED block — types we cannot detect on this build ---
    notcheck_lines = []
    for r in rows:
        if r["bucket"] != "manual":
            notcheck_lines.append(None)
        else:
            notcheck_lines.append(f"  {r['name']:30}  —    cannot detect on this build — manual review")
    notcheck_lines = [x for x in notcheck_lines if x]

    # --- partial-coverage notes — pull the open-item status for context ---
    partial_notes = []
    # Map each "Partial" row to its corresponding open-item number by inspecting
    # the status_full text (it usually mentions "open-item #N" or similar)
    for r in rows:
        if r["bucket"] != "partial":
            continue
        m = re.search(r"open-?item\s*#?(\d+)", r["status_full"], re.IGNORECASE)
        if m:
            num = int(m.group(1))
            oi = oi_statuses.get(num, "(status unknown)")
            partial_notes.append(f"  - {r['name']}: {r['status_full']} (open-item #{num}: {oi})")
        else:
            partial_notes.append(f"  - {r['name']}: {r['status_full']}")

    out = []
    out.append("─── SCAN COVERAGE ──────────────────────────────────────────────")
    out.append("")
    out.append("  Source of truth: agents/claude/ts-dependency-manager/references/dependency-types.md")
    out.append("  When a status changes, update that file — this block regenerates from it.")
    out.append("")
    out.append("  CHECKED                         FOUND")
    out.append("  ──────────────────────────────  ────────")
    out.extend(checked_lines)
    if notcheck_lines:
        out.append("")
        out.append("  NOT CHECKED — manual review recommended")
        out.append("  ──────────────────────────────────────────────────────────────")
        out.extend(notcheck_lines)
    if partial_notes:
        out.append("")
        out.append("  PARTIAL COVERAGE NOTES")
        out.append("  ──────────────────────────────────────────────────────────────")
        out.extend(partial_notes)
    out.append("")
    out.append("─────────────────────────────────────────────────────────────────")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true",
                        help="Emit the compact Step 0 summary")
    parser.add_argument("--scan-coverage", action="store_true",
                        help="Emit the full Step 5 Scan Coverage block")
    parser.add_argument("--list", action="store_true",
                        help="Emit JSON of parsed rows (for debugging / validators)")
    args = parser.parse_args()

    if not (args.summary or args.scan_coverage or args.list):
        parser.error("Must pick one of --summary, --scan-coverage, --list")

    md = DEP_TYPES_PATH.read_text()
    rows = _parse_section_a(md)
    oi_md = OPEN_ITEMS_PATH.read_text()
    oi_statuses = _parse_open_items_status(oi_md)

    if args.summary:
        print(_format_summary(rows))
    elif args.scan_coverage:
        print(_format_scan_coverage(rows, oi_statuses))
    elif args.list:
        import json
        print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
