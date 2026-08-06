# Prototype path: a ThoughtSpot SQL View instead of warehouse DDL

**Use this to show someone the shape of the solution when you cannot run DDL. Do not ship
it.** The end state must be a warehouse change — the reasons are at the bottom, with the
generated SQL that demonstrates them.

A ThoughtSpot SQL View is a query-backed logical table: it runs raw SQL against the
connection and exposes the result columns. It needs **no `CREATE` privilege on the
warehouse**, only ThoughtSpot authoring rights. That makes it the fastest way to put a
working period-over-period model in front of someone.

Live-verified end to end: a SQL View computing the offset column, joined from an aliased
fact, returned the correct prior-period numbers to the cent.

---

## 1. Create the SQL View with the offset column

The computed `DATE_364_DAYS_AGO` is the whole point — it is the key the offset alias joins.

```yaml
sql_view:
  name: DIM_DATE_OFFSET_SQLVIEW
  description: >-
    PROTOTYPE ONLY. Date dimension with a 364-day offset key computed in SQL so no
    warehouse DDL is required. Replace with a real warehouse view before production.
  connection:
    name: {connection_name}
  sql_query: |
    SELECT "date"::DATE AS DATE_VALUE,
           DATEADD(day, -364, "date")::DATE AS DATE_364_DAYS_AGO,
           DATE_TRUNC('week', "date")::DATE AS START_OF_WEEK
    FROM {db}.{schema}.{date_table}
  sql_view_columns:
  - name: DATE_VALUE
    sql_output_column: DATE_VALUE
    properties: { column_type: ATTRIBUTE, index_type: DONT_INDEX }
  - name: DATE_364_DAYS_AGO
    sql_output_column: DATE_364_DAYS_AGO
    properties: { column_type: ATTRIBUTE, index_type: DONT_INDEX }
  - name: START_OF_WEEK
    sql_output_column: START_OF_WEEK
    properties: { column_type: ATTRIBUTE, index_type: DONT_INDEX }
```

```bash
ts tml import --file dim_date_offset.sql_view.tml --policy ALL_OR_NONE --profile {profile}
```

Note the `sql_view_columns[].sql_output_column` mapping — it is **not** `column_id`, which
is the `view:` (AGGR_WORKSHEET) spelling for a different object type.

---

## 2. Join the alias to it

A SQL View is a `LOGICAL_TABLE`, so a Model joins it exactly like a Table — including as
the target of a role-played alias. Reference it by `fqn` (its GUID) and by name in `with:`:

```yaml
- name: DM_ORDER
  alias: DM_ORDER_364_DAYS_AGO
  fqn: {order_table_guid}
  joins:
  - name: ORDER_364_TO_DATE_OFFSET
    with: DIM_DATE_OFFSET_SQLVIEW
    'on': '[DM_ORDER::ORDER_DAY] = [DIM_DATE_OFFSET_SQLVIEW::DATE_364_DAYS_AGO]'
    type: LEFT_OUTER
    cardinality: MANY_TO_ONE
```

Everything else — alias naming, the trimmed column set, the measures, the verification
gates — is identical to the main recipe.

---

## 3. Tell the user, explicitly, that this is a prototype

Say it when you hand it over, not only in a doc:

> This demonstrates the shape and the numbers are correct. Before production the offset
> column should move into the warehouse, because ThoughtSpot inlines a SQL View as an
> unfiltered subquery and the definition is invisible to everything outside this Model.

---

## Why it is not production

### It is inlined unfiltered, once per join role

This is the actual SQL ThoughtSpot generated for a two-role period-over-period question:

```sql
LEFT OUTER JOIN (SELECT "date"::DATE AS DATE_VALUE,
       DATEADD(day, -364, "date")::DATE AS DATE_364_DAYS_AGO,
       DATE_TRUNC('week', "date")::DATE AS START_OF_WEEK
 FROM DUNDERMIFFLIN.PUBLIC."dm_date"
) "ta_1"
  ON "MTA_0"."DM_ORDER_ORDER_DAY" = "ta_1"."DATE_VALUE"
WHERE "ta_1"."START_OF_WEEK" IN ('2019-06-03', '2019-06-10')
```

Two things to notice:

1. **The derived table has no `WHERE` of its own.** ThoughtSpot cannot parse the inner SQL,
   so it cannot push the predicate into it. The filter is applied *outside* the black box.
   You are relying entirely on the warehouse optimiser to rescue it by pushing the
   predicate into a derived table. Snowflake usually will for a small calendar; on a large
   table, or a less capable engine, it will not — and there is no partition pruning to fall
   back on.
2. **It appears twice.** The same block is inlined once per join role (`qt_0` and `qt_1`),
   so the black-box scan happens once per alias, every query.

### The definition is stranded in a BI object

The offset key is business logic. Inside a SQL View it is:

- invisible to every other Model, tool and consumer of the same warehouse,
- not version-controlled or tested alongside the warehouse code,
- impossible to cluster, materialise or index,
- duplicated the moment a second model needs the same comparison.

A warehouse view costs one `CREATE OR REPLACE VIEW` and removes all four problems.

---

## Promoting to production

1. Run Section 2 (augment) of [date-dimension-ddl.sql](date-dimension-ddl.sql) to add the
   offset column to the real calendar.
2. Point the alias joins at the warehouse-backed Table object instead of the SQL View.
   Because a column rename/repoint on a live Model is delete + add, the sequence is
   **add the new Table column → rebuild the Model against it → remove the SQL View.**
3. Re-run the Step 9 verification gates. The numbers must be unchanged — if they move,
   the warehouse column and the SQL View expression disagree.
4. Delete the SQL View so nobody builds on the prototype.
