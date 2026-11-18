"""Each Model's Data Cache readiness, for the audit JSON (`corpus.models[].data_cache`)
and the report's Data Cache view.

ThoughtSpot's Data Cache cannot serve a Model with a custom calendar (P19), a SQL
pass-through formula (P20), a semantic query measure (P21), a source on neither
Snowflake nor Databricks (P23), a connection using OAuth, PrivateLink or a template
variable (P24), a parameterized Table (P25), a parameter in a formula (P26), a SQL View
(P27) or an RLS rule reaching beyond its Table's own columns (P28); a connection that
defines custom calendars is a warning (P22). The readiness is decided by the very rules that
report it: for each one that ran, the item passes the rule's own `requires` and
`where` (scopes.has_data, predicates.passes — what its `each` mode checks before it
fires), and the reasons list the rule's derived field. So the view and the findings
cannot disagree.

    readiness   blocked   a blocking rule fires (whatever else ran)
                unknown   no blocking rule fires, but one of them did not run (an
                          --angles without P) or could not judge the Model (P24 when
                          the connection search failed)
                warning   no blocking rule fires and all ran; P22 fires
                ready     no rule fires and every blocking rule ran
    reasons     [{rule, effect: "blocks" | "warns", label, items}]
    not_assessed  the rules that did not run, or could not judge this Model (P22 when
                the calendar search failed, P24 when the connection search did)
    calendars_in_use      each column that sets a calendar: {column, calendar, kind
                          ("code-based" | "custom"), set_on ("model" | "table")}
    connection_calendars  the custom calendars on the Model's connections:
                          [{connection, calendars}], or None when not fetched
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ts_cli.audit.engine import fields, predicates, scopes
from ts_cli.audit.engine.fields_data_cache import column_calendars, connection_calendars

#: The rules that decide readiness: (rule id, effect, how the view labels the reason).
CHECKS = (
    ("P19", "blocks", "Custom calendar"),
    ("P20", "blocks", "SQL pass-through"),
    ("P21", "blocks", "Semantic query Model"),
    ("P22", "warns", "Connection defines custom calendars"),
    ("P23", "blocks", "Source not Snowflake or Databricks"),
    ("P24", "blocks", "Connection uses OAuth, PrivateLink or a variable"),
    ("P25", "blocks", "Parameterized Table"),
    ("P26", "blocks", "Parameter in a formula"),
    ("P27", "blocks", "SQL View"),
    ("P28", "blocks", "RLS rule beyond its Table's columns"),
)
BLOCKING = tuple(rule for rule, effect, _ in CHECKS if effect == "blocks")


def _judged(rule: Any, item: dict, ctx: Any) -> bool:
    return all(scopes.has_data(item, ctx, req) for req in rule.requires)


def _reason(rule: Any, item: dict, ctx: Any) -> Optional[List[str]]:
    """The items the rule lists for `item` when its `where` passes, else None."""
    where = (rule.aggregate or {}).get("where")
    if not predicates.passes(where, item, ctx):
        return None
    field = where.get("field") if isinstance(where, dict) else None
    return [str(v) for v in (fields.get(item, field, ctx) or [])] if field else []


def model_data_cache(item: dict, ctx: Any, ran: Dict[str, Any]) -> dict:
    """`item` (a model scope item) judged by the rules in `ran` (id -> the catalog rule,
    the rules this run ran)."""
    reasons: List[dict] = []
    not_assessed: List[str] = []
    for rule_id, effect, label in CHECKS:
        rule = ran.get(rule_id)
        if rule is None or not _judged(rule, item, ctx):
            not_assessed.append(rule_id)
            continue
        items = _reason(rule, item, ctx)
        if items is not None:
            reasons.append({"rule": rule_id, "effect": effect, "label": label,
                            "items": items})
    if any(r["effect"] == "blocks" for r in reasons):
        readiness = "blocked"
    elif any(rule in not_assessed for rule in BLOCKING):
        readiness = "unknown"
    else:
        readiness = "warning" if reasons else "ready"
    doc = item.get("doc") or {}
    return {"readiness": readiness, "reasons": reasons, "not_assessed": not_assessed,
            "calendars_in_use": [dict(c) for c in column_calendars(doc, ctx)],
            "connection_calendars": connection_calendars(doc, ctx)}
