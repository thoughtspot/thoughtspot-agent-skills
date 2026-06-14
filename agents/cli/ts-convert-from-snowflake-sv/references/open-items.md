# Open Items: ts-convert-from-snowflake-sv

For a full mapping of what IS supported, see [coverage-matrix.md](coverage-matrix.md).

---

## #1 — sql_view generation path for subquery-backed SVs — VERIFIED NOT APPLICABLE

Snowflake's `tables()` block does not support subquery sources — only named database
objects (tables or views). Verified 2026-06-13 against a live Snowflake instance.

Named views in `tables()` are handled correctly — they work identically to physical
tables (verified on BL018_TEST_SV with EMPLOYEE_SUMMARY_VW).

Since the input scenario (subquery-backed SV sources) cannot occur in the current
Snowflake SV specification, no implementation is needed. If a future SV version adds
subquery support, this item would need to be reopened and implemented using the same
pattern as `ts-convert-from-databricks-mv` (Step 2c) and `ts-convert-from-tableau`
(Step 5c).

Status: VERIFIED — NOT APPLICABLE (2026-06-13)

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

---

## #6 — ASOF joins — VERIFIED

ASOF joins (`references TABLE(COL1, ASOF COL2)`) are mapped in the SKILL.md to
ThoughtSpot `joins[].on` expressions with `=` on the equi column and `>=` on the
ASOF column.

Verified end-to-end on BL018_TEST_SV (2026-06-14):
- Added `SALARY_RATES` table with `EFFECTIVE_DATE` column
- Added ASOF relationship: `EMP_TO_RATE as EMPLOYEES(DEPARTMENT,HIRE_DATE) references SALARY_RATES(DEPARTMENT, asof EFFECTIVE_DATE)`
- Model imported successfully with join expression: `(([EMPLOYEES::DEPARTMENT] = [SALARY_RATES::DEPARTMENT]) AND ([EMPLOYEES::HIRE_DATE] >= [SALARY_RATES::EFFECTIVE_DATE]))`
- Round-trip confirmed: exported model preserves the compound predicate

Status: VERIFIED (2026-06-14)
