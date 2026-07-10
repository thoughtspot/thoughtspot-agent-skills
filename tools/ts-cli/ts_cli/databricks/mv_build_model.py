"""Model TML assembly from parse-mv + translate-formulas output.

Pure functions: dicts in, dicts out. No I/O, no network. Shared formula
transforms are IMPORTED from ts_cli.model_builder / ts_cli.tableau.naming —
never forked (spec 2026-07-08 §Background). No phased import: cross-measure
refs were inlined at translate time.
"""
from __future__ import annotations

from ts_cli.model_builder import add_formula_prefix, fix_double_aggregation
from ts_cli.tableau.naming import resolve_name_collisions


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
    #    operate BEFORE formula ids / paired columns exist.
    physical = []
    formula_entries = []
    for entry in translated:
        titled = dict(entry, title=display_title(entry))
        if entry["output_kind"] == "column":
            physical.append({"name": titled["title"], "entry": titled})
        else:
            formula_entries.append({"name": titled["title"],
                                    "expr": entry["ts_expr"], "entry": titled})
    if filter_entry is not None:
        formula_entries.append({
            "name": filter_entry["name"], "expr": filter_entry["ts_expr"],
            "entry": {"column_type": "ATTRIBUTE", "comment": None, "synonyms": [],
                      "aggregation": None}})

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

    # 4. stamp ids + emit TML entries from post-rename names.
    formulas = []
    columns = []
    for p in physical:
        entry = p["entry"]
        columns.append({"name": p["name"],
                        "column_id": f"{entry['table']}::{entry['column']}",
                        "properties": _column_props(entry, is_formula=False)})
    for f in formula_entries:
        entry = f["entry"]
        formula = {"id": f"formula_{f['name']}", "name": f["name"], "expr": f["expr"]}
        if entry["column_type"] == "ATTRIBUTE":
            formula["properties"] = {"column_type": "ATTRIBUTE"}
        formulas.append(formula)
        columns.append({"name": f["name"], "formula_id": formula["id"],
                        "properties": _column_props(entry, is_formula=True)})
    return columns, formulas, rename_map
