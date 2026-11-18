"""Derived fields for Data Cache readiness, P23-P28: what a Model is built on.

ThoughtSpot's Data Cache cannot serve a Model with any of these (product owner,
2026-11-18), one field each:

    P23  @non_cloud_sources           a source on neither Snowflake nor Databricks (its
                                      connection's type, else its header's), or a Table
                                      with no connection (Falcon, system)
    P24  @connection_cache_blockers   a connection using OAuth, PrivateLink or a template
                                      variable (read off `ctx.connections`, which holds
                                      derived facts only: audit/connection_facts.py);
                                      @connection_cache_lead begins its message
    P25  @parameterized_tables        a Table whose database, schema or table name is a
                                      template variable
    P26  @parameter_formula_names     a formula reading a Model parameter (A9's field,
                                      engine/fields.py: one reading for both)
    P27  @sql_view_sources            a SQL View among its sources
    P28  @rls_rules_beyond_own_table  an RLS rule reaching another table's column or a
                                      join, calling a formula function (a null test named
                                      apart: S12 advises one), or calling a SQL
                                      pass-through; none for a Model bypassing RLS

The sources come from fields_data_cache.model_sources: each `model_tables` fqn's Table
TML and metadata header. The audit keeps no SQL View TML, so a SQL View is seen by its
header, which `build_context` fetches for every Model source. The report's readiness
(audit/data_cache.py) reads these same fields, and two helpers that are not rule
fields: what P23 and P24 could not read for a Model (unjudged_sources,
unjudged_connections), which leaves it not assessed rather than ready, and whether all
P24 reads is to confirm (connection_blockers_to_confirm).

Registered into the same registry as engine/fields.py, which imports this module at its
end. Same import constraint as fields.py: Python 3.9, no third-party imports at module
level.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ts_cli.audit.engine import tml
from ts_cli.audit.engine.fields import register
from ts_cli.audit.engine.fields_data import _code, _own_table_and_paths, _rls_rules_of
from ts_cli.audit.engine.fields_data_cache import (CANT_USE, MAY_NOT_USE, calls_sql_passthrough,
                                                   connection_facts_for, connection_unread,
                                                   model_connections, model_sources,
                                                   source_connection, unread_sources)
from ts_cli.formula_translate.refs import REF_GRAMMAR
from ts_cli.publish_plan import parse_variable_token
from ts_cli.tml_rls_graph import _referenced_path_ids, _segment_joins

# ── P23: sources on neither Snowflake nor Databricks ────────────────────────

#: The warehouse types Data Cache serves, read without an `RDBMS_` prefix, case and edge
#: spaces aside: a connection's type in `ctx.connections` (its `data_warehouse_type`;
#: SNOWFLAKE and DATABRICKS both seen live), else a source header's `dataSourceType`
#: (RDBMS_SNOWFLAKE and RDBMS_DATABRICKS both seen live; SE demo cluster, 2026-11-18,
#: ts-audit open-items #17).
CACHEABLE_WAREHOUSES = ("SNOWFLAKE", "DATABRICKS")


def _warehouse(kind: Any) -> Optional[str]:
    """A warehouse type as compared: upper case, edge spaces and an `RDBMS_` prefix
    dropped; None for anything blank or not text."""
    if not isinstance(kind, str) or not kind.strip():
        return None
    text = kind.strip().upper()
    return text[len("RDBMS_"):] if text.startswith("RDBMS_") else text


def source_type_problem(source: Dict[str, Any], connections: Any = None) -> Optional[str]:
    """Why a source (model_sources) is on neither Snowflake nor Databricks; "" when it is
    on one of them; None when its type is unknown, so P23 cannot judge it.

    "no connection" for a Table whose TML has no connection block (a Falcon or system
    Table). Otherwise the type is that of the source's connection (source_connection)
    in `connections` (`ctx.connections`, matched as P24 matches them), else the source
    header's `dataSourceType`; a type Data Cache does not serve is the problem, as
    written."""
    table = source["table"]
    if table is not None and not tml.mapping(table, "connection"):
        return "no connection"
    conn = source_connection(source)
    kinds = [f.get("type") for f in connection_facts_for(conn, connections)] if conn else []
    kinds = [k.strip() for k in kinds if _warehouse(k)]
    if not kinds:
        header = source["header"].get("dataSourceType")
        kinds = [header.strip()] if _warehouse(header) else []
    if not kinds:
        return None
    other = [k for k in kinds if _warehouse(k) not in CACHEABLE_WAREHOUSES]
    return other[0] if other else ""


@register("non_cloud_sources", uses={"connections"},
          label="the tables on a source other than Snowflake or Databricks")
def _non_cloud_sources(item: dict, ctx: Any) -> Any:
    """Model: "<source> (<why>)" for each source source_type_problem names; a source
    whose type is unknown is not listed (unjudged_sources lists it)."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    out = NameList()
    for source in model_sources(item.get("doc") or {}, ctx):
        why = source_type_problem(source, ctx.connections)
        if why:
            out.append(f"{source['name']} ({why})")
    return out


def unjudged_sources(item: dict, ctx: Any) -> List[str]:
    """Model: the sources whose type P23 cannot read (source_type_problem is None).
    The readiness (audit/data_cache.py) counts P23 as not assessed for a Model it does
    not fire on while any is listed."""
    return [s["name"] for s in model_sources(item.get("doc") or {}, ctx)
            if source_type_problem(s, ctx.connections) is None]


# ── P24: connections using OAuth, PrivateLink or a template variable ────────

#: The readings P24 makes of a connection.
_CONNECTION_FLAGS = ("oauth", "privatelink", "parameterized")
#: The connection_facts keys each reading rests on: a template variable is a `${var}`
#: token in the settings or the metadata header's flag (the search shows a
#: parameterized connection without its tokens, ts-audit open-items #17).
_FLAG_FACTS = {"oauth": ("oauth",), "privatelink": ("privatelink",),
               "parameterized": ("parameterized", "parameterized_connection")}


def connection_readings(item: dict, ctx: Any) -> List[Dict[str, Any]]:
    """Model: what P24 reads of each of its connections (model_connections), in order:
    `{"connection", "found": [(label, to_confirm)], "unknown"}`. Its facts in
    `ctx.connections` are matched by name (any case) or id. `found` holds each flag
    that is True on a matching entry (_flag_reading); `unknown` is True when no entry
    matches or a matching entry leaves a flag unknown (None)."""
    out: List[Dict[str, Any]] = []
    for conn in model_connections(item.get("doc") or {}, ctx):
        mine = connection_facts_for(conn, ctx.connections)
        found = [_flag_reading(key, mine) for key in _CONNECTION_FLAGS
                 if any(f.get(k) is True for f in mine for k in _FLAG_FACTS[key])]
        unknown = not mine or any(f.get(k) is None for f in mine
                                  for key in _CONNECTION_FLAGS for k in _FLAG_FACTS[key])
        out.append({"connection": conn["name"] or conn["id"], "found": found,
                    "unknown": unknown})
    return out


def _flag_reading(key: str, facts: list) -> Tuple[str, bool]:
    """How a finding names one flag, and whether it is a reading the team is to confirm
    (open-items #18): OAuth read only from a client_id/client_secret pair (Databricks
    OAuth M2M), and PrivateLink read from the host. A template variable, and OAuth read
    from a setting named for it, are firm."""
    if key == "oauth":
        m2m = all(f.get("oauth_m2m") is True for f in facts if f.get("oauth") is True)
        return ("OAuth M2M", True) if m2m else ("OAuth", False)
    if key == "privatelink":
        return "PrivateLink read from the host", True
    return "template variable", False


@register("connection_cache_blockers", uses={"connections"},
          label="the connections using OAuth, PrivateLink or a template variable")
def _connection_cache_blockers(item: dict, ctx: Any) -> Any:
    """Model: "<connection>: <reading>; <reading>" for each connection_readings entry
    with a flag found, a reading to confirm followed by "(to confirm)" so the qualifier
    attaches to it alone. Empty when none, and when the connections were not fetched (a
    rule that must skip requires them)."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    return NameList(
        f"{r['connection']}: " + "; ".join(label + (" (to confirm)" if to_confirm else "")
                                          for label, to_confirm in r["found"])
        for r in connection_readings(item, ctx) if r["found"])


def connection_blockers_to_confirm(item: dict, ctx: Any) -> bool:
    """Model: P24 lists a connection, and every reading it lists is one the team is to
    confirm (_flag_reading). The readiness then reads "confirm", not "blocked"."""
    found = [to_confirm for r in connection_readings(item, ctx) for _, to_confirm in r["found"]]
    return bool(found) and all(found)


@register("connection_cache_lead", uses={"connections"}, values=(CANT_USE, MAY_NOT_USE),
          label="whether the Model can't use Data Cache or may not, pending review")
def _connection_cache_lead(item: dict, ctx: Any) -> str:
    """Model: how P24's message begins. MAY_NOT_USE when every reading P24 lists is one
    to confirm (connection_blockers_to_confirm), else CANT_USE."""
    return MAY_NOT_USE if connection_blockers_to_confirm(item, ctx) else CANT_USE


def unjudged_connections(item: dict, ctx: Any) -> List[str]:
    """Model: what P24 cannot read, when the connections were fetched: the connections
    whose settings or header are unknown (connection_readings' `unknown`), and the
    sources whose connection cannot be named at all (connection_unread: no Table TML
    and no header, or a connection block and a header naming none). The readiness counts
    P24 as not assessed for the Model while any is listed."""
    if ctx.connections is None:
        return []
    return [r["connection"] for r in connection_readings(item, ctx) if r["unknown"]] + \
        [s["name"] for s in model_sources(item.get("doc") or {}, ctx) if connection_unread(s)]


# ── P25: Tables named by a template variable ────────────────────────────────

#: Table TML key -> how a finding names it.
_TABLE_FIELDS = (("db", "database"), ("schema", "schema"), ("db_table", "table name"))


@register("parameterized_tables", uses=(),
          label="the tables whose database, schema or table name is a template variable")
def _parameterized_tables(item: dict, ctx: Any) -> Any:
    """Model: "<source> (<fields>)" for each source whose Table TML `db`, `schema` or
    `db_table` is wholly a `${var}` token (publish_plan.parse_variable_token, as
    parameterization writes it); a partial token is a fixed name."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    out = NameList()
    for source in model_sources(item.get("doc") or {}, ctx):
        table = source["table"] or {}
        fields = [label for key, label in _TABLE_FIELDS
                  if parse_variable_token(table.get(key)) is not None]
        if fields:
            out.append(f"{source['name']} ({', '.join(fields)})")
    return out


# ── P27: SQL Views ──────────────────────────────────────────────────────────

@register("sql_view_sources", uses=(),
          label="the SQL Views the Model uses")
def _sql_view_sources(item: dict, ctx: Any) -> Any:
    """Model: each source whose metadata header type (or row subtype) is SQL_VIEW, any
    case. The audit keeps no SQL View TML, so the header is what says so."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    return NameList(s["name"] for s in model_sources(item.get("doc") or {}, ctx)
                    if str(s["header"].get("type") or "").strip().upper() == "SQL_VIEW")


# ── P28: RLS rules reaching beyond their Table's own columns ────────────────

_REF = re.compile(REF_GRAMMAR)
#: A function call outside quoted literals and references.
_CALL = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*\(")
#: Words before `(` that are not a formula function: the session-variable accessor, which
#: a plain rule uses, and the operators.
_NOT_FORMULA = frozenset({"ts_var", "in", "not", "and", "or"})
_PASSTHROUGH_NAME = re.compile(r"(?i)^sql_\w+_op$")
#: A null-test call, in the spellings S12 and S15 read as a call (`isnull`, `is_null`;
#: fields_data._ISNULL_CALL).
_NULL_TEST_NAME = re.compile(r"(?i)^is_?null$")
#: The other null test S12 and S15 accept, `[X] = null` (not `!=`, `<=` or `>=`).
_EQUALS_NULL = re.compile(r"(?i)(?<![!<>=])=\s*null\b")
#: How P28 names a null test: the call S12 advises so an outer join keeps its unmatched
#: rows, which stops Data Cache all the same (product owner, 2026-11-18).
NULL_TEST = "a null test that keeps outer-join rows, see S12"
#: How P28 names an `= null` test: whether that form stops Data Cache is for the product
#: team to confirm (open-items #18, point 4).
NULL_TEST_TO_CONFIRM = NULL_TEST + " (to confirm)"
#: P28's readings that rest on an open product question.
_RLS_TO_CONFIRM = frozenset({NULL_TEST_TO_CONFIRM})


def rls_rule_problems(rule: dict, own: Any, paths: Dict[str, dict]) -> List[str]:
    """What takes an RLS rule beyond its own Table's columns, in a fixed order: "a
    join" (a referenced `table_paths` entry whose `join_path` names a join, as
    tml_rls_graph walks it), "another table's column" (one whose `table` is not the
    owning Table, any case), "a formula" (a function call other than `ts_var` or a null
    test), NULL_TEST (an `isnull` / `is_null` call), NULL_TEST_TO_CONFIRM (an `= null`
    test), "a SQL pass-through" (fields_data_cache's matcher). Read outside quoted
    literals; a path id the rule's `table_paths` does not define is not judged."""
    expr = rule.get("expr")
    code = _code(expr)
    found = _path_problems(code, own, paths) | _call_problems(code)
    if _EQUALS_NULL.search(_REF.sub(" ", code)):
        found.add(NULL_TEST_TO_CONFIRM)
    if calls_sql_passthrough(expr):
        found.add("a SQL pass-through")
    order = ("a join", "another table's column", "a formula", NULL_TEST,
             NULL_TEST_TO_CONFIRM, "a SQL pass-through")
    return [p for p in order if p in found]


def _path_problems(code: str, own: Any, paths: Dict[str, dict]) -> set:
    """"a join" and "another table's column", from the `table_paths` entries `code`
    references."""
    found = set()
    for pid in _referenced_path_ids([{"expr": code}]):
        path = paths.get(pid)
        if not isinstance(path, dict):
            continue
        if any(isinstance(name, str) and name.strip() for name in _segment_joins(path)):
            found.add("a join")
        table = path.get("table")
        if isinstance(table, str) and isinstance(own, str) \
                and table.strip().casefold() != own.strip().casefold():
            found.add("another table's column")
    return found


def _call_problems(code: str) -> set:
    """"a formula" and NULL_TEST, from the function calls in `code` outside `[...]`
    references (not `ts_var`, an operator or a SQL pass-through)."""
    calls = {m.group(1).lower() for m in _CALL.finditer(_REF.sub(" ", code))}
    functions = {c for c in calls if c not in _NOT_FORMULA and not _PASSTHROUGH_NAME.match(c)}
    found = set()
    if any(not _NULL_TEST_NAME.match(c) for c in functions):
        found.add("a formula")
    if any(_NULL_TEST_NAME.match(c) for c in functions):
        found.add(NULL_TEST)
    return found


def unjudged_rls(item: dict, ctx: Any) -> List[str]:
    """Model: the sources whose RLS rules P28 cannot read (unread_sources); none for a
    Model bypassing RLS, which applies no rule wherever it is defined."""
    if tml.mapping(item.get("obj") or {}, "properties").get("is_bypass_rls"):
        return []
    return unread_sources(item, ctx)


def _paths_by_id(table_doc: Any) -> Dict[str, dict]:
    t = table_doc.get("table") if isinstance(table_doc, dict) else None
    rls = t.get("rls_rules") if isinstance(t, dict) else None
    paths = rls.get("table_paths") if isinstance(rls, dict) else None
    return {p["id"].strip(): p for p in (paths if isinstance(paths, list) else [])
            if isinstance(p, dict) and isinstance(p.get("id"), str)}


def rls_readings(item: dict, ctx: Any) -> List[Tuple[str, str, List[str]]]:
    """Model: (source, rule name, rls_rule_problems) for each RLS rule on a source's
    Table TML that the problems name something for, in order; none for a Model
    bypassing RLS (`properties.is_bypass_rls`, read as S17 reads it): it applies no
    rule."""
    if tml.mapping(item.get("obj") or {}, "properties").get("is_bypass_rls"):
        return []
    out = []
    for source in model_sources(item.get("doc") or {}, ctx):
        doc = (ctx.tables or {}).get(source["fqn"]) if source["fqn"] else None
        own, _ = _own_table_and_paths(doc)
        paths = _paths_by_id(doc)
        for rule in _rls_rules_of(doc):
            problems = rls_rule_problems(rule, own, paths)
            if problems:
                name = rule.get("name") if isinstance(rule.get("name"), str) else "?"
                out.append((source["name"], name, problems))
    return out


@register("rls_rules_beyond_own_table", uses=(),
          label="the RLS rules reaching beyond their Table's own columns")
def _rls_rules_beyond_own_table(item: dict, ctx: Any) -> Any:
    """Model: "<source>: <rule> (<what>)" for each rls_readings entry; a rule comparing
    only its own Table's columns with ts_ variables is not listed. Empty for a Model
    bypassing RLS."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    return NameList(f"{source}: {name} ({', '.join(problems)})"
                    for source, name, problems in rls_readings(item, ctx))


def rls_rules_to_confirm(item: dict, ctx: Any) -> bool:
    """Model: P28 lists a rule, and every reading it lists rests on an open product
    question (an `= null` test). The readiness then reads "confirm", not "blocked"."""
    found = [p for _, _, problems in rls_readings(item, ctx) for p in problems]
    return bool(found) and all(p in _RLS_TO_CONFIRM for p in found)


@register("rls_rules_lead", uses=(), values=(CANT_USE, MAY_NOT_USE),
          label="whether the Model can't use Data Cache or may not, pending review")
def _rls_rules_lead(item: dict, ctx: Any) -> str:
    """Model: how P28's message begins. MAY_NOT_USE when every reading it lists is one
    to confirm (rls_rules_to_confirm), else CANT_USE."""
    return MAY_NOT_USE if rls_rules_to_confirm(item, ctx) else CANT_USE
