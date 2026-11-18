"""Derived fields for Data Cache readiness: P19-P22 and the report's Data Cache view
(P23-P28's are in fields_data_cache_sources.py, on the helpers here).

ThoughtSpot's Data Cache cannot serve some Models. The product owner's rules
(2026-11-18), one field each:

    P19  @custom_calendar_columns       a column on a table-based custom calendar (blocks)
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
Data Cache view and the findings cannot disagree. It also reads missing_tables: a source
Table whose TML is not in the context (its export failed) leaves P19, P21, P25 and P28
not assessed for the Model, since each reads that Table.

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


@register("custom_calendar_columns", uses=(),
          label="the columns on a custom calendar")
def _custom_calendar_columns(item: dict, ctx: Any) -> Any:
    """Model: "<column> (<calendar>)" for each column on a custom calendar
    (column_calendars), in column order; empty when none."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    doc = item.get("doc") or {}
    return NameList(f"{c['column']} ({c['calendar']})" for c in column_calendars(doc, ctx)
                    if c["kind"] == CUSTOM)


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
    header ({} when none). Cached per Model."""
    return cached("model_sources", doc, _model_sources, doc, ctx)


def _model_sources(doc: dict, ctx: Any) -> List[Dict[str, Any]]:
    headers = cached("headers_by_id", ctx, _headers_by_id, ctx)
    mts = (doc.get("model") or {}).get("model_tables") if isinstance(doc, dict) else None
    out: List[Dict[str, Any]] = []
    seen = set()
    for mt in (mts if isinstance(mts, list) else []):
        fqn = mt.get("fqn") if isinstance(mt, dict) else None
        if not isinstance(fqn, str) or not fqn or fqn in seen:
            continue
        seen.add(fqn)
        found = (ctx.tables or {}).get(fqn)
        body = found.get("table") if isinstance(found, dict) else None
        out.append({"name": _text(mt.get("name")) or _text(mt.get("alias")) or fqn,
                    "fqn": fqn, "table": body if isinstance(body, dict) else None,
                    "header": headers.get(fqn) or {}})
    return out


def source_connection(source: Dict[str, Any]) -> Optional[Dict[str, Optional[str]]]:
    """The connection a source (model_sources) is on: `{"name", "id"}`, or None when
    neither is known. The name is the Table TML's `table.connection.name` (a Falcon or
    system Table has no connection block, and so no connection); for a source with no
    Table TML (a SQL View), its metadata header's `dataSourceName`. The id is the
    header's `dataSourceId` when it carries one (none of 93 headers on the SE demo
    cluster did, 2026-11-18: the name carries the match; used only when present)."""
    header = source["header"]
    if source["table"] is not None:
        name = tml.mapping(source["table"], "connection").get("name")
    else:
        name = header.get("dataSourceName")
    name = name if isinstance(name, str) and name else None
    cid = header.get("dataSourceId") if isinstance(header.get("dataSourceId"), str) else None
    return {"name": name, "id": cid} if (name or cid) else None


def missing_tables(item: dict, ctx: Any) -> List[str]:
    """Model: the sources whose Table TML is not in the context (its export failed, or
    it is not a Table the audit keeps), a SQL View aside: the audit keeps no SQL View
    TML by design, and P27 reports it. P19 (a Table column's calendar), P21 (a Table
    column's flags), P25 (a Table's names) and P28 (a Table's RLS rules) read the
    Table, so the readiness counts each as not assessed while any is listed."""
    return [s["name"] for s in model_sources(item.get("doc") or {}, ctx)
            if s["table"] is None
            and str(s["header"].get("type") or "").strip().upper() != "SQL_VIEW"]


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
