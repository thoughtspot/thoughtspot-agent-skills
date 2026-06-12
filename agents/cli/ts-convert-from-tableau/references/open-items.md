# Open Items: ts-convert-from-tableau

---

## #1 — VALIDATE_ONLY policy in ts CLI — NEEDS VERIFICATION

The skill uses `ts tml import --policy VALIDATE_ONLY` for the fix loop. Verify that the
`ts` CLI supports this policy flag and returns structured error JSON (not just HTTP status).

Alternative: if VALIDATE_ONLY is unsupported, use `--policy PARTIAL` with a dry-run flag,
or call the REST v2 endpoint directly:
`POST /api/rest/2.0/metadata/tml/import` with `{"import_policy": "VALIDATE_ONLY", "dry_run": true}`

Status: NEEDS VERIFICATION against live cluster

---

## #2 — Connection schema fetch for empty `externalDatabases` — VERIFIED WORKAROUND

When the REST v2 `connections get` endpoint returns no tables (empty `externalDatabases`),
the Callosum `fetchConnection` API can be used with an explicit `database` parameter.
However, the `ts` CLI may not expose this. In that case, ask the user for the database
name and proceed with `YOUR_DATABASE`/`YOUR_SCHEMA` placeholders — ThoughtSpot issues a
warning, not an error, for placeholder values.

Status: WORKAROUND DOCUMENTED in Step 4

---

## #3 — COLLECTION datasources — NOT IMPLEMENTED

Tableau COLLECTION datasources (multiple primary data sources combined) should generate
one model per underlying table. This edge case is not handled in v1.0.0.

Status: DEFERRED to v1.1.0

---

## #4 — Custom SQL relations — RESOLVED

Custom SQL relations now generate `sql_view:` TMLs instead of extracting table names
from the SQL string. The full SQL text is preserved in `sql_query:`, columns are mapped
via `sql_output_column`, and the SQL View is referenced by name in the model's
`model_tables[]`. See Step 5c in SKILL.md and `tableau-tml-rules.md` "SQL View TML Rules".

Status: RESOLVED in v1.1.0

---

## #5 — Answer TML inline vs. separate import — NEEDS VERIFICATION

The skill generates answer content inline within the liveboard's `visualizations` section.
Verify that this structure imports correctly — specifically that `answer:` blocks nested
inside `visualizations[]` are accepted by `ts tml import`.

Status: NEEDS VERIFICATION against live cluster

---

## #6 — Liveboard layout coordinate system — NEEDS VERIFICATION

Step 9c maps Tableau 0–100,000 coords to a ThoughtSpot 12-column grid. Verify:
- The exact column width unit ThoughtSpot uses in TML (is it 1/12 of the liveboard width?)
- The height unit (pixels? rows? a relative unit?)
- The minimum and maximum tile height values

Reference: `thoughtspot-liveboard-tml.md` schema doc for exact field semantics.

Status: NEEDS VERIFICATION

---

## #7 — NOTE_TILE structure — NEEDS VERIFICATION

The skill generates `viz_type: NOTE_TILE` with `note_tile.content`. Verify the exact TML
structure for note tiles against the liveboard TML schema, especially:
- Is `viz_type` the correct field name?
- What is the supported `background_color` format?
- Can note tiles contain HTML or markdown?

Status: NEEDS VERIFICATION

---

## #8 — Multi-datasource worksheets — NOT IMPLEMENTED

Tableau worksheets can blend data from multiple datasources. v1.0.0 assumes each worksheet
uses a single datasource. Blended worksheets will produce an incomplete liveboard
visualization.

Status: DEFERRED to v1.1.0

---

## #9 — Tab support (multiple dashboards → tabs) — NOT IMPLEMENTED

When a Tableau workbook has multiple dashboard sheets, v1.0.0 creates one liveboard per
dashboard. ThoughtSpot supports liveboard tabs — grouping all dashboards into a single
multi-tab liveboard is a better migration output but requires the liveboard tabs TML
structure.

Status: DEFERRED to v1.1.0

---

## #10 — Dynamic Sets — Phase 2a + 2b DONE; 2c deferred

Phase 2a DONE: static sets (top-level `<group>` with `function='union'`+`function='member'`
groupfilter trees) → ThoughtSpot `GROUP_BASED` column sets (`cohort_type: SIMPLE`). Detected
by `function='union'`+`function='member'` presence and absence of `function='end'`/`'except'`/`'intersect'`.

Phase 2b DONE (2026-06-12): Top-N/Bottom-N sets (`function='end'` in groupfilter) →
ThoughtSpot `ADVANCED` query sets (`cohort_type: ADVANCED`, `cohort_grouping_type:
COLUMN_BASED`) with embedded answer holding a rank formula + parameter-filter formula.
Live-verified on se-thoughtspot (model `TEST_SV_DMSI_AI_CONTEXT`). See SKILL.md
Step 5b "Query-set TML emission" and worked example
`agents/shared/worked-examples/tableau/topn-set-to-query-set.md`.

Deferred (logged, never mis-translated):
- **Phase 2c** — Set operations (`function='intersect'`, or `function='except'` of a
  computed/non-member sub-tree) → no ThoughtSpot equivalent yet.
- **No equivalent** — Worksheet set actions (`<action>` on a set) — logged and omitted.

Status: Phase 2a DONE (2026-06-12); Phase 2b DONE (2026-06-12); Phase 2c DEFERRED

---

## #11 — Geospatial functions — DEFERRED (Phase 3)

Tableau geospatial functions (MAKELINE, MAKEPOINT, DISTANCE, etc.) have no ThoughtSpot
formula equivalent. See parent plan for Phase 3 (future round).

Status: DEFERRED

---

## #12 — Missing function-table entries — DONE (Phase 1, 2026-06-12)
DATEPARSE/DATETIME/EXP/PI/trig/PROPER/ASCII/CHAR/STARTSWITH/ENDSWITH added to
tableau-formula-translation.md, all grounded against the 26.6.0 formula reference.
PI/RADIANS/DEGREES use literal composites (no native); PROPER/ASCII/CHAR map to
scalar sql_*_op pass-through (no native equivalent — PT1). Trig converts radians→degrees.
Status: DONE.

---

## #13 — REGEXP family + FINDNTH — PASS-THROUGH ONLY
REGEXP_EXTRACT/MATCH/REPLACE, FINDNTH have no native TS equivalent — mapped to
sql_*_op pass-through (warehouse-dialect-specific) or omit+log.
Status: DONE pending confirmation.

---

## #14 — Extended WINDOW_*/RUNNING_* — DOCUMENTED AS TABLE CALCS
WINDOW_STDEV/PERCENTILE/COUNT/MEDIAN and RUNNING_COUNT documented as answer-level
table calcs (EXC1) with aggregate fallbacks; no model-formula form.
Status: DONE.
