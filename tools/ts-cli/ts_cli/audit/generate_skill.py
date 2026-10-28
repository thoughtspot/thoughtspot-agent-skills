"""The ts-audit skill's catalog-derived sections, generated from the rule catalog.

`agents/cli/ts-audit/SKILL.md` used to restate the categories, the assessment profiles'
bars and which rule ids each catalog file holds — by hand, so a rule change had to
remember to edit it and usually did not. Each of those sections is now a named block::

    <!-- BEGIN GENERATED: categories-table -->
    ...
    <!-- END GENERATED: categories-table -->

rendered here and checked by `python -m ts_cli.audit.generate --check` (and so by the
catalog gate), exactly like check-catalog.md's rule tables. Gate-safe: imports only the
catalog modules and generate's text helpers.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, Iterable, List

from ts_cli.audit.catalog_model import Catalog, Rule, profile_override

#: Block name -> what it holds. Every name must appear in SKILL.md exactly once.
SKILL_BLOCKS = {
    "categories-table": "the category table near the top",
    "angles-overview": "Step 0's list of categories",
    "angles-select": "Step 2a's category prompt",
    "profiles": "Step 2b's profile prompt and what each profile changes",
    "rules-files": "Step 4's table of catalog files and the rule ids they hold",
}

_NOTE = ("<!-- Generated from tools/ts-cli/ts_cli/audit/catalog/ by "
         "`python -m ts_cli.audit.generate`; do not edit by hand. -->")


def _begin(name: str) -> str:
    return f"<!-- BEGIN GENERATED: {name} -->"


def _end(name: str) -> str:
    return f"<!-- END GENERATED: {name} -->"


def render_named_blocks(doc: str, blocks: Dict[str, str]) -> str:
    """`doc` with each named block's content replaced; ValueError naming any block whose
    markers are missing, repeated or out of order (a second copy would never be checked)."""
    for name, body in blocks.items():
        counts = (doc.count(_begin(name)), doc.count(_end(name)))
        if counts != (1, 1) and counts != (0, 0):
            raise ValueError(f"the GENERATED block '{name}' must appear exactly once "
                             f"(found {counts[0]} BEGIN and {counts[1]} END markers)")
        b, e = doc.find(_begin(name)), doc.find(_end(name))
        if b < 0 or e < b:
            raise ValueError(f"the GENERATED block '{name}' is missing its markers")
        doc = doc[:b + len(_begin(name))] + "\n" + body.rstrip("\n") + "\n" + doc[e:]
    return doc


def _id_key(rid: str):
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", rid)
    return (m.group(1), int(m.group(2))) if m else (rid, 0)


def id_ranges(ids: Iterable[str]) -> str:
    """`["A1", "A2", "A3", "A6"]` -> "A1–A3, A6"; "—" for none."""
    keys = sorted((_id_key(i) for i in ids))
    if not keys:
        return "—"
    runs: List[List] = []
    for prefix, n in keys:
        if runs and runs[-1][0] == prefix and runs[-1][2] == n - 1:
            runs[-1][2] = n
        else:
            runs.append([prefix, n, n])
    return ", ".join(f"{p}{a}" if a == b else f"{p}{a}–{p}{b}" for p, a, b in runs)


def _categories_table(cat: Catalog) -> str:
    rows = ["| Code | Angle | What it finds |", "|---|---|---|"]
    rows += [f"| **{c.id}** | {c.label} | {c.description.rstrip('.')} |"
             for c in cat.categories.values()]
    return "\n".join([_NOTE, ""] + rows)


def _angle_lines(cat: Catalog, describe: bool) -> List[str]:
    width = max(len(c.label) for c in cat.categories.values()) + 4
    lines = []
    for c in cat.categories.values():
        if describe:
            lines.append(f"  {c.id}  {(c.label + ' ').ljust(width, '.')} "
                         f"{c.description.rstrip('.')}")
        else:
            lines.append(f"  {c.id}  {c.label}")
    ids = ", ".join(cat.categories)
    return lines + ["", f"  X  All angles ({ids})"]


def _angles_overview(cat: Catalog) -> str:
    return "\n".join(_angle_lines(cat, describe=True))


def _angles_select(cat: Catalog) -> str:
    body = (["```", "Which angles would you like to audit?", ""] + _angle_lines(cat, False)
            + ["", 'Enter letters (e.g. "A,D,S" or "X"):', "```"])
    return "\n".join(body)


def _profile_rules(cat: Catalog) -> List[Rule]:
    return [r for r in cat.rules.values() if r.status == "active" and r.profiles]


def _profiles(cat: Catalog) -> str:
    from ts_cli.audit.generate import per_profile

    choices = list(cat.profiles.values())
    menu = ["```", "Assessment profile — sets pass/fail thresholds:", ""]
    width = max(len(p.label) + (10 if p.default else 0) for p in choices) + 2
    menu += [f"  {i}. {(p.label + (' (default)' if p.default else '')).ljust(width)}"
             f"{'— ' + p.description if p.description else ''}".rstrip()
             for i, p in enumerate(choices, 1)]
    menu += ["", f"Enter {' or '.join(str(i) for i in range(1, len(choices) + 1))}:", "```"]
    flags = " or ".join(f"`--assessment {p.id}` ({i})" for i, p in enumerate(choices, 1))
    lines = [_NOTE, ""] + menu + ["", f"Pass the choice to `ts audit run` as {flags} in "
                                       "Step 4. What the profile changes:", ""]
    for rule in _profile_rules(cat):
        lines.append(f"- **{rule.id} — {rule.title}:** "
                     f"{per_profile(cat, lambda pid, r=rule: _graded(r, pid))}")
    return "\n".join(lines)


def _graded(rule: Rule, pid: str) -> str:
    """The profile's grading, marked provisional when that profile's own message says its
    lines are (P8's Spotter-ready lines: no measurement sets them yet)."""
    from ts_cli.audit.generate import grading

    text = grading(rule, pid)
    message = str(profile_override(rule, pid).get("message") or "")
    return f"{text} (provisional)" if "provisional" in message.lower() else text


def _rules_files(cat: Catalog) -> str:
    by_file: Dict[str, Dict[str, List[str]]] = {}
    for rule in cat.rules.values():
        entry = by_file.setdefault(rule.source_file, {"active": [], "retired": [],
                                                      "cats": []})
        entry["active" if rule.status == "active" else "retired"].append(rule.id)
        entry["cats"].append(rule.categories[0] if rule.categories else "")
    rows = ["| Catalog file | Category | Rules |", "|---|---|---|"]
    for path in sorted(by_file, key=lambda p: min(
            (cat.categories[c].order for c in by_file[p]["cats"] if c in cat.categories),
            default=99)):
        entry = by_file[path]
        cid = max(set(entry["cats"]), key=entry["cats"].count)
        label = cat.categories[cid].label if cid in cat.categories else cid
        retired = f" ({id_ranges(entry['retired'])} retired)" if entry["retired"] else ""
        rows.append(f"| `{_rules_rel(path)}` | {cid} — {label} | "
                    f"{id_ranges(entry['active'])}{retired} |")
    return "\n".join([_NOTE, ""] + rows)


def _rules_rel(source_file: str) -> str:
    """`.../catalog/rules/ai.yaml` -> `rules/ai.yaml`."""
    parts = str(source_file).replace("\\", "/").split("/")
    return "/".join(parts[parts.index("rules"):]) if "rules" in parts else source_file


_BUILDERS: Dict[str, Callable[[Catalog], str]] = {
    "categories-table": _categories_table,
    "angles-overview": _angles_overview,
    "angles-select": _angles_select,
    "profiles": _profiles,
    "rules-files": _rules_files,
}


def skill_blocks(cat: Catalog) -> Dict[str, str]:
    """Every SKILL_BLOCKS entry rendered from `cat`."""
    return {name: _BUILDERS[name](cat) for name in SKILL_BLOCKS}
