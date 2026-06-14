#!/usr/bin/env python3
"""Validate that mirror skills' synced-from markers match their CLI source version.

Mirrors with no marker → FAIL.
Mirrors behind their CLI source with no SYNC-DEBT acknowledgment → FAIL.
Mirrors behind their CLI source with a SYNC-DEBT row → WARN.
Mirrors at or ahead of their CLI source → PASS.

Exit 0 if all PASS/WARN. Exit 1 on any FAIL.
Use --report to print the full gap table without failing.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Skills that exist only in one runtime with no CLI/claude source to sync from
COCO_ONLY = {"ts-setup-sv"}

MARKER_RE = re.compile(
    r"<!--\s*synced-from:\s*(\S+)\s*@\s*v([\d.]+)\s"
)

VERSION_RE = re.compile(
    r"^\|\s*([\d]+\.[\d]+\.[\d]+)\s*\|"
)


def parse_version(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def top_changelog_version(path: Path):
    """Extract the first semver from the changelog table."""
    text = path.read_text()
    for line in text.splitlines():
        m = VERSION_RE.match(line)
        if m:
            return m.group(1)
    return None


def parse_marker(path: Path):
    """Return (source_path, version) from synced-from marker, or None."""
    text = path.read_text()
    m = MARKER_RE.search(text)
    if m:
        return m.group(1), m.group(2)
    return None


def load_sync_debt() -> set[str]:
    """Return set of mirror paths acknowledged in SYNC-DEBT.md."""
    debt_file = ROOT / "agents" / "SYNC-DEBT.md"
    if not debt_file.exists():
        return set()
    paths = set()
    for line in debt_file.read_text().splitlines():
        if line.startswith("|") and "/" in line:
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 2 and cells[1].startswith("agents/"):
                paths.add(cells[1])
    return paths


def discover_mirrors() -> list[Path]:
    """Find all mirror files (CoCo SKILL.md)."""
    mirrors = []
    for p in sorted((ROOT / "agents/coco-snowsight").glob("*/SKILL.md")):
        mirrors.append(p)
    return mirrors


def check():
    mirrors = discover_mirrors()
    debt = load_sync_debt()
    report_mode = "--report" in sys.argv

    results = []
    fails = 0

    for mirror in mirrors:
        rel = str(mirror.relative_to(ROOT))
        skill_name = mirror.parent.name

        if skill_name in COCO_ONLY:
            results.append(("SKIP", rel, "runtime-only skill (no CLI source)"))
            continue

        marker = parse_marker(mirror)

        if marker is None:
            results.append(("FAIL", rel, "no synced-from marker"))
            fails += 1
            continue

        source_path, marker_ver = marker
        source_file = ROOT / source_path
        if not source_file.exists():
            results.append(("FAIL", rel, f"source {source_path} not found"))
            fails += 1
            continue

        cli_ver = top_changelog_version(source_file)
        if cli_ver is None:
            results.append(("WARN", rel, f"source {source_path} has no semver changelog"))
            continue

        if parse_version(marker_ver) >= parse_version(cli_ver):
            results.append(("PASS", rel, f"v{marker_ver} >= v{cli_ver}"))
        elif rel in debt:
            results.append(("WARN", rel, f"v{marker_ver} < v{cli_ver} (acknowledged in SYNC-DEBT)"))
        else:
            results.append(("FAIL", rel, f"v{marker_ver} < v{cli_ver} with no SYNC-DEBT acknowledgment"))
            fails += 1

    if report_mode:
        print("Mirror sync report:")
        for status, path, detail in results:
            print(f"  {status:4s}  {path}")
            print(f"        {detail}")
        return 0

    for status, path, detail in results:
        if status == "FAIL":
            print(f"FAIL {path}: {detail}")
        elif status == "WARN":
            print(f"WARN {path}: {detail}")

    if fails:
        print(f"\n{fails} mirror(s) behind with no SYNC-DEBT acknowledgment")
        return 1

    print("PASS mirror sync")
    return 0


if __name__ == "__main__":
    sys.exit(check())
