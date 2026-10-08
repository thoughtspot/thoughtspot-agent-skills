"""ThoughtSpot joins ↔ dbt `foreign_key` constraints — the composite-key path.

dbt's built-in `relationships` test is single-column, so a composite-key join
(`[A::C1] = [B::C1] and [A::C2] = [B::C2]`, common in ThoughtSpot Models) had no
dbt representation: `ts-convert-to-dbt` reported it as skipped and the round
trip came back with the join missing (ts-convert-to-dbt open-items #5).

dbt's own model constraints can say it (dbt 1.9+; verified against dbt-core
1.12.5, 2026-10-06 — the manifest keeps `columns`, `to` and `to_columns`)::

    models:
      - name: stg_line_notes
        constraints:
          - type: foreign_key
            name: line_notes_to_order_lines
            columns: [ORDER_ID, LINE_NO]
            to: ref('stg_order_lines')
            to_columns: [ORDER_ID, LINE_NO]

A constraint has no slot for a ThoughtSpot join type or cardinality, so those
ride in a model-level meta tag keyed by the constraint's `name`
(``ts_join_options``, a ts-cli extension). Without it — a constraint the user
wrote for their own reasons — the defaults are the ones MetricFlow entity joins
already use: LEFT_OUTER, MANY_TO_ONE (foreign key → its target).

**Path Y only.** ThoughtSpot's native dbt import ignores constraints entirely,
composite or single-column (live 2026-10-06: three Models, no joins). On the
native path a composite join needs a surrogate key and a `relationships` test.

Single-column joins keep using `relationships` tests on the export side — that
is the form the native import does read — but the reader accepts single-column
constraints too, so a project that already declares them is not ignored.
"""
from __future__ import annotations

import re
from collections import defaultdict

#: Model-level meta tag: {constraint name: {ts_join_type, ts_join_cardinality}}.
JOIN_OPTIONS_TAG = "ts_join_options"

_REF_RE = re.compile(r"""ref\(\s*['"]([^'"]+)['"]\s*\)""")
_TYPES = {"inner", "left_outer", "right_outer", "full_outer"}
_CARDINALITIES = {"one_to_one", "many_to_one", "one_to_many"}


# ---------------------------------------------------------------------------
# ThoughtSpot → dbt
# ---------------------------------------------------------------------------

def build_composite_constraints(
    join_data: list[dict], model_names: dict[str, str], unmapped_props: list[dict],
) -> tuple[dict[str, list[dict]], dict[str, dict[str, dict]]]:
    """`foreign_key` constraints (and their join options) for every composite join.

    Returns ``(constraints_by_table, join_options_by_table)``, both keyed by the
    LEFT (foreign-key side) node key — the shape `_build_schema_docs` attaches
    to that table's model entry. Single-column joins are left to the
    relationships-test builder.
    """
    constraints: dict[str, list[dict]] = defaultdict(list)
    options: dict[str, dict[str, dict]] = defaultdict(dict)
    for jd in join_data:
        if len(jd["pairs"]) < 2:
            continue
        right_model = model_names.get(jd["right_table"])
        if right_model is None:
            continue
        name = jd.get("ts_name") or jd["name"]
        constraints[jd["left_id"]].append({
            "type": "foreign_key",
            "name": name,
            "columns": [p[1] for p in jd["pairs"]],
            "to": f"ref('{right_model}')",
            "to_columns": [p[3] for p in jd["pairs"]],
        })
        opts = _join_options(jd, name, unmapped_props)
        if opts:
            options[jd["left_id"]][name] = opts
    return dict(constraints), dict(options)


def _join_options(jd: dict, name: str, unmapped_props: list[dict]) -> dict:
    opts: dict = {}
    for key, value, allowed, tag in (
        ("join_type", (jd.get("join_type") or "").lower(), _TYPES, "ts_join_type"),
        ("join_cardinality", (jd.get("cardinality") or "").lower(), _CARDINALITIES,
         "ts_join_cardinality"),
    ):
        if not value:
            continue
        if value in allowed:
            opts[tag] = value
        else:
            unmapped_props.append({
                "column": None, "property": key, "value": value,
                "reason": f"no {tag} equivalent for '{value}' on join '{name}'"})
    return opts


# ---------------------------------------------------------------------------
# dbt → ThoughtSpot
# ---------------------------------------------------------------------------

def constraint_joins(
    model_nodes: dict[str, dict], dbt_to_table: dict[str, str], ref_to_table: dict[str, str],
    relation_to_table: "dict[str, str] | None" = None,
) -> dict[str, list[dict]]:
    """ThoughtSpot `joins[]` entries from the `foreign_key` constraints on the
    in-scope models, keyed by source Table name. Model-level and column-level
    constraints both count.

    `to` comes in two forms: ``ref('model')`` in a parse-only manifest, and the
    **resolved relation** (``DB.SCHEMA.TABLE``) once dbt has compiled — which is
    every dbt Cloud job artifact and every ``dbt build`` / ``docs generate``
    (live 2026-10-06). ``relation_to_table`` (from :func:`relation_tables`)
    resolves the second. A `to` matching neither, or column lists that do not
    line up, is skipped rather than guessed at.
    """
    out: dict[str, list[dict]] = defaultdict(list)
    for dbt_name, node in model_nodes.items():
        source = dbt_to_table[dbt_name]
        options = (((node.get("config") or {}).get("meta") or {}).get(JOIN_OPTIONS_TAG)) or {}
        for con in _foreign_keys(node):
            join = _join_from_constraint(source, dbt_name, con, options, ref_to_table,
                                         relation_to_table or {})
            if join:
                out[source].append(join)
    return dict(out)


def _join_from_constraint(source: str, dbt_name: str, con: dict, options: dict,
                          ref_to_table: dict[str, str],
                          relation_to_table: dict[str, str]) -> "dict | None":
    target, label = _target_table(con.get("to") or "", ref_to_table, relation_to_table)
    cols, to_cols = con.get("columns") or [], con.get("to_columns") or []
    if not target or not cols or len(cols) != len(to_cols):
        return None
    opts = options.get(con.get("name") or "", {})
    return {
        "name": con.get("name") or f"{dbt_name}_to_{label}",
        "with": target,
        "on": " and ".join(f"[{source}::{c}] = [{target}::{t}]" for c, t in zip(cols, to_cols)),
        "type": (opts.get("ts_join_type") or "left_outer").upper(),
        "cardinality": (opts.get("ts_join_cardinality") or "many_to_one").upper(),
    }


def _target_table(to: str, ref_to_table: dict[str, str],
                  relation_to_table: dict[str, str]) -> "tuple[str | None, str]":
    """`(target Table, label for a derived join name)`, or `(None, "")`."""
    m = _REF_RE.search(to)
    if m:
        return ref_to_table.get(m.group(1), m.group(1).upper()), m.group(1)
    table = relation_to_table.get(_norm_relation(to))
    return (table, table.lower()) if table else (None, "")


def _norm_relation(relation: str) -> str:
    return ".".join(p.strip().strip('"`[]').upper() for p in relation.split("."))


def relation_tables(manifest: dict, table_name) -> dict[str, str]:
    """Normalised ``DB.SCHEMA.TABLE`` relation → Table name, for every model node —
    how a compiled manifest's constraint `to` is resolved."""
    out: dict[str, str] = {}
    for node in (manifest.get("nodes") or {}).values():
        if node.get("resource_type") == "model" and node.get("relation_name"):
            out[_norm_relation(node["relation_name"])] = table_name(node)
    return out


def _foreign_keys(node: dict) -> list[dict]:
    """Model-level foreign keys, plus column-level ones normalised to that shape."""
    fks = [c for c in node.get("constraints") or [] if c.get("type") == "foreign_key"]
    for col_name, col in (node.get("columns") or {}).items():
        for c in col.get("constraints") or []:
            if c.get("type") == "foreign_key":
                fks.append({**c, "columns": [col_name],
                            "to_columns": c.get("to_columns") or []})
    return fks


def add_uncovered_joins(
    joins_by_table: dict[str, list[dict]], extra: dict[str, list[dict]],
) -> list[dict]:
    """Add `extra` joins for table pairs `joins_by_table` does not already join
    (either direction). Returns what was added, as ``[{source, target, name}]``."""
    covered = {(src, j["with"]) for src, jl in joins_by_table.items() for j in jl}
    added: list[dict] = []
    for src, jl in extra.items():
        for j in jl:
            pair = (src, j["with"])
            if pair in covered or (j["with"], src) in covered:
                continue
            covered.add(pair)
            joins_by_table.setdefault(src, []).append(j)
            added.append({"source": src, "target": j["with"], "name": j["name"]})
    return added
