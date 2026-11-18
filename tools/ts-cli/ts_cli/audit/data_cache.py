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
cannot disagree. A rule can also run and still fail to read part of one Model
(UNJUDGED): it is then not assessed for that Model, whether or not it fires, never "no
problem". And P21 or P24 may rest only on readings the product team is to confirm
(TO_CONFIRM): its reason then "may block".

    readiness   blocked   a blocking rule fires on a firm reading (whatever else ran)
                unknown   no firm block, but a blocking rule did not run (an --angles
                          without P) or could not read part of the Model: P24 when the
                          connection search failed or a connection's settings could
                          not be read; P23 when a source's type is unknown; P19, P21,
                          P25 and P28 when a source Table's TML is missing. An unread
                          part outranks a reading to confirm, so it is never hidden
                confirm   no firm block and nothing unread, but a blocking rule fires on
                          readings to confirm only (P24's OAuth M2M or PrivateLink read
                          from the host; P21's measure only flagged pre-aggregated)
                warning   no blocking rule fires and all ran; P22 fires
                ready     no rule fires and every blocking rule ran
    reasons     [{rule, effect: "blocks" | "may block" | "warns", label, items}]
    not_assessed  the rules that did not run, or could not read all of this Model (P22
                when the calendar search failed, and the cases under unknown)
    calendars_in_use      each column that sets a calendar: {column, calendar, kind
                          ("code-based" | "custom"), set_on ("model" | "table")}
    connection_calendars  the custom calendars on the Model's connections:
                          [{connection, calendars}], or None when not fetched
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ts_cli.audit.engine import fields, predicates, scopes
from ts_cli.audit.engine.fields_data_cache import (column_calendars, connection_calendars,
                                                   missing_tables,
                                                   semantic_measures_to_confirm)
from ts_cli.audit.engine.fields_data_cache_sources import (connection_blockers_to_confirm,
                                                           unjudged_connections,
                                                           unjudged_rls, unjudged_sources)

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
#: Rules that can run and still not read all of one Model: rule -> (item, ctx) -> what
#: it could not read (empty when it read everything).
UNJUDGED = {"P19": missing_tables, "P21": missing_tables, "P23": unjudged_sources,
            "P24": unjudged_connections, "P25": missing_tables, "P28": unjudged_rls}
#: Rules whose reason may rest only on readings to confirm: rule -> (item, ctx) -> bool.
TO_CONFIRM = {"P21": semantic_measures_to_confirm, "P24": connection_blockers_to_confirm}


def _judged(rule: Any, item: dict, ctx: Any) -> bool:
    return all(scopes.has_data(item, ctx, req) for req in rule.requires)


def _reason(rule: Any, item: dict, ctx: Any) -> Optional[List[str]]:
    """The items the rule lists for `item` when its `where` passes, else None."""
    where = (rule.aggregate or {}).get("where")
    if not predicates.passes(where, item, ctx):
        return None
    field = where.get("field") if isinstance(where, dict) else None
    return [str(v) for v in (fields.get(item, field, ctx) or [])] if field else []


def _check(rule_id: str, effect: str, label: str, rule: Any, item: dict,
           ctx: Any) -> Tuple[Optional[dict], bool]:
    """One check for `item`: (its reason or None, whether it is not assessed). Not
    assessed when the rule did not run, its data is missing, or it could not read part
    of the Model (UNJUDGED) — the last even when it fires, so a reason never hides what
    was not read. The reason's effect is "may block" when it rests only on readings to
    confirm (TO_CONFIRM)."""
    if rule is None or not _judged(rule, item, ctx):
        return None, True
    unread = UNJUDGED.get(rule_id)
    unassessed = unread is not None and bool(unread(item, ctx))
    items = _reason(rule, item, ctx)
    if items is None:
        return None, unassessed
    to_confirm = TO_CONFIRM.get(rule_id)
    if effect == "blocks" and to_confirm is not None and to_confirm(item, ctx):
        effect = "may block"
    return {"rule": rule_id, "effect": effect, "label": label, "items": items}, unassessed


def _readiness(reasons: List[dict], not_assessed: List[str]) -> str:
    """The readiness the module docstring defines, from the reasons and the checks not
    made."""
    effects = {r["effect"] for r in reasons}
    if "blocks" in effects:
        return "blocked"
    if any(rule in not_assessed for rule in BLOCKING):
        return "unknown"
    if "may block" in effects:
        return "confirm"
    return "warning" if reasons else "ready"


def model_data_cache(item: dict, ctx: Any, ran: Dict[str, Any]) -> dict:
    """`item` (a model scope item) judged by the rules in `ran` (id -> the catalog rule,
    the rules this run ran)."""
    reasons: List[dict] = []
    not_assessed: List[str] = []
    for rule_id, effect, label in CHECKS:
        reason, unassessed = _check(rule_id, effect, label, ran.get(rule_id), item, ctx)
        if reason is not None:
            reasons.append(reason)
        if unassessed:
            not_assessed.append(rule_id)
    doc = item.get("doc") or {}
    return {"readiness": _readiness(reasons, not_assessed), "reasons": reasons,
            "not_assessed": not_assessed,
            "calendars_in_use": [dict(c) for c in column_calendars(doc, ctx)],
            "connection_calendars": connection_calendars(doc, ctx)}
