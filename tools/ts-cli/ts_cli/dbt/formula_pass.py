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
  name, because `tags._formula_id` escapes brackets, so the two can differ.

Pure functions, no I/O.
"""
from __future__ import annotations

import re
from typing import Callable

from ts_cli.formula_common import fix_double_aggregation, resolve_name_collisions

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


def collapse_double_aggregation(formulas: list[dict]) -> list[dict]:
    """Apply `fix_double_aggregation` to every formula (mutated in place).

    Returns `[{"formula", "from", "to"}]` for each expression it changed.
    """
    exprs = {f["id"][len(FORMULA_ID_PREFIX):]: f["expr"] for f in formulas
             if str(f.get("id", "")).startswith(FORMULA_ID_PREFIX)}
    changes: list[dict] = []
    for f in formulas:
        new = fix_double_aggregation(f["expr"], exprs)
        if new != f["expr"]:
            changes.append({"formula": f["name"], "from": f["expr"], "to": new})
            f["expr"] = new
    return changes


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
