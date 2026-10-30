"""Model and Table TML helpers the rules share — joins, table keys and roles, RLS
column references, indexing, string types — and the constants they grade by.

Moved here from `ts_cli/audit/rules.py` when the legacy check functions were deleted
(the rule catalog change): every name left is read by a derived field (fields.py,
fields_data.py), a scope (scopes.py) or a code rule (code_rules.py). The helpers only
the deleted checks used (`is_wide_and_not_progressive`, `FUNC_IN_EXPR`,
`MIN_TABLES_FOR_JOIN_PROGRESSIVE`) went with them: D4/P4 and P14/S9 now carry that
logic as catalog data, and `test_checks_registry.py` holds each such pair together.

Why one module (BL-304, 2026-09-22 audit): the data and performance check sets were
split by **copying**, and six rules existed twice — join_progressive on a wide model
(D4/P4), a function call in an RLS expression (S9/P14), a string column in an RLS rule
(S8/P15), join-graph depth (D1/P7), fact-table detection (D11/P5) and the 75-column
ceiling (D1/P8). A threshold tuned in one angle silently left the other on the old
value, and D2/P6 shipped the *same* two defects and had to be fixed twice in PR #528.

**Findings are still emitted per angle.** A wide un-progressive model genuinely is
both a modelling and a performance concern; what is shared is the rule, not the
reporting — each rule keeps its id, severity and wording.

Kept importable on Python 3.9 with no third-party imports: the catalog gate loads the
engine modules that import it.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ts_cli.tml_join_graph import node_id

#: Warehouse types ThoughtSpot treats as strings. A string join or RLS key is
#: markedly slower than an integer one and is what several checks look for.
STRING_TYPES = ("VARCHAR", "CHAR", "STRING", "TEXT")

#: A table with more than this many MEASURE columns is treated as a fact table.
FACT_MEASURE_THRESHOLD = 3

#: A bracketed column reference inside a TML expression: ``[TABLE::COL]``.
BRACKET_REF = re.compile(r"\[([^\]]+)\]")

#: Keys the Model and Table TML schemas define as mappings, never lists
#: (thoughtspot-model-tml.md, thoughtspot-table-tml.md). A list or scalar under one is
#: malformed: a field path reads it as absent (fields._step) and the run warns
#: (malformed_mappings), rather than mapping over the list and judging what it finds
#: there (BL-406 item 10).
MAPPING_KEYS = frozenset({"properties", "spotter_config", "db_column_properties"})


def mapping(obj: Any, key: str) -> dict:
    """`obj[key]` when it is a mapping, else {}: the one reader for a MAPPING_KEYS key,
    so a malformed (list or scalar) value reads as absent rather than raising."""
    value = obj.get(key) if isinstance(obj, dict) else None
    return value if isinstance(value, dict) else {}


def malformed_mappings(doc: Any, path: str = "") -> list:
    """Dotted paths in `doc` where a MAPPING_KEYS key holds something other than a
    mapping (absent and null excepted), in document order. A list entry is named by its
    `name` when it has one (`columns[Amount].properties`), else by its index."""
    out: list = []
    if isinstance(doc, dict):
        for key, value in doc.items():
            here = f"{path}.{key}" if path else str(key)
            if key in MAPPING_KEYS and value is not None and not isinstance(value, dict):
                out.append(here)
            else:
                out += malformed_mappings(value, here)
    elif isinstance(doc, list):
        for i, value in enumerate(doc):
            name = value.get("name") if isinstance(value, dict) else None
            out += malformed_mappings(value, f"{path}[{name}]" if name else f"{path}.{i}")
    return out


def join_count(model_tables: list) -> int:
    """Joins declared across the model's tables (each lives under its ``model_tables[]``
    entry; Model TML has no Model-level ``joins``)."""
    return sum(len(t.get("joins") or []) for t in model_tables or [])


def join_depth(model_tables: list) -> int:
    """Longest join chain reachable from any table in the model.

    A DFS per start node, counting hops. Cycles terminate on the visited set. Each
    table is a node by its key (alias, else name) and a join's ``with`` resolves to the
    table it names (``join_target_key``); until 2026-10 nodes were keyed by ``name`` while
    ``with`` carries aliases, so a chain of aliased tables read as depth 1.
    """
    tables = model_tables or []
    graph: dict = {}
    for t in tables:
        tn = table_key(t)
        for j in (t.get("joins") or []):
            graph.setdefault(tn, []).append(join_target_key(tables, j.get("with", "")))
    if not graph:
        return 0
    max_d = 0
    for start in graph:
        visited: set = set()
        stack = [(start, 0)]
        while stack:
            node, depth = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            max_d = max(max_d, depth)
            for nb in graph.get(node, []):
                stack.append((nb, depth + 1))
    return max_d


def table_key(model_table: dict) -> str:
    """The prefix this model table's ``column_id`` values carry.

    The model schema: ``column_id`` is ``TABLE_NAME::col``, where TABLE_NAME is
    *"the `name:` (or `alias:`) from model_tables"*. Several checks keyed on
    ``name`` alone, so a role-playing dimension — the whole reason an alias
    exists — resolved to no columns: D10 called a fully-populated table a
    zero-column leaf, D6 and D11 silently saw "unknown" (BL-305).
    """
    return model_table.get("alias") or model_table.get("name") or ""


def join_target(model_tables: list, ref: Any) -> Optional[dict]:
    """The model_tables entry a join's ``with`` names: the entry whose node identity
    (``tml_join_graph.node_id``) it is — exactly, else ignoring case, as
    ``tml_join_graph.JoinGraph.resolve`` resolves it — else, for a ``with`` written as a
    physical name, the entry with that ``name``. None when nothing matches."""
    if not isinstance(ref, str) or not ref:
        return None
    entries = [t for t in (model_tables or []) if isinstance(t, dict)]
    for key in (node_id, lambda t: t.get("name")):
        for fold in (lambda s: s, str.lower):
            want = fold(ref)
            for t in entries:
                k = key(t)
                if isinstance(k, str) and k and fold(k) == want:
                    return t
    return None


def joined_keys(model_tables: list) -> set:
    """Every table on either side of a join, by key (alias, else name): each table that
    declares a join, and each table a join's ``with`` names (``join_target_key``). The
    one definition D5, D10 and H3 share (H3 kept its own copy until 2026-10, and drifted)."""
    tables = model_tables or []
    joined: set = set()
    for t in tables:
        for j in (t.get("joins") or []):
            joined.add(table_key(t))
            joined.add(join_target_key(tables, j.get("with", "")))
    return joined


def join_target_key(model_tables: list, ref: Any) -> Any:
    """The column-prefix key (``table_key``) of the table a join's ``with`` names, or
    ``ref`` itself when it names no model table."""
    target = join_target(model_tables, ref)
    return table_key(target) if target is not None else ref


def model_joins(model: dict, tables: dict):
    """Yield every join of a model, inline or referencing, in one shape.

    A ``model_tables[].joins[]`` entry comes in two forms::

        inline       {with, on, type, cardinality}     condition in the model
        referencing  {with, referencing_join[, type]}  condition in the TABLE

    For a referencing join the definition lives in the source Table TML's
    ``joins_with[]``, keyed by the name ``referencing_join`` holds, and carries
    ``{name, destination: {name, fqn}, on, type}``.

    D2/D3/D11/P6 read only ``joins[].on``, so a referencing join looked like a
    join with no keys and no type — and that is the dominant shape in practice.
    Live-verified 2026-09-23: **0 of 6** joins in a real "Retail Sales - RLS"
    model carried an inline ``on``, and one of them was a VARCHAR join key the
    audit reported as zero (BL-306).

    The model's own ``type`` wins where it sets one: observed live overriding a
    table that says ``INNER`` with ``LEFT_OUTER``.

    ``on`` comes back empty when the referenced table is not in scope. That is
    *unknown*, not *no keys*, and a caller must not read it as clean.
    """
    for mt in (model.get("model_tables") or []):
        by_name = _joins_with_index(mt, tables)
        for j in (mt.get("joins") or []):
            yield _resolve_join(mt, j, by_name)


def _joins_with_index(model_table: dict, tables: dict) -> dict:
    """``joins_with[]`` of this model table's source Table TML, keyed by name."""
    table = (tables or {}).get(model_table.get("fqn", "")) or {}
    return {j.get("name", ""): j
            for j in (table.get("table", {}).get("joins_with") or [])}


def _resolve_join(model_table: dict, join: dict, by_name: dict) -> dict:
    """One join in the common shape, inline or referencing."""
    ref = join.get("referencing_join", "")
    base = by_name.get(ref, {}) if ref else {}
    dest = base.get("destination") or {}
    return {
        "model_table": model_table,
        "name": join.get("name") or ref or join_label(model_table, join),
        "on": join.get("on") or base.get("on", ""),
        # The model overrides the table's type where it declares one.
        "type": join.get("type") or base.get("type", ""),
        "with": join.get("with") or dest.get("name", ""),
        # The model's own cardinality wins, as its type does; exported Table TML
        # rarely carries one (0 of 165 joins_with entries, 2026-07-30 census).
        "cardinality": join.get("cardinality") or base.get("cardinality", ""),
    }


def join_label(model_table: dict, join: dict) -> str:
    """A name for a join, which real TML does not give one.

    ``model_tables[].joins[]`` carries no ``name`` key — none of the 493 joins in
    the 2026-07-30 census has one — so every join finding was reported with an
    empty ``object_name`` and could not be identified in the report. Prefers a
    declared name if some future export grows one.
    """
    declared = join.get("name", "")
    if declared:
        return declared
    left = table_key(model_table)
    right = join.get("with", "")
    return f"{left} -> {right}" if left and right else (left or right)


def table_role(columns: list, table_name: str) -> str:
    """``"fact"``, ``"dimension"`` or ``"unknown"`` for one model table.

    Keyed on the ``column_id`` prefix. Note that prefix is the model_tables
    ``alias`` when one is set, and several callers pass ``name`` — BL-305.
    """
    table_cols = [c for c in (columns or [])
                  if (c.get("column_id") or "").split("::")[0] == table_name]
    if not table_cols:
        return "unknown"
    measures = sum(1 for c in table_cols
                   if mapping(c, "properties").get("column_type") == "MEASURE")
    return "fact" if measures > FACT_MEASURE_THRESHOLD else "dimension"


def fact_tables(columns: list, model_tables: list) -> set:
    """Names of the model's tables that read as fact tables."""
    return {mt.get("name", "") for mt in (model_tables or [])
            if table_role(columns, mt.get("name", "")) == "fact"}


def rls_column_refs(table: dict):
    """Yield ``(rule, column_name, data_type, value_casing)`` per RLS column ref.

    The column's type and casing come from the **Table** TML's own ``columns[]``,
    which is where ``db_column_properties`` lives. An unresolvable reference
    yields ``""`` for both, and a caller must not read that as "not a string" —
    it means unknown. Shared by S8 and P15, which differ only in whether they
    require ``value_casing`` to be absent.
    """
    t = table.get("table", {})
    props = {}
    for c in (t.get("columns") or []):
        props[c.get("name", "")] = (
            mapping(c, "db_column_properties").get("data_type", ""),
            mapping(c, "properties").get("value_casing", ""),
        )
    for rule in ((t.get("rls_rules") or {}).get("rules") or []):
        for ref in BRACKET_REF.findall(rule.get("expr", "")):
            col = ref.split("::")[-1] if "::" in ref else ref
            dt, vc = props.get(col, ("", ""))
            yield rule, col, dt, vc


#: `index_type` suppresses indexing; every other documented value selects a
#: strategy, and omitting the key means full indexing.
NOT_INDEXED = "DONT_INDEX"


def is_indexed(column: dict) -> bool:
    """Whether a model column is text-search indexed.

    The schema is explicit: *"`DONT_INDEX` suppresses text-search indexing …
    Omit for full indexing (default)"*, with `DEFAULT`, `PREFIX_ONLY`,
    `PREFIX_AND_SUBSTRING` and `PREFIX_AND_WORD_SUBSTRING` all selecting a
    strategy rather than disabling one.

    S2, P9 and P11 each tested *presence* of the key instead (BL-299), which
    inverts both halves: a column indexed by default — the commonest shape in
    exported TML, and the risk those checks exist to report — was invisible,
    while a column deliberately tuned to `DONT_INDEX` was reported as indexed.
    `DONT_INDEX` is also the only value this repo ever writes, so every
    converter-produced model turned S2 into a pure false-positive generator.
    """
    idx = mapping(column, "properties").get("index_type", "")
    return (idx or "").upper() != NOT_INDEXED


def is_string_type(data_type: str) -> bool:
    """True for a warehouse string type. Empty (unknown) is not a string."""
    return (data_type or "").upper() in STRING_TYPES
