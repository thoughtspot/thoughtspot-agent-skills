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

### Feedback content retrieval — VERIFIED RETRIEVABLE — 2026-04-27

**Resolved.** The correct call is the standard
`POST /api/rest/2.0/metadata/tml/export` endpoint with the **parent object**
GUID and `metadata[].type: FEEDBACK` — *not* the feedback entry's GUID.
Confirmed in the [SpotterCode REST API spec](https://developers.thoughtspot.com/docs/tml#_export_a_tml)
and live-verified 2026-04-27 against champ-staging on the Dunder Mifflin
Sales Worksheet (`0e4406c7-d978-4be7-abd7-c34e8f7da835`):

```http
POST /api/rest/2.0/metadata/tml/export
{
  "metadata": [{"identifier": "<parent_object_guid>", "type": "FEEDBACK"}],
  "edoc_format": "YAML"
}
```

Response: an array of one object with `edoc` (the full feedback YAML — with
`search_tokens`, `axis_config`, `chart_type`, `display_mode`, `parent_question`,
`access`, `rating`, etc.) and `info` (status / name / type).

There's also a Path 2 (Model + feedback in one call) using
`export_options.export_with_associated_feedbacks: true` — see
[feedback-tml-verified-patterns.md](feedback-tml-verified-patterns.md) for both.

#### Why the v1 probes failed

The v1 attempts (table above, deleted) all used the **feedback entry's
GUID** (the `id` field returned by the dependents API) as the `identifier`.
The correct identifier is the **parent object's GUID**. The TS API treats
feedback as "associated with an object" — the export call retrieves all
feedback for that object, not one entry by entry GUID.

#### Skill behaviour update

- Step 2b: now retrieves full content via `tml/export type=FEEDBACK` instead
  of degrading to header-only mode
- Step 3d input signal: existing `search_tokens` and `access` levels are
  now available — re-enable GLOBAL/USER split, paraphrase variant generation,
  and stale-reference critique
- Step 8c: now CAN preserve existing entries by re-fetching them, then
  including them in the merged payload — solves the #18 destruction problem

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

## #16 — `nls_feedback.search_tokens` keyword syntax — VERIFIED-WORKING FORMS DOCUMENTED — 2026-04-27

**Initial finding (rejection of every non-bracket form) was over-broad.**
Mining the feedback corpus across champ-staging Models surfaced verified-
working syntactic shapes for every "rejected" keyword. The earlier rejections
were caused by **wrong syntax positions / missing quotes**, not by keyword
banning.

See [feedback-tml-verified-patterns.md](feedback-tml-verified-patterns.md) for
the full verified-syntax library. Summary of corrected understanding:

| Original v1 form (REJECTED) | Verified-working form |
|---|---|
| `[Customer Name] [Amount] top 10` | `top 10 [Order Date].monthly` *(top BEFORE the column refs)* |
| `[Order Date] [Amount] monthly` | `[Order Date].monthly` *(dot-suffix, attached to col)* |
| `[Order Date] = 2025 [Amount]` | `[Order Date] = '2025' [Amount]` *(quoted literal value)* |
| `[Amount] this quarter` | `[Order Date] = 'this year' vs [Order Date] = 'last year'` *(period as quoted value of date col, with `vs`)* |
| `[Amount] this quarter [Amount] last quarter` | Same — use `vs` operator inside filter clauses, not bare keywords |
| (no equivalent v1 form) | `sum [Amount]`, `[Amount] sort by [Amount]` *(verified — aggregation prefix + sort keywords)* |
| (no equivalent v1 form) | `[Order Date].'month of year'` *(quoted multi-word date bucket)* |

### Mining corpus

53 entries across 4 source objects on champ-staging:
- `Dunder Mifflin Sales` Worksheet (8 entries — high-quality real-world syntax)
- `TEST_DEPENDENCY_MANAGEMENT` Model (3 entries)
- `Dunder Mifflin Sales & Inventory` Worksheet (2 entries)
- `TEST_SV_Dunder Mifflin Sales & Inventory` (40 entries — our v1 run output;
  bracketed-only)

se-thoughtspot top-200 most-recently-modified Models contained 0 entries —
the SE tenant doesn't have coached models in scope.

### Implication for question generation

The Tier 1 / 2 / 3 patterns are **mostly importable** with corrected syntax:

| Pattern | Status with verified syntax |
|---|---|
| `t1.total` | ✅ `[Amount]` |
| `t1.by_dim` | ✅ `[Customer Name] [Amount]` |
| `t1.top_n` | ✅ `top 10 [Customer Name] [Amount]` *(top first)* |
| `t1.distinct_count` | ⚠ `count [Col]` not yet observed; `unique` may differ |
| `t2.by_time` | ✅ `[Order Date].monthly [Amount]` |
| `t2.recent_period` | ⚠ `[Order Date].'last 30 days'` is plausible — untested |
| `t2.this_vs_last` | ✅ `[Amount] [Order Date] = 'this year' vs [Order Date] = 'last year'` |
| `t2.trend_by_dim` | ✅ `[Order Date].monthly [Product Category] [Amount]` |
| `t3.dim_filter` | ✅ `[Amount] [Category] = 'value'` |
| `t3.year_filter` | ✅ `[Order Date] = '2025' [Amount]` |
| `t3.share_of_total`, `t3.avg_per`, `t3.ratio` | ❌ still need `formula_info` — see [#17](#17) |
| `t4.*` | ❌ all need `formula_info` — see [#17](#17) |

### Action taken

- New reference [feedback-tml-verified-patterns.md](feedback-tml-verified-patterns.md)
  documents every verified-working form
- [token-mapping-rules.md](token-mapping-rules.md) §1 updated to point at
  the verified-patterns reference for syntax authority
- Generator should now use the verified-working syntax, not strip keywords
- Original rejection-summary section (kept below for record):

#### Original v1 attempt (kept for context)

The first end-to-end run on 2026-04-27 emitted these forms — all rejected:

| Token | Why it failed |
|---|---|
| `monthly` after column ref | Should be `[Col].monthly` (dot-suffix, not standalone) |
| `last 30 days` standalone | Should be `[Date Col] = 'last 30 days'` (quoted filter value) — untested but plausible |
| `this quarter` standalone | Should be `[Date Col] = 'this quarter'` (quoted filter value) |
| `top 10` after column refs | Should be `top 10` BEFORE column refs |
| `= 2025` (unquoted) | Quote the literal: `= '2025'` |

The TS search bar accepts these as user input on the UI. The TML import
parser is more strict — quoting and positioning matter. The verified
patterns file is now the authoritative reference for what the parser accepts.

### Action taken (continued)

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

### Mitigation now possible — #2 sub is RESOLVED

[#2 sub](#feedback-content-retrieval--verified-retrievable--2026-04-27) is
now resolved (full feedback content IS retrievable via
`tml/export type=FEEDBACK`). This means the skill **CAN preserve existing
entries** by:

1. Fetching existing feedback content before import
2. Building the merged payload with both existing + new entries
3. Importing the full merged payload (replacing the collection — but the
   collection now contains everything we want to keep)

Pseudocode:

```python
# Step 8c — merged-with-preservation
existing = export_feedback_tml(profile, model_guid)  # FULL content, not headers
existing_entries = existing["nls_feedback"]["feedback"] if existing else []

# Re-id the new entries to avoid collision with existing IDs
used_ids = {str(e.get("id","")) for e in existing_entries}
def next_id():
    n = 1
    while str(n) in used_ids: n += 1
    used_ids.add(str(n)); return str(n)
for e in new_reference_questions + new_business_terms:
    e["id"] = next_id()

merged = existing_entries + new_reference_questions + new_business_terms
feedback_tml = {"guid": model_guid, "nls_feedback": {"feedback": merged}}
# Import — the API "replaces" the collection, but the collection now
# includes the existing entries verbatim, so nothing is lost.
```

This keeps the API's replace-behaviour intact (no API change required) while
delivering the user-facing "never blow them away" invariant.

### Action taken

- **Downgraded from MERGE BLOCKER to documented behaviour** since the
  preservation pattern is now implementable
- SKILL.md Step 8c language updated 2026-04-27 to document the
  fetch-existing-then-merge approach (replacing the prior fictional
  "API merges" claim)
- The user-facing Step 8e import gate still surfaces the replace-behaviour
  explicitly, but with a "✓ existing entries preserved by re-fetch" line
  rather than a destruction warning

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
| #2 sub: feedback content retrieval | Yes — VERIFIED RETRIEVABLE 2026-04-27 (`tml/export type=FEEDBACK`) | — | Damian |
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
| #16 search_tokens keyword syntax | Yes — VERIFIED-WORKING FORMS DOCUMENTED in feedback-tml-verified-patterns.md; generator uses verified forms | Yes — extend coverage as new patterns observed | Damian |
| #17 formula_info on REFERENCE_QUESTION rejected | Yes — VERIFIED REJECTED — formula-bearing tiers use Model-formula workaround in v1 | Yes — re-enable inline formula_info when parser fixed | Damian |
| #18 feedback TML import REPLACES, doesn't merge | Yes — DOCUMENTED + MITIGATION IMPLEMENTABLE (fetch-existing-then-merge via #2 sub resolution) | — | Damian |

**Merge blockers:** #2, #3 — both VERIFIED. No outstanding blockers.

#2 sub (feedback content retrieval) was previously a v2-only requirement and
is now resolved (verified 2026-04-27 — `tml/export type=FEEDBACK` returns
full content). This unlocks the GLOBAL/USER access split, paraphrase-variant
reuse, and the #18 mitigation (fetch-existing-then-merge to preserve user-
authored entries across runs). The cross-tracked
[ts-dependency-manager open-item #18](~/.claude/skills/ts-dependency-manager/references/open-items.md)
benefits from the same finding.
