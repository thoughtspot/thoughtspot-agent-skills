# Known-bad TML fixture (for test_known_bad_fixtures.py)

This block is deliberately invalid: a FULL_OUTER join (rejected in model TML) and
an AVG aggregation (TS uses AVERAGE). check_tml must exit non-zero on it.

```yaml
model:
  name: Bad Model
  model_tables:
    - name: FACT_ORDERS
      joins:
        - name: to_dim
          type: FULL_OUTER
          "on": "[FACT_ORDERS::dim_id] = [DIM::id]"
    - name: DIM
  columns:
    - name: Avg Price
      column_id: FACT_ORDERS::price
      properties:
        column_type: MEASURE
        aggregation: AVG
  formulas: []
```
