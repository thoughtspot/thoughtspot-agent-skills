"""Derived fields for Data Cache readiness: P19-P22 and the report's Data Cache view
(P23-P28's are in fields_data_cache_sources.py, on the helpers here).

ThoughtSpot's Data Cache cannot serve some Models. The product owner's rules
(2026-11-18), one field each:

    P19  @custom_calendar_columns       a column on a table-based custom calendar (blocks);
                                        to confirm: a formula naming a custom calendar,
                                        and a code-based value that a custom calendar on
                                        the connection is also named (open-items #18,
                                        BL-590); @custom_calendar_lead begins the message
    P20  @sql_passthrough_formulas      a formula calling a SQL pass-through function (blocks)
    P21  @semantic_query_measures       a measure aggregated AGGREGATE: a semantic query
                                        Model, uncached by design (blocks); a measure only
                                        flagged pre-aggregated is a reading to confirm
                                        (open-items #18), and @semantic_query_lead begins
                                        the message
    P22  @connection_custom_calendars   a connection of the Model's Tables with custom
                                        calendars registered: a user can pick one at run
                                        time, and that query is not cached (warns)

The report's per-Model readiness (audit/data_cache.py) reads these same fields, so the
Data Cache view and the findings cannot disagree. It also reads unread_sources (a source
whose TML the audit does not hold leaves P19, P21 and P28 not assessed for the Model,
since each reads it), missing_tables (the same for P25, SQL Views aside) and
unjudged_sql_views (P27).

Registered into the same registry as engine/fields.py, which imports this module at its
end. Same import constraint as fields.py: Python 3.9, no third-party imports at module
level.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ts_cli.audit.engine import tml
from ts_cli.audit.engine.fields import register
from ts_cli.audit.engine.memo import cached
from ts_cli.formula_common import close_paren, in_quotes, quoted_spans, split_top_level_args
from ts_cli.formula_translate.refs import REF_GRAMMAR, split_literals

#: `properties.calendar` values that name a code-based calendar, case and edge spaces
#: aside: the default (`calendar`, the spelling a 2026-07-30 census found on 34 Models,
#: and `default`, ThoughtSpot's published spelling) and the fiscal one. Any other value
#: names a table-based custom calendar (product owner, 2026-11-18). An absent, null or
#: blank value sets no calendar.
CODE_BASED_CALENDARS = ("calendar", "fiscal", "default")
CODE, CUSTOM = "code-based", "custom"
#: How a Data Cache message begins: a firm reading, or only readings the product team
#: is to confirm (open-items #18). P21 and P24 choose between them.
CANT_USE = "Can't use Data Cache"
MAY_NOT_USE = "May not be able to use Data Cache"


def calendar_kind(value: Any) -> Optional[str]:
    """CODE for a CODE_BASED_CALENDARS value, CUSTOM for any other, None for none (absent,
    null, or blank text). A non-string value (a YAML number) is read as its text."""
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    if not text:
        return None
    return CODE if text.casefold() in CODE_BASED_CALENDARS else CUSTOM


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _column_label(column: dict) -> str:
    """A Model column as a finding names it: its name, else its `column_id`."""
    return _text(column.get("name")) or _text(column.get("column_id")) or "?"


def _model_columns(doc: dict) -> List[dict]:
    cols = (doc.get("model") or {}).get("columns") if isinstance(doc, dict) else None
    return [c for c in (cols if isinstance(cols, list) else []) if isinstance(c, dict)]


def _table_column(column: dict, table_columns: dict) -> dict:
    """The Table column a Model column's `column_id` resolves to, or {} (a formula
    column, or a Table whose TML is not in scope)."""
    cid = column.get("column_id")
    found = table_columns.get(cid) if isinstance(cid, str) else None
    return found if isinstance(found, dict) else {}


# ── P19: calendars ──────────────────────────────────────────────────────────

def column_calendars(doc: dict, ctx: Any) -> List[Dict[str, str]]:
    """Each Model column that sets a calendar, in column order: `{"column", "calendar",
    "kind" (CODE or CUSTOM), "set_on" ("model" or "table")}`. The Model column's own
    `properties.calendar`; when it sets none, the Table column's its `column_id`
    resolves to (AuditContext.table_columns: the Model table's alias, else name, and the
    Table column's name). Cached per Model."""
    return cached("column_calendars", doc, _column_calendars, doc, ctx)


def _column_calendars(doc: dict, ctx: Any) -> List[Dict[str, str]]:
    table_columns = cached("table_columns", doc, ctx.table_columns, doc)
    out: List[Dict[str, str]] = []
    for col in _model_columns(doc):
        value, set_on = tml.mapping(col, "properties").get("calendar"), "model"
        if calendar_kind(value) is None:
            value = tml.mapping(_table_column(col, table_columns), "properties").get("calendar")
            set_on = "table"
        kind = calendar_kind(value)
        if kind is not None:
            out.append({"column": _column_label(col), "calendar": str(value).strip(),
                        "kind": kind, "set_on": set_on})
    return out


#: Date functions that take a calendar as an optional last argument, a bare keyword:
#: `fiscal`, or a custom calendar's name (thoughtspot-formula-patterns.md, Date
#: Functions; `start_of_week ( [d] , RetailCal )` live-probed 2026-10-07). The `diff_*`
#: functions take it third, after the two dates.
_CALENDAR_FUNCTIONS = frozenset({
    "year", "year_name", "quarter_number", "month", "month_number",
    "month_number_of_quarter", "day", "day_of_week", "day_number_of_week",
    "day_number_of_quarter", "day_number_of_year", "week_number_of_month",
    "week_number_of_quarter", "week_number_of_year", "is_weekend", "start_of_week",
    "start_of_month", "start_of_quarter", "start_of_year"})
_DIFF_CALENDAR_FUNCTIONS = frozenset({"diff_weeks", "diff_months", "diff_quarters",
                                      "diff_years"})
#: A function call outside quoted literals and references (fields_data_cache_sources
#: reads RLS rules with it too).
_CALL = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*\(")
_BARE_KEYWORD = re.compile(r"^[A-Za-z_]\w*$")
#: Bare words that are not a calendar: the formula language's literals.
_NOT_A_CALENDAR = frozenset({"true", "false", "null"})


def formula_calendar_arguments(expr: Any) -> List[str]:
    """Every calendar a formula passes to a date function, in order: the last argument
    of a _CALENDAR_FUNCTIONS call (of two or more) or a _DIFF_CALENDAR_FUNCTIONS call
    (of three or more) when it is a bare keyword other than `true`, `false` or `null`,
    code-based (`fiscal`) or not. Calls inside a quoted literal or a `[...]` reference
    are not read. Uses formula_common's paren and argument splitters, which keep quotes
    and references opaque."""
    if not isinstance(expr, str):
        return []
    spans = quoted_spans(expr)
    out: List[str] = []
    for m in _CALL.finditer(expr):
        name = m.group(1).lower()
        least = 3 if name in _DIFF_CALENDAR_FUNCTIONS else 2
        if (name not in _CALENDAR_FUNCTIONS and name not in _DIFF_CALENDAR_FUNCTIONS) \
                or in_quotes(m.start(), spans):
            continue
        close = close_paren(expr, m.end() - 1)
        args = split_top_level_args(expr[m.end():close]) if close > 0 else []
        last = args[-1] if len(args) >= least else ""
        if _BARE_KEYWORD.match(last) and last.casefold() not in _NOT_A_CALENDAR:
            out.append(last)
    return out


def formula_calendar_names(expr: Any) -> List[str]:
    """The custom calendars among formula_calendar_arguments: those not code-based."""
    return [a for a in formula_calendar_arguments(expr) if calendar_kind(a) == CUSTOM]


def formula_calendars(doc: dict) -> List[Dict[str, str]]:
    """Each calendar a Model formula names (formula_calendar_arguments), in formula
    order: `{"column" (the formula's name, else id), "calendar", "kind" (CODE or
    CUSTOM), "set_on": "formula"}`, the shape column_calendars gives."""
    formulas = (doc.get("model") or {}).get("formulas") if isinstance(doc, dict) else None
    out: List[Dict[str, str]] = []
    for f in (formulas if isinstance(formulas, list) else []):
        if not isinstance(f, dict):
            continue
        label = _text(f.get("name")) or _text(f.get("id")) or "?"
        out += [{"column": label, "calendar": name, "kind": calendar_kind(name) or CUSTOM,
                 "set_on": "formula"}
                for name in formula_calendar_arguments(f.get("expr"))]
    return out


#: calendars_in_use's kind for a code-based value a custom calendar is also named.
UNCLEAR = "unclear"


def calendars_in_use(doc: dict, ctx: Any) -> List[Dict[str, str]]:
    """Every calendar the Model uses, each a fresh mapping, in one pass: column_calendars
    then formula_calendars. A code-based value that a custom calendar registered on one
    of the Model's connections is also named (connection_calendars, any case) reads
    UNCLEAR: which one it means is open (open-items #18 point 9). With the calendars not
    fetched, no value is UNCLEAR."""
    registered = {n.strip().casefold() for c in (connection_calendars(doc, ctx) or [])
                  for n in c["calendars"]}
    out = []
    for c in column_calendars(doc, ctx) + formula_calendars(doc):
        c = dict(c)
        if c["kind"] == CODE and c["calendar"].strip().casefold() in registered:
            c["kind"] = UNCLEAR
        out.append(c)
    return out


def custom_calendar_readings(item: dict, ctx: Any) -> List[Tuple[str, bool]]:
    """Model: (item, to_confirm) for each P19 reading, in calendars_in_use order: a
    column on a custom calendar (firm); a code-based value a custom calendar is also
    named (UNCLEAR), and a formula naming a custom calendar (both to confirm)."""
    out = []
    for c in calendars_in_use(item.get("doc") or {}, ctx):
        in_formula = c["set_on"] == "formula"
        where = f"{c['column']}: calendar {c['calendar']} in a formula" if in_formula \
            else f"{c['column']}: {c['calendar']}"
        if c["kind"] == UNCLEAR:
            out.append((f"{where}, also a custom calendar's name on its connection "
                        "(to confirm)", True))
        elif c["kind"] == CUSTOM and in_formula:
            out.append((f"{where} (to confirm)", True))
        elif c["kind"] == CUSTOM:
            out.append((f"{c['column']} ({c['calendar']})", False))
    return out


@register("custom_calendar_columns", uses={"calendars"},
          label="the columns or formulas on a custom calendar")
def _custom_calendar_columns(item: dict, ctx: Any) -> Any:
    """Model: each custom_calendar_readings item, in order; empty when none."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    return NameList(text for text, _ in custom_calendar_readings(item, ctx))


def custom_calendars_to_confirm(item: dict, ctx: Any) -> bool:
    """Model: P19 lists something, and every reading it lists is one to confirm."""
    found = [to_confirm for _, to_confirm in custom_calendar_readings(item, ctx)]
    return bool(found) and all(found)


@register("custom_calendar_lead", uses={"calendars"}, values=(CANT_USE, MAY_NOT_USE),
          label="whether the Model can't use Data Cache or may not, pending review")
def _custom_calendar_lead(item: dict, ctx: Any) -> str:
    """Model: how P19's message begins: MAY_NOT_USE when every reading is one to
    confirm (custom_calendars_to_confirm), else CANT_USE."""
    return MAY_NOT_USE if custom_calendars_to_confirm(item, ctx) else CANT_USE


# ── P20: SQL pass-through ───────────────────────────────────────────────────

#: A SQL pass-through call, scalar (`sql_string_op`, `sql_int_op`, `sql_double_op`,
#: `sql_bool_op`, `sql_date_op`, ...) or aggregate (`sql_int_aggregate_op`, ...).
_SQL_PASSTHROUGH = re.compile(r"\bsql_[a-z0-9_]+_op\s*\(", re.IGNORECASE)
_REF = re.compile(REF_GRAMMAR)


def calls_sql_passthrough(expr: Any) -> bool:
    """`expr` calls a SQL pass-through function outside quoted literals and `[...]`
    references (formula_translate.refs: a quote inside a reference opens no literal).
    False for a non-string."""
    if not isinstance(expr, str):
        return False
    code = " ".join(seg for literal, seg in split_literals(expr) if not literal)
    return bool(_SQL_PASSTHROUGH.search(_REF.sub(" ", code)))


@register("sql_passthrough_formulas", uses=(),
          label="the formulas calling a SQL pass-through function")
def _sql_passthrough_formulas(item: dict, ctx: Any) -> Any:
    """Model: the name (else id) of each formula whose `expr` calls a SQL pass-through
    function (calls_sql_passthrough), in formula order; empty when none."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    formulas = (item.get("obj") or {}).get("formulas")
    return NameList(_text(f.get("name")) or _text(f.get("id")) or "?"
                    for f in (formulas if isinstance(formulas, list) else [])
                    if isinstance(f, dict) and calls_sql_passthrough(f.get("expr")))


# ── P21: semantic query Model ───────────────────────────────────────────────

def _is_aggregate(properties: dict) -> bool:
    value = properties.get("aggregation")
    return isinstance(value, str) and value.strip().upper() == "AGGREGATE"


#: semantic_measure_kind's values.
AGGREGATED, PRE_AGGREGATED = "aggregate", "pre-aggregated"


def semantic_measure_kind(column: dict, table_column: dict) -> Optional[str]:
    """Whether the source platform aggregates a Model column. AGGREGATED (firm) when its
    own `properties.aggregation` is AGGREGATE (any case) or the Table column it surfaces
    has `aggregation: AGGREGATE`; else PRE_AGGREGATED when that Table column has
    `is_pre_aggregated_measure: true` (the YAML boolean only, as tml_lint's I23 reads
    it), a reading the product team is to confirm stops Data Cache (open-items #18,
    point 6); else None."""
    own = tml.mapping(column, "properties")
    table = tml.mapping(table_column, "properties")
    if _is_aggregate(own) or _is_aggregate(table):
        return AGGREGATED
    return PRE_AGGREGATED if table.get("is_pre_aggregated_measure") is True else None


def is_semantic_measure(column: dict, table_column: dict) -> bool:
    """semantic_measure_kind names a kind for the column."""
    return semantic_measure_kind(column, table_column) is not None


def semantic_measures(item: dict, ctx: Any) -> List[Tuple[str, str]]:
    """Model: (column name, semantic_measure_kind) for each column it names, in column
    order."""
    doc = item.get("doc") or {}
    table_columns = cached("table_columns", doc, ctx.table_columns, doc)
    out = []
    for c in _model_columns(doc):
        kind = semantic_measure_kind(c, _table_column(c, table_columns))
        if kind is not None:
            out.append((_column_label(c), kind))
    return out


@register("semantic_query_measures", uses=(),
          label="the measures the source platform aggregates")
def _semantic_query_measures(item: dict, ctx: Any) -> Any:
    """Model: each column semantic_measures lists, a PRE_AGGREGATED one as "<name>
    (pre-aggregated, to confirm)"; empty when none."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    return NameList(name if kind == AGGREGATED else f"{name} (pre-aggregated, to confirm)"
                    for name, kind in semantic_measures(item, ctx))


def semantic_measures_to_confirm(item: dict, ctx: Any) -> bool:
    """Model: P21 lists a measure, and every one it lists is PRE_AGGREGATED, a reading
    to confirm. The readiness then reads "confirm", not "blocked"."""
    kinds = [kind for _, kind in semantic_measures(item, ctx)]
    return bool(kinds) and all(k == PRE_AGGREGATED for k in kinds)


@register("semantic_query_lead", uses=(), values=(CANT_USE, MAY_NOT_USE),
          label="whether the Model can't use Data Cache or may not, pending review")
def _semantic_query_lead(item: dict, ctx: Any) -> str:
    """Model: how P21's message begins. MAY_NOT_USE when every measure it lists is a
    reading to confirm (semantic_measures_to_confirm), else CANT_USE."""
    return MAY_NOT_USE if semantic_measures_to_confirm(item, ctx) else CANT_USE


# ── P22: connections defining custom calendars ──────────────────────────────

def model_sources(doc: dict, ctx: Any) -> List[Dict[str, Any]]:
    """The Model's sources, each `model_tables` fqn once, in order: `{"name", "fqn",
    "table", "header"}` — its Table TML body (`ctx.tables` by fqn; None for a SQL View,
    whose TML the audit does not keep, or a Table whose export failed) and its metadata
    header ({} when none). An entry with no fqn is a source the audit cannot read: it is
    listed with fqn, Table TML and header all empty, so the rules count it as unread
    rather than skip it. Cached per Model."""
    return cached("model_sources", doc, _model_sources, doc, ctx)


def _model_sources(doc: dict, ctx: Any) -> List[Dict[str, Any]]:
    headers = cached("headers_by_id", ctx, _headers_by_id, ctx)
    mts = (doc.get("model") or {}).get("model_tables") if isinstance(doc, dict) else None
    out: List[Dict[str, Any]] = []
    seen = set()
    for mt in (mts if isinstance(mts, list) else []):
        if not isinstance(mt, dict):
            continue
        fqn = mt.get("fqn") if isinstance(mt.get("fqn"), str) and mt.get("fqn") else None
        if fqn is not None and fqn in seen:
            continue
        seen.add(fqn)
        out.append(_source(mt, fqn, ctx, headers))
    return out


def _source(mt: dict, fqn: Optional[str], ctx: Any, headers: dict) -> Dict[str, Any]:
    """One model_sources entry; an entry with no fqn has no Table TML and no header."""
    found = (ctx.tables or {}).get(fqn) if fqn else None
    body = found.get("table") if isinstance(found, dict) else None
    return {"name": _text(mt.get("name")) or _text(mt.get("alias")) or fqn or "?",
            "fqn": fqn, "table": body if isinstance(body, dict) else None,
            "header": (headers.get(fqn) or {}) if fqn else {}}


def source_connection(source: Dict[str, Any]) -> Optional[Dict[str, Optional[str]]]:
    """The connection a source (model_sources) is on: `{"name", "id"}`, or None when
    neither is known. The name is the Table TML's `table.connection.name` (a Falcon or
    system Table has no connection block, and so no connection), else its metadata
    header's `dataSourceName` (a SQL View, a Table whose export failed, or a connection
    block naming no connection). The id is the header's `dataSourceId` when it carries
    one (none of 93 headers on the SE demo cluster did, 2026-11-18: the name carries
    the match; used only when present)."""
    header = source["header"]
    name = tml.mapping(source["table"], "connection").get("name") \
        if source["table"] is not None else None
    if not (isinstance(name, str) and name):
        name = header.get("dataSourceName")
    name = name if isinstance(name, str) and name else None
    cid = header.get("dataSourceId") if isinstance(header.get("dataSourceId"), str) else None
    return {"name": name, "id": cid} if (name or cid) else None


def connection_unread(source: Dict[str, Any]) -> bool:
    """A source whose connection the audit cannot name (source_connection is None)
    though it has one: anything but a Table whose TML has no connection block (a
    Falcon or system Table, which P23 reports as having none)."""
    if source["table"] is not None and not tml.mapping(source["table"], "connection"):
        return False
    return source_connection(source) is None


def is_sql_view(source: Dict[str, Any]) -> bool:
    return str(source["header"].get("type") or "").strip().upper() == "SQL_VIEW"


def unread_sources(item: dict, ctx: Any) -> List[str]:
    """Model: the sources whose TML the audit does not hold: a Table whose export
    failed, a SQL View (the audit keeps no SQL View TML), a View, or a `model_tables`
    entry with no fqn. Their columns may set a calendar (P19) or be pre-aggregated
    (P21), and they may carry RLS rules (P28), so the readiness counts each of those as
    not assessed while any is listed, and the calendars column names them."""
    return [s["name"] for s in model_sources(item.get("doc") or {}, ctx)
            if s["table"] is None]


def missing_tables(item: dict, ctx: Any) -> List[str]:
    """Model: unread_sources but a SQL View, which has no database, schema or table name
    of its own: what P25 could not read."""
    return [s["name"] for s in model_sources(item.get("doc") or {}, ctx)
            if s["table"] is None and not is_sql_view(s)]


def unjudged_sql_views(item: dict, ctx: Any) -> List[str]:
    """Model: the sources P27 cannot tell from a SQL View: no Table TML, and no header
    type (the header search skipped it, or the entry has no fqn)."""
    return [s["name"] for s in model_sources(item.get("doc") or {}, ctx)
            if s["table"] is None and not str(s["header"].get("type") or "").strip()]


def model_connections(doc: dict, ctx: Any) -> List[Dict[str, Optional[str]]]:
    """The connections the Model's sources are on (source_connection), each once in
    source order."""
    out: List[Dict[str, Optional[str]]] = []
    seen = set()
    for source in model_sources(doc, ctx):
        conn = source_connection(source)
        key = conn and ((conn["name"] or "").strip().casefold(), conn["id"])
        if conn and key not in seen:
            seen.add(key)
            out.append(conn)
    return out


def _headers_by_id(ctx: Any) -> dict:
    """Metadata header by object id; a header without a `type` takes its row's
    `metadata_subtype` (how `metadata/search` may report a LOGICAL_TABLE's subtype)."""
    out = {}
    for entry in ctx.metadata or []:
        header = (entry.get("metadata_header") or entry) if isinstance(entry, dict) else {}
        if isinstance(header, dict) and isinstance(header.get("id"), str):
            if not header.get("type") and isinstance(entry.get("metadata_subtype"), str):
                header = dict(header, type=entry["metadata_subtype"])
            out.setdefault(header["id"], header)
    return out


def connection_matches(conn: Dict[str, Optional[str]], name: Any, cid: Any) -> bool:
    """Whether a calendar's or connection entry's (`name`, `cid`) is `conn`
    (model_connections): the same id, or the same name, case and edge spaces aside."""
    wanted = (conn["name"] or "").strip().casefold()
    return bool((conn["id"] and cid == conn["id"])
                or (wanted and _text(name).strip().casefold() == wanted))


def connection_facts_for(conn: Dict[str, Optional[str]], connections: Any) -> List[dict]:
    """The entries of `connections` (`ctx.connections`: connection_facts) that are
    `conn`'s (connection_matches); none when the connections were not fetched."""
    return [f for f in (connections if isinstance(connections, list) else [])
            if isinstance(f, dict) and connection_matches(conn, f.get("name"), f.get("id"))]


def connection_calendars(doc: dict, ctx: Any) -> Optional[List[Dict[str, Any]]]:
    """For each connection of the Model (model_connections) with a registered custom
    calendar: `{"connection", "calendars"}` (calendar names, sorted). A calendar is the
    connection's when its `connection_id` is the connection's id or its
    `connection_name` its name, case and edge spaces aside. None when the calendars were
    not fetched or the fetch failed (`ctx.calendars` None): unknown, never "none"."""
    calendars = ctx.calendars
    if calendars is None:
        return None
    out = []
    for conn in model_connections(doc, ctx):
        names = sorted({_text(c.get("calendar_name")) or _text(c.get("calendar_id"))
                        for c in calendars if isinstance(c, dict) and connection_matches(
                            conn, c.get("connection_name"), c.get("connection_id"))})
        if names:
            out.append({"connection": conn["name"] or conn["id"], "calendars": names})
    return out


@register("connection_custom_calendars", uses={"calendars"},
          label="the connections that define custom calendars")
def _connection_custom_calendars(item: dict, ctx: Any) -> Any:
    """Model: "<connection> (<n> custom calendar(s))" for each connection_calendars
    entry; empty when none, or when the calendars were not fetched (a rule that must
    skip that Model requires `calendars`)."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    found = connection_calendars(item.get("doc") or {}, ctx) or []
    return NameList(f"{c['connection']} ({len(c['calendars'])} custom calendar"
                    f"{'' if len(c['calendars']) == 1 else 's'})" for c in found)
