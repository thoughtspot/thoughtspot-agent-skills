"""Each Model table's role, from join direction, refined by the measures it holds.

The one classifier the audit, the ERD and the future remodel tool share (audit v2
roadmap PR 4.1; design: docs/superpowers/specs/2026-11-01-audit-table-roles-design.md).
A fact sits at the root of the joins, on the many side; a dimension is joined to, on the
one side. Measures refine the role and never decide it:

    fact                      a root (nothing joins to it) holding a measure, or the only
                              table in the Model when it holds one
    factless                  a root holding no measure: a bridge or a factless fact
    dimension                 joined to, holding no measure
    dimension_with_measures   joined to, holding a measure (an order header's freight)

Flags: `outrigger` (only dimensions join to it: an outrigger or a snowflaked hierarchy,
which direction cannot tell apart), `attribute_heavy` (a fact with more descriptive
columns than measures), `unjoined` (in no directed join in a Model of two or more
tables).

A join reads many-side -> one-side. Its cardinality is its own, else what
`join_cardinality(model_table, join)` resolves (a referencing join's Table-level
definition), else none. MANY_TO_ONE or none: the declaring table is the many side;
ONE_TO_MANY reverses it; ONE_TO_ONE and MANY_TO_MANY give no direction.

Pure and standard-library only: the audit loads this file by path. Malformed TML is
skipped, never raised (BL-501).
"""
from typing import Callable, Dict, Optional

ROLE_LABELS = {
    "fact": "Fact",
    "factless": "Factless / bridge",
    "dimension": "Dimension",
    "dimension_with_measures": "Dimension holding measures",
}
ATTRIBUTE_HEAVY_LABEL = "Fact with descriptive attributes"

_UNDIRECTED = ("ONE_TO_ONE", "MANY_TO_MANY")


def erd_kind(role: str) -> str:
    """The ERD renderer's two-valued `kind`: roots are drawn as facts."""
    return "fact" if role in ("fact", "factless") else "dim"


def _key(mt: dict) -> Optional[str]:
    k = mt.get("alias") or mt.get("name")
    return k if isinstance(k, str) and k else None


def _column_counts(columns) -> Dict[str, list]:
    """{table key: [measures, attributes]} from the Model's physical columns."""
    out: Dict[str, list] = {}
    for c in columns if isinstance(columns, list) else []:
        if not isinstance(c, dict) or not isinstance(c.get("column_id"), str):
            continue
        table, sep, _ = c["column_id"].partition("::")
        if not sep:
            continue
        props = c.get("properties")
        kind = props.get("column_type") if isinstance(props, dict) else None
        out.setdefault(table, [0, 0])[0 if kind == "MEASURE" else 1] += 1
    return out


def _edges(tables: Dict[str, dict], join_cardinality) -> list:
    """Directed (many, one) pairs between the Model's own tables."""
    edges = []
    for key, mt in tables.items():
        for join in mt.get("joins") or [] if isinstance(mt.get("joins"), list) else []:
            if not isinstance(join, dict) or join.get("with") not in tables:
                continue
            card = join.get("cardinality") or (
                join_cardinality(mt, join) if join_cardinality else None) or "MANY_TO_ONE"
            card = str(card).upper()
            if card in _UNDIRECTED:
                continue
            other = join["with"]
            edges.append((other, key) if card == "ONE_TO_MANY" else (key, other))
    return edges


def _model_tables(model: dict) -> Dict[str, dict]:
    mts = model.get("model_tables")
    tables: Dict[str, dict] = {}
    for mt in mts if isinstance(mts, list) else []:
        key = _key(mt) if isinstance(mt, dict) else None
        if key and key not in tables:
            tables[key] = mt
    return tables


def _role(joined_to: bool, measures: int, linked: bool, several: bool) -> str:
    if joined_to:
        return "dimension_with_measures" if measures else "dimension"
    if measures:
        return "fact"
    return "factless" if several and linked else "dimension"


def table_roles(model: dict,
                join_cardinality: Optional[Callable[[dict, dict], Optional[str]]] = None
                ) -> Dict[str, dict]:
    """`{table key: {role, outrigger, attribute_heavy, unjoined, measures, attributes}}`
    for a Model TML body (the dict under `model:`), keyed by alias, else name."""
    if not isinstance(model, dict):
        return {}
    tables = _model_tables(model)
    counts = _column_counts(model.get("columns"))
    edges = _edges(tables, join_cardinality)
    users = {k: {m for m, o in edges if o == k} for k in tables}
    linked = {k for edge in edges for k in edge}
    several = len(tables) > 1
    out = {}
    for key in tables:
        measures, attributes = counts.get(key, [0, 0])
        role = _role(bool(users[key]), measures, key in linked, several)
        out[key] = {
            "role": role,
            "outrigger": bool(users[key]) and all(users[u] for u in users[key]),
            "attribute_heavy": role == "fact" and attributes > measures,
            "unjoined": several and key not in linked,
            "measures": measures,
            "attributes": attributes,
        }
    return out
