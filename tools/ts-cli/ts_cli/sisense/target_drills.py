"""Jump-to-dashboard drills for ``build-liveboard --target-model`` (pure, no I/O).

A Sisense jump-to-dashboard opens a drill dashboard filtered by the clicked value and the source
widget's filters. A Liveboard has no such pop-up, so each drill target becomes ONE details table
on the board, built from the drill dashboard's first widget with fields and carrying the filters
every source widget shares; users narrow it with right-click > Filter. That stands in for the
drill rather than reproducing it, so a clean one is Approximated, and anything that changes which
rows Sisense's drill shows (filters not carried or not shared, the drill dashboard's own filters,
non-default jump-to-dashboard filter settings, extra widgets) is NEEDS REVIEW.
"""
from __future__ import annotations

from ts_cli.sisense.target_filters import is_all

def _shared_filters(binder, widgets: list) -> tuple:
    """(search fragments EVERY source widget carries, note). Sisense passes a source widget's
    filters to the drill, so one that is not carried, or not shared by every source, means the
    details table differs from Sisense for clicks from that source -> the note says which."""
    common, per_source, dropped = None, [], []
    for w in widgets:
        frs, missing = _source_filters(binder, w)
        per_source.append((w.get("title") or "?", frs))
        dropped += [f"{w.get('title') or '?'}: {d}" for d in missing]
        common = frs if common is None else common & frs
    common = common or set()
    dropped += [f"{t}: {f}" for t, frs in per_source for f in sorted(frs - common)]
    note = ("filters Sisense passes to this drill from its source widgets are not carried: " + "; ".join(dropped)
            if dropped else "")
    return sorted(common), note


def _source_filters(binder, w: dict) -> tuple:
    """A drill source widget's filters -> (carried fragments, dims of those not carried)."""
    anchors = binder.anchors(w)
    frs, missing = set(), []
    for sf in w.get("filters", []):
        if sf.get("kind") == "top_n" or is_all(sf):
            continue
        frag, _, fnote = binder.filter_fragment(sf, anchors)
        if frag:
            frs.add(frag)
        elif fnote:
            missing.append(sf.get("dim") or "?")
    return frs, missing


def _drill_description(src_widgets: list, target_title: str) -> str:
    sources = ", ".join(sorted({w.get("title") or "" for w in src_widgets}))
    return (f"Right-click a value in {sources} and choose Filter to narrow this list "
            f"(replaces the Sisense drill to {target_title}).")


def drill_tables(drills, binder, sources, model_fqn, answer_for):
    """Distinct drill targets -> [(key, answer, row, own, facts, widget)]: one details table per
    target, built from the drill dashboard's first widget, carrying the filters EVERY source
    widget shares. The table is a tile like any other, so dashboard chips are checked against it."""
    out = []
    by_title = {(d.get("dashboard") or {}).get("title"): d for d in drills or []}
    for target, src_widgets in sources.items():
        d = by_title.get(target)
        if not d:
            out.append((f"drill:{target}", None, {"visual": f"drill -> {target}", "ts_chart": "GRID_TABLE",
                        "status": "NEEDS REVIEW", "note": f"drill dashboard '{target}' not supplied (--drill)"},
                        set(), [], {}))
            continue
        with_fields = [w for w in d.get("widgets", []) if w.get("fields")]
        if not with_fields:
            out.append((f"drill:{target}", None, {"visual": f"drill -> {target}", "ts_chart": "GRID_TABLE",
                        "status": "NEEDS REVIEW", "note": f"drill dashboard '{target}' has no widget with fields"},
                        set(), [], {}))
            continue
        out.append(_drill_table(d, target, with_fields, binder, src_widgets, model_fqn, answer_for))
    return out


def _drill_problems(target: str, with_fields: list, src_widgets: list, own_dash: list) -> list:
    """What makes the details table differ from the rows Sisense's drill shows."""
    out = []
    jtd = sorted({k for w in src_widgets for k in w.get("drill_filter_settings") or []})
    if jtd:
        out.append(f"the jump-to-dashboard filter settings are not the defaults ({', '.join(jtd)}), so which "
                   "filters reach the drill is not carried")
    rest = [w.get("title") or "?" for w in with_fields[1:]]
    if rest:
        out.append(f"drill dashboard '{target}' has more widgets than its details table carries: {', '.join(rest)}")
    if own_dash:
        out.append(f"drill dashboard '{target}' has its own dashboard filters, not carried: {', '.join(own_dash)}")
    return out


def _drill_table(d: dict, target: str, with_fields: list, binder, src_widgets: list, model_fqn, answer_for) -> tuple:
    """One drill dashboard -> (key, answer, row, own, facts, widget) from its first widget with
    fields; the widget's own filters and the drill dashboard's own filters both apply to it."""
    dw = with_fields[0]
    # the drill dashboard's OWN filters: how a jump-to-dashboard combines them with what the
    # source passes is not verified, so any with a condition is reported, never applied
    own_dash = [sf.get("dim") or "?" for sf in (d.get("dashboard") or {}).get("filters") or [] if not is_all(sf)]
    detail = dict(dw, wtype="tablewidget")
    shared, shared_note = _shared_filters(binder, src_widgets)
    ctx = {"key": f"drill-{target}", "model_fqn": model_fqn, "extra_filters": shared,
           "description": _drill_description(src_widgets, dw.get("title") or target)}
    a, row, own, facts = answer_for(detail, binder, ctx, title_override=dw.get("title") or target)
    problems = _drill_problems(target, with_fields, src_widgets, own_dash) + ([shared_note] if shared_note else [])
    if problems:
        row.update(status="NEEDS REVIEW", note="; ".join(filter(None, [row.get("note")] + problems)))
    elif row["status"] == "Migrated":   # a details table stands in for a pop-up drill: never exact
        row.update(status="Approximated", note="; ".join(filter(None, [row.get("note"), (
            "details table in place of the Sisense jump-to-dashboard; users narrow it with right-click > Filter")])))
    return f"drill:{target}", a, row, own, facts, detail
