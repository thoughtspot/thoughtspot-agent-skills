"""Phase 2 — `ts migrate apply` planning engine. Pure functions, no I/O.

Turns an approved `column-mapping.csv` into an ordered, resumable, reversible plan for
moving one tenant's bespoke content onto the governed published Model.

**Why a plan object rather than a procedure.** Every step here is destructive or
near-destructive in someone's production Org, and the two things that make that
survivable are both properties of a *plan*: it can be printed and read before anything
runs (`--dry-run`), and each step can be matched against a ledger so an interrupted run
resumes instead of redoing. A procedure that does the work inline has neither.

**The step order is load-bearing** and encodes findings that cost live verification to
learn (see `docs/superpowers/verification/2026-07-27-ts-migrate-binding-resolution.md`):

- The target Org needs **its own connection, named as the source's**, before any Table
  import -- publishing does not grant one, and a same-named connection is what lets the
  lifted TML resolve unchanged.
- Cleanup runs **Models, then Tables, then the connection**: connection deletion does not
  cascade. That order is also a safety net -- a Model that still has dependents refuses to
  delete, surfacing a repoint that was missed, where a wholesale Org drop would take the
  un-repointed content with it silently.
- Cleanup runs **before cutover**, so the Org is verified in its final state. The rollback
  throughout is the untouched source Org, never the scaffolding.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ts_cli.migrate.schema import (ColumnMappingRow, GAP_BLOCKER, SET_BLOCKER)

# Ordered phases of one tenant's migration. Names are stable -- the ledger keys on them.
STEP_BACKUP = "backup"
STEP_LIFT_SCAFFOLDING = "lift_scaffolding"
STEP_LIFT_CONTENT = "lift_content"
STEP_RENAME = "rename"
STEP_REPOINT = "repoint"
STEP_CLEANUP_MODELS = "cleanup_models"
STEP_CLEANUP_TABLES = "cleanup_tables"
STEP_CLEANUP_CONNECTION = "cleanup_connection"

STEP_ORDER = (
    STEP_BACKUP, STEP_LIFT_SCAFFOLDING, STEP_LIFT_CONTENT, STEP_RENAME, STEP_REPOINT,
    STEP_CLEANUP_MODELS, STEP_CLEANUP_TABLES, STEP_CLEANUP_CONNECTION,
)


# ---------------------------------------------------------------------------
# Step 0 — validation
# ---------------------------------------------------------------------------

def rename_pairs(rows: Iterable[ColumnMappingRow]) -> List[Tuple[str, str, str]]:
    """`(model, tenant_column, published_column)` for rows that actually rename.

    A row whose names already match needs no work -- emitting it would make the rename
    step O(columns) instead of O(renames) and would import a no-op diff.
    """
    out: List[Tuple[str, str, str]] = []
    for row in rows or ():
        target = (row.published_column or "").strip()
        if not target or target == row.tenant_column:
            continue
        out.append((row.model, row.tenant_column, target))
    return sorted(set(out))


def find_rename_collisions(rows: Iterable[ColumnMappingRow]) -> List[str]:
    """Problems that would produce two columns with one name in the same Model.

    The repo owner's position -- that standard fields keep their names and custom fields
    map into unused generic slots, so collisions cannot arise -- is right by construction.
    This exists because the map is **generated**, and a generation bug is silent: the
    rename cascades to every dependent automatically, so a wrong target quietly repoints
    real content at the wrong column rather than failing.

    Two distinct failures, both fatal:

    1. **Not injective** -- two tenant columns mapped onto one published column.
    2. **Target already present** -- the published name is already a column of that Model,
       so the rename collides with a column that is not being renamed.
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

    # A target that is some OTHER row's untouched tenant column collides on import.
    renamed_away = {(m, t) for m, t, _ in pairs}
    existing: Dict[str, Set[str]] = {}
    for row in rows or ():
        existing.setdefault(row.model, set()).add(row.tenant_column)
    for model, tenant, target in pairs:
        if target in existing.get(model, set()) and (model, target) not in renamed_away:
            problems.append(
                f"{model}: '{tenant}' renames to '{target}', which is already a column of "
                f"that Model and is not itself being renamed")
    return problems


def validate_apply(rows: Sequence[ColumnMappingRow],
                   blocked_model_guids: Optional[Set[str]] = None,
                   model_guids_by_name: Optional[Dict[str, str]] = None) -> List[str]:
    """Every reason this mapping cannot be applied. Empty list means go.

    Returns **all** problems rather than the first: mapping mistakes are systematic, and
    an operator fixing them one round-trip at a time is how a migration window is lost.
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
    # De-duplicate while keeping order: one Model with many SET_BLOCKER rows should say so
    # once, not once per column.
    seen: Set[str] = set()
    return [p for p in problems if not (p in seen or seen.add(p))]


# ---------------------------------------------------------------------------
# Connection provisioning (step 0b)
# ---------------------------------------------------------------------------

def connection_action(source_connection: str,
                      target_connections: Iterable[str]) -> Dict[str, Any]:
    """Decide how the target Org's connection is handled.

    Connection names are per-Org (verified live 2026-07-27), so the target CAN hold the
    source's name -- and when it does, every lifted Table's `connection` block resolves
    unchanged. That is an optimisation with a correct fallback, not a requirement: a
    differently-named connection still works, it just means rewriting one field per Table.
    """
    available = [c for c in (target_connections or []) if c]
    if not available:
        return {"action": "fail",
                "reason": "the target Org has no connection. Publishing does not grant "
                          "one -- provision it first (`ts tenancy`)"}
    if source_connection in available:
        return {"action": "resolve_unchanged", "connection": source_connection}
    return {"action": "rewrite", "connection": available[0],
            "reason": f"the target Org has no connection named '{source_connection}', so "
                      f"each lifted Table's connection block is rewritten to "
                      f"'{available[0]}'. Nothing is queried through the scaffolding and "
                      f"it is deleted at cleanup, so any valid connection will do"}


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

def unfiltered_target_problem(table_rule_counts: Dict[str, int], model_name: str,
                              allow: bool = False) -> Optional[str]:
    """Refuse to repoint tenant content onto a published Model that filters no rows.

    **This is the check that matters, and it replaces a guard that could not fire.** The
    original BL-144 mitigation re-read `rls_rules` after a write -- but `apply` never
    writes a table whose RLS matters: the only Table TML it writes is disposable
    scaffolding, deleted at cleanup and never queried. The guard was dead code.

    The real exposure is at the other end. After the repoint, the tenant's content is
    bound to the SHARED published Model. If that Model's tables carry no row-level
    security, every tenant sees every other tenant's rows -- the single worst outcome the
    programme can produce, silent, and unlike BL-144 entirely checkable before the damage
    is done.

    An override exists because a genuinely single-tenant target, or a warehouse that
    segments elsewhere, is legitimate -- but it must be a deliberate act, which is the
    same posture `ts security column-rules` takes with `--allow-published`.
    """
    if not table_rule_counts:
        return (f"could not read the row-level security of '{model_name}'s tables. "
                f"Repointing tenant content onto a Model whose filtering is unknown is "
                f"refused -- an unreadable check is not a passed one")
    unfiltered = sorted(name for name, count in table_rule_counts.items() if not count)
    if not unfiltered:
        return None
    if allow:
        return None
    return (f"the published Model '{model_name}' has NO row-level security on: "
            f"{', '.join(unfiltered)}. Repointing this tenant's content onto it would "
            f"leave every tenant able to see every other tenant's rows. Add RLS to the "
            f"published table(s), or pass --allow-unfiltered-target if this target is "
            f"deliberately single-tenant or segmented elsewhere")


def build_apply_plan(pair: Dict[str, str], scaffolding: Dict[str, List[str]],
                     content: Dict[str, List[str]], rows: Sequence[ColumnMappingRow],
                     connection: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The ordered steps for one (source Org -> clean Org) pair.

    `scaffolding` and `content` are `{"tables": [...], "models": [...]}` and
    `{"views": [...], "answers": [...], "liveboards": [...]}` of source GUIDs.
    """
    renames = rename_pairs(rows)
    steps: List[Dict[str, Any]] = [
        {"step": STEP_BACKUP, "objects": sorted(
            set(scaffolding.get("tables", []) + scaffolding.get("models", [])
                + content.get("views", []) + content.get("answers", [])
                + content.get("liveboards", [])))},
        {"step": STEP_LIFT_SCAFFOLDING,
         "tables": list(scaffolding.get("tables", [])),
         "models": list(scaffolding.get("models", [])),
         "connection": connection},
        # Dependency order within the content lift: a Liveboard references Answers, an
        # Answer references Views. Intra-batch references remap on import (the fqn falls
        # back to the name), but only for objects already in the batch.
        {"step": STEP_LIFT_CONTENT,
         "batches": [("views", list(content.get("views", []))),
                     ("answers", list(content.get("answers", []))),
                     ("liveboards", list(content.get("liveboards", [])))]},
        {"step": STEP_RENAME, "renames": renames},
        {"step": STEP_REPOINT, "models": list(scaffolding.get("models", []))},
    ]
    steps.extend(build_cleanup_steps(scaffolding, connection))
    for step in steps:
        step["pair"] = dict(pair)
    return steps


def build_cleanup_steps(scaffolding: Dict[str, List[str]],
                        connection: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Cleanup, in the only safe order: Models, then Tables, then the connection.

    Deleting a connection does **not** cascade to its Tables (`deleteConnection`: "If a
    connection has dependent objects, make sure you remove its associations before the
    delete operation"), so the connection cannot go first.

    The connection is only dropped when `apply` provisioned it for this migration. A
    connection the target Org already had is left alone -- deleting it would remove
    something that is not ours.
    """
    steps: List[Dict[str, Any]] = [
        {"step": STEP_CLEANUP_MODELS, "models": list(scaffolding.get("models", []))},
        {"step": STEP_CLEANUP_TABLES, "tables": list(scaffolding.get("tables", []))},
    ]
    if connection.get("provisioned"):
        steps.append({"step": STEP_CLEANUP_CONNECTION,
                      "connection": connection.get("connection")})
    return steps


# ---------------------------------------------------------------------------
# Ledger — resumability
# ---------------------------------------------------------------------------

def new_ledger(pair: Dict[str, str]) -> Dict[str, Any]:
    return {"pair": dict(pair), "completed": [], "created": {}, "failed": None}


def pending_steps(plan: Sequence[Dict[str, Any]],
                  ledger: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Plan steps the ledger has not recorded as completed.

    Resumption is by step name rather than index so a plan regenerated after a mapping
    edit still skips the work already done -- an index would silently shift.
    """
    done = set((ledger or {}).get("completed") or [])
    return [s for s in plan if s["step"] not in done]


def record_completed(ledger: Dict[str, Any], step: str,
                     created: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Mark a step done, keeping the GUIDs it created so a re-run updates in place."""
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

def _render_backup(step):
    return [f"   - {len(step['objects'])} object(s) exported before anything is written"]


def _render_lift_scaffolding(step):
    conn = step["connection"]
    return [f"   - {len(step['tables'])} Table(s), {len(step['models'])} Model(s)",
            f"   - connection: {conn.get('action')}"
            + (f" — {conn['reason']}" if conn.get("reason") else "")]


def _render_lift_content(step):
    return [f"   - {kind}: {len(guids)}" for kind, guids in step["batches"] if guids]


def _render_rename(step):
    if not step["renames"]:
        return ["   - no renames (every column already matches)"]
    return [f"   - {model}: `{tenant}` → `{target}`"
            for model, tenant, target in step["renames"]]


def _render_repoint(step):
    return [f"   - content moved off {len(step['models'])} scaffolding Model(s) onto the "
            f"published Model(s)"]


def _render_cleanup_models(step):
    return [f"   - delete {len(step['models'])} scaffolding Model(s). A Model with "
            f"dependents REFUSES to delete — that is the missed-repoint check, not an "
            f"error to force past"]


def _render_cleanup_tables(step):
    return [f"   - delete {len(step['tables'])} scaffolding Table(s)"]


def _render_cleanup_connection(step):
    return [f"   - delete connection `{step['connection']}` (provisioned by this "
            f"migration; deletion does not cascade, hence last)"]


_STEP_RENDERERS = {
    STEP_BACKUP: _render_backup,
    STEP_LIFT_SCAFFOLDING: _render_lift_scaffolding,
    STEP_LIFT_CONTENT: _render_lift_content,
    STEP_RENAME: _render_rename,
    STEP_REPOINT: _render_repoint,
    STEP_CLEANUP_MODELS: _render_cleanup_models,
    STEP_CLEANUP_TABLES: _render_cleanup_tables,
    STEP_CLEANUP_CONNECTION: _render_cleanup_connection,
}


def render_plan(plan: Sequence[Dict[str, Any]]) -> str:
    """Human-readable ordered plan for `--dry-run`."""
    pair = plan[0].get("pair", {}) if plan else {}
    lines = ["# Migration plan", "",
             f"**{pair.get('source', '?')} → {pair.get('target', '?')}**", ""]
    for i, step in enumerate(plan, 1):
        lines.append(f"{i}. **{step['step']}**")
        renderer = _STEP_RENDERERS.get(step["step"])
        if renderer:
            lines.extend(renderer(step))
    lines += ["", "Cutover is NOT part of this plan. Users move only after the Org is "
                  "verified in its final state; until then the rollback is the untouched "
                  "source Org."]
    return "\n".join(lines)
