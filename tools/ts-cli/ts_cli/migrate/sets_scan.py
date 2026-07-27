"""Phase 0 — `ts migrate scan-sets` engine. Pure functions, no I/O.

**Why this is a command of its own, and why it comes first.** Sets are a hard migration
blocker, so before planning any wave -- or committing to build Phase 2 at all -- the
programme needs one number: how many tenants actually use Sets. That answer decides
whether Sets support gates the whole programme or is a tail of stragglers.

It is deliberately not a mode of `audit`: it needs **no target Org**, so it runs before any
clean Org exists; it is far cheaper (a metadata scan, no TML export, no column matching);
and its output is a fleet roll-up rather than a per-tenant mapping file.

**Why Sets block, in three verified facts** (nebula, 2026-07-26):

1. A Set creates a `LOGICAL_COLUMN` of subtype `COHORT_*` **owned by the Model**.
2. That column **does not appear in the Model's TML at all** -- the Model exported ten
   columns and the cohort column was not among them.
3. It **blocks publishing** the Model and every Answer and Liveboard on it, used or not.

Fact 2 is the dangerous one, and it is the reason this scan exists rather than a TML
inspection: because the column is invisible in TML, a lift-and-shift would **silently
drop** Sets rather than fail, and nobody would notice until a tenant asked where theirs
went. A TML-based check would report a clean Model that is in fact blocked.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

# A Set's column carries a `COHORT_*` subtype (`COHORT_SIMPLE` observed live). Matched by
# prefix rather than equality so a future COHORT_ variant is not silently missed -- the
# failure mode of an exact match here is reporting a blocked Model as clean.
COHORT_PREFIX = "COHORT"

# Only these can depend on a cohort column in a way that matters for migration. A
# dependent of another type is recorded but never counted as an affected object.
REPORTABLE_DEPENDENT_TYPES = ("ANSWER", "LIVEBOARD")


def is_cohort_row(row: Dict[str, Any]) -> bool:
    """Is this `metadata/search` row a Set's cohort column?"""
    header = row.get("metadata_header") or {}
    return str(header.get("type", "")).upper().startswith(COHORT_PREFIX)


def extract_cohort_columns(rows: Iterable[Dict[str, Any]],
                           owner_guids: Iterable[str]) -> Dict[str, List[Dict[str, str]]]:
    """`{owner_guid: [{"name", "guid"}]}` for cohort columns owned by the named objects.

    Mirrors `publish_planning._cohort_columns`, which the spec names as the reference
    implementation, but keyed BY OWNER rather than flattened: a fleet report has to say
    which Model is blocked, not merely that something is.

    Rows whose owner is not in `owner_guids` are skipped, so the caller can pass one
    cluster-wide `LOGICAL_COLUMN` search and slice it per Model without re-querying.
    """
    owners = set(owner_guids)
    found: Dict[str, List[Dict[str, str]]] = {}
    for row in rows or ():
        if not is_cohort_row(row):
            continue
        header = row.get("metadata_header") or {}
        owner = header.get("owner")
        if owner not in owners:
            continue
        name = row.get("metadata_name") or header.get("name")
        guid = row.get("metadata_id") or header.get("id")
        if not name or not guid:
            continue
        bucket = found.setdefault(owner, [])
        if not any(existing["guid"] == guid for existing in bucket):
            bucket.append({"name": name, "guid": guid})
    return {owner: sorted(cols, key=lambda c: c["name"]) for owner, cols in found.items()}


def normalise_dependents(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Dependent rows reduced to `{type, name, guid}`, Answers and Liveboards only.

    The per-object detail is the point of the whole command. "Blocked" alone is a dead
    end; "blocked by these four Answers" is something a tenant can act on -- some
    Set-based content is stale, or rebuilds trivially as a filter, and retiring it turns a
    blocked tenant into a migratable one without waiting for the platform.
    """
    out: List[Dict[str, str]] = []
    for row in rows or ():
        obj_type = str(row.get("type") or row.get("metadata_type") or "").upper()
        if obj_type not in REPORTABLE_DEPENDENT_TYPES:
            continue
        name = row.get("name") or row.get("metadata_name") or ""
        guid = row.get("id") or row.get("guid") or row.get("metadata_id") or ""
        if not guid or any(existing["guid"] == guid for existing in out):
            continue
        out.append({"type": obj_type, "name": name, "guid": guid})
    return sorted(out, key=lambda d: (d["type"], d["name"]))


def build_blocked_entry(org: str, model_name: str, model_guid: str,
                        cohort_columns: List[Dict[str, str]],
                        dependents: List[Dict[str, str]]) -> Dict[str, Any]:
    """One blocked (Org, Model) row of the report."""
    return {"org": org, "model": model_name, "model_guid": model_guid,
            "cohort_columns": list(cohort_columns), "dependents": list(dependents)}


def build_scan_report(scanned_orgs: Iterable[str], scanned_models: int,
                      blocked: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """The `sets-scan.json` document.

    `scanned` carries the denominator deliberately. "Three blocked Orgs" is not a decision;
    "three of twelve" is -- and the whole purpose of Phase 0 is to size the problem before
    committing to build Phase 2.
    """
    blocked = sorted(blocked, key=lambda b: (b["org"], b["model"]))
    orgs = sorted({b["org"] for b in blocked})
    objects_affected = sum(len(b["dependents"]) for b in blocked)
    return {
        "scanned": {"orgs": len(list(scanned_orgs)), "models": scanned_models},
        "summary": {"orgs_blocked": len(orgs),
                    "models_blocked": len(blocked),
                    "objects_affected": objects_affected},
        "blocked": blocked,
    }


def render_scan_markdown(report: Dict[str, Any]) -> str:
    """`sets-scan.md` — the human read of the same data."""
    scanned = report.get("scanned") or {}
    summary = report.get("summary") or {}
    blocked = report.get("blocked") or []

    lines = [
        "# Sets scan — migration blockers",
        "",
        f"Scanned **{scanned.get('models', 0)} Model(s)** across "
        f"**{scanned.get('orgs', 0)} Org(s)**.",
        "",
        "| | |",
        "|---|---|",
        f"| Orgs blocked | **{summary.get('orgs_blocked', 0)}** of {scanned.get('orgs', 0)} |",
        f"| Models blocked | **{summary.get('models_blocked', 0)}** of {scanned.get('models', 0)} |",
        f"| Answers / Liveboards affected | **{summary.get('objects_affected', 0)}** |",
        "",
    ]

    if not blocked:
        lines += [
            "## No blockers found",
            "",
            "No in-scope Model carries a cohort column, so Sets do not block migration for "
            "the scanned scope. Re-run after any change to tenant content — a Set added "
            "later blocks the Model from that moment on.",
            "",
        ]
        return "\n".join(lines)

    lines += [
        "## Blocked Models",
        "",
        "A cohort column blocks publishing its Model **and every Answer and Liveboard on "
        "it**, used or not. It is invisible in TML, so a lift-and-shift would drop the Set "
        "silently rather than fail.",
        "",
    ]
    for entry in blocked:
        cols = ", ".join(f"`{c['name']}`" for c in entry["cohort_columns"]) or "—"
        lines += [f"### {entry['org']} / {entry['model']}", "",
                  f"- Cohort column(s): {cols}",
                  f"- GUID: `{entry['model_guid']}`", ""]
        if entry["dependents"]:
            lines += ["| Dependent | Type | GUID |", "|---|---|---|"]
            lines += [f"| {d['name']} | {d['type']} | `{d['guid']}` |"
                      for d in entry["dependents"]]
        else:
            lines.append("No Answers or Liveboards depend on the cohort column. The Model "
                         "is still blocked — the column blocks publication whether or not "
                         "anything uses it — but nothing has to be rebuilt: deleting the "
                         "Set unblocks the tenant outright.")
        lines.append("")

    lines += [
        "## What to do with this",
        "",
        "`ts migrate apply` refuses any Model carrying a cohort column, and there is no "
        "override — silently leaving content behind is the failure mode this scan exists "
        "to prevent.",
        "",
        "A blocked tenant has three routes:",
        "",
        "1. **Retire the dependent content** listed above, where it is stale.",
        "2. **Rebuild it** — some Set-based content is expressible as a filter.",
        "3. **Wait** for Sets support on published objects (expected roughly 3–6 months "
        "from 2026-07).",
        "",
        "Set usage is a **risk class in the batching strategy**, not a stop on the "
        "programme: low-risk tenants migrate now, Sets-using tenants form a later batch.",
        "",
    ]
    return "\n".join(lines)


def blocked_model_guids(report: Dict[str, Any]) -> Set[str]:
    """GUIDs of blocked Models, for `audit` to mark `SET_BLOCKER` without re-scanning."""
    return {b["model_guid"] for b in (report.get("blocked") or []) if b.get("model_guid")}
