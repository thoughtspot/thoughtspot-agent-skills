# Double Aggregation in Snowflake Semantic Views

## Overview

Double aggregation (also called "nested aggregation" or "metric-on-metric") is when a metric applies an aggregate function to the result of another metric. For example: the **average number of locations per company** requires first counting locations per company, then averaging those counts.

Snowflake Semantic Views support this natively by allowing one metric to reference another metric by name.

## How It Works

### The Building Blocks

A semantic view defines:

- **Tables** with primary keys and relationships (joins)
- **Metrics** — aggregate expressions anchored to a specific table

### The Pattern

```
Outer metric = AGGREGATE_FUNCTION( table_alias.inner_metric_name )
```

The engine resolves this in two steps:

1. Compute the inner metric, grouped by the join key (determined by the declared relationship)
2. Apply the outer aggregate function across those grouped results

## Worked Example

### Schema

Two tables with a many-to-one relationship:

```
PAYROLL_LOCATIONS (many) ──── PAYROLL_COMPANIES (one)
         └── joined on PAYROLL_COMPANY_ID
```

### Semantic View Definition (relevant sections)

**Tables and Relationship:**

```sql
tables (
    PAYROLL_COMPANIES primary key (PAYROLL_COMPANY_ID),
    PAYROLL_LOCATIONS primary key (PAYROLL_LOCATION_ID)
)
relationships (
    LOCATIONS_TO_COMPANIES as PAYROLL_LOCATIONS(PAYROLL_COMPANY_ID)
        references PAYROLL_COMPANIES(PAYROLL_COMPANY_ID)
)
```

**Inner Metric (first aggregation) — anchored to PAYROLL_LOCATIONS:**

```sql
PAYROLL_LOCATIONS.NUMBER_OF_LOCATIONS as COUNT(PAYROLL_LOCATION_ID)
    comment='Total number of payroll locations'
```

**Outer Metric (second aggregation) — anchored to PAYROLL_COMPANIES:**

```sql
PAYROLL_COMPANIES.AVERAGE_LOCATIONS_PER_COMPANY as AVG(payroll_locations.number_of_locations)
    comment='The average number of physical locations operated per payroll company'
```

### Execution Logic

When a user queries `AVERAGE_LOCATIONS_PER_COMPANY`:

| Step | Operation | Result |
|------|-----------|--------|
| 1 | `COUNT(PAYROLL_LOCATION_ID)` grouped by `PAYROLL_COMPANY_ID` | A count of locations for each company |
| 2 | `AVG(...)` across all companies (or filtered by query dimensions) | The average of those counts |

**Example data flow:**

| Company | Location Count (Step 1) |
|---------|------------------------|
| Acme Corp | 5 |
| Beta Inc | 3 |
| Gamma LLC | 7 |

Step 2: `AVG(5, 3, 7)` = **5.0**

### Why the Relationship Matters

The relationship declaration tells the engine *how to group* the inner metric:

```sql
LOCATIONS_TO_COMPANIES as PAYROLL_LOCATIONS(PAYROLL_COMPANY_ID)
    references PAYROLL_COMPANIES(PAYROLL_COMPANY_ID)
```

Without this, the engine wouldn't know that `NUMBER_OF_LOCATIONS` should be grouped by company before the `AVG` is applied.

## Key Rules

1. The **inner metric** must be defined on the child/many-side table (e.g., `PAYROLL_LOCATIONS`)
2. The **outer metric** is defined on the parent/one-side table (e.g., `PAYROLL_COMPANIES`)
3. The outer metric references the inner metric using `table_alias.metric_name` syntax
4. A **relationship** must exist between the two tables to define the grouping boundary

## Translating to ThoughtSpot

ThoughtSpot does not support metric-referencing-metric in the same declarative way. There are two implementation approaches:

### Option A: Pre-aggregated Column (Recommended)

Create a view or dynamic table that pre-computes the inner metric at the company grain, then use a simple aggregate formula in ThoughtSpot.

**SQL (view or dynamic table):**

```sql
SELECT
    c.*,
    loc_counts.number_of_locations
FROM PAYROLL_COMPANIES c
LEFT JOIN (
    SELECT PAYROLL_COMPANY_ID, COUNT(PAYROLL_LOCATION_ID) as NUMBER_OF_LOCATIONS
    FROM PAYROLL_LOCATIONS
    GROUP BY PAYROLL_COMPANY_ID
) loc_counts ON c.PAYROLL_COMPANY_ID = loc_counts.PAYROLL_COMPANY_ID
```

**ThoughtSpot formula:**

```
average ( number_of_locations )
```

**Pros:** Simple, performant, easy for users to understand in search.

### Option B: group_aggregate Formula

Use ThoughtSpot's `group_aggregate` function to perform the inner aggregation inline.

**ThoughtSpot formula:**

```
average ( group_aggregate ( count ( payroll_location_id ), { payroll_company_id }, {} ) )
```

**Pros:** No physical table changes needed.
**Cons:** More complex, harder for users to understand, may confuse Spotter/AI features.

## Summary

| Concept | Semantic View | ThoughtSpot (Option A) | ThoughtSpot (Option B) |
|---------|--------------|----------------------|----------------------|
| Inner aggregation | Metric on child table | Pre-computed column | `group_aggregate(count(...), {group_key}, {})` |
| Outer aggregation | Metric referencing inner metric | Simple formula: `average(column)` | Wrapped in `average(...)` |
| Join/grouping | Declared relationship | JOIN in view definition | `{payroll_company_id}` in group_aggregate |
