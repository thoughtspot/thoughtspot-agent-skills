# Smoke Tests

End-to-end tests that verify full skill workflows. These are self-contained scripts, not
pytest tests — they have their own runners and the live ones have side effects.

**Not all of them need credentials.** The README said "require live credentials" as a
blanket statement until 2026-08-26 (audit finding 6.7); **9 of the 21 do not**, and five
tracked files were missing from the table entirely, making them invisible to anyone
auditing coverage from the docs. There are three tiers, not two:

| Tier | Needs | Runs in CI |
|---|---|---|
| **Pure** | nothing — plain Python | Yes, five of them (see `.github/workflows/validate.yml`) |
| **CLI-only** | `ts` on `PATH`, **no credentials** | No (could) |
| **Live** | `ts` + a configured profile for the named platform(s) | No |

Every classification below was verified by running the script, not inferred from its
imports — an import-based guess mislabels both directions (`smoke_ts_convert_from_qlik`
imports `run_ts` yet needs no credentials; it just needs the CLI installed).

## Scripts

| Script | Skill | Tier |
|---|---|---|
| `smoke_ts_publish_orgs.py` | ts-publish-orgs | Pure |
| `smoke_ts_security_columns.py` | ts-security-columns | Pure |
| `smoke_ts_setup_tenancy.py` | ts-setup-tenancy | Pure |
| `smoke_ts_migrate_orgs.py` | ts-migrate-orgs | Pure |
| `smoke_ts_object_model_alias.py` | ts-object-model-alias | Pure |
| `smoke_ts_object_model_erd.py` | ts-object-model-erd | Pure |
| `smoke_ts-convert-to-databricks-mv.py` | ts-convert-to-databricks-mv (codified emitter) | Pure (`--live` opts in) |
| `smoke_ts_convert_from_qlik.py` | ts-convert-from-qlik | CLI-only |
| `smoke_ts_load_source_data.py` | ts-load-source-data | CLI-only |
| `smoke_ts_to_snowflake.py` | ts-convert-to-snowflake-sv | Live (TS + SF) |
| `smoke_ts_from_snowflake.py` | ts-convert-from-snowflake-sv | Live (TS + SF) |
| `smoke_ts_to_databricks.py` | ts-convert-to-databricks-mv | Live (TS + DBX) |
| `smoke_ts_from_databricks.py` | ts-convert-from-databricks-mv | Live (TS + DBX) |
| `smoke_ts_dependency_manager.py` | ts-dependency-manager | Live (TS) |
| `smoke_ts_audit.py` | ts-audit | Live (TS) |
| `smoke_ts_object_model_coach.py` | ts-object-model-coach | Live (TS) |
| `smoke_ts_object_model_aggregates.py` | ts-object-model-aggregates | Live (TS + SF) |
| `smoke_ts_object_model_agentql_query.py` | ts-object-model-agentql-query | Live (TS) |
| `smoke_ts_variable_timezone.py` | ts-variable-timezone | Live (TS) |
| `smoke_ts_recipe_formula_business_days_snowflake.py` | ts-recipe-formula-business-days-snowflake | Live (SF) |
| `smoke_ts_recipe_formula_hms_display_snowflake.py` | ts-recipe-formula-hms-display-snowflake | Live (SF) |

`_common.py` is shared helpers, not a suite.

### Running the credential-free ones

```bash
# Pure — nothing but Python
python tools/smoke-tests/smoke_ts_publish_orgs.py

# CLI-only — needs `ts` installed (pip install -e tools/ts-cli), no profile
python tools/smoke-tests/smoke_ts_convert_from_qlik.py
```

The Prerequisites below apply to the **Live** tier only.

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
