#!/usr/bin/env python3
"""
generate_readme_skills.py — generate README.md's skills tables from the `metadata:` block in each skill's SKILL.md frontmatter.

The tables used to be maintained by hand, and their counts drifted: the README
once said 32 skills while its tables held 36. Each skill's own SKILL.md is now the
source of truth for its README row:

    metadata:
      category: Conversion                       # one of CATEGORIES below
      summary: "Convert a ThoughtSpot model ..."  # the "What it does" cell, markdown allowed
      platform: Snowflake                        # Conversion only
      coverage: "references/coverage-matrix.md"  # Conversion only; relative to the skill dir, or none
      subcategory: Credentials                   # Setup only

A summary is moved verbatim from the README cell, markdown included, except that
its relative links are written from the skill's directory, as every link in a
SKILL.md is; the generator rebases them onto the repo root for the README.

This rewrites only the regions between paired markers in README.md, and leaves
everything else (the prose between the tables included) as written:

    <!-- BEGIN GENERATED: skills-total -->      the skill and category count in the intro sentence (inline)
    <!-- BEGIN GENERATED: skills-overview -->   the category overview table, with computed counts
    <!-- BEGIN GENERATED: skills-<category> --> one per category table (e.g. skills-semantic-authoring)

each closed by the matching `<!-- END GENERATED: <name> -->`.

Row order within a table is a sort, not stored data: Setup by subcategory then
skill name; Conversion by platform (to- before from-, non-converters such as
ts-link-semantic-layer last); every other table by skill name.

A summary or field containing `|` or a line break is refused, not escaped: either
would split the README table cell, and an escaped pipe has no spelling that is
valid in every YAML quoting style.

Usage:
    python3 tools/validate/generate_readme_skills.py              # rewrite README.md
    python3 tools/validate/generate_readme_skills.py --check      # exit 1 on drift or invalid metadata
    python3 tools/validate/generate_readme_skills.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import difflib
import posixpath
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from _dirs import runtime_globs

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install PyYAML")
    sys.exit(1)


@dataclass(frozen=True)
class Skill:
    name: str                 # the skill's directory name, which is its slash command
    rel_dir: str              # e.g. "agents/cli/ts-audit"
    meta: Dict[str, str]

    def get(self, key: str) -> str:
        return self.meta.get(key, "")


def _by_name(s: Skill) -> tuple:
    return (s.name,)


def _setup_order(s: Skill) -> tuple:
    return (s.get("subcategory").casefold(), s.name)


def _conversion_order(s: Skill) -> tuple:
    direction = 0 if s.name.startswith("ts-convert-to-") else 1
    return (not s.name.startswith("ts-convert-"), s.get("platform").casefold(), direction, s.name)


@dataclass(frozen=True)
class Category:
    name: str                              # the value `metadata.category` must hold
    anchor: str                            # the README's `<a id="...">`, linked from the overview
    problem: str                           # the overview's "Problem it solves" cell
    columns: Tuple[Tuple[str, str], ...]   # (header, metadata key) after the Skill column
    order: Callable[[Skill], tuple] = field(default=_by_name)

    @property
    def block(self) -> str:
        # No "--" in a marker: the anchor "platform--governance" would put one in
        # the HTML comment, which older CommonMark rejects in a comment.
        return "skills-" + "-".join(p for p in self.anchor.split("-") if p)

    @property
    def required(self) -> Tuple[str, ...]:
        """Every column's key is required; `summary` is in every table."""
        return tuple(key for _, key in self.columns)


_WHAT = ("What it does", "summary")

#: README order. Each category's columns keep that table's header wording.
CATEGORIES: Tuple[Category, ...] = (
    Category("Setup", "setup",
             "Nothing else runs until credentials and data exist",
             (_WHAT, ("Category", "subcategory")), _setup_order),
    Category("Conversion", "conversion",
             "The semantics already exist elsewhere, and rebuilding them by hand is what stalls a migration",
             (_WHAT, ("Platform", "platform"), ("Coverage", "coverage")), _conversion_order),
    Category("Semantic Authoring", "semantic-authoring",
             "A Model that imports cleanly can still answer badly or run slowly",
             (_WHAT,)),
    Category("Platform & Governance", "platform--governance",
             "Many audiences, one definition, without a copy per tenant",
             (_WHAT,)),
    Category("Query", "query",
             "Getting data out programmatically, and seeing the SQL behind a disputed number",
             (_WHAT,)),
    Category("Recipes", "recipes",
             "The same analytical need recurs account after account",
             (("What it builds", "summary"),)),
)
_BY_NAME = {c.name: c for c in CATEGORIES}

#: `metadata.coverage` value for a Conversion skill with no coverage matrix.
NO_COVERAGE = "none"

OVERVIEW_BLOCK = "skills-overview"
TOTAL_BLOCK = "skills-total"
GENERATOR = "tools/validate/generate_readme_skills.py"
NOTE = (f"<!-- Generated from each skill's SKILL.md `metadata:` by "
        f"`python3 {GENERATOR}`; do not edit by hand. -->")

_NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven",
                 "eight", "nine", "ten", "eleven", "twelve")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---[ \t]*\n", re.DOTALL)
_LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")
_ABSOLUTE_TARGET = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|#|/)")


class ReadmeError(ValueError):
    """README.md cannot take the generated content (missing or repeated markers, a
    missing anchor)."""


# ---------------------------------------------------------------------------
# Loading and validating metadata
# ---------------------------------------------------------------------------

def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _field_errors(key: str, value: object) -> List[str]:
    if not isinstance(value, str):
        return [f"metadata.{key} must be a string, got {type(value).__name__}"]
    out = []
    if "|" in value:
        out.append(f"metadata.{key} contains '|', which would split the README table cell; "
                   "rephrase it (the generator refuses rather than escapes it)")
    if "\n" in value or "\r" in value:
        out.append(f"metadata.{key} contains a line break; a README table cell is one line")
    return out


def validate_meta(skill_dir: Path, meta: object) -> List[str]:
    """Problems with one skill's `metadata:` block, without the file prefix."""
    if not isinstance(meta, dict):
        return ["frontmatter has no `metadata:` mapping (needs at least category and summary)"]
    category = meta.get("category")
    if _blank(category):
        return [f"metadata.category is missing; set one of: {', '.join(_BY_NAME)}"]
    if not isinstance(category, str) or category not in _BY_NAME:
        return [f"metadata.category {category!r} is not one of: {', '.join(_BY_NAME)}"]
    errors: List[str] = []
    for key in _BY_NAME[category].required:
        value = meta.get(key)
        if _blank(value):
            extra = "" if key == "summary" else f" (required for category {category})"
            errors.append(f"metadata.{key} is missing{extra}")
            continue
        errors.extend(_field_errors(key, value))
        if key == "coverage" and isinstance(value, str) and value != NO_COVERAGE \
                and not (skill_dir / value).is_file():
            errors.append(f"metadata.coverage {value!r} is not a file under the skill's "
                          f"directory (use {NO_COVERAGE!r} if the skill has no coverage matrix)")
    return errors


def load_skills(root: Path) -> Tuple[List[Skill], List[str]]:
    """Every SKILL.md under the runtime dirs, and every problem found, each problem
    prefixed with the repo-relative path of the file it is in."""
    skills: List[Skill] = []
    errors: List[str] = []
    for path in sorted(runtime_globs(root, "*/SKILL.md")):
        rel = path.relative_to(root).as_posix()
        m = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
        if not m:
            errors.append(f"{rel}: no `---` frontmatter block at the top of the file")
            continue
        try:
            front = yaml.safe_load(m.group(1))
        except yaml.YAMLError as exc:
            first = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            errors.append(f"{rel}: frontmatter is not valid YAML: {first}")
            continue
        meta = front.get("metadata") if isinstance(front, dict) else None
        problems = validate_meta(path.parent, meta)
        if problems:
            errors.extend(f"{rel}: {p}" for p in problems)
            continue
        skills.append(Skill(path.parent.name, path.parent.relative_to(root).as_posix(),
                            {k: v for k, v in meta.items() if isinstance(v, str)}))
    return skills, errors


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def rebase_links(text: str, rel_dir: str) -> str:
    """Rewrite each relative markdown link target in `text` from the skill's
    directory onto the repo root, where README.md sits. A summary's links are
    written relative to its SKILL.md, like every other link in that file, so they
    resolve (and `check_references` checks them) where they are written. URLs,
    `#anchors` and root-absolute paths are left alone."""
    def sub(m: "re.Match[str]") -> str:
        target = m.group(1)
        if _ABSOLUTE_TARGET.match(target):
            return m.group(0)
        return f"]({posixpath.normpath(posixpath.join(rel_dir, target))})"
    return _LINK_TARGET.sub(sub, text)


def _cell(skill: Skill, key: str) -> str:
    value = skill.get(key)
    if key == "coverage":
        return "—" if value == NO_COVERAGE else f"[coverage]({skill.rel_dir}/{value})"
    return rebase_links(value, skill.rel_dir)


def render_category_table(category: Category, skills: Sequence[Skill]) -> str:
    headers = ["Skill"] + [h for h, _ in category.columns]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for s in sorted(skills, key=category.order):
        cells = [f"[`{s.name}`]({s.rel_dir}/SKILL.md)"] + [_cell(s, k) for _, k in category.columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_overview(counts: Dict[str, int]) -> str:
    lines = ["| Category | Problem it solves | Skills |", "|---|---|:-:|"]
    lines += [f"| [{c.name}](#{c.anchor}) | {c.problem} | {counts[c.name]} |" for c in CATEGORIES]
    return "\n".join(lines)


def render_total(total: int) -> str:
    n = len(CATEGORIES)
    word = _NUMBER_WORDS[n] if n < len(_NUMBER_WORDS) else str(n)
    return f"{total} skill{'' if total == 1 else 's'} across {word} categories"


def _replace_block(doc: str, name: str, body: str, inline: bool = False) -> str:
    begin, end = f"<!-- BEGIN GENERATED: {name} -->", f"<!-- END GENERATED: {name} -->"
    counts = (doc.count(begin), doc.count(end))
    if counts != (1, 1):
        raise ReadmeError(f"the GENERATED block '{name}' must appear exactly once "
                          f"(found {counts[0]} BEGIN and {counts[1]} END markers)")
    b, e = doc.index(begin) + len(begin), doc.index(end)
    if e < b:
        raise ReadmeError(f"the GENERATED block '{name}' has its END marker before its BEGIN")
    inner = body if inline else f"\n{NOTE}\n\n{body}\n\n"
    return doc[:b] + inner + doc[e:]


def render_readme(doc: str, skills: Sequence[Skill]) -> str:
    """`doc` with every generated block refreshed from `skills`."""
    by_cat: Dict[str, List[Skill]] = {c.name: [] for c in CATEGORIES}
    for s in skills:
        by_cat[s.get("category")].append(s)
    for c in CATEGORIES:
        if f'<a id="{c.anchor}"></a>' not in doc:
            raise ReadmeError(f'no <a id="{c.anchor}"></a> anchor for the {c.name} category, '
                              "which the overview table links to")
        doc = _replace_block(doc, c.block, render_category_table(c, by_cat[c.name]))
    doc = _replace_block(doc, OVERVIEW_BLOCK, render_overview({k: len(v) for k, v in by_cat.items()}))
    return _replace_block(doc, TOTAL_BLOCK, render_total(len(skills)), inline=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _diff_excerpt(old: str, new: str, limit: int = 40) -> str:
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                     "README.md (committed)", "README.md (generated)", lineterm=""))
    shown = diff[:limit]
    if len(diff) > limit:
        shown.append(f"... {len(diff) - limit} more diff lines")
    return "\n".join("    " + line for line in shown)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate README.md's skills tables from SKILL.md metadata.")
    parser.add_argument("--root", default=".", help="Repo root")
    parser.add_argument("--check", action="store_true",
                        help="Exit 1 if README.md is stale or any skill's metadata is invalid; write nothing.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    readme = root / "README.md"
    skills, errors = load_skills(root)
    if not readme.is_file():
        errors.append("README.md: not found")
    if errors:
        for e in errors:
            print(f"FAIL  {e}")
        print(f"\n{len(errors)} problem(s); README.md was not {'checked' if args.check else 'written'}.")
        return 1

    old = readme.read_text(encoding="utf-8")
    try:
        new = render_readme(old, skills)
    except ReadmeError as exc:
        print(f"FAIL  README.md: {exc}")
        return 1

    if args.check:
        if new != old:
            print(f"FAIL  README.md: the skills tables are stale. Run: python3 {GENERATOR}")
            print(_diff_excerpt(old, new))
            return 1
        print(f"PASS  README.md skills tables are up to date ({len(skills)} skills)")
        return 0

    if new == old:
        print(f"README.md skills tables already up to date ({len(skills)} skills)")
    else:
        readme.write_text(new, encoding="utf-8")
        print(f"Updated README.md skills tables ({len(skills)} skills)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
