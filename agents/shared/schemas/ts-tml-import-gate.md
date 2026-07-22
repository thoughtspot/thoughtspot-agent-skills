<!-- currency: thoughtspot — 2026-07 (inaugural anchor; extracted from ts-convert-from-databricks-mv / ts-convert-from-snowflake-sv, BL-063 PR5; verify in next external sweep) -->

# Pre-import lint gate + TML import procedure

Canonical procedure for importing generated Model (+ Table) TML into ThoughtSpot.
Extracted from ts-convert-from-databricks-mv / ts-convert-from-snowflake-sv
(BL-063 PR 5) — skills link here instead of repeating it.

Invariant definitions: [`ts-model-conversion-invariants.md`](ts-model-conversion-invariants.md).

## 1. Lint before every import (`ts tml lint`)

Lint the generated **Model** TML before `ts tml import` — a parser-based check of
the hard invariants that `--policy VALIDATE_ONLY` does **not** catch (ThoughtSpot
accepts the TML and then behaves wrong, or rejects it on import):

- **I1** — every `formulas[]` entry has a paired `columns[]` entry (`formula_id:` == `id:`). *(Unpaired formula silently dropped.)*
- **I2** — no `aggregation:` inside any `formulas[]` entry. *(Raises "FORMULA is not a valid aggregation type".)*
- **I4** — every `model_tables[]` `id:` (when present) equals its `name:`. *(Mismatch makes joins silently fail.)*
- **I5** — no physical-column `aggregation: COUNT_DISTINCT`; use a `unique count ( [TABLE::col] )` formula. *(Silently flips MEASURE → ATTRIBUTE.)*
- **I8** — no duplicate `column_id` across `columns[]`. *(Hard import rejection: "columns should have unique column_id values".)*

`ts tml lint` reads raw TML file paths via `--file`/`--dir` (the same input `ts tml
import` takes) and exits non-zero on any finding, so it gates the import (replace
`<file>` / `<dir>`):

```bash
ts tml lint --file <file>          # one TML file
ts tml lint --dir <dir>            # every *.tml in a directory
```

Do not import until it reports `"clean": true`. Fix any finding and re-lint.
Automated builders (`ts databricks build-model`, the Genie `databricks_mv_lib`
notebook) already run these checks on what they write — re-lint whenever a TML
file has been hand-edited afterwards.

## 2. Updating vs creating (`guid` placement)

Without a `guid`, ThoughtSpot always creates a **new** object — even when a model
with the same name exists. To update in place, put the existing model's GUID at
the **document root**, alongside `model:` — a `guid:` nested inside `model:` is
silently ignored. On first import omit it; **record the returned GUID** — it is
required for any future update.

## 3. Import policy

Import the linted TML with `ts tml import` — same `--file`/`--dir` input as the
lint gate:

```bash
ts tml import --file <file> --policy PARTIAL      # one object
ts tml import --dir <dir> --policy PARTIAL        # a batch
```

| Policy | Behaviour |
|---|---|
| `PARTIAL` | Imports whole objects that validate; skips entire objects that fail. **Default for batch imports.** |
| `ALL_OR_NONE` | Rolls back the **entire** batch if any single TML fails — including objects that imported successfully — and the response still returns success GUIDs for the rolled-back objects, making the failure silent. Use only for atomic pairs (one table + one model that references it). |
| `PARTIAL_OBJECT` | Like `PARTIAL`, but also allows **sub-component** failures within an object. A Liveboard imports even if one visualization fails; a Table imports even if a join/relationship fails. Warnings appear in the API response. REST API v2 only (10.5.0.cl+). |
| `VALIDATE_ONLY` | Validates the objects but does not import them. Useful for dry-run checks — but does **not** catch the hard invariants in §1–§2 above. |

## 4. Common import errors

On `import_status: "failed"`, read `import_error` and consult this table:

| Error | Likely cause | Fix |
|---|---|---|
| `referencing_join not found` | Join name is wrong or join doesn't exist at table level | Export Table TML and verify join name |
| `column_id not found` | Column name in model TML doesn't match any column in the referenced Table TML (e.g. source dimension name used instead of ThoughtSpot column name) | Export Table TML and verify column names |
| `Compulsory Field … joins(N)->with is not populated` | Missing `with` field on an inline join | Add `with: {target_id}` to every inline join entry |
| `{table_name} does not exist in schema` (on `with` field) | `with` value doesn't match any `id` in model_tables | Ensure `with` matches the target's `id` exactly — same case as `name` |
| `Invalid srcTable or destTable in join expression` | `on` clause references a table name that doesn't match any `id` in model_tables | Check that both `[table::col]` refs in `on` use `id` values |
| `Multiple tables have same alias {name}` | Two model_tables entries have the same `name` value | Deduplicate — keep only one entry |
| `fqn resolution failed` | GUID is stale or from a different ThoughtSpot instance | Re-fetch GUIDs from the current instance |
| `formula syntax error` | ThoughtSpot formula has invalid syntax | Fix the formula expression |
| YAML mapping error on formula with `{` | Formula with `{ [col] }` emitted as inline YAML string | Use block scalar (`>-`) for formula expressions containing `{`; CLI YAML emitters handle this automatically — arises in hand-edited TML |
| YAML parse error | Non-printable characters in strings | Strip non-printable chars from all string values before serialising |

## 5. Post-import verification

After a successful import response, confirm the model was indexed and has the
expected shape — not just that the API returned 200.

**1. Search for the model by GUID:**

```bash
ts metadata search --subtype WORKSHEET --name "%{model_name}%" --profile {profile}
```

The GUID returned by the import response must appear in the results. If it is
absent, the import succeeded at the API level but indexing is delayed — wait
5 seconds and retry once.

**2. Export the imported model and count columns:**

```bash
ts tml export {created_guid} --fqn --profile {profile}
```

Parse the returned TML and count `model.columns[]` entries. This count must be
>= the number of translatable fields from the source (total dimensions + measures,
minus any entries skipped during translation).

If the column count is lower than expected: compare the exported TML against the
TML sent at import time to identify which columns ThoughtSpot silently dropped,
and investigate.

**3. Report the model URL:**

```
Model imported successfully.

  Name:    {model_name}
  GUID:    {created_guid}
  URL:     {base_url}/#/model/{created_guid}

Open the URL in a browser to verify the model appears in the ThoughtSpot Data panel.
```
