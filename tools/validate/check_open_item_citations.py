#!/usr/bin/env python3
"""
check_open_item_citations.py — an `open-item #N` citation must resolve to a real item.

`check_open_items.py` grades the items themselves (UNTESTED findings, placeholder text,
`#N` novelty across branches). Nothing resolved a *reference* to one — so a citation
could name an item that does not exist, and stay silent indefinitely.

That is not hypothetical. The 2026-09-22 full audit (finding 5.3) found
`ts-dependency-manager/references/dependency-types.md` citing `open-item #10` at four
sites and `open-item #12` at one, in a file whose headings are #2,#3,#4,#9,#11,#13-#16,
#18,#20-#25. Neither item has ever existed. The citation is what a reader follows to
decide whether a CLI gap is real, so a dangling one does not merely rot — it makes a
stale "we cannot do this yet" look sourced. Two findings that sweep traced back to
exactly that (5.1 and 5.3).

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

#: `open-item #9`, `open items #12`, `open item #19` — case-insensitive.
CITATION_RE = re.compile(r"open[- ]items?\s+#(\d+)", re.IGNORECASE)

#: How far back to look for a skill name that redirects the citation elsewhere.
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


def skill_dirs(root: Path) -> list[Path]:
    out: list[Path] = []
    for runtime in ALL_RUNTIMES:
        base = root / agents_path(runtime)
        if base.is_dir():
            out.extend(d for d in sorted(base.iterdir()) if d.is_dir())
    return out


def owning_skill(text: str, pos: int, known: dict[str, Path]) -> str | None:
    """A skill named just before the citation redirects it to that skill's file."""
    window = text[max(0, pos - LOOKBACK): pos]
    hits = [(window.rfind(name), name) for name in known if name in window]
    hits = [(i, n) for i, n in hits if i >= 0]
    return max(hits)[1] if hits else None


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

        for m in CITATION_RE.finditer(procedure_body(text)):
            number = m.group(1)
            lineno = text.count("\n", 0, m.start()) + 1
            named = owning_skill(text, m.start(), known)

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

    if failures:
        print(f"\n{len(failures)} dangling open-item citation(s):\n")
        print("\n".join(failures))
        print()
        print("A citation is what a reader follows to decide whether a documented gap is")
        print("real. One that resolves to nothing makes a stale claim look sourced.")
        print("Fix the number, point at the right skill, or drop the citation — do not")
        print("create an item to satisfy a reference.")
        return 1

    print(f"All open-item citations resolve ({len(skills)} skill(s) scanned).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
