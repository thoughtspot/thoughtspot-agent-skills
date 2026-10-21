"""Sisense -> ThoughtSpot Model TML assembly (joins, columns, calc-column formulas).

Ported from the standalone converter (map/model.py). Pure functions, no I/O. The
top-level entry point is assemble(): parsed inventory -> (files, mapping), mirroring
the Power BI converter's assemble. build_model_tml builds the Model TML itself.

Join orientation: every join runs from the fact (MANY) side to the dimension (ONE) side,
with cardinality read from the relation (default MANY_TO_ONE). Sisense exports no
cardinality, so the fact side is inferred by ranking every table once (_fact_rank) and
orienting each relation from the higher-ranked table to the lower. One global ranking
makes the graph acyclic by construction and, unlike a per-relation sort over a set of two
table ids, never depends on hash order (BL-398 — the join set used to vary with
PYTHONHASHSEED, so `ts tml lint` I17 passed on one run and failed on the next).

Model columns preserve the standalone converter's dedup behaviour: exactly ONE column
per display name, bound to the MOST-CONNECTED table. When a key column (e.g. "Category
ID") appears in both the fact and a dimension, only the fact's copy survives as a model
column — the dimension-side duplicate is dropped. This drops the dimension-side column
rather than disambiguating it; it is preserved here intentionally (the model path
mirrors the source's behaviour, warts included).

Serialization is NOT done here (assemble returns dicts); the command module serializes
with the shared ts_cli.tml_common.dump_tml_yaml. Formula-name transforms reuse the
shared ts_cli.formula_common helpers (never re-implemented per platform).
"""
from __future__ import annotations

from collections import Counter

from ts_cli.formula_common import (add_formula_prefix, expr_is_aggregated,
                                    fix_double_aggregation, resolve_name_collisions)
from ts_cli.sisense.functions import translate_jaql
from ts_cli.sisense.tables import _cardinality, _clean, _col_role, _dbname, _slug, build_table_tml


def _connectivity(relations: list) -> Counter:
    """table_id -> number of relation endpoints it participates in (the fact is highest)."""
    part: Counter = Counter()
    for rel in relations:
        for ep in rel.get("endpoints", []) or []:
            if ep.get("table"):
                part[ep["table"]] += 1
    return part


def _malformed_relation_note(eps: list, table_ids: set) -> str:
    """Why a relation cannot become a join, or "" when it is a well-formed binary one."""
    if len(eps) < 2 or len(eps) % 2 != 0:
        return "relation does not have an even number (>= 2) of endpoints"
    if any(ep.get("table") not in table_ids for ep in eps):
        return "relation references an unknown table"
    rel_tables = {ep.get("table") for ep in eps if ep.get("table")}
    if len(rel_tables) != 2:
        return f"relation spans {len(rel_tables)} tables; expected a binary relation"
    return ""


def _binary_relation_tables(rel: dict, table_ids: set):
    """The two table ids a well-formed relation joins, else None (the caller flags it)."""
    eps = rel.get("endpoints") or []
    if _malformed_relation_note(eps, table_ids):
        return None
    return {ep["table"] for ep in eps}


def _join_key_uses(relations: list, table_ids: set) -> dict:
    """table_id -> Counter{frozenset(join columns): relations joined on that key set}."""
    uses: dict = {}
    for rel in relations:
        if _binary_relation_tables(rel, table_ids) is None:
            continue
        keys: dict = {}
        for ep in rel["endpoints"]:
            keys.setdefault(ep["table"], set()).add(ep.get("column"))
        for tid, cols in keys.items():
            uses.setdefault(tid, Counter())[frozenset(cols)] += 1
    return uses


def _fact_rank(tables: list, relations: list, part: Counter) -> dict:
    """table_id -> sort key; ascending order = most fact-like first (the join source).

    Sisense exports no cardinality, so the MANY side is inferred from the shape of the
    relations, strongest signal first:
      1. more distinct join keys — a fact carries one foreign key per dimension it
         references, while a dimension is joined on its one key however many tables
         reference it (two facts sharing Product and Calendar: facts 2, dimensions 1);
      2. fewer shared keys — a key set a table joins on in two or more relations is its
         own key, referenced from several sides, which makes it the ONE side there (a
         snowflaked Product joined by two facts and to Category out-counts the facts on
         relations, but its ProductID is shared);
      3. more measure columns (the side holding the numbers is the fact);
      4. more relation endpoints (the standalone converter's original signal);
      5. table id — a total, hash-independent tie-break.
    """
    table_ids = {t["id"] for t in tables}
    uses = _join_key_uses(relations, table_ids)
    rank: dict = {}
    for t in tables:
        tid = t["id"]
        keys = uses.get(tid, Counter())
        shared = sum(1 for n in keys.values() if n > 1)
        measures = sum(1 for c in t.get("columns", []) if _col_role(c)[0] == "MEASURE")
        rank[tid] = (-len(keys), shared, -measures, -part[tid], str(tid))
    return rank


def _col_name_index(tables: list) -> dict:
    """(table_id, column_id) -> column display name — resolves join endpoints (which carry
    the column *id*) to the display *name* the model columns register under (Finding 6)."""
    idx: dict = {}
    for t in tables:
        tid = t["id"]
        for c in t.get("columns", []):
            idx[(tid, c["id"])] = c["name"]
    return idx


def _pair_on_token(pair: tuple, src_table, name_idx: dict) -> tuple:
    """One (from,to) endpoint pair -> ('[S::name] = [D::name]', None) or (None, note).

    Resolves each endpoint's column *id* to its display *name* so the ON token matches the
    model column_id exactly ({Table}::{name}); an unresolvable id yields a review note."""
    src_ep = next((e for e in pair if e.get("table") == src_table), None)
    dst_ep = next((e for e in pair if e.get("table") != src_table), None)
    if src_ep is None or dst_ep is None:
        return None, "a composite-key pair does not span both join tables"
    s_name = name_idx.get((src_ep.get("table"), src_ep.get("column")))
    d_name = name_idx.get((dst_ep.get("table"), dst_ep.get("column")))
    if not s_name or not d_name:
        return None, "a join key column id could not be resolved to a column name"
    return (f"[{_clean(src_ep['table'])}::{s_name}] "
            f"= [{_clean(dst_ep['table'])}::{d_name}]"), None


def _join_on_clause(eps: list, src_table, name_idx: dict) -> tuple:
    """All endpoint pairs -> a conjoined ON clause (composite keys AND'd), or (None, note).

    Endpoints arrive as consecutive (from,to) pairs; every pair is emitted so a two-column
    key produces '[S::c1] = [D::c1] AND [S::c2] = [D::c2]' (Finding 3 — no dropped pair)."""
    tokens: list = []
    for i in range(0, len(eps) - 1, 2):
        tok, err = _pair_on_token((eps[i], eps[i + 1]), src_table, name_idx)
        if err:
            return None, err
        tokens.append(tok)
    return " AND ".join(tokens), None


def _build_one_join(rel: dict, rank: dict, table_ids: set, join_type: str,
                    name_idx: dict, joins_by_src: dict) -> dict:
    """Emit one relation's join (into joins_by_src) and return its status row."""
    eps = rel.get("endpoints") or []
    bad = _malformed_relation_note(eps, table_ids)
    if bad:
        return {"name": "?", "status": "NEEDS REVIEW", "note": bad}
    # The more fact-like table (lower _fact_rank key) is the source (MANY) side.
    src_table, dst_table = sorted(_binary_relation_tables(rel, table_ids), key=rank.__getitem__)
    nm = f"{_clean(src_table)}_to_{_clean(dst_table)}"
    on, err = _join_on_clause(eps, src_table, name_idx)
    if err:
        return {"name": nm, "status": "NEEDS REVIEW", "note": err}
    card, defaulted = _cardinality(rel)
    joins_by_src.setdefault(src_table, []).append({
        "with": _clean(dst_table), "on": on, "type": join_type, "cardinality": card})
    if defaulted:
        return {"name": nm, "status": "NEEDS REVIEW",
                "note": (f"{join_type}, {card}; cardinality defaulted to MANY_TO_ONE "
                         "(Sisense exports none) — verify; a many-to-many bridge will fan out")}
    return {"name": nm, "status": "Migrated", "note": f"{join_type}, {card}"}


def _build_joins(relations: list, rank: dict, table_ids: set, join_type: str,
                 name_idx: dict) -> tuple:
    """Relations -> ({src_table_id: [join,...]} keyed by the fact/source side, rel status
    rows). The higher-ranked table (_fact_rank) is the source; cardinality via _cardinality."""
    joins_by_src: dict = {}
    rel_rows: list = [_build_one_join(rel, rank, table_ids, join_type, name_idx, joins_by_src)
                      for rel in relations]
    return joins_by_src, rel_rows


def _build_model_columns(tables: list, part: Counter) -> tuple:
    """One model column per display name, bound to the most-connected table (see module
    docstring: the dimension-side duplicate is dropped — preserved from the source).

    Returns (model_columns, review_rows). A numeric physical column that defaulted to a SUM
    measure gets a NEEDS REVIEW row (Finding 8 — flag, don't silently sum a Year-like column);
    calc columns are excluded (they resolve to formulas, not physical measures)."""
    best: dict = {}   # display name -> (connectedness score, table, column)
    for t in tables:
        score = part[t["id"]]
        for c in t.get("columns", []):
            cur = best.get(c["name"])
            if cur is None or score > cur[0]:
                best[c["name"]] = (score, t, c)
    mcols: list = []
    review_rows: list = []
    for _name, (_score, t, c) in best.items():
        ctype, agg, note = _col_role(c)
        props = {"column_type": ctype}
        if agg:
            props["aggregation"] = agg
        mcols.append({"name": c["name"], "column_id": f"{_clean(t['id'])}::{c['name']}",
                      "properties": props})
        if note and not (c.get("calculated") and c.get("expression")):
            review_rows.append({"name": c["name"], "original": "", "ts_formula": "",
                                "status": "NEEDS REVIEW", "note": note})
    return mcols, review_rows


def _calc_formula_name(name: str, physical: set) -> tuple:
    """De-collide a calc-column name against physical column names.

    A calc column sharing a physical column's name would, via add_formula_prefix, rewrite its
    own physical reference [Amount] into a self-reference [formula_Amount] and then
    resolve_name_collisions would drop the base column. Renaming the formula preserves both.
    Returns (formula_name, collision_note|"").
    """
    if name not in physical:
        return name, ""
    fname = f"{name} (Calc)"
    return fname, (f"calc column name collided with physical column '{name}'; renamed formula "
                   f"to '{fname}' to preserve the base column")


def _collect_calc_formulas(tables: list, physical: set) -> tuple:
    """Walk calc columns -> (formulas, measure_status_rows), de-colliding names vs physical."""
    formulas, measure_rows = [], []
    for t in tables:
        for c in t.get("columns", []):
            if not (c.get("calculated") and c.get("expression")):
                continue
            expr, status, note = translate_jaql(c["expression"])
            fname, coll = _calc_formula_name(c["name"], physical)
            if coll:
                note = (note + "; " + coll) if note else coll
            measure_rows.append({"name": fname, "original": c["expression"],
                                 "ts_formula": expr or "", "status": status, "note": note})
            if expr:
                formulas.append({"id": f"formula_{fname}", "name": fname, "expr": expr})
    return formulas, measure_rows


def _build_formulas(tables: list, columns: list) -> tuple:
    """Calculated columns (isCustom + expression) -> model formulas[] via translate_jaql.

    Sibling refs [Name] -> [formula_Name] id-refs (add_formula_prefix); a wrapped
    aggregation of an already-aggregated sibling is collapsed (fix_double_aggregation).
    Returns (formulas, formula_columns, measure_status_rows)."""
    physical = {c["name"] for t in tables for c in t.get("columns", [])
                if not (c.get("calculated") and c.get("expression"))}
    formulas, measure_rows = _collect_calc_formulas(tables, physical)
    if not formulas:
        return [], [], measure_rows

    formula_names = {f["name"] for f in formulas}
    for f in formulas:
        f["expr"] = add_formula_prefix(f["expr"], formula_names, set())
    fexprs = {f["name"]: f["expr"] for f in formulas}
    for f in formulas:
        f["expr"] = fix_double_aggregation(f["expr"], fexprs)

    formula_columns = []
    for f in formulas:
        ctype = "MEASURE" if expr_is_aggregated(f["expr"]) else "ATTRIBUTE"
        formula_columns.append({"name": f["name"], "formula_id": f["id"],
                                "properties": {"column_type": ctype}})
    return formulas, formula_columns, measure_rows


def build_model_tml(inv: dict, model_name: str, join_type: str, part: Counter,
                    overrides: dict, warnings: list) -> tuple:
    """Return (model_tml_dict, measure_status_rows, rel_status_rows)."""
    tables = inv.get("tables", [])
    relations = inv.get("relations", [])
    table_ids = {t["id"] for t in tables}

    name_idx = _col_name_index(tables)
    rank = _fact_rank(tables, relations, part)
    joins_by_src, rel_rows = _build_joins(relations, rank, table_ids, join_type, name_idx)
    model_tables = []
    for t in tables:
        entry = {"name": _clean(t["id"])}
        if t["id"] in joins_by_src:
            entry["joins"] = joins_by_src[t["id"]]
        model_tables.append(entry)

    columns, col_review_rows = _build_model_columns(tables, part)
    formulas, formula_columns, measure_rows = _build_formulas(tables, columns)
    columns = columns + formula_columns
    # Resolve collisions between physical columns and calc-column formulas (formula wins).
    columns, formulas, _rename = resolve_name_collisions(columns, formulas, [])

    model = {
        "obj_id": f"{_slug(model_name)}-sisense",
        "model": {"name": model_name, "model_tables": model_tables, "columns": columns},
    }
    if formulas:
        model["model"]["formulas"] = formulas
    # Enable Spotter (NL search): a TML-imported model defaults it off, so the ai/answer
    # APIs return "No answer found" until set true. Default on; override spotter_enabled.
    props = {"spotter_config": {"is_spotter_enabled": overrides.get("spotter_enabled", True)}}
    props.update(overrides.get("model_properties") or {})
    model["model"]["properties"] = props
    return model, measure_rows + col_review_rows, rel_rows


def assemble(inv: dict, overrides: dict, connection: str, db: str, schema: str,
             join_type: str = "LEFT_OUTER", lower_db_table: bool = False,
             model_name: str | None = None) -> tuple:
    """Parsed inventory -> (files, mapping). Pure (no I/O): emits a Table TML per source
    table + one Model TML, and returns files = [(filename, tml_dict), ...] plus the
    mapping.json status dict. The connection block carries name only (never fqn)."""
    overrides = overrides or {}
    warnings = list(inv.get("warnings", []))
    m_name = (model_name or overrides.get("model_name") or inv.get("source")
              or "Converted Model")

    conn = overrides.get("connection") or {}
    conn_name = conn.get("name") or connection
    dbn, sch = conn.get("db") or db, conn.get("schema") or schema

    tables = inv.get("tables", [])
    relations = inv.get("relations", [])
    part = _connectivity(relations)

    files: list = []
    table_rows: list = []
    for t in tables:
        tml, _dropped = build_table_tml(t, conn_name, dbn, sch, warnings, lower_db_table)
        name = _clean(t["id"])
        files.append((f"{_slug(name)}.table.tml", tml))
        table_rows.append({"name": name, "status": "Migrated",
                           "note": f"db_table '{tml['table']['db_table']}'; verify"})

    model_tml, measure_rows, rel_rows = build_model_tml(
        inv, m_name, join_type, part, overrides, warnings)
    files.append((f"{_slug(m_name)}.model.tml", model_tml))

    mapping = {"model_name": m_name, "tables": table_rows, "relationships": rel_rows,
               "measures": measure_rows, "warnings": warnings}
    return files, mapping
