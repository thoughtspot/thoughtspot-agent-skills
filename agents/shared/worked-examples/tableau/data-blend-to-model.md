# Data Blend → Single Model (Worked Example)

Demonstrates converting a Tableau workbook with two blended datasources into a single
ThoughtSpot model with an inline join.

## Source: Dual Axis Example (TWB)

Two datasources:
- **Orders** (primary): `ORDERS` table with columns `Category`, `Order Date`, `Sales`, `Profit`
- **Targets** (secondary): `TARGETS` table with columns `Category`, `Month of Order Date`, `Target`

Blend relationship (from `<datasource-relationships>`):
- Source: `federated.xxx` (Orders) → Target: `federated.yyy` (Targets)
- Linking columns: `Category` = `Category`, `Order Date` (Month) = `Month of Order Date` (Month)

Cross-datasource formula in a worksheet:

```
SUM([Sales]) - SUM([federated.yyy].[Target])
```

## Step 3e Output: blend_graph

```python
blend_graph = {
    'federated.xxx': [{
        'target_ds': 'federated.yyy',
        'column_mappings': [
            {'source_col': 'Category', 'target_col': 'Category'},
            {'source_col': 'Order Date', 'target_col': 'Month of Order Date'},
        ],
    }]
}
```

## Step 5b Output: Merged Model TML

```yaml
model:
  name: Orders

  model_tables:
  - name: ORDERS
  - name: TARGETS
    joins:
    - with: ORDERS
      'on': "[TARGETS::Category] = [ORDERS::Category] and [TARGETS::Month of Order Date] = [ORDERS::Order Date]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE

  columns:
  - name: Category
    column_id: ORDERS::Category
    properties:
      column_type: ATTRIBUTE
  - name: Order Date
    column_id: ORDERS::Order Date
    properties:
      column_type: ATTRIBUTE
  - name: Sales
    column_id: ORDERS::Sales
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
  - name: Profit
    column_id: ORDERS::Profit
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
  - name: Target
    column_id: TARGETS::Target
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
  - name: Sales vs Target
    formula_id: formula_sales_vs_target
    properties:
      column_type: MEASURE
      index_type: DONT_INDEX

  formulas:
  - id: formula_sales_vs_target
    name: Sales vs Target
    expr: "sum ( [ORDERS::Sales] ) - sum ( [TARGETS::Target] )"
```

## Key Decisions

| Decision | Rationale |
|---|---|
| `LEFT_OUTER` join type | Tableau blends are always LEFT JOINs (primary drives, secondary contributes) |
| `MANY_TO_ONE` cardinality | Targets is a reference/dimension table (one target per category); override to `MANY_TO_MANY` if both sides are fact-level |
| No pre-aggregated SQL view | ThoughtSpot's chasm trap protection aggregates each fact independently — keep tables at line level |
| Cross-ds formula → model formula | Both tables are in the same model, so `SUM([Sales]) - SUM([Targets].[Target])` resolves directly as `sum([ORDERS::Sales]) - sum([TARGETS::Target])` |
| Join on TARGETS entry | Join is defined on the secondary (TARGETS) table's `model_tables` entry, joining `with: ORDERS` (the primary) |

## Limitations

- Date-grain linking (`Month` derivation) requires the physical column to be joinable at
  the same grain. If `Order Date` is a full date and `Month of Order Date` is already
  month-truncated, the join works. If both are full dates with different truncations, a
  SQL View may be needed to materialize the truncated column.
- Star topologies (1 primary → N secondaries) produce N joins — one per secondary, each
  on the secondary's `model_tables` entry. All are `LEFT_OUTER`.
