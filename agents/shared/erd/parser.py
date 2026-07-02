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


def _column_entry(col, props, is_formula, src):
    """Build the renderer-facing column dict, including AI-authored metadata.

    Top-level `description`/`synonyms` are usually null; the real content lives
    under `properties` (ai_context, synonyms), so fall back to those.
    """
    return {
        "name": col.get("name", ""),
        "src": src,
        "role": _column_role(props, is_formula),
        "agg": props.get("aggregation"),
        "is_measure": props.get("column_type") == "MEASURE",
        "key": False,
        "hidden": bool(props.get("is_hidden", False)),
        "flag": None,
        "desc": col.get("description") or "",
        "ai_context": props.get("ai_context") or "",
        "synonyms": props.get("synonyms") or col.get("synonyms") or [],
    }


def _rls_rule_list(tdict):
    """Normalise a table's rls_rules to a list of rule dicts.

    Some builds nest the rule list under an object:
        rls_rules: {rules: [...], table_paths: [...], tables: [...]}
    while others emit a flat list of rule dicts.
    """
    raw = tdict.get("table", {}).get("rls_rules") or []
    if isinstance(raw, dict):
        raw = raw.get("rules") or []
    return [r for r in raw if isinstance(r, dict)]


def _rls_for_table(tdict):
    rules = []
    for r in _rls_rule_list(tdict):
        rules.append({
            "name": r.get("name", "RLS rule"),
            "expr": r.get("expression") or r.get("expr") or "",
            "scope": r.get("applies_to") or r.get("scope") or "All users",
        })
    return rules


def _keys_from_on(on_expr):
    return _ONREF.findall(on_expr or "")


def _table_node_id(mt):
    """Node identity for a model_table.

    A model may join the SAME physical table multiple times; each instance is
    distinguished by an ``alias``. When present the alias is the node identity
    and is what a join's ``with:`` references — the un-aliased ``name`` is the
    shared physical table. Keying every node by alias-or-name is what lets
    aliased join endpoints resolve to a real node instead of dangling (a
    dangling endpoint crashes the viewer at ``adj[j.from]``/``undir[j.to]``).
    """
    return mt.get("alias") or mt.get("name")


def _build_formulas(model):
    return {f.get("name"): f.get("expr", "") for f in model.get("formulas", [])}


def _build_columns(model, table_ids, formulas):
    """Route each model column to its owning node (by alias-or-name prefix)."""
    cols_by_table = {tid: [] for tid in table_ids}
    known = set(table_ids)
    for col in model.get("columns", []):
        props = col.get("properties", {}) or {}
        is_formula = "formula_id" in col
        if is_formula:
            owner = _primary_table_of_formula(formulas.get(col.get("name"), ""), known)
            src = "formula"
        else:
            owner = _table_of_column_id(col.get("column_id", ""))
            src = col.get("column_id", "")
        if owner in cols_by_table:
            cols_by_table[owner].append(_column_entry(col, props, is_formula, src))
    return cols_by_table


def _build_joins(model_tables, node_ids):
    """Build model-local joins, keeping only those whose endpoints are both real
    nodes. A join's ``with:`` target absent from ``model_tables`` cannot occur in
    a valid ThoughtSpot export — the model editor won't create a join to a table
    that isn't in the model, and TML import validates join targets — so this only
    guards malformed/hand-edited TML. Such a join is dropped (and reported via the
    returned ``dropped`` names) rather than emitted with a non-existent endpoint,
    which would otherwise reach the viewer as an unresolvable join.

    Returns ``(joins, dropped_names)``.
    """
    joins, dropped = [], []
    for mt in model_tables:
        frm = _table_node_id(mt)
        for j in mt.get("joins", []) or []:
            to = j.get("with", "")
            ref_join = j.get("referencing_join", "")
            inline_on = j.get("on") or ""
            if ref_join:
                rec = {"from": frm, "to": to, "name": ref_join,
                       "card": "UNKNOWN", "origin": "model",
                       "type": "UNKNOWN", "on": ""}
            elif inline_on:
                rec = {"from": frm, "to": to, "name": f"{frm}_{to}",
                       "card": j.get("cardinality", "UNKNOWN"),
                       "origin": "model", "type": j.get("type", "UNKNOWN"),
                       "on": inline_on}
            else:
                continue
            if to in node_ids and frm in node_ids:
                joins.append(rec)
            else:
                dropped.append(rec["name"])
    return joins, dropped


def _table_kind(cols, tid, is_target, has_outgoing):
    """Classify a table. Fact only when it carries real (visible) measures — an
    outgoing join alone does not make a fact (dims join to dims in normalized
    schemas); a measureless table that both receives and emits a join is a
    bridge; anything else with no measures is a dimension."""
    if any(c["is_measure"] and not c["hidden"] for c in cols):
        return "fact"
    if tid in is_target and tid in has_outgoing:
        return "bridge"
    return "dim"


def _stitch_table_joins(joins, table_joins):
    """Upgrade model-local joins with cardinality/type/origin from Table TMLs."""
    for j in joins:
        tj = table_joins.get(j["name"])
        if tj:
            j["origin"] = "table"
            j["card"] = tj["card"]
            j["type"] = tj["type"]
            j["on"] = tj.get("on", "")


def _enrich_from_table_tmls(tables_by_id, phys_by_id, table_tmls):
    """Attach RLS, SQL-view and alias metadata from the physical Table TMLs.

    Table TMLs are keyed by physical table name; an aliased node's physical name
    is ``phys_by_id[tid]``, so look up by that first (multiple alias nodes
    legitimately share one physical Table TML), then fall back to the node id.
    """
    for tid, t in tables_by_id.items():
        phys = phys_by_id.get(tid, tid)
        tdict = table_tmls.get(phys) or table_tmls.get(tid)
        if not tdict:
            continue
        t["rls"] = _rls_for_table(tdict)
        if "sql_view" in tdict:
            t["is_sql_view"] = True
            t["sql_query"] = tdict.get("sql_view", {}).get("sql_query") or ""
        phys_name = (tdict.get("table", {}).get("name")
                     or tdict.get("sql_view", {}).get("name"))
        if phys_name and phys_name != tid and not t["alias_of"]:
            t["alias_of"] = phys_name


def _apply_join_keys(tables_by_id, on_exprs):
    """Flag (or synthesize) the columns that participate in join ON clauses."""
    for on_expr in on_exprs:
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


def _mark_rls_path(tables, table_tmls):
    """Flag tables referenced by another table's RLS rule expression."""
    rls_referenced = set()
    for tname, tdict in table_tmls.items():
        for rule in _rls_rule_list(tdict):
            expr = rule.get("expression") or rule.get("expr") or ""
            for ref_table in _COLREF.findall(expr):
                if ref_table != tname:
                    rls_referenced.add(ref_table)
    for t in tables:
        t["in_rls_path"] = t["id"] in rls_referenced


def _log_dropped_joins(dropped, log):
    if log and dropped:
        log("Dropped %d join(s) whose target table is not in the model — this "
            "cannot occur in a valid ThoughtSpot export and indicates malformed "
            "TML: %s" % (len(dropped), ", ".join(sorted(dropped))))


def _log_degraded_fidelity(joins, table_joins, log):
    if not log:
        return
    referenced = {j["name"] for j in joins}
    if referenced and not table_joins:
        log("Fidelity degraded: no Table TMLs provided — join cardinality/type/"
            "origin and RLS omitted for all %d join(s)." % len(referenced))
        return
    missing = sorted(n for n in referenced if n and n not in table_joins)
    if missing:
        log("Fidelity degraded: %d join(s) had no Table TML definition "
            "(treated as model-local, cardinality unknown): %s"
            % (len(missing), ", ".join(missing)))


def parse_model(model_tml, table_tmls, log=None):
    model = model_tml.get("model", {})
    guid = model_tml.get("guid", "")
    model_tables = model.get("model_tables", []) or []

    table_ids = list(dict.fromkeys(_table_node_id(mt) for mt in model_tables))
    phys_by_id = {_table_node_id(mt): mt.get("name") for mt in model_tables}
    alias_ids = {_table_node_id(mt) for mt in model_tables if mt.get("alias")}

    formulas = _build_formulas(model)
    cols_by_table = _build_columns(model, table_ids, formulas)
    joins, dropped_joins = _build_joins(model_tables, set(table_ids))
    _log_dropped_joins(dropped_joins, log)

    has_outgoing = {_table_node_id(mt) for mt in model_tables if mt.get("joins")}
    is_target = {j["to"] for j in joins}
    # An explicit `alias` instance records its physical table up front (even
    # without a Table TML); a non-aliased node may still be resolved as an alias
    # in _enrich_from_table_tmls if its Table TML's physical name differs.
    tables = [{
        "id": tid,
        "kind": _table_kind(cols_by_table.get(tid, []), tid, is_target, has_outgoing),
        "cols": cols_by_table.get(tid, []),
        "rls": [], "is_sql_view": False, "sql_query": None,
        "alias_of": phys_by_id.get(tid) if tid in alias_ids else None,
        "in_rls_path": False,
    } for tid in table_ids]

    table_joins = _index_table_joins(table_tmls)
    _stitch_table_joins(joins, table_joins)

    tables_by_id = {t["id"]: t for t in tables}
    _enrich_from_table_tmls(tables_by_id, phys_by_id, table_tmls)

    on_exprs = [meta["on"] for meta in table_joins.values()]
    on_exprs.extend(j["on"] for j in joins if j.get("on"))
    _apply_join_keys(tables_by_id, on_exprs)

    _mark_rls_path(tables, table_tmls)
    _log_degraded_fidelity(joins, table_joins, log)

    return {
        "model": {"name": model.get("name", ""), "guid": guid,
                  "description": model.get("description", "")},
        "tables": tables,
        "joins": joins,
        "formulas": formulas,
        "findings": [],
    }
