# Dependency types — coverage and hierarchy

What this file is, in one paragraph: a single source of truth for **every kind of object the
ts-dependency-manager skill considers a "dependent"**, what the skill can detect about each,
and where each fits in the dependency hierarchy. Read this before adding new dep handling
or before changing how Step 4 walks the graph. When the status of a row here changes
(e.g. a "Partial" entry becomes "Implementable" because retrieval is now verified),
update both this file AND the corresponding `references/open-items.md` entry.

Status legend:
- **Implementable** — retrieval verified, detection & update logic sketched
- **Partial** — TML structure known but retrieval mechanism not yet verified
- **Manual** — cannot be programmatically discovered on this build; manual-review fallback
- **GUID-stable** — no skill action needed (the underlying ID survives the rename/remove)
- **Informational** — surfaced in the impact report but never modified by the skill

---

## A. Dependency-type status — what the skill can and cannot check

| # | Dependency type | What it is | Where it lives | Discoverable? | Detection signal | RENAME action | REMOVE action | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | **Model / Worksheet** | Logical model built on tables | own TML (`model:` root) | Yes — v2 dependents bucket `LOGICAL_TABLE` (subtype WORKSHEET) | source GUID in `model_tables[].fqn`; column-name in `columns[].column_id` suffix or `formulas[].expr` | rewrite `column_id` (`TBL::OLD` → `TBL::NEW`) and formula expressions | strip from `columns[]`, drop dependent formulas, drop join_with entries that reference it (open-item #4), drop model-level filters (open-item #12) | Implementable |
| 2 | **View** | Aggregated/joined view over a model | own TML (`view:` root) | Yes — v2 dependents bucket `LOGICAL_TABLE` (subtype AGGR_WORKSHEET) | column-name in `view_columns[].column_id` or `formulas[].expr` or `search_query` | update `column_id` suffix, formula expressions, and `search_query` tokens; also `search_output_column` if it diverges from `name` (open-item #10 layer C) | strip `view_columns[]`, drop formulas, sanitize `search_query`, drop joins | Implementable |
| 3 | **Answer** | Saved search result | own TML (`answer:` root) | Yes — v2 dependents bucket `QUESTION_ANSWER_BOOK` | column-name in `answer_columns[].name`, `chart.chart_columns[].column_id`, `chart.axis_configs[].{x,y,color,size,shape}`, `formulas[].expr`, `search_query`, `cohorts[].config.anchor_column_id` | rewrite all of the above | strip column from `answer_columns`, axis bindings (color/size/shape only — x/y require chart removal decision), formulas, search_query, and answer-level cohorts | Implementable |
| 4 | **Liveboard** | Pinboard composed of viz | own TML (`liveboard:` root) | Yes — v2 dependents bucket `PINBOARD_ANSWER_BOOK` | same as Answer (each viz embeds an `answer:` block); plus liveboard-level `filters[].column[]` | apply Answer-level rewrites to each affected viz; rewrite `filters[].column[]` | per-viz REMOVE_COLUMN / REMOVE_COLOR_BINDING / REMOVE_CHART decisions (skill Step 6); drop liveboard-level filters whose column list goes to zero | Implementable |
| 5 | **Set / Cohort** | Reusable filter group | own TML (`cohort:` root); read via v2 dependents `COHORT` bucket on the source | Yes — v2 dependents `COHORT` bucket (NOT a valid SearchMetadataType — query the source, then read its consumers via the Set's own GUID with `LOGICAL_COLUMN`) | `config.anchor_column_id` (primary anchor), or column appears in `pass_thru_filter`, `groups[].conditions[].column_name`, or embedded `cohort.answer.search_query` | rewrite `anchor_column_id`, `return_column_id`, `groups[].conditions[].column_name`, `pass_thru_filter.{include,exclude}_column_ids`, embedded answer | DELETE if anchor matches (set is invalidated); FIX (strip references) if column is only in body | Implementable |
| 6 | **Spotter feedback** | NLS coaching examples on a model | model's `--associated` export, type `nls_feedback` | Partial — v2 dependents `FEEDBACK` bucket on a model returns the GUIDs, but TML export of the GUID directly fails (open-item #18) | column-name in `feedback[].search_tokens` or `formula_info` references | update `search_tokens` (regex on `[OLD]` → `[NEW]`) | drop matching feedback entries from the list | Partial — read works via `--associated`; standalone GUID export broken |
| 7 | **Monitor alert** | Threshold/anomaly alert on a viz | Liveboard/Answer's `--associated` export, type `monitor_alert` | Yes — Liveboard `--associated` export returns `monitor_alert` doc with all alerts on that liveboard | column-name in `monitor_alert[].personalised_view_info.filters[].column[]` (format `TABLE::COL_NAME`) | rewrite filter column refs; if alert's anchor viz is being removed, prompt user to delete the alert | drop filters whose column lists go to zero; if alert ends up filterless AND its viz is being removed, delete the alert | Implementable |
| 8 | **RLS rule** | Row-level security policy | inline in base table TML (`table.rls_rules`) | Yes — every base table TML returned by `--associated` includes its own `rls_rules` if any | column listed in `rls_rules.table_paths[].column[]` and referenced in `rules[].expr` as `[path_id::COL_NAME]` | update `table_paths[].column[]` and rewrite `rules[].expr` | **STOP CONDITION** — silently breaks access control. Block until user removes the rule via UI or explicitly accepts the security impact | Implementable |
| 9 | **Column security rule (CSR)** | Per-group column allowlist, scoped to a base table | own TML file `<TABLE>_CSR.column_security_rules` | **No on this build** — not returned by v2 `--associated` even on tables that have CSR; cs_tools has zero references; likely UI-download or VCS-commit only | column-name in `column_security_rules.rules[].column_name` | update matching `column_name` | drop matching rule(s); **STOP CONDITION** — dropping a CSR rule changes who can see the rest of the table's data | Partial — structure known, retrieval mechanism unverified (open-item #9) |
| 10 | **Column alias TML** | Per-locale, per-org, per-group display names at model scope | own TML file `<MODEL>.column_alias` | **No on this build** — same status as CSR | model alias in `column_alias.columns[].name`; localized strings in `locales[].orgs[].groups[].entries[].alias` | rewrite the matching `columns[].name`; localized aliases left untouched by default (independent strings) | drop the matching `columns[]` entry entirely | Partial — structure known, retrieval mechanism unverified (open-item #10) |
| 11 | **Inline alias** (Model `name` vs `column_id`, Table `name` vs `db_column_name`, View `name` vs `search_output_column`) | TS-side label vs underlying ref | already in the standard Model/Table/View TML | Yes — comes back in every standard export | difference between `name` and the underlying field for the same column entry | depends on which layer the user is renaming (DB column vs label) — Step 3-N should distinguish | not applicable — alias goes away with the column | Implementable (extension to `rename_column_in_view` for `search_output_column` is pending) |
| 12 | **Column-level ACLs** (sharing) | Who can MODIFY/READ this specific column | ORM records keyed by column GUID; fetched via `POST /api/rest/2.0/security/metadata/fetch-permissions` with `type: LOGICAL_COLUMN` | Yes — v2 endpoint works | not needed — ACLs are GUID-keyed and column GUIDs survive renames | none — ACLs follow the column automatically | none — orphaned ACLs become inert when the column is dropped | GUID-stable — no skill action needed |
| 13 | **Schedule** (scheduled report delivery) | Cron-driven PDF/XLSX export of a Liveboard | `POST /api/rest/2.0/schedules/search` | Yes — but doesn't reference columns; it references the Liveboard as a whole | Liveboard GUID in `metadata.id` | not applicable — schedules don't reference columns | informational only — schedule still runs after column removal but the rendered output may be missing data | Informational |
| 14 | **Connection** | Source of base tables | own TML | Yes — but never affected by a column-level operation on a table or model | not applicable | none | none — column changes don't propagate up to the connection | Informational |

---

## B. Dependency hierarchy

What the skill walks during Step 4. Solid arrows = standard dependencies via v2 dependents API; dotted arrows = TML-attached objects that come through `--associated` exports; dashed arrows = TMLs that exist but are not retrievable on this build.

```
                  [CONNECTION]
                       │
                       ▼
                   [TABLE]──────────────────┐
                  /  │  \                   │
                 /   │   \              (inline)
                /    │    \                 │
               /     │     \                ▼
              /      │      ╲       [table.rls_rules]
             /       │       ╲              (#8 RLS)
            /        │        ╲
           ▼         ▼         ╲- - -→ [<TABLE>_CSR.column_security_rules]
       [MODEL]    [VIEW]                   (#9 — retrieval unverified)
        / │ \      │ │
       /  │  \     │ │
      /   │   ╲    │ │
     /    │    ╲   │ │
    ▼     ▼     ▼  ▼ ▼
 [ANSWER] │  [SET]   ┊
     │    │     │    ┊  (model-attached)
     │    │     ▼    ┊
     │    │  [ANSWER consumers via Set]
     │    │
     ▼    ▼
 [LIVEBOARD]
     │   │  ............→ [<MODEL>.column_alias]
     │   │       (#10 — retrieval unverified)
     │   │
     │   └ ............→ [nls_feedback]   (#6 partial via --associated)
     │
     ├ ............→ [monitor_alert]   (#7 verified via --associated)
     ▼
[SCHEDULE]   (informational only — column-agnostic)
```

Read top-down: removing a column on a TABLE potentially affects every Model that uses it,
every Model affects every View / Answer / Set built on it, every Set affects its consuming
Answers/Liveboards, every Liveboard may have Alerts and Schedules attached. RLS lives ON
the table (inline), CSR lives next to the table (separate TML), and Column Alias TML lives
next to the model (separate TML).

### Walking order (Step 4 implementation)

For source = **TABLE**:

1. Read source table TML — collect inline RLS rules (immediate STOP-condition check)
2. v2 dependents on source GUID — collect direct Models and Views
3. For each Model found, recurse: v2 dependents on the Model — collect Answers, Liveboards, Sets, Feedback (transitive consumers via the Model)
4. For each Set found, query its own dependents (`type: LOGICAL_COLUMN`) for the Answers/Liveboards consuming it
5. For each Liveboard, export `--associated` to retrieve attached `monitor_alert` docs
6. Filter all of the above by whether the affected COLUMN is actually referenced (TML scan)
7. Skipped on this build: CSR (#9) and column_alias (#10) — flag in the impact report's "Not Checked" section

For source = **MODEL**:

1. Skip step 1 (no RLS on a model — it's on the underlying tables; the skill should also check those)
2. Skip step 2 — start at the Model directly
3. Continue from step 3 onward
4. Also walk back to the Model's `model_tables[].fqn` and check each base table for RLS rules referencing the underlying column

---

## C. Sample output — what the user sees in Step 5 impact report

For a hypothetical removal of `Customer Zipcode` (model alias for `DM_CUSTOMER_BIRD::ZIPCODE`)
on TEST_DEPENDENCY_MANAGEMENT:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 IMPACT REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Source:   TEST_DEPENDENCY_MANAGEMENT (MODEL)
Change:   Remove column "Customer Zipcode"  (DM_CUSTOMER_BIRD::ZIPCODE)

⛔  STOP CONDITIONS — REQUIRES CONFIRMATION

   RLS RULE on DM_CUSTOMER_BIRD references this column:
     - Rule:    testRLS
     - Path:    DM_CUSTOMER_BIRD_1
     - Expr:    [DM_CUSTOMER_BIRD_1::ZIPCODE] = ts_groups_int
     Removing the column without first removing or rewriting this RLS rule
     will silently break access control. Resolve before continuing.

   CHART AXIS CONFLICTS (1 viz):
     - TEST_DEPENDENCY_LIVEBOARD / Total Amount by Daily Balance Date
       (Y axis: Customer Zipcode) — per-viz decision required at Step 6.

7 dependent object(s) found:
  3 HIGH   3 MEDIUM   1 LOW
```

### Models / Views

| Risk | Type  | Name                  | GUID         | Owner          | Action                          |
|------|-------|-----------------------|--------------|----------------|---------------------------------|
| HIGH | VIEW  | TEST_DEPENDENCY_VIEW  | 91dd9901-... | damian.waldron | REMOVE_COLUMN                   |

### Answers / Liveboards

| Risk   | Type      | Name                       | GUID         | Owner          | Action                          |
|--------|-----------|----------------------------|--------------|----------------|---------------------------------|
| HIGH   | LIVEBOARD | TEST_DEPENDENCY_LIVEBOARD  | 2fa59781-... | damian.waldron | REMOVE_CHART (1 viz)            |
| MEDIUM | ANSWER    | TEST_DEPENDENCY_ANSWER     | f16015e6-... | damian.waldron | REMOVE_CHART → CONVERT_TO_TABLE |

### Alerts (verified retrievable via Liveboard --associated)

| Risk   | Type   | Name                                                          | Anchor viz   | Filter refs |
|--------|--------|---------------------------------------------------------------|--------------|-------------|
| MEDIUM | ALERT  | Alert on Total Amount by Daily Balance Date                   | b5e803c6-... | TEST_DEPENDENCY_MANAGEMENT::Customer Zipcode |
| MEDIUM | ALERT  | Dependency Alert on Total Amount by Daily Balance Date        | b5e803c6-... | TEST_DEPENDENCY_MANAGEMENT::Customer Zipcode |

These alerts have filters that will become empty if Customer Zipcode is removed.
If you choose REMOVE_CHART for the anchor viz, both alerts will be deleted.
If you keep the viz (CONVERT_TO_TABLE), the alerts continue but lose this filter.

### Spotter feedback

| Risk | Name                                | GUID         | Parent model               |
|------|-------------------------------------|--------------|----------------------------|
| LOW  | by customer zipcode                 | ce706506-... | TEST_DEPENDENCY_MANAGEMENT |
| LOW  | sum of quantity by customer zipcode | f73c8416-... | TEST_DEPENDENCY_MANAGEMENT |

### Dependency tree

```
[CONNECTION] APJ_BIRD
  │
  └─ [TABLE] DM_CUSTOMER_BIRD
       │   └─ [RLS] testRLS — [ZIPCODE]  ⛔ STOP CONDITION
       │
       └─ [MODEL] TEST_DEPENDENCY_MANAGEMENT
            ├─ [VIEW] TEST_DEPENDENCY_VIEW                        REMOVE_COLUMN
            ├─ [ANSWER] TEST_DEPENDENCY_ANSWER                    CONVERT_TO_TABLE
            ├─ [LIVEBOARD] TEST_DEPENDENCY_LIVEBOARD              REMOVE_CHART (1 viz)
            │   ├─ [ALERT] Alert on Total Amount by Daily Balance Date
            │   └─ [ALERT] Dependency Alert on Total Amount by Daily Balance Date
            ├─ [FEEDBACK] by customer zipcode
            └─ [FEEDBACK] sum of quantity by customer zipcode
```

### Scan coverage

```
  CHECKED                 FOUND   NOTES
  ──────────────────────  ──────  ────────────────────────────────────────────
  Models                  1
  Views                   1
  Answers                 1
  Liveboards              1
  Sets / Cohorts          0       (none anchored on this column)
  Spotter feedback        2       (via --associated on the model)
  Monitor alerts          2       (via --associated on the liveboard)
  RLS rules               1       (inline in DM_CUSTOMER_BIRD table TML)

  NOT CHECKED — manual review recommended
  ──────────────────────  ──────  ────────────────────────────────────────────
  Column security rules   —       open item #9: structure known but not retrievable
                                    via --associated on this build (likely UI-download
                                    or VCS-commit only). Run a manual UI export of
                                    DM_CUSTOMER_BIRD and review *_CSR.column_security_rules
                                    if any rules reference ZIPCODE.
  Column alias TML        —       open item #10: same status as CSR. Manual review the
                                    model's column_alias TML if locale aliases exist
                                    for "Customer Zipcode".
  Schedules               1       informational only — Schedule "TEST_LB_Daily" delivers
                                    the liveboard as PDF; column-agnostic, no action needed
```

---

## Maintaining this file

When **any** of these change, update both this file AND the corresponding
`references/open-items.md` entry in the same commit:

- A row in section A moves between status values (e.g. Partial → Implementable when
  retrieval is verified, or a new ThoughtSpot build introduces a new dep type)
- The hierarchy in section B changes (a new dep type is added, or the walking order
  in Step 4 of SKILL.md changes)
- The sample output in section C drifts from what Step 5 actually produces

The pre-commit hook ([scripts/pre-commit.sh](../../../../scripts/pre-commit.sh)) prompts
when SKILL.md or `references/open-items.md` is staged without this file — soft nudge,
not a hard fail. The reviewer's checklist is in the repo's
[CLAUDE.md change impact map](../../../../CLAUDE.md).
