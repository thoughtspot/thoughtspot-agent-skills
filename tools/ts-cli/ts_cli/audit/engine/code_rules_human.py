"""Code rules for the H (Human Readiness) rules — registered into code_rules.REGISTRY
(engine/code_rules.py imports this module at its end, so the registry, and the catalog
gate's list of known names, always include them).

Each reproduces its legacy check in checks_human.py (deleted when the rule catalog replaced them) exactly. The
thresholds, regexes and per-item wordings below were copied verbatim from there; the
legacy answers pinned in tests/audit_rule_fixtures/legacy_findings.json.gz hold them
to it. Where the legacy check would raise on a malformed value (a
non-string name or description), these skip it instead: a raising legacy check aborts
the whole H category, so there is nothing to reproduce.

Same import constraint as code_rules.py (the catalog gate imports this module).
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ts_cli.audit.engine import bands, scopes
from ts_cli.audit.engine.code_rules import code_rule
from ts_cli.audit.engine.messages import render, template
from ts_cli.audit.findings import Finding

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from ts_cli.audit.catalog_model import Rule


def _finding(rule: "Rule", item: dict, severity: str, values: Dict[str, Any],
             **kw: Any) -> Finding:
    return Finding(check_id=rule.id, angle="", severity=severity,
                   object_type=item["object_type"], object_name=item["name"],
                   object_guid=item["guid"],
                   detail=render(template(rule, severity), values), **kw)


# ── H2: description quality ─────────────────────────────────────────────────

# H2's lengths and how many issues it lists are the rule's `parameters` (rules/
# human.yaml: min_chars, max_chars, issues_shown), so a profile can override them.
#: "The " and "A " were dropped 2026-10 (roadmap PR 2.3): ordinary English openings, they
#: made 4,772 of 4,841 flagged descriptions on the 351-Model SE demo snapshot (the
#: 2026-10-23 BL-406 decision sheet; 1,314 of 1,370 on the 148-Model sample).
_BOILERPLATE = re.compile(r"^(This is a|Column for|Field for)", re.IGNORECASE)
def description_issue(column: dict, min_chars: float, max_chars: float) -> Optional[str]:
    """H2's wording of one column's description problem, checked in order (shorter than
    `min_chars` after stripping, longer than `max_chars`, boilerplate opening); None for
    a sound, blank or absent description."""
    desc = column.get("description") or ""
    if not isinstance(desc, str) or not desc.strip():
        return None
    desc, name = desc.strip(), column.get("name", "")
    if len(desc) < min_chars:
        return f"'{name}' too short ({len(desc)} chars)"
    if len(desc) > max_chars:
        return f"'{name}' too long ({len(desc)} chars)"
    if _BOILERPLATE.match(desc):
        return f"'{name}' uses boilerplate pattern"
    return None


@code_rule("description_quality", placeholders={"count", "issues"}, severity="severity",
           uses=(), label="one finding per Model, counting its columns' description issues",
           parameters={"min_chars", "max_chars", "issues_shown"})
def description_quality(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """H2 — one finding per Model with any description issue; `{count}` is how many
    columns have one, `{issues}` the first `issues_shown` joined by "; "."""
    p = rule.parameters
    out: List[Finding] = []
    for item in scopes.available(ctx, rule):
        issues = [i for i in (description_issue(c["obj"], p["min_chars"], p["max_chars"])
                              for c in scopes.iterate(ctx, "model.column", parent=item)) if i]
        if not issues:
            continue
        severity = bands.fixed_severity(rule, item, ctx)
        values = {"count": len(issues),
                  "issues": "; ".join(issues[:int(p["issues_shown"])])}
        out.append(_finding(rule, item, severity, values, metric=len(issues)))
    return out


# ── H10: stale / temporary names ────────────────────────────────────────────

_STALE_NAME = re.compile(
    r"\bdo[-_ ]?not[-_ ]?use\b|\bDEPRECATED\b|\bOBSOLETE\b"
    r"|\btest[-_ ]?\d*\b|\btmp[-_ ]|\btemp[-_ ]"
    r"|^copy[-_ ]of[-_ ]|[-_ ]copy\d*$|[-_ ]\(\d+\)$"
    r"|\bzDEL\b|\bDELETE\b|\bTO[-_ ]?DELETE\b|\bREMOVE\b"
    r"|\bbackup\b|\barchive\b|\bbak\b|[-_ ]old$|^old[-_ ]",
    re.IGNORECASE,
)
_STALE_NAME_SAFE = re.compile(
    r"test_results|test_automation|test_coverage|test_environment|test_suite",
    re.IGNORECASE,
)
_STALE_DESC = re.compile(
    r"do not use|deprecated|obsolete|will be removed|scheduled for deletion"
    r"|temporary|for testing|test only|copied from|clone of"
    r"|to be deleted|to be removed|pending deletion|backup of|archived|old version",
    re.IGNORECASE,
)
# How much of a stale description H10 quotes is its `quote_chars` parameter.


def is_stale_name(name: Any) -> bool:
    """legacy `_stale_match`: a stale pattern matches and no safe pattern does."""
    if not isinstance(name, str) or _STALE_NAME_SAFE.search(name):
        return False
    return bool(_STALE_NAME.search(name))


def is_stale_description(desc: Any) -> bool:
    return isinstance(desc, str) and bool(desc) and bool(_STALE_DESC.search(desc))


@code_rule("stale_names", placeholders={"what", "value"}, severity="severity",
           uses=(), label="one finding per stale-looking name or description",
           parameters={"quote_chars"})
def stale_names(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """H10 — per Model: its name, then each column's name and description, every match
    its own finding (`{what}` names which, `{value}` quotes it — a description's first
    `quote_chars` characters). Each finding is graded by the catalog `severity` on its
    own item: the Model's, or the column's (rules/human.yaml maps @orphan_model)."""
    out: List[Finding] = []
    shown = int(rule.parameters["quote_chars"])
    for item in scopes.available(ctx, rule):
        if is_stale_name(item["name"]):
            out.append(_finding(rule, item, bands.fixed_severity(rule, item, ctx),
                                {"what": "Model name", "value": item["name"]}))
        for col in scopes.iterate(ctx, "model.column", parent=item):
            severity = bands.fixed_severity(rule, col, ctx)
            if is_stale_name(col["name"]):
                out.append(_finding(rule, col, severity,
                                    {"what": "Column name", "value": col["name"]}))
            desc = col["obj"].get("description") or ""
            if is_stale_description(desc):
                out.append(_finding(rule, col, severity, {
                    "what": "Column description", "value": desc[:shown]}))
    return out
