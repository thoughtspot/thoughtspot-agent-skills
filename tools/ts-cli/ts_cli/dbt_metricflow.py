"""MetricFlow (dbt Semantic Layer) metrics → ThoughtSpot Model formulas.

Pure functions over a compiled dbt ``manifest.json`` (schema v12, dbt Core
1.12+ / dbt Fusion — the *nested* ``semantic_model:`` spec). No I/O. Handles
both manifest dialects seen live (2026-09-08): dbt Cloud 2026.9.1 (simple
metric column at ``type_params.expr``; ratio/derived ``depends_on`` metric
nodes) and dbt Fusion local parse (column inside
``metric_aggregation_params``; ``depends_on`` the semantic model).

ThoughtSpot cannot query the dbt Semantic Layer, so MetricFlow's compiled SQL
never runs; what carries over is the *definition*. ``ts dbt build-model`` calls
:func:`translate_metrics` and appends the result to the Model's ``formulas[]``
and ``columns[]`` so one YAML metric definition drives both ``dbt sl query`` and
the ThoughtSpot Model.

Coverage (first slice — see ts-convert-from-dbt open-items.md #14):

| MetricFlow                                   | ThoughtSpot formula                         |
|----------------------------------------------|---------------------------------------------|
| simple, ``agg`` sum/average/min/max/count on a bare column | ``sum([TABLE::COL])`` etc.       |
| simple, ``agg: count_distinct``              | ``unique count([TABLE::COL])``              |
| ratio                                        | ``safe_divide([formula_num], [formula_den])``|
| derived, ``expr`` over ``input_metrics`` aliases | aliases replaced by ``[formula_id]`` refs |
| cumulative, conversion, ``filter``, offsets, SQL-expression ``expr``, median/percentile/sum_boolean | **reported unmapped**, never dropped |

Joins: :func:`entity_joins` derives a ThoughtSpot join for every MetricFlow
foreign→primary entity pair (the only join MetricFlow itself can express:
LEFT OUTER, many-to-one) — used by ``build-model`` **only** for table pairs that
no ``relationships`` test with ``ts_join_*`` already covers, so the explicit
tags keep authority over join type and name.

Precedence: a metric whose label matches an existing ``ts_formula`` column
(case-insensitive) *supersedes* it — the ``ts_formula`` entry is dropped and the
metric-derived formula takes its place. That is the migration path from
``ts_formula`` strings to real metrics without a hard cut-over.
"""
from __future__ import annotations

import os
import re

from ts_cli.dbt.tags import _formula_id

_AGG_TO_TS: dict[str, str] = {
    "sum": "sum",
    "average": "average",
    "avg": "average",
    "min": "min",
    "max": "max",
    "count": "count",
    "count_distinct": "unique count",
}
_UNSUPPORTED_AGG: dict[str, str] = {
    "median": "ThoughtSpot has no median aggregate",
    "percentile": "ThoughtSpot has no percentile aggregate",
    "sum_boolean": "sum_boolean needs a conditional sum — not translated in this slice",
}
_BARE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------

def semantic_models_in_scope(manifest: dict, model_path: str) -> dict[str, dict]:
    """Semantic models whose backing dbt model lives in ``model_path``.

    Returns ``{semantic_model_name: {"uid", "table", "sm"}}`` where ``table`` is
    the ThoughtSpot Table name (dbt model name upper-cased — the same convention
    :func:`ts_cli.dbt_build_export.build_model_tml_from_manifest` uses).
    """
    nodes = manifest.get("nodes", {})
    out: dict[str, dict] = {}
    for uid, sm in (manifest.get("semantic_models") or {}).items():
        model_uid = next(
            (n for n in (sm.get("depends_on") or {}).get("nodes", []) if n.startswith("model.")),
            None)
        node = nodes.get(model_uid or "")
        if not node:
            continue
        if os.path.dirname(node.get("original_file_path", "")) != model_path:
            continue
        out[sm["name"]] = {"uid": uid, "table": node["name"].upper(), "sm": sm}
    return out


def _transitive_semantic_model_deps(uid: str, metrics: dict, seen: set[str] | None = None) -> set[str]:
    """Semantic-model uids a metric depends on, following ``metric.*`` edges.

    dbt Cloud (2026.9.x) manifests list only *metric* nodes under a ratio/derived
    metric's ``depends_on`` (``metric.pkg.total_tips``); Fusion's local parse lists
    the semantic model directly. Resolving transitively handles both.
    """
    seen = seen if seen is not None else set()
    out: set[str] = set()
    for dep in ((metrics.get(uid) or {}).get("depends_on") or {}).get("nodes", []):
        if dep.startswith("semantic_model."):
            out.add(dep)
        elif dep.startswith("metric.") and dep not in seen:
            seen.add(dep)
            out |= _transitive_semantic_model_deps(dep, metrics, seen)
    return out


def metrics_in_scope(manifest: dict, sm_scope: dict[str, dict]) -> list[dict]:
    """Enabled metrics whose (transitive) semantic-model dependencies are all in ``sm_scope``."""
    scope_uids = {v["uid"] for v in sm_scope.values()}
    metrics = manifest.get("metrics") or {}
    out: list[dict] = []
    for uid, mt in metrics.items():
        cfg = mt.get("config") or {}
        if cfg.get("enabled") is False:
            continue
        deps = _transitive_semantic_model_deps(uid, metrics)
        if not deps or not all(d in scope_uids for d in deps):
            continue
        out.append(mt)
    return out


# ---------------------------------------------------------------------------
# Per-type translation
# ---------------------------------------------------------------------------

def _simple_params(mt: dict, sm_scope: dict[str, dict]) -> tuple[dict | None, str | None]:
    """Resolve (agg, expr, table) for a simple metric.

    v2 manifests carry ``type_params.metric_aggregation_params``; older shapes
    point at a semantic-model ``measure`` by name — handle both.
    """
    tp = mt.get("type_params") or {}
    mp = tp.get("metric_aggregation_params")
    if mp:
        sm_name = mp.get("semantic_model")
        entry = sm_scope.get(sm_name or "")
        if not entry:
            return None, f"semantic model {sm_name!r} not in scope"
        # dbt Cloud puts the column at type_params.expr; Fusion's local parse puts
        # it inside metric_aggregation_params. MetricFlow defaults expr to the name.
        expr = mp.get("expr") or tp.get("expr") or mt["name"]
        return {"agg": mp.get("agg"), "expr": expr, "table": entry["table"]}, None
    measure_ref = (tp.get("measure") or {}).get("name") if isinstance(tp.get("measure"), dict) else None
    if measure_ref:
        for entry in sm_scope.values():
            for m in entry["sm"].get("measures") or []:
                if m.get("name") == measure_ref:
                    return {"agg": m.get("agg"), "expr": m.get("expr") or measure_ref,
                            "table": entry["table"]}, None
        return None, f"measure {measure_ref!r} not found in any in-scope semantic model"
    return None, "simple metric without aggregation params"


def _translate_simple(mt: dict, sm_scope: dict[str, dict]) -> tuple[str | None, str | None]:
    if mt.get("filter"):
        return None, "metric-level filter not translated"
    params, err = _simple_params(mt, sm_scope)
    if err:
        return None, err
    agg = (params["agg"] or "").lower()
    if agg in _UNSUPPORTED_AGG:
        return None, _UNSUPPORTED_AGG[agg]
    ts_agg = _AGG_TO_TS.get(agg)
    if not ts_agg:
        return None, f"unknown aggregation {agg!r}"
    expr = str(params["expr"]).strip()
    if not _BARE_IDENT_RE.match(expr):
        return None, f"SQL-expression expr {expr!r} not translated (only bare column names)"
    return f"{ts_agg} ( [{params['table']}::{expr}] )", None


def _input_ref(inp: dict | str | None) -> tuple[str | None, str | None, str | None]:
    """(name, alias, blocker) for a numerator/denominator/input-metric entry."""
    if inp is None:
        return None, None, "missing input metric"
    if isinstance(inp, str):
        return inp, None, None
    if inp.get("filter"):
        return inp.get("name"), inp.get("alias"), "input-metric filter not translated"
    if inp.get("offset_window") or inp.get("offset_to_grain"):
        return inp.get("name"), inp.get("alias"), "offset_window/offset_to_grain not translated"
    return inp.get("name"), inp.get("alias"), None


def _translate_ratio(mt: dict, fids: dict[str, str]) -> tuple[str | None, str | None]:
    if mt.get("filter"):
        return None, "metric-level filter not translated"
    tp = mt.get("type_params") or {}
    num, _, b1 = _input_ref(tp.get("numerator"))
    den, _, b2 = _input_ref(tp.get("denominator"))
    if b1 or b2:
        return None, b1 or b2
    for ref in (num, den):
        if ref not in fids:
            return None, f"input metric {ref!r} not translated"
    return f"safe_divide ( [{fids[num]}] , [{fids[den]}] )", None


def _translate_derived(mt: dict, fids: dict[str, str]) -> tuple[str | None, str | None]:
    if mt.get("filter"):
        return None, "metric-level filter not translated"
    tp = mt.get("type_params") or {}
    expr = tp.get("expr")
    if not expr:
        return None, "derived metric without expr"
    inputs = tp.get("metrics") or tp.get("input_measures") or []
    tokens: dict[str, str] = {}
    for inp in inputs:
        name, alias, blocker = _input_ref(inp)
        if blocker:
            return None, blocker
        if name not in fids:
            return None, f"input metric {name!r} not translated"
        tokens[alias or name] = fids[name]
    # Longest token first so an alias that prefixes another is replaced whole.
    out = str(expr)
    for tok in sorted(tokens, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(tok)}\b", f"[{tokens[tok]}]", out)
    leftover = [w for w in _IDENT_RE.findall(re.sub(r"\[[^\]]*\]", "", out))
                if not w.isdigit()]
    if leftover:
        return None, f"unresolved identifier(s) in expr: {', '.join(sorted(set(leftover)))}"
    return out, None


# ---------------------------------------------------------------------------
# Column properties + public entry point
# ---------------------------------------------------------------------------

def _metric_column_props(mt: dict) -> dict:
    meta = ((mt.get("config") or {}).get("meta") or {})
    props: dict = {"column_type": "MEASURE", "aggregation": "SUM"}
    syns = [s.strip() for s in str(meta.get("ts_synonym") or "").split(",") if s.strip()]
    if syns:
        props["synonyms"] = syns
    if meta.get("ts_format_pattern"):
        props["format_pattern"] = meta["ts_format_pattern"]
    if str(meta.get("ts_index_type") or "").lower() == "dont_index":
        props["index_type"] = "DONT_INDEX"
    if meta.get("ts_ai_context"):
        props["ai_context"] = meta["ts_ai_context"]
    return props


def translate_metrics(
    manifest: dict,
    model_path: str,
    existing_formula_names: set[str] | None = None,
) -> dict:
    """Translate in-scope MetricFlow metrics to ThoughtSpot formulas.

    Returns::

        {
          "formulas":   [{"id", "name", "expr"}],                 # append to model.formulas
          "columns":    [{"name", "formula_id", "properties", "description"?}],
          "superseded": ["Total Tips", ...],   # ts_formula names replaced by a metric
          "unmapped":   [{"metric", "type", "reason"}],
        }

    Simple metrics translate first, then ratio/derived resolve against them; a
    ratio/derived metric whose inputs are themselves unmapped is reported, not
    guessed.
    """
    existing_lower = {n.lower(): n for n in (existing_formula_names or set())}
    sm_scope = semantic_models_in_scope(manifest, model_path)
    metrics = metrics_in_scope(manifest, sm_scope)

    fids: dict[str, str] = {}            # metric name -> formula id
    formulas: list[dict] = []
    columns: list[dict] = []
    superseded: list[str] = []
    unmapped: list[dict] = []

    def _emit(mt: dict, expr: str) -> None:
        display = (mt.get("label") or mt["name"]).strip()
        fid = _formula_id(display)
        fids[mt["name"]] = fid
        formulas.append({"id": fid, "name": display, "expr": expr})
        col: dict = {"name": display, "formula_id": fid, "properties": _metric_column_props(mt)}
        if mt.get("description"):
            col["description"] = mt["description"]
        columns.append(col)
        if display.lower() in existing_lower:
            superseded.append(existing_lower[display.lower()])

    pending = [m for m in metrics if m.get("type") == "simple"]
    for mt in pending:
        expr, err = _translate_simple(mt, sm_scope)
        if err:
            unmapped.append({"metric": mt["name"], "type": "simple", "reason": err})
        else:
            _emit(mt, expr)

    # ratio/derived may chain (derived over a ratio) — iterate to a fixpoint.
    rest = [m for m in metrics if m.get("type") in ("ratio", "derived")]
    progress = True
    while rest and progress:
        progress = False
        still: list[dict] = []
        for mt in rest:
            fn = _translate_ratio if mt["type"] == "ratio" else _translate_derived
            expr, err = fn(mt, fids)
            if expr:
                _emit(mt, expr)
                progress = True
            elif err and "not translated" in err and "input metric" in err:
                still.append(mt)          # dependency may land on a later pass
            else:
                unmapped.append({"metric": mt["name"], "type": mt["type"], "reason": err})
        rest = still
    for mt in rest:
        fn = _translate_ratio if mt["type"] == "ratio" else _translate_derived
        _, err = fn(mt, fids)
        unmapped.append({"metric": mt["name"], "type": mt["type"], "reason": err})

    for mt in metrics:
        if mt.get("type") in ("cumulative", "conversion"):
            unmapped.append({"metric": mt["name"], "type": mt["type"],
                             "reason": f"{mt['type']} metrics not translated in this slice"})
        elif mt.get("type") not in ("simple", "ratio", "derived"):
            unmapped.append({"metric": mt["name"], "type": str(mt.get("type")),
                             "reason": "unknown metric type"})

    return {"formulas": formulas, "columns": columns,
            "superseded": sorted(set(superseded)), "unmapped": unmapped}


# ---------------------------------------------------------------------------
# Entity-derived joins
# ---------------------------------------------------------------------------

def entity_joins(sm_scope: dict[str, dict]) -> list[dict]:
    """ThoughtSpot joins implied by MetricFlow entities across in-scope semantic models.

    For each ``foreign`` entity on model A whose name matches a ``primary`` (or
    ``unique``) entity on model B, returns::

        {"source": "A_TABLE", "target": "B_TABLE", "entity": "customer",
         "join": {"name", "with", "on", "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"}}

    Entities with an ``expr`` that is not a bare column are skipped (ThoughtSpot
    joins need a column on each side). Ambiguous targets (two primaries with the
    same entity name) are skipped too — MetricFlow itself would reject that graph.
    """
    primaries: dict[str, list[tuple[str, str]]] = {}
    for entry in sm_scope.values():
        for e in entry["sm"].get("entities") or []:
            if e.get("type") in ("primary", "unique"):
                col = e.get("expr") or e.get("name")
                if _BARE_IDENT_RE.match(str(col)):
                    primaries.setdefault(e["name"], []).append((entry["table"], str(col)))
    out: list[dict] = []
    for entry in sm_scope.values():
        for e in entry["sm"].get("entities") or []:
            if e.get("type") != "foreign":
                continue
            targets = primaries.get(e["name"]) or []
            col = str(e.get("expr") or e.get("name"))
            if len(targets) != 1 or not _BARE_IDENT_RE.match(col):
                continue
            tgt_table, tgt_col = targets[0]
            if tgt_table == entry["table"]:
                continue
            out.append({
                "source": entry["table"], "target": tgt_table, "entity": e["name"],
                "join": {
                    "name": f"{entry['table'].lower()}_to_{tgt_table.lower()}",
                    "with": tgt_table,
                    "on": f"[{entry['table']}::{col}] = [{tgt_table}::{tgt_col}]",
                    "type": "LEFT_OUTER",
                    "cardinality": "MANY_TO_ONE",
                },
            })
    return out
