"""Apply-plan assembly for Orgs Publishing.

Split from `publish_plan.py` under the file-size gate: that module owns
discovery (field-variance clustering) and the value matrix; this one owns the
multi-root closure merge and turning a closure plus a matrix into an ordered,
reversible plan.

Re-exported from `publish_plan` so callers keep one import site.

Pure functions, no I/O.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from ts_cli.publish_plan import build_clusters


# TML export reports the root's kind in lower case; the publish API wants its own
# enum. Everything in the data layer (model / worksheet / table / view) publishes
# as LOGICAL_TABLE.
_ROOT_TYPE_TO_PUBLISH_TYPE = {
    "liveboard": "LIVEBOARD",
    "pinboard": "LIVEBOARD",
    "answer": "ANSWER",
}


def publish_type_for_root(root_type: Optional[str]) -> str:
    """Map an exported root's type to the publish API's metadata type.

    Falls back to LOGICAL_TABLE, which covers Models, Worksheets, Tables and
    Views, and is the safe default for an unrecognised kind.
    """
    return _ROOT_TYPE_TO_PUBLISH_TYPE.get((root_type or "").lower(), "LOGICAL_TABLE")


def merge_closures(closures: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Combine several single-root closures into one multi-root closure.

    A publish job is usually several objects, not one: cascade carries
    dependencies DOWNWARD automatically but never reaches siblings, so an Answer
    beside a Liveboard on the same Model has to be published in its own right.

    Tables are de-duplicated by GUID, because two roots on one Model resolve the
    same Tables and parameterizing them twice would bind a second variable over
    the first. Clustering then runs once across the union, so two roots sharing a
    schema value still produce one variable rather than one each.

    Pure — no I/O.
    """
    closures = list(closures)
    if not closures:
        raise ValueError("Provide at least one closure to merge")

    tables: Dict[str, Dict[str, Any]] = {}
    roots: List[Dict[str, Any]] = []
    existing: Set[str] = set()
    for closure in closures:
        roots.append(closure["root"])
        for table in closure.get("tables") or []:
            tables.setdefault(table["guid"], table)
        existing.update(closure.get("existing_variables") or ())

    merged_tables = list(tables.values())
    return {
        "roots": roots,
        "tables": merged_tables,
        "clusters": build_clusters(merged_tables, existing_variables=existing),
        "connections": sorted({t["connection"] for t in merged_tables if t.get("connection")}),
        "existing_variables": sorted(existing),
        "owner_org": next((c.get("owner_org") for c in closures if c.get("owner_org")), None),
        "unparameterizable_tables": sorted(
            {t["name"] for t in merged_tables if not t.get("connection")}),
    }


def publish_targets(closure: Dict[str, Any]) -> List[Dict[str, str]]:
    """One `{identifier, type}` entry per root, in the order given.

    Each root carries its own publish type, since a set can mix a Liveboard, an
    Answer and a Model.
    """
    return [{"identifier": r["guid"], "type": publish_type_for_root(r.get("type"))}
            for r in _roots_of(closure)]


def _roots_of(closure: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Roots of a closure, accepting the single-root shape as well."""
    if closure.get("roots"):
        return closure["roots"]
    return [closure["root"]] if closure.get("root") else []


def _variable_steps(variables, originals, object_type):
    """Split the matrix's variables into create / parameterize / rollback steps.

    A field already bound to a token is skipped in both directions: there is
    nothing to do, and nothing to undo. Only variables this run creates are
    recorded for deletion, so one shared with another Model survives a rollback.
    """
    create: List[Dict[str, Any]] = []
    parameterize: List[Dict[str, Any]] = []
    rollback_fields: List[Dict[str, Any]] = []

    for variable in variables:
        name, field = variable["name"], variable["field"]
        if not variable.get("exists"):
            create.append({"name": name, "type": variable.get("type", "TABLE_MAPPING"),
                           "sensitive": bool(variable.get("sensitive"))})
        for guid in variable.get("tables") or []:
            current = ((originals.get(guid) or {}).get(field) or {})
            if current.get("variable"):
                continue
            parameterize.append({"metadata_identifier": guid, "metadata_type": object_type,
                                 "field_names": [field], "variable": name})
            rollback_fields.append({"metadata_identifier": guid, "metadata_type": object_type,
                                    "field_name": field, "original_value": current.get("value")})
    return create, parameterize, rollback_fields


def build_apply_plan(
    closure: Dict[str, Any],
    matrix: Dict[str, Any],
    *,
    publish_orgs: Optional[List[str]] = None,
    object_type: str = "LOGICAL_TABLE",
) -> Dict[str, Any]:
    """Turn a closure plus a value matrix into an ordered plan and a rollback record.

    Order matters and is not negotiable: a variable must exist before it can take
    a value, and must have a value in every target Org before anything using it is
    published (publish fails closed otherwise).

    The rollback record captures each field's ORIGINAL static value, because
    ``unparameterize`` substitutes a value rather than clearing the field. Without
    it there is no way back. Only variables this run creates are listed for
    deletion, so an existing variable shared with another Model is never removed.

    Pure — no I/O.
    """
    originals: Dict[str, Dict[str, Any]] = {
        t["guid"]: (t.get("fields") or {}) for t in closure.get("tables") or []
    }

    create, parameterize, rollback_fields = _variable_steps(
        matrix.get("variables") or [], originals, object_type)

    # One publish call per type: the API takes a single `type` per request, and a
    # selection can mix a Liveboard, an Answer and a Model.
    publish: Optional[List[Dict[str, Any]]] = None
    if publish_orgs:
        grouped: Dict[str, List[str]] = {}
        for target in publish_targets(closure):
            grouped.setdefault(target["type"], []).append(target["identifier"])
        publish = [{"identifiers": ids, "type": typ, "orgs": list(publish_orgs)}
                   for typ, ids in grouped.items()]

    return {
        "create_variables": create,
        "assign_values": list(matrix.get("assignments") or []),
        "parameterize": parameterize,
        "publish": publish,
        "rollback": {
            "created_variables": [c["name"] for c in create],
            "parameterized": rollback_fields,
            "published": publish,
        },
    }


def rollback_steps(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Order the undo actions for a rollback record.

    Reverse of apply: unpublish first (while the objects still resolve), then
    unparameterize back to the recorded static values, then delete the variables
    this run created — a variable cannot be deleted while still bound.

    A field with no recorded original value is skipped and reported, since
    ``unparameterize`` cannot run without one.
    """
    steps: List[Dict[str, Any]] = []
    published = record.get("published")
    # A record written before multi-root support holds a single dict; newer ones
    # hold one entry per publish type. Accept both so old records still replay.
    if isinstance(published, dict):
        published = [published]
    for entry in published or []:
        steps.append({"action": "unpublish", **entry})
    for field in record.get("parameterized") or []:
        if field.get("original_value") in (None, ""):
            steps.append({"action": "skip", "reason": "no recorded original value",
                          "metadata_identifier": field.get("metadata_identifier"),
                          "field_name": field.get("field_name")})
            continue
        steps.append({"action": "unparameterize", **field})
    if record.get("created_variables"):
        steps.append({"action": "delete_variables", "names": list(record["created_variables"])})
    return steps
