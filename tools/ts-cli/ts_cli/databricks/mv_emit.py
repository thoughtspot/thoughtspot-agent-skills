"""ThoughtSpot Model TML -> Databricks Metric View YAML (reverse orchestrator).

Assembly/orchestration only: fact-table detection, cross-reference role
resolution, the two emission passes (dimensions then measures), dangling-ref
cascade, duplicate-name guard, and build_metric_view (the top-level entry
point behind `ts databricks build-mv`). Column-index/resolver foundations
live in mv_emit_base.py, join assembly in mv_emit_joins.py, column
classification + non-window/LOD emitters in mv_emit_classify.py, and
window-measure emission in mv_emit_window.py -- all four split out of this
module under the file-size gate (tools/validate/check_file_size.py). Every
name moved out is re-exported below so existing callers/tests (and the
Genie-vendored closure) keep importing from `ts_cli.databricks.mv_emit`
unchanged.

Pure: stdlib + (PyYAML only in build_view). No I/O here.
"""
from __future__ import annotations
import re
from typing import Callable

from ts_cli.databricks.mv_emit_expr import parse_formula, UntranslatableError
# Foundation (column index / resolvers / [ref] resolution) -- split into
# mv_emit_base.py under the file-size gate; re-exported below.
from ts_cli.databricks.mv_emit_base import (
    to_snake, build_column_index, make_col_resolver, resolve_refs)
# Join assembly -- split into mv_emit_joins.py under the file-size gate;
# re-exported below.
from ts_cli.databricks.mv_emit_joins import build_joins
# Column classification + non-window/LOD emitters -- split into
# mv_emit_classify.py under the file-size gate; re-exported below.
from ts_cli.databricks.mv_emit_classify import (
    classify_column, emit_dimension, emit_measure, emit_filter, emit_lod_dimension,
    _find_formula, _formula_expr, _child_nodes, _is_boolean_top,
    _finalize_column, _raise_unresolved_ref, _IF_FAMILY_FNS, _LOD_FNS)
# Window-measure emission (Task 9) lives in mv_emit_window.py -- split out
# under the file-size gate (tools/validate/check_file_size.py). Re-exported
# here so existing callers/tests keep importing from mv_emit; that module
# late-imports the mv_emit internals it needs to avoid a circular import
# (mirrors the mv_translate.py / mv_window_translate.py split).
from ts_cli.databricks.mv_emit_window import (
    emit_window_measure, synthesize_period_dim, _moving_range, _join_target_tables)


# --- Task 10: fact-table detection + cross-reference resolver + -----------
# build_metric_view assembly. Wires Tasks 6-9 into one MV yaml_doc for a
# single fact table (the multi-fact split loops over detect_fact_tables'
# result, calling build_metric_view once per fact).

def _first_col_ref_table(node) -> str | None:
    """DFS a formula AST for the first {'node':'col'} reference's table,
    walking children in the same order as `_child_nodes` (mirrors how a
    ThoughtSpot formula reads left-to-right). Returns None if the AST has no
    direct physical column reference (e.g. it only chains through other
    formulas via [ref] nodes).
    """
    if not isinstance(node, dict):
        return None
    if node.get("node") == "col":
        return node["table"]
    for child in _child_nodes(node):
        table = _first_col_ref_table(child)
        if table is not None:
            return table
    return None


def _measure_column_table(col: dict, model: dict) -> str | None:
    """A MEASURE column's owning table: its own column_id prefix if physical,
    else the table its formula's first physical [T::col] ref resolves to
    (per the Task 10 brief's 'primary/first' rule). Returns None if neither
    is available (e.g. an untranslatable or all-cross-reference formula) --
    such a column simply contributes no table to detect_fact_tables.
    """
    cid = col.get("column_id")
    if cid:
        return cid.split("::", 1)[0]
    formula_id = col.get("formula_id")
    if not formula_id:
        return None
    formula = _find_formula(model, formula_id)
    if formula is None:
        return None
    try:
        ast = parse_formula(formula["expr"])
    except UntranslatableError:
        return None
    return _first_col_ref_table(ast)


def detect_fact_tables(model: dict) -> list[str]:
    """Tables carrying >= 1 MEASURE column that are also join ROOTS -- i.e. NOT the join
    target of any other table (`_join_target_tables`) -- in `model_tables` order.

    A physical column's table is its `column_id` prefix; a formula column's table is the
    table its first physical `[T::col]` ref resolves to (that DFS can mis-attribute a
    measure to a foreign table referenced only inside a filter/condition argument -- see
    `_measure_column_table`'s docstring). The join-root filter below removes the resulting
    OVER-detection: a mis-attributed measure lands on some OTHER table's excluded
    join-target dimension. It can still UNDER-detect a fact whose ONLY measures are
    condition-first formula measures (e.g. a lone `sum_if(diff_months([DIM::d], ...),
    [FACT::v])` with no physical measure) -- such a model needs to be built with an
    explicit `--source-table`.
    """
    table_order = [mt["name"] for mt in model.get("model_tables", [])]
    join_targets = _join_target_tables(model)

    found: list[str] = []
    for col in model.get("columns", []):
        props = col.get("properties") or {}
        if props.get("column_type") != "MEASURE":
            continue
        table = _measure_column_table(col, model)
        if table and table not in found:
            found.append(table)

    roots = [t for t in found if t not in join_targets]
    ordered = [t for t in table_order if t in roots]
    ordered += [t for t in roots if t not in table_order]
    return ordered


# `formula_roles` (despite the name, kept for interface stability per the
# Task 10 brief) actually maps ANY emitted column's display name -> its final
# MV role, not just formula-backed ones -- a ThoughtSpot [ref] can point at a
# physical MEASURE column just as easily as a formula (see the worked
# example's `safe_divide([Quantity], [Category Quantity])`, where `Quantity`
# is a physical column). Only two target roles are supported, matching the
# brief's stated scope: "measure" -> MEASURE(x), "lod_dimension" -> ANY_VALUE(y).
# A plain (non-LOD) dimension is not yet a valid ref target here -- omitted
# from the map, so referencing one raises UntranslatableError (fail loud
# rather than silently wrong); see the Task 10 report for this scope note.
_REF_ROLE_FN = {"measure": "MEASURE", "lod_dimension": "ANY_VALUE"}


def make_ref_resolver(formula_roles: dict) -> Callable[[dict], str]:
    """Build a ref_resolver for `resolve_refs`/emit_* from this MV's own
    column classification. A ref to a name classified "measure" emits
    `MEASURE(<snake>)`; "lod_dimension" emits `ANY_VALUE(<snake>)`; any other
    (or missing) name raises UntranslatableError.
    """
    def resolver(node: dict) -> str:
        name = node["name"]
        fn = _REF_ROLE_FN.get(formula_roles.get(name))
        if fn is None:
            raise UntranslatableError(
                f"unresolved reference [{name}]: no measure or LOD dimension named "
                f"{name!r} among this Metric View's classified columns")
        return f"{fn}({to_snake(name)})"
    return resolver


def _window_kind(col: dict, model: dict) -> str:
    """"lod" (dimension window function) or "measure" (window: measure) for
    a role=="window" classified column -- classify_column routes both to the
    same "window" role (Task 9), so build_metric_view needs this finer split
    to know whether to emit_lod_dimension or emit_window_measure.
    """
    ast = parse_formula(_formula_expr(col, model))
    fn = ast.get("fn") if ast.get("node") == "call" else None
    return "lod" if fn in _LOD_FNS else "measure"


def _classify_all_columns(model: dict) -> list[tuple[dict, dict]]:
    """Classify every model column, catching classify-time UntranslatableError
    (bad/unparseable formula) as a role=="error" entry rather than aborting --
    per-formula errors must not abort the whole MV.
    """
    classified: list[tuple[dict, dict]] = []
    for col in model.get("columns", []):
        try:
            result = classify_column(col, model)
            if result["role"] == "window":
                result = dict(result)
                result["window_kind"] = _window_kind(col, model)
        except UntranslatableError as exc:
            result = {"role": "error", "reason": str(exc)}
        classified.append((col, result))
    return classified


def _build_ref_roles(classified: list[tuple[dict, dict]]) -> dict:
    """Build the name -> role map `make_ref_resolver` needs, from every
    column's FINAL routed kind (not just formula columns -- see the
    `_REF_ROLE_FN` docstring above): "measure" for a plain or window measure,
    "lod_dimension" for an LOD-formula dimension. Must be built from ALL
    classified columns before any expr is emitted, so a formula can forward-
    or back-reference any other column in this MV.
    """
    roles: dict = {}
    for col, result in classified:
        name = col.get("name")
        role = result.get("role")
        if role == "measure" or (role == "window" and result.get("window_kind") == "measure"):
            roles[name] = "measure"
        elif role == "window" and result.get("window_kind") == "lod":
            roles[name] = "lod_dimension"
    return roles


def _record_skip(skipped: list, warnings: list, name, role: str, reason: str) -> None:
    """Record a per-formula/per-column omission uniformly: every skip gets
    BOTH a structured skipped[] entry and a human-readable warning (required
    follow-up: "every skipped column" must surface in warnings for the
    SKILL's checkpoint).
    """
    skipped.append({"name": name, "role": role, "reason": reason})
    warnings.append(f"skipped {role} column {name!r}: {reason}")


def _route_filter(col: dict, model: dict, col_resolver, ref_resolver,
                   dimensions: list, filter_exprs: list, warnings: list) -> None:
    """Route a role=="filter" classified column. classify_column's filter
    detection accepts EITHER a boolean-shaped expr OR a name containing
    "filter" (ts-to-databricks-rules.md "Filter Generation" > Detection) --
    but only a genuinely boolean expr may land in the MV's `filter:` field
    (required follow-up #1). A name-only match that isn't boolean is
    rerouted to a dimension (always a dimension, never a measure -- filter
    classification only ever fires on ATTRIBUTE columns) instead of being
    silently dropped or wrongly emitted as a global filter. Either path
    surfaces a warning (required follow-up #3) so the SKILL checkpoint can
    ask the user to confirm the routing. Raises UntranslatableError on
    failure -- caller records the skip.
    """
    name = col.get("name")
    ast = parse_formula(_formula_expr(col, model))
    if _is_boolean_top(ast):
        filter_exprs.append(emit_filter(col, col_resolver, ref_resolver, model))
        warnings.append(
            f"formula {name!r} classified as a row filter (boolean) — confirm this is "
            "intended as a global MV filter rather than a dimension")
    else:
        dimensions.append(emit_dimension(col, col_resolver, ref_resolver, model))
        warnings.append(
            f"formula {name!r} name suggests a filter but is not boolean-shaped — "
            "emitted as a dimension instead; confirm this routing")


def _merge_extra_dims(dimensions: list, extra_dims: list) -> None:
    """Append a window measure's synthesized order-dim(s) to `dimensions`,
    deduped by name -- emit_window_measure already prefers reusing a matching
    existing dim over synthesizing a new one (required follow-up #4), so
    `extra_dims` here is only ever genuinely-new dims; this guards against
    re-adding the same synthesized dim twice across multiple window measures.
    """
    existing_names = {d["name"] for d in dimensions}
    for d in extra_dims:
        if d["name"] not in existing_names:
            dimensions.append(d)
            existing_names.add(d["name"])


def _combine_filters(filter_exprs: list) -> str | None:
    """AND-join multiple filter formulas into the MV's single `filter:`
    string, parenthesizing each when there's more than one (so a top-level
    OR inside any individual filter can't leak across the AND join).
    """
    if not filter_exprs:
        return None
    if len(filter_exprs) == 1:
        return filter_exprs[0]
    return " AND ".join(f"({e})" for e in filter_exprs)


# _EMITTED_* avoids a vendoring name clash with mv_expr.py's own _MEASURE_REF_RE (BL-063 PR 14).
_EMITTED_MEASURE_REF_RE = re.compile(r"MEASURE\(([A-Za-z0-9_]+)\)")
_EMITTED_ANY_VALUE_REF_RE = re.compile(r"ANY_VALUE\(([A-Za-z0-9_]+)\)")


def _referenced_names(expr: str) -> set:
    """Every MEASURE(name)/ANY_VALUE(name) machine-name reference inside an
    already-emitted `expr` string (the raw-SQL shape `make_ref_resolver`
    substitutes in -- see `resolve_refs`'s docstring)."""
    text = expr or ""
    return set(_EMITTED_MEASURE_REF_RE.findall(text)) | set(_EMITTED_ANY_VALUE_REF_RE.findall(text))


def _cascade_skip_dangling_refs(dimensions: list, measures: list,
                                 skipped: list, warnings: list) -> None:
    """Remove any emitted dimension/measure whose `expr` references a
    MEASURE()/ANY_VALUE() machine name that is not ITSELF among the emitted
    columns, repeating to a fixed point.

    `_build_ref_roles` classifies every column's ref-target role BEFORE any
    expr is emitted (required so formulas can forward/back-reference each
    other), so a formula can classify as measure/lod_dimension yet still fail
    during its OWN emission (emit_sql raises UntranslatableError) and land in
    `skipped` -- a sibling formula referencing that name by
    MEASURE()/ANY_VALUE() has already resolved and emitted successfully by
    that point, leaving a reference to a name in neither `dimensions:` nor
    `measures:` (a silently invalid MV). This must run AFTER both emission
    passes, once the full dimensions/measures lists are known.

    Runs to a fixed point because removing one dangling column can itself
    dangle another that referenced IT (a transitive chain, e.g. C references
    B references A where A failed emission) -- a pass that removes nothing
    terminates the loop, so this can never spin forever.
    """
    while True:
        emitted = {d["name"] for d in dimensions} | {m["name"] for m in measures}
        removed_any = False
        for coll_name, items in (("dimension", dimensions), ("measure", measures)):
            for item in list(items):
                missing = _referenced_names(item.get("expr", "")) - emitted
                if not missing:
                    continue
                items.remove(item)
                missing_list = ", ".join(repr(n) for n in sorted(missing))
                reason = (f"references missing dependency {missing_list} "
                          "(that column failed emission or was itself skipped)")
                _record_skip(skipped, warnings, item.get("display_name"), coll_name, reason)
                removed_any = True
        if not removed_any:
            break


def _check_duplicate_names(dimensions: list, measures: list) -> None:
    """Raise ValueError on a duplicate emitted `display_name` OR a duplicate
    emitted machine `name:` across all dimensions+measures.

    The original display_name-only check misses a real failure mode: two
    distinct display names can collapse to the SAME `to_snake()` machine name
    (e.g. "Order-ID" and "Order ID" both -> "order_id"), silently producing
    two MV columns sharing one `name:` key -- an invalid Metric View that
    imports without error but only exposes one of the two columns. Checked in
    the same pass as the display_name check (not a separate loop) so both
    collisions are caught with one walk of dimensions+measures.
    """
    seen_display: dict = {}
    seen_name: dict = {}  # machine name -> (coll_name, display_name) that claimed it
    for coll_name, items in (("dimension", dimensions), ("measure", measures)):
        for item in items:
            dn = item.get("display_name")
            if dn in seen_display:
                raise ValueError(
                    f"duplicate display_name {dn!r} across emitted columns "
                    f"({seen_display[dn]} and {coll_name})")
            seen_display[dn] = coll_name

            name = item.get("name")
            if name in seen_name:
                prev_coll, prev_dn = seen_name[name]
                raise ValueError(
                    f"duplicate machine name {name!r} across emitted columns: "
                    f"display_name {prev_dn!r} ({prev_coll}) and {dn!r} ({coll_name}) "
                    "both collapse to the same snake_case name")
            seen_name[name] = (coll_name, dn)


def _source_db_table(tables: list[dict], source_table: str) -> str:
    for t in tables:
        if t["table"]["name"] == source_table:
            return t["table"]["db_table"]
    raise ValueError(f"source_table {source_table!r} not found in tables")


def _emit_dimensions_pass(classified: list[tuple[dict, dict]], model: dict,
                           col_resolver, ref_resolver,
                           skipped: list, warnings: list) -> tuple[list[dict], list[str]]:
    """Pass 1 of 2: plain dimensions, LOD dimensions, filter routing (which
    may itself append a dimension), and unknown/error omission -- everything
    that does NOT need the full dimensions list up front. Must run to
    completion before the measures pass, since window measures need this
    pass's dims available for order-dim reuse (required follow-up #4).
    """
    dimensions: list = []
    filter_exprs: list = []
    for col, result in classified:
        role = result.get("role")
        name = col.get("name")
        try:
            if role == "dimension":
                dimensions.append(emit_dimension(col, col_resolver, ref_resolver, model))
            elif role == "unknown":
                _record_skip(skipped, warnings, name, role, result.get("reason", ""))
            elif role == "error":
                _record_skip(skipped, warnings, name, role, result.get("reason", ""))
            elif role == "filter":
                _route_filter(col, model, col_resolver, ref_resolver,
                               dimensions, filter_exprs, warnings)
            elif role == "window" and result.get("window_kind") == "lod":
                dimensions.append(emit_lod_dimension(col, col_resolver, ref_resolver, model))
        except UntranslatableError as exc:
            _record_skip(skipped, warnings, name, role, str(exc))
    return dimensions, filter_exprs


def _emit_measures_pass(classified: list[tuple[dict, dict]], model: dict,
                         col_resolver, ref_resolver, dimensions: list,
                         skipped: list, warnings: list) -> list[dict]:
    """Pass 2 of 2: plain measures and window measures, using the fully-built
    `dimensions` list (from the dimensions pass) for order-dim reuse. Grows
    `dimensions` in place as window measures synthesize new order dims, so
    later window measures in this same pass can reuse earlier ones (matches
    the worked example's Monthly/Prior Month Revenue sharing one order_month
    dim).
    """
    measures: list = []
    for col, result in classified:
        role = result.get("role")
        name = col.get("name")
        try:
            if role == "measure":
                measures.append(emit_measure(col, col_resolver, ref_resolver, model))
            elif role == "window" and result.get("window_kind") == "measure":
                measure, extra_dims = emit_window_measure(
                    col, col_resolver, ref_resolver, model, existing_dims=dimensions)
                measures.append(measure)
                _merge_extra_dims(dimensions, extra_dims)
        except UntranslatableError as exc:
            _record_skip(skipped, warnings, name, role, str(exc))
    return measures


def build_metric_view(model: dict, tables: list[dict], source_table: str, *,
                       catalog: str, schema: str) -> dict:
    """Assemble one Databricks Metric View YAML doc for `source_table`,
    orchestrating Tasks 6-9: column index + joins (Task 6/7) -> classify
    every model column (Task 8/9) -> role-aware ref resolver (this task) ->
    route each column to its emitter -> cascade-skip any column left with a
    dangling MEASURE()/ANY_VALUE() reference (review fix wave, see
    `_cascade_skip_dangling_refs`) -> assemble the MV dict in schema key
    order. Returns `{"yaml_doc": dict, "skipped": list[dict], "warnings": list[str]}`.

    A column belonging to a different fact table's join tree (relevant only
    in a multi-fact model) has no resolvable dot-path here and naturally
    lands in `skipped` via its own UntranslatableError -- callers looping
    over `detect_fact_tables` don't need to pre-filter `model["columns"]`.
    """
    skipped: list = []
    warnings: list = []

    col_index = build_column_index(model, tables)
    mv_joins, dot_path_by_table = build_joins(model, tables, source_table)
    col_resolver = make_col_resolver(col_index, source_table, dot_path_by_table)

    classified = _classify_all_columns(model)
    ref_resolver = make_ref_resolver(_build_ref_roles(classified))

    dimensions, filter_exprs = _emit_dimensions_pass(
        classified, model, col_resolver, ref_resolver, skipped, warnings)
    measures = _emit_measures_pass(
        classified, model, col_resolver, ref_resolver, dimensions, skipped, warnings)

    _cascade_skip_dangling_refs(dimensions, measures, skipped, warnings)
    _check_duplicate_names(dimensions, measures)

    yaml_doc: dict = {"version": "1.1"}
    comment = model.get("description")
    if comment:
        yaml_doc["comment"] = comment
    yaml_doc["source"] = f"{catalog}.{schema}.{_source_db_table(tables, source_table)}"
    if mv_joins:
        yaml_doc["joins"] = mv_joins
    yaml_doc["dimensions"] = dimensions
    yaml_doc["measures"] = measures
    combined_filter = _combine_filters(filter_exprs)
    if combined_filter:
        yaml_doc["filter"] = combined_filter

    return {"yaml_doc": yaml_doc, "skipped": skipped, "warnings": warnings}
