"""Model TML assembly from parse-mv + translate-formulas output.

Pure functions: dicts in, dicts out. No I/O, no network. Shared formula
transforms are IMPORTED from ts_cli.formula_common (BL-063 PR 5) —
never forked (spec 2026-07-08 §Background). No phased import: cross-measure
refs were inlined at translate time.
"""
from __future__ import annotations

import re

from ts_cli.databricks.mv_translate import normalize_tables
from ts_cli.formula_common import (add_formula_prefix, fix_double_aggregation,
                                   resolve_name_collisions)


def display_title(entry: dict) -> str:
    return entry.get("display_name") or entry["name"].replace("_", " ").title()


def _column_props(entry: dict, *, is_formula: bool) -> dict:
    props: dict = {"column_type": entry["column_type"]}
    if entry["column_type"] == "MEASURE":
        props["aggregation"] = entry.get("aggregation") or "SUM"
        if is_formula:
            props["index_type"] = "DONT_INDEX"
    if entry.get("comment"):
        props["description"] = entry["comment"]
    if entry.get("synonyms"):
        props["synonyms"] = list(entry["synonyms"])
        props["synonym_type"] = "USER_DEFINED"
    return props


def build_columns_and_formulas(
    translated: list[dict], filter_entry: dict | None
) -> tuple[list[dict], list[dict], dict[str, str]]:
    # 1. candidates, titled — plain dicts so resolve_name_collisions can
    #    operate BEFORE formula ids / paired columns exist. Each candidate
    #    carries the MV `name` (distinct from its display "name"/title) so
    #    step 4 can walk `translated` once and emit in MV declaration order
    #    (worked-example docs interleave formula and physical columns in MV
    #    order — see ts-from-databricks.md "Output — Model TML": Transaction
    #    Id, Product Category, Transaction Month [formula], Region,
    #    Transaction Date, ... — not physical-first).
    physical = []
    formula_entries = []
    for entry in translated:
        titled = dict(entry, title=display_title(entry))
        if entry["output_kind"] == "column":
            physical.append({"name": titled["title"], "entry": titled,
                             "mv_name": entry["name"]})
        else:
            formula_entries.append({"name": titled["title"],
                                    "expr": entry["ts_expr"], "entry": titled,
                                    "mv_name": entry["name"]})
    if filter_entry is not None:
        # mv_name None is the sentinel for "not in `translated`" — the MV
        # Filter is always emitted last (step 4), never in-place.
        formula_entries.append({
            "name": filter_entry["name"], "expr": filter_entry["ts_expr"],
            "entry": {"column_type": "ATTRIBUTE", "comment": None, "synonyms": [],
                      "aggregation": None}, "mv_name": None})

    # 2. collisions: drops physical columns shadowed by a formula name;
    #    parameter renames never fire (MVs have no parameters).
    physical, formula_entries, rename_map = resolve_name_collisions(
        physical, formula_entries, [])

    # 3. formula-text pipeline via the shared helpers (safety net — translate
    #    already inlined cross-refs, so these are usually no-ops).
    formula_exprs = {f["name"]: f["expr"] for f in formula_entries}
    formula_names = set(formula_exprs)
    for f in formula_entries:
        expr = add_formula_prefix(f["expr"], formula_names, set())
        f["expr"] = fix_double_aggregation(expr, formula_exprs)

    # 4. stamp ids + emit TML entries, walking `translated` once so each
    #    entry is emitted in place (dropped-by-collision entries have no
    #    mv_name match in either map and are skipped); the filter — never
    #    part of `translated` — is emitted last.
    physical_by_mv = {p["mv_name"]: p for p in physical}
    formula_by_mv = {f["mv_name"]: f for f in formula_entries
                     if f["mv_name"] is not None}

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
            columns.append({"name": candidate["name"], "formula_id": formula["id"],
                            "properties": _column_props(entry, is_formula=True)})
        else:
            columns.append({"name": candidate["name"],
                            "column_id": f"{entry['table']}::{entry['column']}",
                            "properties": _column_props(entry, is_formula=False)})

    for entry in translated:
        mv_name = entry["name"]
        if mv_name in physical_by_mv:
            _emit(physical_by_mv[mv_name], is_formula=False)
        elif mv_name in formula_by_mv:
            _emit(formula_by_mv[mv_name], is_formula=True)
        # else: dropped by the collision pass (physical shadowed by a formula).

    filter_candidate = next(
        (f for f in formula_entries if f["mv_name"] is None), None)
    if filter_candidate is not None:
        _emit(filter_candidate, is_formula=True)

    return columns, formulas, rename_map


# ---------------------------------------------------------------------------
# Joins -> model_tables[] (ts-from-databricks-rules.md "Joins -> ThoughtSpot
# Model Joins" / "using: Joins")
# ---------------------------------------------------------------------------

_CARDINALITY = {"many_to_one": "MANY_TO_ONE", "one_to_many": "ONE_TO_MANY"}


def flatten_join_aliases(parsed_joins: list) -> list[tuple[str, str, dict]]:
    """Pre-order walk of the parsed joins tree.

    Returns (alias_path, parent_path, join_node) triples. alias_path is
    dot-joined from the root; the parent of a top-level join is "source".
    """
    out: list[tuple[str, str, dict]] = []

    def walk(joins: list, parent_path: str) -> None:
        for j in joins:
            path = j["alias"] if parent_path == "source" else f"{parent_path}.{j['alias']}"
            out.append((path, parent_path, j))
            walk(j.get("joins") or [], path)

    walk(parsed_joins or [], "source")
    return out


def _alias_index(flat: dict) -> dict:
    """Map last-path-segment -> [full paths] for single-token alias resolution."""
    index: dict = {}
    for path in flat:
        last = path.split(".")[-1]
        index.setdefault(last, []).append(path)
    return index


def _resolve_join_ref(ref: str, flat: dict, index: dict) -> str:
    parts = ref.strip().split(".")
    if len(parts) < 2:
        raise ValueError(f"join reference '{ref}' has no alias qualifier")
    col = parts[-1]
    path = ".".join(parts[:-1])
    if path not in flat:
        candidates = index.get(path, [])
        if len(candidates) == 1:
            path = candidates[0]
        elif len(candidates) > 1:
            raise ValueError(
                f"join reference '{ref}': alias '{path}' is ambiguous across "
                f"{sorted(candidates)} — disambiguate the tables map")
        else:
            raise ValueError(
                f"join reference '{ref}': alias '{path}' is not in the tables map")
    return f"[{flat[path]}::{col}]"


# Standalone `=` only — not part of a wider operator like `>=`, `<=`, `!=`,
# `==`, or `<=>`. Negative lookbehind/lookahead exclude `=` chars adjacent to
# `<`, `>`, `!`, or another `=`.
_EQUALITY_SPLIT = re.compile(r"(?<![<>!=])=(?!=)")


def _translate_on(on: str, flat: dict, index: dict) -> str:
    conjuncts = re.split(r"(?i)\bAND\b", on)
    parts = []
    for conjunct in conjuncts:
        sides = _EQUALITY_SPLIT.split(conjunct)
        if len(sides) != 2 or any(
                ch in side for side in sides for ch in "<>!="):
            raise ValueError(
                f"join on-clause conjunct '{conjunct.strip()}' is not a simple "
                f"equality — only 'a.COL = b.COL [AND ...]' joins are supported")
        left = _resolve_join_ref(sides[0], flat, index)
        right = _resolve_join_ref(sides[1], flat, index)
        parts.append(f"{left} = {right}")
    return " AND ".join(parts)


def _join_display(parent_path: str, alias_path: str) -> str:
    parent = "fact" if parent_path == "source" else parent_path.split(".")[-1]
    return f"{parent}_to_{alias_path.split('.')[-1]}"


def _join_on_clause(node: dict, parent_path: str, path: str, flat: dict, index: dict) -> str:
    if node.get("on"):
        return _translate_on(node["on"], flat, index)
    using = node.get("using")
    if not using:
        raise ValueError(
            f"join '{path}' has neither an on: clause nor a non-empty "
            f"using: list")
    return " AND ".join(
        f"[{flat[parent_path]}::{c}] = [{flat[path]}::{c}]"
        for c in using)


def _join_entries(triples: list, flat: dict, index: dict) -> dict[str, list[dict]]:
    """Build the joins[] list for each parent path, keyed by parent path."""
    by_parent: dict[str, list[dict]] = {}
    for path, parent_path, node in triples:
        on = _join_on_clause(node, parent_path, path, flat, index)
        by_parent.setdefault(parent_path, []).append({
            "name": _join_display(parent_path, path),
            "with": flat[path],
            "on": on,
            "type": "INNER",
            "cardinality": _CARDINALITY[node.get("cardinality") or "many_to_one"],
        })
    return by_parent


def build_model_tables(parsed: dict, tables: dict) -> list[dict]:
    flat = normalize_tables(tables)
    triples = flatten_join_aliases(parsed.get("joins") or [])
    for path, _, _ in triples:
        if path not in flat:
            raise ValueError(f"join alias '{path}' has no entry in the tables map")
    index = _alias_index(flat)
    has_joins = bool(triples)

    def entry(path: str) -> dict:
        info = tables[path]
        e: dict = {}
        if has_joins:
            e["id"] = flat[path]
        e["name"] = flat[path]
        fqn = info.get("fqn") if isinstance(info, dict) else None
        if fqn:
            e["fqn"] = fqn
        return e

    by_path = {"source": entry("source")}
    for path, _, _ in triples:
        by_path[path] = entry(path)

    joins_by_parent = _join_entries(triples, flat, index)
    for parent_path, joins in joins_by_parent.items():
        by_path[parent_path]["joins"] = joins

    return [by_path["source"]] + [by_path[p] for p, _, _ in triples]


def build_description(comment: str | None, mv_fqn: str | None, has_filter: bool) -> str:
    parts = []
    if comment:
        parts.append(str(comment).strip())
    if mv_fqn:
        parts.append(f"Converted from Databricks Metric View {mv_fqn}.")
    if not parts:
        parts.append("Converted from a Databricks Metric View.")
    if has_filter:
        parts.append("MV Filter applied automatically via model filter.")
    return " ".join(parts)


def _check_no_duplicate_display_names(columns: list[dict]) -> None:
    """Fail loud on display-title collisions across ALL columns[] entries.

    resolve_name_collisions only resolves formula-vs-parameter and
    column-vs-formula clashes — two dimensions (or two measures) that resolve
    to the same display title pass through it untouched and would emit
    duplicate column names. `ts tml lint` I8 (unique column_id) cannot catch
    this: column_id and display name are different fields. (BL-099 #2)
    """
    seen: set[str] = set()
    dupes: set[str] = set()
    for c in columns:
        if c["name"] in seen:
            dupes.add(c["name"])
        seen.add(c["name"])
    if dupes:
        raise ValueError(
            f"duplicate display title(s): {sorted(dupes)} — set distinct "
            f"display_name values in the MV")


def build_model_tml_dbx(*, model_name: str, parsed: dict, translated_doc: dict,
                        tables: dict, mv_fqn: str | None = None,
                        spotter_enabled: bool | None = None,
                        existing_guid: str | None = None) -> tuple[dict, dict]:
    filter_entry = translated_doc.get("filter")
    columns, formulas, rename_map = build_columns_and_formulas(
        translated_doc["translated"], filter_entry)
    _check_no_duplicate_display_names(columns)

    model: dict = {
        "name": model_name,
        "description": build_description(parsed.get("comment"), mv_fqn,
                                         filter_entry is not None),
        "model_tables": build_model_tables(parsed, tables),
        "formulas": formulas,
        "columns": columns,
    }
    if filter_entry is not None:
        model["filters"] = [{"column": [filter_entry["name"]], "oper": "in",
                             "values": ["true"]}]
    props: dict = {"is_bypass_rls": False, "join_progressive": True}
    if spotter_enabled is not None:
        props["spotter_config"] = {"is_spotter_enabled": bool(spotter_enabled)}
    model["properties"] = props

    by_mv_name = {e["name"]: e for e in translated_doc["translated"]}
    window_measures = []
    for mv_name in translated_doc.get("window_measures") or []:
        e = by_mv_name.get(mv_name)
        if e is None:
            continue  # skipped window measure — reported via skipped[]
        window_measures.append({
            "name": rename_map.get(display_title(e), display_title(e)),
            "mv_name": mv_name, "ts_expr": e.get("ts_expr"),
            "annotations": e.get("annotations") or []})
    build_info = {
        "rename_map": rename_map,
        "window_measures": window_measures,
        "filter_applied": filter_entry is not None,
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
