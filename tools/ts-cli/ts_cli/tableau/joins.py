"""Physical join extraction from a Tableau datasource's `<relation join=...>` tree.

Split out of `twb.py` (module-per-concern, BL-069 pattern) to keep that file's
line count in budget — same reason `set_extract.py` was split out. Re-exported
from `ts_cli.tableau.twb`, so existing callers and tests importing these names
from there keep working unchanged.

Imports nothing from `twb.py`, deliberately: `twb.py` imports this module, and
the reverse would be a cycle.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

# Only equality joins are emitted. ThoughtSpot's `joins[].on` documents range
# operators, but nothing here inspects the emitted operator, every join this
# builder writes carries `cardinality: MANY_TO_ONE` (which a non-equality
# relationship cannot satisfy), and BL-240 records `>=` returning materially
# wrong numbers on both legs of an ASOF join. So a non-`=` clause is skipped
# and reported rather than guessed at. Tableau writes not-equal as `<>`.
_SUPPORTED_JOIN_OPERATOR = "="


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

    Inherited limitation: `.strip("[]")` removes every leading/trailing bracket,
    so a column name ending in one (Tableau doubles a literal `]`) loses it.
    """
    stripped = op.strip("[]")
    if "].[" in stripped:
        table, column = stripped.rsplit("].[", 1)
        return column, table
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
        keys.append({
            "left": _join_key_operand(left)[0],
            "right": _join_key_operand(right)[0],
        })
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
        join_keys = []
        for clause in clauses:
            clause_keys = _clause_join_keys(clause, left_table, right_table, warnings)
            if clause_keys:
                join_keys.extend(clause_keys)
        if join_keys:
            joins.append({
                "type": rel.get("join", "inner").upper(),
                "left_table": left_table,
                "right_table": right_table,
                "keys": join_keys,
            })
    return joins, warnings
