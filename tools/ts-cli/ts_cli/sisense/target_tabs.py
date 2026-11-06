"""Sisense WidgetsTabber tab sets for ``build-liveboard --target-model`` (pure, no I/O).

A tab set shows one widget per tab. A hidden tab is MERGED into the shown one only when it is
the same chart -- same type, fields, filters and every setting that changes its numbers -- at
another date level ThoughtSpot's date-bucket control can show. Any other hidden tab is a chart
of its own and becomes a tile.
"""
from __future__ import annotations

import re

from ts_cli.sisense.answers import date_bucket_suffix

_GRAIN_SUFFIX = re.compile(r"\s*\((daily|weekly|monthly|quarterly|yearly)\)\s*$", re.I)


def _field_key(f: dict) -> str:
    """Everything about a plotted field except its title and date level (and the week start,
    which only means something at the weekly level -- a weekly grain is flagged on its row)."""
    return repr(sorted((k, repr(v)) for k, v in f.items() if k not in ("level", "title", "firstday")))


def _shape(w: dict) -> tuple:
    """A widget's plotted fields (date level left out), its filters and every setting that
    changes its numbers, exactly."""
    filters = sorted(repr(sorted((k, repr(v)) for k, v in sf.items())) for sf in w.get("filters", []))
    settings = repr([(k, w.get(k)) for k in ("subtype", "ignore", "filters_mode", "unsupported", "disabled_filters",
                                             "drill_targets", "drill_filter_settings")])
    return (w.get("wtype"), tuple(sorted(_field_key(f) for f in w.get("fields", []))), tuple(filters), settings)


def _levels(w: dict) -> tuple:
    return tuple(sorted((_field_key(f), (f.get("level") or "").lower()) for f in w.get("fields", [])))


def _grain_variant(hidden: dict, shown: dict) -> bool:
    """One chart at another date grain: same type, fields and filters, a different date level
    that ThoughtSpot's date bucket can show."""
    mappable = all(not f.get("level") or date_bucket_suffix(f.get("level")) for f in hidden.get("fields", []))
    # a ranking re-ranks at whatever bucket the chart shows, so a ranked tab is never one grain
    ranked = any(sf.get("kind") == "top_n" for sf in hidden.get("filters", []))
    return mappable and not ranked and _shape(hidden) == _shape(shown) and _levels(hidden) != _levels(shown)


def _hidden_tabs(widgets: list) -> tuple:
    """(grain variants: oid -> (tab-set title, shown oid), other hidden tabs: oid -> tab-set
    title) for every widget a WidgetsTabber hides. Only a hidden widget with the same type, fields and filters as a shown
    one and a different date level is a grain variant; any other hidden tab is a chart of its own."""
    by_oid = {w.get("oid"): w for w in widgets}
    grain, other = {}, {}
    for w in widgets:
        if w.get("tabber"):
            _classify_tabs(w, by_oid, grain, other)
    return grain, other


def _classify_tabs(w: dict, by_oid: dict, grain: dict, other: dict) -> None:
    tb, title = w["tabber"], w.get("title") or ""
    keep = set((tb["tabs"][tb["active"]]["show"] if tb["tabs"] else []))
    shown = [by_oid[o] for o in keep if o in by_oid]
    hidden = [o for tab in tb["tabs"] for o in tab["show"] if o not in keep and o in by_oid]
    for oid in hidden:
        hit = next((s.get("oid") for s in shown if _grain_variant(by_oid[oid], s)), None)
        if hit:
            grain[oid] = (title, hit)
        else:
            other[oid] = title


def tabber_hidden(widgets: list) -> dict:
    """oid -> tab-set title for every hidden widget that is a date-grain variant of a shown one."""
    return {oid: title for oid, (title, _) in _hidden_tabs(widgets)[0].items()}


def _kept_tabs(widgets: list) -> set:
    """Widget oids shown by each tab set's ACTIVE tab."""
    out = set()
    for w in widgets:
        tb = w.get("tabber") or {}
        if tb.get("tabs"):
            out.update(tb["tabs"][tb["active"]]["show"])
    return out
