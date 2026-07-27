# Open items — ts-convert-from-powerbi

Unverified assumptions / follow-ups. Each must reach VERIFIED (live or via MCP spec) or be
explicitly deferred before this ships live.

## #1 — Live e2e faithful-numbers proof — VERIFIED 2026-07-16 (ps-internal, AnujSeth org)

Full chain proven live. `build-model` → the 10 Table TMLs validate against the real Databricks
connection ("Sisense Migration - Databricks", `workspace.sisense_demo`). `VALIDATE_ONLY` flags two
engine-rejected formulas — `MonthIncrementNumber` (`min()` used in row-level scalar arithmetic) and
`EmpCount` (point-in-time) — which the prune step (SKILL.md Step 2) removes; the model then creates
clean. **Faithful numbers / no double-count:** searchdata `[New Hires]` = 878; `[New Hires] [Gender]`
= F 422 + M 456 = 878 → the grouped sum equals the ungrouped total, so the `Employee→Gender`
`MANY_TO_ONE` join does NOT fan out (the bar the Tableau PR met). A throwaway model (`ZZ PBI E2E
Employee`) was created and deleted; the cluster was left clean.

Follow-up (translator refinement, not a blocker): `MonthIncrementNumber` (`(Year - min(Year))*12 + …`)
and `EmpCount` translate to expressions the engine rejects but the safe-subset marks Migrated — the
runtime prune handles them, but the translator could pre-flag `min()`/`max()` used as a row-level
scalar as NEEDS REVIEW instead of relying on the cluster to reject it.

## #2 — Formula cross-references: id-refs resolve on first import — VERIFIED 2026-07-09

Controlled 2×2 on ps-internal (`metadata/tml/import`): `[formula_<id>]` id-references resolve
on first import, **independent of declaration order**; display-name references `[Other Formula]`
fail. So the converter's `[formula_<name>]` id-refs + topo-sort are correct; the topo-sort is
defensive, not load-bearing. No change needed; see the shared model-tml invariant note.

## #3 — Combo `custom_chart_config` GUID requirement — KNOWN (handled by the shared emitter)

A combo's line-vs-column split via `custom_chart_config` references columns by GUID, so a
hand-authored (display-name) config errors `Invalid GUID string` on a fresh import. The shared
`build_from_spec` already drops a display-name config and lets the `ADVANCED_*` type
auto-resolve; a durable pin needs a captured (exported) GUID-based config. Verify per workbook.

## #4 — "Measures/visuals not shown" report granularity — DEFERRED

`build-liveboard` skips non-visuals (slicers/shapes/buttons) on the PBI side, so they don't
appear as Skipped rows in the report yet (the liveboard itself is correct). A later enhancement
records skipped decorations + measures on no visual. Not a blocker.

## #5 — Spotter last-mile — VERIFIED 2026-07-21 (ps-internal, AnujSeth org)

`ts spotter answer` (`POST ai/answer/create`) drafts a flagged time-intelligence measure from
plain English on a Spotter-enabled model. Verified live on the Employee model (`e17c5fae`):
"new hires by month this year versus last year" → `New Hires, Date = 'this year' vs Date =
'last year', Month` (native period comparison, i.e. the SPLY rebuild); "new hires monthly year
over year change" → `growth of New Hires by ... year-over-year`; "separations this year vs last
year" → `Seps, Date = 'this year' vs Date = 'last year'`. So a measure that can't be
auto-translated from DAX (SAMEPERIODLASTYEAR / YoY) is recoverable by asking Spotter, and the
drafted tokens are sensible. The tokens are still shown to a human to verify before adopting;
never auto-adopt.
