#!/usr/bin/env python3
"""
Data Objects Health Audit report generator for ts-audit.

Analyses cross-model sprawl: duplicate tables, overlapping models, table
reuse patterns, conformed dimension divergence. Produces a single self-
contained HTML file.

Usage:
    from efficiency_report import generate_efficiency_report, EfficiencyMeta

    html = generate_efficiency_report(findings, corpus_stats, meta)
"""
from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass, field
from typing import Any


SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
SEVERITY_RANK = {s: i for i, s in enumerate(reversed(SEVERITY_ORDER))}
SEVERITY_RANK["GREEN"] = 0

SEVERITY_COLORS = {
    "CRITICAL": "#dc2626",
    "HIGH": "#f97316",
    "MEDIUM": "#eab308",
    "LOW": "#3b82f6",
    "INFO": "#6b7280",
    "GREEN": "#22c55e",
}


@dataclass
class EfficiencyMeta:
    cluster_url: str = ""
    date: str = ""
    scope: str = "All connections"
    model_count: int = 0
    table_count: int = 0


@dataclass
class CorpusStats:
    """Pre-computed cross-model analysis data."""
    table_reuse: list[dict] = field(default_factory=list)
    duplicate_groups: list[dict] = field(default_factory=list)
    model_overlaps: list[dict] = field(default_factory=list)
    stale_objects: list[dict] = field(default_factory=list)
    dimension_divergence: list[dict] = field(default_factory=list)
    formula_candidates: list[dict] = field(default_factory=list)
    model_deps: list[dict] = field(default_factory=list)
    table_deps: list[dict] = field(default_factory=list)


def _esc(text: str) -> str:
    return html_mod.escape(str(text))


def _ts_url(base_url: str, guid: str | None, obj_type: str = "") -> str:
    """Build a ThoughtSpot object URL. Returns empty string if no GUID."""
    if not guid or not base_url:
        return ""
    base = base_url.rstrip("/")
    if obj_type in ("model", "LOGICAL_TABLE", "worksheet"):
        return f"{base}/#/data/tables/{guid}"
    if obj_type in ("table",):
        return f"{base}/#/data/tables/{guid}"
    return f"{base}/#/pinboard/{guid}"


def _link(text: str, url: str) -> str:
    if not url:
        return _esc(text)
    return f'<a href="{_esc(url)}" target="_blank" title="Open in ThoughtSpot">{_esc(text)}</a>'


def _obj_cell(name: str, guid: str, base_url: str, obj_type: str = "model") -> str:
    """Render a name + short GUID + link cell used throughout the report."""
    url = _ts_url(base_url, guid, obj_type)
    short_guid = f' <span class="guid">{_esc(guid[:8])}</span>' if guid else ""
    return f'{_link(name, url)}{short_guid}'


def build_corpus_stats(findings: list[dict], models: list[dict]) -> CorpusStats:
    """Extract efficiency-relevant data from findings and model TMLs."""
    stats = CorpusStats()

    # Build model GUID lookup
    model_guid_lookup: dict[str, str] = {}
    for m in models:
        mdata = m.get("model", {})
        mname = mdata.get("name", "?")
        mguid = m.get("guid", mdata.get("guid", ""))
        model_guid_lookup[mname] = mguid

    # table FQN/GUID → (display_name, guid)  from model_tables
    table_info: dict[str, dict] = {}
    table_to_models: dict[str, list[str]] = {}
    for m in models:
        mdata = m.get("model", {})
        mname = mdata.get("name", "?")
        for mt in mdata.get("model_tables", []):
            fqn = mt.get("fqn", mt.get("name", ""))
            tname = mt.get("name", fqn)
            table_to_models.setdefault(fqn, []).append(mname)
            if fqn not in table_info:
                table_info[fqn] = {"name": tname, "guid": fqn}

    for fqn, model_names in sorted(table_to_models.items(), key=lambda x: -len(x[1])):
        ti = table_info.get(fqn, {})
        stats.table_reuse.append({
            "fqn": fqn,
            "table_name": ti.get("name", fqn),
            "table_guid": ti.get("guid", ""),
            "models": model_names,
            "count": len(model_names),
            "is_shared": len(set(model_names)) > 1,
            "model_guids": {mn: model_guid_lookup.get(mn, "") for mn in set(model_names)},
        })

    for m in models:
        mdata = m.get("model", {})
        mname = mdata.get("name", "?")
        mguid = m.get("guid", mdata.get("guid", ""))
        tables = mdata.get("model_tables", [])
        stats.model_deps.append({
            "name": mname, "guid": mguid, "table_count": len(tables),
        })

    for fqn, model_names in table_to_models.items():
        unique = sorted(set(model_names))
        ti = table_info.get(fqn, {})
        tname = ti.get("name", fqn)
        short_name = tname if tname != fqn else (fqn.rsplit(".", 1)[-1] if "." in fqn else fqn)
        stats.table_deps.append({
            "fqn": fqn, "short_name": short_name,
            "table_name": tname, "table_guid": ti.get("guid", ""),
            "models": unique, "model_count": len(unique),
            "model_guids": {mn: model_guid_lookup.get(mn, "") for mn in unique},
        })

    for f in findings:
        cid = f.get("check_id")
        if cid == "D8":
            stats.duplicate_groups.append({
                "title": f["title"],
                "detail": f.get("detail", ""),
                "objects": f.get("objects", []),
                "severity": f["severity"],
            })
        elif cid == "D7":
            stats.model_overlaps.append({
                "check_name": f.get("check_name", ""),
                "title": f["title"],
                "detail": f.get("detail", ""),
                "severity": f["severity"],
                "score": f.get("score"),
                "objects": f.get("objects", []),
            })
        elif cid == "H10":
            stats.stale_objects.append({
                "check_name": f.get("check_name", ""),
                "title": f["title"],
                "detail": f.get("detail", ""),
                "severity": f["severity"],
                "model_name": f.get("model_name", ""),
                "model_guid": f.get("model_guid", ""),
            })
        elif cid == "D12":
            stats.dimension_divergence.append({
                "title": f["title"],
                "detail": f.get("detail", ""),
                "severity": f["severity"],
            })
        elif cid == "H8":
            stats.formula_candidates.append({
                "title": f["title"],
                "detail": f.get("detail", ""),
                "severity": f["severity"],
            })

    return stats


def generate_efficiency_report(
    findings: list[dict],
    models: list[dict],
    meta: EfficiencyMeta | None = None,
) -> str:
    if meta is None:
        meta = EfficiencyMeta()

    stats = build_corpus_stats(findings, models)

    shared_tables = [t for t in stats.table_reuse if t["is_shared"]]
    unique_tables = [t for t in stats.table_reuse if not t["is_shared"]]

    return _build_html(meta=meta, stats=stats, shared_tables=shared_tables,
                       unique_tables=unique_tables)


def _build_html(meta, stats, shared_tables, unique_tables):
    n_shared = len(shared_tables)
    n_unique = len(unique_tables)
    n_total = n_shared + n_unique
    n_duplicates = len(stats.duplicate_groups)
    n_overlaps = len(stats.model_overlaps)
    n_identical = sum(1 for o in stats.model_overlaps if o["check_name"] == "IDENTICAL_MODELS")
    n_stale = len(stats.stale_objects)
    n_divergence = len(stats.dimension_divergence)
    n_models_dep = len(stats.model_deps)
    n_tables_dep = len(stats.table_deps)

    stale_models = [s for s in stats.stale_objects if s.get("check_name") == "STALE_OBJECT"]
    stale_columns = [s for s in stats.stale_objects if s.get("check_name") == "STALE_COLUMNS"]

    overlap_identical = [o for o in stats.model_overlaps if o["check_name"] == "IDENTICAL_MODELS"]
    overlap_subset = [o for o in stats.model_overlaps if o["check_name"] == "MODEL_SUBSET"]
    overlap_high = [o for o in stats.model_overlaps if o["check_name"] == "MODEL_OVERLAP"]

    base_url = meta.cluster_url.rstrip("/") if meta.cluster_url else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Data Objects Health Audit — {_esc(meta.cluster_url)}</title>
<style>
{_eff_css()}
</style>
</head>
<body>

<header class="report-header">
  <h1>Data Objects Health Audit</h1>
  <p class="report-desc">Analyses cross-model sprawl: where are models duplicated, which
  physical tables have redundant ThoughtSpot objects, where do conformed dimensions diverge,
  and which objects are stale? Use this report to prioritise consolidation and cleanup.</p>
  <div class="header-meta">
    <span><b>Cluster:</b> {_esc(meta.cluster_url)}</span>
    <span><b>Date:</b> {_esc(meta.date)}</span>
    <span><b>Scope:</b> {_esc(meta.scope)}</span>
    <span><b>Models:</b> {meta.model_count}</span>
    <span><b>Physical Tables:</b> {n_total} ({n_shared} shared across models, {n_unique} single-model)</span>
  </div>
</header>

<nav class="tab-bar">
  <button class="tab active" data-tab="overview" onclick="showTab('overview')">Overview</button>
  <button class="tab" data-tab="overlaps" onclick="showTab('overlaps')">Model Overlaps ({n_overlaps})</button>
  <button class="tab" data-tab="duplicates" onclick="showTab('duplicates')">Duplicate Tables ({n_duplicates})</button>
  <button class="tab" data-tab="reuse" onclick="showTab('reuse')">Table × Model ({n_shared})</button>
  <button class="tab" data-tab="divergence" onclick="showTab('divergence')">Divergence ({n_divergence})</button>
  <button class="tab" data-tab="dependencies" onclick="showTab('dependencies')">Dependencies ({n_models_dep})</button>
  <button class="tab" data-tab="stale" onclick="showTab('stale')">Stale Objects ({n_stale})</button>
</nav>

<main class="content">

  <!-- Overview -->
  <section id="tab-overview" class="tab-content active">
    <div class="stat-grid">
      <div class="stat-card" onclick="showTab('overlaps')">
        <div class="stat-num" style="color:{SEVERITY_COLORS['HIGH']}">{n_identical}</div>
        <div class="stat-label">Identical Model Pairs</div>
        <div class="stat-sub">Same table set — consolidation candidates</div>
      </div>
      <div class="stat-card" onclick="showTab('overlaps')">
        <div class="stat-num" style="color:{SEVERITY_COLORS['MEDIUM']}">{len(overlap_subset)}</div>
        <div class="stat-label">Subset Models</div>
        <div class="stat-sub">One model's tables are a strict subset of another</div>
      </div>
      <div class="stat-card" onclick="showTab('duplicates')">
        <div class="stat-num" style="color:{SEVERITY_COLORS['HIGH']}">{n_duplicates}</div>
        <div class="stat-label">Duplicate Table Objects</div>
        <div class="stat-sub">Different TS objects → same physical table</div>
      </div>
      <div class="stat-card" onclick="showTab('reuse')">
        <div class="stat-num" style="color:{SEVERITY_COLORS['INFO']}">{n_shared}</div>
        <div class="stat-label">Shared Tables</div>
        <div class="stat-sub">Physical tables used by 2+ models</div>
      </div>
      <div class="stat-card" onclick="showTab('divergence')">
        <div class="stat-num" style="color:{SEVERITY_COLORS['MEDIUM']}">{n_divergence}</div>
        <div class="stat-label">Dimension Divergences</div>
        <div class="stat-sub">Same column classified differently across models</div>
      </div>
      <div class="stat-card" onclick="showTab('dependencies')">
        <div class="stat-num" style="color:#0284c7">{n_models_dep}</div>
        <div class="stat-label">Models Analysed</div>
        <div class="stat-sub">Dependency depth: {n_tables_dep} total tables</div>
      </div>
      <div class="stat-card" onclick="showTab('stale')">
        <div class="stat-num" style="color:{SEVERITY_COLORS['LOW']}">{n_stale}</div>
        <div class="stat-label">Stale Objects</div>
        <div class="stat-sub">Models or columns flagged for cleanup</div>
      </div>
    </div>

    <h2>Recommendations</h2>
    <div class="rec-list">
      {_render_recommendations(stats)}
    </div>
  </section>

  <!-- Model Overlaps -->
  <section id="tab-overlaps" class="tab-content">
    <h2>Model Overlaps</h2>
    <p class="section-desc">Models sharing the same underlying tables. Identical pairs are
    strong consolidation candidates. Subsets may be intentional focused models (e.g. sales-only)
    or redundant copies.</p>

    {_render_overlap_section("Identical Models", overlap_identical, base_url)}
    {_render_overlap_section("Subset Models", overlap_subset, base_url)}
    {_render_overlap_section("High Overlap (>50%)", overlap_high, base_url)}
  </section>

  <!-- Duplicate Tables -->
  <section id="tab-duplicates" class="tab-content">
    <h2>Duplicate Table Objects</h2>
    <p class="section-desc">Multiple ThoughtSpot table objects that point to the same
    physical database table. Each duplicate is a separate TS object with its own GUID.
    Consolidate to one TS object per physical table.</p>

    {_render_duplicate_tables(stats.duplicate_groups, shared_tables, base_url)}
  </section>

  <!-- Table Reuse -->
  <section id="tab-reuse" class="tab-content">
    <h2>Table × Model Matrix</h2>
    <p class="section-desc">Which physical tables are used by which models. Shared dimension
    tables (e.g. CUSTOMER, PRODUCT) are healthy. Shared fact tables may indicate model overlap.
    This is NOT duplication — one TS table object, used in multiple models.</p>

    <div class="sub-tab-bar">
      <button class="sub-tab active" data-subtab="reuse-sankey" data-group="reuse"
              onclick="showSubTab('reuse','reuse-sankey')">Sankey Chart</button>
      <button class="sub-tab" data-subtab="reuse-detail" data-group="reuse"
              onclick="showSubTab('reuse','reuse-detail')">Detail Table</button>
    </div>

    <div id="subtab-reuse-sankey" class="sub-tab-content active">
      {_render_sankey(shared_tables, base_url)}
    </div>
    <div id="subtab-reuse-detail" class="sub-tab-content">
      <input type="text" class="filter-input" placeholder="Filter by table or model name..."
             oninput="filterTable('reuse-table', this.value)">
      <table class="data-table" id="reuse-table">
        <thead><tr>
          <th>Table</th>
          <th>Models Using This Table</th>
          <th>Count</th>
        </tr></thead>
        <tbody>
          {_render_reuse_rows(shared_tables, base_url)}
        </tbody>
      </table>
    </div>
  </section>

  <!-- Divergence -->
  <section id="tab-divergence" class="tab-content">
    <h2>Conformed Dimension Divergence</h2>
    <p class="section-desc">Same physical column classified differently across models.
    Inconsistent classification means different query behaviour and confusing search results
    for end users.</p>

    {_render_divergence(stats.dimension_divergence)}
  </section>

  <!-- Dependencies -->
  <section id="tab-dependencies" class="tab-content">
    <h2>Object Dependencies</h2>
    <p class="section-desc">How many tables each model uses, and how many models use each table.
    Models with very high table counts may be too complex. Tables used by many models are
    key conformed dimensions — changes to them have wide blast radius.</p>

    <div class="sub-tab-bar">
      <button class="sub-tab active" data-subtab="dep-model-chart" data-group="dep"
              onclick="showSubTab('dep','dep-model-chart')">Tables per Model</button>
      <button class="sub-tab" data-subtab="dep-table-chart" data-group="dep"
              onclick="showSubTab('dep','dep-table-chart')">Models per Table</button>
      <button class="sub-tab" data-subtab="dep-model-detail" data-group="dep"
              onclick="showSubTab('dep','dep-model-detail')">Model Detail</button>
      <button class="sub-tab" data-subtab="dep-table-detail" data-group="dep"
              onclick="showSubTab('dep','dep-table-detail')">Shared Table Detail</button>
    </div>

    {_render_dependencies(stats, base_url)}
  </section>

  <!-- Stale Objects -->
  <section id="tab-stale" class="tab-content">
    <h2>Stale / Temporary Objects</h2>
    <p class="section-desc">Objects with names suggesting they are deprecated, temporary,
    or candidates for deletion. Cross-reference with usage data before removing.</p>

    {_render_stale(stale_models, stale_columns, base_url)}
  </section>

</main>

<script>
{_eff_js()}
</script>
</body>
</html>"""


def _render_recommendations(stats):
    recs = []
    identical = [o for o in stats.model_overlaps if o["check_name"] == "IDENTICAL_MODELS"]
    if identical:
        recs.append(
            f'<div class="rec high">'
            f'<b>Consolidate {len(identical)} identical model pairs</b> — '
            f'these have the same table set. Use <code>/ts-dependency-manager</code> '
            f'(Repoint mode) to migrate dependents to one canonical model, then delete the duplicate.</div>'
        )
    if stats.duplicate_groups:
        recs.append(
            f'<div class="rec high">'
            f'<b>Deduplicate {len(stats.duplicate_groups)} table groups</b> — '
            f'multiple TS table objects point to the same physical table. Keep one, repoint '
            f'models to use it, delete the extras.</div>'
        )
    if stats.dimension_divergence:
        recs.append(
            f'<div class="rec medium">'
            f'<b>Standardise {len(stats.dimension_divergence)} divergent dimensions</b> — '
            f'same column classified as ATTRIBUTE in some models and MEASURE in others. '
            f'Pick one classification and apply consistently.</div>'
        )
    subsets = [o for o in stats.model_overlaps if o["check_name"] == "MODEL_SUBSET"]
    if subsets:
        recs.append(
            f'<div class="rec info">'
            f'<b>Review {len(subsets)} subset models</b> — '
            f'these are strict subsets of larger models. May be intentionally focused '
            f'(sales-only, marketing-only) or may be redundant copies.</div>'
        )
    if stats.stale_objects:
        recs.append(
            f'<div class="rec low">'
            f'<b>Clean up {len(stats.stale_objects)} stale object groups</b> — '
            f'names matching patterns like "zDEL", "Copy of", "[DO NOT USE]". '
            f'Verify with usage data before removing.</div>'
        )
    if not recs:
        recs.append('<div class="rec info">No efficiency issues found.</div>')
    return "\n".join(recs)


def _render_overlap_section(title, overlaps, base_url):
    if not overlaps:
        return f'<h3>{title}</h3><p class="empty">None found.</p>'

    rows = []
    for o in overlaps:
        color = SEVERITY_COLORS.get(o["severity"], "#999")
        objs = o.get("objects", [])
        score = o.get("score")
        score_str = f"{score:.0%}" if isinstance(score, (int, float)) and score is not None else ""

        model_cells = []
        for obj in objs:
            name = obj.get("name", "?")
            guid = obj.get("guid", "")
            model_cells.append(f'{_obj_cell(name, guid, base_url, "model")}')

        rows.append(
            f'<tr>'
            f'<td style="color:{color};font-weight:700">{_esc(o["severity"])}</td>'
            f'<td>{"</td></tr><tr><td></td><td>".join(model_cells)}</td>'
            f'<td>{_esc(score_str)}</td>'
            f'<td>{_esc(o["detail"])}</td>'
            f'</tr>'
        )

    return (
        f'<h3>{title} ({len(overlaps)})</h3>'
        f'<table class="data-table"><thead><tr>'
        f'<th>Severity</th><th>Model</th><th>Overlap</th><th>Detail</th>'
        f'</tr></thead><tbody>'
        + "\n".join(rows)
        + f'</tbody></table>'
    )


def _render_duplicate_tables(groups, shared_tables, base_url):
    if not groups:
        return '<p class="empty">No duplicate table groups found.</p>'

    fqn_to_models: dict[str, list[dict]] = {}
    for t in shared_tables:
        fqn_to_models[t["fqn"]] = [
            {"name": mn, "guid": t.get("model_guids", {}).get(mn, "")}
            for mn in sorted(set(t["models"]))
        ]

    cards = []
    for g in groups:
        objs = g.get("objects", [])
        physical_fqn = g.get("detail", "")

        obj_rows = []
        for obj in objs:
            name = obj.get("name", "?")
            guid = obj.get("guid", "")
            obj_rows.append(
                f'<tr><td>{_obj_cell(name, guid, base_url, "table")}</td></tr>'
            )

        model_entries = fqn_to_models.get(physical_fqn, [])
        model_list = ", ".join(
            _obj_cell(me["name"], me["guid"], base_url, "model")
            for me in model_entries[:10]
        )
        if len(model_entries) > 10:
            model_list += f" (+{len(model_entries)-10} more)"

        cards.append(
            f'<div class="dup-card">'
            f'<div class="dup-header">'
            f'<span class="dup-table mono">{_esc(physical_fqn)}</span>'
            f'</div>'
            f'<div class="dup-body">'
            f'<div class="dup-section">'
            f'<div class="dup-label">TS Table Objects ({len(objs)})</div>'
            f'<table class="inner-table"><tbody>{"".join(obj_rows)}</tbody></table>'
            f'</div>'
            f'<div class="dup-section">'
            f'<div class="dup-label">Used by Models ({len(model_entries)})</div>'
            f'<div class="dup-models">{model_list if model_entries else "<em>Not in any scoped model</em>"}</div>'
            f'</div>'
            f'</div>'
            f'</div>'
        )

    return "\n".join(cards)


def _render_reuse_rows(shared_tables, base_url):
    rows = []
    for t in sorted(shared_tables, key=lambda x: -x["count"]):
        unique_models = sorted(set(t["models"]))
        tname = t.get("table_name", "")
        tguid = t.get("table_guid", "")
        model_cells = []
        for mn in unique_models:
            mguid = t.get("model_guids", {}).get(mn, "")
            model_cells.append(_obj_cell(mn, mguid, base_url, "model"))
        rows.append(
            f'<tr>'
            f'<td>{_obj_cell(tname, tguid, base_url, "table")}</td>'
            f'<td>{", ".join(model_cells)}</td>'
            f'<td class="center"><b>{len(unique_models)}</b></td>'
            f'</tr>'
        )
    return "\n".join(rows)


def _render_sankey(shared_tables, base_url):
    """Render an SVG Sankey diagram: tables (left) → models (right)."""
    if not shared_tables:
        return '<p class="empty">No shared tables to visualise.</p>'

    tables_sorted = sorted(shared_tables, key=lambda x: -x["count"])[:25]

    all_models: dict[str, int] = {}
    for t in tables_sorted:
        for mn in set(t["models"]):
            all_models[mn] = all_models.get(mn, 0) + 1
    models_sorted = sorted(all_models.items(), key=lambda x: -x[1])

    n_tables = len(tables_sorted)
    n_models = len(models_sorted)
    n_max = max(n_tables, n_models)

    row_h = 28
    pad_top = 30
    chart_h = n_max * row_h + pad_top + 20
    left_x = 220
    right_x = 680
    col_w = 8
    svg_w = 900

    table_y: dict[str, float] = {}
    table_label_data: list[tuple[str, str, str, float]] = []
    for i, t in enumerate(tables_sorted):
        y = pad_top + i * (chart_h - pad_top - 20) / max(n_tables - 1, 1) if n_tables > 1 else chart_h / 2
        tname = t.get("table_name", t["fqn"])
        tguid = t.get("table_guid", "")
        table_y[t["fqn"]] = y
        table_label_data.append((tname, tguid, t["fqn"], y))

    model_y: dict[str, float] = {}
    model_label_data: list[tuple[str, str, float]] = []
    for i, (mn, _cnt) in enumerate(models_sorted):
        y = pad_top + i * (chart_h - pad_top - 20) / max(n_models - 1, 1) if n_models > 1 else chart_h / 2
        model_y[mn] = y
        mguid = ""
        for t in tables_sorted:
            mguid = t.get("model_guids", {}).get(mn, "")
            if mguid:
                break
        model_label_data.append((mn, mguid, y))

    # colour palette for flows
    COLORS = ["#0284c7", "#7c3aed", "#059669", "#d97706", "#dc2626",
              "#6366f1", "#0891b2", "#84cc16", "#e11d48", "#8b5cf6"]

    elements = []
    # flows
    for ti, t in enumerate(tables_sorted):
        color = COLORS[ti % len(COLORS)]
        for mn in sorted(set(t["models"])):
            if mn not in model_y:
                continue
            ty = table_y[t["fqn"]]
            my = model_y[mn]
            cx1 = left_x + col_w + (right_x - left_x - col_w) * 0.35
            cx2 = left_x + col_w + (right_x - left_x - col_w) * 0.65
            elements.append(
                f'<path d="M{left_x + col_w},{ty} C{cx1},{ty} {cx2},{my} {right_x},{my}" '
                f'fill="none" stroke="{color}" stroke-width="2" opacity="0.25" '
                f'class="sankey-flow"/>'
            )

    # table labels (left)
    for tname, tguid, _fqn, y in table_label_data:
        trunc = (tname[:24] + "..") if len(tname) > 26 else tname
        url = _ts_url(base_url, tguid, "table")
        short_g = f' [{tguid[:8]}]' if tguid else ""
        if url:
            elements.append(
                f'<a href="{_esc(url)}" target="_blank">'
                f'<text x="{left_x - 8}" y="{y + 4}" text-anchor="end" font-size="11" '
                f'fill="#0284c7" class="sankey-label">{_esc(trunc)}'
                f'<tspan fill="#94a3b8" font-size="9">{_esc(short_g)}</tspan></text></a>'
            )
        else:
            elements.append(
                f'<text x="{left_x - 8}" y="{y + 4}" text-anchor="end" font-size="11" '
                f'fill="#334155">{_esc(trunc)}'
                f'<tspan fill="#94a3b8" font-size="9">{_esc(short_g)}</tspan></text>'
            )
        elements.append(
            f'<rect x="{left_x}" y="{y - 5}" width="{col_w}" height="10" rx="2" fill="#0284c7" opacity="0.7"/>'
        )

    # model labels (right)
    for mn, mguid, y in model_label_data:
        trunc = (mn[:24] + "..") if len(mn) > 26 else mn
        url = _ts_url(base_url, mguid, "model")
        short_g = f' [{mguid[:8]}]' if mguid else ""
        elements.append(
            f'<rect x="{right_x}" y="{y - 5}" width="{col_w}" height="10" rx="2" fill="#7c3aed" opacity="0.7"/>'
        )
        if url:
            elements.append(
                f'<a href="{_esc(url)}" target="_blank">'
                f'<text x="{right_x + col_w + 8}" y="{y + 4}" font-size="11" '
                f'fill="#0284c7" class="sankey-label">{_esc(trunc)}'
                f'<tspan fill="#94a3b8" font-size="9">{_esc(short_g)}</tspan></text></a>'
            )
        else:
            elements.append(
                f'<text x="{right_x + col_w + 8}" y="{y + 4}" font-size="11" '
                f'fill="#334155">{_esc(trunc)}'
                f'<tspan fill="#94a3b8" font-size="9">{_esc(short_g)}</tspan></text>'
            )

    # column headers
    elements.insert(0,
        f'<text x="{left_x}" y="16" font-size="12" font-weight="700" fill="#64748b">TABLES</text>'
        f'<text x="{right_x}" y="16" font-size="12" font-weight="700" fill="#64748b">MODELS</text>'
    )

    return (
        f'<div class="sankey-wrap" style="overflow-x:auto">'
        f'<svg width="{svg_w}" height="{chart_h}" xmlns="http://www.w3.org/2000/svg" '
        f'style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif">'
        + "\n".join(elements)
        + f'</svg></div>'
    )


def _render_divergence(divergences):
    if not divergences:
        return '<p class="empty">No dimension divergences found.</p>'

    cards = []
    for d in divergences:
        color = SEVERITY_COLORS.get(d["severity"], "#999")
        column_name = d["title"].replace("Divergent classification: ", "")
        detail = d["detail"]

        classification_rows = []
        parts = re.split(r";\s*", detail)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            match = re.match(r"(ATTRIBUTE|MEASURE|FORMULA)\s+in\s+(.*)", part)
            if match:
                col_type = match.group(1)
                model_list = match.group(2)
                badge_cls = "attr" if col_type == "ATTRIBUTE" else "meas" if col_type == "MEASURE" else "form"
                classification_rows.append(
                    f'<tr>'
                    f'<td><span class="type-badge {badge_cls}">{_esc(col_type)}</span></td>'
                    f'<td>{_esc(model_list)}</td>'
                    f'</tr>'
                )
            else:
                classification_rows.append(f'<tr><td colspan="2">{_esc(part)}</td></tr>')

        cards.append(
            f'<div class="div-card">'
            f'<div class="div-header">'
            f'<span class="div-col">{_esc(column_name)}</span>'
            f'<span class="sev-pill" style="background:{color}">{_esc(d["severity"])}</span>'
            f'</div>'
            f'<table class="inner-table"><thead><tr>'
            f'<th>Classification</th><th>Models</th>'
            f'</tr></thead><tbody>'
            + "\n".join(classification_rows)
            + f'</tbody></table>'
            f'</div>'
        )

    return "\n".join(cards)


def _render_bar_chart(items: list[tuple[str, int, str, str]], title: str,
                      bar_color: str = "#0284c7", max_bars: int = 40,
                      base_url: str = "", obj_type: str = "model") -> str:
    """Render a horizontal SVG bar chart. items = [(label, value, guid, fqn_or_extra), ...]."""
    if not items:
        return ""
    items = sorted(items, key=lambda x: -x[1])[:max_bars]
    max_val = max(v for _, v, _, _ in items)
    if max_val == 0:
        return ""

    row_h = 26
    label_w = 240
    bar_area_w = 360
    chart_w = label_w + bar_area_w + 60
    chart_h = len(items) * row_h + 30

    rows = []
    for i, (label, val, guid, _extra) in enumerate(items):
        y = i * row_h + 24
        bar_w = int((val / max_val) * bar_area_w) if max_val else 0
        trunc_label = (label[:26] + "..") if len(label) > 28 else label
        short_g = f" [{guid[:8]}]" if guid else ""
        url = _ts_url(base_url, guid, obj_type)

        if url:
            rows.append(
                f'<a href="{_esc(url)}" target="_blank">'
                f'<text x="{label_w - 8}" y="{y}" text-anchor="end" '
                f'font-size="11" fill="#0284c7">{_esc(trunc_label)}'
                f'<tspan fill="#94a3b8" font-size="9">{_esc(short_g)}</tspan></text></a>'
            )
        else:
            rows.append(
                f'<text x="{label_w - 8}" y="{y}" text-anchor="end" '
                f'font-size="11" fill="#334155">{_esc(trunc_label)}'
                f'<tspan fill="#94a3b8" font-size="9">{_esc(short_g)}</tspan></text>'
            )
        rows.append(
            f'<rect x="{label_w}" y="{y - 12}" width="{bar_w}" height="18" '
            f'rx="3" fill="{bar_color}" opacity="0.85"/>'
            f'<text x="{label_w + bar_w + 6}" y="{y}" font-size="12" '
            f'fill="#64748b" font-weight="600">{val}</text>'
        )

    return (
        f'<svg width="{chart_w}" height="{chart_h}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif">'
        + "\n".join(rows)
        + f'</svg>'
    )


def _render_dependencies(stats: CorpusStats, base_url: str) -> str:
    parts = []

    # Sub-tab 1: Tables per Model (chart)
    model_items = [(d["name"], d["table_count"], d["guid"], "")
                   for d in stats.model_deps]
    parts.append(
        f'<div id="subtab-dep-model-chart" class="sub-tab-content active">'
        + _render_bar_chart(model_items, "Tables per Model",
                            bar_color="#0284c7", max_bars=50,
                            base_url=base_url, obj_type="model")
        + f'</div>'
    )

    # Sub-tab 2: Models per Table (chart)
    table_items = [(d["short_name"], d["model_count"], d["table_guid"], d["fqn"])
                   for d in stats.table_deps if d["model_count"] > 1]
    parts.append(
        f'<div id="subtab-dep-table-chart" class="sub-tab-content">'
        + _render_bar_chart(table_items, "Models per Table (shared tables only)",
                            bar_color="#7c3aed", max_bars=50,
                            base_url=base_url, obj_type="table")
        + f'</div>'
    )

    # Sub-tab 3: Model Detail (table)
    model_rows = []
    for d in sorted(stats.model_deps, key=lambda x: -x["table_count"]):
        model_rows.append(
            f'<tr>'
            f'<td>{_obj_cell(d["name"], d["guid"], base_url, "model")}</td>'
            f'<td class="center"><b>{d["table_count"]}</b></td>'
            f'</tr>'
        )
    parts.append(
        f'<div id="subtab-dep-model-detail" class="sub-tab-content">'
        f'<input type="text" class="filter-input" placeholder="Filter models..."'
        f' oninput="filterTable(\'dep-model-table\', this.value)">'
        f'<table class="data-table" id="dep-model-table"><thead><tr>'
        f'<th>Model</th><th>Tables</th>'
        f'</tr></thead><tbody>'
        + "\n".join(model_rows)
        + f'</tbody></table></div>'
    )

    # Sub-tab 4: Shared Table Detail (table)
    table_rows = []
    for d in sorted(stats.table_deps, key=lambda x: -x["model_count"]):
        if d["model_count"] < 2:
            continue
        model_cells = []
        for mn in d["models"][:10]:
            mguid = d.get("model_guids", {}).get(mn, "")
            model_cells.append(_obj_cell(mn, mguid, base_url, "model"))
        extra = f" (+{len(d['models']) - 10} more)" if len(d["models"]) > 10 else ""
        table_rows.append(
            f'<tr>'
            f'<td>{_obj_cell(d["table_name"], d["table_guid"], base_url, "table")}</td>'
            f'<td class="center"><b>{d["model_count"]}</b></td>'
            f'<td>{", ".join(model_cells)}{_esc(extra)}</td>'
            f'</tr>'
        )

    if table_rows:
        parts.append(
            f'<div id="subtab-dep-table-detail" class="sub-tab-content">'
            f'<input type="text" class="filter-input" placeholder="Filter tables..."'
            f' oninput="filterTable(\'dep-table-table\', this.value)">'
            f'<table class="data-table" id="dep-table-table"><thead><tr>'
            f'<th>Table</th><th>Models</th><th>Used By</th>'
            f'</tr></thead><tbody>'
            + "\n".join(table_rows)
            + f'</tbody></table></div>'
        )
    else:
        parts.append(
            f'<div id="subtab-dep-table-detail" class="sub-tab-content">'
            f'<p class="empty">No shared tables found.</p></div>'
        )

    return "\n".join(parts)


def _render_stale(stale_models, stale_columns, base_url):
    if not stale_models and not stale_columns:
        return '<p class="empty">No stale objects found.</p>'

    parts = []

    if stale_models:
        rows = []
        for s in stale_models:
            title = s["title"]
            obj_name = re.sub(r"^Stale \w+: ", "", title)
            model_guid = s.get("model_guid", "")
            rows.append(
                f'<tr>'
                f'<td>{_obj_cell(obj_name, model_guid, base_url, "model")}</td>'
                f'<td>{_esc(s["detail"])}</td>'
                f'</tr>'
            )
        parts.append(
            f'<h3>Stale Models ({len(stale_models)})</h3>'
            f'<p class="section-desc">Models with names suggesting they are deprecated copies, '
            f'test instances, or marked for deletion.</p>'
            f'<table class="data-table"><thead><tr>'
            f'<th>Model</th><th>Pattern</th>'
            f'</tr></thead><tbody>'
            + "\n".join(rows)
            + f'</tbody></table>'
        )

    if stale_columns:
        rows = []
        for s in stale_columns:
            model_name = s.get("model_name", "—")
            model_guid = s.get("model_guid", "")
            rows.append(
                f'<tr>'
                f'<td>{_obj_cell(model_name, model_guid, base_url, "model")}</td>'
                f'<td>{_esc(s["title"])}</td>'
                f'<td>{_esc(s["detail"])}</td>'
                f'</tr>'
            )
        parts.append(
            f'<h3>Stale Columns ({len(stale_columns)})</h3>'
            f'<p class="section-desc">Columns within models that have names suggesting '
            f'deprecation (e.g. zDEL_, [DO NOT USE]).</p>'
            f'<table class="data-table"><thead><tr>'
            f'<th>Model</th><th>Finding</th><th>Pattern</th>'
            f'</tr></thead><tbody>'
            + "\n".join(rows)
            + f'</tbody></table>'
        )

    return "\n".join(parts)


def _eff_css():
    return """
:root {
  --bg: #f8fafc;
  --card-bg: #fff;
  --border: #e2e8f0;
  --text: #1e293b;
  --text-secondary: #64748b;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--font); color: var(--text); background: var(--bg); font-size: 14px; line-height: 1.5; max-width: 1200px; margin: 0 auto; padding: 24px; }

.report-header { margin-bottom: 16px; padding-bottom: 12px; border-bottom: 2px solid var(--border); }
.report-header h1 { font-size: 22px; margin-bottom: 4px; }
.report-desc { font-size: 13px; color: var(--text-secondary); margin-bottom: 10px; line-height: 1.4; }
.header-meta { display: flex; flex-wrap: wrap; gap: 4px 20px; font-size: 13px; color: var(--text-secondary); }

.tab-bar { display: flex; gap: 4px; margin-bottom: 20px; flex-wrap: wrap; }
.tab { padding: 8px 16px; border: 1px solid var(--border); border-radius: 6px; background: var(--card-bg); cursor: pointer; font-size: 13px; font-weight: 500; transition: all .15s; }
.tab:hover { background: #f1f5f9; }
.tab.active { background: #0284c7; color: #fff; border-color: #0284c7; }

.tab-content { display: none; }
.tab-content.active { display: block; }
.tab-content h2 { font-size: 18px; margin-bottom: 8px; }
.tab-content h3 { font-size: 15px; margin: 16px 0 8px; }
.section-desc { color: var(--text-secondary); font-size: 13px; margin-bottom: 16px; }
.empty { color: var(--text-secondary); font-style: italic; }

/* Sub-tabs (within a section) */
.sub-tab-bar { display: flex; gap: 4px; margin-bottom: 16px; }
.sub-tab { padding: 6px 14px; border: 1px solid var(--border); border-radius: 5px; background: var(--card-bg); cursor: pointer; font-size: 12px; font-weight: 500; transition: all .15s; }
.sub-tab:hover { background: #f1f5f9; }
.sub-tab.active { background: #334155; color: #fff; border-color: #334155; }
.sub-tab-content { display: none; }
.sub-tab-content.active { display: block; }

.stat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin-bottom: 24px; }
.stat-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; cursor: pointer; transition: box-shadow .15s; }
.stat-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.08); }
.stat-num { font-size: 32px; font-weight: 800; line-height: 1.1; }
.stat-label { font-size: 14px; font-weight: 600; margin-top: 4px; }
.stat-sub { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }

.rec-list { display: flex; flex-direction: column; gap: 8px; }
.rec { padding: 10px 14px; border-radius: 6px; font-size: 13px; }
.rec.high { background: #fff7ed; border-left: 4px solid #f97316; }
.rec.medium { background: #fefce8; border-left: 4px solid #eab308; }
.rec.low { background: #eff6ff; border-left: 4px solid #3b82f6; }
.rec.info { background: #f9fafb; border-left: 4px solid #6b7280; }
.rec code { background: #f1f5f9; padding: 1px 4px; border-radius: 3px; font-size: 12px; }

.data-table { width: 100%; border-collapse: collapse; background: var(--card-bg); border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); font-size: 13px; margin-bottom: 16px; }
.data-table th { padding: 8px 10px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: .5px; color: var(--text-secondary); background: #f8fafc; border-bottom: 1px solid var(--border); }
.data-table td { padding: 6px 10px; border-bottom: 1px solid #f1f5f9; }
.data-table .mono { font-family: 'SF Mono', Consolas, monospace; font-size: 12px; }
.data-table .center { text-align: center; }
.data-table a { color: #0284c7; text-decoration: none; }
.data-table a:hover { text-decoration: underline; }

.guid { font-family: 'SF Mono', Consolas, monospace; font-size: 11px; color: var(--text-secondary); }

.filter-input { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; width: 300px; margin-bottom: 10px; }

/* Duplicate table cards */
.dup-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 12px; overflow: hidden; }
.dup-header { padding: 10px 14px; background: #f8fafc; border-bottom: 1px solid var(--border); }
.dup-table { font-size: 13px; font-weight: 600; }
.dup-body { padding: 10px 14px; display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.dup-section { }
.dup-label { font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: var(--text-secondary); margin-bottom: 4px; font-weight: 600; }
.dup-models { font-size: 13px; }
.inner-table { width: 100%; font-size: 13px; }
.inner-table td { padding: 3px 0; border: none; }
.inner-table th { padding: 3px 0; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: var(--text-secondary); border: none; }
.inner-table a { color: #0284c7; text-decoration: none; }
.inner-table a:hover { text-decoration: underline; }

/* Divergence cards */
.div-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 10px; overflow: hidden; }
.div-header { padding: 8px 14px; background: #f8fafc; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
.div-col { font-weight: 600; font-size: 14px; }
.sev-pill { color: #fff; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 10px; }
.type-badge { display: inline-block; font-size: 11px; font-weight: 600; padding: 1px 6px; border-radius: 3px; }
.type-badge.attr { background: #dbeafe; color: #1d4ed8; }
.type-badge.meas { background: #fef3c7; color: #92400e; }
.type-badge.form { background: #e0e7ff; color: #3730a3; }

/* Sankey */
.sankey-wrap { margin-bottom: 16px; }
.sankey-label { cursor: pointer; }
.sankey-label:hover { text-decoration: underline; }
.sankey-flow:hover { opacity: 0.6 !important; stroke-width: 3 !important; }
"""


def _eff_js():
    return """
function showTab(name) {
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  const el = document.getElementById('tab-' + name);
  if (el) el.classList.add('active');
  document.querySelectorAll('.tab').forEach(t => {
    if (t.dataset.tab === name) t.classList.add('active');
  });
}

function showSubTab(group, name) {
  document.querySelectorAll('.sub-tab[data-group="' + group + '"]').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.sub-tab[data-group="' + group + '"]').forEach(t => {
    if (t.dataset.subtab === name) t.classList.add('active');
  });
  var parent = document.querySelector('.sub-tab[data-subtab="' + name + '"]');
  if (parent) {
    var section = parent.closest('.tab-content');
    if (section) {
      section.querySelectorAll('.sub-tab-content').forEach(c => c.classList.remove('active'));
      var target = document.getElementById('subtab-' + name);
      if (target) target.classList.add('active');
    }
  }
}

function filterTable(tableId, query) {
  const q = query.toLowerCase();
  const table = document.getElementById(tableId);
  if (!table) return;
  table.querySelectorAll('tbody tr').forEach(row => {
    const text = row.textContent.toLowerCase();
    row.style.display = (q && !text.includes(q)) ? 'none' : '';
  });
}
"""
