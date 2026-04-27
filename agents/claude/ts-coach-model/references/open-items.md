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

**Merge blockers:** #2 and #3. Both are short tests against champ-staging on the
Dunder Mifflin Model.

The #2 sub-item (feedback content retrieval) is **NOT a merge blocker** — the v1
skill operates header-only and degrades gracefully. It becomes blocking for v2 when
GLOBAL/USER differentiation and paraphrase variant reuse are promoted from "nice to
have" to "core". Cross-track with
[ts-dependency-manager open-item #18](~/.claude/skills/ts-dependency-manager/references/open-items.md).
