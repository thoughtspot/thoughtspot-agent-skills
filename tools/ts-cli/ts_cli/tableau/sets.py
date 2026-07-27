"""Tableau Set -> ThoughtSpot cohort (`*.cohort.tml`) TML assembly (BL-067 part 2).

Pure functions, no I/O — mirrors `ts_cli.tableau.tables`/`ts_cli.tableau.liveboard`'s
shape. Consumes one classified Set spec from `ts_cli.tableau.twb.extract_sets` and
emits the exact TML shape documented in:
  - `agents/cli/ts-convert-from-tableau/references/step-5-tml-generation.md`
    "Tableau Sets -> ThoughtSpot column sets (Phase 2a/2b/2c)"
  - `agents/shared/schemas/thoughtspot-sets-tml.md`

Every rule below is a literal transcription of those docs — do not invent a mapping
that isn't stated there. Each builder returns ``(cohort_tml_or_None, [log_lines])``;
``None`` means the set is untranslatable/empty and should be omitted, per the exact
log line the docs specify for that case.
"""
from __future__ import annotations

import re
from typing import Optional

# The three report tiers audit mode (BL-088) surfaces — see
# agents/cli/ts-convert-from-tableau/references/audit-mode-report.md's
# "Tableau Sets" table: Native/column set, Query set, Partial/deferred.
_COLUMN_SET_TYPES = {"static", "except_members", "intersect_members"}
_QUERY_SET_TYPES = {"topn", "except_topn", "condition", "mixed"}
_DEFERRED_TYPES = {"set_control", "unclassified"}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _worksheet_block(model_name: str, model_obj_id: Optional[str]) -> dict:
    """The `worksheet:` binding block — `id`/`name` = model display name.

    `obj_id` is included only when the caller has a real one to give (e.g. an
    already-imported model being repointed). On a fresh GENERATE-mode build the
    model doesn't have one yet — omit it, the same documented precedent as a
    fresh `model_tables[]` cross-reference (step-5-tml-generation.md: "obj_id is
    optional on fresh import — omit it unless repointing an existing model").
    """
    block: dict[str, str] = {"id": model_name, "name": model_name}
    if model_obj_id:
        block["obj_id"] = model_obj_id
    return block


def _filter_value_kind(datatype: Optional[str]) -> str:
    """Raw Tableau datatype -> cohort `filter_value_type`, per step-5-tml-
    generation.md: "Match filter_value_type to the anchor's type — text ->
    STRING; a numeric calc anchor ... -> DOUBLE; a date anchor -> DATE_FILTER."""
    dt = (datatype or "").strip().lower()
    if dt in ("integer", "real"):
        return "DOUBLE"
    if dt in ("date", "datetime"):
        return "DATE_FILTER"
    return "STRING"


def _cast_value(value: str, value_kind: str):
    if value_kind != "DOUBLE":
        return value
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    return int(f) if f.is_integer() else f


def _member_condition(anchor: str, values: list[str], value_kind: str, operator: str) -> dict:
    """One condition dict for a member-list group (`EQ`, `combine_type: ANY`) or
    a single-excluded-value condition (`NE`, one per value, `combine_type: ALL`)."""
    if value_kind == "DATE_FILTER":
        return {
            "operator": operator, "column_name": anchor,
            "date_filter_values": list(values), "filter_value_type": "DATE_FILTER",
        }
    return {
        "operator": operator, "column_name": anchor,
        "value": [_cast_value(v, value_kind) for v in values],
        "filter_value_type": value_kind,
    }


def _split_null(members: list[str]) -> tuple[list[str], bool]:
    """(regular_members, null_present) — pulls the `"%null%"` sentinel out of a
    raw member list."""
    regular = [m for m in members if m != "%null%"]
    return regular, len(regular) != len(members)


_SIMPLE_AGG_RE = re.compile(r"^\s*([A-Za-z_]+)\s*\(\s*\[([^\]]+)\]\s*\)\s*$")


def _parse_order_expr(expr: Optional[str]) -> tuple[Optional[str], str, bool]:
    """``"SUM([Sales])"`` -> ``("Sales", "SUM", False)``. Falls back to the
    innermost bracketed column ref + SUM for a derived/conditional expression,
    flagging the simplification (dropped_nuance=True) — same rule `twb.py`'s
    extraction-side `_parse_order_expr` documents."""
    if not expr:
        return None, "SUM", False
    m = _SIMPLE_AGG_RE.match(expr)
    if m:
        return m.group(2), m.group(1).upper(), False
    cols = re.findall(r"\[([^\]]+)\]", expr)
    return (cols[-1] if cols else None), "SUM", True


# ---------------------------------------------------------------------------
# Column-set builders (Phase 2a/2c) — cohort_type: SIMPLE, GROUP_BASED
# ---------------------------------------------------------------------------

def _build_static(spec: dict, *, model_name: str, model_obj_id: Optional[str], **_) -> tuple[Optional[dict], list[str]]:
    name = spec["name"]
    anchor = spec.get("anchor_name")
    if not anchor:
        return None, [f"Set '{name}' has no resolvable anchor column — omitted."]

    regular, null_included = _split_null(spec.get("members", []))
    if not regular and not null_included:
        return None, [f"Set '{name}' has no members — omitted."]

    value_kind = _filter_value_kind(spec.get("anchor_datatype"))
    conditions = []
    if regular:
        conditions.append(_member_condition(anchor, regular, value_kind, "EQ"))
    if null_included:
        conditions.append({
            "operator": "EQ", "column_name": anchor,
            "value": ["{Null}"], "filter_value_type": "STRING",
        })

    cohort = {
        "cohort": {
            "name": name,
            "config": {
                "cohort_type": "SIMPLE",
                "cohort_grouping_type": "GROUP_BASED",
                "anchor_column_id": anchor,
                "combine_non_group_values": True,
                "null_output_value": "out",
                "groups": [{"name": "in", "combine_type": "ANY", "conditions": conditions}],
            },
            "worksheet": _worksheet_block(model_name, model_obj_id),
        }
    }
    detail = f"{len(regular)} member(s)" + (" incl. null" if null_included else "")
    log = f"Set '{name}' is a static set -> column set (GROUP_BASED, {detail}, Phase 2a)."
    if spec.get("anchor_is_calc"):
        log += f" Anchored on formula column '{anchor}' — verify the calc migrated."
    return cohort, [log]


def _build_except_members(spec: dict, *, model_name: str, model_obj_id: Optional[str], **_) -> tuple[Optional[dict], list[str]]:
    name = spec["name"]
    anchor = spec.get("anchor_name")
    if not anchor:
        return None, [f"Set '{name}' has no resolvable anchor column — omitted."]

    excluded, _null = _split_null(spec.get("members", []))
    if not excluded:
        return None, [f"Set '{name}' except-list has no non-null members — omitted."]

    value_kind = _filter_value_kind(spec.get("anchor_datatype"))
    conditions = [
        _member_condition(anchor, [m], value_kind, "NE")
        for m in excluded
    ]
    cohort = {
        "cohort": {
            "name": name,
            "config": {
                "cohort_type": "SIMPLE",
                "cohort_grouping_type": "GROUP_BASED",
                "anchor_column_id": anchor,
                "combine_non_group_values": True,
                "null_output_value": "out",
                "groups": [{"name": "in", "combine_type": "ALL", "conditions": conditions}],
            },
            "worksheet": _worksheet_block(model_name, model_obj_id),
        }
    }
    log = (
        f"Set '{name}' is an except-of-member-list set -> column set "
        f"(GROUP_BASED via NE, excluding {len(excluded)} member(s), Phase 2a) — flag for review."
    )
    return cohort, [log]


def _build_intersect_members(spec: dict, *, model_name: str, model_obj_id: Optional[str], **_) -> tuple[Optional[dict], list[str]]:
    name = spec["name"]
    common = spec.get("members", [])
    if not common:
        return None, [f"Set '{name}' intersect yields zero common members — omitted."]
    anchor = spec.get("anchor_name")
    if not anchor:
        return None, [f"Set '{name}' has no resolvable anchor column — omitted."]

    value_kind = _filter_value_kind(spec.get("anchor_datatype"))
    conditions = [_member_condition(anchor, common, value_kind, "EQ")]
    cohort = {
        "cohort": {
            "name": name,
            "config": {
                "cohort_type": "SIMPLE",
                "cohort_grouping_type": "GROUP_BASED",
                "anchor_column_id": anchor,
                "combine_non_group_values": True,
                "null_output_value": "out",
                "groups": [{"name": "in", "combine_type": "ANY", "conditions": conditions}],
            },
            "worksheet": _worksheet_block(model_name, model_obj_id),
        }
    }
    log = (
        f"Set '{name}' is an intersect of two member lists -> column set "
        f"(GROUP_BASED, {len(common)} common members, Phase 2c) — flag for review."
    )
    return cohort, [log]


# ---------------------------------------------------------------------------
# Query-set builders (Phase 2b/2c) — cohort_type: ADVANCED, COLUMN_BASED
# ---------------------------------------------------------------------------

def _rank_formula(alias: str, measure_col: str, agg_fn: str, direction: str) -> dict:
    return {
        "id": "formula_rank", "name": "rank",
        "expr": f"rank ( {agg_fn.lower()} ( [{alias}::{measure_col}] ) , '{direction}' )",
        "properties": {"column_type": "ATTRIBUTE"},
        "was_auto_generated": False,
    }


def _topn_answer_columns_and_table(dimension: str, measure_display: str, with_rank: bool) -> tuple[list, dict]:
    cols = [{"name": dimension}, {"name": measure_display}]
    ids = [dimension, "rank", measure_display] if with_rank else [dimension, measure_display]
    table_cols = [{"column_id": dimension, "show_headline": False}]
    if with_rank:
        cols.append({"name": "rank"})
        table_cols.append({"column_id": measure_display, "show_headline": False})
        table_cols.append({"column_id": "rank", "show_headline": False})
    else:
        table_cols.append({"column_id": measure_display, "show_headline": False})
    table = {"table_columns": table_cols, "ordered_column_ids": ids, "client_state": ""}
    return cols, table


def _build_topn_static(spec: dict, *, model_name: str, model_obj_id: Optional[str],
                        anchor: str, measure_col: str, direction: str, inverted: bool) -> dict:
    """Static form (literal N, no inversion) — plain `top N`/`bottom N` keyword
    search_query, no formulas, no parameter. `inverted` never applies here: an
    "all except literal-N" set still needs the formula-pair form (a keyword
    search has no "not in top N" syntax) — see `_build_topn`'s dispatch."""
    n = spec["topn_count_literal"]
    keyword = "top" if direction == "top" else "bottom"
    # answer_columns/table use the AGGREGATED display name ("Total <measure>") —
    # search_query alone references the raw measure (doc's own worked example:
    # search_query "top 10 [Customer State] [Amount]" vs. answer_columns
    # "Total Amount").
    measure_display = f"Total {measure_col}"
    answer_columns, table = _topn_answer_columns_and_table(anchor, measure_display, with_rank=False)
    return {
        "cohort": {
            "name": spec["name"],
            "answer": {
                "tables": [{"id": model_name, "name": model_name, **({"obj_id": model_obj_id} if model_obj_id else {})}],
                "search_query": f"{keyword} {n} [{anchor}] [{measure_col}]",
                "answer_columns": answer_columns,
                "table": table,
                "display_mode": "TABLE_MODE",
            },
            "worksheet": _worksheet_block(model_name, model_obj_id),
            "config": {
                "cohort_type": "ADVANCED",
                "anchor_column_id": anchor,
                "return_column_id": anchor,
                "cohort_grouping_type": "COLUMN_BASED",
                "hide_excluded_query_values": False,
                "group_excluded_query_values": "Others",
                "pass_thru_filter": {"accept_all": False},
            },
        }
    }


def _build_topn_dynamic(spec: dict, *, model_name: str, model_obj_id: Optional[str],
                         anchor: str, measure_col: str, agg_fn: str, direction: str,
                         param_display_name_map: dict, inverted: bool) -> tuple[Optional[dict], list[str]]:
    """Dynamic form (parameter-driven N, or ANY all-except-Top-N set regardless
    of literal/param N — a keyword search can't express "not in top N")."""
    param_ref = spec.get("topn_count_param", "")
    param_name = param_display_name_map.get(param_ref, param_ref.split(".")[-1].strip("[]"))
    alias = f"{model_name}_1"
    rank_dir = "desc" if direction == "top" else "asc"
    comparator = ">" if inverted else "<="
    n_ref = f"[{alias}::{param_name}] " if "topn_count_param" in spec else f"{spec.get('topn_count_literal')} "
    filter_formula = {
        "id": "formula_filter", "name": "filter",
        "expr": f"[formula_rank] {comparator} {n_ref}",
        "was_auto_generated": False,
    }
    rank_formula = _rank_formula(alias, measure_col, agg_fn, rank_dir)
    measure_display = f"Total {measure_col}"
    answer_columns, table = _topn_answer_columns_and_table(anchor, measure_display, with_rank=True)

    cohort = {
        "cohort": {
            "name": spec["name"],
            "answer": {
                "tables": [{"id": model_name, "name": model_name, **({"obj_id": model_obj_id} if model_obj_id else {})}],
                "table_paths": [{"id": alias, "table": model_name}],
                "formulas": [filter_formula, rank_formula],
                "search_query": f"[{measure_col}] [{anchor}] [formula_rank] [formula_filter] = true",
                "answer_columns": answer_columns,
                "table": table,
                "display_mode": "TABLE_MODE",
            },
            "worksheet": _worksheet_block(model_name, model_obj_id),
            "config": {
                "cohort_type": "ADVANCED",
                "anchor_column_id": anchor,
                "return_column_id": anchor,
                "cohort_grouping_type": "COLUMN_BASED",
                "hide_excluded_query_values": True,
                "group_excluded_query_values": "Excluded values",
                "pass_thru_filter": {"accept_all": False},
            },
        }
    }
    return cohort, []


def _build_topn(spec: dict, *, model_name: str, model_obj_id: Optional[str],
                 param_display_name_map: dict, inverted: bool = False, **_) -> tuple[Optional[dict], list[str]]:
    name = spec["name"]
    anchor = spec.get("anchor_name")
    order_expr = spec.get("order_expr")
    if not anchor or not order_expr:
        return None, [f"Set '{name}' Top-N set is missing its anchor/order expression — omitted."]

    direction = spec.get("topn_direction", "top")
    measure_col, agg_fn, dropped_nuance = _parse_order_expr(order_expr)
    if not measure_col:
        return None, [f"Set '{name}' Top-N set has no resolvable ranking measure — omitted."]

    logs = []
    if inverted:
        logs.append(
            f"Set '{name}' is 'all except Top/Bottom-N' -> query set with inverted rank "
            f"filter (Phase 2c) — flag for review."
        )
    elif "topn_count_param" in spec:
        logs.append(
            f"Set '{name}' is a Top-N/Bottom-N set -> translated to a ThoughtSpot query set "
            f"(rank formula + parameter-filter, Phase 2b) — flag for review."
        )
    else:
        logs.append(
            f"Set '{name}' is a Top-N/Bottom-N set (literal N) -> translated to a ThoughtSpot "
            f"query set (top/bottom N keyword search, Phase 2b) — flag for review."
        )
    if dropped_nuance:
        logs.append(
            f"Dropped null-padding / conditional ranking — using plain {measure_col}; "
            f"verify ranking matches the Tableau set '{name}'."
        )

    # A literal, non-inverted N is the simplest form: a keyword search, no formulas.
    if not inverted and "topn_count_literal" in spec and isinstance(spec["topn_count_literal"], int):
        cohort = _build_topn_static(
            spec, model_name=model_name, model_obj_id=model_obj_id,
            anchor=anchor, measure_col=measure_col, direction=direction, inverted=inverted,
        )
        return cohort, logs

    if "topn_count_param" in spec or inverted:
        cohort, _extra = _build_topn_dynamic(
            spec, model_name=model_name, model_obj_id=model_obj_id, anchor=anchor,
            measure_col=measure_col, agg_fn=agg_fn, direction=direction,
            param_display_name_map=param_display_name_map, inverted=inverted,
        )
        return cohort, logs

    return None, [f"Set '{name}' Top-N set has neither a literal count nor a parameter — omitted."]


def _build_except_topn(spec: dict, **kwargs) -> tuple[Optional[dict], list[str]]:
    return _build_topn(spec, inverted=True, **kwargs)


def _build_condition(spec: dict, *, model_name: str, model_obj_id: Optional[str], **_) -> tuple[Optional[dict], list[str]]:
    name = spec["name"]
    anchor = spec.get("anchor_name")
    expr = spec.get("condition_expr")
    if not anchor or not expr:
        return None, [f"Set '{name}' condition-based set is missing its anchor/condition — omitted."]

    m = re.search(r"([A-Za-z_]+)\s*\(\s*\[([^\]]+)\]\s*\)\s*(.+)$", expr)
    if not m:
        return None, [f"Set '{name}' condition expression could not be parsed — omitted."]
    agg_fn, measure_col, rest = m.group(1).upper(), m.group(2), m.group(3).strip()
    formula_expr = f"{agg_fn.lower()} ( [{measure_col}] ) {rest}"

    cohort = {
        "cohort": {
            "name": name,
            "answer": {
                "tables": [{"id": model_name, "name": model_name, **({"obj_id": model_obj_id} if model_obj_id else {})}],
                "table_paths": [{"id": f"{model_name}_1", "table": model_name}],
                "formulas": [{
                    "id": "formula_condition", "name": "condition",
                    "expr": formula_expr,
                    "properties": {"column_type": "ATTRIBUTE"},
                    "was_auto_generated": False,
                }],
                # Literal per step-5-tml-generation.md's condition-based emission
                # rule: the formula reference appears once as an output column,
                # once as the "= true" filter predicate.
                "search_query": f"[{measure_col}] [{anchor}] [formula_condition] [formula_condition] = true",
                "answer_columns": [{"name": anchor}, {"name": measure_col}, {"name": "condition"}],
                "table": {
                    "table_columns": [
                        {"column_id": anchor, "show_headline": False},
                        {"column_id": measure_col, "show_headline": False},
                        {"column_id": "condition", "show_headline": False},
                    ],
                    "ordered_column_ids": [anchor, "condition", measure_col],
                    "client_state": "",
                },
                "display_mode": "TABLE_MODE",
            },
            "worksheet": _worksheet_block(model_name, model_obj_id),
            "config": {
                "cohort_type": "ADVANCED",
                "anchor_column_id": anchor,
                "return_column_id": anchor,
                "cohort_grouping_type": "COLUMN_BASED",
                "hide_excluded_query_values": True,
                "group_excluded_query_values": "Excluded values",
                "pass_thru_filter": {"accept_all": False},
            },
        }
    }
    log = (
        f"Set '{name}' is a condition-based set (condition: {expr}) -> query set with "
        f"condition formula (Phase 2c) — flag for review."
    )
    return cohort, [log]


# ---------------------------------------------------------------------------
# Mixed computed set operations (Phase 2c — multi-formula query set)
# ---------------------------------------------------------------------------

def _mixed_members_side(alias: str, anchor: str, side: dict, i: int) -> Optional[tuple]:
    """Member-list side of a mixed intersect/except -> (formulas, ref_id,
    already_inverted, measure_col). A member side never contributes a measure
    or gets comparator-inverted."""
    members = [m for m in side.get("members", []) if m != "%null%"]
    if not members:
        return None
    clause = " or ".join(f"[{alias}::{anchor}] = '{v}'" for v in members)
    fid = f"formula_members_{i}"
    formulas = [{
        "id": fid, "name": f"member_filter_{i}", "expr": clause,
        "properties": {"column_type": "ATTRIBUTE"}, "was_auto_generated": False,
    }]
    return formulas, fid, False, None


def _mixed_topn_side(alias: str, side: dict, i: int, op: str) -> Optional[tuple]:
    """Top-N side of a mixed intersect/except. Contributes a rank + a filter
    formula; when it's the "B" side of an except, the comparator itself is
    inverted (`>` instead of `<=`) so the combining step can still say "= true"
    for it — the documented Top-N-exclusion special case (distinct from a
    condition/member side, which combines via a plain "= false" instead)."""
    measure_col, agg_fn, _dropped = _parse_order_expr(side.get("order_expr"))
    if not measure_col:
        return None
    rank_dir = "desc" if side.get("topn_direction", "top") == "top" else "asc"
    rank_fid, topn_fid = f"formula_rank_{i}", f"formula_topn_{i}"
    invert = op == "except" and i == 1
    comparator = ">" if invert else "<="
    if "topn_count_param" in side:
        n_ref = f"[{alias}::{side['topn_count_param'].split('.')[-1].strip('[]')}]"
    else:
        n_ref = str(side.get("topn_count_literal"))
    formulas = [
        {
            "id": rank_fid, "name": f"rank_{i}",
            "expr": f"rank ( {agg_fn.lower()} ( [{alias}::{measure_col}] ) , '{rank_dir}' )",
            "properties": {"column_type": "ATTRIBUTE"}, "was_auto_generated": False,
        },
        {
            "id": topn_fid, "name": f"topn_filter_{i}",
            "expr": f"[{rank_fid}] {comparator} {n_ref}", "was_auto_generated": False,
        },
    ]
    return formulas, topn_fid, invert, measure_col


def _mixed_condition_side(alias: str, side: dict, i: int) -> Optional[tuple]:
    """Condition side of a mixed intersect/except. Unlike Top-N, a condition
    side is never comparator-inverted — the "except" combining rule uses plain
    "= false" for it (inversion is specifically the Top-N special case)."""
    m = re.search(r"([A-Za-z_]+)\s*\(\s*\[([^\]]+)\]\s*\)\s*(.+)$", side.get("condition_expr", ""))
    if not m:
        return None
    measure_col = m.group(2)
    fid = f"formula_cond_{i}"
    formulas = [{
        "id": fid, "name": f"condition_{i}",
        "expr": f"{m.group(1).lower()} ( [{alias}::{measure_col}] ) {m.group(3).strip()}",
        "properties": {"column_type": "ATTRIBUTE"}, "was_auto_generated": False,
    }]
    return formulas, fid, False, measure_col


def _build_one_mixed_side(alias: str, anchor: str, side: dict, i: int, op: str) -> Optional[tuple]:
    """Dispatch one side of a mixed intersect/except to its kind-specific
    builder. Returns ``(formulas, ref_id, already_inverted, measure_col)`` or
    ``None`` when the side is empty/unparsable/unrecognized."""
    kind = side.get("kind")
    if kind == "members":
        return _mixed_members_side(alias, anchor, side, i)
    if kind == "topn":
        return _mixed_topn_side(alias, side, i, op)
    if kind == "condition":
        return _mixed_condition_side(alias, side, i)
    return None


def _mixed_predicate(op: str, i: int, fid: str, already_inverted: bool) -> str:
    """Combine rule: intersect => every side "= true"; except => side 0
    "= true", side 1 "= false" UNLESS side 1 was already comparator-inverted
    (Top-N exclusion), which stays "= true" too."""
    if op == "intersect" or i == 0 or already_inverted:
        return f"[{fid}] = true"
    return f"[{fid}] = false"


def _assemble_mixed_answer(model_name: str, model_obj_id: Optional[str], alias: str,
                            anchor: str, measure_col: Optional[str],
                            formulas: list[dict], search_query: str) -> dict:
    answer_columns = [{"name": anchor}] + ([{"name": measure_col}] if measure_col else []) + [
        {"name": f["name"]} for f in formulas
    ]
    table_columns = [{"column_id": anchor, "show_headline": False}] + (
        [{"column_id": measure_col, "show_headline": False}] if measure_col else []
    )
    ordered_ids = [anchor] + ([measure_col] if measure_col else [])
    return {
        "tables": [{"id": model_name, "name": model_name, **({"obj_id": model_obj_id} if model_obj_id else {})}],
        "table_paths": [{"id": alias, "table": model_name}],
        "formulas": formulas,
        "search_query": search_query,
        "answer_columns": answer_columns,
        "table": {"table_columns": table_columns, "ordered_column_ids": ordered_ids, "client_state": ""},
        "display_mode": "TABLE_MODE",
    }


def _build_mixed(spec: dict, *, model_name: str, model_obj_id: Optional[str], **_) -> tuple[Optional[dict], list[str]]:
    """Phase 2c "computed set operations" — a member-list/condition/Top-N side
    combined with another via intersect/except, per step-5-tml-generation.md's
    composition + combining tables. Shallow (one level) only: a side that is
    itself a nested set-op is flagged, not recursively decomposed (the docs
    themselves call deep nesting a "flag prominently", not a mandatory-recurse,
    case)."""
    name = spec["name"]
    op = spec.get("mixed_op")
    sides = spec.get("sides") or []
    anchor = spec.get("anchor_name")
    if len(sides) != 2 or any(s is None for s in sides) or not anchor:
        return None, [
            f"Set '{name}' is a nested set operation — verify the combined filter "
            f"logic; not auto-converted, flag for review."
        ]

    alias = f"{model_name}_1"
    formulas: list[dict] = []
    ref_ids: list[tuple[str, bool]] = []
    measure_col = None
    for i, side in enumerate(sides):
        built = _build_one_mixed_side(alias, anchor, side, i, op)
        if built is None:
            return None, [f"Set '{name}' has an empty, unparsable, or unrecognized side — omitted."]
        side_formulas, fid, invert, side_measure = built
        formulas.extend(side_formulas)
        ref_ids.append((fid, invert))
        measure_col = side_measure or measure_col

    predicates = [_mixed_predicate(op, i, fid, inv) for i, (fid, inv) in enumerate(ref_ids)]
    formula_refs = " ".join(f"[{fid}]" for fid, _ in ref_ids)
    measure_ref = f"[{measure_col}] " if measure_col else ""
    search_query = re.sub(
        r"\s+", " ",
        f"{measure_ref}[{anchor}] {formula_refs} {' '.join(predicates)}".strip(),
    )

    cohort = {
        "cohort": {
            "name": name,
            "answer": _assemble_mixed_answer(model_name, model_obj_id, alias, anchor, measure_col, formulas, search_query),
            "worksheet": _worksheet_block(model_name, model_obj_id),
            "config": {
                "cohort_type": "ADVANCED",
                "anchor_column_id": anchor,
                "return_column_id": anchor,
                "cohort_grouping_type": "COLUMN_BASED",
                "hide_excluded_query_values": True,
                "group_excluded_query_values": "Excluded values",
                "pass_thru_filter": {"accept_all": False},
            },
        }
    }
    log = (
        f"Set '{name}' is a computed set operation ({op} of "
        f"{sides[0]['kind']} and {sides[1]['kind']}) -> query set with "
        f"{len(formulas)} formulas (Phase 2c) — flag for review."
    )
    return cohort, [log]


# ---------------------------------------------------------------------------
# Untranslatable
# ---------------------------------------------------------------------------

def _build_set_control(spec: dict, **_) -> tuple[None, list[str]]:
    name = spec["name"]
    anchor = spec.get("anchor_name") or spec.get("anchor_ref") or "?"
    return None, [
        f"Set '{name}' is a dynamic Set Control -> mapped to a filter on {anchor} "
        "(anchor calc migrated as a column); its IF-[Set] scaffolding calcs were "
        "collapsed into measure+filter, not migrated."
    ]


def _build_unclassified(spec: dict, **_) -> tuple[None, list[str]]:
    return None, [f"Set '{spec.get('name')}' has an unrecognized structure — omitted."]


_BUILDERS = {
    "static": _build_static,
    "except_members": _build_except_members,
    "intersect_members": _build_intersect_members,
    "topn": _build_topn,
    "except_topn": _build_except_topn,
    "condition": _build_condition,
    "mixed": _build_mixed,
    "set_control": _build_set_control,
    "unclassified": _build_unclassified,
}


def build_cohort_tml(
    set_spec: dict,
    *,
    model_name: str,
    model_obj_id: Optional[str] = None,
    param_display_name_map: Optional[dict] = None,
) -> tuple[Optional[dict], list[str]]:
    """Build one ``*.cohort.tml`` dict from a parsed Tableau Set spec
    (``ts_cli.tableau.twb.extract_sets``).

    Returns ``(cohort_tml, log_lines)``. ``cohort_tml`` is ``None`` for an
    untranslatable/empty set (set control, empty intersect, unparsable
    condition, ...) — always paired with the documented log line explaining why.
    """
    builder = _BUILDERS.get(set_spec.get("set_type"), _build_unclassified)
    return builder(
        set_spec,
        model_name=model_name,
        model_obj_id=model_obj_id,
        param_display_name_map=param_display_name_map or {},
    )


# ---------------------------------------------------------------------------
# Audit classification (BL-088) — reuses the SAME `set_type` twb.py already
# computed; no re-derivation, "one detector" per the BL-088 approach note.
# ---------------------------------------------------------------------------

def classify_sets(sets: list[dict]) -> dict:
    """Tier each parsed Set for audit mode's "Tableau Sets" report (see
    agents/cli/ts-convert-from-tableau/references/audit-mode-report.md).

    Returns ``{"sets": [{"name", "set_type", "tier"}], "tier_counts": {...}}``
    with exactly the three documented tiers: ``column_set`` (Native / column
    set — static + member-intersect), ``query_set`` (Top-N, condition,
    all-except-Top-N, mixed ops), ``deferred`` (set controls/actions + an
    empty member-intersect, which structurally can't emit a cohort either).
    """
    classified = []
    counts: dict[str, int] = {"column_set": 0, "query_set": 0, "deferred": 0}
    for s in sets:
        set_type = s.get("set_type")
        if set_type == "intersect_members" and not s.get("members"):
            tier = "deferred"
        elif set_type in _COLUMN_SET_TYPES:
            tier = "column_set"
        elif set_type in _QUERY_SET_TYPES:
            tier = "query_set"
        else:
            tier = "deferred"
        counts[tier] += 1
        classified.append({"name": s.get("name"), "set_type": set_type, "tier": tier})
    return {"sets": classified, "tier_counts": counts}
