-- Re-alias a loaded calendar table's UPPER_CASE columns back to the quoted
-- lower-case names ThoughtSpot's createCalendar API requires.
--
-- WHY THIS EXISTS. Snowflake folds an unquoted identifier to UPPER CASE, and
-- `ts load snowflake` both upper-cases every CSV header and emits the DDL
-- unquoted -- so a loaded calendar table has columns DATE, DAY_OF_WEEK, ... .
-- The calendar contract is lower case ("date", "day_of_week", ...), and
-- ThoughtSpot REJECTS the upper-case table: HTTP 400,
-- INVALID_EXTERNAL_CALENDAR wrapping CONNECTION_METADATA_FETCH_ERROR, a
-- message that never names the offending column. Verified live 2026-09-16 --
-- the identical rows registered 200 once re-aliased by this CTAS.
--
-- What it does, and what it deliberately does not:
--   * Selects all 30 contract columns by their UPPER_CASE names and aliases
--     each to its quoted lower-case contract name.
--   * Casts each to its contract type -- the same mapping
--     `ts calendar generate --ddl` emits. The loader infers types from the
--     DATA, so a calendar with no --year-prefix/--quarter-prefix loads its
--     "year" AND "quarter" label columns as INTEGER (confirmed against
--     load.infer_column_types on real generator output), and a label column
--     typed as a number is another shape the API rejects.
--   * DROPS any column beyond the 30, including an RLS discriminator that was
--     loaded from the CSV. That is deliberate: the union view (SKILL.md
--     Step 6) re-adds the discriminator as a quoted literal per branch, which
--     is the corpus `rlscalendar` shape. Carrying it through here as well
--     would name the same column twice and Snowflake would reject the view.
--   * Assumes a 30-column source. A table loaded from a --columns 10 CSV has
--     no `monthly`/`quarterly`/... to select and this statement fails on the
--     first missing one. That shape cannot be registered anyway -- see
--     references/calendar-table-contract.md.
--
-- Run with (angle brackets mark a value you supply; the only curly-brace
-- tokens in this file are the four --var placeholders, because
-- `ts snowflake exec` scans the whole file for them, comments included, and
-- aborts on any it cannot fill):
--   ts snowflake exec -f references/fix-column-case.sql --sf-profile <profile> \
--     --var source_db=CUSTOM_CALENDAR --var source_schema=PUBLIC \
--     --var source_table=RETAIL_CAL_STAGE --var target_table=RETAIL_CAL
CREATE OR REPLACE TABLE "{source_db}"."{source_schema}"."{target_table}" AS (
  SELECT
    "DATE"::DATE                       AS "date",
    "DAY_OF_WEEK"::VARCHAR             AS "day_of_week",
    "MONTH"::VARCHAR                   AS "month",
    "QUARTER"::VARCHAR                 AS "quarter",
    "YEAR"::VARCHAR                    AS "year",
    "DAY_NUMBER_OF_WEEK"::NUMBER       AS "day_number_of_week",
    "WEEK_NUMBER_OF_MONTH"::NUMBER     AS "week_number_of_month",
    "WEEK_NUMBER_OF_QUARTER"::NUMBER   AS "week_number_of_quarter",
    "WEEK_NUMBER_OF_YEAR"::NUMBER      AS "week_number_of_year",
    "IS_WEEKEND"::BOOLEAN              AS "is_weekend",
    "MONTHLY"::VARCHAR                 AS "monthly",
    "QUARTERLY"::VARCHAR               AS "quarterly",
    "DAY_NUMBER_OF_MONTH"::NUMBER      AS "day_number_of_month",
    "DAY_NUMBER_OF_QUARTER"::NUMBER    AS "day_number_of_quarter",
    "DAY_NUMBER_OF_YEAR"::NUMBER       AS "day_number_of_year",
    "MONTH_NUMBER_OF_QUARTER"::NUMBER  AS "month_number_of_quarter",
    "MONTH_NUMBER_OF_YEAR"::NUMBER     AS "month_number_of_year",
    "QUARTER_NUMBER_OF_YEAR"::NUMBER   AS "quarter_number_of_year",
    "ABSOLUTE_WEEK_NUMBER"::NUMBER     AS "absolute_week_number",
    "START_OF_WEEK_EPOCH"::DATE        AS "start_of_week_epoch",
    "END_OF_WEEK_EPOCH"::DATE          AS "end_of_week_epoch",
    "ABSOLUTE_MONTH_NUMBER"::NUMBER    AS "absolute_month_number",
    "START_OF_MONTH_EPOCH"::DATE       AS "start_of_month_epoch",
    "END_OF_MONTH_EPOCH"::DATE         AS "end_of_month_epoch",
    "ABSOLUTE_QUARTER_NUMBER"::NUMBER  AS "absolute_quarter_number",
    "START_OF_QUARTER_EPOCH"::DATE     AS "start_of_quarter_epoch",
    "END_OF_QUARTER_EPOCH"::DATE       AS "end_of_quarter_epoch",
    "ABSOLUTE_YEAR_NUMBER"::NUMBER     AS "absolute_year_number",
    "START_OF_YEAR_EPOCH"::DATE        AS "start_of_year_epoch",
    "END_OF_YEAR_EPOCH"::DATE          AS "end_of_year_epoch"
  FROM "{source_db}"."{source_schema}"."{source_table}"
);
