"""Pre-import TML linter — the model invariants that `--policy VALIDATE_ONLY` does NOT catch.

ThoughtSpot accepts TML that violates these and then behaves wrong (silently drops a
formula, flips a measure to an attribute, breaks a join at query time). Catching them
locally — before import — is the only way to fail loud. Rules mirror invariants
I1/I2/I4/I5/I8 in `agents/shared/schemas/ts-model-conversion-invariants.md`.

Pure functions over a parsed TML dict so they are trivially unit-testable.
"""
from __future__ import annotations

import re
from typing import Any


def lint_tml(data: dict) -> list[str]:
    """Return a list of invariant-violation strings for one parsed TML doc. Empty = clean.

    Auto-detects table vs model TML by the top-level key. Only the model invariants
    (I1/I2/I4/I5) plus the guid-placement rule are checked here — these are the ones the
    server's VALIDATE_ONLY policy does not surface.
    """
    if not isinstance(data, dict):
        return ["Top-level TML value must be a mapping"]

    findings: list[str] = []

    # guid must sit at the document root, never nested inside table:/model:.
    for key in ("table", "model"):
        inner = data.get(key)
        if isinstance(inner, dict) and "guid" in inner:
            findings.append(
                f"guid is nested inside '{key}:' — it must be a top-level key "
                f"(sibling of '{key}:'), or omitted on first import."
            )

    model = data.get("model")
    if not isinstance(model, dict):
        return findings  # not a model TML — nothing more to check here

    formulas = model.get("formulas") or []
    columns = model.get("columns") or []
    model_tables = model.get("model_tables") or []

    # I1 — every formulas[] id has a paired columns[] entry (formula_id == id).
    paired = {c.get("formula_id") for c in columns if isinstance(c, dict)}
    for f in formulas:
        if not isinstance(f, dict):
            continue
        fid = f.get("id")
        if fid and fid not in paired:
            findings.append(
                f"I1: formula '{fid}' has no paired columns[] entry "
                f"(formula_id: {fid}) — it will be silently dropped on import."
            )

    # I2 — no aggregation: inside a formulas[] entry (only columns[] may carry it).
    for f in formulas:
        if isinstance(f, dict) and isinstance(f.get("properties"), dict) and "aggregation" in f["properties"]:
            findings.append(
                f"I2: formula '{f.get('id', '?')}' has an aggregation: under formulas[] — "
                f"raises 'FORMULA is not a valid aggregation type'. Move it to the columns[] entry."
            )

    # I4 — model_tables[].id (when present) must equal name exactly (case included).
    for t in model_tables:
        if isinstance(t, dict) and "id" in t and t.get("id") != t.get("name"):
            findings.append(
                f"I4: model_tables id '{t.get('id')}' != name '{t.get('name')}' — "
                f"joins silently fail at query time ('{t.get('name')} does not exist in schema')."
            )

    # I5 — a physical-column columns[] entry must not use aggregation: COUNT_DISTINCT
    # (it silently flips column_type MEASURE → ATTRIBUTE; use a `unique count(...)` formula).
    for c in columns:
        if not isinstance(c, dict) or "formula_id" in c:
            continue  # formula columns are exempt; this targets physical columns
        props = c.get("properties") or {}
        if isinstance(props, dict) and props.get("aggregation") == "COUNT_DISTINCT":
            findings.append(
                f"I5: column '{c.get('name', '?')}' uses aggregation: COUNT_DISTINCT — "
                f"this flips MEASURE → ATTRIBUTE silently. Use a `unique count(...)` formula instead."
            )

    # I8 — every column_id in columns[] must be unique. A duplicate is a HARD import
    # rejection ("columns should have unique column_id values"). When a source defines
    # two metrics on one physical column, only one may be a column_id entry; the rest
    # must be formulas[].
    id_counts: dict[str, int] = {}
    for c in columns:
        if not isinstance(c, dict):
            continue
        cid = c.get("column_id")
        if cid:
            id_counts[cid] = id_counts.get(cid, 0) + 1
    for cid, n in id_counts.items():
        if n > 1:
            findings.append(
                f"I8: column_id '{cid}' appears {n} times in columns[] — ThoughtSpot "
                f"rejects the import ('columns should have unique column_id values'). Keep one "
                f"column_id entry and express the other aggregation(s) as formulas[]."
            )

    return findings


# A bracketed `[TABLE::COL]` reference inside a join `on:` expression. Matches
# regardless of the surrounding operator (`=`, `>=`, `<`, `and`, ...) — we only
# need every bracketed structural ref the expression contains.
_ON_REF_RE = re.compile(r"\[([^\[\]]+?)::([^\[\]]+?)\]")


def _check_table_col_ref(
    ref: str,
    context: str,
    ref_to_table: dict[str, str],
    columns_ci: dict[str, set[str]],
) -> list[str]:
    """Return findings for one structural ``TABLE::COL`` reference, or [] if it resolves.

    Shared by the join `on:` clause check and the `column_id` check (checks 3 & 4)
    — both need to resolve TABLE against ``ref_to_table`` (name-or-alias) and then
    confirm COL exists in that table's generated column set.
    """
    if "::" not in ref:
        return []
    table_part, col_part = ref.split("::", 1)
    table_key = table_part.lower()
    if table_key not in ref_to_table:
        return [
            f"XREF: {context} references table '{table_part}' which is not "
            f"a model table — 'column_id not found' on import."
        ]
    physical = ref_to_table[table_key]
    physical_cols = columns_ci.get(physical.lower())
    if physical_cols is None:
        return []  # table itself wasn't generated — already reported by check 1
    if col_part.lower() not in physical_cols:
        return [
            f"XREF: {context} references column '{col_part}' which does not "
            f"exist on table '{physical}' — 'column_id not found' on import."
        ]
    return []


def _check_model_tables_exist(model_tables: list[dict], tables_ci: dict[str, str]) -> list[str]:
    """Check 1 — every model_tables[].name must have actually been generated."""
    findings: list[str] = []
    for t in model_tables:
        name = t.get("name")
        if name and name.lower() not in tables_ci:
            findings.append(
                f"XREF: model_tables references table '{name}' which was not "
                f"generated — import will fail ('{name} does not exist in schema')."
            )
    return findings


def _check_join_targets(
    model_tables: list[dict],
    ref_to_table: dict[str, str],
    columns_ci: dict[str, set[str]],
) -> list[str]:
    """Checks 2 & 4 — join targets (`with`) and any `[TABLE::COL]` refs inside `on:`."""
    findings: list[str] = []
    for t in model_tables:
        src_name = t.get("name", "?")
        for j in t.get("joins") or []:
            if not isinstance(j, dict):
                continue
            target = j.get("with")
            if target and target.lower() not in ref_to_table:
                findings.append(
                    f"XREF: join on '{src_name}' targets '{target}' which is not "
                    f"a model table — 'destination is missing' or '{target} does "
                    f"not exist in schema' on import."
                )
            on_clause = j.get("on") or ""
            for table_part, col_part in _ON_REF_RE.findall(on_clause):
                findings.extend(
                    _check_table_col_ref(
                        f"{table_part}::{col_part}", f"join on '{src_name}'",
                        ref_to_table, columns_ci,
                    )
                )
    return findings


def _check_column_ids(
    columns: list,
    ref_to_table: dict[str, str],
    columns_ci: dict[str, set[str]],
) -> list[str]:
    """Check 3 — every `column_id: TABLE::COL` in columns[] resolves TABLE/COL."""
    findings: list[str] = []
    for c in columns:
        if not isinstance(c, dict):
            continue
        col_id = c.get("column_id")
        if not col_id or not isinstance(col_id, str):
            continue
        findings.extend(
            _check_table_col_ref(col_id, f"column '{c.get('name', col_id)}'", ref_to_table, columns_ci)
        )
    return findings


def lint_cross_references(model_tml: dict, tables: dict[str, set[str]]) -> list[str]:
    """Return dangling-cross-reference findings for a Model TML. Empty = clean.

    ``tables`` maps each generated table/sql_view NAME to the set of column names
    it provides (e.g. read off freshly-emitted Table/SQL View TML). This catches a
    Model that references a table or column that was never generated — a class of
    import rejection that only surfaces after a round trip to the server otherwise.

    Checks (all case-insensitive on names/columns, matching ThoughtSpot's own
    case-insensitivity on identifiers):

    1. Every ``model_tables[].name`` exists as a key in ``tables``.
    2. Every join target (``model_tables[].joins[].with``) resolves to a
       ``model_tables[]`` entry (matched by ``name`` or, when present, ``alias`` —
       the schema allows a self-join/role-playing table to be addressed by its
       alias, see agents/shared/schemas/thoughtspot-model-tml.md).
    3. Every ``column_id: TABLE::COL`` in ``columns[]`` resolves TABLE to a
       ``model_tables[]`` entry, and COL exists in that table's generated column set.
    4. Every ``[TABLE::COL]`` reference inside a join ``on:`` clause resolves the
       same way as (3).

    Only the structural ``TABLE::COL`` refs in ``column_id`` and joins are checked.
    ``formulas[].expr`` is not inspected — formula-internal ``[formula_*]`` id refs
    and bare (no ``::``) column refs are out of scope for this check.

    Pure function, no I/O.
    """
    if not isinstance(model_tml, dict):
        return []
    model = model_tml.get("model")
    if not isinstance(model, dict):
        return []

    # Case-insensitive index of the tables/sql_views actually generated.
    tables_ci: dict[str, str] = {name.lower(): name for name in tables}
    columns_ci: dict[str, set[str]] = {
        name.lower(): {c.lower() for c in cols} for name, cols in tables.items()
    }

    model_tables = [t for t in (model.get("model_tables") or []) if isinstance(t, dict)]

    # Every reference name a model_tables[] entry can be addressed by (its `name`
    # AND, when present, its `alias`) -> the entry's physical table name, so a
    # column-set lookup always keys into `tables` by the real generated name.
    ref_to_table: dict[str, str] = {}
    for t in model_tables:
        name = t.get("name")
        alias = t.get("alias")
        if name:
            ref_to_table.setdefault(name.lower(), name)
        if alias:
            ref_to_table.setdefault(alias.lower(), name or alias)

    findings: list[str] = []
    findings.extend(_check_model_tables_exist(model_tables, tables_ci))
    findings.extend(_check_join_targets(model_tables, ref_to_table, columns_ci))
    findings.extend(_check_column_ids(model.get("columns") or [], ref_to_table, columns_ci))
    return findings
