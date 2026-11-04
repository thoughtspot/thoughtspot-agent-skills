"""Derived fields for the D (Data Modeling) rules.

Registered into the same registry as engine/fields.py (which imports this module at its
end, so `fields.FIELDS` — and the catalog gate's list of known names — always includes
them). Each reproduces what a legacy check in checks_data.py (deleted when the rule catalog replaced them) read,
step for step, including the readings that are known to be wrong (the legacy answers
pinned in tests/audit_rule_fixtures/legacy_findings.json.gz hold them to it; fixing
them is the follow-up work the spec lists):

- D10 and D11 looked a model table up by its `name`, where its columns' `column_id`s
  carry the `alias` when it has one (BL-305). Since 2026-10 (roadmap PR 2.3) they key a
  table by alias, else name (tml.table_key), and resolve a join's `with` to the table
  it names (tml.join_target), as the join graph does.

Same import constraint as fields.py: Python 3.9, no third-party imports at module level.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from ts_cli.audit.engine import tml
from ts_cli.audit.engine.fields import _model_of, model_roles, register
from ts_cli.audit.engine.memo import cached
from ts_cli.tml_join_graph import on_clause_key_pairs


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
    """Join: the key (alias, else name) of the model table it is declared on ("" when
    absent). The physical `name` until 2026-10 (BL-305)."""
    return tml.table_key(_join_from_table(item))


@register("is_fact_to_fact_join", uses=(), values=(False, True),
          label="the join links two tables that both hold measures")
def _is_fact_to_fact_join(item: dict, ctx: Any) -> bool:
    """Join: both ends hold measures — each end's role (model_roles) is `fact` or
    `dimension_with_measures` — each end by its key (alias, else name): the declaring
    table's, and the table the join's `with` names (tml.join_target_key). Under roles
    from join direction a root is never joined to, so "two facts" would never hold; two
    tables of measures joined, one side's repeating, is what the field always meant.
    Until 2026-11 an end was a fact when it had more than 3 MEASURE columns."""
    model = _model_of(item)
    roles = model_roles(model, ctx)
    to_table = tml.join_target_key(model.get("model_tables") or [],
                                   (item.get("obj") or {}).get("with", ""))
    held = ("fact", "dimension_with_measures")
    return all((roles.get(k) or {}).get("role") in held
               for k in (_join_from_name(item, ctx), to_table))


# ── model tables (D5, D6, D10) ──────────────────────────────────────────────

def _joined_keys(model: dict) -> set:
    """Every table on either side of a join, by key (tml.joined_keys; D5, D10, and H3
    through fields_human). Once per Model per run (engine/memo.py)."""
    return cached("joined_keys", model, tml.joined_keys, model.get("model_tables") or [])


@register("is_joined", uses=(),
          label="the table takes part in a join")
def _is_joined(item: dict, ctx: Any) -> bool:
    """Model table: its key (alias, else name) is on either side of some join."""
    return item.get("name") in _joined_keys(_model_of(item))


@register("zero_column_role", uses=(), values=(None, "bridge", "leaf"),
          label="the table's place in the joins")
def _zero_column_role(item: dict, ctx: Any) -> Optional[str]:
    """Model table (D10): None when its key (alias, else name) prefixes some model
    column's `column_id`; otherwise "bridge" when it is on either side of a join,
    "leaf" when not. Keyed by `name` until 2026-10, so an aliased table always read
    zero-column (BL-305)."""
    model = _model_of(item)
    with_columns = set()
    for c in model.get("columns") or []:
        cid = c.get("column_id", "")
        if isinstance(cid, str) and "::" in cid:
            with_columns.add(cid.split("::")[0])
    key = tml.table_key(item.get("obj") or {})
    if key in with_columns:
        return None
    return "bridge" if key in _joined_keys(model) else "leaf"


def _table_columns(item: dict) -> Tuple[list, list]:
    """(the model's columns, those whose `column_id` prefix is this table's key)."""
    cols = _model_of(item).get("columns") or []
    key = item.get("name")
    return cols, [c for c in cols if (c.get("column_id") or "").split("::")[0] == key]


def _attribute_count(table_cols: List[dict]) -> int:
    return sum(1 for c in table_cols
               if tml.mapping(c, "properties").get("column_type") == "ATTRIBUTE")


@register("table_role", uses=(),
          label="the table's role (fact, factless, dimension or dimension with measures)")
def _table_role(item: dict, ctx: Any) -> str:
    """Model table: its role from join direction (model_roles), by its key — alias,
    else name: fact, factless, dimension or dimension_with_measures ("" for a table
    the classifier skipped as malformed)."""
    return (model_roles(_model_of(item), ctx).get(item.get("name")) or {}).get("role", "")


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
    table whose role (model_roles, by key: alias else name) is `fact`."""
    model = item.get("obj") or {}
    roles = model_roles(model, ctx)
    return [t.get("fqn", t.get("name", "")) for t in model.get("model_tables") or []
            if (roles.get(tml.table_key(t)) or {}).get("role") == "fact"]


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


# ── S12: an RLS table on the optional side of an outer join ─────────────────

#: An RLS rule keeping a table's unmatched (null) rows: a null test on a column — the RLS
#: docs' `is_null ( … )` (security-rls, "Respect join definitions"), the formula
#: language's `isnull ( … )` (thoughtspot-formula-patterns.md), or `= null`.
_ISNULL_CALL = re.compile(r"(?i)\bis_?null\s*\(|=\s*null\b")


def _optional_tables(join: dict, model_tables: list) -> List[dict]:
    """The model tables an outer join may find no row in — the side that can be null:
    the table its `with` names (tml.join_target, as the join graph resolves it) for
    LEFT_OUTER, the declaring table for RIGHT_OUTER, both for OUTER (ThoughtSpot's full
    outer join); none otherwise, and none it cannot resolve."""
    kind = _upper(join.get("type"))
    declaring = join.get("model_table")
    target = tml.join_target(model_tables, join.get("with"))
    sides = {"LEFT_OUTER": [target], "RIGHT_OUTER": [declaring],
             "OUTER": [declaring, target]}.get(kind, [])
    return [t for t in sides if isinstance(t, dict)]


def _key(model_table: dict) -> str:
    """A model table's key (alias, else name) when it is a string, else ""."""
    for k in ("alias", "name"):
        if isinstance(model_table.get(k), str) and model_table[k]:
            return model_table[k]
    return ""


def _unguarded_rls(table_doc: Any) -> bool:
    """A Table TML with RLS rules, none of which has a null branch (_ISNULL_CALL)."""
    t = table_doc.get("table") if isinstance(table_doc, dict) else None
    rls = t.get("rls_rules") if isinstance(t, dict) else None
    rules = rls.get("rules") if isinstance(rls, dict) else None
    rules = [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []
    return bool(rules) and not any(_ISNULL_CALL.search(str(r.get("expr") or ""))
                                   for r in rules)


@register("outer_join_unguarded_rls", uses=(),
          label="the outer join's optional-side tables with RLS and no null branch")
def _outer_join_unguarded_rls(item: dict, ctx: Any) -> list:
    """Join: the keys, sorted, of the tables on its optional side (_optional_tables) whose
    Table TML carries RLS rules none of which has a null branch (`is_null` / `isnull`).
    Without one the outer join can act as an inner one for users under the rule
    (security-rls, "Respect join definitions"). A table with no Table TML in scope is
    unknown and not listed; a name list in messages."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    model_tables = _model_of(item).get("model_tables")
    sides = _optional_tables(item.get("obj") or {},
                             model_tables if isinstance(model_tables, list) else [])
    return NameList(sorted({_key(t) for t in sides
                            if isinstance(t.get("fqn"), str)
                            and _unguarded_rls(ctx.tables.get(t["fqn"]))} - {""}))


# ── D15: duplicate Table-level joins ────────────────────────────────────────

def _join_group_key(j: Any) -> Optional[tuple]:
    """(destination — `fqn`, else `name` —, `on` without whitespace) for a well-formed
    `joins_with` entry, else None."""
    dest = j.get("destination") if isinstance(j, dict) else None
    on = j.get("on") if isinstance(j, dict) else None
    if not isinstance(dest, dict) or not isinstance(on, str) or not on.strip():
        return None
    target = dest.get("fqn") or dest.get("name")
    return (target, "".join(on.split())) if isinstance(target, str) and target else None


def _duplicate_joins(table: dict) -> List[tuple]:
    """(label, conflicting) per group of two or more `joins_with` entries with the same
    destination and `on` (_join_group_key); conflicting when their type or cardinality
    differ. Malformed entries are skipped."""
    joins_with = table.get("joins_with")
    groups: dict = {}
    for j in joins_with if isinstance(joins_with, list) else []:
        key = _join_group_key(j)
        if key:
            groups.setdefault(key, []).append(j)
    out = []
    for (dest, _), joins in groups.items():
        if len(joins) > 1:
            shapes = {(_upper(j.get("type")), _upper(j.get("cardinality"))) for j in joins}
            name = joins[0]["destination"].get("name")
            name = name if isinstance(name, str) and name else dest
            out.append((f"{len(joins)} joins to {name} on {joins[0]['on']}", len(shapes) > 1))
    return out


@register("duplicate_joins", uses=(),
          label="the Table's duplicate joins")
def _duplicate_joins_field(item: dict, ctx: Any) -> list:
    """Table: one label per group of `joins_with` entries sharing a destination and an
    `on` (see _duplicate_joins); a name list in messages, empty when there are none."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    return NameList(label for label, _ in _duplicate_joins(item.get("obj") or {}))


@register("duplicate_joins_conflict", uses=(), values=(False, True),
          label="the Table's duplicate joins differ in type or cardinality")
def _duplicate_joins_conflict(item: dict, ctx: Any) -> bool:
    """Table: a group of duplicate joins whose type or cardinality differ, so a query's
    result depends on which one a Model takes."""
    return any(conflict for _, conflict in _duplicate_joins(item.get("obj") or {}))


# ── D16: join keys of different types ───────────────────────────────────────

#: Warehouse types by family: a join pairing two families compares unlike values.
_TYPE_FAMILIES = {
    "string": ("VARCHAR", "CHAR", "STRING", "TEXT"),
    "integer": ("INT32", "INT64", "INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT"),
    "decimal": ("DOUBLE", "FLOAT", "DECIMAL", "NUMBER", "NUMERIC", "REAL"),
    "datetime": ("DATE", "DATE_TIME", "DATETIME", "TIMESTAMP", "TIME"),
    "boolean": ("BOOL", "BOOLEAN"),
}
_FAMILY_OF = {t: fam for fam, types in _TYPE_FAMILIES.items() for t in types}


def key_type_mismatches(on: Any, col_types: dict) -> List[str]:
    """`"A::x (TYPE) = B::y (TYPE)"` for each key pair in `on` (the join graph's reader,
    tml_join_graph.on_clause_key_pairs: unescaped, whole conjuncts only) whose types are
    in different families (_TYPE_FAMILIES). A key with an unknown type, or a type
    outside the families, is not compared."""
    out = []
    for t1, c1, t2, c2 in on_clause_key_pairs(on if isinstance(on, str) else ""):
        left, right = f"{t1}::{c1}", f"{t2}::{c2}"
        lt, rt = (str(col_types.get(k, "")).upper() for k in (left, right))
        lf, rf = _FAMILY_OF.get(lt), _FAMILY_OF.get(rt)
        if lf and rf and lf != rf:
            out.append(f"{left} ({lt}) = {right} ({rt})")
    return out


@register("join_key_type_mismatches", uses=(),
          label="the join's key pairs of different types")
def _join_key_type_mismatches(item: dict, ctx: Any) -> list:
    """Join: each pair of keys in its `on` whose warehouse types, read off the Table TMLs
    (AuditContext.column_types, as @varchar_join_keys reads them), are of different
    families; a name list in messages. A key of a table with no Table TML in scope — or,
    through that lookup, of an aliased table — has no type and is not compared."""
    from ts_cli.audit.engine.messages import NameList  # messages imports fields
    col_types = cached("column_types", item["doc"], ctx.column_types, item["doc"])
    return NameList(key_type_mismatches((item.get("obj") or {}).get("on"), col_types))

