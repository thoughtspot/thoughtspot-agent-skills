#!/usr/bin/env python3
"""
check_open_item_citations.py — an `open-item #N` citation must resolve to a real item.

`check_open_items.py` grades the items themselves (UNTESTED findings, placeholder text,
`#N` novelty across branches). Nothing resolved a *reference* to one — so a citation
could name an item that does not exist, and stay silent indefinitely.

That is not hypothetical, and the real shape is worse than "someone typed a wrong
number". `ts-dependency-manager/references/dependency-types.md` cited `#10` and `#12`,
which its `open-items.md` does not have. Both **did** exist and were deleted as
**resolved** — `2a25a6e` (2026-06-15) dropped #5/#10/#19/#22/#23/#24, and #10 read
"Column alias TML — VERIFIED 2026-06-01 via export_with_column_aliases beta flag". So
row 10's "retrieval mechanism unverified (open-item #10)" was not merely pointing at
nothing; it was pointing at an item that said the **opposite**, three months earlier.

That is the dominant failure mode: a resolved item is deleted and its inbound references
keep asserting the superseded state. PR #31 (2026-06-01) did the same to
`ts-object-model-coach`, trimming 17 items to 7 and leaving 31 references behind.

Rule: inside a skill directory, every `open-item #N` / `open items #N` / `open item #N`
citation must match an item heading in **that skill's** `references/open-items.md` —
unless the citation names a different skill, in which case it resolves against that
skill's file instead.

The heading pattern is imported from ``generate_open_items_index`` rather than
re-declared. `check_open_items.py` carries a comment explaining why: this module's
`_ITEM_HEADER` was once `##`-only while the generator accepted `##` and `###`, so one
file's twenty items were invisible to the gate. A third copy here would be a third
chance to drift.

Exit codes:
  0 — every citation resolves
  1 — at least one dangling citation, or a citation in a skill with no open-items.md

Run manually:
    python3 tools/validate/check_open_item_citations.py --root .
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dirs import ALL_RUNTIMES, agents_path  # noqa: E402
from generate_open_items_index import _HEADER_RE  # noqa: E402

#: `open-item #9`, `open items #12`, `open item #19`, `open-items.md #11`, and the
#: markdown-link form `[open-items.md #11](open-items.md)`. The `.md` spelling was
#: missed by the first cut of this regex, which required whitespace straight after
#: `items` — it hid 15 live dangling pointers in one skill.
CITATION_RE = re.compile(r"open[-_ ]items?(?:\.md)?\s*#(\d+)", re.IGNORECASE)

#: The bare markdown-link form: ``[#17](references/open-items.md)``. The link *path*
#: resolves, so ``check_references`` passes it while the item number points at nothing
#: — the most invisible spelling of this defect, and 10 sites of it hid in one skill.
LINK_CITATION_RE = re.compile(
    r"\[[^\]]*?#(\d+)[^\]]*?\]\([^)]*open[-_]items?\.md[^)]*\)", re.IGNORECASE)

#: How far either side of a citation to look for a skill name that redirects it.
#: Both directions: "see ts-x open-item #3" and "see open-item #3 in ts-x" are equally
#: natural, and a backward-only window scored the second as unqualified.
LOOKBACK = 120

SCANNED_SUFFIXES = {".md", ".py"}

#: A `## Changelog` section records history — a row saying "cited #4, which never
#: existed" is describing a fix, not pointing a reader at a live item. Scanning it
#: would make documenting one of these failures impossible without reintroducing it.
CHANGELOG_RE = re.compile(r"^##+\s+Changelog\s*$", re.MULTILINE)


def procedure_body(text: str) -> str:
    """Everything above `## Changelog` — the part whose citations are live pointers."""
    m = CHANGELOG_RE.search(text)
    return text[: m.start()] if m else text


def item_numbers(path: Path) -> set[str]:
    """Every `## #N` / `### #N` item number in one open-items.md."""
    try:
        return {m.group(2) for m in _HEADER_RE.finditer(path.read_text(encoding="utf-8"))}
    except OSError:
        return set()


def shared_files(root: Path) -> list[Path]:
    """Files under ``agents/shared/`` — no owning skill, so citations must name one."""
    base = root / "agents" / "shared"
    if not base.is_dir():
        return []
    return sorted(f for f in base.rglob("*")
                  if f.is_file() and f.suffix in SCANNED_SUFFIXES)


def check_shared(path: Path, root: Path, known: dict[str, Path]) -> list[str]:
    """A shared file is read by several skills, so an unqualified `#N` is ambiguous."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    body = procedure_body(text)
    raw = [(m.start(), m.group(1)) for m in CITATION_RE.finditer(body)]
    raw += [(m.start(), m.group(1)) for m in LINK_CITATION_RE.finditer(body)]
    problems: list[str] = []
    for start, number in sorted(set(raw)):
        lineno = body.count("\n", 0, start) + 1
        named = owning_skill(text, start, known)
        if named is None:
            problems.append(
                f"  ✗ {path.relative_to(root)}:{lineno}: cites open-item #{number} but "
                f"names no skill. A shared file has no owning open-items.md — write "
                f"\"<skill> open-item #{number}\" or state the finding inline.")
        elif number not in item_numbers(known[named] / "references" / "open-items.md"):
            problems.append(
                f"  ✗ {path.relative_to(root)}:{lineno}: {named} has no open-item #{number}")
    return problems


def skill_dirs(root: Path) -> list[Path]:
    out: list[Path] = []
    for runtime in ALL_RUNTIMES:
        base = root / agents_path(runtime)
        if base.is_dir():
            out.extend(d for d in sorted(base.iterdir()) if d.is_dir())
    return out


def owning_skill(text: str, pos: int, known: dict[str, Path]) -> str | None:
    """A skill named just before the citation redirects it to that skill's file."""
    before = text[max(0, pos - LOOKBACK): pos]
    after = text[pos: pos + LOOKBACK]
    # Nearest name wins, measured by distance from the citation in either direction.
    hits: list[tuple[int, str]] = []
    for name in known:
        i = before.rfind(name)
        if i >= 0:
            hits.append((len(before) - i, name))
        j = after.find(name)
        if j >= 0:
            hits.append((j, name))
    return min(hits)[1] if hits else None


def check_skill(skill: Path, root: Path, known: dict[str, Path]) -> list[str]:
    own_items_file = skill / "references" / "open-items.md"
    own_items = item_numbers(own_items_file) if own_items_file.is_file() else None

    problems: list[str] = []
    for path in sorted(skill.rglob("*")):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        if path == own_items_file:
            continue  # an item may legitimately cross-reference its neighbours
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        body = procedure_body(text)
        raw = [(m.start(), m.group(1)) for m in CITATION_RE.finditer(body)]
        raw += [(m.start(), m.group(1)) for m in LINK_CITATION_RE.finditer(body)]
        # `[open-items.md #12](…open-items.md)` matches BOTH patterns — one citation,
        # so dedupe on (line, item) rather than match offset, which differs per pattern.
        seen: dict[tuple[int, str], int] = {}
        for start, number in sorted(raw):
            key = (body.count("\n", 0, start) + 1, number)
            seen.setdefault(key, start)
        for (lineno, number), start in sorted(seen.items()):
            named = owning_skill(text, start, known)

            if named and named != skill.name:
                target = known[named] / "references" / "open-items.md"
                if not target.is_file():
                    problems.append(
                        f"  ✗ {path.relative_to(root)}:{lineno}: cites {named} "
                        f"open-item #{number}, but that skill has no open-items.md")
                elif number not in item_numbers(target):
                    problems.append(
                        f"  ✗ {path.relative_to(root)}:{lineno}: {named} has no "
                        f"open-item #{number}")
                continue

            if own_items is None:
                problems.append(
                    f"  ✗ {path.relative_to(root)}:{lineno}: cites open-item #{number}, "
                    f"but {skill.name} has no references/open-items.md")
            elif number not in own_items:
                have = ", ".join(f"#{n}" for n in sorted(own_items, key=int)) or "(none)"
                problems.append(
                    f"  ✗ {path.relative_to(root)}:{lineno}: open-item #{number} does "
                    f"not exist in {skill.name}. Items are: {have}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    skills = skill_dirs(root)
    if not skills:
        print(f"\nNo skill directories found under {root} — layout moved or --root wrong.")
        return 1

    known = {d.name: d for d in skills}
    failures: list[str] = []
    for skill in skills:
        failures.extend(check_skill(skill, root, known))
    # agents/shared/ has no owning skill, but the pre-commit trigger matches it — a
    # gate that runs on a file it never reads is the fail-open this rubric is about.
    shared = shared_files(root)
    for path in shared:
        failures.extend(check_shared(path, root, known))

    if failures:
        print(f"\n{len(failures)} dangling open-item citation(s):\n")
        print("\n".join(failures))
        print()
        print("A citation is what a reader follows to decide whether a documented gap is")
        print("real. One that resolves to nothing makes a stale claim look sourced.")
        print("Fix the number, point at the right skill, or drop the citation — do not")
        print("create an item to satisfy a reference.")
        return 1

    print(f"All open-item citations resolve "
          f"({len(skills)} skill(s) + {len(shared)} shared file(s) scanned).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
