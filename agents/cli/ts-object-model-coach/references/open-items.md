# Open Items — ts-coach-model

Items that need verification against a live ThoughtSpot (or Snowflake) instance before
the skill is considered fully verified. Update each item with findings after testing.

Status legend: **CONFIRMED** (direction known, needs live verification) | **VERIFIED** (tested) | **OPEN** (unknown)

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

**v1 behaviour (current):** Step 6.5 generates the **structured 5-category form**
defined in [model-instructions-schema.md](model-instructions-schema.md) to
`{run_dir}/model_instructions.yaml`, AND a prose `{run_dir}/instructions.md` for
copy-paste into *Settings → Coach Spotter → Instructions*. No TML import yet.

**v1.1 work needed:**
1. Find the TML field by:
   - Setting an instruction via the UI on a test Model and exporting TML before/after
     to diff
   - Asking ThoughtSpot engineering for the field path
   - Inspecting the v2 OpenAPI doc once accessible
2. Add the field to `thoughtspot-model-tml.md` schema
3. Update Step 8b to write `model_instructions.yaml` content into the Model TML
4. Update Step 9a to confirm round-trip on re-export

**Acceptance for v1.1:** instructions imported via TML, round-trip preserves them.

---

## #6 — `search_tokens` dry-run validation via `/searchdata` — OPEN — Optional

Step 7 may sample-validate 3 tokenised search strings before import. The CLI does not
yet expose `searchdata`. Direct REST call as test scaffolding documented here.

**To record:**
- Does `searchdata` accept `logical_table_identifier` for a Model GUID on Cloud?
- Response shape on a parse error (need a clean error code to flag bad tokens)
- Throughput: can we sample 10 mappings without throttling?

Non-blocking. Step 7 currently relies on the user's eyeball review.

---

## #7 — Coaching index refresh latency — OPEN

After importing `nls_feedback`, how long until Spotter's coaching index incorporates
the new entries and the smoke test is meaningful?

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

Non-blocking for v1 — defaults to 15 with user-adjustable target. Calibration is a
v2 enhancement.

---

## #9 — Whether column `synonyms` and `BUSINESS_TERM` produce identical Spotter behaviour — OPEN

Both can map a phrase to a column. Are they functionally equivalent at query time, or
do they have measurable behaviour differences?

This determines whether the
[synonym-strategy-explainer.md](synonym-strategy-explainer.md) recommendations are
correct in practice. The current explainer is theoretical — verifying #9 lets us
update it with empirical guidance.

---

## #13 — Verified TS period-over-period growth-% formula — OPEN

The `t4.yoy` and `t4.mom` rows in the original question-taxonomy + token-mapping-rules
used a formula template with `[T] - 1` inside `group_aggregate`, which is **not valid
TS formula syntax**. Caught in conversation 2026-04-27 — the user flagged it before
any TML import.

**Interim fix (already applied):** taxonomy emits keyword-based comparisons instead —
`t4.yoy_compare` and `t4.mom_compare` produce two side-by-side KPIs requiring no formula.

**Test (when re-investigating):** Investigate `growth_of` keyword, `sum_if` with
date-diff predicates, and date-shifted column synonyms as candidate approaches.

---

## #15 — Cross-Model consistency heuristic calibration — OPEN

The Step 4.5 cross-Model consistency scan uses heuristics to propose a default
RouteAction for each detected collision. The heuristics have NOT been calibrated
against a live tenant — until calibration, the skill defaults every collision to
`NEEDS_REVIEW` rather than the heuristic's pick.

**Pass criteria:** ≥ 70% correct OR ≥ 90% (correct + close) for the heuristic to
become the default proposal.
