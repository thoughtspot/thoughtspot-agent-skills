"""Phase 2 executor — the I/O half of `ts migrate apply`.

Pure planning lives in `apply_plan.py`, the pure transform in `rewrite.py`; this module
runs them. The split keeps the ordering, validation and rewrite rules -- the parts that
encode live findings -- testable without a cluster.

Each `run_*` takes `(ctx, step)` and returns `{name: guid}` for the ledger, raising
`StepFailed` with an actionable message on anything it cannot complete.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ts_cli.migrate.apply_plan import (STEP_BACKUP, STEP_MOVE_SHIELDED,
                                       STEP_REWRITE_CONTENT, STEP_REWRITE_VIEWS,
                                       STEP_SHARE, bound_variable_names,
                                       segmentation_for_target,
                                       unfiltered_target_problem)
from ts_cli.migrate.rewrite import residual_references, rewrite_content, rewrite_view


class StepFailed(Exception):
    """A step could not complete. The message is shown to the operator verbatim."""


class Ctx:
    """Everything a step needs: both clients, the plan directory, and the live ledger."""

    def __init__(self, source_client, target_client, plan_dir: Path,
                 ledger: Dict[str, Any], dry_run: bool = False,
                 allow_unfiltered: bool = False, unscoped_client=None):
        self.source = source_client
        self.target = target_client
        # A session NOT scoped to any Org. Required for the segmentation check: an
        # Org-scoped variable read returns only THAT Org's value, so from inside the
        # target every variable looks like it has one value -- and every target looks
        # SHARED. Same trap as `tenancy._groups_in_org`. Falls back to the target client,
        # which yields UNKNOWN rather than a false pass.
        self.unscoped = unscoped_client or target_client
        self.plan_dir = plan_dir
        self.ledger = ledger
        self.dry_run = dry_run
        # Only ever set by an explicit --allow-unfiltered-target. Defaulting it True would
        # turn the tenant-isolation check into a no-op for everyone who never reads the
        # flag list.
        self.allow_unfiltered = allow_unfiltered

    def created(self, step: str) -> Dict[str, str]:
        return (self.ledger.get("created") or {}).get(step, {})


# ---------------------------------------------------------------------------
# TML helpers
# ---------------------------------------------------------------------------

def export_tml(client, guids: List[str]) -> List[Dict[str, Any]]:
    """Export a batch as parsed JSON documents. One call: calls scale with batches
    rather than objects, which is the round-trip budget the design is built on."""
    if not guids:
        return []
    resp = client.post("/api/rest/2.0/metadata/tml/export",
                       json={"metadata": [{"identifier": g} for g in guids],
                             "edoc_format": "JSON", "export_fqn": True})
    return [json.loads(i["edoc"]) for i in resp.json() if i.get("edoc")]


def import_tml(client, docs: List[Dict[str, Any]], *, create_new: bool
               ) -> List[Dict[str, Any]]:
    """Import a batch all-or-none and return the per-item outcomes.

    ALL_OR_NONE because a partial content import leaves the tenant with some objects
    migrated and some not, which is harder to reason about than none.
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
    out = {}
    for item in results or []:
        header = ((item.get("response") or {}).get("header") or {})
        if header.get("name") and header.get("id_guid"):
            out[header["name"]] = header["id_guid"]
    return out


def model_table_docs(client, model_guid: str) -> List[Dict[str, Any]]:
    """The exported TML of every Table under a Model, in two batched calls.

    Read through the TARGET Org's session: a published object is Primary-owned but
    visible in the tenant Org, and reading it as the tenant reads what the tenant is
    actually bound to (verified 2026-07-28). One export feeds BOTH tenant-isolation
    reads -- the RLS rule counts and the `${var}` publication bindings -- so the two
    checks cannot diverge on what they looked at.
    """
    docs = export_tml(client, [model_guid])
    if not docs:
        return []
    body = docs[0].get("model") or docs[0].get("worksheet") or {}
    fqns = [t.get("fqn") for t in body.get("model_tables") or [] if t.get("fqn")]
    return export_tml(client, fqns)


def rls_rule_counts_from_docs(table_docs: List[Dict[str, Any]]) -> Dict[str, int]:
    """`{table_name: rule_count}` from already-exported Table documents."""
    counts: Dict[str, int] = {}
    for doc in table_docs:
        table = doc.get("table") or {}
        counts[table.get("name") or "?"] = len((table.get("rls_rules") or {})
                                               .get("rules") or [])
    return counts


def rls_rule_counts(client, model_guid: str) -> Dict[str, int]:
    """`{table_name: rule_count}` for the tables under a Model."""
    return rls_rule_counts_from_docs(model_table_docs(client, model_guid))


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def run_backup(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    """Export every in-scope object before anything is written.

    All-or-nothing: nothing is saved if any export fails. A partial backup is worse than
    none -- it reads as a safety net that is not there. In a same-Org run it IS the
    rollback, so this is the step that makes that topology survivable at all.
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


def publication_variables(client) -> List[Dict[str, Any]]:
    """Template variables with their per-Org values.

    **Must be called with an UNSCOPED client.** An Org-scoped session returns only that
    Org's value for each variable (verified live 2026-07-28), so the caller sees one
    distinct value and concludes the Orgs share data -- when they may be pointed at
    entirely different schemas. Segmentation is a cross-Org question and cannot be
    answered from inside one Org.

    Needed because **RLS only matters when publication resolves every Org to the same
    physical table**. A `TABLE_MAPPING` variable holding a different value per Org points
    each tenant at its own database or schema, and demanding RLS on top of that would be
    a false alarm -- worse than no check, because it teaches operators to pass the
    override reflexively.
    """
    resp = client.post("/api/rest/2.0/template/variables/search", raise_for_status=False,
                       json={"response_content": "METADATA_AND_VALUES", "record_size": -1})
    if resp.status_code >= 300:
        return []
    body = resp.json()
    return body if isinstance(body, list) else []


def _assert_tenants_separated(ctx: Ctx, target: Dict[str, str]) -> None:
    """Refuse to bind tenant content to a Model that separates no tenants.

    Checks how the Orgs are separated FIRST, and only falls back to requiring RLS when
    they genuinely share physical data.
    """
    guid = target.get("guid")
    if not guid or ctx.dry_run:
        return
    # One export feeds both halves of the check. The variables read stays UNSCOPED
    # (values are a cross-Org question) but is then filtered to the variables the
    # target's tables actually bind -- an unrelated programme's per-Org variable must
    # not vouch for THIS target's segmentation (audit 2026-07-29 finding 17.4). The
    # cluster read is skipped entirely when nothing is bound.
    docs = model_table_docs(ctx.target, guid)
    variables = (publication_variables(ctx.unscoped)
                 if bound_variable_names(docs) else [])
    segmentation = segmentation_for_target(docs, variables, target.get("org"))
    problem = unfiltered_target_problem(rls_rule_counts_from_docs(docs),
                                        target.get("name", guid),
                                        allow=ctx.allow_unfiltered,
                                        segmentation=segmentation)
    if problem:
        raise StepFailed(f"refused: {problem}")


def _rewrite_batch(ctx: Ctx, step: Dict[str, Any], transform) -> Dict[str, str]:
    """Export, rewrite, import -- the whole migration for one class of object."""
    objects = step["objects"]
    if not objects:
        return {}
    columns = step["columns"]
    target = step["target"]
    mode = step["mode"]

    _assert_tenants_separated(ctx, target)

    guids = [o["guid"] for o in objects]
    docs = export_tml(ctx.source, guids)
    if len(docs) != len(guids):
        raise StepFailed(f"exported {len(docs)} of {len(guids)} object(s); refusing to "
                         f"migrate a partial set")

    # Views the content batch's mixed dependents may ALSO read (an Answer on the
    # migrating Model and a View at once -- classify_dependent charges it as content).
    # Their View reference must follow the View created by rewrite_views, not stay on
    # the source View's guid, and must never be rebound to the published Model.
    view_remap = _view_guid_remap(ctx, objects) if transform is rewrite_content else {}

    rewritten = []
    for doc in docs:
        out = transform(doc, columns, target["guid"], target.get("name"),
                        target.get("source_guid"))
        if view_remap:
            out = _repoint_fqns(out, view_remap)
        # The completeness gate, per object. A partial rewrite imports cleanly and
        # RENDERS WRONG, so this is checked before writing rather than discovered by a
        # user later.
        residual = residual_references(out, columns)
        if residual:
            paths = "; ".join(f"{p} = {v[:60]}" for p, v in residual[:4])
            raise StepFailed(
                f"rewrite incomplete for '{_doc_name(out)}': {len(residual)} source "
                f"column reference(s) survive -- {paths}. Importing this would produce an "
                f"object that loads but renders wrong. This is a gap in the rewrite's "
                f"field coverage, not a data problem")
        if mode.get("keep_guid"):
            out["guid"] = doc.get("guid")
        else:
            out.pop("guid", None)
        rewritten.append(out)

    if ctx.dry_run:
        return {}
    results = import_tml(ctx.target, rewritten, create_new=mode["create_new"])
    failures = import_failures(results)
    if failures:
        raise StepFailed("import failed:\n  " + "\n  ".join(failures))
    return imported_guids(results)


def _doc_name(doc: Dict[str, Any]) -> str:
    for key in ("liveboard", "answer", "view", "model", "worksheet", "table"):
        body = doc.get(key)
        if isinstance(body, dict) and body.get("name"):
            return body["name"]
    return doc.get("guid", "<unnamed>")


def run_rewrite_views(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    """Repoint Views, PRESERVING what they expose.

    Rewriting `search_output_column` while leaving `view_columns[].name` means the View
    reads the published Model while exposing the same names -- so every Answer and
    Liveboard built on it needs no migration at all. Proven end to end 2026-07-28,
    including that the untouched content still returns data.

    Views go first so that in a new-Org run they exist before anything references them.
    """
    return _rewrite_batch(ctx, step, rewrite_view)


def run_rewrite_content(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    """Rewrite Answers and Liveboards onto the published Model.

    Only content NOT already shielded by a View is here: rewriting a shielded object
    again would be work that can only introduce error.
    """
    return _rewrite_batch(ctx, step, rewrite_content)


def _view_guid_remap(ctx: Ctx, objects: List[Dict[str, Any]]) -> Dict[str, str]:
    """`{source View guid -> target View guid}` for the Views these objects sit on.

    Matched by View NAME, which `rewrite_views` recorded in the ledger. The source guid is
    dead in the target, so the name is the only bridge.
    """
    created_views = ctx.created(STEP_REWRITE_VIEWS)
    refs = sorted({r for o in objects for r in o.get("source_refs") or []})
    remap: Dict[str, str] = {}
    for doc in export_tml(ctx.source, refs):
        new_guid = created_views.get((doc.get("view") or {}).get("name"))
        if doc.get("guid") and new_guid:
            remap[doc["guid"]] = new_guid
    return remap


def run_move_shielded(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    """Copy View-shielded content into the target, repointing it at the NEW View.

    Its columns are **not** rewritten -- the View's exposed names did not change, which is
    the whole point of the shield. But in a new-Org run the content still has to exist
    over there, and its `tables[].fqn` still points at the SOURCE View's guid, which is
    dead in the target.

    Omitting this step is silent data loss: the tenant's Answer simply would not appear.
    Observed live 2026-07-28.
    """
    objects = step["objects"]
    if not objects or ctx.dry_run:
        return {}

    remap = _view_guid_remap(ctx, objects)
    guids = [o["guid"] for o in objects]
    docs = export_tml(ctx.source, guids)
    if len(docs) != len(guids):
        raise StepFailed(f"exported {len(docs)} of {len(guids)} shielded object(s); "
                         f"refusing to move a partial set")

    moved = []
    for doc in docs:
        unresolved = [r for r in _table_fqns(doc) if r not in remap]
        if unresolved:
            raise StepFailed(
                f"'{_doc_name(doc)}' sits on a View that was not migrated "
                f"({', '.join(unresolved)}). Moving it would leave it bound to an object "
                f"that does not exist in the target")
        out = _repoint_fqns(doc, remap)
        out.pop("guid", None)
        moved.append(out)

    results = import_tml(ctx.target, moved, create_new=True)
    failures = import_failures(results)
    if failures:
        raise StepFailed("shielded-content move failed:\n  " + "\n  ".join(failures))
    return imported_guids(results)


def _table_fqns(doc: Dict[str, Any]) -> List[str]:
    out: List[str] = []

    def walk(node, key=None):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            if key == "tables":
                out.extend(e["fqn"] for e in node
                           if isinstance(e, dict) and e.get("fqn"))
            else:
                for v in node:
                    walk(v, key)

    walk(doc)
    return out


def _repoint_fqns(doc: Dict[str, Any], remap: Dict[str, str]) -> Dict[str, Any]:
    """Swap each `tables[].fqn` for its target-Org equivalent, leaving names alone."""
    def walk(node, key=None):
        if isinstance(node, dict):
            return {k: walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            if key == "tables":
                out = []
                for e in node:
                    if isinstance(e, dict) and e.get("fqn") in remap:
                        e = dict(e)
                        e["fqn"] = remap[e["fqn"]]
                    out.append(e)
                return out
            return [walk(v, key) for v in node]
        return node
    return walk(doc)


def source_group_grants(client, objects: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """`{object name: [group names]}` for the GROUP grants on the source objects.

    Group level only, deliberately. A per-user grant cannot reliably be applied before
    cutover -- the users may not be in the target Org yet -- and group membership is where
    a tenant's access is actually administered.

    Reads through `share_plan.permission_rows`, which encodes the gotcha that a landed
    share shows in `permission` and NOT in `shared_permission`.
    """
    from ts_cli.share_plan import permission_rows

    out: Dict[str, List[str]] = {}
    for obj in objects:
        resp = client.post("/api/rest/2.0/security/metadata/fetch-permissions",
                           raise_for_status=False,
                           json={"metadata": [{"identifier": obj["guid"],
                                               "type": obj.get("type") or "ANSWER"}]})
        if resp.status_code >= 300:
            continue
        groups = sorted({r["principal_name"] for r in permission_rows(resp.json())
                         if r.get("principal_type") == "USER_GROUP"
                         and r.get("permission") not in (None, "", "NO_ACCESS")})
        if groups:
            out[obj.get("name") or obj["guid"]] = groups
    return out


def target_stack(client, model_guid: str) -> List[Dict[str, str]]:
    """The published Model and its Tables, bottom-up: Tables first, then the Model.

    Order is load-bearing. Under **Strict Object Mode** a user needs a grant on the whole
    chain, and a grant applied to something whose source is ungranted is **accepted and
    silently dropped** -- `HTTP 204`, no row recorded (verified live 2026-07-28 on a cluster
    with the mode ON; it is a per-cluster setting, and granting the stack is harmless when
    it is off).
    """
    docs = export_tml(client, [model_guid])
    if not docs:
        return []
    body = docs[0].get("model") or docs[0].get("worksheet") or {}
    tables = [t.get("fqn") for t in body.get("model_tables") or [] if t.get("fqn")]
    return ([{"guid": g, "type": "LOGICAL_TABLE"} for g in tables]
            + [{"guid": model_guid, "type": "LOGICAL_TABLE"}])


def run_share_grants(ctx: Ctx, step: Dict[str, Any]) -> Dict[str, str]:
    """Grant the tenant's groups access to the WHOLE object stack, bottom-up.

    Two facts make this more than sharing the content:

    1. **Publication makes an object present, not visible.** The published Model carries no
       tenant grants of its own, so publishing it does not let the tenant's users read it.
    2. **Strict Object Mode requires the whole chain** -- Table, then Model, then content.
       A grant on content whose Model is ungranted is accepted and **silently dropped**:
       `HTTP 204` with no row recorded. Strict Object Mode is a **per-cluster setting**, so
       this is not universal -- but granting the stack is **safe either way**, since with
       the mode off the extra grants are merely redundant. Hence no mode detection.

    So this grants published Tables, then the published Model, then the migrated content.
    Sharing only the content -- which is what this step did originally -- produced a
    migration that reported success while the tenant saw nothing (BL-150).
    """
    objects = step["objects"]
    if not objects or ctx.dry_run:
        return {}

    wanted = source_group_grants(ctx.source, objects)
    if not wanted:
        print("  share_grants: no group grants on the source objects -- nothing to "
              "re-establish", file=__import__("sys").stderr)
        return {}
    # The UNION of the tenant's groups -- correct for the SHARED STACK only (every group
    # needs the whole Table -> Model -> View chain, or its content grant is silently
    # dropped). Content gets its own source object's groups, never the union: an Answer
    # shared only with Finance must not become visible to HR because some other migrated
    # object was (audit 2026-07-29 finding 17.5).
    groups = sorted({g for gs in wanted.values() for g in gs})

    target = step.get("target") or {}
    # Bottom-up, and the ORDER IS THE FIX: published Tables, published Model, migrated
    # Views, then content. A grant on anything whose source is ungranted is accepted and
    # SILENTLY DROPPED, so each layer must already be granted before the next is applied.
    # Missing the Views cost a second round of this bug: the Answer built on a View was
    # dropped exactly as the Answer on the Model had been.
    stack = target_stack(ctx.target, target["guid"]) if target.get("guid") else []
    stack += [{"guid": guid, "type": "LOGICAL_TABLE"}
              for guid in sorted(ctx.created(STEP_REWRITE_VIEWS).values())]
    created = {**ctx.created(STEP_REWRITE_CONTENT), **ctx.created(STEP_MOVE_SHIELDED)}
    # (item, groups-for-item): the stack takes the union; each content object takes
    # exactly its own source object's groups, matched by name -- `wanted` and `created`
    # are both keyed by object name.
    grants = [(item, groups) for item in stack]
    grants += [({"guid": guid, "type": _type_of(objects, name)}, wanted.get(name) or ())
               for name, guid in sorted(created.items())]

    failures, applied = _apply_grants(ctx.target, grants)
    if failures:
        raise StepFailed(
            f"applied {applied} grant(s), but these failed: {', '.join(failures)}. "
            f"Groups are PER-ORG principals, so the target Org needs a group of each name "
            f"(provision it with `ts tenancy`)")
    print(f"  share_grants: {applied} grant(s) across {len(stack)} stack object(s) and "
          f"{len(created)} content object(s)", file=__import__("sys").stderr)
    return {}


def _apply_grants(client, grants) -> "tuple[List[str], int]":
    """Apply `(item, groups)` READ_ONLY grants, collecting failures rather than
    stopping -- an aborted grant pass strands every layer after it."""
    failures: List[str] = []
    applied = 0
    for item, item_groups in grants:
        for group in item_groups:
            resp = client.post(
                "/api/rest/2.0/security/metadata/share", raise_for_status=False,
                json={"metadata_type": item["type"],
                      "metadata_identifiers": [item["guid"]],
                      "permissions": [{"principal": {"type": "USER_GROUP",
                                                     "identifier": group},
                                       "share_mode": "READ_ONLY"}],
                      "message": "Re-established by ts migrate apply",
                      "notify_on_share": False})
            if resp.status_code >= 300:
                failures.append(f"{item['guid']} -> {group} (HTTP {resp.status_code})")
            else:
                applied += 1
    return failures, applied


def _type_of(objects: List[Dict[str, Any]], name: str) -> str:
    for obj in objects:
        if (obj.get("name") or obj["guid"]) == name:
            return obj.get("type") or "ANSWER"
    return "ANSWER"


RUNNERS = {
    STEP_BACKUP: run_backup,
    STEP_REWRITE_VIEWS: run_rewrite_views,
    STEP_REWRITE_CONTENT: run_rewrite_content,
    STEP_MOVE_SHIELDED: run_move_shielded,
    STEP_SHARE: run_share_grants,
}
