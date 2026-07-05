"""Pure helpers behind ``ts tableau build-model`` (BL-069 follow-up).

Extracted from the ~440-line ``build_model_cmd`` so each piece is unit-testable
in isolation. Pure functions, no I/O — subprocess calls and stderr echoes stay
in ``ts_cli/commands/tableau.py``.
"""
from __future__ import annotations

import re

from ts_cli.model_builder import (
    add_formula_prefix,
    build_col_table_map,
    build_column_lookup,
    fix_bare_refs,
    fix_double_aggregation,
)

_CSQ_SUFFIX = re.compile(r"\s*\(Custom SQL Query\d*\)\s*$")
_CSQ_IN_REF = re.compile(r"\[([^\]]+?)\s+\(\s*Custom SQL Query\d*\)\]")


def fix_sqlproxy_scoping(
    scoped_columns: dict[str, str],
    existing_tml: dict,
) -> tuple[dict[str, str], str]:
    """Remap ``sqlproxy`` table scopes to actual model tables.

    Published-datasource TWBs scope columns to the ``sqlproxy`` pseudo-table.
    When merging into an existing model, derive the real column→table map from
    the model's ``column_id`` entries (``TABLE::COLUMN``).

    Returns ``(fixed_scoped, message)`` — message is "" when nothing needed
    fixing, otherwise a human-readable summary for the caller to echo.
    """
    if not any(t == "sqlproxy" for t in scoped_columns.values()):
        return scoped_columns, ""

    model_tables = existing_tml["model"].get("model_tables", [])
    if len(model_tables) == 1:
        return _force_single_table(scoped_columns, existing_tml)
    return _remap_multi_table(scoped_columns, existing_tml)


def _force_single_table(
    scoped_columns: dict[str, str],
    existing_tml: dict,
) -> tuple[dict[str, str], str]:
    """Single-table model: force ALL columns to the one table."""
    single_table = existing_tml["model"]["model_tables"][0]["name"]
    fixed_scoped: dict[str, str] = {}
    for col_key in scoped_columns:
        base = _CSQ_SUFFIX.sub("", col_key)
        fixed_scoped[col_key] = single_table
        if base != col_key:
            fixed_scoped[base] = single_table
    for col in existing_tml["model"]["columns"]:
        cid = col.get("column_id", "")
        if "::" in cid:
            _, cname = cid.split("::", 1)
            if cname not in {k.upper() for k in fixed_scoped}:
                fixed_scoped[cname] = single_table
    return fixed_scoped, f"Single-table model: forced all columns → {single_table}"


def _remap_multi_table(
    scoped_columns: dict[str, str],
    existing_tml: dict,
) -> tuple[dict[str, str], str]:
    """Multi-table model: remap sqlproxy scopes via ``column_id`` lookup."""
    col_to_table: dict[str, str] = {}
    for col in existing_tml["model"]["columns"]:
        col_id = col.get("column_id", "")
        if "::" in col_id:
            tbl, cname = col_id.split("::", 1)
            col_to_table[cname.upper()] = tbl
    fixed_scoped = {}
    for col_key, tbl in scoped_columns.items():
        base = _CSQ_SUFFIX.sub("", col_key)
        lookup = base.upper()
        actual_tbl = col_to_table.get(lookup, tbl) if tbl == "sqlproxy" else tbl
        fixed_scoped[col_key] = actual_tbl
        if base != col_key and lookup in col_to_table and base not in fixed_scoped:
            fixed_scoped[base] = col_to_table[lookup]
    for cname, tbl in col_to_table.items():
        if cname not in {k.upper() for k in fixed_scoped}:
            fixed_scoped[cname] = tbl
    remapped = sum(
        1 for k in fixed_scoped
        if k in scoped_columns and fixed_scoped[k] != scoped_columns[k]
    )
    return fixed_scoped, f"Remapped {remapped}/{len(scoped_columns)} sqlproxy columns"


def apply_table_name_map(
    ds: dict,
    scoped_columns: dict[str, str],
    name_map: dict[str, str],
) -> tuple[dict, dict[str, str]]:
    """Remap TWB physical table names to actual ThoughtSpot table TML names.

    GENERATE-mode-only helper (``ts tableau build-model`` without
    ``--existing-guid``). Used when the ThoughtSpot table was created under a
    different name than the TWB relation name — warehouse-normalized names,
    or ``sqlproxy``/published-datasource scoping where the TWB never recorded
    the real physical table name.

    Renames, everywhere a TWB table name feeds the generated model TML:
      - ``ds["tables"][].name`` and ``.db_table`` (both become the mapped
        name — see ``build_model_tml``'s ``model.tables[].fqn`` construction,
        which reads ``t.get("db_table", t["name"])``)
      - ``ds["joins"][].left_table`` / ``.right_table``
      - ``ds["columns"][].table``, when present (defensive — the TWB parser
        does not currently populate this key, but ``build_model_tml`` honors
        it for ``column_id`` prefixing when it is)
      - the table values in ``scoped_columns`` (column name → table name),
        so formula translation's ``scope_columns()`` embeds
        ``[MAPPED_NAME::COL]`` refs rather than the stale TWB name

    Returns a new ``(ds, scoped_columns)`` pair — inputs are not mutated.
    Table names absent from ``name_map`` pass through unchanged. When
    ``name_map`` is empty, returns the inputs unchanged (no-op).
    """
    if not name_map:
        return ds, scoped_columns

    def _remap(table_name: str) -> str:
        return name_map.get(table_name, table_name)

    new_tables = []
    for t in ds.get("tables", []):
        mapped = name_map.get(t["name"])
        if mapped is None:
            new_tables.append(t)
            continue
        nt = dict(t)
        nt["name"] = mapped
        nt["db_table"] = mapped
        new_tables.append(nt)

    new_joins = []
    for j in ds.get("joins", []):
        nj = dict(j)
        nj["left_table"] = _remap(j.get("left_table", ""))
        nj["right_table"] = _remap(j.get("right_table", ""))
        new_joins.append(nj)

    new_columns = []
    for c in ds.get("columns", []):
        if c.get("table") in name_map:
            nc = dict(c)
            nc["table"] = name_map[c["table"]]
            new_columns.append(nc)
        else:
            new_columns.append(c)

    new_scoped = {col: _remap(tbl) for col, tbl in scoped_columns.items()}

    new_ds = dict(ds)
    new_ds["tables"] = new_tables
    new_ds["joins"] = new_joins
    new_ds["columns"] = new_columns

    return new_ds, new_scoped


def strip_csq_suffixes(formulas: list[dict]) -> int:
    """Strip `` (Custom SQL QueryN)`` suffixes from bracketed refs, in place.

    Returns the number of formulas whose expression changed.
    """
    changed = 0
    for f in formulas:
        new_expr = _CSQ_IN_REF.sub(r"[\1]", f["expr"])
        if new_expr != f["expr"]:
            f["expr"] = new_expr
            changed += 1
    return changed


def collect_existing_model_context(existing_tml: dict) -> dict:
    """Extract the name/id sets and lookups the merge flow needs from a model TML."""
    model = existing_tml["model"]
    model_tables = model.get("model_tables", [])
    return {
        "existing_ids": {f["id"] for f in model.get("formulas", [])},
        "existing_cols": {
            c.get("column_id", "").split("::")[-1]
            for c in model.get("columns", [])
            if "::" in c.get("column_id", "")
        },
        "formula_names": {f["name"] for f in model.get("formulas", [])},
        "param_names": {p["name"] for p in model.get("parameters", [])},
        "col_lookup": build_column_lookup(existing_tml),
        "col_table_map": build_col_table_map(
            existing_tml,
            model_tables[0]["name"] if model_tables else None,
        ),
        "primary_table": model_tables[0]["name"] if model_tables else None,
    }


def prepare_formulas_for_merge(
    cleaned_formulas: list[dict],
    ctx: dict,
) -> tuple[list[dict], int]:
    """CSQ-strip, bare-ref fix, ``formula_`` prefix, and double-agg fix.

    Mutates ``cleaned_formulas`` expressions in place (matching the original
    inline behavior), then builds the ``{expr, id, name}`` dicts the merge
    consumes. Returns ``(formula_dicts, bare_fixed_count)``.
    """
    strip_csq_suffixes(cleaned_formulas)

    new_formula_names = {f["name"] for f in cleaned_formulas}
    all_formula_names = ctx["formula_names"] | new_formula_names
    param_names = ctx["param_names"]

    bare_fixed = 0
    # "is not None", not truthy — the original gated on model_tables being
    # non-empty, so an empty-string table name must still run the loop
    if ctx["primary_table"] is not None:
        for f in cleaned_formulas:
            before = f["expr"]
            f["expr"] = fix_bare_refs(
                f["expr"], all_formula_names, param_names,
                ctx["col_lookup"], ctx["primary_table"],
                ctx.get("col_table_map"),
            )
            if f["expr"] != before:
                bare_fixed += 1

    formula_exprs = {f["name"]: f["expr"] for f in cleaned_formulas}
    formula_dicts = []
    for f in cleaned_formulas:
        expr = add_formula_prefix(f["expr"], all_formula_names, param_names)
        expr = fix_double_aggregation(expr, formula_exprs)
        formula_dicts.append({
            "expr": expr,
            "id": f"formula_{f['name']}",
            "name": f["name"],
        })
    return formula_dicts, bare_fixed


_IMPORT_ERR = re.compile(r"Formula:\s*([^,]+),\s*Error:")


def parse_import_error(msg: str) -> tuple[str, str] | None:
    """Parse a ThoughtSpot import error into ``(formula_name, detail)``.

    Returns None when the message doesn't name a failing formula (caller
    should stop retrying and surface the raw message).
    """
    m = _IMPORT_ERR.search(msg)
    if not m:
        return None
    bad_name = m.group(1).strip()
    err_detail = msg.split("Error:", 1)[-1].strip()[:120] if "Error:" in msg else ""
    return bad_name, err_detail


def remove_formula(merged: dict, formula_name: str) -> None:
    """Drop a formula and its derived columns from a model TML, in place."""
    fid = f"formula_{formula_name}"
    merged["model"]["formulas"] = [
        f for f in merged["model"]["formulas"] if f.get("id") != fid
    ]
    merged["model"]["columns"] = [
        c for c in merged["model"]["columns"] if c.get("formula_id") != fid
    ]


def extract_imported_guid(import_result: list) -> str | None:
    """Pull the created/updated object GUID out of a tml import response."""
    obj_list = import_result[0].get("response", {}).get("object", [])
    if obj_list:
        return obj_list[0].get("header", {}).get("id_guid") or None
    return None


def apply_prefix_and_double_agg(
    cleaned_formulas: list[dict],
    formula_names: set[str],
    param_names: set[str],
) -> None:
    """Generate-flow formula rewrite: ``formula_`` prefix + double-agg fix, in place.

    ``formula_exprs`` is snapshotted before the loop (pre-mutation values) —
    this matches the original inline behavior exactly.
    """
    formula_exprs = {f["name"]: f["expr"] for f in cleaned_formulas}
    for f in cleaned_formulas:
        f["expr"] = add_formula_prefix(f["expr"], formula_names, param_names)
        f["expr"] = fix_double_aggregation(f["expr"], formula_exprs)


# ---------------------------------------------------------------------------
# Data-blend graph → join plan (A4-A6)
# ---------------------------------------------------------------------------

def build_blend_components(blend_graph: dict) -> list[dict]:
    """Group blended datasources into connected components via BFS.

    ``blend_graph`` is keyed by source datasource caption (see
    ``extract_blends``): ``{caption: [{"target_ds": caption, ...}]}``.
    Within each component, the ``primary`` is a node that appears as a
    source but never as a target (the root of the blend); if no such node
    exists (e.g. a cycle), falls back to the first member found.

    Returns ``[{"primary": caption, "members": [caption, ...]}]``.
    """
    adjacency: dict = {}
    for src, targets in blend_graph.items():
        for t in targets:
            adjacency.setdefault(src, set()).add(t["target_ds"])
            adjacency.setdefault(t["target_ds"], set()).add(src)
    all_targets = {t["target_ds"] for edges in blend_graph.values() for t in edges}
    visited: set = set()
    groups: list = []
    for ds_id in adjacency:
        if ds_id in visited:
            continue
        comp: list = []
        queue = [ds_id]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            comp.append(node)
            queue.extend(adjacency.get(node, set()) - visited)
        roots = [d for d in comp if d in blend_graph and d not in all_targets]
        groups.append({"primary": roots[0] if roots else comp[0], "members": comp})
    return groups


def map_ds_to_tables(datasources: list[dict]) -> dict:
    """Map each datasource caption to its primary (first) table name.

    ``datasources`` is the ``parse_twb`` output: keyed by caption in each
    entry's ``name`` field, with the primary table at ``tables[0]["name"]``.
    A datasource with no tables maps to ``None``.
    """
    out: dict = {}
    for ds in datasources:
        tables = ds.get("tables") or []
        out[ds["name"]] = tables[0]["name"] if tables else None
    return out


def derive_blend_joins(component: dict, blend_graph: dict, ds_to_table: dict) -> list[dict]:
    """Derive model-table joins for every blend edge inside a component.

    Iterates ALL edges among ``component["members"]`` (not just edges from
    the primary), so star topologies (one primary, multiple secondaries)
    and transitive chains both produce a join per edge. Edges whose source
    or target datasource has no mapped table (``ds_to_table``) are skipped.

    Returns ``[{"with", "table", "on", "type": "LEFT_OUTER",
    "cardinality": "MANY_TO_ONE"}]``.
    """
    joins: list = []
    for member in component["members"]:
        for tinfo in blend_graph.get(member, []):
            src_t = ds_to_table.get(member)
            tgt_t = ds_to_table.get(tinfo["target_ds"])
            if not src_t or not tgt_t:
                continue
            on = " and ".join(
                f"[{src_t}::{cm['source_col']}] = [{tgt_t}::{cm['target_col']}]"
                for cm in tinfo["column_mappings"]
            )
            joins.append({"with": src_t, "table": tgt_t, "on": on,
                          "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"})
    return joins


def build_blend_plan(blend_graph: dict, datasources: list[dict]) -> dict:
    """Assemble the full blend plan: components, table map, and joins.

    Returns ``{"components", "ds_table_map", "joins"}``. An empty
    ``blend_graph`` (no blends in the workbook) short-circuits to an
    all-empty plan.
    """
    if not blend_graph:
        return {"components": [], "ds_table_map": {}, "joins": []}
    ds_to_table = map_ds_to_tables(datasources)
    components = build_blend_components(blend_graph)
    joins: list = []
    for c in components:
        joins.extend(derive_blend_joins(c, blend_graph, ds_to_table))
    return {"components": components, "ds_table_map": ds_to_table, "joins": joins}
