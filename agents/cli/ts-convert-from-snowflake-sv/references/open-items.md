# Open Items: ts-convert-from-snowflake-sv

For a full mapping of what IS supported, see [coverage-matrix.md](coverage-matrix.md).

---

## #2 — Custom instructions mapping — NOT IMPLEMENTED (LOW)

Snowflake SVs support `CUSTOM_INSTRUCTIONS` with `AI_QUESTION_CATEGORIZATION` and
`AI_SQL_GENERATION` properties that guide Cortex Analyst behaviour.

ThoughtSpot equivalent: `data_model_instructions` on the Model TML (guides Spotter).

The skill does not parse or map custom instructions. They are not surfaced in the
conversion report or at the review checkpoint.

**Workaround:** run `/ts-object-model-coach` after conversion to create Spotter
instructions. The coach skill's Step 6.5 generates `data_model_instructions` from
the model's column structure — independent of SV custom instructions.

Status: NOT IMPLEMENTED — LOW priority (post-conversion coaching covers the gap)

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
