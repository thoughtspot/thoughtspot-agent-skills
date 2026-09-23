"""Predicates, thresholds and patterns shared by more than one audit angle.

The data and performance check sets were split by **copying**, not by extracting
(2026-09-22 audit, BL-304). Six rules existed twice:

===========================  ==================================================
Rule                         Where it was duplicated
===========================  ==================================================
join_progressive on a wide   ``check_d4`` / ``check_p4`` — byte-identical bodies
model                        apart from the id and the wording
Function call in an RLS      ``check_s9`` / ``check_p14`` — likewise
expression
String column in an RLS      ``check_s8`` / ``check_p15`` — s8 is p15 without
rule                         the ``value_casing`` guard
Join-graph depth             ``_join_depth`` / the inline copy in ``check_p7``
Fact-table detection         ``_table_role`` / the inline copy in ``check_p5``
Model column ceiling (75)    ``check_d1``'s threshold table / ``check_p8``
===========================  ==================================================

That is not a cosmetic problem. A threshold tuned in one angle silently left the
other on the old value, and `check_d2`/`check_p6` — the same shape — shipped with
the *same* two defects and had to be fixed twice in PR #528.

**Findings are still emitted per angle.** A wide un-progressive model genuinely is
both a modelling and a performance concern, and the report's angles are different
lenses on one environment. What is unified here is the *rule*, not the reporting:
both checks keep their id, severity and wording.
"""
from __future__ import annotations

import re

#: Warehouse types ThoughtSpot treats as strings. A string join or RLS key is
#: markedly slower than an integer one and is what several checks look for.
STRING_TYPES = ("VARCHAR", "CHAR", "STRING", "TEXT")

#: A model wider than this makes for a wider GROUP BY and heavier query plans.
#: `check_d1` grades against it as its "columns" yellow band; `check_p8` reports
#: crossing it outright. One number, two presentations.
MAX_MODEL_COLUMNS = 75

#: Above this many tables, `join_progressive: false` means every query joins all
#: of them. Shared by D4 and P4.
MIN_TABLES_FOR_JOIN_PROGRESSIVE = 5

#: A table with more than this many MEASURE columns is treated as a fact table.
FACT_MEASURE_THRESHOLD = 3

#: Join-graph depth bands, shared by D1's grading table and P7's severity split.
JOIN_DEPTH_GREEN = 3
JOIN_DEPTH_YELLOW = 5

#: A function call around an RLS operand. Defeats index/partition pruning, and
#: is a correctness smell besides. Was declared identically in two modules.
FUNC_IN_EXPR = re.compile(
    r"\b(UPPER|LOWER|TRIM|CAST|CONCAT|CONTAINS|IF)\s*\(", re.IGNORECASE)

#: A bracketed column reference inside a TML expression: ``[TABLE::COL]``.
BRACKET_REF = re.compile(r"\[([^\]]+)\]")


def join_depth(model_tables: list) -> int:
    """Longest join chain reachable from any table in the model.

    A DFS per start node, counting hops. Cycles terminate on the visited set.
    """
    graph: dict = {}
    for t in model_tables or []:
        tn = t.get("name", "")
        for j in (t.get("joins") or []):
            graph.setdefault(tn, []).append(j.get("with", ""))
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
                   if (c.get("properties") or {}).get("column_type") == "MEASURE")
    return "fact" if measures > FACT_MEASURE_THRESHOLD else "dimension"


def fact_tables(columns: list, model_tables: list) -> set:
    """Names of the model's tables that read as fact tables."""
    return {mt.get("name", "") for mt in (model_tables or [])
            if table_role(columns, mt.get("name", "")) == "fact"}


def is_wide_and_not_progressive(model: dict) -> bool:
    """A model with many tables and ``join_progressive`` off.

    Every query then joins all of them. Shared by D4 (modelling) and P4
    (performance); both report it, under their own id and wording.
    """
    tables = model.get("model_tables") or []
    progressive = (model.get("properties") or {}).get("join_progressive", False)
    return len(tables) > MIN_TABLES_FOR_JOIN_PROGRESSIVE and not progressive


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
            (c.get("db_column_properties") or {}).get("data_type", ""),
            (c.get("properties") or {}).get("value_casing", ""),
        )
    for rule in ((t.get("rls_rules") or {}).get("rules") or []):
        for ref in BRACKET_REF.findall(rule.get("expr", "")):
            col = ref.split("::")[-1] if "::" in ref else ref
            dt, vc = props.get(col, ("", ""))
            yield rule, col, dt, vc


def is_string_type(data_type: str) -> bool:
    """True for a warehouse string type. Empty (unknown) is not a string."""
    return (data_type or "").upper() in STRING_TYPES
