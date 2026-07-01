"""Parse ThoughtSpot Model + Table TML into the ERD MODEL schema."""
import re

import yaml

_COLREF = re.compile(r"\[([^\]]+?)::[^\]]+?\]")


def load_tml(path):
    """Load a TML (YAML) file into a dict."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _table_of_column_id(column_id):
    return column_id.split("::", 1)[0] if "::" in column_id else ""


def _primary_table_of_formula(expr, known_tables):
    for tbl in _COLREF.findall(expr or ""):
        if tbl in known_tables:
            return tbl
    return ""


def _column_role(props, is_formula):
    if is_formula:
        return "FORMULA"
    return "MEASURE" if props.get("column_type") == "MEASURE" else "ATTR"


def parse_model(model_tml, table_tmls, log=None):
    model = model_tml.get("model", {})
    guid = model_tml.get("guid", "")
    table_names = [t["name"] for t in model.get("model_tables", [])]

    formula_name_by_id = {}
    formulas = {}
    for f in model.get("formulas", []):
        formula_name_by_id[f.get("id")] = f.get("name")
        formulas[f.get("name")] = f.get("expr", "")

    cols_by_table = {name: [] for name in table_names}
    for col in model.get("columns", []):
        props = col.get("properties", {}) or {}
        is_formula = "formula_id" in col
        if is_formula:
            expr = formulas.get(col.get("name"), "")
            owner = _primary_table_of_formula(expr, set(table_names))
            src = "formula"
        else:
            owner = _table_of_column_id(col.get("column_id", ""))
            src = col.get("column_id", "")
        if owner not in cols_by_table:
            continue
        cols_by_table[owner].append({
            "name": col.get("name", ""),
            "src": src,
            "role": _column_role(props, is_formula),
            "agg": props.get("aggregation"),
            "key": False,
            "hidden": False,
            "flag": None,
        })

    joins = []
    for mt in model.get("model_tables", []):
        for j in mt.get("joins", []) or []:
            joins.append({
                "from": mt["name"],
                "to": j.get("with", ""),
                "name": j.get("referencing_join", ""),
                "card": "UNKNOWN",
                "origin": "model",
                "type": "UNKNOWN",
            })

    has_outgoing = {mt["name"] for mt in model.get("model_tables", []) if mt.get("joins")}
    is_target = {j["to"] for j in joins}
    tables = []
    for name in table_names:
        cols = cols_by_table.get(name, [])
        has_measure = any(c["role"] in ("MEASURE", "FORMULA") for c in cols)
        if has_measure or name in has_outgoing:
            if name in is_target and name in has_outgoing and not has_measure:
                kind = "bridge"
            else:
                kind = "fact"
        else:
            kind = "dim"
        tables.append({"id": name, "kind": kind, "cols": cols, "rls": []})

    return {
        "model": {"name": model.get("name", ""), "guid": guid,
                  "description": model.get("description", "")},
        "tables": tables,
        "joins": joins,
        "formulas": formulas,
        "findings": [],
    }
