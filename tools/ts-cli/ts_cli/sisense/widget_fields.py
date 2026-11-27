"""One Sisense widget's measures and filters -> ThoughtSpot answer formulas + search filters.

Pure functions, no I/O. ``answers._widget_answer`` calls ``widget_plan`` once per widget.

* Every widget measure that is a JAQL formula, or a plain ``agg`` over a column that is
  not already a Model measure, becomes an Answer formula (``answer.formulas``) named after
  the widget item. Before this, a formula measure was reported as an unmapped field and the
  tile was dropped, so a Sisense indicator (whose value is almost always a formula) never
  reached ThoughtSpot.
* The widget's own filters (its Filters panel, or a filter on a plotted item) go into the
  search query, unless the column also carries a Liveboard filter: a Liveboard filter on a
  column replaces the tile's own filter on that column, so there the tile filter is folded
  into each measure as a condition instead (``scope.py``).
* ``metadata.ignore`` (dashboard filters the widget does not take) wraps each aggregate in
  ``group_aggregate``; a single-value widget groups by ``{ }``, any other by
  ``query_groups ( )``.
* A pivot is flattened to a GRID_TABLE when it has no Columns panel (it is a flat table
  already) or when its Columns dimension carries a member list (one conditional measure per
  member and value). PIVOT_TABLE refuses a large unfiltered result ("too many results"), so
  a pivot keyed on job- or person-level rows did not render.
"""
from __future__ import annotations

import re

from ts_cli.sisense.functions import translate_jaql
from ts_cli.sisense.scope import (GROUPS_QUERY, GROUPS_SINGLE, Scope, and_conds,
                                  filter_condition, map_agg_calls, search_filter_tokens,
                                  _conditional_call)

_REF = re.compile(r"\[([^\[\]]+)\]")
_SINGLE_VALUE = frozenset({"indicator"})


def _leaf(dim) -> str:
    """'[Table.Column (Calendar)]' -> 'Column' (mirrors answers._model_col)."""
    inner = (dim or "").strip().strip("[]")
    leaf = inner.split(".")[-1].strip() if inner else ""
    if leaf.endswith(")") and " (" in leaf:
        leaf = leaf.split(" (")[0].strip()
    return leaf


def _resolve(name: str, norm: dict):
    if not name:
        return None
    return norm.get(name.lower()) or norm.get(name.split(" (")[0].strip().lower())


def resolve_refs(expr: str, norm: dict, keep=frozenset()) -> tuple:
    """Rewrite each ``[name]`` in a formula to the Model's spelling -> (expr, missing)."""
    missing: list = []

    def sub(m):
        name = m.group(1)
        if name in keep or name.startswith("formula_"):
            return m.group(0)
        hit = _resolve(name, norm)
        if hit is None:
            missing.append(name)
            return m.group(0)
        return "[" + hit + "]"
    return _REF.sub(sub, expr), missing


# --------------------------------------------------------------------------- #
# Scope: widget filters + ignored dashboard filters
# --------------------------------------------------------------------------- #
def _ignored_cols(widget: dict, dash_filters: list, norm: dict) -> tuple:
    ig = widget.get("ignore") or {}
    ids = set(ig.get("ids") or [])
    dims = [df.get("dim") for df in dash_filters
            if ids & set(df.get("instanceids") or [df.get("instanceid")])]
    dims += [d for d in ig.get("dimensions") or [] if isinstance(d, str)]
    cols = sorted({"[" + c + "]" for c in (_resolve(_leaf(d), norm) for d in dims) if c})
    return bool(ig.get("all")), cols


def _tile_filter(sf: dict, col: str, lb_cols: set, scope: Scope, search: list, notes: list):
    """Route one widget filter to a search token or (shadowed by a Liveboard filter) a
    measure condition. Returns False when it has no faithful form."""
    ref = "[" + col + "]"
    raw, dtype = sf.get("raw") or {}, sf.get("datatype") or ""
    if col not in lb_cols:
        toks, err = search_filter_tokens(ref, raw)
        if toks is not None:
            if toks:
                search.append(toks)
            return True
        if dtype.lower() == "datetime":
            notes.append(f"widget filter not applied: {err}")
            return False
    cond, err = filter_condition(ref, raw, dtype)
    if err:
        notes.append(f"widget filter not applied: {err}")
        return False
    if cond:
        scope.conds[ref] = and_conds([scope.conds.get(ref), cond])
        if col in lb_cols:
            notes.append(f"filter on {ref} folded into the measures: the Liveboard filter "
                         "on that column would replace it")
    return True


def build_scope(widget: dict, dash_filters: list, norm: dict, lb_cols: set) -> tuple:
    """-> (Scope, search tokens, notes, ok). ``ok`` False = a filter was not applied."""
    single = (widget.get("wtype") or "").lower() in _SINGLE_VALUE
    ignore_all, ignore_cols = _ignored_cols(widget, dash_filters, norm)
    scope = Scope(groups=GROUPS_SINGLE if single else GROUPS_QUERY,
                  ignore_cols=ignore_cols, ignore_all=ignore_all)
    search, notes, ok = [], [], True
    for sf in widget.get("filters") or []:
        if sf.get("kind") in ("top_n", "all"):
            continue
        col = _resolve(_leaf(sf.get("dim")), norm)
        if not col:
            notes.append(f"widget filter on {sf.get('dim')} not applied: column not in Model")
            ok = False
            continue
        ok = _tile_filter(sf, col, lb_cols, scope, search, notes) and ok
    if ignore_all:
        notes.append("widget ignores every dashboard filter: measures use group_aggregate "
                     "with no query filters")
    elif ignore_cols:
        notes.append("widget ignores the dashboard filter on " + ", ".join(ignore_cols)
                     + ": measures drop it via group_aggregate")
    return scope, search, notes, ok


# --------------------------------------------------------------------------- #
# Measures -> formulas
# --------------------------------------------------------------------------- #
def _unique_name(title: str, taken: set) -> str:
    """``title``, or ``title Value`` / ``title (2)``… when a Model column or an earlier
    formula already has the name (case-insensitive)."""
    base = (title or "").strip() or "Value"
    candidates = [base, f"{base} Value"] + [f"{base} ({n})" for n in range(2, 1000)]
    name = next(c for c in candidates if c.lower() not in taken)
    taken.add(name.lower())
    return name


def _measure_expr(f: dict, scope: Scope) -> tuple:
    """A measure field -> (TS expr | None, status, note)."""
    if f.get("formula"):
        fm = f["formula"]
        return translate_jaql(fm.get("expression"), fm.get("context") or {}, scope)
    return translate_jaql(f"{f.get('agg')}([__f])", {"__f": {"dim": f.get("dim")}}, scope)


def _one_measure(f: dict, scope: Scope, norm: dict) -> tuple:
    """-> (expr | None, status, note) with the formula's references in Model spelling."""
    label = f.get("title") or _leaf(f.get("dim"))
    expr, st, note = _measure_expr(f, scope)
    if expr is None:
        return None, "NEEDS REVIEW", f"{label}: {note}"
    expr, unknown = resolve_refs(expr, norm)
    if unknown:
        return None, "NEEDS REVIEW", (f"{label}: references "
                                      f"{', '.join(sorted(set(unknown)))} not in the Model")
    return expr, st, (f"{label}: {note}" if note else "")


def _stays_column(f: dict, scope: Scope, norm: dict, measures: set):
    """The Model measure a plain ``sum`` stays as when nothing scopes it, else None."""
    if f.get("formula") or not f.get("dim") or not scope.trivial():
        return None
    col = _resolve(_leaf(f.get("dim")), norm)
    return col if col in measures and (f.get("agg") or "sum") == "sum" else None


def measure_formulas(fields: list, scope: Scope, norm: dict, measures: set) -> tuple:
    """Measure fields -> (formulas, plain measure columns, status, notes, missing).

    A plain ``agg`` over a Model MEASURE stays the column when the agg is ``sum`` and the
    scope is trivial; everything else becomes an Answer formula."""
    taken = set(norm)
    formulas, plain, notes, missing, status = [], [], [], [], "Migrated"
    rank = {"Migrated": 0, "Approximated": 1, "NEEDS REVIEW": 2}
    for f in fields:
        col = _stays_column(f, scope, norm, measures)
        if col:
            plain.append(col)
            continue
        expr, st, note = _one_measure(f, scope, norm)
        if note:
            notes.append(note)
        status = max(status, st, key=lambda x: rank.get(x, 0))
        label = f.get("title") or _leaf(f.get("dim"))
        if expr is None:
            missing.append(label or "?")
            continue
        name = _unique_name(label, taken)
        formulas.append({"id": f"formula_{name}", "name": name, "expr": expr})
    return formulas, plain, status, notes, missing


# --------------------------------------------------------------------------- #
# Pivot flattening
# --------------------------------------------------------------------------- #
def _members_for(widget: dict, dim) -> list:
    for sf in widget.get("filters") or []:
        if sf.get("dim") == dim and sf.get("kind") == "member":
            return list(sf.get("values") or [])
    return []


def flatten_pivot(widget: dict, dims: list, formulas: list, plain: list, norm: dict) -> tuple:
    """-> (ts_chart, dims, formulas, plain, note). See module docstring."""
    col_dims = [d for d in dims if d["role"] == "Columns"]
    if not col_dims:
        return "GRID_TABLE", dims, formulas, plain, (
            "pivot with no Columns panel emitted as a flat GRID_TABLE (PIVOT_TABLE refuses "
            "large unfiltered results)")
    members = _members_for(widget, col_dims[0]["dim"]) if len(col_dims) == 1 else []
    if not members:
        return "PIVOT_TABLE", dims, formulas, plain, (
            "pivot kept: its Columns values are not known offline; if its rows are "
            "high-cardinality PIVOT_TABLE fails with too many results, so flatten it into "
            "one conditional measure per column value")
    ref = "[" + col_dims[0]["name"] + "]"
    values = [(f["name"], f["expr"]) for f in formulas] + [(c, f"sum ( [{c}] )") for c in plain]
    taken = set(norm)
    out = []
    for m in members:
        cond, _ = filter_condition(ref, {"members": [m]}, col_dims[0].get("datatype") or "")
        for vname, vexpr in values:
            label = str(m) if len(values) == 1 else f"{m} {vname}"
            name = _unique_name(label, taken)
            expr = map_agg_calls(vexpr, lambda n, a, c=cond: _conditional_call(n, a, c))
            out.append({"id": f"formula_{name}", "name": name, "expr": expr})
    rest = [d for d in dims if d is not col_dims[0]]
    return "GRID_TABLE", rest, out, [], (
        f"pivot flattened to a GRID_TABLE: one conditional measure per {ref} value "
        f"({len(members)} values)")
