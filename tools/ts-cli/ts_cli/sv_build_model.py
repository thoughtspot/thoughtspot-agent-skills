"""Model TML assembly from parse-sv + translate-formulas output (Snowflake SV).

Pure functions: dicts in, dicts out. No I/O, no network. Shared formula
transforms are IMPORTED from ts_cli.formula_common (BL-100 PR3) —
never forked. Mirrors mv_build_model.py for the Databricks direction.

Key SV-specific differences from the Databricks builder:
  - SV relationships → inline joins (Scenario B) with equi/range/ASOF support
  - First synonym → display name (SV `with synonyms=(...)` convention)
  - Private columns → index_type: DONT_INDEX
  - No separate filter entry — filter-labeled columns are inline in translated[]
"""
from __future__ import annotations

from ts_cli.formula_common import (add_formula_prefix, fix_double_aggregation,
                                   resolve_name_collisions)
from ts_cli.sv_translate import build_node_id_map


def display_title(entry: dict) -> str:
    synonyms = entry.get("synonyms") or []
    if synonyms:
        return synonyms[0]
    return entry["name"].replace("_", " ").title()


def normalize_tables(tables: dict) -> dict[str, str]:
    """Normalize the tables map: alias -> TS table name (string)."""
    out: dict[str, str] = {}
    for alias, info in tables.items():
        if isinstance(info, dict):
            out[alias] = info["name"]
        else:
            out[alias] = info
    return out


def _column_props(entry: dict, *, is_formula: bool) -> dict:
    props: dict = {"column_type": entry["column_type"]}
    if entry["column_type"] == "MEASURE":
        props["aggregation"] = entry.get("aggregation") or "SUM"
        if is_formula:
            props["index_type"] = "DONT_INDEX"
    if entry.get("is_private"):
        props["index_type"] = "DONT_INDEX"
    if entry.get("comment"):
        props["description"] = entry["comment"]
    syns = entry.get("synonyms") or []
    remaining = syns[1:] if syns else []
    if remaining:
        props["synonyms"] = list(remaining)
        props["synonym_type"] = "USER_DEFINED"
    return props


def build_columns_and_formulas(
    translated: list[dict],
) -> tuple[list[dict], list[dict], dict[str, str]]:
    physical = []
    formula_entries = []
    for entry in translated:
        titled = dict(entry, title=display_title(entry))
        if entry["output_kind"] == "column":
            physical.append({"name": titled["title"], "entry": titled,
                             "sv_name": entry["name"]})
        else:
            formula_entries.append({"name": titled["title"],
                                    "expr": entry["ts_expr"], "entry": titled,
                                    "sv_name": entry["name"]})

    physical, formula_entries, rename_map = resolve_name_collisions(
        physical, formula_entries, [])

    formula_exprs = {f["name"]: f["expr"] for f in formula_entries}
    formula_names = set(formula_exprs)
    for f in formula_entries:
        expr = add_formula_prefix(f["expr"], formula_names, set())
        f["expr"] = fix_double_aggregation(expr, formula_exprs)

    physical_by_sv = {p["sv_name"]: p for p in physical}
    formula_by_sv = {f["sv_name"]: f for f in formula_entries}

    formulas = []
    columns = []

    def _emit(candidate: dict, *, is_formula: bool) -> None:
        entry = candidate["entry"]
        if is_formula:
            formula = {"id": f"formula_{candidate['name']}",
                       "name": candidate["name"], "expr": candidate["expr"]}
            if entry["column_type"] == "ATTRIBUTE":
                formula["properties"] = {"column_type": "ATTRIBUTE"}
            formulas.append(formula)
            columns.append({"name": candidate["name"],
                            "formula_id": formula["id"],
                            "properties": _column_props(entry, is_formula=True)})
        else:
            columns.append({"name": candidate["name"],
                            "column_id": f"{entry['table']}::{entry['column']}",
                            "properties": _column_props(entry, is_formula=False)})

    for entry in translated:
        sv_name = entry["name"]
        if sv_name in physical_by_sv:
            _emit(physical_by_sv[sv_name], is_formula=False)
        elif sv_name in formula_by_sv:
            _emit(formula_by_sv[sv_name], is_formula=True)

    return columns, formulas, rename_map


def _check_no_duplicate_display_names(columns: list[dict]) -> None:
    seen: set[str] = set()
    dupes: set[str] = set()
    for c in columns:
        if c["name"] in seen:
            dupes.add(c["name"])
        seen.add(c["name"])
    if dupes:
        raise ValueError(
            f"duplicate display title(s): {sorted(dupes)} — set distinct "
            f"display_name values in the SV")


def _detect_fact_tables(relationships: list[dict]) -> set[str]:
    """Return the set of table aliases that never appear on the TO side."""
    to_tables = {r["to_table"] for r in relationships}
    from_tables = {r["from_table"] for r in relationships}
    all_tables = from_tables | to_tables
    return all_tables - to_tables


def _build_join_on(rel: dict, node_of: dict[str, str]) -> str:
    """Build the `on` expression for one relationship.

    ``node_of`` maps each SV alias to its model node id, so a role-playing
    endpoint resolves to its alias node (``[ON_BEHALF_ACCOUNT::ID]``) rather
    than the shared physical table name."""
    from_ts = node_of[rel["from_table"]]
    to_ts = node_of[rel["to_table"]]
    style = rel.get("join_style", "equi")

    if style == "range":
        fc = rel["from_cols"][0]
        start, end = rel["to_cols"][0], rel["to_cols"][1]
        return (f"[{from_ts}::{fc}] >= [{to_ts}::{start}] and "
                f"[{from_ts}::{fc}] < [{to_ts}::{end}]")

    if style == "asof":
        parts = []
        for fc, tc in zip(rel["from_cols"], rel["to_cols"]):
            parts.append(f"[{from_ts}::{fc}] = [{to_ts}::{tc}]")
        parts[-1] = parts[-1].replace("] =", "] >=", 1)
        return " and ".join(parts)

    return " and ".join(
        f"[{from_ts}::{fc}] = [{to_ts}::{tc}]"
        for fc, tc in zip(rel["from_cols"], rel["to_cols"]))


def _collect_joins(
    relationships: list[dict], node_of: dict[str, str], flat: dict[str, str],
) -> dict[str, list[dict]]:
    joins_by_from: dict[str, list[dict]] = {}
    for rel in relationships:
        from_alias = rel["from_table"]
        to_alias = rel["to_table"]
        # Membership is validated against the caller-supplied tables map (tables.json),
        # not node_of (which is derived from the SV and always complete).
        if from_alias not in flat:
            raise ValueError(
                f"relationship from_table '{from_alias}' not in tables map")
        if to_alias not in flat:
            raise ValueError(
                f"relationship to_table '{to_alias}' not in tables map")
        join_entry = {
            "name": rel["name"],
            "with": node_of[to_alias],
            "on": _build_join_on(rel, node_of),
            "type": "LEFT_OUTER",
            "cardinality": "MANY_TO_ONE",
        }
        joins_by_from.setdefault(from_alias, []).append(join_entry)
    return joins_by_from


def build_model_tables(
    parsed: dict, tables: dict,
) -> list[dict]:
    flat = normalize_tables(tables)
    node_of = build_node_id_map(parsed)
    relationships = parsed.get("relationships") or []
    has_joins = bool(relationships)
    joins_by_from = _collect_joins(relationships, node_of, flat)

    fact_aliases = _detect_fact_tables(relationships) if relationships else set()

    order = []
    seen = set()
    for alias in tables:
        if alias in flat and alias not in seen:
            if alias in fact_aliases or not relationships:
                order.insert(0, alias)
            else:
                order.append(alias)
            seen.add(alias)

    model_tables = []
    for alias in order:
        info = tables[alias]
        phys = flat[alias]
        # node id: physical name for a single-use table, or the SV alias for a
        # role-playing instance of a reused physical table.
        node = node_of.get(alias, phys)
        e: dict = {}
        if node != phys:
            # Role-playing instance of a reused physical table. ThoughtSpot
            # identifies it by `alias` (name stays the physical table); joins and
            # column_id prefixes reference the alias. Do NOT set `id` to the alias
            # — I4 requires id == name, and id != name silently breaks joins.
            e["name"] = phys
            e["alias"] = node
        else:
            if has_joins:
                e["id"] = phys
            e["name"] = phys
        fqn = info.get("fqn") if isinstance(info, dict) else None
        if fqn:
            e["fqn"] = fqn
        if alias in joins_by_from:
            e["joins"] = joins_by_from[alias]
        model_tables.append(e)

    return model_tables


def build_description(
    comment: str | None, sv_fqn: str | None,
) -> str:
    parts = []
    if comment:
        parts.append(str(comment).strip())
    if sv_fqn:
        parts.append(f"Converted from Snowflake Semantic View {sv_fqn}.")
    if not parts:
        parts.append("Converted from a Snowflake Semantic View.")
    return " ".join(parts)


def strip_formulas(doc: dict) -> dict:
    """Return a model doc with formulas removed (for two-pass import phase 1).

    Removes model.formulas entirely and drops columns[] entries that have
    formula_id (keeps only column_id entries)."""
    import copy
    stripped = copy.deepcopy(doc)
    model = stripped.get("model", {})
    model.pop("formulas", None)
    columns = model.get("columns") or []
    model["columns"] = [c for c in columns if "column_id" in c]
    return stripped


def build_model_tml_sv(
    *, model_name: str, parsed: dict, translated_doc: dict,
    tables: dict, sv_fqn: str | None = None,
    spotter_enabled: bool | None = None,
    existing_guid: str | None = None,
) -> tuple[dict, dict]:
    columns, formulas, rename_map = build_columns_and_formulas(
        translated_doc["translated"])
    _check_no_duplicate_display_names(columns)

    model: dict = {
        "name": model_name,
        "description": build_description(parsed.get("comment"), sv_fqn),
        "model_tables": build_model_tables(parsed, tables),
        "formulas": formulas,
        "columns": columns,
    }
    props: dict = {"is_bypass_rls": False, "join_progressive": True}
    if spotter_enabled is not None:
        props["spotter_config"] = {"is_spotter_enabled": bool(spotter_enabled)}
    model["properties"] = props

    build_info = {
        "rename_map": rename_map,
        "attributes": [c["name"] for c in columns
                       if c["properties"]["column_type"] == "ATTRIBUTE"],
        "measures": [c["name"] for c in columns
                     if c["properties"]["column_type"] == "MEASURE"],
        "formula_count": len(formulas),
    }
    doc = {"model": model}
    if existing_guid:
        doc = {"guid": existing_guid, "model": model}
    return doc, build_info
