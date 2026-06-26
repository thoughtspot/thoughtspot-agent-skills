#!/usr/bin/env python3
"""
HTML report generator for ts-audit.

Takes findings from the analyzer and produces a single self-contained HTML file
with three views: cluster heatmap, model scorecard, and by-check detail.

Usage:
    from report import generate_html_report

    html = generate_html_report(findings, meta)
    Path("audit_report.html").write_text(html)
"""
from __future__ import annotations

import html
from dataclasses import dataclass, asdict
from typing import Any


ANGLE_LABELS = {
    "A": "AI Readiness",
    "D": "Data Modeling",
    "H": "Human Readiness",
    "P": "Performance",
    "S": "Security",
}

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
SEVERITY_RANK = {s: i for i, s in enumerate(reversed(SEVERITY_ORDER))}
SEVERITY_RANK["GREEN"] = 0

SEVERITY_LABELS = {
    "CRITICAL": "Critical",
    "HIGH": "Warning",
    "MEDIUM": "Advisory",
    "LOW": "Info",
    "INFO": "Note",
    "GREEN": "Pass",
}

SEVERITY_COLORS = {
    "CRITICAL": "#dc2626",
    "HIGH": "#f97316",
    "MEDIUM": "#eab308",
    "LOW": "#3b82f6",
    "INFO": "#6b7280",
    "GREEN": "#22c55e",
}

SEVERITY_BG = {
    "CRITICAL": "#fef2f2",
    "HIGH": "#fff7ed",
    "MEDIUM": "#fefce8",
    "LOW": "#eff6ff",
    "INFO": "#f9fafb",
    "GREEN": "#f0fdf4",
}

CHECK_DESCRIPTIONS: dict[str, str] = {
    "A1": "Percentage of columns with a non-empty description. Descriptions power Spotter's natural-language understanding — without them, the AI cannot interpret what a column represents.",
    "A2": "Percentage of columns with at least one synonym. Synonyms let users search with their own vocabulary (e.g. 'revenue' finds 'total_sales').",
    "A3": "Whether the model has AI context (data model instructions). These coaching instructions tell Spotter how to interpret the model, what questions it can answer, and which columns to prefer.",
    "A4": "Whether the model has a meaningful model-level description. Helps both AI and human users understand the model's purpose at a glance.",
    "A5": "Composite readiness score combining description coverage, synonym coverage, AI context, model description, and column name quality. Models scoring below 80 are not ready for Spotter.",
    "D1": "Counts of tables, columns, joins, formulas, and join depth per model. High complexity leads to slower queries, harder maintenance, and poor Spotter performance.",
    "D2": "VARCHAR-to-VARCHAR joins are 2–5× slower than integer joins. Multi-column joins suggest a missing surrogate key.",
    "D3": "FULL OUTER joins often cause row multiplication and performance issues. LEFT/RIGHT OUTER joins may indicate data discrepancies worth reviewing.",
    "D4": "Progressive joins allow ThoughtSpot to only join tables needed by each query. Without them, every query joins ALL tables regardless of which columns are searched.",
    "D5": "Tables added to the model but not joined to any other table. When queried alongside other tables, ThoughtSpot produces a Cartesian product (every row crossed with every row).",
    "D6": "Fact tables should be mostly measures; high attribute ratios suggest grain issues. A fact table with 90% attributes may be at the wrong granularity or misclassified.",
    "D7": "Compares table sets across models to find duplication. Shared dimension tables are healthy (conformed dimensions); shared fact tables or near-identical models suggest consolidation.",
    "D8": "Different ThoughtSpot table objects pointing at the same physical database table. Creates confusion about which table object is canonical.",
    "D9": "sql_*_aggregate_op formulas bypass ThoughtSpot's query engine and push raw SQL to the warehouse. Legitimate for edge cases but overuse indicates formula limitations being worked around.",
    "D10": "Tables in the model with no columns selected. Bridge tables (used in join paths) are informational; leaf tables with no joins and no columns serve no purpose.",
    "D11": "Joins that risk row multiplication — hub-to-hub (fact-to-fact) joins, ONE_TO_MANY cardinality, or conversion/rate table patterns.",
    "H1": "Generic names (col1, field_1, val), temp prefixes (tmp_), digit-leading, or ALL_UPPER_UNDERSCORE names that make the model hard to navigate for business users.",
    "H2": "Descriptions that are too short (<20 chars), too long (>400 chars), or boilerplate ('This is a column for...'). Low-quality descriptions are worse than none — they give false confidence.",
    "H3": "Hidden columns not referenced by any formula. Hidden columns cause locked visualisations. Unused columns should be removed from the model, not hidden.",
    "H4": "Models with zero dependents — no answers, liveboards, or sets use them. May be abandoned or under development.",
    "H7": "Answers connected directly to tables, bypassing the semantic model layer. Loses governance, descriptions, synonyms, and RLS.",
    "H8": "Formulas duplicated in 2+ answers against the same model but not in the model itself. Should be promoted to the model for single-source-of-truth.",
    "H10": "Names or descriptions indicating temporary, deprecated, or abandoned objects — test_, zDEL, 'Copy of', backup, etc.",
    "H11": "Models with many columns but no column groups defined. Column groups organise the search bar into folders for discoverability.",
    "P2": "Scalar formulas (no aggregation) that run row-by-row. High density increases query evaluation time.",
    "P3": "Non-progressive filter columns — filters that cannot leverage database partitioning or indexing, forcing full table scans.",
    "P5": "Models with fact tables but no date/time constraint column. Without a date filter, every query scans the full history.",
    "P8": "More than 75 columns in a model. Wider GROUP BY clauses and more complex query plans degrade performance.",
    "P9": "GUID, transaction ID, or similar high-cardinality columns indexed as ATTRIBUTEs. Wastes storage and pollutes Spotter suggestions with meaningless values.",
    "P11": "Many indexed columns on a Spotter-enabled model. Each indexed column adds a database lookup for autocomplete suggestions.",
    "P13": "Many RLS rules per table — each evaluates independently on every query. Cost compounds linearly with rule count.",
    "P14": "Functions in RLS expressions (if, contains, concat, etc.) prevent index and partition pruning, forcing row-by-row evaluation.",
    "P15": "VARCHAR columns used in RLS without value_casing set. The database cannot use indexes efficiently for case-sensitive RLS filtering.",
    "P16": "Deeply nested if() conditionals in model formulas. Each nesting level adds branching in the ThoughtSpot calculation engine.",
    "P17": "Formulas referencing other formulas, creating calculation chains. Each link adds a computation layer at query time.",
    "P18": "Columns using COUNT_DISTINCT aggregation — the most expensive aggregation on most warehouses. Not wrong, but worth surfacing.",
    "P19": "Large models without aggregate awareness configured. Aggregate models route queries to pre-aggregated tables when the query grain matches, reducing warehouse compute.",
    "S1": "Columns matching PII name patterns (email, phone, SSN, date of birth). Heuristic — false positives expected.",
    "S2": "PII columns that are indexed, exposing values in Spotter autocomplete. Can only be secured if the backing table has RLS rules.",
    "S4": "RLS bypass enabled AND the model contains PII columns. All users see all rows including personally identifiable information.",
    "S5": "Columns matching credential patterns (password, secret_key, api_key, token). Should never be in an analytics model.",
    "D12": "Same physical column (db_column_name) across models classified differently (e.g. ATTRIBUTE in one, MEASURE in another). Causes inconsistent aggregation and search behaviour for the same underlying data.",
    "S8": "RLS rules filtering on VARCHAR columns are 2–5× slower than integer filters. Identifies tables where RLS performance can be improved by using integer keys.",
    "S9": "Functions wrapping columns in RLS expressions (e.g. UPPER([col])) prevent filter pushdown to the database, forcing row-by-row evaluation in ThoughtSpot.",
    "S10": "RLS bypass (is_bypass_rls) disables Row-Level Security — all users see all rows regardless of RLS rules. Legitimate for aggregate-only models but should be the exception.",
}

CHECK_NAMES: dict[str, str] = {
    "A1": "DESC_COVERAGE", "A2": "SYNONYM_COVERAGE", "A3": "AI_CONTEXT_MISSING",
    "A4": "MODEL_DESCRIPTION_MISSING", "A5": "SPOTTER_READINESS",
    "D1": "COMPLEXITY", "D2": "JOIN_QUALITY", "D3": "OUTER_JOIN",
    "D4": "JOIN_NOT_PROGRESSIVE", "D5": "ORPHAN_TABLE_IN_MODEL",
    "D6": "GRAIN_INCONSISTENCY", "D7": "MODEL_OVERLAP", "D8": "DUPLICATE_TABLE",
    "D9": "SQL_PASSTHROUGH", "D10": "ZERO_COLUMN_TABLE", "D11": "FANOUT_RISK",
    "D12": "CONFORMED_DIM_DIVERGENCE",
    "H1": "COLUMN_NAME_QUALITY", "H2": "DESCRIPTION_QUALITY",
    "H3": "UNNECESSARY_HIDDEN", "H4": "ORPHAN_MODEL",
    "H7": "DIRECT_TABLE_CONNECTION", "H8": "FORMULA_PROMOTION", "H10": "STALE_COLUMNS",
    "H11": "NO_COLUMN_GROUPS",
    "P2": "SCALAR_FORMULA_DENSITY", "P3": "NON_PROGRESSIVE_FILTER",
    "P5": "NO_DATE_CONSTRAINT", "P8": "COLUMN_SPRAWL",
    "P9": "HIGH_CARDINALITY_INDEX", "P11": "SECURE_SUGGESTIONS_OVERHEAD",
    "P13": "RLS_RULE_DENSITY", "P14": "RLS_FUNCTION_PERF",
    "P15": "RLS_COLUMN_CASING", "P16": "FORMULA_NESTING_DEPTH",
    "P17": "FORMULA_CHAIN_DEPTH", "P18": "COUNT_DISTINCT_MEASURES",
    "P19": "NO_AGGREGATE_AWARENESS",
    "S1": "PII_DETECTED", "S2": "PII_INDEXED_NO_RLS",
    "S4": "RLS_BYPASS_WITH_PII", "S5": "CREDENTIAL_IN_MODEL",
    "S8": "RLS_VARCHAR_FILTER", "S9": "RLS_FUNCTION_IN_EXPR", "S10": "RLS_BYPASS",
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


def _sev_label(sev: str) -> str:
    return SEVERITY_LABELS.get(sev, sev)


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


def _disambiguate_model_names(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """When multiple GUIDs share a model_name, suffix each with a short GUID fragment."""
    name_guids: dict[str, set[str]] = {}
    for f in findings:
        mn = f.get("model_name")
        mg = f.get("model_guid")
        if mn and mg:
            name_guids.setdefault(mn, set()).add(mg)

    ambiguous = {name: guids for name, guids in name_guids.items() if len(guids) > 1}
    if not ambiguous:
        return findings

    guid_suffix: dict[str, str] = {}
    for name, guids in ambiguous.items():
        sorted_guids = sorted(guids)
        for i, g in enumerate(sorted_guids, 1):
            guid_suffix[f"{name}|{g}"] = f"{name} #{i}"

    result = []
    for f in findings:
        mn = f.get("model_name", "")
        mg = f.get("model_guid", "")
        key = f"{mn}|{mg}"
        if key in guid_suffix:
            f = dict(f)
            f["model_name"] = guid_suffix[key]
        result.append(f)
    return result


def generate_html_report(
    findings: list[dict[str, Any]],
    meta: ReportMeta | None = None,
) -> str:
    if meta is None:
        meta = ReportMeta()

    findings = _disambiguate_model_names(findings)

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

    return _build_html(
        findings=findings,
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
        f'{_sev_label(s)}: {sev_counts.get(s, 0)}</a>'
        for s in SEVERITY_ORDER if sev_counts.get(s, 0)
    )

    sev_toggles = []
    for s in SEVERITY_ORDER:
        if sev_counts.get(s, 0):
            color = SEVERITY_COLORS.get(s, "#999")
            sev_toggles.append(
                f'<label class="sev-toggle">'
                f"<input type=\"checkbox\" checked onchange=\"toggleSeverity('{s}')\" data-sev=\"{s}\">"
                f'<span class="sev-chip" style="background:{color}">{_sev_label(s)}</span></label>'
            )
    sev_toggles_html = "".join(sev_toggles)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Semantic Layer Health Audit — {_esc(meta.cluster_url)}</title>
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
    <a href="#" onclick="showView('checks'); scrollToSummary(); return false;" class="nav-link" id="nav-summary">
      Checks Summary</a>
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
    <h1>Semantic Layer Health Audit</h1>
    <p class="report-desc">Scores each semantic model against five quality dimensions: AI readiness,
    data modeling best practices, human readiness (naming, descriptions), performance, and security.
    Use this report to identify which models need attention and where to focus improvement efforts.</p>
    <div class="header-meta">
      <div class="meta-row"><span class="meta-label">Cluster:</span> {_esc(meta.cluster_url or meta.profile_name)}</div>
      <div class="meta-row"><span class="meta-label">Date:</span> {_esc(meta.date)}</div>
      <div class="meta-row"><span class="meta-label">Audit Profile:</span> {_esc(meta.audit_profile)}</div>
      <div class="meta-row"><span class="meta-label">Scope:</span> {_esc(meta.scope)}</div>
      <div class="meta-row"><span class="meta-label">Angles:</span> {', '.join(f'{a} ({ANGLE_LABELS.get(a, a)})' for a in angles)}</div>
      <div class="meta-row"><span class="meta-label">Models:</span> {meta.model_count}
        &nbsp;&nbsp; <span class="meta-label">Findings:</span> {total}
        &nbsp;&nbsp; <span class="meta-label">Critical:</span> {critical}
        &nbsp;&nbsp; <span class="meta-label">Warning:</span> {high}</div>
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
                f'{_sev_label(sev)}</td>'
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
            f'{_sev_label(worst)} <span class="count-num">({md["count"]})</span></td>'
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

            check_groups: dict[str, list[dict]] = {}
            for f in af:
                check_groups.setdefault(f["check_id"], []).append(f)

            sorted_cids = sorted(
                check_groups.keys(),
                key=lambda c: SEVERITY_RANK.get(
                    _worst_severity([f["severity"] for f in check_groups[c]]), 0
                ),
                reverse=True,
            )

            check_blocks = []
            for cid in sorted_cids:
                cfs = check_groups[cid]
                cid_worst = _worst_severity([f["severity"] for f in cfs])
                cid_color = SEVERITY_COLORS.get(cid_worst, "#999")
                cid_name = CHECK_NAMES.get(cid, cfs[0].get("check_name", ""))
                cid_desc = CHECK_DESCRIPTIONS.get(cid, "")

                rows = []
                for f in sorted(cfs, key=lambda f: SEVERITY_RANK.get(f["severity"], 0), reverse=True):
                    sc = SEVERITY_COLORS.get(f["severity"], "#999")
                    score_str = ""
                    if f.get("score") is not None:
                        s = f["score"]
                        score_str = f"{s:.0%}" if isinstance(s, float) and s <= 1.0 else str(s)
                    rows.append(
                        f'<div class="finding-row" data-sev="{f["severity"]}">'
                        f'<span class="finding-sev" style="color:{sc}">{_sev_label(f["severity"])}</span>'
                        f'<span class="finding-title">{_esc(f["title"])}</span>'
                        f'{"<span class=finding-score>" + _esc(score_str) + "</span>" if score_str else ""}'
                        f'</div>'
                    )

                desc_html = f'<div class="check-group-desc">{_esc(cid_desc)}</div>' if cid_desc else ''

                if len(cfs) == 1:
                    check_blocks.append(
                        f'<div class="check-group-single">'
                        f'<div class="check-group-header" style="border-left:3px solid {cid_color}">'
                        f'<span class="finding-id">{_esc(cid)}</span>'
                        f'<span class="check-group-name">{_esc(cid_name)}</span>'
                        f'<span class="check-group-sev" style="color:{cid_color}">{_sev_label(cid_worst)}</span>'
                        f'</div>'
                        f'{desc_html}'
                        f'<div class="check-group-body">{"".join(rows)}</div>'
                        f'</div>'
                    )
                else:
                    cid_expand = "open" if cid_worst in ("CRITICAL", "HIGH") else ""
                    check_blocks.append(
                        f'<details class="check-group" {cid_expand}>'
                        f'<summary class="check-group-header" style="border-left:3px solid {cid_color}">'
                        f'<span class="finding-id">{_esc(cid)}</span>'
                        f'<span class="check-group-name">{_esc(cid_name)}</span>'
                        f'<span class="check-group-count">{len(cfs)}</span>'
                        f'<span class="check-group-sev" style="color:{cid_color}">{_sev_label(cid_worst)}</span>'
                        f'</summary>'
                        f'{desc_html}'
                        f'<div class="check-group-body">{"".join(rows)}</div>'
                        f'</details>'
                    )

            expand = "open" if worst in ("CRITICAL", "RED", "HIGH") else ""
            sections.append(
                f'<details class="angle-section" {expand}>'
                f'<summary style="border-left:4px solid {color}">'
                f'<span class="angle-code">{a}</span>'
                f'<span class="angle-label">{ANGLE_LABELS.get(a, a)}</span>'
                f'<span class="angle-sev" style="color:{color}">{_sev_label(worst)}</span>'
                f'<span class="angle-count">{len(af)} findings</span>'
                f'</summary>'
                f'<div class="angle-findings">{"".join(check_blocks)}</div>'
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
    """Summary table showing ALL checks — those with findings and those passing clean."""
    all_cids = sorted(CHECK_DESCRIPTIONS.keys(), key=lambda c: (c[0], int("".join(ch for ch in c[1:] if ch.isdigit()) or "0")))

    max_count = max((len(checks_data.get(c, [])) for c in all_cids), default=1) or 1

    rows = []
    for cid in all_cids:
        cfs = checks_data.get(cid, [])
        count = len(cfs)
        model_count = len(set(f.get("model_name", "") for f in cfs if f.get("model_name")))
        worst = _worst_severity([f["severity"] for f in cfs]) if cfs else "GREEN"
        color = SEVERITY_COLORS.get(worst, "#22c55e")
        bar_pct = (count / max_count * 100) if max_count else 0
        check_name = CHECK_NAMES.get(cid, cfs[0].get("check_name", "") if cfs else "")
        desc = CHECK_DESCRIPTIONS.get(cid, "")
        angle = cid[0]
        onclick = f"scrollToCheck('{cid}')" if count > 0 else ""
        cursor = "cursor:pointer" if count > 0 else "cursor:default;opacity:0.7"

        rows.append(
            f'<tr class="summary-row" data-angle="{angle}" data-sev="{worst}" data-count="{count}"'
            f' onclick="{onclick}" style="{cursor}">'
            f'<td class="summary-id">{_esc(cid)}</td>'
            f'<td class="summary-name">{_esc(check_name)}</td>'
            f'<td class="summary-desc">{_esc(desc)}</td>'
            f'<td style="color:{color}" class="summary-sev">{_sev_label(worst)}</td>'
            f'<td class="summary-models">{model_count}</td>'
            f'<td class="summary-bar-cell">'
            f'<div class="summary-bar-wrap">'
            f'<div class="summary-bar" style="width:{bar_pct:.0f}%;background:{color}"></div>'
            f'<span class="summary-bar-label">{count}</span>'
            f'</div></td>'
            f'</tr>'
        )

    angle_options = "".join(
        f'<option value="{a}">{a} — {ANGLE_LABELS.get(a, a)}</option>'
        for a in sorted(ANGLE_LABELS.keys())
    )
    sev_options = "".join(
        f'<option value="{s}">{_sev_label(s)}</option>'
        for s in SEVERITY_ORDER + ["GREEN"]
    )

    filters = (
        f'<div class="summary-filters" id="summary-filters">'
        f'<select id="summary-angle-filter" onchange="filterSummaryTable()" class="summary-select">'
        f'<option value="">All angles</option>{angle_options}</select>'
        f'<select id="summary-sev-filter" onchange="filterSummaryTable()" class="summary-select">'
        f'<option value="">All severities</option>{sev_options}</select>'
        f'<label class="summary-toggle"><input type="checkbox" id="summary-issues-only"'
        f' onchange="filterSummaryTable()"> Issues only</label>'
        f'</div>'
    )

    return (
        f'<div id="checks-summary">{filters}'
        f'<table class="summary-table"><thead><tr>'
        f'<th>Check</th><th>Name</th><th>Description</th><th>Severity</th><th>Models</th><th>Findings</th>'
        f'</tr></thead><tbody>'
        + "\n".join(rows)
        + f'</tbody></table></div>'
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
            check_name = CHECK_NAMES.get(cid, cfs[0].get("check_name", ""))
            model_count = len(set(f.get("model_name", "") for f in cfs if f.get("model_name")))

            rows = []
            sorted_cfs = sorted(cfs, key=lambda f: SEVERITY_RANK.get(f["severity"], 0), reverse=True)
            for f in sorted_cfs:
                sc = SEVERITY_COLORS.get(f["severity"], "#999")
                mn = f.get("model_name", "")
                if mn:
                    link = f'<a href="#" onclick="showModel(\'{_esc(mn)}\'); return false;">{_esc(mn)}</a>'
                else:
                    title_text = f.get("title", "")
                    link = f'<span class="object-level">{_esc(title_text)}</span>'
                score_str = ""
                if f.get("score") is not None:
                    s = f["score"]
                    score_str = f"{s:.0%}" if isinstance(s, float) and s <= 1.0 else str(s)
                rows.append(
                    f'<tr data-sev="{f["severity"]}">'
                    f'<td>{link}</td>'
                    f'<td style="color:{sc}">{_sev_label(f["severity"])}</td>'
                    f'<td>{_esc(score_str)}</td>'
                    f'<td>{_esc(f["title"])}</td>'
                    f'</tr>'
                )

            desc = CHECK_DESCRIPTIONS.get(cid, "")
            rec = cfs[0].get("recommendation", "") if cfs else ""
            desc_html = f'<p class="check-desc">{_esc(desc)}</p>' if desc else ""
            rec_html = f'<p class="check-rec">{_esc(rec)}</p>' if rec else ""
            expand = "open" if worst in ("CRITICAL", "HIGH") else ""
            check_sections.append(
                f'<details class="check-block" id="check-{cid}" {expand}>'
                f'<summary class="check-summary" style="border-left:4px solid {color}; padding-left:8px">'
                f'<span class="check-title">{_esc(cid)} — {_esc(check_name)}</span>'
                f' <span class="check-stat">({len(cfs)} findings across {model_count} models)</span>'
                f' <span class="check-sev" style="color:{color}">{_sev_label(worst)}</span>'
                f'</summary>'
                f'<div class="check-body">'
                f'{desc_html}{rec_html}'
                f'<table class="check-table"><thead><tr>'
                f'<th>Model</th><th>Severity</th><th>Score</th><th>Detail</th>'
                f'</tr></thead><tbody>'
                f'{"".join(rows)}'
                f'</tbody></table></div></details>'
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
.report-header h1 { font-size: 22px; margin-bottom: 4px; }
.report-desc { font-size: 13px; color: var(--text-secondary); margin-bottom: 10px; line-height: 1.4; }
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

.check-group, .check-group-single { margin-bottom: 6px; background: #f8fafc; border-radius: 6px; overflow: hidden; }
.check-group-header { padding: 6px 10px; display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; list-style: none; }
.check-group-header::-webkit-details-marker { display: none; }
.check-group > .check-group-header::before { content: '\\25B8'; transition: transform .15s; font-size: 10px; flex-shrink: 0; }
.check-group[open] > .check-group-header::before { transform: rotate(90deg); }
.check-group-single .check-group-header { cursor: default; }
.check-group-name { font-size: 12px; color: var(--text-secondary); }
.check-group-count { font-size: 11px; background: var(--border); padding: 1px 6px; border-radius: 8px; color: var(--text-secondary); }
.check-group-sev { font-weight: 700; font-size: 12px; margin-left: auto; }
.check-group-desc { font-size: 12px; color: var(--text-secondary); padding: 0 10px 4px 28px; line-height: 1.3; }
.check-group-body { padding: 0 10px 8px 18px; }
.finding-row { padding: 6px 0; border-bottom: 1px solid #f1f5f9; display: flex; align-items: baseline; gap: 8px; }
.finding-row:last-child { border-bottom: none; }
.finding-id { font-weight: 600; font-size: 12px; color: var(--text-secondary); }
.finding-sev { font-weight: 700; font-size: 12px; }
.finding-title { font-size: 13px; }
.finding-score { font-size: 12px; color: var(--text-secondary); font-weight: 600; }
.finding-detail { width: 100%; font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.finding-rec { width: 100%; font-size: 12px; color: #0284c7; margin-top: 2px; }

/* Check tables */
.angle-block { margin-bottom: 24px; }
.angle-block h3 { font-size: 16px; margin-bottom: 12px; padding-bottom: 6px; border-bottom: 2px solid var(--border); }
.check-block { margin-bottom: 12px; background: var(--card-bg); border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.06); overflow: hidden; }
.check-summary { padding: 10px 14px; cursor: pointer; display: flex; align-items: center; gap: 8px; user-select: none; list-style: none; font-size: 14px; }
.check-summary::-webkit-details-marker { display: none; }
.check-summary::before { content: '\\25B8'; transition: transform .15s; font-size: 12px; flex-shrink: 0; }
.check-block[open] .check-summary::before { transform: rotate(90deg); }
.check-title { font-weight: 700; }
.check-sev { font-weight: 700; font-size: 13px; margin-left: auto; }
.check-body { padding: 4px 14px 14px; }
.check-desc { color: var(--text-secondary); font-size: 13px; margin: 0 0 4px 12px; line-height: 1.4; }
.check-rec { color: #0284c7; font-size: 13px; margin: 0 0 8px 12px; line-height: 1.4; }
.object-level { font-style: italic; color: var(--text-secondary); }
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
.summary-row { transition: background .1s; }
.summary-row:hover { background: #f1f5f9; }
.summary-id { font-weight: 700; width: 40px; }
.summary-name { color: var(--text-secondary); white-space: nowrap; }
.summary-desc { color: var(--text-secondary); font-size: 12px; max-width: 340px; line-height: 1.3; }
.summary-sev { font-weight: 700; width: 70px; }
.summary-models { text-align: center; width: 60px; }
.summary-bar-cell { width: 120px; }
.summary-bar-wrap { display: flex; align-items: center; gap: 8px; }
.summary-bar { height: 18px; border-radius: 3px; min-width: 2px; transition: width .2s; }
.summary-bar-label { font-weight: 600; font-size: 12px; white-space: nowrap; }
.summary-filters { display: flex; gap: 12px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
.summary-select { padding: 5px 8px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; background: var(--card-bg); }
.summary-toggle { display: flex; align-items: center; gap: 4px; font-size: 13px; cursor: pointer; color: var(--text-secondary); }

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

const SEV_LABELS = {CRITICAL:'Critical',HIGH:'Warning',MEDIUM:'Advisory',LOW:'Info',INFO:'Note',GREEN:'Pass'};
function sevLabel(s) { return SEV_LABELS[s] || s; }

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
  div.innerHTML = 'Showing <strong>' + sevLabel(sev) + '</strong> findings only. <a href="#" onclick="clearSevFilter(); return false;">Show all</a>';
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

function scrollToSummary() {
  const el = document.getElementById('checks-summary');
  if (el) setTimeout(() => el.scrollIntoView({behavior: 'smooth', block: 'start'}), 50);
}

function filterSummaryTable() {
  const angle = document.getElementById('summary-angle-filter').value;
  const sev = document.getElementById('summary-sev-filter').value;
  const issuesOnly = document.getElementById('summary-issues-only').checked;

  document.querySelectorAll('.summary-table .summary-row').forEach(row => {
    const rAngle = row.dataset.angle;
    const rSev = row.dataset.sev;
    const rCount = parseInt(row.dataset.count, 10);

    let show = true;
    if (angle && rAngle !== angle) show = false;
    if (sev && rSev !== sev) show = false;
    if (issuesOnly && rCount === 0) show = false;
    row.style.display = show ? '' : 'none';
  });
}

showView('heatmap');
"""
