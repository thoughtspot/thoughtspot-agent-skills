"""Logical-relationship ("noodle") join extraction from a Tableau datasource.

Split out of `twb.py` (module-per-concern, BL-069 pattern) to keep that file's
line count in budget, the same reason `joins.py` holds the physical
`<relation join=...>` path. Re-exported from `ts_cli.tableau.twb`, so the import
path is unchanged. `_extract_noodle_joins` returns `(joins, warnings)`; it used
to return `joins` alone.

Imports nothing from `twb.py`, deliberately: `twb.py` imports this module, and
the reverse would be a cycle.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Optional

# `[<col> (<Table Name>)]` once the brackets are stripped.
_REF_WITH_TABLE = re.compile(r"^(.*?)\s*\((.+)\)\s*$")
# One function call around a single bracketed reference: `INT([ORDER_ID])`.
_WRAPPED_REF = re.compile(r"^([A-Za-z_]\w*)\s*\(\s*(\[.*\])\s*\)$")


def _detail_id_count(view: dict) -> int:
    """Count detail-grain id columns (`*_id` / `* id`) in a view's output.

    The MANY side of a join has finer grain — it carries more identifier columns
    (e.g. driver-events has fleet_account_id AND driver_id; the account-level KI
    breakdown has only fleet_account_id). Robust where GROUP-BY arity isn't (pivot
    CTEs group positionally). The join key counts too, but the finer table has strictly
    more, so the comparison still orders them correctly."""
    n = 0
    for c in view.get("columns", []):
        name = (c.get("sql_output_column") or c.get("name") or "").lower().strip()
        if re.search(r"(^|[ _])id$", name):
            n += 1
    return n


def _relationship_operand(op: str) -> tuple[str, Optional[str], Optional[str]]:
    """Split a relationship operand into ``(column, table, wrapper)``.

    The operand is ``[<col> (<Table Name>)]``, or bare ``[<col>]`` when the
    column's name was not disambiguated, so the text does not say its table
    (table is None; BL-278). Tableau can also wrap the reference in one function
    call, ``INT([<col> (<Table Name>)])``; the wrapper is unwrapped and returned
    so the caller can report it. Reading the wrapped text as a reference made
    `INT` the column and the inner reference the table, which invented a join
    between two tables that do not exist. ``]]`` is Tableau's escaped ``]``.

    Anything else (an expression, a literal, nested calls) is not a reference:
    table is None, and the caller skips the relationship with a warning.
    """
    s = (op or "").strip()
    wrapper = None
    m = _WRAPPED_REF.match(s)
    if m:
        wrapper, s = m.group(1), m.group(2)
    if not (s.startswith("[") and s.endswith("]")):
        return s, None, wrapper
    inner = s[1:-1]
    if "[" in inner or "]" in inner.replace("]]", ""):  # several references
        return s, None, wrapper
    m = _REF_WITH_TABLE.match(inner)
    if not m:
        return inner, None, wrapper
    return m.group(1).strip(), m.group(2).strip(), wrapper


def _extract_noodle_joins(
    ds: ET.Element, sql_views: list[dict], tables: Optional[list[dict]] = None,
) -> tuple[list[dict], list[str]]:
    """Extract logical-relationship ("noodle") joins from `<relationships>`.

    Modern Tableau stores joins as logical relationships in
    `<object-graph>/<relationships>`, NOT as physical `<relation join=...>`. Each
    `<relationship>/<expression op="=">` holds two column refs of the form
    `[<col> (<Table Name>)]`; the parenthesised suffix identifies each side's table.

    Tableau defers cardinality to query time, so it is (almost always) absent from the
    file. We infer the MANY side from CTE grain — the table whose Custom SQL has more
    terms in its final `GROUP BY` is finer-grained (MANY). This is a heuristic; a
    post-build double-count check is the proof (see reference-tableau-model-discovery-algorithm).

    A relationship whose side names a table that is neither one of the
    datasource's ``tables`` nor one of its ``sql_views`` is dropped and reported:
    a published datasource flattened to one ``sqlproxy`` table still carries the
    relationships between its server-side logical tables, and no model table
    exists to join. With no ``tables`` and no ``sql_views`` to check against,
    nothing is dropped. A relationship whose table cannot be read from either
    operand is skipped with a warning (BL-278). A key wrapped in a function is
    joined on the bare column, with a warning that the join may match different
    rows than the source.
    """
    grain = {v.get("name"): _detail_id_count(v) for v in sql_views}
    known = {t.get("name") for t in (tables or [])} | {v.get("name") for v in sql_views}
    known.discard(None)

    joins: list[dict] = []
    warnings: list[str] = []
    for rel in ds.findall(".//relationships/relationship"):
        join, warning = _relationship_join(rel, known, grain)
        if warning:
            warnings.append(warning)
        if join:
            joins.append(join)
    return joins, warnings


def _skip_reason(lop: str, ltab: Optional[str], rop: str, rtab: Optional[str],
                 known: set) -> Optional[str]:
    """Why a relationship emits no join, or None when it joins two known tables."""
    unknown = [t for t in (ltab, rtab) if t and known and t not in known]
    if unknown:
        return f"no table named {', '.join(repr(t) for t in unknown)} in this datasource"
    if ltab and rtab:
        return None
    side = "both sides" if not (ltab or rtab) else (rop if ltab else lop)
    return f"the table of {side} cannot be read from the relationship (BL-278)"


def _relationship_join(
    rel: ET.Element, known: set, grain: dict,
) -> tuple[Optional[dict], Optional[str]]:
    """One `<relationship>` as ``(join or None, warning or None)``."""
    eq = rel.find("./expression[@op='=']")
    exprs = eq.findall("./expression") if eq is not None else []
    if len(exprs) < 2:
        return None, None
    lop, rop = exprs[0].get("op", ""), exprs[1].get("op", "")
    lcol, ltab, lwrap = _relationship_operand(lop)
    rcol, rtab, rwrap = _relationship_operand(rop)
    skipped = _skip_reason(lop, ltab, rop, rtab, known)
    if skipped:
        return None, f"relationship {lop} = {rop} skipped: {skipped}"
    wrappers = sorted({w for w in (lwrap, rwrap) if w})
    warning = (f"relationship {lop} = {rop} joined on the bare columns without "
               f"{', '.join(wrappers)}(): the join can match different rows than "
               "Tableau's, so review it before import" if wrappers else None)
    # MANY side = finer grain (more detail id columns). Orient left=MANY, right=ONE.
    if grain.get(rtab, 0) > grain.get(ltab, 0):   # right is finer → right is MANY → swap
        ltab, rtab, lcol, rcol = rtab, ltab, rcol, lcol
    return {
        "type": "INNER",
        "left_table": ltab,           # MANY side
        "right_table": rtab,          # ONE side
        "keys": [{"left": lcol, "right": rcol}],
        "cardinality": "MANY_TO_ONE",
        "_source": "noodle",
    }, warning
