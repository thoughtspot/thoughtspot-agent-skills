"""Formula finalisation shared by BOTH dbt Model builders.

`ts dbt build-model` (manifest.build_model_tml_from_manifest) and
`ts dbt-export build-model` (model_from_schema_yml.build_model_tml_from_schema_yml)
both assemble Model TML directly rather than through `model_builder.build_model_tml`,
so neither inherited the shared `formula_common` passes every other converter
runs. 2026-10 (PR #506 review, BL-217 — decision: adopt, not exempt): both now
finish through this module, which calls the shared helpers rather than restating
them (formula_common: "Never fork these into a platform module; import them").

How each helper maps onto dbt's existing, live-verified collision policy:

* `resolve_name_collisions` — its column-vs-formula rule ("a column named like a
  formula is dropped") is the DETECTOR here, not the policy. dbt's policy is
  stricter and stays as it was: an *inferred* column (typed from catalog.json, no
  schema.yml entry to hang a `ts_display_name` on) is RENAMED with its table
  prefix, because dropping it loses a column; a *declared* column is never passed
  in, so it stays in place for the callers' `find_display_name_collisions`
  refusal. Names are compared lower-cased because ThoughtSpot compares Model
  column names case-insensitively. Its formula-vs-parameter rule is vacuous: dbt
  emits no parameters.
* `fix_double_aggregation` — collapses `sum ( [formula_X] )` to `[formula_X]` when
  X is already aggregated. Keyed by formula ID (minus `formula_`), not by display
  name, because `tags._formula_id` escapes brackets, so the two can differ. Only
  the `sum` form is passed in: the helper also collapses count/average/min/max,
  which changes what a hand-written formula means, so those are reported instead
  (`find_reaggregation_kept`) and left for the user to decide.

Pure functions, no I/O.
"""
from __future__ import annotations

import re
from typing import Callable

from ts_cli.formula_common import (
    count_distinct_columns_to_formulas, expr_is_aggregated, fix_double_aggregation,
    resolve_name_collisions)

FORMULA_ID_PREFIX = "formula_"

# A `[formula_…]` id reference. Brackets never occur inside an id — tags._formula_id
# escapes them — so the shortest match is the whole reference.
_FORMULA_REF_RE = re.compile(r"\[(formula_[^\[\]]+)\]")


def rename_colliding_columns(
    columns: list[dict],
    formula_columns: list[dict],
    renamable_ids: set[str],
    new_name: Callable[[str], str],
) -> list[dict]:
    """Rename each renamable physical column whose display name a formula uses.

    `columns` are the physical `columns[]` docs (mutated in place); only those
    whose `column_id` is in `renamable_ids` are considered. Returns
    `[{"column_id", "from", "to"}]` for the caller's diagnostics.
    """
    candidates = [{"name": c["name"].lower(), "column_id": c["column_id"]}
                  for c in columns if c.get("column_id") in renamable_ids]
    if not candidates:
        return []
    kept, _formulas, _rename_map = resolve_name_collisions(
        candidates, [{"name": f["name"].lower()} for f in formula_columns], [])
    kept_ids = {c["column_id"] for c in kept}
    renames: list[dict] = []
    for col in columns:
        cid = col.get("column_id")
        if cid in renamable_ids and cid not in kept_ids:
            to = new_name(cid)
            renames.append({"column_id": cid, "from": col["name"], "to": to})
            col["name"] = to
    return renames


def print_double_aggregation(changes: list) -> None:
    """stderr line per formula the collapse rewrote — never a silent change."""
    import sys
    for d in changes:
        print(f"  Formula {d['formula']!r}: re-aggregation of an already-aggregated formula "
              f"removed — {d['from']}  →  {d['to']}", file=sys.stderr)


def print_reaggregation_kept(kept: list) -> None:
    """stderr warning per non-sum re-aggregation left as the user wrote it."""
    import sys
    for d in kept:
        print(f"  WARNING: Formula {d['formula']!r}: {d['wrapper']} over the already-aggregated "
              f"[formula_{d['ref']}] was left as written ({d['expr']}). Check it means what "
              f"you intend; only sum is collapsed automatically.", file=sys.stderr)


# 2026-10 (PR #506 review round 3, blocker 2): the shared fix_double_aggregation
# also collapses count/average/min/max wrappers, but for hand-written ts_formula
# text only sum is close to equivalent — count ( [formula_Rev] ) -> [formula_Rev]
# is a different metric. So dbt feeds it the sum-wrapped references alone, and
# reports every other wrapper over an aggregated formula untouched.
_SUM_WRAPPED_REF_RE = re.compile(r"\bsum\s*\(\s*\[formula_[^\]]+\]\s*\)", re.IGNORECASE)
_OTHER_WRAPPED_REF_RE = re.compile(
    r"\b(count|average|max|min)\s*\(\s*\[formula_([^\]]+)\]\s*\)", re.IGNORECASE)


def _formula_exprs(formulas: list[dict]) -> dict[str, str]:
    return {f["id"][len(FORMULA_ID_PREFIX):]: f["expr"] for f in formulas
            if str(f.get("id", "")).startswith(FORMULA_ID_PREFIX)}


def collapse_double_aggregation(formulas: list[dict]) -> list[dict]:
    """Collapse `sum ( [formula_X] )` to `[formula_X]` when X is already
    aggregated, via `fix_double_aggregation` (formulas mutated in place).

    No other wrapper is rewritten — see `find_reaggregation_kept`.
    Returns `[{"formula", "from", "to"}]` for each expression it changed.
    """
    exprs = _formula_exprs(formulas)
    changes: list[dict] = []
    for f in formulas:
        new = _SUM_WRAPPED_REF_RE.sub(
            lambda m: fix_double_aggregation(m.group(0), exprs), f["expr"])
        if new != f["expr"]:
            changes.append({"formula": f["name"], "from": f["expr"], "to": new})
            f["expr"] = new
    return changes


def find_reaggregation_kept(formulas: list[dict]) -> list[dict]:
    """Every count/average/min/max wrapped around an already-aggregated formula,
    which `collapse_double_aggregation` deliberately leaves alone.

    Returns `[{"formula", "wrapper", "ref", "expr"}]` for the caller to report.
    """
    exprs = _formula_exprs(formulas)
    kept: list[dict] = []
    for f in formulas:
        for m in _OTHER_WRAPPED_REF_RE.finditer(f["expr"]):
            if expr_is_aggregated(exprs.get(m.group(2), "")):
                kept.append({"formula": f["name"], "wrapper": m.group(1).lower(),
                             "ref": m.group(2), "expr": f["expr"]})
    return kept


def repoint_formula_refs(formulas: list[dict], id_map: dict[str, str]) -> list[dict]:
    """Rewrite `[formula_…]` references whose id case-insensitively matches a key
    of `id_map` (lower-cased old id -> new id). Mutates in place.

    2026-10 (PR #506 review, minor 1): a MetricFlow metric supersedes a
    `ts_formula` by label, case-insensitively, but a sibling formula referencing
    the superseded id — in that case or any other (`[formula_total tips]` for
    `formula_Total Tips`) — was left pointing at an id that no longer exists
    (lint I13; ThoughtSpot parses it as search tokens). Returns
    `[{"formula", "from", "to"}]` per changed expression.
    """
    if not id_map:
        return []
    changes: list[dict] = []
    for f in formulas:
        new = _FORMULA_REF_RE.sub(
            lambda m: f"[{id_map.get(m.group(1).lower(), m.group(1))}]", f["expr"])
        if new != f["expr"]:
            changes.append({"formula": f["name"], "from": f["expr"], "to": new})
            f["expr"] = new
    return changes


def count_distinct_pass(columns: list, formulas: list, formula_col_entries: list,
                        *, enabled: bool) -> tuple:
    """`ts_aggregation: count_distinct` on a physical column → a `unique count`
    formula column of the same name (invariant I5; audit 2026-10-29, 9.2).

    ``enabled`` is False when UPDATING an existing Model: a dbt `count_distinct`
    tag is usually ThoughtSpot's own column, round-tripped by ts-convert-to-dbt, and
    turning it into a formula in place could break the Answers built on it. I5's
    round-trip exception keeps it as it is there; the lint gate reports it as
    advisory. Returns ``(columns, formulas, formula_col_entries, converted_names)``.
    """
    if not enabled:
        return columns, formulas, formula_col_entries, []
    from .tags import _formula_id   # lazy — tags imports from this package
    columns, new_f, new_cols, converted = count_distinct_columns_to_formulas(
        columns, formulas, id_fn=_formula_id)
    return columns, formulas + new_f, formula_col_entries + new_cols, converted
