<!-- GENERATED FILE — do not edit by hand.
     Regenerate (needs a live cluster for the capture, then offline for the build):
       python3 tools/agentql-retest/run.py --profile <profile> --suite lessons guards --out /tmp/cap.json
       python3 tools/agentql-retest/build_lesson_sql.py --from /tmp/cap.json
-->
# Captured warehouse SQL — Learn AgentQL lessons

The exact warehouse SQL ThoughtSpot compiled (`executable_sql`) for every course lesson,
captured live on the sample Model **`(Sample) Retail - Apparel`** (the SE demo cluster) on
2026-10-20. **Offline mode shows these verbatim in section 3** — a lesson should never reconstruct
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
SELECT "t1"."region" AS x FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region" UNION ALL SELECT SUM("t1"."sales") AS x FROM "(Sample) Retail - Apparel" AS "t1"
```

**Generated SQL** (`status: SUCCESS`)

```sql
WITH 
  "qt_0" AS (
    SELECT "ta_1"."REGION" "ca_1"
    FROM "RETAILAPPAREL"."PUBLIC"."DIM_RETAPP_STORES" "ta_1"
    GROUP BY "ca_1"
  ), 
  "qt_1" AS (
    SELECT CASE
      WHEN sum("ta_2"."SALES") IS NOT NULL THEN sum("ta_2"."SALES")
      ELSE 0
    END "ca_2"
    FROM "RETAILAPPAREL"."PUBLIC"."FACT_RETAPP_SALES" "ta_2"
  )
(
  SELECT *
  FROM "qt_0"
)
UNION ALL (
  SELECT *
  FROM "qt_1"
)
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

## l3_agg_on_raw_measure_rejected

*📘 3.4 formula measures: AGG, not SUM (break it)*

**AgentQL**

```sql
SELECT "t1"."region" AS r, AGG("t1"."sales") AS s FROM "(Sample) Retail - Apparel" AS "t1" GROUP BY "t1"."region"
```

**Rejected — `status: QUERY_GEN_ERROR`** — Failed to transform QuerySpec: Error Code: QUERY_GEN_ERROR Error Message: Failed validation for GroupAggregateOptimizationTransformer: All non-constant columns should be grouped by or aggregated in a query. id { guid: "…" name: "SQL Query" } column { id { guid: "…" name: "REGION" } output_id { guid: "…" name: "r" } column_type: ATTRIBUTE data_type: CHAR } column { id { guid: "…" name: "SALES" } ou …

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
