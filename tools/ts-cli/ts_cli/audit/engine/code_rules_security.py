"""S (Security) code rules. engine/code_rules.py imports this module at its end, so the
registry — and the catalog gate — see these rules wherever REGISTRY is read.

Same import constraint as code_rules.py: the catalog gate imports this module under a
plain python3 with no ts-cli dependencies, so import only pure modules at the top.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

from ts_cli.audit.engine import scopes
from ts_cli.audit.engine.code_rules import code_rule
from ts_cli.audit.engine.messages import render, template
from ts_cli.audit.findings import Finding
from ts_cli.tml_rls_graph import rls_join_cycles

if TYPE_CHECKING:
    from ts_cli.audit.catalog_model import Rule


def _table_of(ctx_tables: Dict[str, dict]):
    """A Model entry -> its Table TML `table:` body, through the entry's `fqn`. The audit
    keeps each Table TML as the whole parsed document (`{guid, table}`), keyed by guid;
    an entry whose Table TML is not in scope resolves to None."""
    def resolve(entry: dict):
        doc = (ctx_tables or {}).get(entry.get("fqn") or "")
        body = doc.get("table") if isinstance(doc, dict) else None
        return body if isinstance(body, dict) else None
    return resolve


@code_rule("rls_join_cycles", placeholders={"table", "join", "target", "back"},
           severity="severity_name", uses=(),
           label="one finding per RLS join that closes a loop with the Model's joins")
def rls_join_cycle_rule(rule: "Rule", ctx: Any, profile: str) -> List[Finding]:
    """S11 — the Model's join graph plus the joins its Tables' RLS rules use
    (ts_cli/tml_rls_graph.py): one finding per RLS join that closes a directed cycle."""
    out: List[Finding] = []
    for item in scopes.available(ctx, rule):
        model = item["obj"]
        notes: list = []
        for hit in rls_join_cycles(model.get("model_tables") or [], {},
                                   table_of=_table_of(ctx.tables), notes=notes):
            e, cycle = hit["rls_edge"], hit["cycle"]
            via = f" (Model joins: {', '.join(hit['model_joins'])})" if hit["model_joins"] else ""
            values = {"table": e.table, "join": e.join, "target": cycle[1],
                      "back": " -> ".join(cycle[1:]) + via}
            out.append(Finding(check_id=rule.id, angle="", severity=rule.severity,
                               object_type=item["object_type"], object_name=item["name"],
                               object_guid=item["guid"],
                               detail=render(template(rule, rule.severity), values)))
        ctx.warnings.extend(f"S11: {item['name']}: {n}" for n in notes)
    return out
