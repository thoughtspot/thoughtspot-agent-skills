"""Derived fields for Data Cache readiness, P23-P28: what a Model is built on.

ThoughtSpot's Data Cache cannot serve a Model with any of these (product owner,
2026-11-18), one field each:

    P23  @non_cloud_sources           a source on neither Snowflake nor Databricks, or a
                                      Table with no connection (Falcon, system)
    P24  @connection_cache_blockers   a connection using OAuth, PrivateLink or a template
                                      variable (read off `ctx.connections`, which holds
                                      derived facts only: audit/connection_facts.py)
    P25  @parameterized_tables        a Table whose database, schema or table name is a
                                      template variable
    P26  @parameter_formula_names     a formula reading a Model parameter (A9's field,
                                      engine/fields.py: one reading for both)
    P27  @sql_view_sources            a SQL View among its sources
    P28  @rls_rules_beyond_own_table  an RLS rule reaching another table's column or a
                                      join, calling a formula function, or calling a SQL
                                      pass-through

The sources come from fields_data_cache.model_sources: each `model_tables` fqn's Table
TML and metadata header. The audit keeps no SQL View TML, so a SQL View is seen by its
header, which `build_context` fetches for every Model source. The report's readiness
(audit/data_cache.py) reads these same fields.

Registered into the same registry as engine/fields.py, which imports this module at its
end. Same import constraint as fields.py: Python 3.9, no third-party imports at module
level.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from ts_cli.audit.engine import tml
from ts_cli.audit.engine.fields import register
from ts_cli.audit.engine.fields_data import _code, _own_table_and_paths, _rls_rules_of
from ts_cli.audit.engine.fields_data_cache import (calls_sql_passthrough, connection_matches,
                                                   model_connections, model_sources)
from ts_cli.formula_translate.refs import REF_GRAMMAR
from ts_cli.publish_plan import parse_variable_token
from ts_cli.tml_rls_graph import _referenced_path_ids

# ── P23: sources on neither Snowflake nor Databricks ────────────────────────

#: The metadata header `dataSourceType` values Data Cache serves, any case.
#: RDBMS_SNOWFLAKE is live (73 of 92 headers on the SE demo cluster, 2026-11-18);
#: RDBMS_DATABRICKS follows the `RDBMS_<TYPE>` pattern and is not yet seen (open-items #17).
CACHEABLE_SOURCE_TYPES = ("RDBMS_SNOWFLAKE", "RDBMS_DATABRICKS")


def source_type_problem(source: Dict[str, Any]) -> str:
    """Why a source (model_sources) is on neither Snowflake nor Databricks — "no
    connection" for a Table whose TML has no connection block, else its header's
    `dataSourceType` when that is another type — or "" when it is not known to be."""
    table = source["table"]
    if table is not None and not tml.mapping(table, "connection"):
        return "no connection"
    kind = source["header"].get("dataSourceType")
    if isinstance(kind, str) and kind.strip() \
            and kind.strip().upper() not in CACHEABLE_SOURCE_TYPES:
        return kind.strip()
    return ""


@register("non_cloud_sources", uses=(),
          label="the tables on a source other than Snowflake or Databricks")
def _non_cloud_sources(item: dict, ctx: Any) -> Any:
    """Model: "<source> (<why>)" for each source source_type_problem names; a source
    with no header type and a connection is unknown and not listed."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    out = NameList()
    for source in model_sources(item.get("doc") or {}, ctx):
        why = source_type_problem(source)
        if why:
            out.append(f"{source['name']} ({why})")
    return out


# ── P24: connections using OAuth, PrivateLink or a template variable ────────

#: connection_facts flag -> how a finding names it.
_CONNECTION_FLAGS = (("oauth", "OAuth"), ("privatelink", "PrivateLink"),
                     ("parameterized", "template variable"))


@register("connection_cache_blockers", uses={"connections"},
          label="the connections using OAuth, PrivateLink or a template variable")
def _connection_cache_blockers(item: dict, ctx: Any) -> Any:
    """Model: "<connection> (<what>)" for each of its connections (model_connections)
    whose facts in `ctx.connections` (matched by name, any case, or id) say OAuth,
    PrivateLink or a template variable; a flag that is unknown (None) is not one. Empty
    when the connections were not fetched (a rule that must skip requires them)."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    facts = [f for f in (ctx.connections or []) if isinstance(f, dict)]
    out = NameList()
    for conn in model_connections(item.get("doc") or {}, ctx):
        mine = [f for f in facts if connection_matches(conn, f.get("name"), f.get("id"))]
        found = [_flag_label(key, label, mine) for key, label in _CONNECTION_FLAGS
                 if any(f.get(key) is True for f in mine)]
        if found:
            out.append(f"{conn['name'] or conn['id']} ({', '.join(found)})")
    return out


def _flag_label(key: str, label: str, facts: list) -> str:
    """How a finding names one flag; the two inferred readings say they are for the
    team to confirm (open-items #18): OAuth read only from a client_id/client_secret
    pair (Databricks OAuth M2M), and PrivateLink read from the host."""
    if key == "oauth" and all(f.get("oauth_m2m") is True for f in facts if f.get("oauth") is True):
        return "OAuth M2M, to confirm"
    if key == "privatelink":
        return "PrivateLink read from the host, to confirm"
    return label


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


def rls_rule_problems(rule: dict, own: Any, paths: Dict[str, dict]) -> List[str]:
    """What takes an RLS rule beyond its own Table's columns, in a fixed order: "a
    join" (a referenced `table_paths` entry with a `join_path`), "another table's
    column" (one whose `table` is not the owning Table, any case), "a formula" (a
    function call other than `ts_var`), "a SQL pass-through" (fields_data_cache's
    matcher). Read outside quoted literals; a path id the rule's `table_paths` does not
    define is not judged."""
    expr = rule.get("expr")
    code = _code(expr)
    found = set()
    for pid in _referenced_path_ids([{"expr": code}]):
        path = paths.get(pid)
        if not isinstance(path, dict):
            continue
        if path.get("join_path"):
            found.add("a join")
        table = path.get("table")
        if isinstance(table, str) and isinstance(own, str) \
                and table.strip().casefold() != own.strip().casefold():
            found.add("another table's column")
    calls = {m.group(1).lower() for m in _CALL.finditer(_REF.sub(" ", code))}
    if any(c not in _NOT_FORMULA and not _PASSTHROUGH_NAME.match(c) for c in calls):
        found.add("a formula")
    if calls_sql_passthrough(expr):
        found.add("a SQL pass-through")
    order = ("a join", "another table's column", "a formula", "a SQL pass-through")
    return [p for p in order if p in found]


def _paths_by_id(table_doc: Any) -> Dict[str, dict]:
    t = table_doc.get("table") if isinstance(table_doc, dict) else None
    rls = t.get("rls_rules") if isinstance(t, dict) else None
    paths = rls.get("table_paths") if isinstance(rls, dict) else None
    return {p["id"].strip(): p for p in (paths if isinstance(paths, list) else [])
            if isinstance(p, dict) and isinstance(p.get("id"), str)}


@register("rls_rules_beyond_own_table", uses=(),
          label="the RLS rules reaching beyond their Table's own columns")
def _rls_rules_beyond_own_table(item: dict, ctx: Any) -> Any:
    """Model: "<source>: <rule> (<what>)" for each RLS rule on a source's Table TML that
    rls_rule_problems names something for; a rule comparing only its own Table's
    columns with ts_ variables is not listed."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    out = NameList()
    for source in model_sources(item.get("doc") or {}, ctx):
        doc = (ctx.tables or {}).get(source["fqn"])
        own, _ = _own_table_and_paths(doc)
        paths = _paths_by_id(doc)
        for rule in _rls_rules_of(doc):
            problems = rls_rule_problems(rule, own, paths)
            if problems:
                name = rule.get("name") if isinstance(rule.get("name"), str) else "?"
                out.append(f"{source['name']}: {name} ({', '.join(problems)})")
    return out
