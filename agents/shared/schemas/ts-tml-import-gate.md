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

`ts tml lint` reads the same stdin shape as `ts tml import` and exits non-zero on
any finding, so it gates the import (replace `<file>`):

```bash
python3 -c "import json,pathlib; print(json.dumps([pathlib.Path('<file>').read_text()]))" | ts tml lint
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

Use `--policy PARTIAL` when importing multiple objects in a batch. `ALL_OR_NONE`
rolls back the **entire** batch if any single TML fails — including objects that
imported successfully — and the response still returns success GUIDs for the
rolled-back objects, making the failure silent. Use `ALL_OR_NONE` only for atomic
pairs (one table + one model that references it).
