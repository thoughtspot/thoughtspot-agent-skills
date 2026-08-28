# Migration report format (`mapping.json`)

`ts domo build-model` and `build-liveboard` both write/extend `mapping.json` — the single
deliverable that accounts for every Domo object and its conversion status. Same shape as the rest
of the family so downstream tooling and the audit mode can read all converters uniformly.

## Status vocabulary
- **Migrated** — faithful 1:1 conversion.
- **Approximated** — converted with a documented approximation (verify).
- **NEEDS REVIEW** — emitted verbatim or skipped; a human must rebuild/verify.
- **Skipped** — intentionally not converted (with reason).

## Shape

```json
{
  "source": { "mode": "offline|domo-cloud", "app_name": "Sales Overview" },
  "datasets": [
    { "domo_id": "61c4e63d-…", "name": "Sample Sales Transactions",
      "ts_table": "Sample Sales Transactions", "columns": 10, "status": "Migrated" }
  ],
  "joins": [
    { "left": "…", "right": "…", "on": "Customer ID", "inferred": true,
      "status": "NEEDS REVIEW", "note": "inferred by shared column name" }
  ],
  "beast_modes": [
    { "domo_id": 1001, "name": "Net Revenue",
      "domo_formula": "SUM(`Revenue`) - SUM(`Discount`)",
      "ts_formula": "sum([Revenue]) - sum([Discount])", "status": "Migrated" }
  ],
  "cards": [
    { "urn": "500000001", "title": "Net Revenue", "chart_type": "kpi",
      "ts_chart": "KPI", "status": "Migrated", "notes": [] }
  ],
  "pages": [
    { "domo_id": 900000002, "name": "Sales Overview",
      "ts_liveboard": "Sales Overview", "cards": 3, "tabs": 1, "status": "Migrated" }
  ],
  "notes": [
    { "object_type": "beast_mode", "object_id": 1099, "severity": "needs_review",
      "message": "window function RANK() has no ThoughtSpot equivalent — left verbatim" }
  ]
}
```

## Rules
- **Every** dataset, Beast Mode, card and page appears exactly once with a status.
- Every `NEEDS REVIEW` / `Approximated` row carries a `note` explaining the gap and the original
  Domo definition, so a human can rebuild without re-opening Domo.
- Inferred joins are **always** `NEEDS REVIEW`.
- The report is the hand-off: when presenting, lead with the NEEDS REVIEW rows.

## Rendered report (`ts domo report` → `migration_report.md`)

`render_report(mapping, lb_mapping)` turns the JSON above into the family-standard **rich**
Markdown report (same shape as qlik/looker — see [migration-report.example.md](migration-report.example.md)).
Every number is derived from the mappings; nothing is invented. Sections, in order:

1. **Header** — app, source mode, provenance (SOURCE model / Magic-ETL joins / INFERRED charts).
2. **Executive summary** — complexity, automation vs manual %, estimated effort, risk score
   (all derived from table/join counts and flag ratios).
3. **Inventory** — tables, columns, relationships, measures, pages, visuals.
4. **Modernization** — dashboards eliminated/merged, Search & Spotter opportunities, semantic
   improvements (derived from clean vs flagged formulas, renamed columns, joins).
5. **Summary by object type** — In Domo / Migrated / Approximated / Needs review / Skipped.
6. **Data model** — Tables, Relationships → joins, Beast Modes → Formulas.
7. **Cards → answers & liveboard** — each card's ThoughtSpot chart + status.
8. **Manual review** — leads with every NEEDS REVIEW / Approximated item, plus a **chasm-trap**
   warning when ≥ 2 joins share a key (multi-fact fan-out risk).
9. **Verification checklist** — concrete spot-checks (match a known total, confirm no fan-out).
10. **ThoughtSpot Modernization Scorecard** — Semantic Model / Search / Spotter / Liveboards /
    AI Readiness scores + recommendations, scaled by the flag ratios.
