-- =====================================================================
-- Period-over-period: date dimension DDL templates (Snowflake)
--
-- Deploy with:
--   ts snowflake exec --file date-dimension-ddl.sql \
--     --var target_db=MYDB --var target_schema=MYSCHEMA --sf-profile {sf_profile}
--
-- Run ONLY the sections you need — see the header comment on each.
-- Databricks equivalents are noted inline; they are NOT live-verified.
-- =====================================================================

USE DATABASE {target_db};
USE SCHEMA {target_schema};


-- ---------------------------------------------------------------------
-- SECTION 1 — CREATE a day calendar from scratch
-- Use when Step 2a found no date dimension.
--
-- SIZING: the spine MUST start >= 364 days BEFORE the first fact date and
-- end >= 364 days AFTER the last fact date, or facts orphan into a NULL
-- bucket. Widen generously — a day dimension is tiny.
-- 40 years = 14,610 rows and costs nothing.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE DIM_DATE AS
SELECT
    d                                                   AS DATE_VALUE,
    DATEADD(day, -364, d)                               AS DATE_364_DAYS_AGO,
    DATE_TRUNC('week',    d)::DATE                      AS START_OF_WEEK,
    DATE_TRUNC('month',   d)::DATE                      AS START_OF_MONTH,
    DATE_TRUNC('quarter', d)::DATE                      AS START_OF_QUARTER,
    YEAR(d)                                             AS YEAR_NUMBER,
    QUARTER(d)                                          AS QUARTER_NUMBER,
    MONTH(d)                                            AS MONTH_NUMBER,     -- 1-12, cyclic: safe for sum_if
    MONTHNAME(d)                                        AS MONTH_NAME,
    DAYOFWEEK(d)                                        AS DAY_OF_WEEK,      -- cyclic: safe for sum_if
    DAYNAME(d)                                          AS DAY_NAME
FROM (
    SELECT DATEADD(day, seq4(), '1995-01-01'::DATE) AS d      -- <<< adjust start
    FROM TABLE(GENERATOR(ROWCOUNT => 14610))                  -- <<< adjust span
);
-- Databricks: sequence(start, stop, interval 1 day) + explode, or a generated view.


-- ---------------------------------------------------------------------
-- SECTION 2 — AUGMENT an existing day calendar (the common case)
-- Use when Step 2a found a date dimension without offset keys.
--
-- ADDITIVE ONLY. Keep every existing column exactly as it is: other
-- Semantic Views, Models and reports bind to them by name, and dropping
-- or renaming one breaks those dependents (ThoughtSpot refuses outright).
-- Replace the column list below with the REAL current column list.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW DIM_DATE_V AS
SELECT
    -- ---- every pre-existing column, unchanged ----
    src.DATE_VALUE,
    src.START_OF_WEEK,
    src.START_OF_MONTH,
    -- ... keep the rest verbatim ...

    -- ---- new: the 364-day offset key ----
    DATEADD(day, -364, src.DATE_VALUE)  AS DATE_364_DAYS_AGO
FROM {target_db}.{target_schema}.DIM_DATE src;


-- ---------------------------------------------------------------------
-- SECTION 3 — MONTH dimension (ONLY if comparing calendar months)
--
-- WHY A SEPARATE TABLE: a 12-month offset held on the DAY calendar
-- repeats for every day of the month, so it is not unique. Snowflake
-- accepts UNIQUE on it WITHOUT VALIDATING, then fans out at query time
-- (measured 14,415 against a true 465 -- 31x over, silently).
-- The offset must live on a dimension whose grain matches the comparison.
--
-- Skip this section entirely if only the 364-day comparison is wanted:
-- 364 days == 52 weeks, so it already serves day and week comparisons.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW DIM_MONTH AS
SELECT DISTINCT
    DATE_TRUNC('month', DATE_VALUE)::DATE                        AS MONTH_START,
    ADD_MONTHS(DATE_TRUNC('month', DATE_VALUE)::DATE, -12)::DATE AS MONTH_START_12_MONTHS_AGO,
    YEAR(DATE_VALUE)                                             AS YEAR_NUMBER,
    MONTH(DATE_VALUE)                                            AS MONTH_NUMBER,
    MONTHNAME(DATE_VALUE)                                        AS MONTH_NAME
FROM {target_db}.{target_schema}.DIM_DATE;


-- ---------------------------------------------------------------------
-- SECTION 4 — FACT-side keys
--
-- The fact needs a key at each comparison grain, matching the dimension
-- key's TYPE. A TIMESTAMP fact column joined to a DATE dimension key
-- matches only rows landing exactly on midnight -- measured 830 of
-- 176,264 orders (0.5%), silently.
--
-- Add these to the fact's reporting view; do not alter the base table.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW FACT_V AS
SELECT
    -- ---- every pre-existing column, unchanged ----
    src.*,

    -- ---- new: DATE-typed day key (joins DIM_DATE.DATE_VALUE and .DATE_364_DAYS_AGO)
    src.ORDER_TIMESTAMP::DATE                          AS ORDER_DAY,

    -- ---- new: month key (only if Section 3 was used; joins DIM_MONTH)
    DATE_TRUNC('month', src.ORDER_TIMESTAMP)::DATE     AS ORDER_MONTH
FROM {target_db}.{target_schema}.FACT src;


-- =====================================================================
-- VERIFICATION — run these before building the model. Both must pass.
-- =====================================================================

-- V1. SPINE COVERAGE: spine_end must be >= last_fact + 364 days,
--     and spine_start <= first_fact. Otherwise facts orphan into a
--     NULL bucket (measured: a phantom blank week carrying 2,089,360).
SELECT (SELECT MIN(ORDER_DAY) FROM FACT_V)      AS first_fact,
       (SELECT MAX(ORDER_DAY) FROM FACT_V)      AS last_fact,
       (SELECT MIN(DATE_VALUE) FROM DIM_DATE)   AS spine_start,
       (SELECT MAX(DATE_VALUE) FROM DIM_DATE)   AS spine_end,
       (SELECT MAX(DATE_VALUE) FROM DIM_DATE)
         >= DATEADD(day, 364, (SELECT MAX(ORDER_DAY) FROM FACT_V)) AS spine_ok;

-- V2. JOIN RATE: both counts must equal the fact row count. If the
--     as-is count is far lower, the fact key is a TIMESTAMP -- use the
--     ::DATE key from Section 4.
SELECT COUNT(*)                AS fact_rows,
       COUNT(cur.DATE_VALUE)   AS joined_current,
       COUNT(off.DATE_364_DAYS_AGO) AS joined_offset
FROM FACT_V f
LEFT JOIN DIM_DATE cur ON f.ORDER_DAY = cur.DATE_VALUE
LEFT JOIN DIM_DATE off ON f.ORDER_DAY = off.DATE_364_DAYS_AGO;

-- V3. RECONCILIATION (run AFTER the model is built): the prior-period
--     measure summed over ALL periods must equal the base measure's
--     grand total -- same rows, shifted key. Any difference is orphaned
--     rows or fan-out.
SELECT (SELECT SUM(AMOUNT) FROM FACT_V) AS base_total;
