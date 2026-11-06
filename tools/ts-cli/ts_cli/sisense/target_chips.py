"""Sisense dashboard filters -> Liveboard filter chips for ``--target-model`` (pure, no I/O).

A chip is one filter for the whole board, so on top of carrying its condition
(``target_filters.chip_condition``) it has to apply to each tile the way Sisense applied the
dashboard filter to that widget:

- a widget filter on the same column takes priority over the dashboard filter in Sisense, and a
  chip REPLACES a tile's own filter in ThoughtSpot, so the tile is excluded from the chip;
- a widget that ignores the filter (``metadata.ignore``: all, its dimension, or its instance id)
  is excluded too;
- a widget in Highlight mode (``dashboardFiltersMode: select``) highlights members of a column
  it plots instead of filtering, which a chip cannot do -> NEEDS REVIEW;
- the chip binds ONE role-played copy of a table for the board, while Sisense resolves each
  widget by its own path, so a tile whose own path is a different copy -- or whose path cannot
  be determined -- is NEEDS REVIEW, as is a tile the chip cannot reach.

Every problem is reported on the chip AND on each tile it touches, so a reader of the tile rows
sees the risk too. Nothing is carried on a guess.
"""
from __future__ import annotations

from ts_cli.sisense.target_filters import chip_condition, is_all
from ts_cli.sisense.target_model import split_dim


def review(visual: str, note: str) -> dict:
    return {"visual": visual, "ts_chart": "FILTER", "status": "NEEDS REVIEW", "note": note}


def flag_tile(tile: dict, note: str) -> None:
    """Downgrade one tile's report row with the reason."""
    row = tile["row"]
    row["status"] = "NEEDS REVIEW"
    row["note"] = "; ".join(filter(None, [row.get("note"), note]))


def _chip_column(sf: dict, binder, anchor_sets: list) -> tuple:
    """Dashboard filter -> (model column | None, instance | None, note)."""
    dim = sf.get("dim") or ""
    if dim in binder.field_map:
        name, _, note = binder.mapped(dim)
        insts = binder.t.instances_of.get(name) or set()
        return name, (next(iter(insts)) if len(insts) == 1 else None), note
    table, col = split_dim(dim)
    inst, note = binder.t.resolve_chip_instance(table, anchor_sets, binder.relations)
    name = binder.t.column(inst, col) if inst else None
    if inst and not name:
        note = f"{table}.{col} is not exposed on the target model"
    return name, inst, note


def _same_dim(a: str, b: str) -> bool:
    return split_dim(a) == split_dim(b)


def _ignores(widget: dict, sf: dict) -> bool:
    ig = widget.get("ignore") or {}
    if ig.get("all"):
        return True
    if any(_same_dim(d, sf.get("dim") or "") for d in ig.get("dimensions") or []):
        return True
    return bool(set(ig.get("ids") or []) & set(sf.get("instanceids") or []))


def _highlights(widget: dict, sf: dict) -> bool:
    return widget.get("filters_mode") == "select" and any(
        _same_dim(f.get("dim") or "", sf.get("dim") or "") for f in widget.get("fields", []))


def _tile_problem(tile: dict, sf: dict, inst, binder) -> str:
    """Why this chip does not filter this tile the way Sisense filtered the widget, or ''."""
    mode = tile["widget"].get("filters_mode")
    if mode not in (None, "filter", "select"):
        return f"the widget's dashboard-filter mode is {mode!r}, which this converter does not read"
    if _highlights(tile["widget"], sf):
        return "the widget is in Highlight mode in Sisense, so this column highlights instead of filtering"
    facts = tile["facts"]
    if inst is None:
        return "the chip's table instance could not be determined, so whether it filters this tile as in Sisense cannot be checked"
    path = binder.no_fact_problem(tile["widget"], (split_dim(sf.get("dim") or "")[0], inst))
    if path:
        return path
    if not facts:
        return "the tile's facts could not be determined, so whether the chip reaches it cannot be checked"
    if not any(inst in binder.t.reachable(a) for a in facts):
        return f"the chip's {inst} does not reach this tile's facts"
    if (sf.get("dim") or "") in binder.field_map:
        return ""
    table = split_dim(sf.get("dim") or "")[0]
    own = binder.t.resolve_instance(table, facts, binder.relations)[0]
    if own is None:
        return "the tile's own path to the filtered table could not be determined"
    if own != inst:
        return f"the chip binds {inst}, but this widget reaches the table through {own} in Sisense"
    insts = binder._widget_instances(tile["widget"])
    known = binder.t.path_known(table, inst, facts, any(r in insts for r in binder.t.roots()), binder.relations)
    return binder.t.role_conflict(table, inst, insts, known, relations=binder.relations)


def _split_tiles(sf: dict, name: str, tiles: list) -> tuple:
    """-> (excluded viz ids, titles of tiles ignoring the filter, tiles the chip applies to)."""
    excluded, ignoring = [], []
    for t in tiles:
        if name in t["own"]:
            excluded.append(t["vid"])                  # the widget's own filter wins in Sisense
        elif _ignores(t["widget"], sf):
            excluded.append(t["vid"])
            ignoring.append(t["title"])
    return excluded, ignoring, [t for t in tiles if t["vid"] not in excluded]


def _condition_rows(sf: dict, chip: dict, name: str, binder, applied: list) -> list:
    """Carry the condition; when it is not carried exactly, report it on the chip and its tiles."""
    why = chip_condition(sf, chip)
    if not why:
        return []
    for t in applied:
        flag_tile(t, f"dashboard filter {name} is not carried exactly ({why})")
    return [review(f"filter chip {name}", f"dashboard filter on {sf.get('dim') or name}: {why}")]


def _tile_rows(sf: dict, name: str, inst, binder, applied: list) -> list:
    """Check each tile the chip applies to; report and flag every one it mis-filters."""
    if is_all(sf):
        return []                                      # no condition: nothing to mis-apply
    problems = [(t, _tile_problem(t, sf, inst, binder)) for t in applied]
    problems = [(t, p) for t, p in problems if p]
    for t, p in problems:
        flag_tile(t, f"dashboard filter {name}: {p}")
    if not problems:
        return []
    return [review(f"filter chip {name}", "does not filter every tile as in Sisense: "
                   + "; ".join(f"{t['title']} ({p})" for t, p in problems))]


def _chip(sf: dict, name: str, inst, binder, tiles: list) -> tuple:
    """One resolved dashboard filter -> (chip, review rows); flags the tiles it mis-filters."""
    chip = {"column": [name], "is_mandatory": False, "is_single_value": False, "display_name": ""}
    excluded, ignoring, applied = _split_tiles(sf, name, tiles)
    if excluded:
        chip["excluded_visualizations"] = excluded
    rows = _condition_rows(sf, chip, name, binder, applied) + _tile_rows(sf, name, inst, binder, applied)
    if ignoring:
        rows.append({"visual": f"filter chip {name}", "ts_chart": "FILTER", "status": "Migrated",
                     "note": "excluded from tiles that ignore it in Sisense: " + "; ".join(ignoring)})
    return chip, rows


def build_chips(inv: dict, binder, tiles: list) -> tuple:
    """Dashboard filters -> (chips, report rows). ``tiles``: one dict per answer tile with
    ``vid, own, facts, title, row, widget``."""
    chips, rows = [], []
    dash = inv.get("dashboard") or {}
    for dim in dash.get("disabled_filters") or []:
        rows.append({"visual": f"filter chip {dim}", "ts_chart": "FILTER", "status": "Skipped",
                     "note": "disabled in Sisense (no filtering), so no chip"})
    for problem in dash.get("unreadable_filters") or []:
        rows += _uncarried({"dim": problem}, tiles, "the dashboard filter could not be read")
    anchor_sets = [t["facts"] for t in tiles if t["facts"]]
    for sf in dash.get("filters", []) or []:
        chip, chip_rows = _one_filter(sf, binder, tiles, anchor_sets)
        rows += chip_rows
        if chip:
            chips.append(chip)
    return chips, rows + _duplicate_chip_rows(chips, tiles)


def _duplicate_chip_rows(chips: list, tiles: list) -> list:
    """Two chips on one column: how a Liveboard combines them is not verified."""
    cols = [c["column"][0] for c in chips if c.get("oper") or c.get("generic_filter")]
    rows = []
    for col in sorted({c for c in cols if cols.count(c) > 1}):
        for t in tiles:
            flag_tile(t, f"two dashboard filters on {col}: how two chips on one column combine is not verified")
        rows.append(review(f"filter chip {col}", "two dashboard filters on this column; how two chips on one "
                           "column combine is not verified"))
    return rows


def _uncarried(sf: dict, tiles: list, reason: str) -> list:
    """A dashboard filter with no chip: its row, and every tile flagged unless it is `all`."""
    if not is_all(sf):
        for t in tiles:
            flag_tile(t, f"dashboard filter on {sf.get('dim')} is not carried ({reason})")
    return [review(f"filter chip {sf.get('dim') or ''}", reason)]


def _one_filter(sf: dict, binder, tiles: list, anchor_sets: list) -> tuple:
    """One dashboard filter -> (chip | None, report rows)."""
    if sf.get("kind") == "top_n":
        return None, _uncarried(dict(sf, raw={}), tiles, "a dashboard-level top/bottom ranking has no chip form")
    name, inst, note = _chip_column(sf, binder, anchor_sets)
    if not name:
        return None, _uncarried(sf, tiles, note)
    chip, rows = _chip(sf, name, inst, binder, tiles)
    return chip, rows + ([review(f"filter chip {name}", note)] if note else [])
