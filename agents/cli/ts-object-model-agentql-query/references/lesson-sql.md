<!-- GENERATED FILE — do not edit by hand.
     Regenerate (needs a live cluster for the capture, then offline for the build):
       python3 tools/agentql-retest/run.py --profile <profile> --suite lessons guards --out /tmp/cap.json
       python3 tools/agentql-retest/build_lesson_sql.py --from /tmp/cap.json
-->
# Captured warehouse SQL — Learn AgentQL lessons

The exact warehouse SQL ThoughtSpot compiled (`executable_sql`) for every course lesson,
captured live on the sample Model **`(Sample) Retail - Apparel`** (the SE demo cluster) on
2026-10-19. **Offline mode shows these verbatim in section 3** — a lesson should never reconstruct
the SQL by hand. Each entry is keyed by the lesson's **Guarded by** id. A *break it* lesson
(one whose point is a rejection) shows the real `status` and error instead of SQL.

Keep this in step with the lessons: the ids come straight from `tools/agentql-retest`
(`--suite lessons guards`), so re-run the two commands above whenever a lesson's AgentQL
changes.


## ctl_ap_total

*control*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
LIMIT 100000
```

---

## ctl_ap_by_region

*control*

**AgentQL**

```sql
SELECT "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."REGION" "ca_1", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l1_select_star_rejected

*📘 1.2 a rejected query is a structured error*

**AgentQL**

```sql
SELECT * FROM "(Sample) Retail - Apparel" AS "t1"
```

**Rejected — `status: SELECT_STAR`** — Error Code: QUERY_GEN_ERROR Error Message: SQL validation failed with 1 error(s) Validation Errors: 1. [SELECT_STAR] SELECT * is not supported. Please explicitly list columns. in SELECT clause, column 1 (near '*')

---

## l1_unknown_column

*📘 1.2 a rejected query is a structured error*

**AgentQL**

```sql
SELECT SUM("t1"."revenue") AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Rejected — `status: COLUMN_NOT_FOUND`** — Error Code: QUERY_GEN_ERROR Error Message: SQL validation failed with 1 error(s) Validation Errors: 1. [COLUMN_NOT_FOUND] Column 'revenue' not found in table '(Sample) Retail - Apparel'. in SELECT clause, column 1

---

## l1_compiles_then_fails

*📘 1.3 generate-sql SUCCESS is not proof the query runs*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" WHERE "t1"."product" IN (SELECT "t2"."product" FROM "(Sample) Retail - Apparel" AS "t2" WHERE "t2"."item type" = 'Jackets')
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_2"
    ON "ta_1"."PRODUCTID" = "ta_2"."PRODUCTID"
WHERE "ta_2"."PRODUCTNAME" in (select "t2".product from (sample) retail - apparel "t2" where "t2".item type = 'Jackets')
LIMIT 100000
```

---

## l1_dates_are_epoch_seconds

*📘 1.4 reading fetch-data: types, and dates as epoch seconds*

**AgentQL**

```sql
SELECT "t1"."date" AS d, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."date" ORDER BY "t1"."date" DESC LIMIT 1
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE") "ca_1", 
  CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
GROUP BY "ca_1"
ORDER BY "ca_1" DESC NULLS LAST
LIMIT 1
```

---

## l2_total_touches_fact_only

*📘 2.1 a total: null handling, the row cap, one table*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s, SUM("t1"."quantity purchased") AS q FROM "(Sample) Retail - Apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END "ca_1", 
  CASE
    WHEN sum("ta_1"."QUANTITYPURCHASED") IS NOT NULL THEN sum("ta_1"."QUANTITYPURCHASED")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
LIMIT 100000
```

---

## l2_group_by_joins_one_dim

*📘 2.2 grouping by a dimension: the join is written for you*

**AgentQL**

```sql
SELECT "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."REGION" "ca_1", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l2_two_dims_two_joins

*📘 2.3 two dimensions, two joins*

**AgentQL**

```sql
SELECT "t1"."item type" AS it, "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."item type", "t1"."region"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."PRODUCTTYPE" "ca_1", 
  "ta_2"."REGION" "ca_2", 
  CASE
    WHEN sum("ta_3"."SALES") IS NOT NULL THEN sum("ta_3"."SALES")
    ELSE 0
  END "ca_3"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_3"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_1"
    ON "ta_3"."PRODUCTID" = "ta_1"."PRODUCTID"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_2"
    ON "ta_3"."STOREID" = "ta_2"."STOREID"
GROUP BY 
  "ca_1", 
  "ca_2"
LIMIT 100000
```

---

## l2_top_n

*📘 2.4 top N: ORDER BY and LIMIT*

**AgentQL**

```sql
SELECT "t1"."item type" AS it, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."item type" ORDER BY s DESC LIMIT 3
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."PRODUCTTYPE" "ca_1", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_1"
    ON "ta_2"."PRODUCTID" = "ta_1"."PRODUCTID"
GROUP BY "ca_1"
ORDER BY "ca_2" DESC NULLS LAST
LIMIT 3
```

---

## l2_formula_compiles_inline

*📘 2.5 a Model formula compiles into the SQL*

**AgentQL**

```sql
SELECT YEAR("t1"."date") AS y, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY YEAR("t1"."date")
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  extract(year from DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) "ca_1", 
  CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l2_current_date_rejected

*📘 2.5 a Model formula compiles into the SQL (break it)*

**AgentQL**

```sql
SELECT CURRENT_DATE AS d, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Rejected — `status: SQL_DATE_FUNCTION`** — Error Code: QUERY_GEN_ERROR Error Message: SQL validation failed with 1 error(s) Validation Errors: 1. [SQL_DATE_FUNCTION] SQL date functions like 'current_date' are not supported. Use literal dates. in SELECT clause, column 1 (near 'current_date')

---

## l2_filter_case_insensitive

*📘 2.6 filters: string equality is case-insensitive*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" WHERE "t1"."region" = 'west'
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_2"
    ON "ta_1"."STOREID" = "ta_2"."STOREID"
WHERE LOWER("ta_2"."REGION") = 'west'
LIMIT 100000
```

---

## l2_identifiers_case_insensitive

*📘 2.7 the parser is lenient: identifier case*

**AgentQL**

```sql
SELECT SUM("t1"."Sales") AS s FROM "(sample) retail - apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
LIMIT 100000
```

---

## l2_implicit_group_by

*📘 2.7 the parser is lenient: a missing GROUP BY*

**AgentQL**

```sql
SELECT "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."REGION" "ca_1", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l2_bare_measure_row_level

*📘 2.8 a bare measure is not aggregated*

**AgentQL**

```sql
SELECT "t1"."region" AS r, "t1"."sales" AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."REGION" "ca_1", 
  "ta_2"."SALES" "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
LIMIT 100000
```

---

## l2_count_distinct

*📘 2.6 counting: COUNT(DISTINCT col), never COUNT(*)*

**AgentQL**

```sql
SELECT COUNT(DISTINCT "t1"."store") AS n FROM "(Sample) Retail - Apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT count(DISTINCT "ta_1"."STORENAME") "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
LIMIT 100000
```

---

## l2_count_star_rejected

*📘 2.6 counting: COUNT(DISTINCT col), never COUNT(*)*

**AgentQL**

```sql
SELECT COUNT(*) AS n FROM "(Sample) Retail - Apparel" AS "t1"
```

**Rejected — `status: COUNT_STAR`** — Error Code: QUERY_GEN_ERROR Error Message: SQL validation failed with 1 error(s) Validation Errors: 1. [COUNT_STAR] COUNT(*) is not supported. Please use COUNT(column_name). in SELECT clause, column 1 (near 'count(*)')

---

## ctl_ap_item_parts

*control*

**AgentQL**

```sql
SELECT "t1"."item type" AS it, SUM("t1"."sales") AS s, SUM("t1"."quantity purchased") AS q FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."item type"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."PRODUCTTYPE" "ca_1", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_2", 
  CASE
    WHEN sum("ta_2"."QUANTITYPURCHASED") IS NOT NULL THEN sum("ta_2"."QUANTITYPURCHASED")
    ELSE 0
  END "ca_3"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_1"
    ON "ta_2"."PRODUCTID" = "ta_1"."PRODUCTID"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l3_ratio_safe_division

*📘 3.1 a ratio of two measures, divided safely*

**AgentQL**

```sql
SELECT "t1"."item type" AS it, SUM("t1"."sales") / SUM("t1"."quantity purchased") AS avg_price FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."item type"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."PRODUCTTYPE" "ca_1", 
  (CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END / NULLIF(CASE
    WHEN sum("ta_2"."QUANTITYPURCHASED") IS NOT NULL THEN sum("ta_2"."QUANTITYPURCHASED")
    ELSE 0
  END,0.0)) "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_1"
    ON "ta_2"."PRODUCTID" = "ta_1"."PRODUCTID"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l3_avg_is_row_level

*📘 3.2 AVG averages fact rows, not anything larger*

**AgentQL**

```sql
SELECT "t1"."region" AS r, AVG("t1"."sales") AS a, SUM("t1"."sales") AS s, COUNT("t1"."sales") AS n FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."REGION" "ca_1", 
  avg("ta_2"."SALES") "ca_2", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_3", 
  count("ta_2"."SALES") "ca_4"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l3_agg_on_raw_measure_rejected

*📘 3.4 formula measures: AGG, not SUM (break it)*

**AgentQL**

```sql
SELECT "t1"."region" AS r, AGG("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region"
```

**Rejected — `status: QUERY_GEN_ERROR`** — Failed to transform QuerySpec: Error Code: QUERY_GEN_ERROR Error Message: Failed validation for GroupAggregateOptimizationTransformer: All non-constant columns should be grouped by or aggregated in a query. id { guid: "…" name: "SQL Query" } column { id { guid: "…" name: "REGION" } output_id { guid: "…" name: "r" } column_type: ATTRIBUTE data_type: CHAR } column { id { guid: "…" name: "SALES" } ou …

---

## l3_dim_only_one_table

*📘 3.3 a dimension-only query reads only its own table*

**AgentQL**

```sql
SELECT "t1"."item type" AS it FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."item type"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT "ta_1"."PRODUCTTYPE" "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_1"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l3_two_dims_via_fact

*📘 3.3 two dimensions are joined through the fact table*

**AgentQL**

```sql
SELECT "t1"."item type" AS it, "t1"."region" AS r FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."item type", "t1"."region"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."PRODUCTTYPE" "ca_1", 
  "ta_2"."REGION" "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "MTA_0"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_1"
    ON "MTA_0"."PRODUCTID" = "ta_1"."PRODUCTID"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_2"
    ON "MTA_0"."STOREID" = "ta_2"."STOREID"
GROUP BY 
  "ca_1", 
  "ca_2"
LIMIT 100000
```

---

## l3_all_products_left_join

*📘 3.6 every product via an outer join; business rules in the generated SQL*

**AgentQL**

```sql
WITH all_p AS (SELECT "t1"."product" AS p FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."product"), west AS (SELECT "t2"."product" AS p, SUM("t2"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t2" WHERE "t2"."region" = 'West' GROUP BY "t2"."product") SELECT a.p AS product, COALESCE(west.s, 0) AS west_sales FROM all_p a LEFT OUTER JOIN west ON a.p = west.p
```

**Generated SQL** (`status: SUCCESS`)

```sql
WITH 
  "qt_0" AS (
    SELECT "ta_1"."PRODUCTNAME" "ca_1"
    FROM "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_1"
    GROUP BY "ca_1"
  ), 
  "qt_1" AS (
    SELECT 
      "ta_2"."PRODUCTNAME" "ca_2", 
      CASE
        WHEN sum("ta_3"."SALES") IS NOT NULL THEN sum("ta_3"."SALES")
        ELSE 0
      END "ca_3"
    FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_3"
      JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_2"
        ON "ta_3"."PRODUCTID" = "ta_2"."PRODUCTID"
      JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_4"
        ON "ta_3"."STOREID" = "ta_4"."STOREID"
    WHERE LOWER("ta_4"."REGION") = 'west'
    GROUP BY "ca_2"
  )
SELECT 
  "ta_5"."ca_1" "ca_4", 
  CASE
    WHEN "ta_6"."ca_3" IS NOT NULL THEN "ta_6"."ca_3"
    ELSE 0
  END "ca_5"
FROM "qt_0" "ta_5"
  LEFT OUTER JOIN "qt_1" "ta_6"
    ON "ta_5"."ca_1" = "ta_6"."ca_2"
LIMIT 100000
```

---

## ctl_ap_by_year

*control*

**AgentQL**

```sql
SELECT YEAR_NUMBER("t1"."date") AS y, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY YEAR_NUMBER("t1"."date")
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  EXTRACT(YEAR FROM DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) "ca_1", 
  CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l4_date_parts

*📘 4.1 date parts with the extraction functions*

**AgentQL**

```sql
SELECT YEAR_NUMBER("t1"."date") AS y, QUARTER_NUMBER("t1"."date") AS qn, MONTH_NUMBER("t1"."date") AS m, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY YEAR_NUMBER("t1"."date"), QUARTER_NUMBER("t1"."date"), MONTH_NUMBER("t1"."date")
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  EXTRACT(YEAR FROM DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) "ca_1", 
  CEIL((EXTRACT(MONTH FROM DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) / NULLIF(3.0,0.0))) "ca_2", 
  EXTRACT(MONTH FROM DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) "ca_3", 
  CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END "ca_4"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
GROUP BY 
  "ca_1", 
  "ca_2", 
  "ca_3"
LIMIT 100000
```

---

## l4_day_name

*📘 4.1 date parts with the extraction functions*

**AgentQL**

```sql
SELECT DAY_NAME("t1"."date") AS dn, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY DAY_NAME("t1"."date")
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  CASE
    WHEN (MOD((DATEDIFF(day, DATE '1970-01-01', DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) + 3), 7) + 1) = 1 THEN 'monday'
    WHEN (MOD((DATEDIFF(day, DATE '1970-01-01', DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) + 3), 7) + 1) = 2 THEN 'tuesday'
    WHEN (MOD((DATEDIFF(day, DATE '1970-01-01', DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) + 3), 7) + 1) = 3 THEN 'wednesday'
    WHEN (MOD((DATEDIFF(day, DATE '1970-01-01', DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) + 3), 7) + 1) = 4 THEN 'thursday'
    WHEN (MOD((DATEDIFF(day, DATE '1970-01-01', DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) + 3), 7) + 1) = 5 THEN 'friday'
    WHEN (MOD((DATEDIFF(day, DATE '1970-01-01', DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) + 3), 7) + 1) = 6 THEN 'saturday'
    WHEN (MOD((DATEDIFF(day, DATE '1970-01-01', DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) + 3), 7) + 1) = 7 THEN 'sunday'
  END "ca_1", 
  CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l4_day_in_week

*📘 4.1 date parts with the extraction functions*

**AgentQL**

```sql
SELECT DAY_IN_WEEK_NUMBER("t1"."date") AS dw, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY DAY_IN_WEEK_NUMBER("t1"."date")
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  (MOD((DATEDIFF(day, DATE '1970-01-01', DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) + 3), 7) + 1) "ca_1", 
  CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l4_this_year_relative

*📘 4.2 relative dates: the period functions*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" WHERE DIFF_YEAR(START_OF_CURRENT_YEAR(), "t1"."date") = 0
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
WHERE (EXTRACT(YEAR FROM DATE_FROM_PARTS(EXTRACT(YEAR FROM CURRENT_DATE()), 1, 01)) - EXTRACT(YEAR FROM DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE"))) = 0
LIMIT 100000
```

---

## l4_last_30_days

*📘 4.2 relative dates: the period functions*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" WHERE DIFF_DAY(START_OF_CURRENT_DAY(), "t1"."date") BETWEEN 1 AND 30
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
WHERE (
  DATEDIFF(day, DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE"), CURRENT_DATE()) >= 1
  AND DATEDIFF(day, DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE"), CURRENT_DATE()) <= 30
)
LIMIT 100000
```

---

## l4_date_literal_filter

*📘 4.3 a date literal in WHERE*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" WHERE "t1"."date" >= '2026-01-01'
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
WHERE DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE") >= '2026-01-01'
LIMIT 100000
```

---

## l4_date_trunc_fails

*📘 4.3 a date literal in WHERE (break it)*

**AgentQL**

```sql
SELECT DATE_TRUNC('month', "t1"."date") AS m, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY DATE_TRUNC('month', "t1"."date")
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  min(trunc("t1".date, null)) "ca_1", 
  CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
LIMIT 100000
```

---

## l4_string_functions

*📘 4.4 string functions*

**AgentQL**

```sql
SELECT UPPER("t1"."region") AS u, LENGTH("t1"."region") AS l, CONCAT("t1"."region", '-', "t1"."state") AS c, SUBSTR("t1"."state", 1, 3) AS sub FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY UPPER("t1"."region"), LENGTH("t1"."region"), CONCAT("t1"."region", '-', "t1"."state"), SUBSTR("t1"."state", 1, 3)
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  upper("ta_1"."REGION") "ca_1", 
  LENGTH("ta_1"."REGION") "ca_2", 
  ("ta_1"."REGION" || '-' || "ta_1"."STATE") "ca_3", 
  substring("ta_1"."STATE", 1, 3) "ca_4"
FROM "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
GROUP BY 
  "ca_1", 
  "ca_2", 
  "ca_3", 
  "ca_4"
LIMIT 100000
```

---

## l4_group_by_alias

*📘 4.4 string functions*

**AgentQL**

```sql
SELECT UPPER("t1"."region") AS u, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY u
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  upper("ta_1"."REGION") "ca_1", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l4_group_by_ordinal_rejected

*📘 4.4 string functions*

**AgentQL**

```sql
SELECT UPPER("t1"."region") AS u, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY 1
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Failed to deserialize SQL: Missing formula alias: 3f87fea7-e1e4-478e-b7be-66386ae08c23

---

## l4_case_buckets

*📘 4.5 CASE to bucket values*

**AgentQL**

```sql
SELECT CASE WHEN "t1"."sales" >= 1000 THEN 'large' WHEN "t1"."sales" >= 100 THEN 'medium' ELSE 'small' END AS b, COUNT("t1"."sales") AS n, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY CASE WHEN "t1"."sales" >= 1000 THEN 'large' WHEN "t1"."sales" >= 100 THEN 'medium' ELSE 'small' END
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  CASE
    WHEN "ta_1"."SALES" >= 1000 THEN 'large'
    ELSE CASE
      WHEN "ta_1"."SALES" >= 100 THEN 'medium'
      ELSE 'small'
    END
  END "ca_1", 
  count("ta_1"."SALES") "ca_2", 
  CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END "ca_3"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
GROUP BY "ca_1"
LIMIT 100000
```

---

## ctl_ap_by_store

*control*

**AgentQL**

```sql
SELECT "t1"."store" AS st, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."store"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."STORENAME" "ca_1", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l5_cte_two_step

*📘 5.1 a CTE for two-step aggregation*

**AgentQL**

```sql
WITH st AS (SELECT "t1"."store" AS store, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."store") SELECT AVG(st.s) AS avg_store_sales, COUNT(st.store) AS n FROM st
```

**Generated SQL** (`status: SUCCESS`)

```sql
WITH "qt_0" AS (
  SELECT 
    "ta_1"."STORENAME" "ca_1", 
    CASE
      WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
      ELSE 0
    END "ca_2"
  FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
    JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
      ON "ta_2"."STOREID" = "ta_1"."STOREID"
  GROUP BY "ca_1"
)
SELECT 
  avg("ta_3"."ca_2") "ca_3", 
  count("ta_3"."ca_1") "ca_4"
FROM "qt_0" "ta_3"
LIMIT 100000
```

---

## l5_rank

*📘 5.2 window functions: rank and share of total*

**AgentQL**

```sql
SELECT "t1"."region" AS r, "t1"."store" AS store, SUM("t1"."sales") AS s, RANK() OVER (PARTITION BY "t1"."region" ORDER BY SUM("t1"."sales") DESC) AS rk FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region", "t1"."store"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."REGION" "ca_1", 
  "ta_1"."STORENAME" "ca_2", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_3", 
  rank() over (partition by "ta_1"."REGION" order by CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END desc) "ca_4"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
GROUP BY 
  "ca_1", 
  "ca_2"
LIMIT 100000
```

---

## l5_share_of_total

*📘 5.2 window functions: rank and share of total*

**AgentQL**

```sql
SELECT "t1"."region" AS r, SUM("t1"."sales") AS s, SUM("t1"."sales") / SUM(SUM("t1"."sales")) OVER () AS share FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."REGION" "ca_1", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_2", 
  (CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END / NULLIF(sum(CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END) over (),0.0)) "ca_3"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l5_top_n_per_group

*📘 5.3 top N per group*

**AgentQL**

```sql
WITH x AS (SELECT "t1"."region" AS r, "t1"."item type" AS it, SUM("t1"."sales") AS s, ROW_NUMBER() OVER (PARTITION BY "t1"."region" ORDER BY SUM("t1"."sales") DESC) AS rn FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region", "t1"."item type") SELECT x.r, x.it, x.s FROM x WHERE x.rn <= 2
```

**Generated SQL** (`status: SUCCESS`)

```sql
WITH "qt_0" AS (
  SELECT 
    "ta_1"."REGION" "ca_1", 
    "ta_2"."PRODUCTTYPE" "ca_2", 
    CASE
      WHEN sum("ta_3"."SALES") IS NOT NULL THEN sum("ta_3"."SALES")
      ELSE 0
    END "ca_3", 
    row_number() over (partition by "ta_1"."REGION" order by CASE
      WHEN sum("ta_3"."SALES") IS NOT NULL THEN sum("ta_3"."SALES")
      ELSE 0
    END desc) "ca_4"
  FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_3"
    JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
      ON "ta_3"."STOREID" = "ta_1"."STOREID"
    JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_2"
      ON "ta_3"."PRODUCTID" = "ta_2"."PRODUCTID"
  GROUP BY 
    "ca_1", 
    "ca_2"
  
)
SELECT 
  "ta_4"."ca_1" "ca_5", 
  "ta_4"."ca_2" "ca_6", 
  "ta_4"."ca_3" "ca_7"
FROM "qt_0" "ta_4"
WHERE "ta_4"."ca_4" <= 2
LIMIT 100000
```

---

## l5_year_over_year

*📘 5.4 period over period and running totals*

**AgentQL**

```sql
SELECT YEAR_NUMBER("t1"."date") AS y, SUM("t1"."sales") AS s, LAG(SUM("t1"."sales")) OVER (ORDER BY YEAR_NUMBER("t1"."date")) AS prev FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY YEAR_NUMBER("t1"."date")
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  EXTRACT(YEAR FROM DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) "ca_1", 
  CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END "ca_2", 
  lag(CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END) over (order by EXTRACT(YEAR FROM DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) asc) "ca_3"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l5_running_total

*📘 5.4 period over period and running totals*

**AgentQL**

```sql
SELECT YEAR_NUMBER("t1"."date") AS y, SUM("t1"."sales") AS s, SUM(SUM("t1"."sales")) OVER (ORDER BY YEAR_NUMBER("t1"."date")) AS running FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY YEAR_NUMBER("t1"."date")
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  EXTRACT(YEAR FROM DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) "ca_1", 
  CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END "ca_2", 
  sum(CASE
    WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
    ELSE 0
  END) over (order by EXTRACT(YEAR FROM DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) asc) "ca_3"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
GROUP BY "ca_1"
LIMIT 100000
```

---

## l5_union_all

*📘 5.5 combining results: set operations and CTE joins*

**AgentQL**

```sql
SELECT "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" WHERE "t1"."region" = 'West' GROUP BY "t1"."region" UNION ALL SELECT "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" WHERE "t1"."region" = 'East' GROUP BY "t1"."region"
```

**Generated SQL** (`status: SUCCESS`)

```sql
WITH 
  "qt_0" AS (
    SELECT 
      "ta_1"."REGION" "ca_1", 
      CASE
        WHEN sum(CASE
          WHEN LOWER("ta_1"."REGION") = 'west' THEN "ta_2"."SALES"
          ELSE NULL
        END) IS NOT NULL THEN sum(CASE
          WHEN LOWER("ta_1"."REGION") = 'west' THEN "ta_2"."SALES"
          ELSE NULL
        END)
        ELSE 0
      END "ca_2", 
      (CASE
        WHEN sum(CASE
          WHEN (
            LOWER("ta_1"."REGION") = 'west'
            AND NOT("ta_2"."SALES" IS NULL)
          ) THEN 1
          ELSE 0
        END) IS NOT NULL THEN sum(CASE
          WHEN (
            LOWER("ta_1"."REGION") = 'west'
            AND NOT("ta_2"."SALES" IS NULL)
          ) THEN 1
          ELSE 0
        END)
        ELSE 0
      END > 0) "ca_3", 
      CASE
        WHEN sum(CASE
          WHEN LOWER("ta_1"."REGION") = 'east' THEN "ta_2"."SALES"
          ELSE NULL
        END) IS NOT NULL THEN sum(CASE
          WHEN LOWER("ta_1"."REGION") = 'east' THEN "ta_2"."SALES"
          ELSE NULL
        END)
        ELSE 0
      END "ca_4", 
      (CASE
        WHEN sum(CASE
          WHEN (
            LOWER("ta_1"."REGION") = 'east'
            AND NOT("ta_2"."SALES" IS NULL)
          ) THEN 1
          ELSE 0
        END) IS NOT NULL THEN sum(CASE
          WHEN (
            LOWER("ta_1"."REGION") = 'east'
            AND NOT("ta_2"."SALES" IS NULL)
          ) THEN 1
          ELSE 0
        END)
        ELSE 0
      END > 0) "ca_5"
    FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
      JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
        ON "ta_2"."STOREID" = "ta_1"."STOREID"
    GROUP BY "ca_1"
  ), 
  "qt_1" AS (
    SELECT 
      "ta_3"."ca_1" "ca_6", 
      "ta_3"."ca_2" "ca_7"
    FROM "qt_0" "ta_3"
    WHERE "ta_3"."ca_3"
  ), 
  "qt_2" AS (
    SELECT 
      "ta_3"."ca_1" "ca_8", 
      "ta_3"."ca_4" "ca_9"
    FROM "qt_0" "ta_3"
    WHERE "ta_3"."ca_5"
  )
(
  SELECT *
  FROM "qt_1"
)
UNION ALL (
  SELECT *
  FROM "qt_2"
)
```

---

## l5_join_ctes

*📘 5.5 combining results: set operations and CTE joins*

**AgentQL**

```sql
WITH a AS (SELECT "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region"), b AS (SELECT "t1"."region" AS r, COUNT(DISTINCT "t1"."store") AS n FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region") SELECT a.r, a.s, b.n, a.s / b.n AS per_store FROM a JOIN b ON a.r = b.r
```

**Generated SQL** (`status: SUCCESS`)

```sql
WITH 
  "qt_0" AS (
    SELECT 
      "ta_1"."REGION" "ca_1", 
      CASE
        WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
        ELSE 0
      END "ca_2"
    FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
      JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
        ON "ta_2"."STOREID" = "ta_1"."STOREID"
    GROUP BY "ca_1"
  ), 
  "qt_1" AS (
    SELECT 
      "ta_3"."REGION" "ca_3", 
      count(DISTINCT "ta_3"."STORENAME") "ca_4"
    FROM "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_3"
    GROUP BY "ca_3"
  )
SELECT 
  "ta_4"."ca_1" "ca_5", 
  "ta_4"."ca_2" "ca_6", 
  "ta_5"."ca_4" "ca_7", 
  ("ta_4"."ca_2" / NULLIF("ta_5"."ca_4",0)) "ca_8"
FROM "qt_0" "ta_4"
  JOIN "qt_1" "ta_5"
    ON "ta_4"."ca_1" = "ta_5"."ca_3"
LIMIT 100000
```

---

## l5_having

*📘 5.6 HAVING, and the shapes that are not allowed*

**AgentQL**

```sql
SELECT "t1"."store" AS store, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."store" HAVING SUM("t1"."sales") > 40000000
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."STORENAME" "ca_1", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
GROUP BY "ca_1"
HAVING CASE
  WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
  ELSE 0
END > 40000000
LIMIT 100000
```

---

## l5_from_subquery_rejected

*📘 5.6 HAVING, and the shapes that are not allowed*

**AgentQL**

```sql
SELECT x.r FROM (SELECT "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region") AS x
```

**Rejected — `status: TABLE_NOT_FOUND`** — Error Code: QUERY_GEN_ERROR Error Message: SQL validation failed with 2 error(s) Validation Errors: 1. [TABLE_NOT_FOUND] Table 't' not found. in FROM clause 2. [TABLE_NOT_FOUND] Table 'x' not found. in SELECT clause, column 1

---

## ctl_ap_top1_per_region

*control*

**AgentQL**

```sql
WITH x AS (SELECT "t1"."region" AS r, "t1"."item type" AS it, SUM("t1"."sales") AS s, ROW_NUMBER() OVER (PARTITION BY "t1"."region" ORDER BY SUM("t1"."sales") DESC) AS rn FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region", "t1"."item type") SELECT x.r, x.it, x.s FROM x WHERE x.rn = 1
```

**Generated SQL** (`status: SUCCESS`)

```sql
WITH "qt_0" AS (
  SELECT 
    "ta_1"."REGION" "ca_1", 
    "ta_2"."PRODUCTTYPE" "ca_2", 
    CASE
      WHEN sum("ta_3"."SALES") IS NOT NULL THEN sum("ta_3"."SALES")
      ELSE 0
    END "ca_3", 
    row_number() over (partition by "ta_1"."REGION" order by CASE
      WHEN sum("ta_3"."SALES") IS NOT NULL THEN sum("ta_3"."SALES")
      ELSE 0
    END desc) "ca_4"
  FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_3"
    JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
      ON "ta_3"."STOREID" = "ta_1"."STOREID"
    JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_2"
      ON "ta_3"."PRODUCTID" = "ta_2"."PRODUCTID"
  GROUP BY 
    "ca_1", 
    "ca_2"
  
)
SELECT 
  "ta_4"."ca_1" "ca_5", 
  "ta_4"."ca_2" "ca_6", 
  "ta_4"."ca_3" "ca_7"
FROM "qt_0" "ta_4"
WHERE "ta_4"."ca_4" = 1
LIMIT 100000
```

---

## ctl_ap_west_case

*control*

**AgentQL**

```sql
SELECT SUM(CASE WHEN "t1"."region" = 'West' THEN "t1"."sales" ELSE 0 END) AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum(CASE
    WHEN LOWER("ta_2"."REGION") = 'west' THEN "ta_1"."SALES"
    ELSE 0
  END) IS NOT NULL THEN sum(CASE
    WHEN LOWER("ta_2"."REGION") = 'west' THEN "ta_1"."SALES"
    ELSE 0
  END)
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_2"
    ON "ta_1"."STOREID" = "ta_2"."STOREID"
LIMIT 100000
```

---

## l6_qualify_dropped

*📘 6.1 QUALIFY is silently dropped*

**AgentQL**

```sql
SELECT "t1"."region" AS r, "t1"."item type" AS it, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region", "t1"."item type" QUALIFY ROW_NUMBER() OVER (PARTITION BY "t1"."region" ORDER BY SUM("t1"."sales") DESC) = 1
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."REGION" "ca_1", 
  "ta_2"."PRODUCTTYPE" "ca_2", 
  CASE
    WHEN sum("ta_3"."SALES") IS NOT NULL THEN sum("ta_3"."SALES")
    ELSE 0
  END "ca_3"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_3"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_3"."STOREID" = "ta_1"."STOREID"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_PRODUCTS" "ta_2"
    ON "ta_3"."PRODUCTID" = "ta_2"."PRODUCTID"
GROUP BY 
  "ca_1", 
  "ca_2"
LIMIT 100000
```

---

## l6_filter_dropped

*📘 6.2 FILTER (WHERE …) is silently dropped*

**AgentQL**

```sql
SELECT SUM("t1"."sales") FILTER (WHERE "t1"."region" = 'West') AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
LIMIT 100000
```

---

## l6_where_aggregate_is_having

*📘 6.3 lenient rewrites you should not rely on*

**AgentQL**

```sql
SELECT "t1"."store" AS store, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" WHERE SUM("t1"."sales") > 40000000 GROUP BY "t1"."store"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."STORENAME" "ca_1", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
GROUP BY "ca_1"
HAVING CASE
  WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
  ELSE 0
END > 40000000
LIMIT 100000
```

---

## l6_stddev_rejected

*📘 6.4 loud failures, and their workarounds*

**AgentQL**

```sql
SELECT STDDEV_SAMP("t1"."sales") AS sd FROM "(Sample) Retail - Apparel" AS "t1"
```

**Rejected — `status: UNSUPPORTED_AGGREGATE`** — Error Code: QUERY_GEN_ERROR Error Message: SQL validation failed with 1 error(s) Validation Errors: 1. [UNSUPPORTED_AGGREGATE] Aggregate/window function 'stddev_samp' is not supported directly on a model. Select the arguments as output columns in a CTE and apply this function over those output columns. in SELECT clause, column 1 (near 'stddev_samp("t1".sales)')

---

## l6_stddev_over_cte

*📘 6.4 loud failures, and their workarounds*

**AgentQL**

```sql
WITH st AS (SELECT "t1"."store" AS store, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."store") SELECT STDDEV_SAMP(st.s) AS sd FROM st
```

**Generated SQL** (`status: SUCCESS`)

```sql
WITH "qt_0" AS (
  SELECT 
    "ta_1"."STORENAME" "ca_1", 
    CASE
      WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
      ELSE 0
    END "ca_2"
  FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
    JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
      ON "ta_2"."STOREID" = "ta_1"."STOREID"
  GROUP BY "ca_1"
)
SELECT stddev_samp("ta_3"."ca_2") "ca_3"
FROM "qt_0" "ta_3"
LIMIT 100000
```

---

## l6_in_subquery_fails

*📘 6.4 loud failures, and their workarounds*

**AgentQL**

```sql
SELECT "t1"."region" AS r, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" WHERE "t1"."region" IN (SELECT "t2"."region" FROM "(Sample) Retail - Apparel" AS "t2" WHERE "t2"."state" = 'california') GROUP BY "t1"."region"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."REGION" "ca_1", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_2"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
WHERE "ta_1"."REGION" in (select "t2".region from (sample) retail - apparel "t2" where "t2".state = 'california')
GROUP BY "ca_1"
LIMIT 100000
```

---

## l6_sum_case_date_literal

*📘 6.1 QUALIFY is silently dropped (and one more silent case)*

**AgentQL**

```sql
SELECT SUM(CASE WHEN "t1"."date" >= '2026-01-01' THEN "t1"."sales" ELSE 0 END) AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum(CASE
    WHEN DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE") >= '2026-01-01' THEN "ta_1"."SALES"
    ELSE 0
  END) IS NOT NULL THEN sum(CASE
    WHEN DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE") >= '2026-01-01' THEN "ta_1"."SALES"
    ELSE 0
  END)
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
LIMIT 100000
```

---

## ctl_ap_this_year_case

*control*

**AgentQL**

```sql
SELECT SUM(CASE WHEN YEAR_NUMBER("t1"."date") >= 2026 THEN "t1"."sales" ELSE 0 END) AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum(CASE
    WHEN EXTRACT(YEAR FROM DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) >= 2026 THEN "ta_1"."SALES"
    ELSE 0
  END) IS NOT NULL THEN sum(CASE
    WHEN EXTRACT(YEAR FROM DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_1"."RECORDDATE")) >= 2026 THEN "ta_1"."SALES"
    ELSE 0
  END)
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
LIMIT 100000
```

---

## l7_columns_match_rows

*📘 7.1 consuming fetch-data in code*

**AgentQL**

```sql
SELECT "t1"."region" AS r, "t1"."date" AS d, SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region", "t1"."date" ORDER BY "t1"."date" DESC LIMIT 5
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT 
  "ta_1"."REGION" "ca_1", 
  DATEADD(day, DATEDIFF(day, DATE('2020-04-30', 'YYYY-MM-DD'), CURRENT_DATE()), "ta_2"."RECORDDATE") "ca_2", 
  CASE
    WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
    ELSE 0
  END "ca_3"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    ON "ta_2"."STOREID" = "ta_1"."STOREID"
GROUP BY 
  "ca_1", 
  "ca_2"
ORDER BY "ca_2" DESC NULLS LAST
LIMIT 5
```

---

## g_ctl_valid_select

*🛡 control: a valid query compiles*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
LIMIT 100000
```

---

## g_delete_all

*🛡 Writes are rejected: DELETE*

**AgentQL**

```sql
DELETE FROM "(Sample) Retail - Apparel"
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_delete_where

*🛡 Writes are rejected: DELETE*

**AgentQL**

```sql
DELETE FROM "(Sample) Retail - Apparel" AS "t1" WHERE "t1"."region" = 'West'
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_update

*🛡 Writes are rejected: UPDATE*

**AgentQL**

```sql
UPDATE "(Sample) Retail - Apparel" SET "sales" = 0
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_insert_values

*🛡 Writes are rejected: INSERT*

**AgentQL**

```sql
INSERT INTO "(Sample) Retail - Apparel" ("region") VALUES ('X')
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_insert_select

*🛡 Writes are rejected: INSERT*

**AgentQL**

```sql
INSERT INTO "(Sample) Retail - Apparel" SELECT * FROM "(Sample) Retail - Apparel"
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_merge

*🛡 Writes are rejected: MERGE*

**AgentQL**

```sql
MERGE INTO "(Sample) Retail - Apparel" AS t USING "(Sample) Retail - Apparel" AS s ON t."region" = s."region" WHEN MATCHED THEN DELETE
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_copy_into

*🛡 Writes are rejected: COPY INTO*

**AgentQL**

```sql
COPY INTO @stage FROM (SELECT 1)
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Failed to deserialize SQL: Unsupported query type: [1:1] [*]COPY INTO @stage FROM (SELECT 1)

---

## g_cte_delete

*🛡 Writes are rejected: inside a CTE*

**AgentQL**

```sql
WITH d AS (DELETE FROM "(Sample) Retail - Apparel" RETURNING *) SELECT * FROM d
```

**Rejected — `status: UNSUPPORTED_CONDITION`** — Error Code: QUERY_GEN_ERROR Error Message: SQL validation failed with 3 error(s) Validation Errors: 1. [UNSUPPORTED_CONDITION] CTE query must be a SELECT statement: d in QUERY clause 2. [TABLE_NOT_FOUND] Table 'd' not found. in FROM clause 3. [SELECT_STAR] SELECT * is not supported. Please explicitly list columns. in SELECT clause, column 1 (near '*')

---

## g_truncate

*🛡 DDL is rejected: TRUNCATE*

**AgentQL**

```sql
TRUNCATE TABLE "(Sample) Retail - Apparel"
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_drop_table

*🛡 DDL is rejected: DROP*

**AgentQL**

```sql
DROP TABLE "(Sample) Retail - Apparel"
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_create_table

*🛡 DDL is rejected: CREATE*

**AgentQL**

```sql
CREATE TABLE x (a INT)
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_create_as

*🛡 DDL is rejected: CREATE … AS SELECT*

**AgentQL**

```sql
CREATE TABLE x AS SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_alter_table

*🛡 DDL is rejected: ALTER*

**AgentQL**

```sql
ALTER TABLE "(Sample) Retail - Apparel" ADD COLUMN x INT
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_grant

*🛡 Admin is rejected: GRANT*

**AgentQL**

```sql
GRANT SELECT ON "(Sample) Retail - Apparel" TO PUBLIC
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_call

*🛡 Admin is rejected: CALL*

**AgentQL**

```sql
CALL some_procedure()
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_use

*🛡 Admin is rejected: USE*

**AgentQL**

```sql
USE DATABASE other
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Only SELECT queries are supported for deserialization

---

## g_alter_session

*🛡 Admin is rejected: ALTER SESSION*

**AgentQL**

```sql
ALTER SESSION SET QUERY_TAG = 'x'
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Failed to deserialize SQL: Keyword 'SET CURRENT_SCHEMA' expected: [1:15] ALTER SESSION [*]SET QUERY_TAG = 'x'

---

## g_second_statement_delete

*🛡 One statement only: a second is rejected*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"; DELETE FROM "(Sample) Retail - Apparel"
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Failed to deserialize SQL: Unexpected clause: [1:71] ...es") AS s FROM "(Sample) Retail - Apparel" AS "t1"[*]; DELETE FROM "(Sample) Retail - Apparel"

---

## g_second_statement_drop

*🛡 One statement only: a second is rejected*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1"; DROP TABLE "(Sample) Retail - Apparel"
```

**Rejected — `status: QUERY_GEN_ERROR`** — Error Code: QUERY_GEN_ERROR Error Message: Failed to deserialize SQL: Unexpected clause: [1:71] ...es") AS s FROM "(Sample) Retail - Apparel" AS "t1"[*]; DROP TABLE "(Sample) Retail - Apparel"

---

## g_physical_table

*🛡 Only the Model is queryable: physical tables are rejected*

**AgentQL**

```sql
SELECT SUM("SALES") AS s FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES"
```

**Rejected — `status: TABLE_NOT_FOUND`** — Error Code: QUERY_GEN_ERROR Error Message: SQL validation failed with 2 error(s) Validation Errors: 1. [TABLE_NOT_FOUND] Table 'fact_retapp_sales' not found. in FROM clause 2. [COLUMN_NOT_FOUND] Column 'sales' not found in table '(any table)'. in SELECT clause, column 1

---

## g_information_schema

*🛡 Only the Model is queryable: information_schema is rejected*

**AgentQL**

```sql
SELECT table_name FROM information_schema.tables
```

**Rejected — `status: TABLE_NOT_FOUND`** — Error Code: QUERY_GEN_ERROR Error Message: SQL validation failed with 2 error(s) Validation Errors: 1. [TABLE_NOT_FOUND] Table 'tables' not found. in FROM clause 2. [COLUMN_NOT_FOUND] Column 'table_name' not found in table '(any table)'. in SELECT clause, column 1

---

## g_line_comment

*🛡 Comments are dropped, never passed through*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" -- ; DROP TABLE x
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
LIMIT 100000
```

---

## g_block_comment

*🛡 Comments are dropped, never passed through*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" /* ; DELETE FROM x */
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
LIMIT 100000
```

---

## g_select_into

*🛡 SELECT … INTO compiles to a plain SELECT*

**AgentQL**

```sql
SELECT "t1"."region" INTO newtab FROM "(Sample) Retail - Apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT "ta_1"."REGION" "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
LIMIT 100000
```

---

## g_literal_semicolon

*🛡 A '; DROP inside a string literal stays a value*

**AgentQL**

```sql
SELECT SUM("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" WHERE "t1"."region" = 'x''; DROP TABLE y; --'
```

**Generated SQL** (`status: SUCCESS`)

```sql
SELECT CASE
  WHEN sum("ta_1"."SALES") IS NOT NULL THEN sum("ta_1"."SALES")
  ELSE 0
END "ca_1"
FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_1"
  JOIN "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_2"
    ON "ta_1"."STOREID" = "ta_2"."STOREID"
WHERE LOWER("ta_2"."REGION") = 'x''; drop table y; --'
LIMIT 100000
```

---
