"""Publish planning engine — field-variance clustering for Orgs Publishing.

Pure functions, no I/O, so the planning logic is unit-testable without a live
instance. The I/O wrapper is `ts publish export` in `commands/publish.py`.

The shape of this module follows directly from two behaviours verified live on
2026-07-25 (see docs/superpowers/specs/2026-07-25-ts-publish-orgs-design.md §2.5):

1. A variable holds exactly ONE value per scope.
2. `field_names[]` on parameterize-fields writes the SAME `${token}` into every
   field listed.

Together those mean the unit of parameterization is a **distinct value**, not a
field and not a table. Twenty tables sharing one schema need one schema
variable, not twenty. Clustering by (field, current value) recovers exactly that
set, so each cluster maps one-to-one onto a variable to create.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set

# Table TML key -> the field name the parameterize API expects.
TML_KEY_TO_FIELD = {
    "db": "databaseName",
    "schema": "schemaName",
    "db_table": "tableName",
}

# Short suffix used when naming a suggested variable.
_FIELD_SUFFIX = {
    "databaseName": "db",
    "schemaName": "schema",
    "tableName": "table",
}

# databaseName and schemaName are the conventional per-tenant discriminators.
# tableName is almost never one — tenant tables normally share a name — and it
# also never clusters across tables, since each table has its own. Recommended
# is a default for the review step, not a restriction: the caller can override.
_RECOMMENDED_FIELDS = ("databaseName", "schemaName")

_TOKEN_RE = re.compile(r"^\$\{([^}\s]+)\}$")


def parse_variable_token(value: Optional[str]) -> Optional[str]:
    """Return the variable name when ``value`` is entirely a ``${var}`` token.

    A partial token (``prefix_${x}``) does not count: parameterization replaces
    the whole field value, so anything else is a static string that merely looks
    token-ish.
    """
    if not isinstance(value, str):
        return None
    match = _TOKEN_RE.match(value.strip())
    return match.group(1) if match else None


def slugify(text: str) -> str:
    """Lower-case, underscore-separated identifier fragment."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", (text or "").lower())).strip("_")


def extract_table_fields(table_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce one exported Table TML document to its parameterizable fields.

    Input is ``{"guid": ..., "table": {...}}`` as produced by a TML export.
    Output is ``{"guid", "name", "connection", "fields": {<field>: {"value",
    "variable"}}}`` where ``variable`` is set when the field already carries a
    token.
    """
    table = table_doc.get("table") or {}
    fields: Dict[str, Dict[str, Any]] = {}
    for tml_key, field_name in TML_KEY_TO_FIELD.items():
        raw = table.get(tml_key)
        fields[field_name] = {"value": raw, "variable": parse_variable_token(raw)}
    return {
        "guid": table_doc.get("guid"),
        "name": table.get("name"),
        "connection": (table.get("connection") or {}).get("name"),
        "fields": fields,
    }


def suggest_variable_name(
    connection: Optional[str], field: str, value: str, taken: Set[str], *, disambiguate: bool,
) -> str:
    """Propose a unique variable name for one cluster.

    Base form is ``{connection}_{db|schema|table}``. When a field has more than
    one distinct value across the closure the value is folded in, so
    ``apj_sales_schema`` and ``apj_shared_ref_schema`` stay distinct and
    self-describing. A numeric suffix breaks any remaining collision, including
    against variables that already exist on the instance — names are unique
    instance-wide, so `create` fails on a duplicate.
    """
    conn = slugify(connection or "ts")
    suffix = _FIELD_SUFFIX.get(field, slugify(field))
    parts = [conn, slugify(value), suffix] if disambiguate else [conn, suffix]
    base = "_".join(p for p in parts if p)

    candidate = base
    counter = 2
    while candidate in taken:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def build_clusters(
    tables: Iterable[Dict[str, Any]], existing_variables: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Group parameterizable fields by distinct current value.

    One cluster per (field, current value) pair. Each cluster is one variable:
    every table listed in it needs the same value for that field, so they share
    a variable rather than getting one each.

    A field that already carries a token clusters separately from a static one
    with the same effective value, and gets no fresh suggestion — it is already
    wired.

    Fields with no value at all are skipped.
    """
    taken: Set[str] = set(existing_variables or ())
    tables = list(tables)

    # (field, raw value) -> cluster under construction, insertion-ordered so the
    # output is stable for a given input.
    grouped: Dict[tuple, Dict[str, Any]] = {}
    for table in tables:
        for field, info in (table.get("fields") or {}).items():
            value = info.get("value")
            if value is None or value == "":
                continue
            key = (field, value)
            cluster = grouped.setdefault(key, {
                "field": field,
                "current_value": value,
                "variable": info.get("variable"),
                "already_parameterized": info.get("variable") is not None,
                "tables": [],
                "table_names": [],
                "connection": table.get("connection"),
            })
            cluster["tables"].append(table.get("guid"))
            cluster["table_names"].append(table.get("name"))

    # A field needs its value folded into the suggested name only when that field
    # carries more than one distinct value across the closure.
    values_per_field: Dict[str, Set[str]] = {}
    for field, value in grouped:
        values_per_field.setdefault(field, set()).add(value)

    clusters: List[Dict[str, Any]] = []
    for cluster in grouped.values():
        field = cluster["field"]
        cluster["spans_tables"] = len(cluster["tables"])
        # A table with no connection block is Falcon-backed (ThoughtSpot's own
        # in-memory store). Those are the "default system tables" the docs say
        # cannot be parameterized, so proposing a variable for one would be a
        # dead end. Flag rather than drop, so the caller can explain why.
        cluster["parameterizable"] = cluster["connection"] is not None
        cluster["recommended"] = field in _RECOMMENDED_FIELDS and cluster["parameterizable"]
        if cluster["already_parameterized"]:
            cluster["suggested_variable"] = None
        else:
            name = suggest_variable_name(
                cluster["connection"], field, cluster["current_value"], taken,
                disambiguate=len(values_per_field[field]) > 1,
            )
            taken.add(name)
            cluster["suggested_variable"] = name
        clusters.append(cluster)
    return clusters
