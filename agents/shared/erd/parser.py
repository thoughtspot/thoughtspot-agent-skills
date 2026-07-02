"""Parse ThoughtSpot Model + Table TML into the ERD MODEL schema."""
import re

import yaml

_COLREF = re.compile(r"\[([^\]]+?)::[^\]]+?\]")
_ONREF = re.compile(r"\[([^\]]+?)::([^\]]+?)\]")


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


def _index_table_joins(table_tmls):
    out = {}
    for tdict in table_tmls.values():
        tbl = tdict.get("table", {})
        for jw in tbl.get("joins_with", []) or []:
            out[jw.get("name")] = {
                "card": jw.get("cardinality", "UNKNOWN"),
                "type": jw.get("type", "UNKNOWN"),
                "on": jw.get("on") or jw.get("'on'") or "",
            }
    return out


def _rls_for_table(tdict):
    rules = []
    for r in (tdict.get("table", {}).get("rls_rules") or []):
        rules.append({
            "name": r.get("name", "RLS rule"),
            "expr": r.get("expression") or r.get("expr") or "",
            "scope": r.get("applies_to") or r.get("scope") or "All users",
        })
    return rules


def _keys_from_on(on_expr):
    return _ONREF.findall(on_expr or "")


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
            "is_measure": props.get("column_type") == "MEASURE",
            "key": False,
            "hidden": bool(props.get("is_hidden", False)),
            "flag": None,
        })

    joins = []
    for mt in model.get("model_tables", []):
        for j in mt.get("joins", []) or []:
            ref_join = j.get("referencing_join", "")
            inline_on = j.get("on") or ""
            if ref_join:
                joins.append({
                    "from": mt["name"],
                    "to": j.get("with", ""),
                    "name": ref_join,
                    "card": "UNKNOWN",
                    "origin": "model",
                    "type": "UNKNOWN",
                    "on": "",
                })
            elif inline_on:
                joins.append({
                    "from": mt["name"],
                    "to": j.get("with", ""),
                    "name": f"{mt['name']}_{j.get('with', '')}",
                    "card": j.get("cardinality", "UNKNOWN"),
                    "origin": "model",
                    "type": j.get("type", "UNKNOWN"),
                    "on": inline_on,
                })

    has_outgoing = {mt["name"] for mt in model.get("model_tables", []) if mt.get("joins")}
    is_target = {j["to"] for j in joins}
    tables = []
    for name in table_names:
        cols = cols_by_table.get(name, [])
        has_measure = any(c["is_measure"] and not c["hidden"] for c in cols)
        # A table is a fact only when it carries real (visible) measures. Merely
        # having an outgoing join does NOT make it a fact — in normalized/snowflake
        # schemas dimensions join to other dimensions (e.g. person -> account,
        # user -> engagement), so an outgoing FK is not evidence of a fact.
        # A measureless table that both receives and emits a join is a pass-through
        # (bridge); anything else with no measures is a dimension.
        if has_measure:
            kind = "fact"
        elif name in is_target and name in has_outgoing:
            kind = "bridge"
        else:
            kind = "dim"
        tables.append({"id": name, "kind": kind, "cols": cols, "rls": [],
                       "is_sql_view": False, "sql_query": None,
                       "alias_of": None, "in_rls_path": False})

    def _log(msg):
        if log:
            log(msg)

    table_joins = _index_table_joins(table_tmls)
    for j in joins:
        if j["name"] in table_joins:
            tj = table_joins[j["name"]]
            j["origin"] = "table"
            j["card"] = tj["card"]
            j["type"] = tj["type"]
            j["on"] = tj.get("on", "")

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

    all_on_exprs = [meta["on"] for meta in table_joins.values()]
    all_on_exprs.extend(j["on"] for j in joins if j.get("on"))
    for on_expr in all_on_exprs:
        for tbl, col in _keys_from_on(on_expr):
            t = tables_by_id.get(tbl)
            if not t:
                continue
            existing = next((c for c in t["cols"] if c["name"] == col), None)
            if existing:
                existing["key"] = True
            else:
                t["cols"].append({"name": col, "src": col, "role": "ATTR",
                                  "agg": None, "key": True, "hidden": True, "flag": None})

    rls_referenced = set()
    for tname, tdict in table_tmls.items():
        for rule in (tdict.get("table", {}).get("rls_rules") or []):
            expr = rule.get("expression") or rule.get("expr") or ""
            for ref_table in _COLREF.findall(expr):
                if ref_table != tname:
                    rls_referenced.add(ref_table)
    for t in tables:
        t["in_rls_path"] = t["id"] in rls_referenced

    referenced = {j["name"] for j in joins}
    if referenced and not table_joins:
        _log("Fidelity degraded: no Table TMLs provided — join cardinality/type/origin "
             "and RLS omitted for all %d join(s)." % len(referenced))
    else:
        missing = sorted(n for n in referenced if n and n not in table_joins)
        if missing:
            _log("Fidelity degraded: %d join(s) had no Table TML definition "
                 "(treated as model-local, cardinality unknown): %s"
                 % (len(missing), ", ".join(missing)))

    return {
        "model": {"name": model.get("name", ""), "guid": guid,
                  "description": model.get("description", "")},
        "tables": tables,
        "joins": joins,
        "formulas": formulas,
        "findings": [],
    }
