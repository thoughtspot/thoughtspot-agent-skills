# Smoke Tests

Live end-to-end tests that verify the full skill workflows against real ThoughtSpot and
Snowflake instances. These are self-contained scripts, not pytest tests — they have side
effects and require live credentials.

## Scripts

| Script | Tests |
|---|---|
| `smoke_ts_to_snowflake.py` | SV YAML validation → dry-run → create → SHOW → SELECT → cleanup |
| `smoke_ts_from_snowflake.py` | GET_DDL → parse DDL → find TS tables → import model → verify → cleanup |
| `smoke_ts_dependency_manager.py` | auth → resolve model → `ts dependency backup` → (opt-in) `ts dependency apply-change` → `ts dependency rollback --only updates` → cleanup |

## Prerequisites

1. **ThoughtSpot profile** — configured via `/ts-profile-thoughtspot`. Check with:
   ```bash
   ts auth whoami --profile <name>
   ```

2. **Snowflake profile** — configured via `/ts-profile-snowflake`. Must use `method: cli`
   (Snowflake CLI connection). Check with:
   ```bash
   snow connection test -c <connection_name>
   ```

3. **Python dependencies**:
   ```bash
   pip install PyYAML
   ```

## Usage

### ts-to-snowflake (create a Semantic View from the worked example)

```bash
python tools/smoke-tests/smoke_ts_to_snowflake.py \
    --ts-profile production \
    --sf-profile production \
    --sf-target-db ANALYTICS \
    --sf-target-schema PUBLIC_SMOKE_TEST

# Optionally verify TML export from a known ThoughtSpot model:
python tools/smoke-tests/smoke_ts_to_snowflake.py \
    --ts-profile production \
    --sf-profile production \
    --sf-target-db ANALYTICS \
    --sf-target-schema PUBLIC_SMOKE_TEST \
    --ts-model-name "Retail Sales"

# Keep the created view for manual inspection:
python tools/smoke-tests/smoke_ts_to_snowflake.py ... --no-cleanup
```

### ts-from-snowflake (import a ThoughtSpot model from a Semantic View)

```bash
python tools/smoke-tests/smoke_ts_from_snowflake.py \
    --ts-profile production \
    --sf-profile production \
    --sv-fqn "BIRD.SUPERHERO_SV.BIRD_SUPERHEROS_SV"
```

### ts-dependency-manager (BL-083 `ts dependency` command surface)

```bash
# Safe legs only (default): ts dependency backup + rollback --only updates (idempotent no-op)
python tools/smoke-tests/smoke_ts_dependency_manager.py \
    --ts-profile production \
    --model-name "Retail Sales"

# Keep backup for manual inspection:
python tools/smoke-tests/smoke_ts_dependency_manager.py \
    --ts-profile production \
    --model-name "Retail Sales" \
    --no-cleanup

# Opt in to the DESTRUCTIVE apply-change leg (removes real columns — use a disposable model):
python tools/smoke-tests/smoke_ts_dependency_manager.py \
    --ts-profile production \
    --model-name "Disposable Model" \
    --run-apply-change --apply-change-columns "Col A,Col B"
```

The test exercises the real `ts dependency backup` / `apply-change` / `rollback` subcommands
(BL-083). `backup` (TML export only) and `rollback --only updates` (re-import of the unchanged
backed-up TML) are non-destructive and run by default; the destructive `apply-change` leg is
gated behind `--run-apply-change` (plus `--apply-change-columns`) and is skipped unless opted in.

## Output

Each script prints a step-by-step report:

```
============================================================
Smoke test: ts-convert-to-snowflake-sv
============================================================
  ThoughtSpot profile:  production
  Snowflake profile:    production
  SV YAML source:       agents/shared/worked-examples/...
  Target:               ANALYTICS.PUBLIC_SMOKE_TEST

  Load Snowflake profile...                       [PASS]
  ThoughtSpot auth (ts auth whoami)...            [PASS]
        Authenticated as: Damian Waldron
  Extract SV YAML from .md file...                [PASS]
        View name: retail_sales
  Structural validation (check_sv_yaml)...        [PASS]
  ...

  All required steps passed.
```

## Cleanup

All smoke tests drop/delete their test objects by default. Use `--no-cleanup` to keep
created objects for manual inspection. Always clean up manually if you interrupt a test
mid-run.

## Interpreting failures

| Error | Cause | Fix |
|---|---|---|
| `ts auth whoami failed` | Bad profile or expired token | Run `ts auth logout --profile <name>` then retry |
| `Structural validation … N error(s)` | Worked example has invalid YAML structure | Fix the worked example or the validator |
| `Dry-run … returned error` | YAML would fail SYSTEM$CREATE call | Check error code (392700 = data_type on metric) |
| `SHOW SEMANTIC VIEWS returned no row` | CREATE succeeded but view not visible | Check Snowflake role permissions on the target schema |
| `SELECT … LIMIT 1 failed` | View created but not queryable by Cortex | Error 392700 = bad field; check error message |
| `Connection 'X' not found` | Connection name mismatch | Run `ts connections list --type SNOWFLAKE --profile <name>` to see available names |
