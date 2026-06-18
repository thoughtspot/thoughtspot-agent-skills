#!/usr/bin/env python3
"""
HTML report generator for ts-dependency-audit.

Takes findings from the analyzer and produces a single self-contained HTML file
with three views: cluster heatmap, model scorecard, and by-check detail.

Usage:
    from report import generate_html_report

    html = generate_html_report(findings, meta)
    Path("audit_report.html").write_text(html)
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass, asdict
from typing import Any


ANGLE_LABELS = {
    "A": "AI Readiness",
    "D": "Data Modeling",
    "H": "Human Readiness",
    "P": "Performance",
    "S": "Security",
}

SEVERITY_ORDER = ["CRITICAL", "RED", "HIGH", "MEDIUM", "YELLOW", "LOW", "INFO", "GREEN"]
SEVERITY_RANK = {s: i for i, s in enumerate(reversed(SEVERITY_ORDER))}

SEVERITY_COLORS = {
    "CRITICAL": "#dc2626",
    "RED": "#ef4444",
    "HIGH": "#f97316",
    "MEDIUM": "#eab308",
    "YELLOW": "#eab308",
    "LOW": "#3b82f6",
    "INFO": "#6b7280",
    "GREEN": "#22c55e",
}

SEVERITY_BG = {
    "CRITICAL": "#fef2f2",
    "RED": "#fef2f2",
    "HIGH": "#fff7ed",
    "MEDIUM": "#fefce8",
    "YELLOW": "#fefce8",
    "LOW": "#eff6ff",
    "INFO": "#f9fafb",
    "GREEN": "#f0fdf4",
}


@dataclass
class ReportMeta:
    profile_name: str = ""
    cluster_url: str = ""
    date: str = ""
    audit_profile: str = "Spotter-ready"
    scope: str = "All connections"
    angles: list[str] | None = None
    model_count: int = 0


def _esc(text: str) -> str:
    return html.escape(str(text))


def _worst_severity(severities: list[str]) -> str:
    best = "GREEN"
    for s in severities:
        if SEVERITY_RANK.get(s, 0) > SEVERITY_RANK.get(best, 0):
            best = s
    return best


def _model_stats(findings: list[dict], model_name: str) -> dict:
    mf = [f for f in findings if f.get("model_name") == model_name]
    by_angle: dict[str, str] = {}
    for f in mf:
        angle = f["angle"]
        sev = f["severity"]
        current = by_angle.get(angle, "GREEN")
        if SEVERITY_RANK.get(sev, 0) > SEVERITY_RANK.get(current, 0):
            by_angle[angle] = sev
    return {
        "count": len(mf),
        "by_angle": by_angle,
        "worst": _worst_severity([f["severity"] for f in mf]) if mf else "GREEN",
    }


def generate_html_report(
    findings: list[dict[str, Any]],
    meta: ReportMeta | None = None,
) -> str:
    if meta is None:
        meta = ReportMeta()
    angles = meta.angles or sorted(set(f["angle"] for f in findings))

    model_names = sorted(set(
        f["model_name"] for f in findings if f.get("model_name")
    ))

    model_data = {}
    for mn in model_names:
        model_data[mn] = _model_stats(findings, mn)

    sorted_models = sorted(
        model_names,
        key=lambda mn: SEVERITY_RANK.get(model_data[mn]["worst"], 0),
        reverse=True,
    )

    check_ids = sorted(set(f["check_id"] for f in findings))
    checks_data: dict[str, list[dict]] = {}
    for cid in check_ids:
        checks_data[cid] = [f for f in findings if f["check_id"] == cid]

    sev_counts = {}
    for f in findings:
        s = f["severity"]
        sev_counts[s] = sev_counts.get(s, 0) + 1

    findings_json = json.dumps(findings, default=str)
    models_json = json.dumps(model_data, default=str)
    meta_json = json.dumps(asdict(meta) if hasattr(meta, '__dataclass_fields__') else {}, default=str)

    return _build_html(
        findings=findings,
        findings_json=findings_json,
        models_json=models_json,
        meta_json=meta_json,
        meta=meta,
        angles=angles,
        sorted_models=sorted_models,
        model_data=model_data,
        checks_data=checks_data,
        sev_counts=sev_counts,
        check_ids=check_ids,
    )


def _build_html(**ctx) -> str:
    meta = ctx["meta"]
    findings = ctx["findings"]
    angles = ctx["angles"]
    sorted_models = ctx["sorted_models"]
    model_data = ctx["model_data"]
    checks_data = ctx["checks_data"]
    sev_counts = ctx["sev_counts"]
    check_ids = ctx["check_ids"]

    total = len(findings)
    critical = sev_counts.get("CRITICAL", 0)
    high = sev_counts.get("HIGH", 0) + sev_counts.get("RED", 0)
    medium = sev_counts.get("MEDIUM", 0) + sev_counts.get("YELLOW", 0)

    heatmap_rows = _render_heatmap_rows(sorted_models, model_data, angles)
    model_cards = _render_model_cards(sorted_models, findings, angles)
    check_summary = _render_check_summary(check_ids, checks_data)
    check_tables = _render_check_tables(check_ids, checks_data)
    sidebar_models = _render_sidebar_models(sorted_models, model_data)
    sidebar_checks = _render_sidebar_checks(check_ids, checks_data, angles)

    angle_headers = "".join(
        f'<th class="heatmap-th angle-header" data-angle="{a}">'
        f'<a href="#checks-{a}" onclick="showView(\'checks\', \'{a}\')">{ANGLE_LABELS.get(a, a)}</a></th>'
        for a in angles
    )

    sev_badges = "".join(
        f'<a href="#" class="sev-badge" style="background:{SEVERITY_COLORS.get(s, "#999")}"'
        f" onclick=\"filterBySeverity('{s}'); return false;\">"
        f'{s}: {sev_counts.get(s, 0)}</a>'
        for s in SEVERITY_ORDER if sev_counts.get(s, 0)
    )

    sev_toggles = []
    for s in SEVERITY_ORDER:
        if sev_counts.get(s, 0):
            color = SEVERITY_COLORS.get(s, "#999")
            sev_toggles.append(
                f'<label class="sev-toggle">'
                f"<input type=\"checkbox\" checked onchange=\"toggleSeverity('{s}')\" data-sev=\"{s}\">"
                f'<span class="sev-chip" style="background:{color}">{s}</span></label>'
            )
    sev_toggles_html = "".join(sev_toggles)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ThoughtSpot Audit Report — {_esc(meta.profile_name)}</title>
<style>
{_css()}
</style>
</head>
<body>
<div class="layout">

<nav class="sidebar" id="sidebar">
  <div class="sidebar-header">
    <h2>Audit Report</h2>
    <div class="meta-small">
      <div>{_esc(meta.cluster_url or meta.profile_name)}</div>
      <div>{_esc(meta.date)}</div>
    </div>
  </div>

  <div class="sidebar-section">
    <a href="#" onclick="showView('heatmap'); return false;" class="nav-link active" id="nav-heatmap">
      Cluster Heatmap</a>
  </div>

  <div class="sidebar-section">
    <div class="sidebar-label">Severity</div>
    <div class="sev-summary">{sev_badges}</div>
  </div>

  <div class="sidebar-section">
    <div class="sidebar-label">Checks by Angle</div>
    {sidebar_checks}
  </div>

  <div class="sidebar-section">
    <div class="sidebar-label">Models ({len(sorted_models)})</div>
    <input type="text" id="sidebar-model-filter" placeholder="Filter models..."
           class="filter-input" oninput="filterSidebarModels(this.value)">
    <div id="sidebar-model-list">
      {sidebar_models}
    </div>
  </div>
</nav>

<main class="content">

  <header class="report-header">
    <h1>ThoughtSpot Environment Audit Report</h1>
    <div class="header-meta">
      <div class="meta-row"><span class="meta-label">Cluster:</span> {_esc(meta.cluster_url or meta.profile_name)}</div>
      <div class="meta-row"><span class="meta-label">Date:</span> {_esc(meta.date)}</div>
      <div class="meta-row"><span class="meta-label">Audit Profile:</span> {_esc(meta.audit_profile)}</div>
      <div class="meta-row"><span class="meta-label">Scope:</span> {_esc(meta.scope)}</div>
      <div class="meta-row"><span class="meta-label">Angles:</span> {', '.join(f'{a} ({ANGLE_LABELS.get(a, a)})' for a in angles)}</div>
      <div class="meta-row"><span class="meta-label">Models:</span> {meta.model_count}
        &nbsp;&nbsp; <span class="meta-label">Findings:</span> {total}
        &nbsp;&nbsp; <span class="meta-label">CRITICAL:</span> {critical}
        &nbsp;&nbsp; <span class="meta-label">HIGH:</span> {high}</div>
    </div>
  </header>

  <!-- View 1: Cluster Heatmap -->
  <section id="view-heatmap" class="view active">
    <h2>Cluster Heatmap</h2>
    <div class="controls">
      <input type="text" id="heatmap-filter" placeholder="Filter models..."
             class="filter-input" oninput="filterHeatmap(this.value)">
      <div class="sev-toggles">
        {sev_toggles_html}
      </div>
    </div>
    <div class="table-wrap">
    <table class="heatmap-table">
      <thead>
        <tr>
          <th class="heatmap-th model-col">Model</th>
          {angle_headers}
          <th class="heatmap-th">Overall</th>
        </tr>
      </thead>
      <tbody id="heatmap-body">
        {heatmap_rows}
      </tbody>
    </table>
    </div>
  </section>

  <!-- View 2: Model Scorecards -->
  <section id="view-model" class="view">
    {model_cards}
  </section>

  <!-- View 3: By-Check Detail -->
  <section id="view-checks" class="view">
    <h2>Checks Overview</h2>
    {check_summary}
    <h2 style="margin-top:24px">Check Detail</h2>
    {check_tables}
  </section>

</main>

</div>

<script>
const FINDINGS = {ctx["findings_json"]};
const MODEL_DATA = {ctx["models_json"]};
const META = {ctx["meta_json"]};
const SEV_RANK = {json.dumps(SEVERITY_RANK)};

{_js()}
</script>
</body>
</html>"""


def _render_heatmap_rows(models, model_data, angles):
    rows = []
    for mn in models:
        md = model_data[mn]
        worst = md["worst"]
        cells = []
        for a in angles:
            sev = md["by_angle"].get(a, "GREEN")
            color = SEVERITY_COLORS.get(sev, "#22c55e")
            bg = SEVERITY_BG.get(sev, "#f0fdf4")
            cells.append(
                f'<td class="heatmap-cell" style="background:{bg};color:{color};'
                f'border-left:3px solid {color}" data-sev="{sev}"'
                f" onclick=\"showModel('{_esc(mn)}', '{a}')\">"
                f'{sev}</td>'
            )
        worst_color = SEVERITY_COLORS.get(worst, "#22c55e")
        worst_bg = SEVERITY_BG.get(worst, "#f0fdf4")
        rows.append(
            f'<tr class="heatmap-row" data-model="{_esc(mn)}" data-worst="{worst}">'
            f'<td class="model-name-cell">'
            f'<a href="#" onclick="showModel(\'{_esc(mn)}\'); return false;">{_esc(mn)}</a></td>'
            + "".join(cells)
            + f'<td class="findings-count" style="background:{worst_bg};color:{worst_color};'
            f'border-left:3px solid {worst_color}">'
            f'{worst} <span class="count-num">({md["count"]})</span></td>'
            f'</tr>'
        )
    return "\n".join(rows)


def _render_model_cards(models, findings, angles):
    cards = []
    for mn in models:
        mf = [f for f in findings if f.get("model_name") == mn]
        sections = []
        for a in angles:
            af = [f for f in mf if f["angle"] == a]
            if not af:
                continue
            worst = _worst_severity([f["severity"] for f in af])
            color = SEVERITY_COLORS.get(worst, "#22c55e")
            rows = []
            af_sorted = sorted(af, key=lambda f: SEVERITY_RANK.get(f["severity"], 0), reverse=True)
            for f in af_sorted:
                sc = SEVERITY_COLORS.get(f["severity"], "#999")
                score_str = ""
                if f.get("score") is not None:
                    s = f["score"]
                    score_str = f"{s:.0%}" if isinstance(s, float) and s <= 1.0 else str(s)
                rec = f'<div class="finding-rec">{_esc(f.get("recommendation", ""))}</div>' if f.get("recommendation") else ""
                rows.append(
                    f'<div class="finding-row" data-sev="{f["severity"]}">'
                    f'<span class="finding-id">{_esc(f["check_id"])}</span>'
                    f'<span class="finding-sev" style="color:{sc}">{_esc(f["severity"])}</span>'
                    f'<span class="finding-title">{_esc(f["title"])}</span>'
                    f'{"<span class=finding-score>" + _esc(score_str) + "</span>" if score_str else ""}'
                    f'<div class="finding-detail">{_esc(f.get("detail", ""))}</div>'
                    f'{rec}'
                    f'</div>'
                )
            expand = "open" if worst in ("CRITICAL", "RED", "HIGH") else ""
            sections.append(
                f'<details class="angle-section" {expand}>'
                f'<summary style="border-left:4px solid {color}">'
                f'<span class="angle-code">{a}</span>'
                f'<span class="angle-label">{ANGLE_LABELS.get(a, a)}</span>'
                f'<span class="angle-sev" style="color:{color}">{worst}</span>'
                f'<span class="angle-count">{len(af)} findings</span>'
                f'</summary>'
                f'<div class="angle-findings">{"".join(rows)}</div>'
                f'</details>'
            )

        cards.append(
            f'<div class="model-card" id="model-{_esc(mn)}" data-model="{_esc(mn)}">'
            f'<div class="card-header">'
            f'<a href="#" onclick="showView(\'heatmap\'); return false;" class="back-link">&larr; Cluster</a>'
            f'<h3>{_esc(mn)}</h3>'
            f'</div>'
            f'<div class="card-body">{"".join(sections)}</div>'
            f'</div>'
        )
    return "\n".join(cards)


def _render_check_summary(check_ids, checks_data):
    """Compact summary table: one row per check with a proportional bar."""
    if not check_ids:
        return ""
    max_count = max(len(checks_data[c]) for c in check_ids) if check_ids else 1

    rows = []
    for cid in check_ids:
        cfs = checks_data[cid]
        if not cfs:
            continue
        count = len(cfs)
        model_count = len(set(f.get("model_name", "") for f in cfs if f.get("model_name")))
        worst = _worst_severity([f["severity"] for f in cfs])
        color = SEVERITY_COLORS.get(worst, "#999")
        bg = SEVERITY_BG.get(worst, "#f9fafb")
        bar_pct = (count / max_count * 100) if max_count else 0
        check_name = cfs[0].get("check_name", "")

        rows.append(
            f'<tr class="summary-row" onclick="scrollToCheck(\'{cid}\')">'
            f'<td class="summary-id">{_esc(cid)}</td>'
            f'<td class="summary-name">{_esc(check_name)}</td>'
            f'<td style="color:{color}" class="summary-sev">{_esc(worst)}</td>'
            f'<td class="summary-models">{model_count}</td>'
            f'<td class="summary-bar-cell">'
            f'<div class="summary-bar-wrap">'
            f'<div class="summary-bar" style="width:{bar_pct:.0f}%;background:{color}"></div>'
            f'<span class="summary-bar-label">{count}</span>'
            f'</div></td>'
            f'</tr>'
        )

    return (
        f'<table class="summary-table"><thead><tr>'
        f'<th>Check</th><th>Name</th><th>Severity</th><th>Models</th><th>Findings</th>'
        f'</tr></thead><tbody>'
        + "\n".join(rows)
        + f'</tbody></table>'
    )


def _render_check_tables(check_ids, checks_data):
    sections = []
    grouped: dict[str, list[str]] = {}
    for cid in check_ids:
        angle = cid[0]
        grouped.setdefault(angle, []).append(cid)

    for angle in sorted(grouped.keys()):
        cids = grouped[angle]
        check_sections = []
        for cid in cids:
            cfs = checks_data[cid]
            if not cfs:
                continue
            worst = _worst_severity([f["severity"] for f in cfs])
            color = SEVERITY_COLORS.get(worst, "#999")
            check_name = cfs[0].get("check_name", "")
            model_count = len(set(f.get("model_name", "") for f in cfs if f.get("model_name")))

            rows = []
            sorted_cfs = sorted(cfs, key=lambda f: SEVERITY_RANK.get(f["severity"], 0), reverse=True)
            for f in sorted_cfs:
                sc = SEVERITY_COLORS.get(f["severity"], "#999")
                mn = f.get("model_name", "—")
                link = f'<a href="#" onclick="showModel(\'{_esc(mn)}\'); return false;">{_esc(mn)}</a>' if mn != "—" else "—"
                score_str = ""
                if f.get("score") is not None:
                    s = f["score"]
                    score_str = f"{s:.0%}" if isinstance(s, float) and s <= 1.0 else str(s)
                rows.append(
                    f'<tr data-sev="{f["severity"]}">'
                    f'<td>{link}</td>'
                    f'<td style="color:{sc}">{_esc(f["severity"])}</td>'
                    f'<td>{_esc(score_str)}</td>'
                    f'<td>{_esc(f["title"])}</td>'
                    f'<td class="detail-cell">{_esc(f.get("detail", ""))}</td>'
                    f'</tr>'
                )

            check_sections.append(
                f'<div class="check-block" id="check-{cid}">'
                f'<h4 style="border-left:4px solid {color}; padding-left:8px">'
                f'{_esc(cid)} — {_esc(check_name)}'
                f' <span class="check-stat">({len(cfs)} findings across {model_count} models)</span>'
                f'</h4>'
                f'<table class="check-table"><thead><tr>'
                f'<th>Model</th><th>Severity</th><th>Score</th><th>Title</th><th>Detail</th>'
                f'</tr></thead><tbody>'
                f'{"".join(rows)}'
                f'</tbody></table></div>'
            )

        sections.append(
            f'<div class="angle-block" id="checks-{angle}">'
            f'<h3>{angle} — {ANGLE_LABELS.get(angle, angle)}</h3>'
            f'{"".join(check_sections)}'
            f'</div>'
        )
    return "\n".join(sections)


def _render_sidebar_models(models, model_data):
    items = []
    for mn in models:
        md = model_data[mn]
        color = SEVERITY_COLORS.get(md["worst"], "#22c55e")
        items.append(
            f'<a href="#" class="sidebar-model" data-model="{_esc(mn)}"'
            f' onclick="showModel(\'{_esc(mn)}\'); return false;">'
            f'<span class="dot" style="background:{color}"></span>'
            f'{_esc(mn)}'
            f'<span class="count">{md["count"]}</span></a>'
        )
    return "\n".join(items)


def _render_sidebar_checks(check_ids, checks_data, angles):
    grouped: dict[str, list[str]] = {}
    for cid in check_ids:
        grouped.setdefault(cid[0], []).append(cid)

    items = []
    for a in sorted(grouped.keys()):
        cids = grouped[a]
        total = sum(len(checks_data[c]) for c in cids)
        items.append(
            f'<a href="#checks-{a}" class="sidebar-angle"'
            f' onclick="showView(\'checks\', \'{a}\'); return false;">'
            f'{a} — {ANGLE_LABELS.get(a, a)} ({total})</a>'
        )
    return "\n".join(items)


def _css():
    return """
:root {
  --sidebar-w: 260px;
  --bg: #f8fafc;
  --card-bg: #fff;
  --border: #e2e8f0;
  --text: #1e293b;
  --text-secondary: #64748b;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--font); color: var(--text); background: var(--bg); font-size: 14px; line-height: 1.5; }

.layout { display: flex; min-height: 100vh; }

/* Sidebar */
.sidebar {
  width: var(--sidebar-w); background: var(--card-bg); border-right: 1px solid var(--border);
  position: fixed; top: 0; left: 0; bottom: 0; overflow-y: auto; z-index: 10;
  padding: 16px 12px;
}
.sidebar-header h2 { font-size: 16px; margin-bottom: 4px; }
.meta-small { font-size: 12px; color: var(--text-secondary); margin-bottom: 12px; }
.sidebar-section { margin-bottom: 16px; }
.sidebar-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-secondary); margin-bottom: 6px; font-weight: 600; }
.nav-link { display: block; padding: 6px 10px; border-radius: 6px; text-decoration: none; color: var(--text); font-weight: 600; }
.nav-link:hover, .nav-link.active { background: #e0f2fe; color: #0284c7; }
.sidebar-model { display: flex; align-items: center; gap: 6px; padding: 3px 8px; border-radius: 4px; text-decoration: none; color: var(--text); font-size: 13px; }
.sidebar-model:hover { background: #f1f5f9; }
.sidebar-model .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.sidebar-model .count { margin-left: auto; color: var(--text-secondary); font-size: 12px; }
.sidebar-angle { display: block; padding: 4px 8px; border-radius: 4px; text-decoration: none; color: var(--text); font-size: 13px; }
.sidebar-angle:hover { background: #f1f5f9; }
.sev-summary { display: flex; flex-wrap: wrap; gap: 4px; }
.sev-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; color: #fff; font-weight: 600; text-decoration: none; cursor: pointer; transition: opacity .15s; }
.sev-badge:hover { opacity: 0.8; }

/* Content */
.content { margin-left: var(--sidebar-w); flex: 1; padding: 24px 32px; max-width: 1200px; }

/* Header */
.report-header { margin-bottom: 24px; padding-bottom: 16px; border-bottom: 2px solid var(--border); }
.report-header h1 { font-size: 22px; margin-bottom: 8px; }
.header-meta { display: flex; flex-wrap: wrap; gap: 4px 24px; font-size: 13px; color: var(--text-secondary); }
.meta-row { white-space: nowrap; }
.meta-label { font-weight: 600; color: var(--text); }

/* Views */
.view { display: none; }
.view.active { display: block; }
.view h2 { font-size: 18px; margin-bottom: 12px; }

/* Controls */
.controls { display: flex; gap: 16px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.filter-input { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; width: 220px; }
.sev-toggles { display: flex; gap: 4px; flex-wrap: wrap; }
.sev-toggle { display: inline-flex; align-items: center; cursor: pointer; }
.sev-toggle input { display: none; }
.sev-chip { padding: 2px 8px; border-radius: 10px; font-size: 11px; color: #fff; font-weight: 600; opacity: 1; transition: opacity .15s; }
.sev-toggle input:not(:checked) + .sev-chip { opacity: 0.3; }

/* Heatmap */
.table-wrap { overflow-x: auto; }
.heatmap-table { width: 100%; border-collapse: collapse; background: var(--card-bg); border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.heatmap-th { padding: 10px 12px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: .5px; color: var(--text-secondary); background: #f8fafc; border-bottom: 2px solid var(--border); }
.heatmap-th a { color: inherit; text-decoration: none; }
.heatmap-th a:hover { color: #0284c7; }
.model-col { min-width: 200px; }
.heatmap-row { cursor: pointer; transition: background .1s; }
.heatmap-row:hover { background: #f1f5f9 !important; }
.heatmap-row.hidden { display: none; }
.heatmap-cell { padding: 8px 12px; font-size: 12px; font-weight: 700; text-align: center; min-width: 100px; }
.model-name-cell { padding: 8px 12px; font-weight: 500; }
.model-name-cell a { color: var(--text); text-decoration: none; }
.model-name-cell a:hover { color: #0284c7; }
.findings-count { padding: 8px 12px; font-weight: 700; text-align: center; min-width: 110px; }
.count-num { font-weight: 400; font-size: 12px; opacity: 0.7; }

/* Model card */
.model-card { display: none; }
.model-card.active { display: block; }
.card-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.card-header h3 { font-size: 18px; }
.back-link { font-size: 13px; text-decoration: none; color: #0284c7; white-space: nowrap; }

.angle-section { margin-bottom: 8px; background: var(--card-bg); border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.06); overflow: hidden; }
.angle-section summary { padding: 10px 14px; cursor: pointer; display: flex; align-items: center; gap: 10px; user-select: none; list-style: none; }
.angle-section summary::-webkit-details-marker { display: none; }
.angle-section summary::before { content: '\\25B8'; transition: transform .15s; font-size: 12px; }
.angle-section[open] summary::before { transform: rotate(90deg); }
.angle-code { font-weight: 700; font-size: 14px; }
.angle-label { color: var(--text-secondary); font-size: 13px; }
.angle-sev { font-weight: 700; font-size: 13px; margin-left: auto; }
.angle-count { font-size: 12px; color: var(--text-secondary); }

.angle-findings { padding: 4px 14px 14px; }
.finding-row { padding: 8px 0; border-bottom: 1px solid #f1f5f9; display: grid; grid-template-columns: 40px 70px 1fr auto; gap: 8px; align-items: start; }
.finding-row:last-child { border-bottom: none; }
.finding-id { font-weight: 600; font-size: 12px; color: var(--text-secondary); }
.finding-sev { font-weight: 700; font-size: 12px; }
.finding-title { font-size: 13px; }
.finding-score { font-size: 12px; color: var(--text-secondary); font-weight: 600; }
.finding-detail { grid-column: 1 / -1; font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.finding-rec { grid-column: 1 / -1; font-size: 12px; color: #0284c7; margin-top: 2px; }

/* Check tables */
.angle-block { margin-bottom: 24px; }
.angle-block h3 { font-size: 16px; margin-bottom: 12px; padding-bottom: 6px; border-bottom: 2px solid var(--border); }
.check-block { margin-bottom: 16px; }
.check-block h4 { font-size: 14px; margin-bottom: 8px; }
.check-stat { font-weight: 400; color: var(--text-secondary); font-size: 13px; }
.check-table { width: 100%; border-collapse: collapse; background: var(--card-bg); border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); font-size: 13px; }
.check-table th { padding: 8px 10px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: .5px; color: var(--text-secondary); background: #f8fafc; border-bottom: 1px solid var(--border); }
.check-table td { padding: 6px 10px; border-bottom: 1px solid #f1f5f9; }
.check-table a { color: var(--text); text-decoration: none; }
.check-table a:hover { color: #0284c7; }
.detail-cell { max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-cell:hover { white-space: normal; }

/* Check summary */
.summary-table { width: 100%; border-collapse: collapse; background: var(--card-bg); border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); font-size: 13px; margin-bottom: 8px; }
.summary-table th { padding: 8px 10px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: .5px; color: var(--text-secondary); background: #f8fafc; border-bottom: 1px solid var(--border); }
.summary-table td { padding: 6px 10px; border-bottom: 1px solid #f1f5f9; }
.summary-row { cursor: pointer; transition: background .1s; }
.summary-row:hover { background: #f1f5f9; }
.summary-id { font-weight: 700; width: 40px; }
.summary-name { color: var(--text-secondary); }
.summary-sev { font-weight: 700; width: 70px; }
.summary-models { text-align: center; width: 60px; }
.summary-bar-cell { width: 40%; }
.summary-bar-wrap { display: flex; align-items: center; gap: 8px; }
.summary-bar { height: 18px; border-radius: 3px; min-width: 2px; transition: width .2s; }
.summary-bar-label { font-weight: 600; font-size: 12px; white-space: nowrap; }

@media (max-width: 900px) {
  .sidebar { display: none; }
  .content { margin-left: 0; padding: 16px; }
}
"""


def _js():
    return """
function showView(view, scrollTo) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));

  if (view === 'heatmap') {
    document.getElementById('view-heatmap').classList.add('active');
    document.getElementById('nav-heatmap').classList.add('active');
  } else if (view === 'model') {
    document.getElementById('view-model').classList.add('active');
  } else if (view === 'checks') {
    document.getElementById('view-checks').classList.add('active');
    if (scrollTo) {
      const el = document.getElementById('checks-' + scrollTo);
      if (el) setTimeout(() => el.scrollIntoView({behavior: 'smooth'}), 50);
    }
  }
}

function showModel(name, angle) {
  showView('model');
  document.querySelectorAll('.model-card').forEach(c => c.classList.remove('active'));
  const cards = document.querySelectorAll('.model-card');
  for (const card of cards) {
    if (card.dataset.model === name) {
      card.classList.add('active');
      if (angle) {
        const sections = card.querySelectorAll('.angle-section');
        for (const sec of sections) {
          const code = sec.querySelector('.angle-code');
          if (code && code.textContent.trim() === angle) {
            sec.setAttribute('open', '');
            setTimeout(() => sec.scrollIntoView({behavior: 'smooth', block: 'start'}), 50);
            return;
          }
        }
      }
      card.scrollIntoView({behavior: 'smooth', block: 'start'});
      break;
    }
  }
}

function filterHeatmap(query) {
  const q = query.toLowerCase();
  document.querySelectorAll('.heatmap-row').forEach(row => {
    const name = row.dataset.model.toLowerCase();
    row.classList.toggle('hidden', q && !name.includes(q));
  });
}

function filterSidebarModels(query) {
  const q = query.toLowerCase();
  document.querySelectorAll('.sidebar-model').forEach(el => {
    const name = el.dataset.model.toLowerCase();
    el.style.display = (q && !name.includes(q)) ? 'none' : '';
  });
}

const hiddenSeverities = new Set();
function toggleSeverity(sev) {
  if (hiddenSeverities.has(sev)) hiddenSeverities.delete(sev);
  else hiddenSeverities.add(sev);
  document.querySelectorAll('.heatmap-row').forEach(row => {
    const worst = row.dataset.worst;
    row.classList.toggle('hidden', hiddenSeverities.has(worst));
  });
}

function scrollToCheck(checkId) {
  const el = document.getElementById('check-' + checkId);
  if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function filterBySeverity(sev) {
  showView('checks');
  document.querySelectorAll('.check-table tbody tr').forEach(row => {
    row.style.display = (row.dataset.sev === sev) ? '' : 'none';
  });
  const banner = document.getElementById('sev-filter-banner');
  if (banner) banner.remove();
  const content = document.querySelector('.content');
  const div = document.createElement('div');
  div.id = 'sev-filter-banner';
  div.style.cssText = 'padding:8px 14px;background:#fef3c7;border-radius:6px;margin-bottom:12px;font-size:13px;display:flex;align-items:center;gap:8px;';
  div.innerHTML = 'Showing <strong>' + sev + '</strong> findings only. <a href="#" onclick="clearSevFilter(); return false;">Show all</a>';
  const checksView = document.getElementById('view-checks');
  checksView.insertBefore(div, checksView.firstChild);
}

function clearSevFilter() {
  document.querySelectorAll('.check-table tbody tr').forEach(row => {
    row.style.display = '';
  });
  const banner = document.getElementById('sev-filter-banner');
  if (banner) banner.remove();
}

showView('heatmap');
"""
