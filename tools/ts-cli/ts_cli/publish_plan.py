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


def published_org_ids(header: Dict[str, Any]) -> List[Any]:
    """The Org ids an object is published INTO, read from one ``metadata_header``.

    THE one place this field's semantics are stated. ``metadata_header.orgIds`` lists
    the OWNING Org plus every Org the object is published to, so ``ownerOrgId`` is
    excluded here and the result means "additionally visible in": an empty list is an
    object that is published nowhere. Reading it needs no per-Org authentication, which
    is why publication state is answerable from the Primary Org.

    Restating that reading at each call site is how it diverged before: `ts publish
    status` excluded the owner and `ts security column-rules` did not, so on an
    Orgs-enabled cluster every table read as published. Both now call this.

    Ids come back exactly as the platform gave them, uncoerced, so a caller can map them
    against an Org index (and one that only needs "is it published" can take the truth
    value).

    Pure -- no I/O.
    """
    owner_org_id = header.get("ownerOrgId")
    return [org_id for org_id in (header.get("orgIds") or []) if org_id != owner_org_id]


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


# ---------------------------------------------------------------------------
# Manifest parsing — file and DB-table driven selection
# ---------------------------------------------------------------------------

_TRUTHY = {"true", "t", "yes", "y", "1"}


def _lower_keys(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a row's headers. A DB cursor returns them upper-case; a CSV
    written by hand rarely does."""
    return {str(k).strip().lower(): v for k, v in (row or {}).items()}


def parse_object_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parse a publication manifest of objects to publish.

    Columns: ``identifier`` (required), ``type`` (optional; inferred from the
    object when omitted), ``with_dependents`` (optional; expand upward to the
    Answers and Liveboards riding on this object).

    De-duplicated on identifier with order preserved, so a manifest that lists an
    object twice does not publish it twice.
    """
    parsed: Dict[str, Dict[str, Any]] = {}
    for raw in rows or ():
        row = _lower_keys(raw)
        identifier = str(row.get("identifier") or "").strip()
        if not identifier:
            raise ValueError(f"Manifest row has no identifier: {raw!r}")
        if identifier in parsed:
            continue
        obj_type = str(row.get("type") or "").strip().upper() or None
        parsed[identifier] = {
            "identifier": identifier,
            "type": obj_type,
            "with_dependents": str(row.get("with_dependents") or "").strip().lower() in _TRUTHY,
        }
    return list(parsed.values())


def parse_value_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Parse a variable-value manifest into the shape ``build_value_matrix`` wants.

    Columns: ``org_name``, ``variable_name``, ``value``. Fully blank rows are
    skipped so a trailing newline in a CSV is harmless; a partially filled row is
    an error, because silently dropping it would surface later as a coverage gap
    with no explanation.
    """
    out: List[Dict[str, str]] = []
    for raw in rows or ():
        row = _lower_keys(raw)
        org = str(row.get("org_name") or "").strip()
        name = str(row.get("variable_name") or "").strip()
        value = row.get("value")
        if not org and not name and not str(value or "").strip():
            continue
        for field, given in (("org_name", org), ("variable_name", name)):
            if not given:
                raise ValueError(f"Manifest row is missing {field}: {raw!r}")
        out.append({"org_name": org, "variable_name": name,
                    "value": "" if value is None else str(value)})
    return out


# ---------------------------------------------------------------------------
# Value matrix — the `ts publish resolve` engine
# ---------------------------------------------------------------------------

# Placeholders accepted in a --pattern template.
_PLACEHOLDER_RE = re.compile(r"\{([A-Z_]+)\}")
_KNOWN_PLACEHOLDERS = ("ORG", "ORG_UPPER", "ORG_LOWER", "ORG_ID", "VALUE")


def expand_pattern(template: str, org_name: str, org_id: Any, current_value: str) -> str:
    """Expand a per-field pattern for one Org.

    Placeholders: ``{ORG}``, ``{ORG_UPPER}``, ``{ORG_LOWER}``, ``{ORG_ID}`` and
    ``{VALUE}`` (the field's current value in the Primary Org). An unknown
    placeholder raises rather than being left in the output, because a literal
    ``{TENANT}`` reaching the warehouse would surface as a confusing runtime
    error long after the typo.
    """
    unknown = [p for p in _PLACEHOLDER_RE.findall(template or "") if p not in _KNOWN_PLACEHOLDERS]
    if unknown:
        raise ValueError(
            f"Unknown placeholder(s) in pattern '{template}': {', '.join(unknown)}. "
            f"Expected one of: {', '.join('{' + p + '}' for p in _KNOWN_PLACEHOLDERS)}"
        )
    return (template
            .replace("{ORG_UPPER}", str(org_name).upper())
            .replace("{ORG_LOWER}", str(org_name).lower())
            .replace("{ORG_ID}", str(org_id))
            .replace("{ORG}", str(org_name))
            .replace("{VALUE}", str(current_value)))


def parse_pattern_args(raw: Iterable[str]) -> Dict[str, str]:
    """Parse repeated ``--pattern field=template`` arguments into a mapping."""
    patterns: Dict[str, str] = {}
    for entry in raw or ():
        if "=" not in entry:
            raise ValueError(f"Malformed --pattern '{entry}'. Expected field=pattern, "
                             f"e.g. schemaName={{ORG_UPPER}}")
        field, template = entry.split("=", 1)
        patterns[field.strip()] = template
    return patterns


def selectable_clusters(
    clusters: Iterable[Dict[str, Any]], fields: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Choose which clusters to build a matrix for.

    Defaults to the recommended ones (databaseName / schemaName). An explicit
    field list overrides that, which is how a caller opts tableName in. A cluster
    that cannot be parameterized at all is never returned, whatever was asked
    for: proposing a variable for a Falcon-backed table is a dead end.
    """
    wanted = set(fields) if fields else None
    out = []
    for cluster in clusters:
        if not cluster.get("parameterizable", True):
            continue
        if wanted is None:
            if cluster.get("recommended"):
                out.append(cluster)
        elif cluster["field"] in wanted:
            out.append(cluster)
    return out


def _variable_name(cluster: Dict[str, Any]) -> str:
    """The variable a cluster will use: the bound one, else the suggestion."""
    return cluster.get("variable") or cluster.get("suggested_variable")


def coverage_report(
    assignments: List[Dict[str, Any]], variable_names: Iterable[str], orgs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check every variable has a non-empty value in every target Org.

    Publishing fails closed on a gap, reporting the variable by GUID and the Org
    by numeric id. Catching it here instead produces a message with names in it.
    A blank value counts as missing, not as a value.
    """
    have = {(a["variable"], a["org"]) for a in assignments if str(a.get("value") or "").strip()}
    missing = [{"variable": name, "org": org["name"]}
               for name in variable_names
               for org in orgs
               if (name, org["name"]) not in have]
    return {"complete": not missing, "missing": missing}


def build_value_matrix(
    clusters: Iterable[Dict[str, Any]],
    orgs: List[Dict[str, Any]],
    *,
    source: str,
    patterns: Optional[Dict[str, str]] = None,
    csv_rows: Optional[Iterable[Dict[str, str]]] = None,
    existing_values: Optional[Dict[str, Dict[str, str]]] = None,
    owner_org: Optional[str] = None,
) -> Dict[str, Any]:
    """Produce the variable set, the per-Org value assignments, and a coverage check.

    Sources:

    ``uniform``   the field's current value, replicated to every Org. The shared-table
                  case: still a real variable, so publish validation stays on and a
                  later divergence is one `update-values` call rather than a
                  structural change.
    ``pattern``   a per-field template expanded per Org. A field with no pattern
                  falls back to its current value rather than becoming a gap.
    ``file``      rows of ``{org_name, variable_name, value}``.
    ``existing``  values already assigned on the instance, keyed
                  ``{variable: {org: value}}``. The re-publish / add-a-tenant path.

    ``owner_org`` (the Primary Org) is always included and always keeps the
    field's CURRENT value, whatever source is chosen. Two reasons, both learned
    the hard way:

    * Parameterizing replaces the static db/schema with tokens. If the owner Org
      has no value the FQN collapses and the **source** object breaks — Snowflake
      returns "Object 'T1_PUBLISH' does not exist". ThoughtSpot's publish
      validation only checks TARGET orgs, so nothing else catches it.
    * Expanding a pattern for the owner Org would silently repoint the source
      object at different data. Publishing must not change what Primary reads.

    Pure — no I/O. The caller supplies rows and existing values.
    """
    clusters = list(clusters)
    if owner_org and owner_org not in {o["name"] for o in orgs}:
        orgs = [{"name": owner_org, "id": None}] + list(orgs)
    rows = list(csv_rows or ())
    existing_values = existing_values or {}

    variables: List[Dict[str, Any]] = []
    assignments: List[Dict[str, Any]] = []

    for cluster in clusters:
        name = _variable_name(cluster)
        if not name:
            continue
        variables.append({
            "name": name,
            "type": "TABLE_MAPPING",
            "field": cluster["field"],
            "tables": list(cluster["tables"]),
            "exists": bool(cluster.get("variable")),
            "sensitive": False,
        })
        for org in orgs:
            effective = "uniform" if org["name"] == owner_org else source
            value = _value_for(cluster, name, org, effective, patterns or {}, rows, existing_values)
            if value is not None:
                assignments.append({"variable": name, "org": org["name"], "value": value})

    return {
        "orgs": [o["name"] for o in orgs],
        "variables": variables,
        "assignments": assignments,
        "coverage": coverage_report(assignments, [v["name"] for v in variables], orgs),
    }


def _value_for(
    cluster: Dict[str, Any], name: str, org: Dict[str, Any], source: str,
    patterns: Dict[str, str], rows: List[Dict[str, str]],
    existing_values: Dict[str, Dict[str, str]],
) -> Optional[str]:
    """Resolve one (variable, Org) value for the chosen source.

    Returns None when the source has nothing for this pair, which becomes a
    coverage gap rather than a silent blank.
    """
    current = cluster.get("current_value")
    if source == "uniform":
        return current
    if source == "pattern":
        template = patterns.get(cluster["field"])
        return expand_pattern(template, org["name"], org.get("id"), current) if template else current
    if source == "file":
        for row in rows:
            if row.get("org_name") == org["name"] and row.get("variable_name") == name:
                return row.get("value")
        return None
    if source == "existing":
        return (existing_values.get(name) or {}).get(org["name"])
    raise ValueError(f"Unknown source '{source}'. Expected uniform, pattern, file or existing.")


# ---------------------------------------------------------------------------
# Apply plan — the `ts publish apply` / `rollback` engine
# ---------------------------------------------------------------------------


# Apply-plan assembly lives in publish_apply.py (file-size gate). Re-exported here
# so callers have a single import site. Imported at the bottom because
# publish_apply depends on build_clusters above.
from ts_cli.publish_apply import (  # noqa: E402,F401
    build_apply_plan,
    merge_closures,
    publish_targets,
    publish_type_for_root,
    rollback_steps,
)
