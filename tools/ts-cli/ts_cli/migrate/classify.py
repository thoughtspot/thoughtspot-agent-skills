"""Classify each dependent by WHAT IT SITS ON. Pure functions, no I/O.

This is the number that sizes a tenant's migration, and it is not the object count.

Because a View's exposed column names survive a repoint (proven live 2026-07-28: a View
repointed to a different Model, through a different column name, kept its aliases and its
untouched Answer kept returning data), content built on a View costs **nothing** to
migrate. Repoint the View and everything above it is done.

So a tenant with 200 Answers over 4 Views is four repoints, while a tenant with 40 Answers
straight onto the Model is forty rewrites. The object counts point the wrong way. Only this
classification tells you which tenant is the cheap one, and the audit is the only place it
can be computed.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

# What a dependent sits on, and therefore what it costs.
MODEL_BASED = "MODEL_BASED"    # full rewrite
VIEW_BASED = "VIEW_BASED"      # FREE -- repointing the View covers it
TABLE_BASED = "TABLE_BASED"    # full rewrite, AND a warning
UNKNOWN = "UNKNOWN"            # could not resolve -- treated as needing work

# Subtypes as `metadata/search` reports them.
_VIEW_SUBTYPES = {"AGGR_WORKSHEET"}
_MODEL_SUBTYPES = {"WORKSHEET"}
_TABLE_SUBTYPES = {"ONE_TO_ONE_LOGICAL", "USER_DEFINED", "SQL_VIEW"}


def kind_of(subtype: Optional[str]) -> str:
    """Map a `LOGICAL_TABLE` subtype to what it means for migration cost."""
    s = (subtype or "").upper()
    if s in _VIEW_SUBTYPES:
        return VIEW_BASED
    if s in _MODEL_SUBTYPES:
        return MODEL_BASED
    if s in _TABLE_SUBTYPES:
        return TABLE_BASED
    return UNKNOWN


def source_refs(doc: Mapping[str, Any]) -> List[str]:
    """Every `tables[].fqn` a content document points at.

    `fqn` and not the name: it is the only stable reference in a content document, and the
    name is exactly what the migration is about to change.
    """
    found: List[str] = []

    def walk(node, key=None):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            if key == "tables":
                for entry in node:
                    if isinstance(entry, dict) and entry.get("fqn"):
                        if entry["fqn"] not in found:
                            found.append(entry["fqn"])
            else:
                for v in node:
                    walk(v, key)

    walk(doc)
    return found


def classify_dependent(guid: str, name: str, obj_type: str,
                       refs: Iterable[str],
                       kinds_by_guid: Mapping[str, str]) -> Dict[str, Any]:
    """Classify one dependent, and say what it costs.

    A dependent pointing at several sources takes the **most expensive** classification:
    an Answer that reads one View and one Model still needs rewriting for the Model half,
    so calling it VIEW_BASED would under-count the work and skip it.
    """
    refs = list(refs)
    kinds = [kinds_by_guid.get(r, UNKNOWN) for r in refs] or [UNKNOWN]
    for worst in (UNKNOWN, TABLE_BASED, MODEL_BASED, VIEW_BASED):
        if worst in kinds:
            kind = worst
            break
    return {"guid": guid, "name": name, "type": obj_type, "sits_on": kind,
            "source_refs": refs, "needs_rewrite": kind != VIEW_BASED}


def build_effort(classified: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Roll up what the migration actually costs, and why.

    `views_to_repoint` is the useful half: the objects it shields never appear in the
    rewrite count, which is what makes a View-heavy tenant cheap.
    """
    items = list(classified)
    by_kind: Dict[str, int] = {}
    for item in items:
        by_kind[item["sits_on"]] = by_kind.get(item["sits_on"], 0) + 1
    shielded = by_kind.get(VIEW_BASED, 0)
    views = sorted({ref for item in items if item["sits_on"] == VIEW_BASED
                    for ref in item["source_refs"]})
    return {
        "dependents": len(items),
        "by_kind": by_kind,
        "needs_rewrite": sum(1 for i in items if i["needs_rewrite"]),
        "shielded_by_views": shielded,
        "views_to_repoint": views,
        "table_based_warning": by_kind.get(TABLE_BASED, 0),
        "unresolved": by_kind.get(UNKNOWN, 0),
    }


def render_effort_markdown(effort: Mapping[str, Any]) -> str:
    """The section of the audit report a human reads to size the job."""
    total = effort.get("dependents", 0)
    rewrite = effort.get("needs_rewrite", 0)
    shielded = effort.get("shielded_by_views", 0)
    views = effort.get("views_to_repoint") or []

    lines = ["## Migration effort", "",
             f"**{total} dependent object(s)**, of which **{rewrite} need rewriting**.", ""]
    if shielded:
        lines += [f"**{shielded} are shielded by {len(views)} View(s)** and cost nothing: "
                  f"a View's exposed column names survive a repoint, so repointing the "
                  f"View migrates everything built on it.", ""]
        lines += ["| View to repoint |", "|---|"]
        lines += [f"| `{v}` |" for v in views]
        lines.append("")
    if effort.get("table_based_warning"):
        lines += [f"> **{effort['table_based_warning']} object(s) sit directly on a Table, "
                  f"not the Model.** They still need rewriting, and a Model-level change "
                  f"never reaches them — so anything that assumes Model-level coverage "
                  f"will silently miss these.", ""]
    if effort.get("unresolved"):
        lines += [f"> **{effort['unresolved']} object(s) could not be resolved** to a "
                  f"source. They are counted as needing a rewrite, because an unresolved "
                  f"dependency is not a safe one to skip.", ""]
    if not shielded and total:
        lines += ["No View shielding available: every dependent reads its source "
                  "directly, so the rewrite count is the object count.", ""]
    return "\n".join(lines)
