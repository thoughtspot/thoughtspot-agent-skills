"""Physical join extraction from a Tableau datasource's `<relation join=...>` tree.

Split out of `twb.py` (module-per-concern, BL-069 pattern) to keep that file's
line count in budget — same reason `set_extract.py` was split out. Re-exported
from `ts_cli.tableau.twb`, so the import path is unchanged — but only the path:
`_extract_joins` returns `(joins, warnings)` in this same release where it used
to return `joins`, and a caller left unadapted iterates that 2-tuple rather than
raising.

Imports nothing from `twb.py`, deliberately: `twb.py` imports this module, and
the reverse would be a cycle.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

# Only equality joins are emitted. ThoughtSpot's `joins[].on` documents range
# operators, but nothing here inspects the emitted operator, a join this builder
# writes carries `cardinality: MANY_TO_ONE` by default (which a non-equality
# relationship cannot satisfy), and BL-240 records `>=` returning materially
# wrong numbers on both legs of an ASOF join. So a non-`=` clause is skipped
# and reported rather than guessed at. Tableau writes not-equal as `<>`.
_SUPPORTED_JOIN_OPERATOR = "="


# Consulted on an OPERAND, not on the operator combining them. Arity alone
# cannot tell `(A=B)` from `CONCAT([A],[B])` — both hold two children — so an
# operand counts as a condition only when its own operator is one of these.
# A connective absent from the set is still caught, because what is inspected is
# its operands: `NAND` over two equalities is reported by name, since those
# equalities are conditions whatever sits above them.
_CONDITION_OPERATORS = frozenset({
    "=", "<>", ">", ">=", "<", "<=", "AND", "OR", "XOR", "NOT",
})


def _is_condition(expr: ET.Element) -> bool:
    """True when an operand is itself a comparison, not a column or a function call.

    Both halves are needed: an equality sitting under a connective, or beside
    another under one `<clause>`, carries a comparison operator AND two operands,
    while ``UPPER([Col])`` fails the child count and ``CONCAT([A],[B])`` fails
    the operator — both are reported as unsupported operands instead.
    """
    return (expr.get("op", "").upper() in _CONDITION_OPERATORS
            and len(expr.findall("./expression")) >= 2)


def _relation_name(rel: ET.Element) -> str:
    """A join side's name: its own `name`, else the leaf of its `table` path."""
    return rel.get("name", "") or rel.get("table", "").replace("[", "").replace("]", "").split(".")[-1]


def _join_key_operand(op: str) -> tuple[str, str]:
    """Split a join-clause operand into ``(column, table)``; table is `""` if bare.

    Tableau writes the operand bare (``[Col]``) or table-qualified
    (``[Table].[Col]``). The table half is kept, not discarded: it is the only
    thing in the XML that says which tables a clause joins — see `_join_sides`.
    Mirrors `parse_ref()` in `_extract_noodle_joins`, same problem for the
    logical-relationship shape.

    The table is the LEAF of the qualifier, so a deeper one
    (``[Schema].[Table].[Col]``) yields `Table`, not `Schema].[Table`. That
    matches `_relation_name`, which the result is compared against — a name
    carrying the separator matches no relation and the join is dropped with no
    warning. Leaf-keying means same-named tables in different schemas collapse
    to one name; that is already true of `_relation_name` and so of this whole
    module, not something this split introduces.

    Inherited limitation: `.strip("[]")` removes every leading/trailing bracket,
    so a column name ending in one (Tableau doubles a literal `]`) loses it.
    """
    stripped = op.strip("[]")
    if "].[" in stripped:
        table, column = stripped.rsplit("].[", 1)
        return column, table.rsplit("].[", 1)[-1]
    return stripped, ""


def _collect_comparisons(node: ET.Element) -> list[tuple[ET.Element, ET.Element, str]]:
    """Recursively collect (left, right, op) comparison triples from a join clause.

    Recurses through `AND` at any depth so a composite key keeps every condition
    — truncating to the first one joins on a partial key, which fans out and
    silently double-counts every measure built on it.

    Only the `<clause>` node is transparent. An `<expression>` is never unwrapped
    on the caller's behalf: its `op` is returned verbatim, so an unary wrapper
    (`NOT`) or a blank operator reaches the caller as an unrecognised operator
    and is reported, rather than being silently read as the equality it wraps.
    """
    children = [c for c in node if c.tag == "expression"]
    is_wrapper = node.tag == "expression"
    # A flat `<clause>` carries its operands directly and is equality by
    # construction — it has no operator node to read.
    op = node.get("op", "") if is_wrapper else _SUPPORTED_JOIN_OPERATOR
    if op.upper() == "AND" and children:
        out: list[tuple[ET.Element, ET.Element, str]] = []
        for child in children:
            out.extend(_collect_comparisons(child))
        return out
    if len(children) == 2:
        # Pass the pair through even when a side isn't a plain leaf (e.g.
        # UPPER([Col])) — the caller's bracket check is what warns about that
        # shape; matching stricter here made it vanish with no warning at all.
        return [(children[0], children[1], op)]
    if len(children) == 1 and not is_wrapper:
        return _collect_comparisons(children[0])
    return []


def _join_sides(rel: ET.Element, clauses: list[ET.Element]) -> tuple[str, str]:
    """Resolve ``(left_table, right_table)`` for one ``<relation join=...>``.

    The clause's qualifiers win over child order. On a nested ``((A⋈B)⋈C)`` the
    outer relation's direct children are a join node plus one table, so child
    order resolves only one side and the other comes back empty — matching no
    table and dropping the join silently. And even on a flat join the clause may
    name its operands in the opposite order to the children, which pairs both
    columns with the wrong table: a join that imports and lints clean and
    changes every number built on it.

    Falls back to child order for the legacy flat clause shape, whose operands
    carry no qualifier. A side may be a Custom SQL relation (`type='text'`), not
    just a physical table.
    """
    for clause in clauses:
        for left_expr, right_expr, _ in _collect_comparisons(clause):
            _, left_table = _join_key_operand(left_expr.get("op", ""))
            _, right_table = _join_key_operand(right_expr.get("op", ""))
            if left_table and right_table:
                return left_table, right_table

    children = [c for c in rel.findall("./relation") if c.get("type") in ("table", "text")]
    if len(children) < 2:
        return "", ""
    return _relation_name(children[0]), _relation_name(children[1])


def _connective_label(raw_op: str) -> str:
    """How two conditions are combined, for the skip message.

    `(none)` rather than an empty interpolation, matching the non-equality
    branch in ``_clause_join_keys`` — a blank `op` is not `=`, so without this
    the customer-facing report reads "combines conditions with  —". Extracted
    rather than inlined to keep ``_clause_join_keys`` under the BL-089
    complexity cap.
    """
    if raw_op == _SUPPORTED_JOIN_OPERATOR:
        return "side by side"
    return f"with {raw_op.upper() if raw_op else '(none)'}"


def _clause_join_keys(
    clause: ET.Element, left_table: str, right_table: str, warnings: list[str]
) -> list[dict] | None:
    """One ``<clause>`` → join keys, or ``None`` if it must be skipped.

    A skip is all-or-nothing: keeping the translatable half of a composite key
    would join on part of that key, with the same fan-out risk as dropping it.
    """
    comparisons = _collect_comparisons(clause)
    if not comparisons:
        warnings.append(
            f"join clause between {left_table!r} and {right_table!r} has no "
            f"recognizable comparison — an unary operator such as NOT, or a "
            f"clause shape this parser does not read; skipped"
        )
        return None
    composite_note = " (composite key)" if len(comparisons) > 1 else ""
    keys: list[dict] = []
    for left_expr, right_expr, raw_op in comparisons:
        left = left_expr.get("op", "")
        right = right_expr.get("op", "")
        # Ahead of the operand check, which would otherwise report the `=` inside
        # a combined condition and blame a function call that isn't there.
        if _is_condition(left_expr) or _is_condition(right_expr):
            how = _connective_label(raw_op)
            warnings.append(
                f"join clause between {left_table!r} and {right_table!r} combines "
                f"conditions {how} — a ThoughtSpot join is a conjunction of key "
                f"pairs, so only AND-combined equalities are supported; skipped"
            )
            return None
        if not (left.startswith("[") and right.startswith("[")):
            bad = left if not left.startswith("[") else right
            warnings.append(
                f"join clause between {left_table!r} and {right_table!r} has an "
                f"unsupported operand {bad!r} — not a plain column reference "
                f"(function call or unrecognized expression){composite_note}, skipped"
            )
            return None
        if raw_op != _SUPPORTED_JOIN_OPERATOR:
            shown = raw_op if raw_op else "(none)"
            warnings.append(
                f"join clause between {left_table!r} and {right_table!r} uses "
                f"non-equality operator {shown!r}{composite_note} — non-equi "
                f"joins are not supported yet, skipped"
            )
            return None
        left_col, left_qual = _join_key_operand(left)
        right_col, right_qual = _join_key_operand(right)
        # `left`/`right` mean "belongs to left_table/right_table", but the
        # relation's orientation is fixed by the FIRST qualified comparison and
        # a later one may name its operands the other way round — the same join,
        # written in the other direction. Re-orient against the resolved tables
        # rather than trusting operand order. Only an unambiguous match swaps, so
        # a bare operand falls through. `left_qual != right_qual` is what keeps a
        # self-join out: there both comparisons against the resolved pair hold
        # trivially, and the swap would reverse a correctly-ordered key.
        if (left_qual != right_qual
                and left_qual == right_table and right_qual == left_table):
            left_col, right_col = right_col, left_col
        keys.append({"left": left_col, "right": right_col})
    return keys


def _extract_joins(ds: ET.Element) -> tuple[list[dict], list[str]]:
    """Extract join definitions from a datasource → ``(joins, warnings)``."""
    joins = []
    warnings: list[str] = []
    for rel in ds.findall(".//relation[@join]"):
        # `./clause`, NOT `.//clause`: on a nested join a descendant search also
        # picks up the inner relation's clause, welding two separate joins into
        # one bogus composite — and the inner relation is visited in its own
        # right anyway, so those keys would be emitted twice.
        clauses = rel.findall("./clause")
        # Resolved up front so a skip warning can name the tables it means.
        left_table, right_table = _join_sides(rel, clauses)
        if not (left_table and right_table):
            # `_join_sides`' own sentinel for "no table pair" — a nested join
            # whose clauses carry no qualifier, where child order sees a join
            # node plus one table. An entry with a blank name binds to nothing
            # in either `model_tables` builder, so emitting it loses the join
            # two modules later with nothing said. Report it here instead.
            cause = ("its clause operands carry no table qualifier and child "
                     "order resolves only one side" if clauses else
                     "it carries no join clause to read table names from")
            warnings.append(
                f"join could not be resolved to a table pair — {cause}; skipped"
            )
            continue
        # Sibling <clause> nodes are conditions of ONE composite key — this loop
        # merges them into a single join — so a failure in any of them makes the
        # key partial, exactly as a failed condition inside one clause does.
        # `_clause_join_keys` returns None for a deliberate skip, [] for nothing
        # found; only the former abandons the relation.
        join_keys = []
        for clause in clauses:
            clause_keys = _clause_join_keys(clause, left_table, right_table, warnings)
            if clause_keys is None:
                join_keys = None
                break
            join_keys.extend(clause_keys)
        if join_keys:
            joins.append({
                "type": rel.get("join", "inner").upper(),
                "left_table": left_table,
                "right_table": right_table,
                "keys": join_keys,
            })
    return joins, warnings
