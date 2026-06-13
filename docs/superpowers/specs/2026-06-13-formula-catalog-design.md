# Formula Catalog — Design Spec

**Date:** 2026-06-13
**Status:** Draft — design approved, ready for implementation planning

## Problem

TS-side facts (function existence, syntax, behavior) are restated independently
in four files:

- `agents/shared/schemas/thoughtspot-formula-patterns.md` (the intended authority)
- `agents/shared/mappings/tableau/tableau-formula-translation.md`
- `agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md`
- `agents/shared/mappings/ts-databricks/ts-databricks-formula-translation.md`

Each mapping file has its own scalar function tables (Math, String, Date, Type
Conversion) that restate what TS functions exist and how they're spelled. These
restatements drift — the 2026-06-13 audit found `pow`/`power`, `upper`/`lower`,
`date_trunc`, `day_number_of_month`, and `rank` semantics contradicted across
files. Fixing each correction required touching 3-4 files and sweeping for
stragglers.

The problem worsens with each new platform. Adding a BigQuery or Redshift mapping
would create another copy of these facts.

## Solution

Separate scalar function mappings (1:1 translations) from complex translation
patterns (LOD, window functions, pass-through, semi-additive). Scalar mappings
move to a single catalog in `thoughtspot-formula-patterns.md` with platform columns.
Complex patterns stay in platform-specific mapping files.

### What moves to the catalog

The catalog covers functions where the TS→Platform translation is a simple
function-name swap with no structural change:

- **Math:** `pow`, `abs`, `ceil`, `floor`, `round`, `mod`, `sqrt`, `ln`, `log2`,
  `log10`, `safe_divide`, `least`, `greatest`
- **String:** `concat`, `substr`, `strlen`, `strpos`, `left`, `right`, `trim`,
  `replace`, `contains`, `starts_with`, `ends_with`, `upper` (pass-through),
  `lower` (pass-through)
- **Date (extraction):** `year`, `month`, `month_number`, `day`,
  `day_number_of_week`, `day_number_of_quarter`, `day_number_of_year`,
  `day_of_week`, `hour_of_day`, `quarter_number`, `week_number_of_year`,
  `month_number_of_quarter`, `is_weekend`
- **Date (manipulation):** `today`, `now`, `date`, `time`, `start_of_month`,
  `start_of_quarter`, `start_of_week`, `start_of_year`, `start_of_hour`,
  `start_of_min`, `add_days`, `add_weeks`, `add_months`, `add_years`,
  `add_minutes`, `add_seconds`, `diff_days`, `diff_weeks`, `diff_months`,
  `diff_quarters`, `diff_years`, `diff_time`, `diff_hours`, `diff_minutes`
- **Type conversion:** `to_integer`, `to_double`, `to_string`, `to_date`
- **Conditional:** `if/then/else`, `isnull`, `isnotnull`, `ifnull`, `nullif`,
  `not`, `and`, `or`, `in`, `between`
- **Aggregate:** `sum`, `count`, `unique count`, `average`, `min`, `max`,
  `median`, `stddev`, `variance`, conditional `*_if` variants

### What stays in platform mapping files

Complex translation patterns that differ structurally per platform:

- **Window functions:** `cumulative_*`, `moving_*` — different SQL OVER clause
  construction per platform
- **LOD functions:** `group_aggregate`, `group_sum`, etc. — Snowflake uses
  `PARTITION BY EXCLUDING`, Databricks uses subqueries
- **Semi-additive:** `last_value`, `first_value`, `last_value_in_period` —
  different windowing patterns
- **Rank:** `rank`, `rank_percentile` — partitioned rank requires pass-through
- **Pass-through functions:** `sql_*_op` family — inherently platform-specific
- **Parameter references** — untranslatable, platform-specific handling
- **Tableau-specific patterns:** aggregation stripping for cumulative/moving,
  division-by-zero guards, date column rules, set conversions

### Catalog table format

Each existing function table in formula-patterns.md gains platform columns:

```markdown
## Math Functions

| Function | TS Syntax | Snowflake | Databricks | Tableau | Notes |
|---|---|---|---|---|---|
| `pow` | `pow ( [x] , [n] )` | `POWER(x, n)` | `POWER(x, y)` | `POWER(x, n)` | Verified 2026-06-13 |
| `safe_divide` | `safe_divide ( [a] , [b] )` | `DIV0(a, b)` | `COALESCE(a / NULLIF(b, 0), 0)` | — | Returns 0 on zero divisor |
| ~~`upper`~~ | does not exist | `UPPER(x)` | `UPPER(s)` | `UPPER(s)` | Use `sql_string_op("UPPER({0})", [x])` pass-through |
```

**Column semantics:**
- **Function:** TS function name. `~~strikethrough~~` = does not exist.
- **TS Syntax:** canonical ThoughtSpot syntax with spacing conventions.
- **Snowflake / Databricks / Tableau:** the equivalent SQL expression on that
  platform. `—` = no mapping (function doesn't apply to this platform's conversion).
- **Notes:** platform-specific caveats. Brief — one line. Complex caveats
  (e.g. INT truncation composite) get a footnote reference to the platform mapping.

**Non-existent function rows:** Functions that DON'T exist in TS but are commonly
expected (upper, lower, date_trunc, day_number_of_month) get explicit rows with
strikethrough and the pass-through or alternative. This prevents future contributors
from adding them to mapping files.

### Platform mapping file changes

Each mapping file's scalar function sections (Math, String, Date, Type Conversion)
are replaced with a single reference block:

```markdown
## Scalar Functions

For all scalar function mappings (math, string, date, type conversion, conditional,
aggregate), see the platform catalog in
[../../schemas/thoughtspot-formula-patterns.md](../../schemas/thoughtspot-formula-patterns.md).

The Snowflake column in each table provides the translation. Do NOT duplicate
scalar function rows in this file — the catalog is the single source of truth.

**Snowflake-specific notes not in the catalog:**
- `POSITION('val' IN x)` — Snowflake uses `IN` keyword; TS `strpos` uses comma
- `SUBSTR` indexing — Snowflake is 1-based; TS `substr` is 0-based
```

The "platform-specific notes" block captures any translation nuance too detailed
for the catalog's Notes column. These are about the platform SQL behavior, not
about what TS functions exist.

### Tableau mapping specifics

The Tableau mapping differs from Snowflake/Databricks:
- It's one-directional (Tableau → TS)
- Rows carry Tableau-context notes ("Tableau overloads + for concat")
- Some mappings are composites (INT → floor/ceil composite)

For the catalog: the Tableau column contains the Tableau function name that maps
to each TS function. The Notes column carries brief Tableau caveats. Complex
Tableau-specific patterns (the INT composite, division-by-zero guard, date column
rules, set conversion, aggregation stripping) remain in
`tableau-formula-translation.md` under their existing sections.

The Tableau file's current scalar tables (~40 rows covering UPPER, LOWER, POWER,
ABS, LEN, etc.) are removed and replaced with the reference block.

---

## Validator: check_formula_catalog.py

A new pre-commit validator that enforces catalog consistency.

### What it checks

1. **Catalog parse:** reads formula-patterns.md, extracts every function name from
   the catalog tables. Builds a set of valid TS function names and a set of
   "does not exist" function names (strikethrough rows).

2. **Mapping file scan:** for each mapping file (`tableau-formula-translation.md`,
   `ts-snowflake-formula-translation.md`, `ts-databricks-formula-translation.md`),
   scans for TS function references (patterns like `function_name ( ` or
   `function_name(` at the start of a table cell or in inline code).

3. **Contradiction check:**
   - A mapping file uses a function name that's in the "does not exist" set → ERROR
   - A mapping file uses a function name not in the catalog at all → WARNING
     (may be a complex pattern function that legitimately lives only in the mapping)
   - A mapping file has a scalar function table section (Math/String/Date/Type
     headers with `|---|` table format) → ERROR ("scalar tables belong in catalog")

4. **Completeness check:** every platform column in the catalog has a value for
   every function (either a SQL expression or explicit `—`). No blank cells.

### Integration

- Runs in pre-commit hook when any file in `agents/shared/mappings/` or
  `agents/shared/schemas/thoughtspot-formula-patterns.md` is staged.
- Also runs via `python3 tools/validate/check_formula_catalog.py --all` for
  full-repo checks.
- Added to `.github/workflows/validate.yml`.

### Test coverage

Unit tests in `tools/validate/tests/test_formula_catalog.py`:

| Test | What it verifies |
|---|---|
| `test_parse_catalog` | Extracts function names and platform mappings from a fixture |
| `test_nonexistent_detected` | Strikethrough rows are correctly parsed as "does not exist" |
| `test_contradiction_flagged` | A mapping file using a non-existent function is caught |
| `test_unknown_function_warned` | A function not in catalog triggers a warning |
| `test_scalar_table_flagged` | A mapping file with its own scalar table section is caught |
| `test_blank_cell_flagged` | Missing platform value in catalog is caught |
| `test_complex_patterns_allowed` | Functions like `cumulative_sum`, `group_aggregate` in mapping files are not flagged (they're complex patterns, not scalar) |

---

## Databricks mapping corrections (discovered during design)

The Databricks mapping has additional TS function name errors beyond what the
audit found:

| Current (wrong) | Correct | Source |
|---|---|---|
| `upper(s)` | does not exist (pass-through) | Verified P4 |
| `lower(s)` | does not exist (pass-through) | Verified P4 |
| `day_of_month(d)` | `day(d)` | Verified P8 |
| `hour(ts)` | `hour_of_day(ts)` | Official TS docs |
| `minute(ts)` | not a TS function | Official TS docs |
| `second(ts)` | not a TS function | Official TS docs |
| `quarter(d)` | `quarter_number(d)` | Official TS docs |
| `week_of_year(d)` | `week_number_of_year(d)` | Official TS docs |
| `day_of_week(d)` | `day_number_of_week(d)` or `day_of_week(d)` | Official TS docs (both exist — number vs name) |
| `date_format(d, fmt)` | not a TS function | Official TS docs |
| `month_number` note "Not month()" | `month()` exists (returns name) | Official TS docs |

These will be corrected as part of the catalog migration — every function gets
its canonical name from the catalog.

---

## Implementation scope

### Files modified

| File | Change |
|---|---|
| `agents/shared/schemas/thoughtspot-formula-patterns.md` | Add Snowflake, Databricks, Tableau columns to each function table |
| `agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md` | Remove scalar function sections (~100 lines); add catalog reference block |
| `agents/shared/mappings/ts-databricks/ts-databricks-formula-translation.md` | Remove scalar function sections (~80 lines); add catalog reference block; fix wrong TS function names in complex sections |
| `agents/shared/mappings/tableau/tableau-formula-translation.md` | Remove scalar function rows that are pure 1:1 (~30 rows); add catalog reference block; keep Tableau-specific complex patterns |
| `tools/validate/check_formula_catalog.py` | New validator |
| `tools/validate/tests/test_formula_catalog.py` | New tests |
| `scripts/pre-commit.sh` | Add formula-catalog gate |
| `.github/workflows/validate.yml` | Add check_formula_catalog step |

### Files NOT modified

- Platform-specific complex pattern sections (LOD, window, semi-additive, rank,
  pass-through) — these stay as-is in each mapping file
- Skill SKILL.md files — they reference mapping files and formula-patterns, both
  of which keep their paths
- Worked examples — they reference specific sections by content, not by line
  number, so section removal doesn't break them

### Cross-runtime coverage

CoCo (`agents/coco-snowsight/`) and Cursor (`agents/cursor/`) skills do NOT have
their own formula facts. They reference the same shared files:

- CoCo SKILL.md files link to `../../shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md`
  and `../../shared/schemas/thoughtspot-formula-patterns.md` via relative paths
- Cursor `.mdc` files reference `~/.cursor/shared/mappings/...` (symlinked to the
  same repo files)
- CoCo deploys these files to Snowflake stage via `stage-sync.sh`

**This means the catalog approach covers all runtimes automatically** — fixing the
shared files fixes CoCo and Cursor too. The validator scans `agents/shared/` which
is the single source for all three runtimes. No separate CoCo/Cursor drift is
possible because they don't maintain independent copies.

After merge: run `./scripts/stage-sync.sh` to push updated shared files to the
Snowflake stage for CoCo.

### Risk assessment

| Risk | Mitigation |
|---|---|
| Skills that read mapping files for scalar functions break | Mapping files include a reference block pointing to formula-patterns.md — skills follow the reference |
| CoCo skills read these files from Snowflake stage | `stage-sync.sh` after merge; files keep same paths |
| Cursor .mdc files reference specific mapping sections | Cursor mirrors reference the skill SKILL.md, not mapping files directly |
| formula-patterns.md becomes too wide with 4+ columns | Table is markdown — renders fine. If a future platform needs adding, it's one column |

---

## What this design does NOT cover

- **Verifying every TS function name against a live instance** — the official docs
  list from 2026-06-13 is the baseline. Individual functions will be verified
  as conversions exercise them.
- **Adding new platforms** (BigQuery, Redshift) — the catalog structure supports
  adding columns, but no new platform mapping files are created in this work.
- **Restructuring complex pattern sections** — LOD, window, semi-additive sections
  stay in platform files as-is. A future refactor could extract shared patterns,
  but that's a separate concern.
- **Formula-patterns.md as a validator input for SKILL.md** — the validator checks
  mapping files only. Extending it to scan SKILL.md files for stale function
  references is a follow-on.

---

## Future: adding a new platform

When a new platform mapping file is created (e.g. `ts-bigquery-formula-translation.md`):

1. Add a column to each catalog table in formula-patterns.md
2. Fill in the SQL equivalents for that platform
3. The new mapping file starts with ONLY the complex pattern sections — no scalar
   tables (the validator blocks them)
4. The validator auto-discovers the new mapping file (scans `agents/shared/mappings/`)
