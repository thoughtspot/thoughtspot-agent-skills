"""ERD data generation for the audit report.

Parses Model + Table TML dicts (already in memory from AuditContext)
into the ERD bundle format consumed by the shared renderer.
"""
from __future__ import annotations

import re
from typing import Any

_COLREF = re.compile(r"\[([^\]]+?)::[^\]]+?\]")
_ONREF = re.compile(r"\[([^\]]+?)::([^\]]+?)\]")


def _table_of_column_id(column_id: str) -> str:
    return column_id.split("::", 1)[0] if "::" in column_id else ""


def _primary_table_of_formula(expr: str, known_tables: set) -> str:
    for tbl in _COLREF.findall(expr or ""):
        if tbl in known_tables:
            return tbl
    return ""


def _column_role(props: dict, is_formula: bool) -> str:
    if is_formula:
        return "FORMULA"
    return "MEASURE" if props.get("column_type") == "MEASURE" else "ATTR"


def _index_table_joins(table_tmls: dict) -> dict:
    out: dict = {}
    for tdict in table_tmls.values():
        tbl = tdict.get("table", {})
        for jw in tbl.get("joins_with", []) or []:
            out[jw.get("name")] = {
                "card": jw.get("cardinality", "UNKNOWN"),
                "type": jw.get("type", "UNKNOWN"),
                "on": jw.get("on") or jw.get("'on'") or "",
            }
    return out


def _rls_for_table(tdict: dict) -> list:
    rules = []
    for r in (tdict.get("table", {}).get("rls_rules") or []):
        rules.append({
            "name": r.get("name", "RLS rule"),
            "expr": r.get("expression") or r.get("expr") or "",
            "scope": r.get("applies_to") or r.get("scope") or "All users",
        })
    return rules


def _keys_from_on(on_expr: str) -> list:
    return _ONREF.findall(on_expr or "")


def parse_model(model_tml: dict, table_tmls: dict) -> dict:
    """Parse a Model TML + associated Table TMLs into ERD renderer format.

    Args:
        model_tml: Full model TML dict (has 'model' and optionally 'guid' keys).
        table_tmls: Dict of model_table_name -> table TML dict.

    Returns:
        ERD model dict with keys: model, tables, joins, formulas, findings.
    """
    model = model_tml.get("model", {})
    guid = model_tml.get("guid", "")
    table_names = [t["name"] for t in model.get("model_tables", [])]

    formula_name_by_id: dict = {}
    formulas: dict = {}
    for f in model.get("formulas", []):
        formula_name_by_id[f.get("id")] = f.get("name")
        formulas[f.get("name")] = f.get("expr", "")

    cols_by_table: dict = {name: [] for name in table_names}
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
        tables.append({
            "id": name, "kind": kind, "cols": cols, "rls": [],
            "is_sql_view": False, "sql_query": None,
            "alias_of": None, "in_rls_path": False,
        })

    table_joins = _index_table_joins(table_tmls)
    for j in joins:
        if j["name"] in table_joins:
            j["origin"] = "table"
            j["card"] = table_joins[j["name"]]["card"]
            j["type"] = table_joins[j["name"]]["type"]

    tables_by_id = {t["id"]: t for t in tables}

    for name, tdict in table_tmls.items():
        if name in tables_by_id:
            tables_by_id[name]["rls"] = _rls_for_table(tdict)
            if "sql_view" in tdict:
                tables_by_id[name]["is_sql_view"] = True
                tables_by_id[name]["sql_query"] = (
                    tdict.get("sql_view", {}).get("sql_query") or "")
            phys = (tdict.get("table", {}).get("name")
                    or tdict.get("sql_view", {}).get("name"))
            if phys and phys != name:
                tables_by_id[name]["alias_of"] = phys

    for meta in table_joins.values():
        for tbl, col in _keys_from_on(meta["on"]):
            t = tables_by_id.get(tbl)
            if not t:
                continue
            if not any(c["name"] == col for c in t["cols"]):
                t["cols"].append({
                    "name": col, "src": col, "role": "ATTR",
                    "agg": None, "key": True, "hidden": True, "flag": None,
                })

    rls_referenced: set = set()
    for tname, tdict in table_tmls.items():
        for rule in (tdict.get("table", {}).get("rls_rules") or []):
            expr = rule.get("expression") or rule.get("expr") or ""
            for ref_table in _COLREF.findall(expr):
                if ref_table != tname:
                    rls_referenced.add(ref_table)
    for t in tables:
        t["in_rls_path"] = t["id"] in rls_referenced

    return {
        "model": {"name": model.get("name", ""), "guid": guid,
                  "description": model.get("description", "")},
        "tables": tables,
        "joins": joins,
        "formulas": formulas,
        "findings": [],
    }


def build_erd_for_audit(ctx: Any) -> list:
    """Generate ERD data for all models in the audit context.

    Returns a list of parsed ERD model dicts, one per ctx.models entry.
    """
    results = []
    for model_tml in ctx.models:
        needed: dict = {}
        for mt in (model_tml.get("model", {}).get("model_tables") or []):
            fqn = mt.get("fqn", "")
            name = mt.get("name", "")
            t = ctx.tables.get(fqn)
            if not t:
                for k, v in ctx.tables.items():
                    tbl_name = v.get("table", {}).get("name") or v.get("sql_view", {}).get("name")
                    if tbl_name == name or k.endswith("." + name):
                        t = v
                        break
            if t:
                needed[name] = t
        results.append(parse_model(model_tml, needed))
    return results
