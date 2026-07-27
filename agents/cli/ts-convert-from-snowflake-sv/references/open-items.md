# Open Items: ts-convert-from-snowflake-sv

For a full mapping of what IS supported, see [coverage-matrix.md](coverage-matrix.md).

---

## #2 — Custom instructions mapping — PARTIALLY IMPLEMENTED (LOW)

Snowflake SVs support `ai_sql_generation` / `ai_question_categorization` free-text
instruction strings (`CUSTOM_INSTRUCTIONS` module) that guide Cortex Analyst behaviour.

ThoughtSpot equivalent: `data_model_instructions` on the Model TML (guides Spotter).

**Done (SKILL v1.16.0 + Step 4x):** the skill now parses `ai_sql_generation` /
`ai_question_categorization` from the DDL and surfaces the free text as candidate
Data Model Instructions content in the conversion report and at the review
checkpoint. See coverage-matrix.md L1.

**Still open:** this is a reporting/handoff step, not a structural TML mapping — the
exact ThoughtSpot TML field for Data Model Instructions is still TBD (see
`ts-object-model-coach` references/open-items.md #4). Until that field is confirmed,
the surfaced text is not written into the Model TML directly.

**Workaround:** run `/ts-object-model-coach` after conversion to place the surfaced
text (or generate independent Spotter instructions from the model's column structure
if the SV had none).

Status: PARTIALLY IMPLEMENTED — parse+surface done; structural TML field placement
still open, LOW priority (post-conversion coaching covers the gap in the meantime)

---

## #3 — Table-level synonyms — NOT IMPLEMENTED (LOW)

SVs support `with synonyms=(...)` on table entries in the `tables()` block (e.g.
`ORDERS with synonyms=('sales orders')`). ThoughtSpot models have no table-level
synonym concept.

**Workaround:** add table synonyms to `model.description` or `data_model_instructions`
so Spotter has the context.

Status: NOT IMPLEMENTED — LOW priority (no ThoughtSpot equivalent)

---

## #4 — Private facts and metrics (`ACCESS_MODIFIER: PRIVATE`) — NOT IMPLEMENTED (LOW)

SVs support marking facts and metrics as private — helper columns not exposed to
end users. ThoughtSpot has no "private" column concept in models.

**Workaround:** omit private facts/metrics from the model entirely, or include them
with `index_type: DONT_INDEX` so Spotter ignores them.

Status: NOT IMPLEMENTED — LOW priority (rare in practice)

---

## #5 — `unique_keys` declarations — NOT IMPLEMENTED (LOW)

SVs support `unique_keys` declarations on table entries beyond primary key.
ThoughtSpot does not use key declarations in models.

**Workaround:** none needed — ThoughtSpot does not consume key metadata. The skill
already parses `primary key` for join target identification; `unique_keys` would add
no value to the converted model.

Status: NOT IMPLEMENTED — LOW priority (no ThoughtSpot equivalent)
