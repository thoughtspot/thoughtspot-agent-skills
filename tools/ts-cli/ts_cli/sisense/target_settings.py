"""The target Model's own query settings, against Sisense's (pure, no I/O).

The binding checks assume ThoughtSpot joins only the tables a query reads, along the Model's
declared joins, filters nothing the widget does not, and reads the same warehouse rows Sisense
does. This module checks the Model and its Tables for anything that breaks that assumption,
with the same allowlist rule as the Sisense side (``allowlist.py``): a key is read, or only
presentation (search indexing, Spotter coaching, display format), or it is reported.

- Model level: ``filters`` and ``constraints`` filter every query; ``joins_with`` and a join's
  ``referencing_join`` declare joins this converter does not read; ``aggregated_models`` routes
  queries to other tables; ``properties.join_progressive`` off joins every table into every
  query. Each is a board-level reason: every tile is NEEDS REVIEW.
- Join type: a Sisense relation with no type is Sisense's default, an INNER join (Sisense
  docs, "Creating and Removing a Relationship Between Tables"). A Model join on a tile's path
  that is not ``INNER`` keeps rows Sisense drops (or the reverse), so the tile is flagged.
- Join type, per direction: a LEFT_OUTER join (fact kept) differs from INNER only where a
  tile shows the unmatched rows (a plotted column, an exclude, which keeps NULLs); RIGHT_OUTER,
  OUTER (dimension rows kept) or an unstated type differ wherever the tile reads the joined
  table, since an `=` filter keeps dimension rows with no fact. A join declared ONE_TO_MANY on
  the dimension side is read with its direction reversed (LEFT becomes RIGHT).
- Column level: a property that changes how a column aggregates (``is_additive``,
  ``is_attribution_dimension`` off), a missing ``column_type``, or a formula reading a parameter
  (its value is whatever the parameter is set to) flags the tiles that read that column -- and,
  followed through formula references, every formula built on it.
- Table level: the Tables are allowlisted too. ``rls_rules`` filter rows per user (Sisense data
  security is not compared), a pre-aggregated measure, or any key or column property not read
  flags the tiles reading that Table.
- Physical table: the Sisense table a binding stands for must read the same warehouse table
  (database, schema and table, as far as both sides state them) as the Table TML the Model
  column reads; a custom-SQL table on either side, or a side naming only a table, cannot be
  compared.
"""
from __future__ import annotations

import re
from collections import deque

_MODEL_READ = frozenset({"name", "description", "model_tables", "columns", "formulas", "properties",
                         "parameters"})
_MODEL_PRESENTATION = frozenset({"model_instructions", "action_object_associations", "column_groups",
                                 "spotter_config"})
_MODEL_REASONS = {
    "filters": "Model-level filters apply to every query ThoughtSpot runs, and Sisense applies none of them",
    "constraints": "Model-level date-range constraints filter every query, and Sisense applies none of them",
    "joins_with": "the Model declares joins at model level (joins_with), which this converter does not read",
    "aggregated_models": "the Model routes queries to aggregated models, which this converter does not compare",
}
_PROPERTIES_OK = frozenset({"is_bypass_rls", "join_progressive", "spotter_config"})
# a join condition this converter reads: one or more `[a::x] = [b::y]` joined by AND
_ON_CLAUSE = re.compile(r"\s*\[[^\]]+\]\s*=\s*\[[^\]]+\](\s+and\s+\[[^\]]+\]\s*=\s*\[[^\]]+\])*\s*", re.I)
# Table TML (``ts tml export --associated``)
_TABLE_TML_KEYS = frozenset({"name", "db", "schema", "db_table", "connection", "columns", "properties",
                             "description",
                             "joins_with"})   # read by a Model only through referencing_join, which is reported
_TABLE_TML_PROPS = frozenset({"spotter_config"})
_TABLE_COLUMN_KEYS = frozenset({"name", "db_column_name", "description", "properties", "db_column_properties"})
_TABLE_COLUMN_PROPS = frozenset({
    "column_type", "aggregation", "index_type", "index_priority", "value_casing", "synonyms", "synonym_type",
    "format_pattern", "is_hidden", "currency_type", "calendar", "spotiq_preference", "ai_context",
    "search_iq_preferred", "geo_config", "custom_order", "default_date_bucket"})
_DATE_TYPES = frozenset({"DATE", "DATE_TIME", "TIME", "TIMESTAMP", "DATETIME"})
_TABLE_KEYS = frozenset({"name", "alias", "fqn", "obj_id", "id", "joins"})
_JOIN_KEYS = frozenset({"with", "on", "type", "cardinality", "name"})
_COLUMN_KEYS = frozenset({"name", "column_id", "formula_id", "description", "properties",
                          "data_panel_column_groups"})
# column properties that only change search, display or Spotter, never a number
_COLUMN_PROPS_OK = frozenset({
    "column_type", "aggregation", "index_type", "index_priority", "is_hidden", "format_pattern",
    "currency_type", "geo_config", "spotiq_preference", "search_iq_preferred", "ai_context",
    "custom_order", "default_date_bucket", "calendar", "value_casing", "synonyms", "synonym_type"})
# properties read at their default only: off changes how the column aggregates across joins
_COLUMN_PROPS_DEFAULT = {"is_additive": (True, None), "is_attribution_dimension": (True, None)}


def model_problems(model: dict) -> list:
    """Model-level reasons every tile is NEEDS REVIEW (empty when the Model is plain)."""
    out = [_MODEL_REASONS.get(key, f"the Model sets {key}, which this converter does not read")
           for key, value in model.items()
           if key not in _MODEL_READ and key not in _MODEL_PRESENTATION and value not in (None, [], {})]
    return out + _property_reasons(model.get("properties") or {}) + \
        [r for mt in model.get("model_tables") or [] for r in _table_reasons(mt)]


def _property_reasons(props: dict) -> list:
    out = [] if props.get("join_progressive") is True else [
        "the Model's join_progressive is off or unset, so ThoughtSpot joins every table into every query, "
        "not only the ones a tile reads"]
    if props.get("is_bypass_rls"):
        out.append("the Model bypasses row-level security (is_bypass_rls), which Sisense data security is not "
                   "compared with")
    return out + [f"the Model sets properties.{k}, which this converter does not read" for k in props if k not in _PROPERTIES_OK]


def _table_reasons(mt: dict) -> list:
    inst = mt.get("alias") or mt.get("name")
    out = [f"model table {inst} sets {k}, which this converter does not read" for k in mt if k not in _TABLE_KEYS]
    for j in mt.get("joins") or []:
        out += [f"a join from {inst} to {j.get('with')} sets {k}, which this converter does not read"
                for k in j if k not in _JOIN_KEYS and k is not True]   # YAML 1.1 reads `on:` as True
        on = j.get("on", j.get(True))
        if isinstance(on, str) and not _ON_CLAUSE.fullmatch(on):
            out.append(f"the join from {inst} to {j.get('with')} is on {on!r}, which is not a column-equals-column "
                       "condition this converter reads")
    return out


def column_problems(model: dict) -> dict:
    """Model column name -> why a tile reading it may not return Sisense's numbers. A formula
    inherits the problems of every column and formula it references, to a fixed point."""
    params = {p.get("name") for p in model.get("parameters") or [] if p.get("name")}
    formulas = {f.get("id"): f.get("expr") or "" for f in model.get("formulas") or []}
    columns = model.get("columns") or []
    own = {c.get("name"): _column_reasons(c, params, formulas.get(c.get("formula_id"), "")) for c in columns}
    _inherit(own, _formula_uses(columns, formulas))
    return {name: (f"Model column [{name}] " + "; ".join(why) + ", which this converter does not compare with Sisense")
            for name, why in own.items() if why}


def _inherit(own: dict, uses: dict) -> None:
    """A formula built on a column with a problem has that problem too, to a fixed point."""
    changed = True
    while changed:
        changed = False
        for name, used in uses.items():
            extra = [f"is built on [{u}]" for u in sorted(used) if own.get(u) and f"is built on [{u}]" not in own[name]]
            if extra:
                own[name] = own[name] + extra
                changed = True


def _formula_uses(columns: list, formulas: dict) -> dict:
    """Formula column -> the Model columns its expression references (by name, formula id or column_id)."""
    by_ref = {}
    for c in columns:
        by_ref[c.get("name")] = c.get("name")
        for key in ("formula_id", "column_id"):
            if c.get(key):
                by_ref[c[key]] = c.get("name")
    return {c.get("name"): {by_ref[r] for r in re.findall(r"\[([^\]]+)\]", formulas.get(c.get("formula_id"), ""))
                            if r in by_ref and by_ref[r] != c.get("name")}
            for c in columns if c.get("formula_id")}


def _column_reasons(c: dict, params: set, expr: str) -> list:
    props = c.get("properties") or {}
    why = [f"sets {k}" for k in c if k not in _COLUMN_KEYS]
    if props.get("column_type") not in ("ATTRIBUTE", "MEASURE"):
        why.append("states no column_type (ATTRIBUTE or MEASURE)")
    why += [f"sets properties.{k}" for k in props if k not in _COLUMN_PROPS_OK and k not in _COLUMN_PROPS_DEFAULT]
    why += [f"sets properties.{k}: {props[k]}" for k, ok in _COLUMN_PROPS_DEFAULT.items()
            if k in props and props[k] not in ok]
    return why + [f"is a formula reading parameter [{p}], so it shows whatever the parameter is set to"
                  for p in sorted(params) if f"[{p}]" in expr]


def join_type_problem(target, facts: list, null_side: set, reads: set = frozenset()) -> str:
    """Joins on the tile's paths (each fact to each instance it reads, or between the instances
    when it reads no fact) that differ from Sisense's INNER for what the tile shows: a LEFT_OUTER
    join on the path to a ``null_side`` instance (its unmatched rows are shown), any other
    non-INNER join on the path to any instance in ``null_side | reads``."""
    insts = set(null_side) | set(reads)
    starts = [f for f in facts if f in insts or any(i in target.reachable(f) for i in insts)] or sorted(insts)
    bad = set()
    for start in starts:
        for inst in insts - {start}:
            for edge in _path(target, start, inst):
                kind = target.join_type.get(edge)
                if kind != "INNER" and (kind != "LEFT_OUTER" or inst in null_side):
                    bad.add((edge[0], edge[1], kind or "of no stated type"))
    if not bad:
        return ""
    joins = ", ".join(f"{a} > {b} ({k})" for a, b, k in sorted(bad))
    return f"join not INNER on its path: {joins} (see the join-type row)"


def join_type_row(target):
    """The board-level explanation behind every 'join not INNER' note, once."""
    kinds = sorted({k or "of no stated type" for k in target.join_type.values() if k != "INNER"})
    if not kinds:
        return None
    n = sum(1 for k in target.join_type.values() if k != "INNER")
    return {"visual": "(join types)", "ts_chart": "-", "status": "NEEDS REVIEW",
            "note": (f"{n} of the Model's {len(target.join_type)} joins are {', '.join(kinds)}, not INNER (read in the "
                     "fact-to-dimension direction). A Sisense relation with no join type is an INNER join (Sisense "
                     "docs, 'Creating and Removing a Relationship Between Tables'), so a row with no match on the other "
                     "side is dropped in Sisense and kept (with nulls) by an outer join. Each tile whose path uses one "
                     "where that shows is flagged; its numbers match only if no key on that path is unmatched, or "
                     "once the joins are INNER")}


def path_instances(target, facts: list, insts: set) -> set:
    """Every instance on the many -> one paths from the tile's facts to the instances it reads
    (the ends included). With no fact (a widget naming none), the paths between its own tables:
    a fact the query never joins is not on its path."""
    out = set()
    for start in facts or sorted(insts):
        for inst in insts - {start}:
            for many, one, _ in _path(target, start, inst):
                out |= {many, one}
    return out


def _path(target, start: str, goal: str) -> list:
    """One shortest many -> one path start -> goal as (many, one, fk) edges; [] if none."""
    seen, todo = {start: []}, deque([start])
    while todo:
        cur = todo.popleft()
        if cur == goal:
            return seen[cur]
        for nxt, fk in target.joins.get(cur, []):
            if nxt and nxt not in seen:
                seen[nxt] = seen[cur] + [(cur, nxt, fk)]
                todo.append(nxt)
    return []


_SQL_VIEW = "(sql view)"


def table_connections(tables) -> dict:
    """Table name -> the ThoughtSpot connection it reads."""
    return {(t.get("table") or t.get("sql_view") or {}).get("name"):
            ((t.get("table") or t.get("sql_view") or {}).get("connection") or {}).get("name") for t in tables or []}


def table_physicals(tables) -> dict:
    """Table / SQL View TML dicts -> {Table name: 'db.schema.table' lower-case (as far as stated),
    or _SQL_VIEW}. A Table whose export names no db_table is left out (nothing to compare; the
    Table problems report it)."""
    out = {}
    for t in tables or []:
        if t.get("sql_view"):
            out[t["sql_view"].get("name")] = _SQL_VIEW
            continue
        body = t.get("table") or t
        parts = [body.get(k) or "" for k in ("db", "schema", "db_table")]
        if parts[2]:
            out[body.get("name")] = ".".join(p for p in parts if p).lower()
    return out


def table_problems(tables) -> dict:
    """Table name -> why a tile reading it may not return Sisense's numbers (the Table allowlist)."""
    out = {}
    for t in tables or []:
        body = t.get("table")
        if not isinstance(body, dict):
            continue
        why = [_TABLE_REASONS.get(k, f"sets {k}") for k in body if k not in _TABLE_TML_KEYS and body[k] not in (None, [], {})]
        why += [f"sets properties.{k}" for k in body.get("properties") or {} if k not in _TABLE_TML_PROPS]
        if not body.get("db_table"):
            why.append("names no db_table, so its warehouse table cannot be compared with Sisense's")
        why += [r for c in body.get("columns") or [] for r in _table_column_reasons(c)]
        if why:
            out[body.get("name")] = f"Table {body.get('name')} " + "; ".join(why) + ", which this converter does not compare with Sisense"
    return out


_TABLE_REASONS = {"rls_rules": "has row-level security rules (rows filtered per user; Sisense data security is "
                               "not read)"}


def _table_column_reasons(c: dict) -> list:
    props = c.get("properties") or {}
    why = [f"column {c.get('name')} sets {k}" for k in c if k not in _TABLE_COLUMN_KEYS]
    why += [f"column {c.get('name')} sets properties.{k}" for k in props if k not in _TABLE_COLUMN_PROPS]
    return why


def formula_dates(model: dict, dates: set, table_dates: set = frozenset(), base_of=None) -> set:
    """Model formula columns that read a date column (directly or through other formulas, or a
    date Table column no Model column exposes): their values are dates or derived from one, so no
    search form for them is verified either."""
    formulas = {f.get("id"): f.get("expr") or "" for f in model.get("formulas") or []}
    columns = model.get("columns") or []
    base_of = base_of or {}
    out = {c.get("name") for c in columns
           if c.get("name") in dates or _reads_date(formulas.get(c.get("formula_id"), ""), table_dates, base_of)}
    flags = {name: (["date"] if name in out else []) for name in (c.get("name") for c in columns)}
    _inherit(flags, _formula_uses(columns, formulas))
    return {name for name, why in flags.items() if why}


def _reads_date(expr: str, table_dates: set, base_of: dict) -> bool:
    if _DATE_FUNCTION.search(expr or ""):
        return True
    return any((base_of.get(i, i), col) in table_dates for i, col in re.findall(r"\[([^\]:]+)::([^\]]+)\]", expr))


# a formula that is one if / else-if / else whose every branch is a boolean literal
_COND = r"\((?:(?!\bthen\b|\belse\b).)*?\)"       # a condition that runs into no branch
_BOOL_FORMULA = re.compile(rf"\s*if\s*{_COND}\s*then\s+(?:true|false)"
                           rf"(?:\s+else\s+if\s*{_COND}\s*then\s+(?:true|false))*\s+else\s+(?:true|false)\s*",
                           re.I | re.S)
# date functions: a formula using one returns a date or a value derived from one
_DATE_FUNCTION = re.compile(r"\b(?:to_date|date|today|now|add_\w+|start_of_\w+|end_of_\w+)\s*\(", re.I)
# the boolean filters verified live (26.11): `= true` and `= false` return exactly the true and
# the false rows, `!= true` the false rows; nothing else on a boolean column is verified
VERIFIED_BOOLEAN_TERMS = {("=", "true"), ("=", "false"), ("!=", "true")}


def boolean_columns(model: dict, tables, base_of: dict) -> set:
    """Model columns that are booleans: over a BOOL Table column, or a formula whose every
    then / else branch is `true` or `false`."""
    bools = _bool_table_columns(tables)
    formulas = {f.get("id"): f.get("expr") or "" for f in model.get("formulas") or []}
    out = set()
    for c in model.get("columns") or []:
        cid = c.get("column_id") or ""
        on_bool = "::" in cid and (base_of.get(cid.split("::")[0]), cid.split("::", 1)[1]) in bools
        if on_bool or _boolean_formula(formulas.get(c.get("formula_id"), "")):
            out.add(c.get("name"))
    return out


def _bool_table_columns(tables) -> set:
    return {((t.get("table") or {}).get("name"), c.get("name")) for t in tables or []
            for c in (t.get("table") or {}).get("columns") or []
            if str((c.get("db_column_properties") or {}).get("data_type") or "").upper() in ("BOOL", "BOOLEAN")}


def _boolean_formula(expr: str) -> bool:
    return bool(_BOOL_FORMULA.fullmatch(expr or ""))


_NUMBER_TYPES = frozenset({"INT32", "INT64", "DOUBLE", "FLOAT", "DECIMAL", "NUMBER", "BIGINT", "INT"})


def number_columns(model: dict, tables, base_of: dict) -> set:
    """Model columns over a numeric Table column."""
    nums = {((t.get("table") or {}).get("name"), c.get("name")) for t in tables or []
            for c in (t.get("table") or {}).get("columns") or []
            if str((c.get("db_column_properties") or {}).get("data_type") or "").upper() in _NUMBER_TYPES}
    return {c.get("name") for c in model.get("columns") or [] if "::" in (c.get("column_id") or "")
            and (base_of.get(c["column_id"].split("::")[0]), c["column_id"].split("::", 1)[1]) in nums}


def date_columns(tables) -> set:
    """(Table name, Table column name) of every DATE / DATE_TIME / TIME column."""
    out = set()
    for t in tables or []:
        body = t.get("table") or t.get("sql_view") or {}
        for c in body.get("columns") or body.get("sql_view_columns") or []:
            if str((c.get("db_column_properties") or {}).get("data_type") or "").upper() in _DATE_TYPES:
                out.add((body.get("name"), c.get("name")))
    return out


def physical_problem(sis: dict, ts_physical: dict, base: str) -> str:
    """Why the Sisense table ``sis`` and the Model's Table ``base`` may not read the same rows, or ''."""
    if not sis:
        return ""
    name = sis.get("jaql_name") or sis.get("id")
    if sis.get("physical_problem"):     # a Sisense-side fact, whatever the Model reads
        return f"Sisense table {name}: {sis['physical_problem']}"
    if sis.get("unsupported"):
        return f"Sisense table {name} carries settings this converter does not read: {', '.join(sis['unsupported'])}"
    if base not in ts_physical:
        return ""          # no Table TML: the board-level "export with --associated" row covers it
    if not sis.get("physical"):
        return ""          # a bundle that does not say which warehouse table it reads
    ts_side = ts_physical[base]
    if ts_side == _SQL_VIEW:
        return f"Model table {base} is a SQL View, so whether it reads Sisense table {name}'s rows cannot be compared"
    sis_parts, ts_parts = sis["physical"].split("."), ts_side.split(".")
    if len(sis_parts) < 3 or len(ts_parts) < 3:
        return (f"Sisense table {name} reads {sis['physical']} and Model table {base} reads {ts_side}; without a "
                "database and schema on both sides they cannot be compared")
    if sis_parts[-3:] != ts_parts[-3:]:
        return f"Sisense table {name} reads {sis['physical']}, but Model table {base} reads {ts_side}"
    return ""


def board_reasons(inv: dict, target) -> list:
    """Reasons every tile is NEEDS REVIEW: the Model's own query settings, and Sisense relations
    whose join type is not the default."""
    rel = sorted({r["problem"] for r in inv.get("relations") or [] if r.get("problem")})
    dash_source = (inv.get("dashboard") or {}).get("datasource")
    model = inv.get("datamodel_title")
    other = [f"the bundle's data model is '{model}', but the dashboard reads data source '{dash_source}'"] \
        if model and dash_source and model != dash_source else []
    no_model = [] if inv.get("tables") else [
        "the bundle carries no Sisense data model, so relations, calculated columns and warehouse tables "
        "cannot be checked for any tile"]
    model_keys = inv.get("datamodel_unsupported") or []
    dm = [f"the Sisense data model carries settings this converter does not read: {', '.join(model_keys)}"] \
        if model_keys else []
    bundle = [f"the bundle carries keys this converter does not read: {', '.join(inv['bundle_unsupported'])}"] \
        if inv.get("bundle_unsupported") else []
    return list(target.problems) + rel + other + dm + no_model + bundle + connection_reasons(inv, target)


def connection_reasons(inv: dict, target) -> list:
    """The warehouse connection each side reads, which names alone cannot prove equal: one reason
    unless every Table's connection is declared to be the Sisense dataset's (``connections`` in the
    overrides: {"<Sisense connection>": "<ThoughtSpot connection>"})."""
    sis = sorted({c for c in inv.get("connections") or [] if c})
    ts = sorted(set(target.table_connections.values()) - {None})
    if not sis or not ts:
        return []
    declared = target.declared_connections
    reached = {declared[s] for s in sis if s in declared}      # only names Sisense actually reads count
    if all(s in declared for s in sis) and set(ts) <= reached:
        return []
    return [f"the Sisense data reads connection(s) {', '.join(sis)} and the Model's Tables read {', '.join(ts)}; "
            "that they reach the same warehouse is not checked (declare it with `connections` in the overrides)"]


_VALUE_FILTER = re.compile(r"\]\s*!?=\s*(?:'|-?\d)")     # text or a number under = / !=


def value_matching_row(answers: list, chips: list):
    """One board-level row when a carried filter compares text values: ThoughtSpot matches them
    without regard to case and keeps NULL rows under `!=` (live-verified, 26.11); whether Sisense
    members and excludes match the same way is not verified. None when nothing compares text."""
    tiles = [a["answer"]["name"] for a in answers if _VALUE_FILTER.search(a["answer"].get("search_query") or "")]
    chip_cols = [c["column"][0] for c in chips if c.get("oper") and c.get("values")]
    if not tiles and not chip_cols:
        return None
    where = "; ".join(filter(None, [("tiles: " + ", ".join(tiles)) if tiles else "",
                                    ("chips: " + ", ".join(chip_cols)) if chip_cols else ""]))
    return {"visual": "(filter value matching)", "ts_chart": "FILTER", "status": "NEEDS REVIEW",
            "_tiles": tiles, "_chips": chip_cols,
            "note": ("ThoughtSpot search matches filter values without regard to case (= 'active' matches "
                     "Active) and keeps NULL rows under != (live-verified, 26.11); chips are not verified "
                     "either way, and Sisense's member and exclude matching is not verified to do the same. "
                     "Where a filtered column has values differing only by case, or NULLs under an exclude, "
                     f"compare with Sisense ({where})")}
