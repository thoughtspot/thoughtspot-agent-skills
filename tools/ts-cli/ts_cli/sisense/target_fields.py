"""One widget's plotted fields -> the columns, roles and search tokens of its Answer, for
``build-liveboard --target-model`` (pure, no I/O).

Every field outside the filter panel ends up as an answer column or is named in a note: the
ACCOUNTING GATE in ``_collect_fields`` reports any field that did neither, so a path that drops a
field without saying why cannot ship a tile showing less than the Sisense widget. Binding a
field to the Model is the binder's job (target_answers._Binder); this module only assembles.
"""
from __future__ import annotations

from ts_cli.sisense.answers import date_bucket_suffix
from ts_cli.sisense.target_model import split_dim


def _dimension(name: str, level) -> dict:
    suf = date_bucket_suffix(level)
    if level and not suf:
        return {"note": f"date level {level} on [{name}] has no ThoughtSpot bucket, so its grain is not carried"}
    token = f"[{name}].{suf.lower()}" if suf else f"[{name}]"
    out = f"{_bucket_out(suf)}({name})" if suf else name
    return {"name": name, "token": token, "out": out, "measure": False, "bucketed": bool(suf)}


def _bucket_out(suf: str) -> str:
    return {"HOURLY": "Hour", "DAILY": "Day", "WEEKLY": "Week", "MONTHLY": "Month",
            "QUARTERLY": "Quarter", "YEARLY": "Year"}[suf]


_ROLE_OF_PANEL = {"categories": "Category", "x-axis": "Category", "rows": "Rows", "columns": "Columns",
                  "break by": "Series", "break-by": "Series", "break by / color": "Series", "color": "Series",
                  "point": "Category"}
_FILTER_PANEL = "filters"           # read by _collect_filters
_GAUGE_BOUNDS = ("min", "max")      # a gauge's scale, not a value; `secondary` is a shown value


def _label_for(f: dict, b: dict):
    """Sisense title -> custom_name, unless it is just the column (or a bucketed date)."""
    title = (f.get("title") or "").strip()
    if not title or b.get("bucketed") or title.lower() == b["out"].lower():
        return None
    if not b["measure"] and title.replace("_", "").lower() == split_dim(f.get("dim"))[1].replace("_", "").lower():
        return None
    return title


def _collect_fields(widget: dict, binder, anchors: list) -> dict:
    """Plotted fields -> {cols, roles, tokens, measures, measure_outs, labels, notes}.

    ACCOUNTING GATE: every field outside the filter panel ends up as an answer column or is
    named in a note. A field that did neither (a path that returns without reporting) is
    reported here rather than lost, so a new silent path cannot ship a tile that quietly shows
    less than the Sisense widget."""
    acc = {"cols": [], "roles": [], "tokens": {}, "measures": set(), "measure_outs": {}, "labels": {},
           "notes": [], "measure_fields": [], "dimension_fields": []}
    for f in widget.get("fields", []):
        panel = (f.get("panel") or "").lower()
        if panel == _FILTER_PANEL:
            continue
        before = (len(acc["cols"]), len(acc["notes"]))
        _collect_field(acc, f, panel, binder, anchors)
        if (len(acc["cols"]), len(acc["notes"])) == before:
            acc["notes"].append(f"field {f.get('title') or f.get('dim') or '?'} ({panel or 'no panel'}) is not "
                                "carried and no check reported why")
    return acc


def _collect_field(acc: dict, f: dict, panel: str, binder, anchors: list) -> None:
    if panel in _GAUGE_BOUNDS:
        acc["notes"].append(f"the gauge {panel} {f.get('title') or f.get('dim') or '?'} is not carried "
                            "(ThoughtSpot sets a gauge's scale on the chart)")
        return
    problem = _field_problem(f, panel)
    if problem:
        acc["notes"].append(problem)
        return
    b = binder.field(f, anchors)
    if "note" in b:
        acc["notes"].append(b["note"])
        return
    if b.get("warn"):
        acc["notes"].append(b["warn"])
    _add_field(acc, f, b, panel, binder)


def _add_field(acc: dict, f: dict, b: dict, panel: str, binder) -> None:
    """One bound field into the answer accumulator; a second use of a column is reported."""
    acc["notes"] += _binding_warnings(f, b, binder)
    if b["name"] in acc["cols"]:            # one answer carries one use per column
        acc["notes"].append(_second_use(acc, f, b))
        return
    acc["cols"].append(b["name"])
    acc["roles"].append("Values" if b["measure"] else (_ROLE_OF_PANEL.get(panel) or "Category"))
    acc["tokens"][b["name"]] = b["token"]
    if b["measure"]:
        acc["measures"].add(b["name"])
        acc["measure_outs"][b["out"]] = b["name"]
        acc["measure_fields"].append(f)
    else:
        acc["dimension_fields"].append(f)
    label = _label_for(f, b)
    if label:
        acc["labels"][b["out"]] = label


def _binding_warnings(f: dict, b: dict, binder) -> list:
    """Why a carried field may still not match Sisense: its date grain, a custom calendar, a percent."""
    out = [_field_warning(f)] if _field_warning(f) else []
    if b.get("bucketed") and binder.t.calendars.get(b["name"]):
        out.append(f"[{b['name']}] buckets by the custom calendar {binder.t.calendars[b['name']]}, "
                   "which Sisense's calendar periods may not match")
    if f.get("percent") and b["measure"] and b["name"] not in binder.t.formatted:
        out.append(f"Sisense shows {f.get('title') or b['name']} as a percent; Model column "
                   f"[{b['name']}] has no format of its own, so it would show as a plain number")
    return out


def _second_use(acc: dict, f: dict, b: dict) -> str:
    what = f.get("title") or f.get("dim") or "?"
    if acc["tokens"][b["name"]] != b["token"]:   # same column, another aggregation or grain
        return (f"{b['token']} ({what}) is not carried: the answer already uses [{b['name']}] "
                f"as {acc['tokens'][b['name']]}, and one answer carries one use per column")
    return (f"field {what} binds to [{b['name']}], which the answer already shows for "   # two Sisense fields,
            "another Sisense field, so the two show one column")                          # one Model column


def _field_problem(f: dict, panel: str):
    """Why a plotted field cannot be carried as a plain column, or None."""
    what = f.get("title") or f.get("dim") or "?"
    if f.get("disabled"):
        return f"field {what} is disabled in Sisense; not carried"
    if f.get("quick_function"):
        return f"field {what} applies the Sisense quick function {f['quick_function']}, which is not carried"
    if panel == "secondary":
        return f"the secondary value {what} is not carried"
    return None


def _field_warning(f: dict):
    """Why a carried field may not match Sisense exactly (the field stays; the tile is flagged)."""
    what = f.get("title") or f.get("dim") or "?"
    if f.get("dateTimeLevel"):
        return f"field {what} has Sisense date-time level {f['dateTimeLevel']}, which is not carried"
    if (f.get("level") or "").lower() in ("quarters", "years"):
        return (f"field {what} buckets {f['level']}, which in ThoughtSpot follow the cluster's fiscal-year start; "
                "confirm it matches Sisense's")
    if f.get("datatype") == "datetime" and not f.get("level") and f.get("kind") != "measure":
        return f"date field {what} carries no level, so the grain ThoughtSpot shows it at is not decided"
    if (f.get("level") or "").lower() == "weeks":
        start = f"starting on {f['firstday']}" if f.get("firstday") else "with the Sisense server's week start"
        return (f"field {what} buckets weeks {start}; ThoughtSpot's weekly bucket follows the cluster's "
                "week start, so confirm they match")
    return None
