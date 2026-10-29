"""Derived fields for the D (Data Modeling) rules.

Registered into the same registry as engine/fields.py (which imports this module at its
end, so `fields.FIELDS` — and the catalog gate's list of known names — always includes
them). Each reproduces what a legacy check in checks_data.py (deleted when the rule catalog replaced them) read,
step for step, including the readings that are known to be wrong (the legacy answers
pinned in tests/audit_rule_fixtures/legacy_findings.json.gz hold them to it; fixing
them is the follow-up work the spec lists):

- D10 and D11 look a model table up by its `name`, where its columns' `column_id`s
  carry the `alias` when it has one (BL-305) — @zero_column_role, @join_from_name and
  @is_fact_to_fact_join keep that.
- D6 keys by alias, else name (tml.table_key) — the model.table scope's own name.

Same import constraint as fields.py: Python 3.9, no third-party imports at module level.
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from ts_cli.audit.engine import tml
from ts_cli.audit.engine.fields import _model_of, register
from ts_cli.audit.engine.memo import cached


def _upper(value: Any) -> Optional[str]:
    """`(value or "").upper()` as the legacy checks read a join's type and cardinality;
    None for a non-string (where the legacy `.upper()` would raise)."""
    value = value or ""
    return value.upper() if isinstance(value, str) else None


# ── joins (D3, D11) ─────────────────────────────────────────────────────────

@register("join_type", uses=(),
          values=("", "INNER", "LEFT_OUTER", "RIGHT_OUTER", "OUTER", None),
          label="the join type")
def _join_type(item: dict, ctx: Any) -> Optional[str]:
    """Join: its type upper-cased ("" when unset) — INNER, LEFT_OUTER, RIGHT_OUTER or
    OUTER (ThoughtSpot's full outer join). A referencing join's type comes from the
    Table's `joins_with` unless the model overrides it (tml.model_joins)."""
    return _upper((item.get("obj") or {}).get("type"))


@register("join_cardinality", uses=(),
          label="the join cardinality")
def _join_cardinality(item: dict, ctx: Any) -> Optional[str]:
    """Join: its cardinality upper-cased ("" when unset): the model's own, else a
    referencing join's Table `joins_with` entry, which exported Table TML rarely
    carries (tml.model_joins)."""
    return _upper((item.get("obj") or {}).get("cardinality"))


def _join_from_table(item: dict) -> dict:
    return (item.get("obj") or {}).get("model_table") or {}


@register("join_from_name", uses=(),
          label="the table the join starts from")
def _join_from_name(item: dict, ctx: Any) -> Any:
    """Join: the `name` of the model table it is declared on ("" when absent) — the
    physical name, not the alias (legacy D11's reading)."""
    return _join_from_table(item).get("name", "")


@register("is_fact_to_fact_join", uses=(), values=(False, True),
          label="the join links two fact tables")
def _is_fact_to_fact_join(item: dict, ctx: Any) -> bool:
    """Join: both ends read as fact tables (more than 3 MEASURE columns — rules.
    table_role), each end looked up by NAME: the model table's `name` and the join's
    `with` (legacy D11; an aliased end therefore reads as "unknown", BL-305)."""
    cols = _model_of(item).get("columns") or []
    to_table = (item.get("obj") or {}).get("with", "")
    return (tml.table_role(cols, _join_from_name(item, ctx)) == "fact"
            and tml.table_role(cols, to_table) == "fact")


# ── model tables (D5, D6, D10) ──────────────────────────────────────────────

def _joined_keys(model: dict) -> set:
    """Every table on either side of a join: the declaring table's key (alias, else
    name) and the join's `with`, as legacy D5 and D10 collect them. Once per Model per
    run (engine/memo.py)."""
    return cached("joined_keys", model, _build_joined_keys, model)


def _build_joined_keys(model: dict) -> set:
    joined: set = set()
    for t in model.get("model_tables") or []:
        for j in (t.get("joins") or []):
            joined.add(tml.table_key(t))
            joined.add(j.get("with", ""))
    return joined


@register("is_joined", uses=(),
          label="the table takes part in a join")
def _is_joined(item: dict, ctx: Any) -> bool:
    """Model table: its key (alias, else name) is on either side of some join."""
    return item.get("name") in _joined_keys(_model_of(item))


@register("zero_column_role", uses=(), values=(None, "bridge", "leaf"),
          label="the table's place in the joins")
def _zero_column_role(item: dict, ctx: Any) -> Optional[str]:
    """Model table, legacy D10: None when its `name` prefixes some model column's
    `column_id`; otherwise "bridge" when that name is on either side of a join, "leaf"
    when not. By NAME, not alias, so an aliased table always reads zero-column
    (BL-305, kept)."""
    model = _model_of(item)
    with_columns = set()
    for c in model.get("columns") or []:
        cid = c.get("column_id", "")
        if isinstance(cid, str) and "::" in cid:
            with_columns.add(cid.split("::")[0])
    name = (item.get("obj") or {}).get("name", "")
    if name in with_columns:
        return None
    return "bridge" if name in _joined_keys(model) else "leaf"


def _table_columns(item: dict) -> Tuple[list, list]:
    """(the model's columns, those whose `column_id` prefix is this table's key)."""
    cols = _model_of(item).get("columns") or []
    key = item.get("name")
    return cols, [c for c in cols if (c.get("column_id") or "").split("::")[0] == key]


def _attribute_count(table_cols: List[dict]) -> int:
    return sum(1 for c in table_cols
               if (c.get("properties") or {}).get("column_type") == "ATTRIBUTE")


@register("table_role", uses=(),
          label="the table's role (fact or dimension)")
def _table_role(item: dict, ctx: Any) -> str:
    """Model table: "fact" (more than 3 MEASURE columns), "dimension", or "unknown"
    (no columns), its columns found by its key — alias, else name (tml.table_role)."""
    cols, _ = _table_columns(item)
    return tml.table_role(cols, item.get("name"))


@register("table_column_count", uses=(),
          label="the number of the table's columns")
def _table_column_count(item: dict, ctx: Any) -> int:
    """Model table: how many model columns its key prefixes."""
    return len(_table_columns(item)[1])


@register("attribute_count", uses=(),
          label="the number of ATTRIBUTE columns")
def _attribute_count_field(item: dict, ctx: Any) -> int:
    """Model table: how many of its model columns are ATTRIBUTEs."""
    return _attribute_count(_table_columns(item)[1])


@register("attribute_share", uses=(),
          label="the share of ATTRIBUTE columns")
def _attribute_share(item: dict, ctx: Any) -> Optional[float]:
    """Model table: the fraction of its model columns that are ATTRIBUTEs (None
    without columns) — what legacy D6 compares (`> 0.4`). Its metric, the rounded
    percentage (@attribute_pct), is not: 40.04% rounds to 40.0 yet is over the line."""
    _, table_cols = _table_columns(item)
    return _attribute_count(table_cols) / len(table_cols) if table_cols else None


@register("attribute_pct", uses=(),
          label="the percentage of ATTRIBUTE columns")
def _attribute_pct(item: dict, ctx: Any) -> Optional[float]:
    """Model table: that share as a percentage, rounded to 1 place (D6's metric)."""
    _, table_cols = _table_columns(item)
    if not table_cols:
        return None
    return round(_attribute_count(table_cols) / len(table_cols) * 100, 1)


# ── models (D7) and metadata (D8) ───────────────────────────────────────────

@register("table_set", uses=(),
          label="the Model's tables")
def _table_set(item: dict, ctx: Any) -> list:
    """Model: each model table's identity as legacy D7 reads it — its `fqn`, or its
    `name` ("" when absent) when it has no `fqn` key at all (an explicit `fqn: None`
    stays None)."""
    return [t.get("fqn", t.get("name", ""))
            for t in (item.get("obj") or {}).get("model_tables") or []]


@register("fact_table_set", uses=(),
          label="the Model's fact tables")
def _fact_table_set(item: dict, ctx: Any) -> list:
    """Model: the identity (as @table_set reads it: `fqn`, else `name`) of each model
    table that reads as a fact table — more than 3 MEASURE columns, its columns found
    by its key, alias else name (tml.table_key; not the name-only lookup BL-305
    records). Formula measures are not counted, as in every audit fact test today."""
    model = item.get("obj") or {}
    cols = model.get("columns") or []
    return [t.get("fqn", t.get("name", "")) for t in model.get("model_tables") or []
            if tml.table_role(cols, tml.table_key(t)) == "fact"]


@register("physical_table_key", uses=(),
          label="the physical table (connection, database, schema, name)")
def _physical_table_key(item: dict, ctx: Any) -> Any:
    """Metadata header: (connection, database, schema, table name) — each "" when
    absent — the physical table legacy D8 groups Table objects by. Renders
    dot-joined in a message."""
    from ts_cli.audit.engine.messages import Key  # messages imports fields
    header = item.get("obj") or {}
    return Key((header.get("dataSourceName", ""), header.get("databaseStripe", ""),
                header.get("schemaStripe", ""), header.get("name", "")))
