"""Power BI -> ThoughtSpot Model TML assembly (joins, formulas, columns, params).

Ported from the standalone converter (generate_tml.py). Pure functions, no I/O. The
top-level entry point is assemble(): parsed inventory -> (files, mapping). build_model_tml
builds the Model TML itself, split into phase helpers so each stays simple. Formula
cross-refs are [formula_<name>] id-refs, topologically ordered, with a cascade that flags
dependents of an un-migrated formula (id-refs resolve on first import, name-refs do not —
see project-powerbi-port / open-item #2). Join cardinality is read from the file
(fromCardinality/toCardinality); aggregation from summarizeBy (AVG vs SUM) via _col_role.
"""
from __future__ import annotations

import re

from ts_cli.powerbi.functions import translate_dax
from ts_cli.powerbi.tables import (_AUTO_TABLE, _cardinality, _col_role, _dbname,
                                    _slug, build_table_tml)


def _drop_auto_date_tables(model_json):
    """Drop Power BI auto date tables (LocalDateTable_/DateTableTemplate_) and any
    relationship touching them (mutates model_json). Returns Skipped status rows."""
    auto = {t["name"] for t in model_json.get("tables", []) if _AUTO_TABLE.match(t["name"])}
    skipped = [{"name": n, "status": "Skipped",
                "note": "Power BI auto date table (internal); not migrated"}
               for n in sorted(auto)]
    if auto:
        model_json["tables"] = [t for t in model_json["tables"] if t["name"] not in auto]
        model_json["relationships"] = [
            r for r in model_json.get("relationships", [])
            if r.get("fromTable") not in auto and r.get("toTable") not in auto]
    return skipped


def _force_physical_join_keys(model_json):
    """Calculated columns used as a JOIN KEY must be physical (joins are physical), so map
    "Table::Col" -> inferred data_type (from the column it joins to) for materialization."""
    phys_type, calc_set = {}, set()
    for t in model_json.get("tables", []):
        for c in t.get("columns", []):
            if c.get("calculated"):
                calc_set.add((t["name"], c["name"]))
            else:
                phys_type[(t["name"], c["name"])] = c.get("dataType")
    force_physical = {}
    for rel in model_json.get("relationships", []):
        ends = [(rel.get("fromTable"), rel.get("fromColumn")),
                (rel.get("toTable"), rel.get("toColumn"))]
        for (tbl, col), (otbl, ocol) in (ends, ends[::-1]):
            if (tbl, col) in calc_set:
                dt = phys_type.get((otbl, ocol)) or ("int64" if str(col).lower().endswith("id") else "string")
                force_physical[f"{tbl}::{col}"] = dt
    return force_physical


def _build_joins(rels, table_names, dropped_ids, join_type):
    """Relationships -> ({src_table: [join,...]} keyed by the from/many side, rel status rows).
    Real cardinality comes from the file via _cardinality (default MANY_TO_ONE)."""
    joins_by_src, rel_rows = {}, []
    for rel in rels:
        ft, fc = rel.get("fromTable"), rel.get("fromColumn")
        tt, tc = rel.get("toTable"), rel.get("toColumn")
        nm = rel.get("name") or f"{ft}->{tt}"
        if not (ft and tt and fc and tc):
            rel_rows.append({"name": nm, "status": "NEEDS REVIEW",
                             "note": "relationship missing an endpoint column"})
            continue
        if ft not in table_names or tt not in table_names:
            rel_rows.append({"name": nm, "status": "NEEDS REVIEW",
                             "note": "relationship references an unknown table"})
            continue
        if f"{ft}::{fc}" in dropped_ids or f"{tt}::{tc}" in dropped_ids:
            rel_rows.append({"name": nm, "status": "NEEDS REVIEW",
                             "note": "join key column has no physical match (dropped); join skipped"})
            continue
        card = _cardinality(rel)
        joins_by_src.setdefault(ft, []).append({
            "with": tt,
            "on": f"[{ft}::{fc}] = [{tt}::{tc}]",
            "type": join_type,
            "cardinality": card,
        })
        note = f"{join_type}, {card}"
        if (rel.get("crossFilter") or "").lower() in ("both", "bothdirections"):
            note += "; PBI bidirectional cross-filter not modelled (verify)"
        rel_rows.append({"name": nm, "status": "Migrated", "note": note})
    return joins_by_src, rel_rows


def _build_physical_columns(tables, dropped_ids, force_physical, warnings):
    """Every physical column -> model columns[], keeping column_id stable and only
    disambiguating colliding display names (a join references column_id, so dropping a
    column would break a join). Returns (columns, seen_display_names_lower)."""
    seen, columns, renamed = set(), [], []
    for t in tables:
        for c in t.get("columns", []):
            colid = f"{t['name']}::{c['name']}"
            if c.get("calculated") and colid not in force_physical:
                continue
            if colid in dropped_ids:
                continue
            disp = c["name"]
            if disp.lower() in seen:
                disp = f"{c['name']} ({t['name']})"
                i = 2
                while disp.lower() in seen:
                    disp = f"{c['name']} ({t['name']} {i})"
                    i += 1
                renamed.append(f"{colid} -> '{disp}'")
            seen.add(disp.lower())
            if c.get("calculated"):       # materialized join-key calc column -> attribute
                ctype, agg = "ATTRIBUTE", None
            else:
                ctype, agg = _col_role(c)
            props = {"column_type": ctype}
            if agg:
                props["aggregation"] = agg
            columns.append({"name": disp, "column_id": colid, "properties": props})
    if renamed:
        warnings.append("Duplicate display names disambiguated (all columns kept, "
                        "column_id unchanged): " + ", ".join(renamed))
    return columns, seen


def _add_formula(ctx, name, dax, kind, home_table=None, home_cols=None):
    """Translate one measure/calc-column and append its status row, formula, and column
    entry into the shared build context `ctx` (an override ts_formula wins). NEEDS-REVIEW
    formulas record a status row but emit no formula."""
    ov = ctx["ov_measures"].get(name)
    if ov and ov.get("ts_formula"):
        expr, status = ov["ts_formula"], ov.get("status", "Migrated")
        note = ov.get("note", "from overrides")
    else:
        expr, status, note = translate_dax(dax, home_table, home_cols,
                                           ctx["date_cols"], ctx["measure_dax"], ctx["physical_cols"])
    if expr and any(f"[{d}]" in expr for d in ctx["dropped_ids"]):
        expr, status = None, "NEEDS REVIEW"
        note = (note + "; " if note else "") + "references a column with no physical match (dropped)"
    ctx["measure_rows"].append({"name": name, "original_dax": dax,
                                "ts_formula": expr or "", "status": status, "note": note})
    if not expr:
        return  # NEEDS REVIEW: do not emit an invalid formula
    if name.lower() in ctx["seen"]:        # case-insensitive: ThoughtSpot display names must be unique
        # a measure/calc column whose name collides with a physical column (seen is seeded
        # with physical display names) or an already-emitted formula: emit NEITHER the
        # formula nor the column and flag it, rather than emitting a duplicate-named formula
        # that TML import can reject.
        ctx["measure_rows"][-1]["status"] = "NEEDS REVIEW"
        ctx["measure_rows"][-1]["note"] = ((note + "; ") if note else "") + "name collides with an existing column; not emitted"
        return
    ctx["seen"].add(name.lower())
    fid = f"formula_{name}"
    ctx["formulas"].append({"id": fid, "name": name, "expr": expr})
    # an override may force the column role (e.g. a month-of-year axis formula is an
    # ATTRIBUTE, not a summable MEASURE)
    ctype = (ov.get("column_type") if ov else None) or ("MEASURE" if kind == "measure" else "ATTRIBUTE")
    ctx["columns"].append({"name": name, "formula_id": fid, "properties": {"column_type": ctype}})


def _formula_ctx(tables, overrides, force_physical, dropped_ids, seen, columns):
    """Assemble the shared formula-build context: the override map, DATE columns (for
    diff_days), the measure/calc DAX map (for [formula_<name>] id-refs), and the mutable
    outputs. Consumed by _add_formula / _emit_table_formulas."""
    ov_measures = {m["name"]: m for m in (overrides.get("measures") or [])}
    date_cols = {f"{t['name']}::{c['name']}" for t in tables for c in t.get("columns", [])
                 if (c.get("dataType") or "").lower() in ("datetime", "date") and not c.get("calculated")}
    measure_dax = {me["name"]: me.get("expression", "") for t in tables for me in t.get("measures", [])}
    measure_dax.update({c["name"]: c.get("expression", "") for t in tables for c in t.get("columns", [])
                        if c.get("calculated") and f"{t['name']}::{c['name']}" not in force_physical})
    return {"ov_measures": ov_measures, "formulas": [], "measure_rows": [], "columns": columns,
            "seen": seen, "date_cols": date_cols, "measure_dax": measure_dax, "dropped_ids": dropped_ids,
            "physical_cols": _physical_col_names(tables, force_physical)}


def _physical_col_names(tables, force_physical):
    """Display names of columns that remain physical in the Table TML: non-calculated
    columns, plus calc columns forced physical because they are used as join keys."""
    return {c["name"] for t in tables for c in t.get("columns", [])
            if not c.get("calculated") or f"{t['name']}::{c['name']}" in force_physical}


def _emit_table_formulas(ctx, t, force_physical):
    """Translate one table's measures + non-materialized calc columns into ctx (via
    _add_formula). Bare DAX refs to this table's physical columns get qualified to
    [table::col] so display-name renames don't break them."""
    hcols = {c["name"] for c in t.get("columns", []) if not c.get("calculated")}
    hcols |= {c["name"] for c in t.get("columns", [])
              if c.get("calculated") and f"{t['name']}::{c['name']}" in force_physical}
    for m in t.get("measures", []):
        _add_formula(ctx, m["name"], m.get("expression", ""), "measure", t["name"], hcols)
    for c in t.get("columns", []):
        if c.get("calculated") and f"{t['name']}::{c['name']}" not in force_physical:
            _add_formula(ctx, c["name"], c.get("expression", ""), "column", t["name"], hcols)


def _build_formulas(tables, overrides, dropped_ids, force_physical, seen, columns):
    """DAX measures + calc columns -> model formulas[] (id-referenced). Override measures
    win and can add formulas with no Power BI counterpart (parameter-driven SPLY/YoY).
    Returns (formulas, measure_status_rows)."""
    ctx = _formula_ctx(tables, overrides, force_physical, dropped_ids, seen, columns)
    for t in tables:
        _emit_table_formulas(ctx, t, force_physical)
    # Override-only measures added last so they can reference PBI measures by [formula_<name>].
    existing = {f["name"] for f in ctx["formulas"]}
    for name, ov in ctx["ov_measures"].items():
        if name not in existing and ov.get("ts_formula"):
            _add_formula(ctx, name, "", "measure")
    return ctx["formulas"], ctx["measure_rows"]


def _cascade_flag(formulas, measure_rows, columns):
    """Drop any formula referencing [formula_X] where X did not translate (would dangle at
    import), cascading, and flip its status row to NEEDS REVIEW (keeps the report honest
    instead of a 'Migrated' formula being silently pruned on import)."""
    row_by_name = {r["name"]: r for r in measure_rows}
    idref = re.compile(r"\[formula_([^\]]+)\]")
    changed = True
    while changed:
        changed = False
        emitted = {f["name"] for f in formulas}
        for f in list(formulas):
            dangling = sorted({x for x in idref.findall(f["expr"])
                               if x != f["name"] and x not in emitted})
            if dangling:
                formulas.remove(f)
                columns[:] = [c for c in columns if c.get("formula_id") != f["id"]]
                r = row_by_name.get(f["name"])
                if r:
                    r["status"], r["ts_formula"] = "NEEDS REVIEW", ""
                    r["note"] = ((r["note"] + "; ") if r.get("note") else "") + \
                        "depends on un-migrated measure(s): " + ", ".join(dangling)
                changed = True


def _topo_sort_formulas(formulas):
    """Order formulas so a formula appears AFTER the formulas it references by id
    (ThoughtSpot adds them sequentially; a forward [formula_X] ref fails). Cycle-safe."""
    fnames = {f["name"] for f in formulas}
    by_name = {f["name"]: f for f in formulas}
    ordered, state = [], {}      # state: 1=visiting, 2=done

    def _visit(f):
        if state.get(f["name"]):
            return                                   # done or in a cycle -> skip
        state[f["name"]] = 1
        for g in fnames:
            if g != f["name"] and f"[formula_{g}]" in f["expr"]:
                _visit(by_name[g])
        state[f["name"]] = 2
        ordered.append(f)

    for f in formulas:
        _visit(f)
    return ordered


def build_model_tml(model_json, model_name, join_type, overrides, warnings,
                    dropped_ids=None, force_physical=None):
    """Return (model_tml_dict, measure_status_rows, rel_status_rows)."""
    dropped_ids = dropped_ids or set()     # "Table::Col" dropped at the physical layer
    force_physical = force_physical or {}  # calc cols emitted as physical (join keys)
    tables = model_json.get("tables", [])
    rels = model_json.get("relationships", [])
    table_names = {t["name"] for t in tables}

    joins_by_src, rel_rows = _build_joins(rels, table_names, dropped_ids, join_type)
    model_tables = []
    for t in tables:
        entry = {"name": t["name"]}
        if t["name"] in joins_by_src:
            entry["joins"] = joins_by_src[t["name"]]
        model_tables.append(entry)

    columns, seen = _build_physical_columns(tables, dropped_ids, force_physical, warnings)
    formulas, measure_rows = _build_formulas(tables, overrides, dropped_ids, force_physical, seen, columns)
    _cascade_flag(formulas, measure_rows, columns)
    formulas = _topo_sort_formulas(formulas)

    model = {
        "obj_id": f"{_slug(model_name)}-pbi",
        "model": {"name": model_name, "model_tables": model_tables, "columns": columns},
    }
    if formulas:
        model["model"]["formulas"] = formulas
    # Enable Spotter (NL search); a TML-imported model defaults it off, so the ai/answer
    # APIs return "No answer found" until set true. Default on; override spotter_enabled.
    props = {"spotter_config": {"is_spotter_enabled": overrides.get("spotter_enabled", True)}}
    props.update(overrides.get("model_properties") or {})
    model["model"]["properties"] = props
    # Parameters (overrides.parameters): typed model-level values a formula reads by name
    # (e.g. a Reference Date driving parameter-based SPLY/YoY). DATE default_value is MM/DD/YYYY.
    params = overrides.get("parameters")
    if params:
        model["model"]["parameters"] = params
    return model, measure_rows, rel_rows


def assemble(inv, overrides, connection, db, schema, join_type, lower_db_table, model_name=None):
    """Parsed inventory -> (files, mapping). Pure (no I/O): drops auto-date tables, finds
    join-key calc columns, emits a Table TML per source table + the Model TML, and returns
    files = [(filename, tml_dict), ...] plus the mapping.json status dict. The connection
    block carries name only (never fqn) per repo invariant."""
    warnings = list(inv.get("warnings", []))
    src = (inv.get("source_folder") or "").rstrip("/").split("/")[-1] or "Power BI project"
    m_name = model_name or overrides.get("project_name") or f"{src} Model"

    table_rows = _drop_auto_date_tables(inv)
    force_physical = _force_physical_join_keys(inv)

    conn = overrides.get("connection") or {}
    conn_name = conn.get("name") or connection
    dbn, sch = conn.get("db") or db, conn.get("schema") or schema
    table_map = overrides.get("table_map") or {}
    column_map = overrides.get("column_map") or {}
    drop_unmapped = bool(overrides.get("drop_unmapped_columns"))

    files, dropped_ids = [], set()
    for t in inv.get("tables", []):
        tml, dropped = build_table_tml(t, conn_name, dbn, sch, warnings, table_map,
                                       column_map, drop_unmapped, lower_db_table, force_physical)
        for d in dropped:
            dropped_ids.add(f"{t['name']}::{d}")
        files.append((f"{_slug(t['name'])}.table.tml", tml))
        table_rows.append({"name": t["name"], "status": "Migrated",
                           "note": (f"bound to db_table '{table_map[t['name']]}'" if t["name"] in table_map
                                    else f"db_table guessed as '{_dbname(t['name'])}'; verify")})

    model_tml, measure_rows, rel_rows = build_model_tml(
        inv, m_name, join_type, overrides, warnings, dropped_ids, force_physical)
    files.append((f"{_slug(m_name)}.model.tml", model_tml))

    mapping = {"project_name": m_name, "tables": table_rows, "relationships": rel_rows,
               "measures": measure_rows, "warnings": warnings}
    return files, mapping
