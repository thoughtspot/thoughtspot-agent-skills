"""Correctness tests for `ts_cli.tableau.joins` — 2026-09-22 audit angle 17.

These pin behaviour the parser's own contract promises and did not deliver, and
document the one question the repo cannot answer from its own fixtures.
"""
import xml.etree.ElementTree as ET

import pytest

from ts_cli.tableau.joins import _extract_joins, _join_sides


def ds(inner: str) -> ET.Element:
    return ET.fromstring(f"<datasource>{inner}</datasource>")


FLAT = """<relation join='inner' type='join'>
  <relation name='ORDERS' type='table' table='[d].[s].[ORDERS]'/>
  <relation name='RETURNS' type='table' table='[d].[s].[RETURNS]'/>
  {clause}
</relation>"""

EQ = """<clause type='join'><expression op='='>
  <expression op='[{l}].[OrderId]'/><expression op='[{r}].[OrderId]'/>
</expression></clause>"""


# ── 17.3 — a dropped join must say so ──────────────────────────────────────

def test_two_tables_no_clause_warns_rather_than_vanishing():
    """`_extract_joins`' contract is to report what it skips. This path did not.

    With both tables resolvable from child order and no `<clause>` at all, the
    key loop never runs, `join_keys` stays empty, and the relation is skipped —
    previously with nothing appended to `warnings`, so a join present in the
    workbook was absent from the model and from the migration report.
    """
    joins, warnings = _extract_joins(ds(FLAT.format(clause="")))
    assert joins == []
    assert len(warnings) == 1
    assert "ORDERS" in warnings[0] and "RETURNS" in warnings[0]
    assert "no join clause" in warnings[0]


def test_unary_clause_still_warns():
    """The neighbouring path already warned; keep it that way."""
    clause = "<clause type='join'><expression op='NOT'><expression op='[ORDERS].[k]'/></expression></clause>"
    joins, warnings = _extract_joins(ds(FLAT.format(clause=clause)))
    assert joins == []
    assert any("no recognizable comparison" in w for w in warnings)


def test_a_good_join_emits_no_warning():
    joins, warnings = _extract_joins(ds(FLAT.format(clause=EQ.format(l="ORDERS", r="RETURNS"))))
    assert warnings == []
    assert len(joins) == 1
    assert joins[0]["keys"] == [{"left": "OrderId", "right": "OrderId"}]


# ── 17.1 — what the two anchors actually do ────────────────────────────────

def test_child_order_cannot_resolve_a_nested_join():
    """Why the clause is consulted first. Child order sees a join node + one table."""
    nested = ET.fromstring("""<relation join='inner' type='join'>
      <relation join='inner' type='join'>
        <relation name='A' type='table' table='[d].[s].[A]'/>
        <relation name='B' type='table' table='[d].[s].[B]'/>
        <clause type='join'><expression op='='>
          <expression op='[A].[k]'/><expression op='[B].[k]'/></expression></clause>
      </relation>
      <relation name='C' type='table' table='[d].[s].[C]'/>
      <clause type='join'><expression op='='>
        <expression op='[B].[c]'/><expression op='[C].[c]'/></expression></clause>
    </relation>""")
    table_children = [c for c in nested.findall("./relation")
                      if c.get("type") in ("table", "text")]
    assert [c.get("name") for c in table_children] == ["C"], "only one side"
    assert _join_sides(nested, nested.findall("./clause")) == ("B", "C")


def test_flat_join_same_order_agrees_under_either_anchor():
    rel = ET.fromstring(FLAT.format(clause=EQ.format(l="ORDERS", r="RETURNS")))
    assert _join_sides(rel, rel.findall("./clause")) == ("ORDERS", "RETURNS")


def test_flat_join_reversed_clause_follows_the_clause_not_the_children():
    """The case the audit raised, pinned as CURRENT behaviour — not as correct.

    Children are (ORDERS, RETURNS); the clause names (RETURNS, ORDERS). The two
    anchors disagree, and `left_table` is consumed downstream as the MANY side
    (`twb.py`), so which one wins inverts the emitted cardinality.

    Neither anchor is evidence of cardinality. The sibling noodle path says so
    outright — "Tableau defers cardinality to query time, so it is (almost
    always) absent from the file" — and infers the MANY side from CTE grain
    instead. This test records what the parser does so a future change is
    deliberate; BL-296 carries the question.
    """
    rel = ET.fromstring(FLAT.format(clause=EQ.format(l="RETURNS", r="ORDERS")))
    assert _join_sides(rel, rel.findall("./clause")) == ("RETURNS", "ORDERS")


def test_reversed_clause_still_pairs_keys_with_the_right_tables():
    """Whichever anchor wins, the keys must follow it — this part is sound."""
    joins, warnings = _extract_joins(ds(FLAT.format(clause=EQ.format(l="RETURNS", r="ORDERS"))))
    assert warnings == []
    assert joins[0]["left_table"] == "RETURNS"
    assert joins[0]["keys"] == [{"left": "OrderId", "right": "OrderId"}]
