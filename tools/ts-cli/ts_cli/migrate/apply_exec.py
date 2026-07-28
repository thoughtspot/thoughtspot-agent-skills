"""Phase 2 executor — the I/O half of `ts migrate apply`.

Pure planning lives in `apply_plan.py`; this module runs the plan. Split so the ordering
and validation rules -- the parts that encode live findings -- stay unit-testable without
a cluster.

Each `run_*` takes `(ctx, step)` and returns `{guid: new_guid}` for the ledger, raising
`StepFailed` with an actionable message on anything it cannot complete. The caller records
the outcome and decides whether to continue.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ts_cli.migrate.apply_plan import (STEP_BACKUP, STEP_CLEANUP_CONNECTION,
                                       STEP_CLEANUP_MODELS, STEP_CLEANUP_TABLES,
                                       STEP_LIFT_CONTENT, STEP_LIFT_SCAFFOLDING,
                                       STEP_RENAME, STEP_REPOINT,
                                       unfiltered_target_problem)


class StepFailed(Exception):
    """A step could not complete. The message is shown to the operator verbatim."""


class Ctx:
    """Everything a step needs: both clients, the plan directory, and the live ledger."""

    def __init__(self, source_client, target_client, plan_dir: Path,
                 ledger: Dict[str, Any], dry_run: bool = False,
                 allow_unfiltered: bool = False):
        self.source = source_client
        self.target = target_client
        self.plan_dir = plan_dir
        self.ledger = ledger
        self.dry_run = dry_run
        # Only ever set by an explicit --allow-unfiltered-target. Defaulting it True
        # would turn the tenant-isolation check into a no-op for everyone who never
        # reads the flag list.
        self.allow_unfiltered = allow_unfiltered

    def created(self, step: str) -> Dict[str, str]:
        return (self.ledger.get("created") or {}).get(step, {})


# ---------------------------------------------------------------------------
# TML helpers
# ---------------------------------------------------------------------------

def export_tml(client, guids: List[str]) -> List[Dict[str, Any]]:
    """Export a batch as parsed JSON documents. One call, because calls scale with
    batches rather than objects -- the round-trip budget the design is built on."""
    if not guids:
        return []
    resp = client.post("/api/rest/2.0/metadata/tml/export",
                       json={"metadata": [{"identifier": g} for g in guids],
                             "edoc_format": "JSON", "export_fqn": True})
    docs = []
    for item in resp.json():
        edoc = item.get("edoc")
        if edoc:
            docs.append(json.loads(edoc))
    return docs


def import_tml(client, docs: List[Dict[str, Any]], *, create_new: bool = True
               ) -> List[Dict[str, Any]]:
    """Import a batch all-or-none and return the per-item outcomes.

    ALL_OR_NONE because a partial scaffolding import leaves the target Org holding half a
    reference graph, which the next step would bind content to.
    """
    if not docs:
        return []
    resp = client.post("/api/rest/2.0/metadata/tml/import",
                       json={"metadata_tmls": [json.dumps(d) for d in docs],
                             "import_policy": "ALL_OR_NONE", "create_new": create_new})
    return resp.json()


def import_failures(results: List[Dict[str, Any]]) -> List[str]:
    """Failed items. `metadata/tml/import` returns HTTP 200 even when every item failed --
    the outcome is in the body, not the status code (BL-138)."""
    out = []
    for item in results or []:
        resp = item.get("response") or {}
        status = resp.get("status") or {}
        if str(status.get("status_code", "")).upper() not in ("OK", "WARNING"):
            name = (resp.get("header") or {}).get("name") or "<unnamed>"
            msg = " ".join((status.get("error_message") or "").split())[:200]
            out.append(f"{name}: {msg}")
    return out


def imported_guids(results: List[Dict[str, Any]]) -> Dict[str, str]:
    """`{name: guid}` for successfully imported items, for the ledger."""
    out = {}
    for item in results or []:
        header = ((item.get("response") or {}).get("header") or {})
        if header.get("name") and header.get("id_guid"):
            out[header["name"]] = header["id_guid"]
    return out


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def run_backup(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    """Export every in-scope source object before anything is written.

    All-or-nothing: nothing is saved if any export fails, mirroring `ts dependency
    backup`. A partial backup is worse than none -- it reads as a safety net that is not
    there.
    """
    guids = step["objects"]
    docs = export_tml(ctx.source, guids)
    if len(docs) != len(guids):
        raise StepFailed(f"backup incomplete: exported {len(docs)} of {len(guids)} "
                         f"object(s); nothing written")
    if ctx.dry_run:
        return {}
    out = ctx.plan_dir / "backup"
    out.mkdir(parents=True, exist_ok=True)
    for guid, doc in zip(guids, docs):
        (out / f"{guid}.json").write_text(json.dumps(doc, indent=2))
    return {}


def _rewrite_connection(doc: Dict[str, Any], connection_name: str) -> None:
    table = doc.get("table")
    if isinstance(table, dict) and isinstance(table.get("connection"), dict):
        table["connection"] = {"name": connection_name}


def run_lift_scaffolding(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    """Lift the tenant's Tables and Models into the target Org as one batch.

    Tables and Models go together so their references stay internally consistent -- the
    importer remaps intra-batch references, which is the whole reason this is
    lift-and-shift rather than per-object GUID rewriting.
    """
    conn = step["connection"]
    if conn.get("action") == "fail":
        raise StepFailed(conn["reason"])

    docs = export_tml(ctx.source, step["tables"] + step["models"])
    if conn["action"] == "rewrite":
        for doc in docs:
            _rewrite_connection(doc, conn["connection"])
    for doc in docs:
        doc.pop("guid", None)  # create-new in the target Org

    if ctx.dry_run:
        return {}
    # Imported as ONE batch so intra-batch references remap; the kind is then read back
    # off each document, because Tables and Models are both LOGICAL_TABLE to the API and
    # cleanup has to delete Models FIRST.
    results = import_tml(ctx.target, docs, create_new=True)
    failures = import_failures(results)
    if failures:
        raise StepFailed("scaffolding import failed:\n  " + "\n  ".join(failures))

    created = imported_guids(results)
    kinds = ctx.ledger.setdefault("kinds", {"tables": [], "models": []})
    for doc, item in zip(docs, results):
        guid = ((item.get("response") or {}).get("header") or {}).get("id_guid")
        if not guid:
            continue
        bucket = "tables" if "table" in doc else "models"
        if guid not in kinds[bucket]:
            kinds[bucket].append(guid)
    return created


def run_lift_content(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    """Lift bespoke content in dependency order: Views, then Answers, then Liveboards.

    References resolve to the scaffolding just imported. The importer tries the `fqn`
    (dead in the target) and falls back to the NAME, which is why names must be unique in
    the target Org.
    """
    created: Dict[str, str] = {}
    for kind, guids in step["batches"]:
        if not guids:
            continue
        docs = export_tml(ctx.source, guids)
        for doc in docs:
            doc.pop("guid", None)
        if ctx.dry_run:
            continue
        results = import_tml(ctx.target, docs, create_new=True)
        failures = import_failures(results)
        if failures:
            raise StepFailed(f"{kind} import failed:\n  " + "\n  ".join(failures))
        created.update(imported_guids(results))
    return created


def _rename_columns(doc: Dict[str, Any], renames: Dict[str, str]) -> int:
    """Rewrite `columns[].name` in place. Returns how many changed.

    Only `name` is touched -- `column_id` is the physical binding and anchors the
    dependents, so an in-place rename cascades to every Answer and Liveboard
    automatically. Touching `column_id` would make it a drop-and-add instead.
    """
    changed = 0
    for section in ("table", "model", "worksheet"):
        body = doc.get(section)
        if not isinstance(body, dict):
            continue
        for col in body.get("columns") or []:
            new = renames.get(col.get("name"))
            if new:
                col["name"] = new
                changed += 1
    return changed


def run_rename(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    """Rename scaffolding columns to the published names, once per column.

    Cascades to every dependent automatically (verified 2026-07-15), so this is
    O(columns), not O(objects) -- the reason the architecture works at all.
    """
    renames = step["renames"]
    if not renames:
        return {}
    lifted = ctx.created(STEP_LIFT_SCAFFOLDING)
    by_model: Dict[str, Dict[str, str]] = {}
    for model, tenant, target in renames:
        by_model.setdefault(model, {})[tenant] = target

    for model_name, mapping in sorted(by_model.items()):
        guid = lifted.get(model_name)
        if not guid:
            raise StepFailed(f"rename: no lifted object recorded for Model "
                             f"'{model_name}' -- re-run the lift step")
        if ctx.dry_run:
            continue
        docs = export_tml(ctx.target, [guid])
        if not docs:
            raise StepFailed(f"rename: could not export '{model_name}' ({guid})")
        doc = docs[0]
        if _rename_columns(doc, mapping) == 0:
            raise StepFailed(f"rename: none of {sorted(mapping)} matched a column of "
                             f"'{model_name}' -- the mapping is stale")
        doc["guid"] = guid
        results = import_tml(ctx.target, [doc], create_new=False)
        failures = import_failures(results)
        if failures:
            raise StepFailed(f"rename of '{model_name}' failed:\n  "
                             + "\n  ".join(failures))
    return {}


def rls_rule_counts(client, model_guid: str) -> Dict[str, int]:
    """`{table_name: rule_count}` for the tables under a Model.

    Read from the TARGET Org's session deliberately. A published object is Primary-owned
    but visible in the tenant Org, and reading it as the tenant reads what the tenant is
    actually bound to -- verified 2026-07-28 that this resolves.
    """
    docs = export_tml(client, [model_guid])
    if not docs:
        return {}
    body = docs[0].get("model") or docs[0].get("worksheet") or {}
    fqns = [t.get("fqn") for t in body.get("model_tables") or [] if t.get("fqn")]
    counts: Dict[str, int] = {}
    for doc in export_tml(client, fqns):
        table = doc.get("table") or {}
        rules = (table.get("rls_rules") or {}).get("rules") or []
        counts[table.get("name") or "?"] = len(rules)
    return counts


def run_repoint(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    """Move bespoke content off the scaffolding Models onto the published Models.

    A 1:1-by-name match, because the rename step already aligned the column names. The
    TML transform is `ts dependency`'s proven `apply_repoint` rather than a second
    implementation -- it already handles `search_query` sanitisation and dangling joins,
    which a fresh one would rediscover the hard way.
    """
    from ts_cli.dependency.mutate import apply_repoint
    from ts_cli.migrate import discover

    lifted = ctx.created(STEP_LIFT_SCAFFOLDING)
    content = ctx.created(STEP_LIFT_CONTENT)
    if not content:
        return {}

    repointed = 0
    for name, source_guid in sorted(lifted.items()):
        target_guid = discover.find_model_by_name(ctx.target, name)
        if not target_guid or target_guid == source_guid:
            raise StepFailed(
                f"repoint: no published Model named '{name}' in the target Org. The "
                f"published Model must exist before content can be moved onto it")
        if ctx.dry_run:
            continue
        # Checked HERE, immediately before content is bound to the shared Model -- the
        # one moment where an unfiltered target stops being theoretical.
        problem = unfiltered_target_problem(rls_rule_counts(ctx.target, target_guid),
                                            name, allow=ctx.allow_unfiltered)
        if problem:
            raise StepFailed(f"repoint refused: {problem}")
        docs = export_tml(ctx.target, sorted(content.values()))
        updated = []
        for doc in docs:
            guid = doc.get("guid")
            new_doc = apply_repoint(doc, source_guid=source_guid, target_guid=target_guid,
                                    target_name=name, column_gap=[])
            if new_doc != doc:
                new_doc["guid"] = guid
                updated.append(new_doc)
        if updated:
            results = import_tml(ctx.target, updated, create_new=False)
            failures = import_failures(results)
            if failures:
                raise StepFailed("repoint failed:\n  " + "\n  ".join(failures))
            repointed += len(updated)
    return {}


def _delete(client, guids: List[str], obj_type: str) -> Optional[str]:
    if not guids:
        return None
    resp = client.post("/api/rest/2.0/metadata/delete", raise_for_status=False,
                       json={"metadata": [{"identifier": g, "type": obj_type}
                                          for g in guids]})
    if resp.status_code >= 300:
        return f"HTTP {resp.status_code} {resp.text[:250]}"
    return None


def run_cleanup_models(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    """Delete the scaffolding Models.

    **A refusal here is the check working, not an error to force past.** By this point
    the repoint has run, so nothing should reference the scaffolding; a Model that still
    has dependents means a repoint was missed, and those objects would be orphaned. This
    is the reason cleanup is surgical rather than a wholesale Org delete, which would
    take the un-repointed content silently.
    """
    if ctx.dry_run:
        return {}
    problem = _delete(ctx.target, sorted(_lifted_of_kind(ctx, "models")), "LOGICAL_TABLE")
    if problem:
        raise StepFailed(
            f"scaffolding Model delete refused ({problem}).\nThis is very likely a MISSED "
            f"REPOINT: content still references the scaffolding. Find it before forcing "
            f"anything -- deleting past this orphans that content.")
    return {}


def _lifted_of_kind(ctx: Ctx, kind: str) -> set:
    """GUIDs the lift recorded. Tables and Models are both LOGICAL_TABLE to the API, so
    the plan's own lists are the only way to tell them apart."""
    return set((ctx.ledger.get("kinds") or {}).get(kind, []))


def run_cleanup_tables(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    if ctx.dry_run:
        return {}
    tables = sorted(_lifted_of_kind(ctx, "tables"))
    problem = _delete(ctx.target, tables, "LOGICAL_TABLE")
    if problem:
        raise StepFailed(f"scaffolding Table delete refused ({problem})")
    return {}


def run_cleanup_connection(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    """Delete the connection this migration provisioned. Last, because deletion does not
    cascade to Tables -- they had to go first."""
    if ctx.dry_run:
        return {}
    resp = ctx.target.post(
        f"/api/rest/2.0/connections/{step['connection']}/delete",
        raise_for_status=False, json={})
    if resp.status_code >= 300:
        raise StepFailed(f"connection delete refused: HTTP {resp.status_code} "
                         f"{resp.text[:200]}. Its Tables must be gone first")
    return {}


RUNNERS = {
    STEP_BACKUP: run_backup,
    STEP_LIFT_SCAFFOLDING: run_lift_scaffolding,
    STEP_LIFT_CONTENT: run_lift_content,
    STEP_RENAME: run_rename,
    STEP_REPOINT: run_repoint,
    STEP_CLEANUP_MODELS: run_cleanup_models,
    STEP_CLEANUP_TABLES: run_cleanup_tables,
    STEP_CLEANUP_CONNECTION: run_cleanup_connection,
}
