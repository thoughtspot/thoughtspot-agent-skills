"""What is generated from the rule catalog: the human check catalog and the report's meta.

    catalog_markdown(cat) -> str   the per-rule tables of
                                   agents/cli/ts-audit/references/check-catalog.md,
                                   written between its BEGIN/END GENERATED markers
    report_meta(cat) -> dict       {"categories": [{id, label, order, angle_key,
                                   description}], "profiles": [{id, label, default}],
                                   "views": {view: [rule id, ...]},
                                   "checks": {rule id: {title, desc, thresholds, message,
                                   remediation, views, categories}}} — what the audit
                                   JSON's `check_meta` and the HTML report read, in place
                                   of the hand-written CHECK_META, recommendations and
                                   category labels

Every rule's grading is rendered as text, never as a data structure: a band list as
"HIGH < 25%, MEDIUM < 50%"; a severity map as "INFO when the column's table has
row-level security; otherwise HIGH"; a code rule that grades in code as its registered
label and the severities it declares; and a value that differs between profiles once
per profile ("Spotter-ready: … · General: …"). Generated text is read by audit readers,
so it never shows an engine identifier: a derived field is written as its registered
`label`, a code rule as its registration's `label`, never `@name` or `code:<name>`.
Messages and legacy threshold payloads in their per-severity form render one entry per
severity.

    python -m ts_cli.audit.generate [--root REPO] [--check]

writes the doc block, or with `--check` exits 1 when it is stale (the catalog gate,
tools/validate/check_audit_catalog.py, runs the same check).

Kept importable on Python 3.9 with only PyYAML: the catalog gate imports it without the
rest of ts_cli.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ts_cli.audit.catalog_code import CODE_IMPL, code_rule_declaration
from ts_cli.audit.catalog_forms import BY_SEVERITY
from ts_cli.audit.catalog_model import (
    CATALOG_DIR, Bands, Catalog, CatalogError, Rule, load_catalog, parse_bands,
    profile_override,
)

DOC_REL = Path("agents/cli/ts-audit/references/check-catalog.md")
#: The skill file whose catalog-derived sections are named GENERATED blocks
#: (ts_cli.audit.generate_skill). Checked when it exists: a catalog-only copy has none.
SKILL_REL = Path("agents/cli/ts-audit/SKILL.md")
CATALOG_REL = Path("tools/ts-cli/ts_cli/audit/catalog")
BEGIN = "<!-- BEGIN GENERATED -->"
END = "<!-- END GENERATED -->"
_OPS = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥", "eq": "="}
_UNITS = {"percent": "%"}
_SEP = " · "


# ── values as text ──────────────────────────────────────────────────────────

def _num(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return _num(value) if isinstance(value, (int, float)) else str(value)


def bands_text(bands: Any) -> str:
    """'HIGH < 25%, MEDIUM < 50%' — worst first, as the catalog orders them."""
    if not isinstance(bands, Bands):
        bands = parse_bands(bands, "", "")
    unit = _UNITS.get(bands.unit, "")
    return ", ".join(f"{lv.severity} {_OPS.get(lv.op, lv.op)} {_num(lv.value)}{unit}"
                     for lv in bands.levels)


def field_text(path: Any) -> str:
    """How a field path reads: a derived field's registered label ('@join_type' ->
    'the join type'), a TML path as words ('properties.column_type' -> 'the column
    type')."""
    path = str(path or "")
    if path.startswith("@"):
        from ts_cli.audit.engine.fields import FIELD_LABELS
        label = FIELD_LABELS.get(path[1:])
        if label:
            return label
        path = path[1:]
    words = [w for w in path.split(".") if w not in ("parent", "obj", "properties")]
    return "the " + " ".join(words).replace("_", " ")


def _case_text(sev: str, field: str, key: Any) -> str:
    if key is True:
        return f"{sev} when {field}"
    if key is False:
        return f"{sev} unless {field}"
    if key is None:
        return f"{sev} when {field} is absent"
    return f"{sev} when {field} is {_scalar(key)}"


def severity_text(severity: Any) -> str:
    """A fixed severity, or a map: 'HIGH when the join type is OUTER; otherwise INFO'."""
    if not isinstance(severity, dict):
        return str(severity)
    field = field_text(severity.get("field"))
    cases = [_case_text(sev, field, key) for key, sev in (severity.get("map") or {}).items()]
    return "; ".join(cases + [f"otherwise {severity.get('default')}"])


def mapping_text(value: Dict[str, Any]) -> str:
    """A legacy threshold payload: 'green=50, assessment=General, yellow=25'."""
    return ", ".join(f"{k}={_scalar(v)}" for k, v in value.items())


def _by_severity_text(value: Any, render) -> str:
    if isinstance(value, dict) and BY_SEVERITY in value:
        return "; ".join(f"{sev}: {render(v)}" for sev, v in value[BY_SEVERITY].items())
    return render(value)


# ── one rule under one profile ──────────────────────────────────────────────

def _code_name(rule: Rule) -> Optional[str]:
    m = CODE_IMPL.match(rule.implementation)
    return m.group(1) if m else None


def _code_label(name: str) -> str:
    from ts_cli.audit.engine.code_rules import CODE_LABELS
    return CODE_LABELS.get(name) or "graded in code"


def grading(rule: Rule, pid: str) -> str:
    """How `rule` grades a finding under profile `pid`, and the `parameters` it is
    tuned by there (`min_chars=20, ...`)."""
    params = profile_override(rule, pid).get("parameters", rule.parameters)
    text = _grading(rule, pid)
    return f"{text} · tuned by {mapping_text(params)}" if params else text


def _grading(rule: Rule, pid: str) -> str:
    override = profile_override(rule, pid)
    bands = override.get("bands", rule.bands)
    severity = override.get("severity", rule.severity)
    name = _code_name(rule)
    decl = code_rule_declaration(name) if name else None
    if decl is not None and isinstance(decl[0], frozenset):
        order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        return f"{_code_label(name)} — {', '.join(sorted(decl[0], key=order.index))}"
    if bands is not None and (decl is None or decl[0] == "bands"):
        return bands_text(bands)
    return severity_text(severity) if severity is not None else "—"


_DERIVED_PLACEHOLDER = re.compile(r"\{@([A-Za-z_]\w*)(?::([^{}]*))?\}")
_ITEM_PLACEHOLDER = re.compile(r"\{obj\.([^{}]+)\}")


def _placeholder_text(match: "re.Match") -> str:
    """`{@fact_tables:head3}` -> `{fact tables, first 3}`: a derived field's label (its
    leading article dropped), never its engine name."""
    label = re.sub(r"^the ", "", field_text("@" + match.group(1)))
    head = re.fullmatch(r"head(\d+)", match.group(2) or "")
    return "{" + label + (f", first {head.group(1)}" if head else "") + "}"


def template_text(template: str) -> str:
    """A message template as a reader sees it: derived-field and item-path
    placeholders in words (`{@join_type}` -> `{join type}`, `{obj.with}` -> `{with}`);
    the rule's own named values (`{name}`, `{count}`) as they are."""
    return _ITEM_PLACEHOLDER.sub(r"{\1}", _DERIVED_PLACEHOLDER.sub(_placeholder_text, template))


def message_text(rule: Rule, pid: str) -> str:
    message = profile_override(rule, pid).get("message", rule.message)
    return _by_severity_text(message, lambda m: f"“{template_text(str(m))}”")


def threshold_text(rule: Rule, pid: str, label: str) -> str:
    """The legacy `threshold` payload under `pid`, `{profile_label}` rendered."""
    name = _code_name(rule)
    decl = code_rule_declaration(name) if name else None
    if decl is not None and decl[1]:
        return f"set per finding — {_code_label(name)}"
    value = profile_override(rule, pid).get("legacy_threshold", rule.legacy_threshold)
    if value is None:
        return "—"
    return _by_severity_text(
        value, lambda v: mapping_text(v).replace("{profile_label}", label))


def per_profile(cat: Catalog, render) -> str:
    """`render(pid)` once when every profile agrees, else 'Label: …' per profile."""
    texts = {pid: render(pid) for pid in cat.profiles}
    if len(set(texts.values())) == 1:
        return next(iter(texts.values()))
    return _SEP.join(f"{cat.profiles[pid].label}: {text}" for pid, text in texts.items())


def _rule_meta(cat: Catalog, rule: Rule) -> Dict[str, Any]:
    return {
        "title": rule.title,
        "desc": rule.title,
        "thresholds": per_profile(cat, lambda pid: grading(rule, pid)),
        "message": per_profile(cat, lambda pid: message_text(rule, pid)),
        "remediation": rule.remediation,
        "views": list(rule.views),
        "categories": list(rule.categories),
    }


# ── report meta ─────────────────────────────────────────────────────────────

def report_meta(cat: Catalog) -> Dict[str, Any]:
    """Category labels/order, profiles, the views and per-rule text — active rules only
    (a retired rule emits nothing to describe)."""
    active = [r for r in cat.rules.values() if r.status == "active"]
    views: Dict[str, List[str]] = {}
    for rule in active:
        for view in rule.views:
            views.setdefault(view, []).append(rule.id)
    return {
        "categories": [{"id": c.id, "label": c.label, "order": c.order,
                        "angle_key": c.angle_key, "description": c.description}
                       for c in cat.categories.values()],
        "profiles": [{"id": p.id, "label": p.label, "default": p.default}
                     for p in cat.profiles.values()],
        "views": views,
        "checks": {rule.id: _rule_meta(cat, rule) for rule in active},
    }


# ── the check catalog doc ───────────────────────────────────────────────────

def _cell(text: Any) -> str:
    return " ".join(str(text or "").split()).replace("|", "\\|") or "—"


def _rule_row(cat: Catalog, rule: Rule, category: str) -> str:
    meta = _rule_meta(cat, rule)
    also = [c for c in rule.categories if c != category]
    what = f"**{rule.title}.** {rule.description}"
    if also:
        what += f" (also in {', '.join(also)})"
    return "| " + " | ".join(_cell(v) for v in (
        rule.id, what, meta["thresholds"], meta["message"], rule.remediation)) + " |"


def _category_section(cat: Catalog, cid: str) -> List[str]:
    category = cat.categories[cid]
    rows = [_rule_row(cat, r, cid) for r in cat.rules.values()
            if r.status == "active" and cid in r.categories]
    return [f"### {category.label} ({cid})", "", category.description, "",
            "| ID | What it detects | Severity | Finding text | Remediation |",
            "|---|---|---|---|---|", *rows, ""]


def _threshold_section(cat: Catalog) -> List[str]:
    rows = []
    for rule in cat.rules.values():
        if rule.status != "active":
            continue
        text = per_profile(cat, lambda pid, r=rule: threshold_text(
            r, pid, cat.profiles[pid].label))
        if text != "—":
            rows.append(f"| {rule.id} | {_cell(text)} |")
    return ["### Legacy `threshold` payloads", "",
            "The `threshold` dict each finding has always carried, kept for readers of "
            "older audit JSON (the uniform `bands` payload supersedes it).", "",
            "| ID | `threshold` |", "|---|---|", *rows, ""]


def _retired_section(cat: Catalog) -> List[str]:
    rows = [f"| {r.id} | {_cell(r.title)} | {_cell(r.description)} |"
            for r in cat.rules.values() if r.status == "retired"]
    return ["### Retired rules", "",
            "A retired rule keeps its id, which is never reused.", "",
            "| ID | Title | Why |", "|---|---|---|", *rows, ""]


def catalog_markdown(cat: Catalog) -> str:
    """The generated block of check-catalog.md (without the markers)."""
    profiles = ", ".join(f"`{p.id}` ({p.label}{', default' if p.default else ''})"
                         for p in cat.profiles.values())
    lines = ["<!-- Generated from tools/ts-cli/ts_cli/audit/catalog/ by "
             "`python -m ts_cli.audit.generate`. Do not edit by hand: the catalog gate "
             "fails when this block is stale. -->", "",
             f"Assessment profiles: {profiles}. Where a rule grades or words a finding "
             "differently per profile, each profile is shown.", ""]
    for cid in cat.categories:
        lines += _category_section(cat, cid)
    lines += _threshold_section(cat) + _retired_section(cat)
    return "\n".join(lines).rstrip() + "\n"


def render_doc(doc: str, cat: Catalog) -> str:
    """`doc` with its generated block replaced; ValueError without the markers."""
    start, end = doc.find(BEGIN), doc.find(END)
    if start < 0 or end < start:
        raise ValueError(f"{DOC_REL}: the {BEGIN} / {END} markers are missing")
    return doc[:start + len(BEGIN)] + "\n" + catalog_markdown(cat) + doc[end:]


def render_skill(doc: str, cat: Catalog) -> str:
    """SKILL.md with its named GENERATED blocks re-rendered; ValueError on a missing one."""
    from ts_cli.audit.generate_skill import render_named_blocks, skill_blocks
    try:
        return render_named_blocks(doc, skill_blocks(cat))
    except ValueError as exc:
        raise ValueError(f"{SKILL_REL}: {exc}") from exc


def _targets(root: Path) -> List[tuple]:
    """(path relative to root, renderer) for each generated doc: check-catalog.md always,
    SKILL.md when present."""
    targets = [(DOC_REL, render_doc)]
    if (Path(root) / SKILL_REL).is_file():
        targets.append((SKILL_REL, render_skill))
    return targets


def check(root: Path) -> List[str]:
    """Problems with the generated docs under repo `root` (empty: current)."""
    problems: List[str] = []
    try:
        cat = load_catalog(Path(root) / CATALOG_REL)
        for rel, render in _targets(root):
            doc = (Path(root) / rel).read_text(encoding="utf-8")
            if render(doc, cat) != doc:
                problems.append(f"{rel} is stale: run `python -m ts_cli.audit.generate`")
    except (OSError, ValueError, CatalogError) as exc:  # a malformed catalog included
        return [str(exc)]
    return problems


def write(root: Path) -> List[Path]:
    """Regenerate the docs under `root`; the ones that changed."""
    cat = load_catalog(Path(root) / CATALOG_REL)
    changed = []
    for rel, render in _targets(root):
        path = Path(root) / rel
        doc = path.read_text(encoding="utf-8")
        new = render(doc, cat)
        if new != doc:
            path.write_text(new, encoding="utf-8")
            changed.append(rel)
    return changed


def _default_root() -> Path:
    return CATALOG_DIR.parents[4]


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ts_cli.audit.generate",
                                description="Generate check-catalog.md's rule tables and "
                                            "the ts-audit skill's catalog-derived blocks.")
    p.add_argument("--root", type=Path, default=_default_root(), help="repository root")
    p.add_argument("--check", action="store_true", help="exit 1 when the doc is stale")
    args = p.parse_args(argv)
    if args.check:
        problems = check(args.root)
        for problem in problems:
            print(f"FAIL  {problem}")
        if not problems:
            print("PASS  " + ", ".join(str(rel) for rel, _ in _targets(args.root))
                  + " current")
        return 1 if problems else 0
    changed = write(args.root)
    print("Wrote " + ", ".join(map(str, changed)) if changed else "Unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
