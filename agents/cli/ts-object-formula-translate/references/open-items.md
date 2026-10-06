# Open Items — ts-object-formula-translate

Questions that needed a live ThoughtSpot answer before the skill's output could be trusted.
Spec §9 lists them; findings are recorded here.

Status legend: **VERIFIED** (tested live) | **OPEN** (not yet verified) | **DEFERRED** (decided later, tracked in the backlog)

Fixture cluster: se-thoughtspot. Model *BL018_TEST_SV* `93b6ff6b-f4d9-4941-bb02-c64fe71a3c3c`
(Snowflake, `AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST`). Every probe used a scratch copy named
`ZZ_FORMULA_PROBE_<timestamp>_DELETE_ME` and confirmed it gone afterwards; the fixture Model
was only exported.

---

## #1 — Does `import_policy: VALIDATE_ONLY` reject a malformed formula? — VERIFIED 2026-10-06

**Yes — it parses formula expressions, and it creates nothing.** A scratch copy of the Model
(guid dropped, new name, one formula + `columns[]` entry appended) was imported with
`VALIDATE_ONLY`, `create_new: true`:

| Formula | Response (HTTP 200, ~0.5s) |
|---|---|
| `round ( [EMPLOYEES::SALARY] , 0.01 )` | `status_code: OK` (header carries an `id_guid`, but no object exists — searched by GUID and by name) |
| `round ( [EMPLOYEES::SALARY] , ` (truncated) | `ERROR` 14516 — `Formula addition failed. Formula: Probe, Error: Unknown data type.` |
| `foo_bar ( [EMPLOYEES::SALARY] )` | `ERROR` 14516 — `Search did not find "foo_bar (" …` |
| `sum ( [EMPLOYEES::NOPE_COL] )` | `ERROR` 14516 — `Search did not find "EMPLOYEES::NOPE_COL )" …` |
| `strpos ( [EMPLOYEES::EMPLOYEE_NAME] , 'a' , 2 )` | `ERROR` 14516 — `Function strpos expects only 2 arguments.` |
| `unique_count ( [EMPLOYEES::EMPLOYEE_ID] )` | `ERROR` 14516 — `Search did not find "unique_count (" …` |

`ts metadata search --subtype WORKSHEET --name "ZZ_%PROBE%"` returned `[]` after all six.

**Consequence (implemented):** `--validate compile` uses VALIDATE_ONLY and creates no object.
It returns no SQL — ThoughtSpot compiles SQL only for a query, and a query needs a real Model —
so the scratch-Model path is kept for `--validate execute`, which also runs the VALIDATE_ONLY
check first so a broken formula never creates an object.

## #2 — Does `day_number_of_week` follow the week-start setting? — VERIFIED 2026-10-06

Probed by the coordinating session (scratch Models, `ts agentql generate-sql` / `fetch-data`;
deleted). Tracked as **BL-334**.

- `day_number_of_week ( d )` compiles to `MOD(DATEDIFF(day, DATE '1970-01-01', d) + 3, 7) + 1`:
  **1 = Monday … 7 = Sunday, fixed**, independent of the warehouse's `WEEK_START`.
- `start_of_week ( d )` compiles to `DATE_TRUNC(week, d)`, which follows Snowflake's
  `WEEK_START` session parameter (it returned Monday on se-thoughtspot). It matches Monday only
  while `WEEK_START` is 0 or 1.
- ThoughtSpot domain review: the week comes from the **Model's calendar** — Gregorian with a
  Monday week start by default, so `day_number_of_week` agrees with the default by design.
  `start_of_*` accept a calendar-name string literal (`start_of_week ( [d] , 'Calendar Name' )`),
  but translations must **not** emit it; the Model supplies the calendar.
- A cluster-level ThoughtSpot week-start setting could not be varied on one cluster; its effect
  on `day_number_of_week` is not probed.

**Consequence (implemented):** every translation that assumes Monday is day one carries the trap
line "assumes a Monday week start; diverges if the Model's calendar starts on another day"
(CLI `traps.py`; SKILL.md Step 4b for map-backed rows). A source with a fiscal or custom week
setting gets "the week/fiscal definition comes from the Model's calendar, not from the formula".

## #3 — Does `diff_months` count boundaries or complete months? — VERIFIED 2026-10-06

Probed by the coordinating session. **Boundaries crossed:**
`diff_months ( end , start )` = `DATEDIFF(month, epoch, end) - DATEDIFF(month, epoch, start)`.
Jan 31 → Feb 1 = 1, Jan 31 → Feb 28 = 1, Jan 20 → Mar 15 = 2, reversed = −1.
`diff_years` = `EXTRACT(YEAR end) - EXTRACT(YEAR start)` (Dec 31 → Jan 1 = 1).

**Consequence (implemented):** a trap line on every `diff_months` / `diff_years` /
`diff_quarters` output. Excel `DATEDIF` `"M"`/`"Y"` and Sigma `DateDiff` on complete periods need
the map's day-of-month correction; plain `diff_months` is not equivalent.

## #4 — Is `contains` case-sensitive? — VERIFIED 2026-10-06

Probed by the coordinating session. Tracked as **BL-333**. **No — and neither are `strpos` or
`=`.** ThoughtSpot wraps the column in `LOWER()` and lowercases string literals at compile
time: `[DEPARTMENT] = 'engineering'` matched `Engineering`; `contains('Hello World', 'WORLD')`
= true.

**Consequence (implemented):** a case-sensitive source comparison has no native form; it needs
`sql_bool_op ( "{0} = {1}" , … )` / `sql_bool_op ( "CONTAINS({0}, {1})" , … )`. The CLI flags
every string comparison translated from a case-sensitive dialect (Tableau, Snowflake,
Databricks); SKILL.md Step 4b applies the reclassified passthrough map rows (Excel `EXACT`/`FIND`,
Sigma `Contains`/`StartsWith`/`EndsWith`/`Find`/`Like`, Omni `EXACT`/`FIND` and the
contains-family filters).

**Follow-up probe (this session, 2026-10-06, `--validate execute` machinery, scratch Models
deleted):** a string literal passed as a `sql_bool_op` *argument* is **not** lowercased.
`if ( sql_bool_op ( "{0} = {1}" , [EMPLOYEES::DEPARTMENT] , 'Engineering' ) ) then 1 else 0`
and the literal-in-template form `sql_bool_op ( "{0} = 'Engineering'" , … )` both compiled to
`"DEPARTMENT" = 'Engineering'` and returned both 1 and 0 rows. So the map's
`sql_bool_op ( "{0} = {1}" , [a] , 'Literal' )` templates are case-faithful.

## #5 — Can `sql_double_op` wrap an aggregate? — VERIFIED 2026-10-06

**Yes**, with one semantic change. Probed with `--validate execute`'s own machinery on the
fixture Model (scratch Models deleted, absence confirmed):

| Formula | Result |
|---|---|
| `sql_double_op ( "ROUND({0}, 2)" , sum ( [EMPLOYEES::SALARY] ) )` | imports; compiles to `ROUND(CASE WHEN sum(SALARY) IS NOT NULL THEN sum(SALARY) ELSE 0 END, 2)`; returns rows (Acme Corp 320000.0, …) |
| `sql_double_aggregate_op ( "ROUND(SUM({0}), 2)" , [EMPLOYEES::SALARY] )` | VALIDATE_ONLY: accepted |
| `sql_int_aggregate_op ( "SUM({0})" , [EMPLOYEES::SALARY] )` | VALIDATE_ONLY: accepted |
| `sql_number_aggregate_op ( "SUM({0})" , [EMPLOYEES::SALARY] )` | **rejected** — `Search did not find "sql_number_aggregate_op ( …"` (error_code 14516) |

Two findings beyond the question:

1. **The aggregate wrapped by `sql_double_op` is coalesced to 0** — an empty group returns 0,
   not NULL. Non-literal `ROUND(SUM(x), d)` *can* pass through, but not NULL-faithfully, so
   BL-331's choice to refuse it stands for converters that must be exact.
2. **`sql_number_aggregate_op` does not exist on this build**; `sql_double_aggregate_op` does
   (as the Tableau mapping already said). The shared references named the former; they were
   corrected on main in #563 (BL-335), and the CLI's output guard rejects the bad name.
