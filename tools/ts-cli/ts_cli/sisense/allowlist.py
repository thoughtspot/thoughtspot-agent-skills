"""The Sisense settings ``build-liveboard --target-model`` reads, level by level (pure, no I/O).

An ALLOWLIST at every level of a dashboard export: the dashboard, each widget (with its
``options``, ``style`` and ``metadata``), each panel, and each data-model table and relation.
Every key is one of:

- READ: the converter reads it and carries what it means;
- PRESENTATION: it changes how the dashboard looks or behaves in the Sisense UI, never which
  rows or numbers a widget shows (titles, colours, menus, edit state, sharing, timestamps);
- DEFAULT: carried only at the value Sisense ships by default, because any other value changes
  the numbers (a data limit, a pie's "Others" slice, a pivot's grand totals, a script).

Anything else, or a DEFAULT key at another value, is returned as a reason, which the caller
reports NEEDS REVIEW on the widget (or on every tile, for a dashboard-level key). The sets were
built from every key that 21 real dashboard exports (201 widgets) carry; a key Sisense adds
later is refused until someone decides which list it belongs on.

A script runs in the browser and can rewrite any query (``beforequery``), so a widget or
dashboard script is refused unless nothing is left once its comments are stripped. Stripping
is deliberately naive: a comment marker inside a string can only strip MORE, and the string's
own opening quote always survives, so a script with code in it can never come back empty.
"""
from __future__ import annotations

import re
from typing import Optional

# filterRelations / filterToDatasourceMapping are read by parse_dashboard (``filter_settings``)
_DASHBOARD_READ = frozenset({"filters", "layout", "widgets", "title", "datasource", "oid", "_id",
                             "filterRelations", "filterToDatasourceMapping"})
_DASHBOARD_PRESENTATION = frozenset({
    "desc", "source", "type", "style", "previewLayout", "editing", "parentFolder",
    "allowChangeSubscription", "isPublic", "subscription", "lastPublish", "original", "lastOpened",
    "lastUpdated", "created", "owner", "userId", "shares", "instanceType", "defaultFilters",
    "settings"})
_DASHBOARD_DEFAULTS = {"dataExploration": (False, None), "hierarchies": ([], None),
                       "defaultFilterRelations": ([], None)}

_WIDGET_READ = frozenset({"oid", "title", "type", "subtype", "datasource", "metadata", "options",
                          "style", "drillToDashboardConfig", "instanceid", "dashboardid", "showNulls"})
_WIDGET_PRESENTATION = frozenset({
    "desc", "source", "lastOpened", "viewState", "_dataSourcePermission", "_toDisableOptionsList",
    "displayMenu", "realTimeRefreshing", "drilledDashboardDisplay", "aiContext", "prevSortObjects",
    "scriptConfigColors", "questQueryResult", "script_old", "currentPage", "created", "lastUpdated",
    "owner", "userId"})
_WIDGET_DEFAULTS = {"selection": (None,), "custom": ({}, None), "_drillToDashboardConfig": (None,)}

_OPTIONS_READ = frozenset({"dashboardFiltersMode"})
_OPTIONS_PRESENTATION = frozenset({
    "selector", "triggersDomready", "autoUpdateOnEveryChange", "drillToAnywhere", "supportsHierarchies",
    "disallowSelector", "previousScrollerLocation", "aiFeatures", "selectorLocked", "imageColumns",
    "hideFromWidgetList", "disableExportToCSV", "disableExportToImage", "toolbarButton",
    "disallowWidgetTitle", "title", "dataTypes"})
_OPTIONS_DEFAULTS = {"drillTarget": (None, "dummy", "")}

_METADATA_READ = frozenset({"panels", "ignore"})
_METADATA_DEFAULTS = {"usedFormulasMapping": ({}, None)}

# style keys that only draw the widget (axes, legends, colours, tab-set chrome, rich text)
_STYLE_PRESENTATION = frozenset({
    "narration", "widgetDesign", "legend", "seriesLabels", "xAxis", "yAxis", "y2Axis", "navigator",
    "subtype", "skin", "components", "indicator/numeric", "indicator/gauge", "automaticHeight",
    "scroll", "pageSize", "colors", "lineWidth", "markers", "lineStyle", "content", "labels",
    "activeTab", "showTitle", "showSeparators", "useSelectedBkg", "useUnselectedBkg", "tabsSize",
    "tabsInterval", "tabsAlignment", "selectedColor", "selectedBkgColor", "unselectedColor",
    "unselectedBkgColor", "descriptionColor", "tabCornerRadius", "showDescription", "tabs",
    "selectedWidgets", "otherTabberWidgets", "currentCard", "currentConfig", "currentCardName",
    "borders/all", "borders/grid", "borders/rows", "borders/columns", "width/content", "width/window",
    "colors/headers", "colors/rows", "colors/columns", "wordwrap/headers", "wordwrap/rows",
    "tableState", "title",
    "convolution", "dataLimits"})   # dataLimits: checked by shape in _data_limit_problems   # its one number-changing setting is checked in _convolution
# style keys that change which values are shown, at the value that changes nothing
# (dataLimits is checked against what the widget plots, in _data_limits)
_STYLE_DEFAULTS = {
    "rowsGrandTotal": (False, None),
    "columnsGrandTotal": (False, None),
}

# panel names a widget type plots or filters; anything else is a panel this converter does not read
_PANELS = {
    "indicator": {"value", "secondary", "min", "max", "filters"},
    "chart/pie": {"categories", "values", "filters"},
    "chart/bar": {"categories", "values", "break by", "filters"},
    "chart/column": {"categories", "values", "break by", "filters"},
    "chart/line": {"x-axis", "values", "break by", "filters"},
    "chart/area": {"x-axis", "values", "break by", "filters"},
    "pivot2": {"rows", "values", "columns", "filters"},
    "pivot": {"rows", "values", "columns", "filters"},
    "tablewidget": {"columns", "filters"},
    "tablewidgetagg": {"columns", "filters"},
}

_TABLE_READ = frozenset({"oid", "id", "name", "displayName", "columns", "type", "schemaName",
                         "configOptions", "expression", "tupleTransformations"})
_TABLE_PRESENTATION = frozenset({"hidden", "vTag", "isMaterialized", "description"})
# an ElastiCube build that accumulates or upserts keeps rows the warehouse table no longer has
_TABLE_DEFAULTS = {"buildBehavior": ({"type": "sync", "accumulativeConfig": None}, {"type": "sync"}, None)}
_COLUMN_READ = frozenset({"oid", "id", "name", "displayName", "type", "isCustom", "expression"})
_COLUMN_PRESENTATION = frozenset({"size", "precision", "scale", "hidden", "indexed", "semanticIndex", "description"})
_COLUMN_DEFAULTS = {"isUpsertBy": (False, None)}
# the data model and its datasets. relationType: a live model has only direct relations
# ("direct"); "regular" allows shared relation groups, which arrive as relations of three or more
# endpoints and are refused where read (Sisense docs, "Duplicating Data Models")
_DATAMODEL_READ = frozenset({"datasets", "relations", "title", "name", "oid", "_id", "type"})
_DATAMODEL_PRESENTATION = frozenset({"server", "buildDestination", "modelStatistics", "modelsLayouts",
                                     "dependencies", "analyticalEngine", "lastBuildTime", "lastSuccessfulBuildTime"})
_DATAMODEL_DEFAULTS = {"relationType": ("direct", "regular", None), "fiscal": ("system", None)}
_DATASET_READ = frozenset({"oid", "schema", "database"})
# names and the live/extract kind: which warehouse a dataset reads is compared per table (physical)
_DATASET_PRESENTATION = frozenset({"connection", "liveQuerySettings", "schemaName", "name", "fullname", "type"})
_DATASET_DEFAULTS = {"modelingTransformations": ([], None)}
_RELATION_READ = frozenset({"oid", "type", "columns"})
_ENDPOINT_READ = frozenset({"dataset", "table", "column"})
_ENDPOINT_DEFAULTS = {"isDropped": (None, False)}
# a dashboard filter object (around its jaql)
_DASH_FILTER_READ = frozenset({"jaql", "levels", "instanceid", "disabled"})
# locked / hidden: the filter still applies; isCascading / model: the UI's store for a cascading
# group, whose levels[] are read
_DASH_FILTER_PRESENTATION = frozenset({"locked", "hidden", "isCascading", "model"})
_PANEL_KEYS = frozenset({"name", "items"})
# jump-to-dashboard keys that only shape the navigation (menus, panes, window); the ones that
# change which filters reach the drill are read in parsing._DRILL_FILTER_DEFAULTS
_DRILL_PRESENTATION = frozenset({
    "drilledDashboardPrefix", "drilledDashboardsFolderPrefix", "displayFilterPane", "displayDashboardsPane",
    "displayToolbarRow", "displayHeaderRow", "volatile", "hideDrilledDashboards", "hideSharedDashboardsForNonOwner",
    "drillToDashboardMenuCaption", "drillToDashboardRightMenuCaption", "drillToDashboardNavigateType",
    "drillToDashboardNavigateTypePivot", "drillToDashboardNavigateTypeCharts", "drillToDashboardNavigateTypeOthers",
    "drilledDashboardDisplayType", "dashboardIds", "modalWindowResize", "showFolderNameOnMenuSelection",
    "showJTDIcon", "drillToDashboardByName", "enabled", "version", "dirty", "sameCubeRestriction",
    "includeFilterDims", "excludeFilterDims", "includeDashFilterDims", "excludeDashFilterDims",
    "resetDashFiltersAfterJTD", "mergeTargetDashboardFilters"})
_DRILL_DEFAULTS = {"forceZeroInsteadNull": (False, None), "sendPieChartMeasureFiltersOnClick": (True, None)}
# table transformations that leave the rows alone: an added (calculated) column, and a source
# column not imported (a binding to it already reports the column as not exposed)
_ROW_SAFE_TRANSFORMS = ("add-column", "dont-import")
_SIMPLE_IMPORT = re.compile(r'\s*select\s+\*\s+from\s+([\w"]+(?:\.[\w"]+)*)\s*;?\s*', re.I)


def _strip_comments(script: str) -> str:
    """Script text with ``/* */`` and ``//`` comments removed (see the module docstring)."""
    # a `//` comment ends at any JavaScript line terminator, not only \n
    return re.sub(r"//[^\n\r\u2028\u2029]*", "", re.sub(r"/\*.*?(\*/|$)", "", script or "", flags=re.S)).strip()


def script_problem(script) -> Optional[str]:
    if script is None or (isinstance(script, str) and not _strip_comments(script)):
        return None
    return ("it carries a script, which runs in the browser and can change the query; scripts are not read")


def _level(obj: dict, prefix: str, read, presentation, defaults: dict) -> list:
    """One level's keys -> reasons for every key not read, not presentation, or off its default."""
    out = []
    for key, value in obj.items():
        if key in read or key in presentation:
            continue
        if key in defaults:
            if value not in defaults[key]:
                out.append(f"{prefix}{key}={_short(value)}")
            continue
        out.append(f"{prefix}{key}")
    return out


def _short(value) -> str:
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def dashboard_unsupported(raw: dict) -> list:
    """Dashboard keys this converter does not read, or not at their default; a script counts."""
    out = _level({k: v for k, v in raw.items() if k != "script"}, "", _DASHBOARD_READ,
                 _DASHBOARD_PRESENTATION, _DASHBOARD_DEFAULTS)
    if script_problem(raw.get("script")):
        out.append("script")
    return sorted(out)


def widget_unsupported(widget: dict) -> list:
    """Widget keys (and options / style / metadata / panel names) this converter does not read.
    A sub-level that is not an object is itself reported (it could not be read)."""
    out = _level({k: v for k, v in widget.items() if k != "script"}, "", _WIDGET_READ,
                 _WIDGET_PRESENTATION, _WIDGET_DEFAULTS)
    if script_problem(widget.get("script")):
        out.append("script")
    for sub, read, pres, defaults in (("options", _OPTIONS_READ, _OPTIONS_PRESENTATION, _OPTIONS_DEFAULTS),
                                      ("metadata", _METADATA_READ, frozenset(), _METADATA_DEFAULTS),
                                      ("style", frozenset(), _STYLE_PRESENTATION, _STYLE_DEFAULTS)):
        value = widget.get(sub)
        if isinstance(value, dict):
            out += _level(value, f"{sub}.", read, pres, defaults)
        elif value is not None:
            out.append(f"{sub} (not an object)")
    out += _convolution(widget.get("style"))
    out += _data_limit_problems(widget.get("style"))
    out += _show_nulls(widget.get("showNulls"))
    out = _drop_read_drill_target(widget, out)
    out += _panels(widget)
    return sorted(set(out))


def _show_nulls(value) -> list:
    """``showNulls``: an undocumented per-column setting (Sisense shows null values in every
    widget by default since 8.1, as ThoughtSpot shows a {Null} group), so any value is reported."""
    if value is None or value == {}:
        return []
    return [f"showNulls={_short(value)}"]


def _drop_read_drill_target(widget: dict, out: list) -> list:
    """A pivot's ``options.drillTarget`` names the same dashboard as its jump-to-dashboard drill,
    which is read; it is only refused when it points anywhere else."""
    options, drill = widget.get("options"), widget.get("drillToDashboardConfig")
    target = options.get("drillTarget") if isinstance(options, dict) else None
    drills = (drill.get("dashboardIds") or []) if isinstance(drill, dict) else []
    if isinstance(target, dict) and any(isinstance(d, dict) and target.get("oid") in (d.get("oid"), d.get("id"))
                                        for d in drills):
        return [u for u in out if not u.startswith("options.drillTarget=")]
    return out


def _convolution(style) -> list:
    """A pie's "Others" slice (``convolution.enabled``) merges small slices; off it changes nothing."""
    conv = (style or {}).get("convolution") if isinstance(style, dict) else None
    if isinstance(conv, dict) and conv.get("enabled"):
        return ["style.convolution (small slices merged into Others)"]
    return []


_NO_PANELS = ("WidgetsTabber", "richtexteditor")


def _panels(widget: dict) -> list:
    wtype = widget.get("type") or ""
    known = _PANELS.get(wtype)
    if known is None:
        return [] if wtype in _NO_PANELS else [f"panels of widget type {wtype or '?'} (not read)"]
    panels = [p for p in _panel_list(widget) if isinstance(p, dict)]
    extra = sorted({k for p in panels for k in p if k not in _PANEL_KEYS})
    return [f"panel '{p.get('name')}'" for p in panels if p.get("name") not in known] + [f"panel key {k}" for k in extra]


def _panel_list(widget: dict) -> list:
    meta = widget.get("metadata")
    panels = meta.get("panels") if isinstance(meta, dict) else None
    return panels if isinstance(panels, list) else []


_LIMIT_KEYS = ("seriesCapacity", "categoriesCapacity")
_SERIES_DEFAULT = 50     # Sisense's own series cap on a chart; a note when a break-by is plotted


def _whole_number(v) -> bool:
    """A finite whole number (an int, or a float like 50.0); never a bool, NaN or infinity."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    return v == v and v not in (float("inf"), float("-inf")) and v == int(v)


def _data_limit_problems(style) -> list:
    """``style.dataLimits``: only the two caps, as whole numbers, are read. A category cap below
    100000 (Sisense ships 100000) or a series cap below its default of 50 cuts what Sisense shows."""
    limits = style.get("dataLimits") if isinstance(style, dict) else None
    if limits is None:
        return []
    if not isinstance(limits, dict):
        return ["style.dataLimits (not an object)"]
    out = [f"style.dataLimits.{k}" for k in limits if k not in _LIMIT_KEYS]
    for k in _LIMIT_KEYS:
        v = limits.get(k)
        if v is not None and not _whole_number(v):
            out.append(f"style.dataLimits.{k}={v!r}")
        elif v is not None and v < (100000 if k == "categoriesCapacity" else _SERIES_DEFAULT):
            out.append(f"style.dataLimits.{k}={v} (caps what Sisense shows)")
    return out


def widget_info(widget: dict) -> list:
    """Notes for the report that do not change a widget's numbers on their own."""
    return _data_limits(widget)


def _data_limits(widget: dict) -> list:
    """Sisense's series cap (50 unless set) cuts a break-by with more members than that, where
    ThoughtSpot shows them all: a note when a break-by is plotted. A cap below the default, or a
    category cap, is a problem instead (_data_limit_problems)."""
    style = widget.get("style")
    limits = style.get("dataLimits") if isinstance(style, dict) else None
    limits = {} if limits is None else limits
    if not isinstance(limits, dict):
        return []
    meta = widget.get("metadata") if isinstance(widget.get("metadata"), dict) else {}
    plotted = {p.get("name") for p in meta.get("panels") or [] if isinstance(p, dict) and p.get("items")}
    v = limits.get("seriesCapacity", _SERIES_DEFAULT)
    if not _whole_number(v) or not _SERIES_DEFAULT <= v < 100000 or "break by" not in plotted:
        return []     # below the default it is a problem (above); a huge cap cuts nothing
    default = " (Sisense's default)" if v == _SERIES_DEFAULT else ""
    return [f"Sisense shows at most {int(v)} break-by series{default}; ThoughtSpot shows them all, which "
            "differs only beyond that many"]


def table_physical(t: dict, database: str = "") -> tuple:
    """A data-model table -> (physical name | None, reason it is not a plain table | None).

    A ``base`` table reads ``database.schemaName.name`` unless its import query says otherwise;
    an import query that is ``select * from x`` reads ``x`` (in the dataset's database when ``x``
    names no database). A custom-SQL table, or an import query with anything more (a WHERE, a
    join, a column list), has rows this converter cannot compare."""
    query, problem = _import_query(t)
    if problem:
        return None, problem
    parts, problem = _query_parts(query) if query else _named_parts(t)
    if problem:
        return None, problem
    if database and len(parts) == 2:    # the dataset's database goes before schema.table only
        parts = [database] + parts
    return ".".join(str(p) for p in parts).lower(), None


def _import_query(t: dict) -> tuple:
    """-> (import query text, reason the table is not read) for a data-model table."""
    options = t.get("configOptions")
    if options is not None and not isinstance(options, dict):
        return "", "its configOptions could not be read"
    query = (options or {}).get("importQuery")
    if query is not None and not isinstance(query, str):
        return "", "its import query could not be read"
    if t.get("type") not in (None, "base"):
        return "", f"it is a {t.get('type')} table (its rows come from Sisense SQL, not a warehouse table)"
    return (query or "").strip(), None


def _query_parts(query: str) -> tuple:
    m = _SIMPLE_IMPORT.fullmatch(query)
    if not m:
        return [], "its import query is more than `select * from <table>`, so its rows are not a warehouse table's"
    return m.group(1).replace('"', "").split("."), None


def _named_parts(t: dict) -> tuple:
    """With no import query, ``id`` names the source table when it is not an opaque ``tq_`` id; an
    id differing from the name (a role copy, a renamed table) leaves the source undecided."""
    tid, name = str(t.get("id") or ""), str(t.get("name") or "")
    if tid and tid != name and not tid.startswith("tq_"):
        return [], f"its id ({tid}) and name ({name}) differ, so which warehouse table it reads is not known"
    return [p for p in (t.get("schemaName"), name) if p], None


def table_unsupported(t: dict) -> list:
    """Table keys and column keys not read (or off their default), and table transformations
    other than added columns."""
    out = _level(t, "", _TABLE_READ, _TABLE_PRESENTATION, _TABLE_DEFAULTS)
    for c in t.get("columns") or []:
        if isinstance(c, dict):
            out += [f"column {c.get('name')}: {u}" for u in _level(c, "", _COLUMN_READ, _COLUMN_PRESENTATION, _COLUMN_DEFAULTS)]
    tts = t.get("tupleTransformations") or []
    out += [f"tupleTransformations[{tt.get('type') if isinstance(tt, dict) else '?'}]"
            for tt in (tts if isinstance(tts, list) else [tts])
            if not isinstance(tt, dict) or tt.get("type") not in _ROW_SAFE_TRANSFORMS]
    options = t.get("configOptions")
    extra = sorted(set(options) - {"importQuery"}) if isinstance(options, dict) else []
    return out + [f"configOptions.{k}" for k in extra]


def relation_problem(rel: dict) -> Optional[str]:
    """A relation's join type (unset is Sisense's default, inner) and any relation or endpoint
    key not read."""
    kind = rel.get("type")
    if kind not in (None, "", "inner", "INNER"):
        return f"a relation sets join type {kind!r}, which this converter does not read"
    extra = _level(rel, "", _RELATION_READ, frozenset(), {})
    for e in rel.get("columns") or []:
        if isinstance(e, dict):
            extra += _level(e, "endpoint.", _ENDPOINT_READ, frozenset(), _ENDPOINT_DEFAULTS)
    return f"a relation sets {', '.join(extra)}, which this converter does not read" if extra else None


def datamodel_unsupported(dm: dict) -> list:
    """Data-model and dataset keys not read, or off their default."""
    out = _level(dm, "", _DATAMODEL_READ, _DATAMODEL_PRESENTATION, _DATAMODEL_DEFAULTS)
    for ds in dm.get("datasets") or []:
        if isinstance(ds, dict):
            out += _level(ds, "dataset.", _DATASET_READ, _DATASET_PRESENTATION, _DATASET_DEFAULTS)
    return sorted(set(out))


def dashboard_filter_unsupported(f: dict) -> list:
    """Keys of a dashboard filter object (around its jaql) not read."""
    return _level(f, "filter.", _DASH_FILTER_READ, _DASH_FILTER_PRESENTATION, {})


def drill_unsupported(drill: dict) -> list:
    """Jump-to-dashboard keys not read, or off their default."""
    return _level(drill, "", frozenset(), _DRILL_PRESENTATION, _DRILL_DEFAULTS) if isinstance(drill, dict) else []
