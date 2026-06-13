# Known-bad anti-pattern fixture (for test_known_bad_fixtures.py)

This connection block uses `fqn:` instead of `name:` — check_patterns must flag it.

```yaml
table:
  name: ORDERS
  connection:
    fqn: a1b2c3d4-0000-0000-0000-000000000000
    name: My Snowflake
  columns:
    - name: id
      db_column_name: id
```
