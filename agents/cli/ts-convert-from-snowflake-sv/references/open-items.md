# Open Items: ts-convert-from-snowflake-sv

For a full mapping of what IS supported, see [coverage-matrix.md](coverage-matrix.md).

---

## #1 — sql_view generation path for subquery-backed SVs — NOT IMPLEMENTED

Some Snowflake Semantic Views are backed by subqueries rather than physical
tables or named views (the `FROM` clause uses a subquery instead of a direct
object reference). In these cases, the skill cannot bind a ThoughtSpot Table TML
to a physical table — a SQL View TML (`sql_view:`) should be generated instead,
and the model should reference the SQL View by name in `model_tables[]`.

This path is implemented in `ts-convert-from-databricks-mv` (Step 2c — subquery source
→ SQL View TML) and `ts-convert-from-tableau` (Step 5c — custom SQL relations). The
Snowflake-SV skill currently assumes all source objects are named database objects
(tables or views) accessible via the connection schema.

**Note:** Named views in `tables()` are handled correctly — they work identically to
physical tables. This item only affects subquery sources, which Snowflake's `tables()`
block does not support (verified 2026-06-13). Keeping this item open in case a future
SV version adds subquery support.

**Workaround:** user manually creates a ThoughtSpot SQL View TML for the subquery
source, imports it, and replaces the Table TML reference in the model with the SQL View
GUID/name.

Status: NOT IMPLEMENTED

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

## #6 — ASOF joins — MAPPED, NOT YET VERIFIED LIVE

ASOF joins (`references TABLE(COL1, ASOF COL2)`) are mapped in the SKILL.md to
ThoughtSpot `joins[].on` expressions with `=` on the equi column and `>=` on the
ASOF column. The mapping follows the documented Snowflake DDL syntax.

The translation is implemented but has not been tested against a live Semantic View
containing an ASOF relationship. Range joins (the related pattern) have been verified
live on BL018_TEST_SV.

Status: MAPPED — needs live verification when a test SV with ASOF joins is available
