"""Phase 2 — `ts migrate apply` planning engine. Pure functions, no I/O.

Turns an approved `column-mapping.csv` into an ordered, resumable plan.

**The migration is three steps: back up, rewrite Views, rewrite content.** An earlier
version of this module planned eight — lifting scaffolding Tables and Models into the
target, renaming the Model's columns, repointing content off the scaffolding, then
deleting it. All of that existed to avoid rewriting content, and BL-148/BL-149 showed
the avoidance was never possible: content TML has no physical anchor, so every reference
is a display name that has to be rewritten explicitly. Accepting that made the design
smaller. See `docs/superpowers/specs/2026-07-28-ts-migrate-orgs-rewrite-design.md`.

**Views come before content, and are the reason a migration can be cheap.** A View's
exposed column names survive a repoint, so content built on one needs nothing at all.
Rewriting Views first also means that in a new-Org run the View exists before anything
references it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ts_cli.migrate.schema import ColumnMappingRow, GAP_BLOCKER, SET_BLOCKER

STEP_BACKUP = "backup"
STEP_REWRITE_VIEWS = "rewrite_views"
STEP_REWRITE_CONTENT = "rewrite_content"

STEP_ORDER = (STEP_BACKUP, STEP_REWRITE_VIEWS, STEP_REWRITE_CONTENT)


# ---------------------------------------------------------------------------
# Step 0 — validation
# ---------------------------------------------------------------------------

def rename_pairs(rows) -> List[Tuple[str, str, str]]:
    """`(model, tenant_column, published_column)` for rows that actually rename."""
    out: List[Tuple[str, str, str]] = []
    for row in rows or ():
        target = (row.published_column or "").strip()
        if not target or target == row.tenant_column:
            continue
        out.append((row.model, row.tenant_column, target))
    return sorted(set(out))


def column_map(rows) -> Dict[str, str]:
    """`{tenant_column: published_column}` across every Model in the mapping.

    Flat rather than per-Model because a content object can read several Models at once,
    and the rewrite works on the document rather than on one Model's slice of it. A name
    that means different things in two Models would be ambiguous here -- which is exactly
    what `find_rename_collisions` refuses.
    """
    return {tenant: published for _model, tenant, published in rename_pairs(rows)}


def find_rename_collisions(rows) -> List[str]:
    """Problems that would produce two columns with one name, or an ambiguous rewrite.

    The map is **generated**, and its failure is silent: the rewrite substitutes names
    across the whole document, so a wrong target quietly repoints real content at the
    wrong column rather than erroring.
    """
    problems: List[str] = []
    pairs = rename_pairs(rows)

    by_target: Dict[Tuple[str, str], List[str]] = {}
    for model, tenant, target in pairs:
        by_target.setdefault((model, target), []).append(tenant)
    for (model, target), sources in sorted(by_target.items()):
        if len(sources) > 1:
            problems.append(
                f"{model}: {len(sources)} columns map onto '{target}' "
                f"({', '.join(sorted(sources))}) -- the rename map is not injective")

    renamed_away = {(m, t) for m, t, _ in pairs}
    existing: Dict[str, Set[str]] = {}
    for row in rows or ():
        existing.setdefault(row.model, set()).add(row.tenant_column)
    for model, tenant, target in pairs:
        if target in existing.get(model, set()) and (model, target) not in renamed_away:
            problems.append(
                f"{model}: '{tenant}' renames to '{target}', which is already a column of "
                f"that Model and is not itself being renamed")

    # One tenant column mapped to DIFFERENT published names in two Models. The rewrite
    # is document-wide, so it could not honour both -- and would silently pick one.
    per_name: Dict[str, Set[str]] = {}
    for _model, tenant, target in pairs:
        per_name.setdefault(tenant, set()).add(target)
    for tenant, targets in sorted(per_name.items()):
        if len(targets) > 1:
            problems.append(
                f"'{tenant}' maps to {sorted(targets)} in different Models. The rewrite "
                f"is document-wide and cannot honour both")
    return problems


def validate_apply(rows: Sequence[ColumnMappingRow],
                   blocked_model_guids: Optional[Set[str]] = None,
                   model_guids_by_name: Optional[Dict[str, str]] = None) -> List[str]:
    """Every reason this mapping cannot be applied. Empty list means go.

    Returns **all** problems: mapping mistakes are systematic, and fixing them one
    round-trip at a time is how a migration window is lost.
    """
    problems: List[str] = []
    for row in rows or ():
        if row.status == GAP_BLOCKER and not (row.published_column or "").strip():
            problems.append(f"{row.model}.{row.tenant_column}: GAP_BLOCKER with no "
                            f"published_column mapping")
        if row.status == SET_BLOCKER:
            problems.append(f"{row.model}: SET_BLOCKER -- the Model carries a cohort "
                            f"column. There is no override; retire or rebuild the Set")

    blocked = blocked_model_guids or set()
    if blocked and model_guids_by_name:
        for name, guid in sorted(model_guids_by_name.items()):
            if guid in blocked:
                problems.append(f"{name}: SET_BLOCKER from `ts migrate scan-sets` "
                                f"({guid}) -- refused, no override")

    problems.extend(find_rename_collisions(rows))
    seen: Set[str] = set()
    return [p for p in problems if not (p in seen or seen.add(p))]


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------

def import_mode(source_org: Optional[str], target_org: Optional[str],
                source_profile: Optional[str] = None,
                target_profile: Optional[str] = None) -> Dict[str, Any]:
    """How rewritten documents are written back.

    The only thing that differs between the three supported topologies. Cluster needs no
    handling at all: it is a property of the profile, and the two clients are already
    independent.

    - **same Org** -> update in place, keeping the guid. The objects already exist.
    - **new Org**  -> create fresh, stripping the guid.
    """
    same = (source_profile == target_profile
            and (source_org or "") == (target_org or ""))
    return {"same_org": same, "create_new": not same, "keep_guid": same,
            "note": ("updating content in place; the backup is the only rollback"
                     if same else
                     "creating fresh content; the target Org can be deleted to roll back")}


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

# How a target Org's data is kept separate from other tenants'. RLS is only ONE of these,
# and demanding it where the platform already segments physically is both wrong and
# corrosive: it trains operators to pass --allow-unfiltered-target reflexively, which
# destroys the check for the case where it genuinely matters.
SEGMENT_PHYSICAL = "physical"            # a variable resolves to a different db/schema/table per Org
SEGMENT_PER_PRINCIPAL = "per_principal"  # resolved per user/group, so not an Org-level question
SEGMENT_SHARED = "shared"                # every Org reads the SAME rows -- RLS is the only separator
SEGMENT_UNKNOWN = "unknown"              # could not be determined

# Variable classes that segment by resolving differently per PRINCIPAL rather than per Org.
_PER_PRINCIPAL_TYPES = {"CONNECTION_PROPERTY_PER_PRINCIPAL", "USER_PROPERTY"}
# Variable classes that can point an Org at different physical data.
_PHYSICAL_TYPES = {"TABLE_MAPPING", "CONNECTION_PROPERTY"}


def target_segmentation(variables: Sequence[Mapping[str, Any]],
                        target_org: Optional[str]) -> str:
    """How this target Org's rows are separated from other tenants'.

    **RLS only matters when publication resolves every Org to the SAME physical table.**
    ThoughtSpot Publishing requires a variable bound to the db/schema/table fields, and
    that variable may hold a *different* value per Org -- pointing each tenant at its own
    database or schema. Where it does, the tenants are already physically separated and
    row-level security is not the mechanism keeping them apart.

    `variables` is the `METADATA_AND_VALUES` response for the variables bound to the
    published object's fields.

    Returns `SEGMENT_UNKNOWN` when nothing can be read: not knowing how a shared Model is
    separated is not the same as knowing it is safe.
    """
    if not variables:
        return SEGMENT_UNKNOWN
    saw_physical_variable = False
    for var in variables:
        vtype = str(var.get("variable_type") or "").upper()
        values = var.get("values") or []
        if vtype in _PER_PRINCIPAL_TYPES:
            return SEGMENT_PER_PRINCIPAL
        if any(v.get("principal_identifier") for v in values):
            return SEGMENT_PER_PRINCIPAL
        if vtype not in _PHYSICAL_TYPES:
            continue
        saw_physical_variable = True
        distinct = {v.get("value") for v in values if v.get("value") is not None}
        # More than one distinct value across Orgs means at least two Orgs read different
        # physical data. That is segmentation, whether or not THIS Org is one of them.
        if len(distinct) > 1:
            return SEGMENT_PHYSICAL
    return SEGMENT_SHARED if saw_physical_variable else SEGMENT_UNKNOWN


def unfiltered_target_problem(table_rule_counts: Mapping[str, int], model_name: str,
                              allow: bool = False,
                              segmentation: str = SEGMENT_SHARED) -> Optional[str]:
    """Refuse to bind tenant content to a published Model that separates no tenants.

    RLS is checked **only when the Orgs share physical data**. If publication resolves
    each Org to its own database, schema or table -- or resolves per principal -- the
    tenants are already separated and requiring RLS on top would be a false alarm.
    """
    if segmentation in (SEGMENT_PHYSICAL, SEGMENT_PER_PRINCIPAL):
        return None
    if segmentation == SEGMENT_UNKNOWN:
        return (f"could not determine how '{model_name}' separates tenants: neither its "
                f"row-level security nor its publication variables could be read. "
                f"Refused -- an unreadable check is not a passed one")
    if not table_rule_counts:
        return (f"'{model_name}' resolves every Org to the SAME physical data, and its "
                f"row-level security could not be read. Refused -- an unreadable check is "
                f"not a passed one")
    unfiltered = sorted(name for name, count in table_rule_counts.items() if not count)
    if not unfiltered or allow:
        return None
    return (f"the published Model '{model_name}' resolves every Org to the SAME physical "
            f"data and has NO row-level security on: {', '.join(unfiltered)}. Binding "
            f"this tenant's content to it would leave every tenant able to see every "
            f"other tenant's rows. Add RLS, point the Orgs at different data via the "
            f"publication variable, or pass --allow-unfiltered-target if this target is "
            f"deliberately single-tenant")


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

def build_apply_plan(pair: Dict[str, str], views: List[Dict[str, Any]],
                     content: List[Dict[str, Any]], columns: Mapping[str, str],
                     target: Dict[str, str], mode: Dict[str, Any]
                     ) -> List[Dict[str, Any]]:
    """The ordered steps for one (source -> target) pair.

    `views` and `content` are classified dependent rows. Content already shielded by a
    View is **not** in `content`: rewriting the View covers it, and rewriting it again
    would be work that can only introduce error.
    """
    steps: List[Dict[str, Any]] = [
        {"step": STEP_BACKUP,
         "objects": sorted({d["guid"] for d in list(views) + list(content)})},
        {"step": STEP_REWRITE_VIEWS, "objects": list(views),
         "columns": dict(columns), "target": dict(target), "mode": dict(mode)},
        {"step": STEP_REWRITE_CONTENT, "objects": list(content),
         "columns": dict(columns), "target": dict(target), "mode": dict(mode)},
    ]
    for step in steps:
        step["pair"] = dict(pair)
    return steps


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def new_ledger(pair: Dict[str, str]) -> Dict[str, Any]:
    return {"pair": dict(pair), "completed": [], "created": {}, "failed": None}


def pending_steps(plan: Sequence[Dict[str, Any]],
                  ledger: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Plan steps the ledger has not recorded as completed.

    Keyed on step NAME rather than index, so a plan regenerated after a mapping edit
    still skips completed work -- an index would silently shift.
    """
    done = set((ledger or {}).get("completed") or [])
    return [s for s in plan if s["step"] not in done]


def record_completed(ledger: Dict[str, Any], step: str,
                     created: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if step not in ledger["completed"]:
        ledger["completed"].append(step)
    if created:
        ledger.setdefault("created", {}).setdefault(step, {}).update(created)
    ledger["failed"] = None
    return ledger


def record_failure(ledger: Dict[str, Any], step: str, detail: str) -> Dict[str, Any]:
    ledger["failed"] = {"step": step, "detail": detail}
    return ledger


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_rewrite_step(step: Dict[str, Any]) -> List[str]:
    """The lines for one rewrite step."""
    objs = step["objects"]
    mode = step.get("mode") or {}
    verb = "updated in place" if mode.get("same_org") else "created fresh"
    lines = [f"   - {len(objs)} object(s), {verb}"]
    if step["step"] == STEP_REWRITE_VIEWS and objs:
        lines.append("   - a View's exposed column names are PRESERVED, so content "
                     "built on it needs no migration")
    if not objs:
        lines.append("   - none")
    if step["step"] == STEP_REWRITE_CONTENT:
        cols = sorted((step.get("columns") or {}).items())
        lines += [f"     `{old}` → `{new}`" for old, new in cols[:6]]
        if len(cols) > 6:
            lines.append(f"     … and {len(cols) - 6} more")
    return lines


def render_plan(plan: Sequence[Dict[str, Any]]) -> str:
    """Human-readable ordered plan for `--dry-run`."""
    pair = plan[0].get("pair", {}) if plan else {}
    lines = ["# Migration plan", "",
             f"**{pair.get('source', '?')} → {pair.get('target', '?')}**", ""]
    for i, step in enumerate(plan, 1):
        lines.append(f"{i}. **{step['step']}**")
        if step["step"] == STEP_BACKUP:
            lines.append(f"   - {len(step['objects'])} object(s) exported before anything "
                         f"is written")
        else:
            lines.extend(_render_rewrite_step(step))
    mode = (plan[1].get("mode") if len(plan) > 1 else {}) or {}
    lines += ["", f"Mode: {mode.get('note', '?')}."]
    if not mode.get("same_org"):
        lines.append("Cutover is NOT part of this plan. Users move only after the target "
                     "is verified; until then the source Org is untouched and is the "
                     "rollback.")
    return "\n".join(lines)
