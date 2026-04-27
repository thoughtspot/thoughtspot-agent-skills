# Open Items — ts-coach-model

Items that need verification against a live ThoughtSpot (or Snowflake) instance before
the skill is considered fully verified. Update each item with findings after testing.

Status legend: **CONFIRMED** (direction known, needs live verification) | **VERIFIED** (tested) | **OPEN** (unknown)

Test against the staging Model recorded in `reference_ts_dep_staging_objects.md` memory
(champagne-master) plus the Dunder Mifflin Sales & Inventory Model
(`4da3a07f-fe29-4d20-8758-260eb1315071`) for full end-to-end coverage.

---

## #1 — Mining dependent Liveboards/Answers via verified v2 API — VERIFIED

The verified v2 API contract from
[~/.claude/skills/ts-dependency-manager/references/open-items.md](~/.claude/skills/ts-dependency-manager/references/open-items.md)
#1 (CONFIRMED on champ-staging 2026-04-25 against the Dunder Mifflin Model):

```http
POST /api/rest/2.0/metadata/search
{
  "metadata": [{"identifier": "{model_guid}", "type": "LOGICAL_TABLE"}],
  "include_dependent_objects": true,
  "dependent_object_version": "V2"
}
```

Response shape:
```json
[{"dependent_objects": {"dependents": {"{model_guid}": {
    "QUESTION_ANSWER_BOOK": [...], "PINBOARD_ANSWER_BOOK": [...]
}}}}]
```

The `ts metadata search` CLI does NOT yet expose the `--include-dependent-objects` flag.
Until it does, the skill calls this v2 endpoint directly (acceptable per
`.claude/rules/ts-cli.md` because the API contract is verified in another skill's
open-items.md and has been validated against this exact instance).

**Action:** propose `ts metadata dependents <guid>` as a new ts-cli command; until
shipped, the skill uses the direct API call.

---

## #2 — `nls_feedback` standalone TML import — VERIFIED (positive) — 2026-04-26

**`nls_feedback` standalone TML import works** on ThoughtSpot Cloud. Verified 2026-04-26
against Dunder Mifflin Sales & Inventory on champ-staging: 60 fresh entries imported
via `ts tml import --policy ALL_OR_NONE --no-create-new` with the standalone
`nls_feedback` TML payload. All 60 persisted on the Model (confirmed via verification
path below).

**The trap that misled v1 of this skill:** `ts tml export {model_guid} --associated --parse`
does NOT surface feedback entries even though they exist on the Model. The export
returns only `model` + `table` items.

### Correct verification path

Feedback entries are dependents of the Model object, surfaced via
`POST /api/rest/2.0/metadata/search` with `include_dependent_objects: true`. They live
under `dependent_objects.dependents.{model_guid}.FEEDBACK[]` — separate key from
`QUESTION_ANSWER_BOOK[]` and `PINBOARD_ANSWER_BOOK[]`.

```python
# Correct way to enumerate feedback entries on a Model:
import urllib.request, json
req = urllib.request.Request(
    f"{base_url}/api/rest/2.0/metadata/search", method="POST",
    headers={"Authorization": f"Bearer {token}", "X-Requested-By": "ThoughtSpot",
             "Content-Type": "application/json"},
    data=json.dumps({
        "metadata": [{"identifier": model_guid, "type": "LOGICAL_TABLE"}],
        "include_dependent_objects": True,
        "dependent_object_version": "V2",
    }).encode(),
)
body = json.loads(urllib.request.urlopen(req).read())
feedback_entries = body[0]["dependent_objects"]["dependents"][model_guid].get("FEEDBACK", [])
# Each entry: {id, name (= feedback_phrase), description (= type), author, created, ...}
```

### Import response interpretation

Successful feedback imports return `{header, status: {status_code: OK}}` with **empty
`diff: {}`** and **no `object` field** — different from Model TML imports which
return `diff: {columns_updated: N}`. Don't interpret empty diff as failure for
feedback imports.

"Duplicates will be replaced" warnings are accurate — they reference entries
already on the Model from prior runs.

### Action for the skill

Step 9b verification must use `metadata/search` with `include_dependent_objects`,
NOT `ts tml export --associated`. The `--associated` export does NOT include
feedback. SKILL.md Step 9c should be updated to count entries via the search API
path.

### Implication for skill scope

Surfaces 3 (Reference Questions) and 4 (Business Terms) ARE fully automatable via
TML import. No manual-entry workaround is required for v1. The earlier conclusion
that "standalone import is broken" was wrong — caused by checking the wrong API.

### Feedback content retrieval — OPEN — 2026-04-26 (degrades skill, non-blocking)

Enumeration via the dependents API returns entry **headers only** (`id`, `name` =
phrase, `description` = type, author, modified). The full content
(`search_tokens`, `formula_info`, `access` level, `chart_type`, `display_mode`)
is not surfaced anywhere on champ-staging. Verified 2026-04-26 against the Dunder
Mifflin Model — none of the following return content:

| Endpoint / approach | Result |
|---|---|
| `ts tml export <feedback_guid>` | error 10002 — "Specified identifier doesn't exist" |
| `POST /api/rest/2.0/metadata/tml/export` with `type=FEEDBACK` | 400 — same error |
| `POST /api/rest/2.0/metadata/search` with `type=FEEDBACK` | 400 — `FEEDBACK` not in `SearchMetadataType` enum |
| `GET /api/rest/2.0/metadata/feedback/{id}` | 500 |
| `GET /api/rest/2.0/metadata/{id}` (where id is feedback guid) | 500 |
| `POST /api/rest/2.0/sage/feedback/list` | 500 |
| `POST /api/rest/2.0/spotter/feedback/list` (with model identifier) | 500 |
| `POST /api/rest/2.0/metadata/nls_feedback/export` | 500 |
| `tml/export` of model with `export_feedback`, `include_feedback`, `export_nls_feedback`, `export_dependent` flags | All return 9 items (model + 8 tables); never include `nls_feedback` |

This is the same root cause as
[ts-dependency-manager open-item #18](~/.claude/skills/ts-dependency-manager/references/open-items.md) —
the correct content endpoint is unknown across both skills.

#### Header-only fallback (skill behaviour while this is open)

The skill **degrades gracefully** when content is unretrievable:

| Surface / step | With content | Header-only fallback |
|---|---|---|
| Step 2b GLOBAL/USER split | Split by `access` field | All entries treated as `UNKNOWN_ACCESS`; Step 5 USER opt-in collapses to no-op |
| Step 3d input signal | Existing `search_tokens` seed paraphrase variants | Skip — no tokens available |
| Step 4 §4b stale-reference critique | Cross-check tokens vs current schema | Soft warning when entry phrase mentions a column not on the Model |
| Step 6 dedup | By `feedback_phrase` exact match (lower-cased) | Same — phrase IS exposed in headers |
| Step 6.3 paraphrase variants from existing entries | Reuse existing `feedback_phrase` for matching `search_tokens` | Skip — no token mapping to anchor variants |

When the correct endpoint is identified, restore the full Step 2b GLOBAL/USER split
and re-enable variant generation in Step 6.3. SKILL.md Step 2b includes the fallback
flag `feedback_content_retrievable: False` so downstream steps key off it cleanly.

#### Action

- Probe ThoughtSpot v2 OpenAPI doc once accessible — there must be a content endpoint
- Ask ThoughtSpot engineering for the correct path — same question as
  ts-dependency-manager #18
- Once verified, update Step 2b code, remove the fallback branch, mark this
  sub-item VERIFIED

---

## #3 — Column `ai_context` and `synonyms` round-trip — VERIFIED — 2026-04-26

Verified on 2026-04-26 against Dunder Mifflin Sales & Inventory Model on champ-staging.

**ai_context: VERIFIED** — round-trips cleanly when written to
`model.columns[].properties.ai_context`. 19/19 columns in the test survived a full
import + re-export cycle with values matching exactly.

**synonyms: VERIFIED with documentation correction**
- ❌ Schema doc says `model.columns[].synonyms[]` (column-level field) — **WRONG**, the
  import silently drops it (0/16 columns survived round-trip)
- ✅ Correct location is `model.columns[].properties.synonyms[]` — **inside `properties`**.
  Verified: 16/16 columns round-tripped with all 54 phrases preserved.

The companion field `properties.synonym_type: USER_DEFINED` is also accepted and
round-trips cleanly (must be set explicitly; ThoughtSpot does not infer it).

**Action: update [~/.claude/shared/schemas/thoughtspot-model-tml.md](~/.claude/shared/schemas/thoughtspot-model-tml.md) line 134:**
```diff
- | `synonyms` | No | Array of alternative names for search. |
+ | `properties.synonyms` | No | Array of alternative names for search. Must be inside `properties`, not at column-level (verified 2026-04-26 on Cloud). |
```

The diff field on Model TML import returns `columns_updated: N` where N counts only
columns where structural fields changed — `ai_context`-only updates may report a
lower N than the actual number of columns touched. Permission requirement is the
same as any Model TML write: MODIFY or FULL.

This unblocks Step 9a (Model TML import for surfaces 1, 2, 6) — all three are
now fully automatable.

---

## #4 — Data Model Instructions TML field location — OPEN — DEFERRED TO v1.1

Documented as a feature ([Data Model Instructions](https://docs.thoughtspot.com/cloud/latest/data-model-instructions))
with examples like *"When I ask for last month, use 'last 30 days' as a filter"* but the
TML storage location is **not in the published TML schema or this project's
[thoughtspot-model-tml.md](~/.claude/shared/schemas/thoughtspot-model-tml.md)**.

API probing (against champ-staging 2026-04-25) returned 500 on:
- `/api/rest/2.0/sage/instructions`
- `/api/rest/2.0/spotter/instructions`
- `/api/rest/2.0/metadata/sage/instructions`
- `/api/rest/2.0/metadata/instructions`
- `/api/rest/2.0/metadata/{guid}/instructions`

(500 = backend reached but errored, vs 404 = no route. Suggests routes exist but our
payload/method is wrong.)

**v1 behaviour (current):** generate proposed instructions as plain markdown in
`{run_dir}/instructions.md`; the user copy-pastes them into the Spotter UI under
*Settings → Coach Spotter → Instructions*. No TML import.

**v1.1 work needed:**
1. Find the TML field by:
   - Setting an instruction via the UI on a test Model and exporting TML before/after
     to diff
   - Asking ThoughtSpot engineering for the field path
   - Inspecting the v2 OpenAPI doc once accessible
2. Add the field to `thoughtspot-model-tml.md` schema
3. Update Step 8b to write the proposed instructions into the Model TML
4. Update Step 9a to confirm round-trip on re-export

**Acceptance for v1.1:** instructions imported via TML, round-trip preserves them.

---

## #5 — Snowflake `ACCOUNT_USAGE.QUERY_HISTORY` access on the user's role — VERIFIED on champ-staging

Confirmed (2026-04-25) that the `ThoughtSpot Partner (AP)` Snowflake profile
(`thoughtspot_partner.ap-southeast-2`, role `SE_ROLE`) can query
`SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` and that `QUERY_PARAMETERIZED_HASH` works for
grouping queries by structure.

**Real-world finding for ThoughtSpot-fronted Snowflake:** demo / staging accounts often
have **zero analytical user queries** — the entire workload is ThoughtSpot's own
SAGE_INDEXING and SAGE_SAMPLING tasks, plus viz queries. Mining yields no useful
patterns. The skill must degrade gracefully (already handled in Step 3b error logging).

**For production accounts:** mining is still expected to be valuable when there is
mixed workload (DBT models, analyst notebooks, BI tools other than ThoughtSpot).
Don't remove the feature — just document that emptiness on demos is normal.

---

## #6 — `search_tokens` dry-run validation via `/searchdata` — OPEN — Optional

Step 7 may sample-validate 3 tokenised search strings before import. The CLI does not
yet expose `searchdata`. Direct REST call as test scaffolding documented here.

**Test:**

```python
import urllib.request, os, json
req = urllib.request.Request(
    f"{base_url}/api/rest/2.0/searchdata",
    method="POST",
    headers={"Authorization": f"Bearer {token}", "X-Requested-By": "ThoughtSpot",
             "Content-Type": "application/json"},
    data=json.dumps({
        "logical_table_identifier": model_guid,
        "query_string":             "[Customer Name] [Revenue] top 10",
        "data_format":              "COMPACT",
        "record_size":              5,
    }).encode(),
)
```

**To record:**
- Does `searchdata` accept `logical_table_identifier` for a Model GUID on Cloud?
- Response shape on a parse error (need a clean error code to flag bad tokens)
- Throughput: can we sample 10 mappings without throttling?

Non-blocking. Step 7 currently relies on the user's eyeball review.

---

## #7 — Coaching index refresh latency — OPEN

After importing `nls_feedback`, how long until Spotter's coaching index incorporates
the new entries and the smoke test is meaningful?

**Test:**
1. Import 3 reference questions
2. Immediately query Spotter UI with one of the verified phrases
3. Then query again at +5min, +30min, +60min — record when the answer first matches
   the coached `search_tokens`

**To record:**
- Coaching index refresh interval (config? always async? immediate?)
- Whether re-indexing requires a Model touch or happens automatically on
  `nls_feedback` import

Affects user expectations in Step 9d ("Spotter will use these on the next index
refresh"). Document the actual cadence rather than a generic statement.

---

## #8 — Volume calibration for ThoughtSpot Spotter (vs Snowflake "10–20") — OPEN — v2

The "10–20 verified queries" anchor is from
[Snowflake's Cortex Analyst best practices](https://www.snowflake.com/en/developers/guides/best-practices-semantic-views-cortex-analyst/).
Validate whether this number is right for ThoughtSpot Spotter — its coaching index
is keyword/similarity-based (not LLM-backed), so the inflection point may differ.

**Test (manual, not automated):**
1. Pick a Model with measurable Spotter accuracy (baseline pass rate on a held-out
   question set)
2. Run `ts-coach-model` with target = 10, 15, 25, 40
3. Plot accuracy vs entry count
4. Identify the diminishing-returns inflection

Non-blocking for v1 — defaults to 15 with user-adjustable target. Calibration is a
v2 enhancement.

---

## #12 — `BUSINESS_TERM` semantics and required fields — VERIFIED — 2026-04-26

**BUSINESS_TERM entries reference existing Model artifacts only — they cannot define
new formulas inline.** Verified on champ-staging 2026-04-26.

### Verified working shape

```yaml
- id: "1"
  type: BUSINESS_TERM
  access: GLOBAL
  feedback_phrase: "current stock level"
  parent_question: "current stock level"
  search_tokens: "[Inventory Balance]"   # references an EXISTING Model formula
  rating: UPVOTE
  display_mode: UNDEFINED                 # REQUIRED
  chart_type: KPI                         # REQUIRED — even for BTs
```

The `search_tokens` value must reference a column or formula that already exists
on the Model (verified with both a physical column `[Customer Name]` and a Model
formula `[Inventory Balance]` — both imported successfully).

### What does NOT work

- `formula_info` on a BUSINESS_TERM with a NEW formula expression. Every variant
  tested fails with `EDOC_FEEDBACK_TML_INVALID` and "Search did not find <expression>
  in your data or metadata". The API parses the expression as a search-bar query
  looking for an existing artifact, not as a formula definition. Verified attempts:
  - `[Amount] - group_aggregate(...)` (YoY pattern)
  - `[Inventory Balance] / group_aggregate(sum, [col], {})`
  - Same with `query_groups()` and `query_filters()` (per [formula-patterns.md:268,274,286](~/.claude/shared/schemas/thoughtspot-formula-patterns.md))

- Omitting `chart_type` — even though the schema doc implies it's optional for
  BUSINESS_TERMs, the API rejects with "Invalid chart_type field"

### Implications for the skill

**The earlier design of Method B (Business Term + formula) was wrong.** A BUSINESS_TERM
cannot ship a calculation alongside the phrase mapping. The correct pattern when a
phrase needs a calculation:

1. First, add the formula as a **Model formula** (via `/ts-object-answer-promote`
   or by editing the Model TML directly)
2. Then, create the BUSINESS_TERM with `search_tokens` referencing the new formula by name
3. The skill should detect when this two-step workflow is needed and surface it
   to the user, not attempt to inline the formula

**Updated Method labels for [synonym-strategy-explainer.md](synonym-strategy-explainer.md):**

| Method | Targets | Effort |
|---|---|---|
| A — Synonym | Existing Model COLUMN | Single TML import |
| B — Business Term | Existing Model COLUMN or FORMULA | Single TML import (NO formula creation) |
| C — Reference Question | Whole-question phrasing → search_tokens | Single TML import (formula_info CAN create answer-level formulas, but those are scoped to the answer, not the Model) |

**Key insight:** Methods A and B substantially overlap when the target is a column.
The remaining BT-only territory is **phrase → existing Model formula**. Examples:
- For Dunder Mifflin: `"stock"` could be a Synonym OR a BT pointing at `[Inventory Balance]`
  (which is a Model formula, not a column — so Synonyms can't reach it)
- Therefore: **for phrases targeting Model formulas (not columns), use Method B**;
  for phrases targeting columns, prefer Method A

### Action for SKILL.md (next iteration)

1. Step 6.4 (Method B generation): only emit BTs where the target exists on the Model
   already. Drop any phrase that requires a new formula
2. Step 7 review files: when a phrase needs a new calculation, surface a
   `MOVE_TO_NEW_FORMULA` action rather than `KEEP` as Method B
3. SKILL.md Step 9b: ensure `chart_type` and `display_mode` are always set on BT entries
4. Update [token-mapping-rules.md §4](token-mapping-rules.md) Method B description
   accordingly — remove the "ship calculation with the entry" framing

---

## #11 — Valid `chart_type` values for `nls_feedback` REFERENCE_QUESTION — VERIFIED — 2026-04-26

Probed on champ-staging. The valid set is more restrictive than
[~/.claude/shared/schemas/thoughtspot-feedback-tml.md](~/.claude/shared/schemas/thoughtspot-feedback-tml.md)
suggests:

| chart_type value | Accepted? |
|---|---|
| `KPI` | ✅ |
| `COLUMN` | ✅ |
| `BAR` | ✅ |
| `LINE` | ✅ |
| `PIE` | ✅ |
| `STACKED_COLUMN` | ✅ |
| `AREA` | ✅ |
| `SCATTER` | ✅ |
| `TREEMAP` | ✅ |
| `HEATMAP` | ✅ |
| `WATERFALL` | ✅ |
| **`TABLE`** | **❌ REJECTED** with `EDOC_FEEDBACK_TML_INVALID` "Invalid chart_type field" |
| `TABLE_MODE` | ❌ REJECTED (that's a `display_mode` value, not a `chart_type`) |
| Lowercase variants (`table`, `column`) | ❌ REJECTED — must be UPPERCASE |

**Implication for the skill:** for entries that should display as a table by default,
use `chart_type: COLUMN` + `display_mode: TABLE_MODE`. Don't ever set
`chart_type: TABLE`. KPI is fine for any single-value entry (the user-facing rendering
prefers a date filter for the comparison delta, but the import itself is permissive).

**Update needed:** [~/.claude/shared/schemas/thoughtspot-feedback-tml.md](~/.claude/shared/schemas/thoughtspot-feedback-tml.md)
line 76 (`chart_type` row in the field reference) should drop `TABLE` from its example
list and add the verified set above.

This finding is moot until Open Item #2 is resolved (currently the import doesn't
write entries at all, so chart_type validation runs but has no effect). When #2 is
resolved, the chart_type whitelist above must be enforced.

---

## #9 — Whether column `synonyms` and `BUSINESS_TERM` produce identical Spotter behaviour — OPEN

Both can map a phrase to a column. Are they functionally equivalent at query time, or
do they have measurable behaviour differences?

**Test:**
1. Create a Model with column `Inventory Balance`
2. Add `synonyms: ["stock"]` to that column (Surface 2)
3. Type "stock by product" in Spotter — confirm it parses as `[Inventory Balance] [Product Name]`
4. Remove the synonym; instead add a `BUSINESS_TERM` coaching entry: `feedback_phrase: "stock"`, `search_tokens: "[Inventory Balance]"`
5. Repeat the same query — is the parse identical? Is the coverage identical for related
   queries like "stock for printer paper", "top 10 stock"?

**To record:**
- Are the two mechanisms equivalent in actual Spotter parsing?
- Are there query shapes that one catches but the other doesn't?
- Latency: does one resolve faster than the other?

This determines whether the
[synonym-strategy-explainer.md](synonym-strategy-explainer.md) recommendations are
correct in practice. The current explainer is theoretical — verifying #9 lets us
update it with empirical guidance.

---

## #13 — Verified TS period-over-period growth-% formula — OPEN

**Symptom that prompted this entry.** The `t4.yoy` and `t4.mom` rows in the original
question-taxonomy + token-mapping-rules used a formula template:

```
( [M] - group_aggregate ( sum , [M] , { [T] - 1 } ) ) / group_aggregate ( sum , [M] , { [T] - 1 } )
```

The `[T] - 1` operator on a date column inside a `group_aggregate` grouping argument is
**not valid TS formula syntax** — the third argument of `group_aggregate` is a
`query_filters()` expression, not a date offset. There is no documented way to express
"prior-period value of M for the same scope" in
[thoughtspot-formula-patterns.md](~/.claude/shared/schemas/thoughtspot-formula-patterns.md).
Caught in conversation 2026-04-27 while running the skill against the Dunder Mifflin
Sales & Inventory Model — the user (a TS employee) flagged it before any TML import.

### Interim fix (already applied)

The taxonomy now emits keyword-based comparisons instead — `t4.yoy_compare` and
`t4.mom_compare` produce two side-by-side KPIs (`[M] this year [M] last year` /
`[M] this month [M] last month`) and require no formula. This mirrors the existing
`t2.this_vs_last` pattern.

### Test (when re-investigating)

Investigate three candidate approaches against a live instance:

1. **`growth_of` keyword** — Spotter's search bar accepts phrasings like
   `revenue growth of order date last year`. Check whether the same keyword produces a
   valid `search_tokens` entry that imports cleanly into `nls_feedback`.

2. **`safe_divide` + `sum_if(year_diff([T], today()) = 1, [M])`** — express the
   prior-period value via `sum_if` against a date-diff predicate. Verify both
   syntax acceptance and result correctness against a known dataset.

3. **Date-shifted column synonym** — define a Model formula like
   `Prior Year [M]: sum_if ( year ( [T] ) = year ( today() ) - 1 , [M] )`, then write
   a normal `( [M] - [Prior Year M] ) / [Prior Year M]` answer formula. The work
   shifts from the answer formula to the Model — acceptable if the Model is being
   coached anyway.

Record findings here. If approach 1 works, the keyword-based comparison can be
upgraded from "two KPIs" to "true growth %" without re-introducing a formula.

### Action when verified

Restore `t4.yoy` / `t4.mom` patterns in
[question-taxonomy.md](question-taxonomy.md) and
[token-mapping-rules.md](token-mapping-rules.md) with the verified formula or
keyword string. Until then, `t4.yoy_compare` / `t4.mom_compare` (no formula) is the
only safe pattern.

---

## #14 — `ai_context` character limit — VERIFIED — 2026-04-27

**The limit is 400 characters per column.** Verified on champ-staging during
end-to-end run on TEST_SV_Dunder Mifflin Sales & Inventory. The API returns:

```
status_code: ERROR
OBJECT_INVALID_STATE: AI column context exceeds maximum length of 400 characters
for column: <comma-separated list of over-length columns>
```

The error names every offending column on a single import attempt — no
truncation, the import fails ALL-OR-NONE.

### Implication for the structured-YAML AI Context schema

The full 8-axis schema (meaning + unit + includes + excludes + source +
time_basis + null_zero + watch_out + formula) easily runs 600–1200 chars.
**400 chars forces a terse single-line-per-axis format.** Pattern that fits:

```yaml
meaning: <one line, ≤ 80 chars>
unit:    <one line, ≤ 30 chars>
source:  <table.column, ≤ 60 chars>
time:    <one line, ≤ 50 chars (when relevant)>
nulls:   <one line, ≤ 40 chars (when relevant)>
watch:   <one line, ≤ 80 chars>
formula: <one line for formula columns>
```

Verified working on all 20 columns of the Dunder Mifflin Model, with lengths
ranging 148–313 chars (all under the 400 limit).

### Where the verbose prose lives instead

`column.description` (separate field) — confirmed during the same end-to-end
run to accept the longer prose-style descriptions (lengths 200-400 chars
tested without rejection). Verified upper bound of `column.description` is
NOT yet tested; if it has its own limit it has not been hit in practice.

### Action taken

- Generators must cap `properties.ai_context` at 400 chars and validate
  before import
- If the structured-YAML schema cannot fit, drop axes in this priority
  order: `excludes` → `includes` → `null_zero` → `time_basis` → `unit`
  (preserve `meaning` + `source` + `watch` as last to drop)
- Detailed prose belongs in `column.description`, not duplicated in
  `ai_context`

---

## #15 — Cross-Model consistency heuristic calibration — OPEN

The Step 4.5 cross-Model consistency scan
([cross-model-consistency.md](cross-model-consistency.md)) uses heuristics
to propose a default RouteAction (`RENAME` / `ALIGN` / `DOCUMENT_DIFFERENCE` /
etc.) for each detected collision. The heuristics have NOT been calibrated
against a live tenant — until calibration, the skill defaults every
collision to `NEEDS_REVIEW` rather than the heuristic's pick.

### Test (run against champ-staging or se-thoughtspot)

1. Run `ts-coach-model` Step 4.5 against a Model with ≥ 5 known
   cross-Model collisions
2. For each collision, record:
   - Heuristic-proposed RouteAction
   - Domain-expert-correct RouteAction (from the user)
   - Whether the heuristic was right, wrong, or close
3. Aggregate to a calibration scorecard: `correct / wrong / close × 100`

### Pass criteria

- ≥ 70% correct OR ≥ 90% (correct + close) for the heuristic to become the
  default proposal
- Below that — keep `NEEDS_REVIEW` as the default; the heuristic appears
  in the "Suggested" column only as a hint

### Specific signals to tune

- The "canonical Model" heuristic for `ALIGN` proposals (creation_time vs
  modified_time vs ai_context-completeness)
- The substring-conflict heuristic for `ai_context` divergence (how
  aggressive should it be? false-positive rate currently unknown)
- `db_column_name` exact-match — confirm this is the right granularity (vs
  matching at table-level)

---

## #16 — Search-bar keyword vocabulary in `nls_feedback.search_tokens` — VERIFIED REJECTED — 2026-04-27

**The keyword vocabulary documented in
[token-mapping-rules.md](token-mapping-rules.md) §1 is aspirational, not
verified.** Every non-bracket token tested in `search_tokens` is rejected by
the feedback parser with `EDOC_FEEDBACK_TML_INVALID — Invalid value token: <kw>`.

### Tested on champ-staging 2026-04-27 (end-to-end run)

| Token (in `search_tokens`) | Documented in token-mapping-rules.md | Verified outcome |
|---|---|---|
| `monthly` | ✓ Time grain | ❌ Invalid value token: monthly |
| `last 30 days` | ✓ Relative time | ❌ Invalid value token: last |
| `this quarter` | ✓ Relative time | ❌ Invalid value token: this |
| `last quarter` | ✓ Relative time | ❌ Invalid value token: last |
| `top 10` | ✓ Top/Bottom N | ❌ Invalid value token: top |
| `= 2025` | ✓ Filter | ❌ Invalid value token (parser doesn't accept literal filter) |
| `[Column]` (bracketed display name) | ✓ Column ref | ✅ Accepted |

The verified-safe shape is **bracketed column references only** (with no
keywords / operators / filters). Spaces between tokens are accepted.

### Implication for question generation

The Tier 1 / Tier 2 / Tier 3 patterns in
[question-taxonomy.md](question-taxonomy.md) lose meaningful semantics when
keywords are stripped:

| Pattern | search_tokens after stripping | Spotter behavior |
|---|---|---|
| `t1.top_n` | `[Customer Name] [Amount]` | Same as `t1.by_dim` (no top-N anchor) |
| `t2.by_time` | `[Order Date] [Amount]` | Loses month-grain hint |
| `t2.recent_period` | `[Amount]` | Loses date filter — collapses to `t1.total` |
| `t2.this_vs_last` | `[Amount] [Amount]` | Nonsense |
| `t3.year_filter` | `[Order Date] [Amount]` | Loses year filter |

This means **`t1.top_n`, `t2.recent_period`, `t2.this_vs_last`, `t3.year_filter`
are not currently importable as distinct Reference Questions** — their tokens
collapse to redundant or nonsensical column-only forms. Only `t1.total`,
`t1.by_dim`, `t1.distinct_count`, `t2.by_time` (semi), `t2.trend_by_dim` (semi),
and `t3.dim_filter` (when value-free) work cleanly.

### Test (when re-investigating)

The TS search bar accepts these keywords on its UI input. The disconnect is
in the `nls_feedback` import parser, not the search bar itself. Likely
candidates to test:

1. **Quoted keywords**: `"monthly"`, `'top 10'` — does quoting bypass validation?
2. **Different token positions**: e.g. `[Order Date].monthly [Amount]` —
   does keyword-after-dot syntax work as a column-modifier?
3. **Wildcards**: `[Order Date]:month [Amount]`
4. **Date-bucket function calls**: `month([Order Date]) [Amount]`

Until verified, the skill should strip keywords before building feedback TML
and warn the user that question semantics are degraded.

### Action taken

- Generator strips non-bracket tokens before TML build (verified working
  during the end-to-end run)
- `t1.top_n`, `t2.recent_period`, `t2.this_vs_last`, `t3.year_filter`,
  and `t3.dim_filter` (with values) marked as DEFERRED until verification
- The keyword vocabulary table in
  [token-mapping-rules.md](token-mapping-rules.md) §1 should be revised
  to mark every non-`[Col]` row as UNVERIFIED

---

## #17 — `formula_info` on `REFERENCE_QUESTION` rejected by parser — VERIFIED REJECTED — 2026-04-27

**The same parser bug documented in [#12](#12) for BUSINESS_TERM also affects
REFERENCE_QUESTION when `formula_info[]` is present.** The parser tries to
treat `formula_info[].expression` as a search query rather than a formula,
fails, and rejects the entire entry with:

```
status_code: ERROR
EDOC_FEEDBACK_TML_INVALID: Search did not find "<expression suffix>" in your data
or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc.
```

Verified on champ-staging 2026-04-27 with two formula-bearing Reference
Questions:

| Question | Formula expression | Outcome |
|---|---|---|
| Cumulative Amount by month | `cumulative_sum ( [Amount] , [Order Date] )` | ❌ Rejected |
| Product Category share of total Amount | `[Amount] / group_aggregate ( sum , [Amount] , { } )` | ❌ Rejected |

This contradicts the documented examples in
[token-mapping-rules.md](token-mapping-rules.md) §2 and §6.

### Implication for the question taxonomy

Every formula-bearing tier becomes **non-importable in this skill's current
single-step path**:

- `t2.cumulative` — needs `cumulative_sum`
- `t3.avg_per` — needs `[M] / unique count([D])`
- `t3.ratio` — needs `( [M1] - [M2] ) / [M1]`
- `t3.share_of_total` — needs `[M] / group_aggregate(sum, [M], {})`
- `t4.window_rank` — needs `rank([M], {[D2]})`
- `t4.conditional_agg` — needs `sum_if(...)`
- `t4.cross_join_metric` — needs `[M1] / [M2]`

### Workaround

Define the formula as a Model formula FIRST (via `/ts-object-answer-promote` or
manual TML edit), then reference it by display name in `search_tokens`:

```yaml
# 1. Add formula to Model:
#    [Cumulative Amount] = cumulative_sum( [Amount] , [Order Date] )
# 2. Then create the Reference Question without formula_info:
search_tokens: "[Order Date] [Cumulative Amount]"
# (no formula_info field)
```

This is the same constraint already documented for BUSINESS_TERM in
[#12](#12). The skill should treat both surfaces consistently.

### Test (when re-investigating)

Try the YAML folded-block-scalar (`>-`) form documented in token-mapping-rules.md
§2 (required for `{ }` curly-brace expressions). Try without quoting. Try the
`expr` field name vs `expression`. Verify on Cloud vs on-prem (parser may
differ between deployment types).

### Action taken

- Generator drops formula-bearing questions before feedback TML build
- The skill emits a `MOVE_TO_NEW_FORMULA` proposal for those questions
  (same as the existing BUSINESS_TERM workflow per #12), routing the user
  to define the formula on the Model first, then re-run

---

## #18 — Feedback TML import REPLACES rather than MERGES — VERIFIED — 2026-04-27

**Importing an `nls_feedback` TML payload silently REPLACES every existing
feedback entry on the Model.** The SKILL.md Step 8c statement *"Merge new
entries with existing ones; never blow them away"* is **incorrect** for the
verified API behavior.

Verified on champ-staging 2026-04-27 during the end-to-end run on
TEST_SV_Dunder Mifflin Sales & Inventory:

- Before import: 5 `SMOKE_TEST_PROBE_*` entries on the Model (residue from
  prior smoke runs)
- Import payload: 40 new entries (new IDs, no overlap with existing IDs)
- After import: 40 entries total — the 5 SMOKE_TEST_PROBE entries are **gone**

The `--policy ALL_OR_NONE --no-create-new` flags don't change this — the
import wholesale replaces the Model's `nls_feedback.feedback[]` collection
with whatever the payload contains.

### Why this is a SAFETY ISSUE

A second run of `ts-coach-model` on the same Model would silently destroy
every feedback entry created since the prior run — including entries added
manually via the UI. This contradicts the skill's stated invariant ("existing
values are never silently overwritten").

### Compounded by #2 sub (content retrieval)

The skill cannot **preserve** existing entries by re-fetching them and
including them in the merged payload, because per
[#2 sub-item](#2-feedback-content-retrieval), the full content
(`search_tokens`, `formula_info`, `chart_type`, `display_mode`, `access`) of
existing feedback is NOT retrievable via any verified API. Only the headers
(id, name, type, author, modified) come back.

This means: **without a fix, every run of `ts-coach-model` destroys any
manually-added or previously-coached feedback entries.**

### Mitigations to add before this is safe to ship

1. **Pre-import warning gate** — enumerate existing feedback headers before
   import; if any non-skill-managed entries exist, force the user to either:
   a) export/document them manually first, or b) explicitly acknowledge they
   will be lost
2. **Per-author guard** — if any existing entry has an author other than the
   current run's author, abort with explicit confirmation required
3. **Track skill-managed entries** — write a tag or convention into
   `feedback_phrase` (e.g. `[ts-coach-model:run_id]`) so subsequent runs can
   distinguish skill-added from human-added entries

### Action taken

- This is now a **MERGE BLOCKER** for `wip/ts-coach-model` → `main` until
  one of the mitigations above is implemented
- SKILL.md Step 8c language ("merge with existing; never blow them away")
  must be corrected to reflect verified replace-behavior
- The user-facing Step 8e import gate must surface the loss explicitly

### Test (to confirm fix lands)

After mitigation:
1. Add a manual feedback entry via the Spotter UI to the test Model
2. Run `ts-coach-model` end-to-end with one new Reference Question
3. Verify the manual entry is still present after import
4. Verify the new entry is also present

---

## Verification matrix

| Item | Required for merge to main | Required for v2 | Owner |
|---|---|---|---|
| #1 dependent search via v2 API | Yes — VERIFIED | — | Damian |
| #2 standalone nls_feedback import | **Yes — BLOCKING (VERIFIED)** | — | Damian |
| #2 sub: feedback content retrieval | No — header-only fallback in v1 | Yes — restores GLOBAL/USER split + variant generation | Damian |
| #3 ai_context / synonyms round-trip on Model TML | **Yes — BLOCKING (VERIFIED)** | — | Damian |
| #4 Data Model Instructions TML location | No (deferred to v1.1; markdown draft only) | Yes | Damian |
| #5 ACCOUNT_USAGE access | Yes — VERIFIED | — | — |
| #6 searchdata dry-run | No | Yes (promote to `ts searchdata` command) | Damian |
| #7 coaching index refresh latency | No (informational) | Yes (sets expectations) | Damian |
| #8 volume calibration | No | Yes (drives default target) | Damian |
| #9 synonyms vs BUSINESS_TERM equivalence | No (theory holds for v1) | Yes (refines explainer) | Damian |
| #13 verified period-over-period growth-% formula | No (keyword fallback in place) | Yes (re-enables true t4.yoy / t4.mom) | Damian |
| #14 ai_context character limit (400 chars) | Yes — VERIFIED — generators must cap at 400 | — | Damian |
| #15 cross-Model consistency heuristic calibration | No (defaults to NEEDS_REVIEW) | Yes (heuristic-driven defaults reduce review load) | Damian |
| #16 search-bar keyword vocabulary in feedback parser | Yes — VERIFIED REJECTED — generator strips keywords; affected tiers DEFERRED | Yes — re-enable t1.top_n / t2.recent_period / t2.this_vs_last / t3.year_filter when verified | Damian |
| #17 formula_info on REFERENCE_QUESTION rejected | Yes — VERIFIED REJECTED — formula-bearing tiers DEFERRED in v1 (use Model-formula workaround) | Yes — re-enable t2.cumulative / t3.avg_per / t3.ratio / t3.share_of_total / t4.* when verified | Damian |
| #18 feedback TML import REPLACES, doesn't merge | **Yes — BLOCKING** — destroys existing feedback; mitigation required before merge | — | Damian |

**Merge blockers:** #2, #3, and **#18 (newly verified)**. #18 is the only
genuinely unsafe item — without mitigation, every run of the skill destroys
any feedback added since the previous run.

The #2 sub-item (feedback content retrieval) is **NOT a merge blocker** — the v1
skill operates header-only and degrades gracefully. It becomes blocking for v2 when
GLOBAL/USER differentiation and paraphrase variant reuse are promoted from "nice to
have" to "core". Cross-track with
[ts-dependency-manager open-item #18](~/.claude/skills/ts-dependency-manager/references/open-items.md).
