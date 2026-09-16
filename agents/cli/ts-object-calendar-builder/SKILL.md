---
name: ts-object-calendar-builder
description: Build ThoughtSpot custom calendars that the native API cannot express — week-aligned fiscal years, 4-4-5 / 4-5-4 / 5-4-4 / 13-period patterns with correct 52/53-week tiling, localized or abbreviated labels, calendar-year vs fiscal-year month labelling, and RLS union calendars spanning multiple tenants. Use whenever someone asks for a retail calendar, a 4-4-5 or 4-5-4 calendar, a fiscal calendar starting on a specific weekday ("first Monday of February"), a 13-period calendar, a custom calendar table for Snowflake, or a per-group calendar resolved by row-level security. Also use when an existing calendar's month labels show the wrong year. Not for standard month-offset fiscal calendars, which the ThoughtSpot API already handles natively.
---

# ThoughtSpot: Custom Calendar Builder

ThoughtSpot's native custom-calendar API (`FROM_INPUT_PARAMS`) generates a
calendar itself from a handful of parameters. It is fine for a plain
month-offset fiscal year. It is **not** fine for a real retail or 4-4-5-style
calendar, because it never inserts a leap week: every fiscal year it
generates is a fixed 364 days. A 4-5-4 calendar drifts against the Gregorian
calendar at roughly 1.25 days a year and can never re-anchor. Verified
live against a known-good corpus calendar (`LULULEMON`): the native output
matches exactly through **FY2018**, then diverges at **FY2019** by 7 days,
is 7 days off by FY2022, and 14 days off by FY2025.

**This is why the skill exists, and why testing it briefly is misleading.**
Any comparison shorter than about four years lands entirely inside the
window where the native output still happens to be right. See
[references/anchor-rules.md](references/anchor-rules.md) for the full
worked table and why the gap only widens.

The native API also mislabels months: its `monthly` column carries the
*fiscal* year, not the calendar year a date actually falls in, so a January
period inside a December-start fiscal year reads `"January 2024"` for dates
in January 2025. [references/relabel-calendar.sql](references/relabel-calendar.sql)
fixes an already-generated table in place, without regenerating it.

This skill generates the calendar correctly, loads it to Snowflake, and
registers it with ThoughtSpot — using the native fast path only where it is
provably safe (see Step 3 and Step 7).

Ask one question at a time for **dependent** decisions. Batch **independent**
questions into a single prompt to cut round-trips.

---

## References

| File | Purpose |
|---|---|
| [references/calendar-table-contract.md](references/calendar-table-contract.md) | The 10/30-column schema, value formats, epoch exclusivity, the RLS discriminator column |
| [references/anchor-rules.md](references/anchor-rules.md) | The three anchor rules, worked year tables, the `nearest`-vs-`first` divergence, leap-week placement, period patterns |
| [references/relabel-calendar.sql](references/relabel-calendar.sql) | Parameterised CTAS to fix an existing calendar's month labels without regenerating it |
| [references/open-items.md](references/open-items.md) | Unverified or cluster-specific findings — read before trusting `--native` |
| [tools/ts-cli/README.md](../../../tools/ts-cli/README.md) (`ts calendar`, `ts load`, `ts snowflake`) | Full flag reference for every command below |

---

## Prerequisites

- `ts` CLI on PATH, version **0.139.0+**
- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- ThoughtSpot **10.12.0.cl / 26.3.0.sw or later** (custom calendars are not
  available before this)
- A Snowflake profile — run `/ts-profile-snowflake` if not — needed for the
  load path (Step 6). Not needed if the user only wants the CSV, or is
  taking the `--native` fast path

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-object-calendar-builder** — build a ThoughtSpot custom calendar the
native API can't, or relabel one that already exists.

If you are relabelling an existing calendar's wrong month labels rather
than building a new one, skip straight to Step 9 — Relabel.

Steps:
  1.  Authenticate ...................................... auto
  2.  Gather the calendar specification ................. you choose
  3.  Preview + compare, confirm the shape ............... you confirm (checkpoint)
  4.  Generate the calendar CSV(s) ...................... auto
  5.  Validate against the column contract .............. auto
  6.  Load to Snowflake .................................. auto
  7.  Register with ThoughtSpot .......................... auto
  8.  Verify what landed ................................. auto
  9.  Relabel an existing calendar (alternate path) ...... you confirm (checkpoint)

Confirmation required: Step 2, the checkpoint in Step 3, and the checkpoint
in Step 9 (taken instead of Steps 1-8, not after them)
Auto-executed: Steps 1, 4, 5, 6, 7, 8

The native ThoughtSpot API never inserts a leap week — every fiscal year it
generates is a fixed 364 days. That matches a real retail calendar only for
a few years, then silently drifts. This skill generates the calendar
correctly and only uses the native path where it is provably safe: anchor
rule `fixed52`, and never for pattern `13x4` (the API has no 13-period
calendar type at all, regardless of anchor rule).

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Step 1 — Authenticate

```bash
ts auth whoami --profile "{profile_name}"
```

Confirm this succeeds before asking anything else — every later step assumes
a working profile.

---

## Step 2 — Gather the Calendar Specification

These are independent — ask them together, in one prompt:

```
Let's build your custom calendar.

  1. Fiscal year start month (e.g. February, July, December):
  2. Start day of week (e.g. Monday):
  3. Pattern — 4-4-5 / 4-5-4 (default) / 5-4-4 / 13x4:
  4. Anchor rule — nearest (retail-standard, re-anchors each year) /
                    first (first weekday on/after the 1st) /
                    fixed52 (fixed +364 days — matches the native API):
  5. Fiscal year range, first and last year (e.g. 2020-2027):
  6. Year/quarter label prefixes, if any (e.g. FY, Q):
  7. Label basis for year / month / quarter — fiscal (default) or gregorian
     for each, independently:
  8. Non-default month or day names? (localization, abbreviation like FEB,
     or 13-period labels — leave blank for English full names)
  9. Is this a per-tenant / row-level-security calendar (multiple variants
     sharing one registered object)?
```

Notes for gathering these, not to read verbatim to the user:

- **If they answer `13x4` to question 3**, tell them up front:
  "13x4 is query-safe but filter-unverified — the numeric columns are fine
  for aggregation, but whether a Liveboard filter widget accepts and orders
  period labels correctly on this build hasn't been confirmed live. If it
  turns out not to work, filter on `month_number_of_year` or a date range
  instead." See [references/anchor-rules.md](references/anchor-rules.md).
  Also tell them `--native` (Step 7's fast path) is refused for `13x4`
  regardless of anchor rule — the API has no 13-period calendar type — so a
  `13x4` calendar always goes through Steps 4–6.
- **If they answer yes to question 9**, question 5 onward repeats per
  variant (each tenant may have a different pattern, anchor rule, or year
  range), but the **label vocabulary from questions 6–8 is shared across
  every variant** — never ask for it per variant. ThoughtSpot indexes a
  column's label values across every row of the registered object while RLS
  resolves any one user to a single variant, so if one variant labels a
  month `AUGUST` and another `AUG`, the UI offers both as search
  suggestions while only one can ever return rows for a given user. Also
  collect a discriminator column name (the corpus uses both
  `TS_CALENDAR_GROUP` and `TSGROUP` — either is fine, just be consistent)
  and a short discriminator value per variant (e.g. `tenant_a`).
- Do not ask about `--leap-week-period` unless the user brings it up — the
  default (`last`) matches every verified corpus example.

---

## Step 3 — Preview and Confirm

```bash
ts calendar preview --start-month "{start_month}" --start-day "{start_day}" \
  --pattern "{pattern}" --anchor "{anchor}" \
  --first-year {first_year} --last-year {last_year}
```

Show the user which fiscal years come out 53 weeks and which period absorbs
the extra week. This is the point to catch a wrong pattern or year range —
before generating what could be tens of thousands of rows.

**Run `ts calendar compare` whenever a consequential option is still
undecided**, and show the user the difference before they commit — don't
skip it just because the previewed shape looks right:

- **Anchor rule undecided** — `--vary anchor`, and report the
  `first_divergence` value it returns. This is the exact year the chosen
  anchor rules stop agreeing with each other (and with `fixed52`, the
  native API's behaviour):

  ```bash
  ts calendar compare --vary anchor --start-month "{start_month}" \
    --start-day "{start_day}" --pattern "{pattern}" --anchor "{anchor}" \
    --first-year {first_year} --last-year {last_year}
  ```

- **Start month is not January, and a label basis is undecided** —
  `--vary year-basis` and/or `--vary monthly-basis`:

  ```bash
  ts calendar compare --vary year-basis --start-month "{start_month}" \
    --start-day "{start_day}" --pattern "{pattern}" --anchor "{anchor}" \
    --first-year {first_year} --last-year {last_year}
  ```

**A zero result is a real, useful answer — state it plainly rather than
skipping the check:** "0 of 364 rows differ for this range — this choice
does not affect your calendar." Do not assume a January start month means
the basis choice never matters: it usually still does, because the anchor
is rarely exactly 1 January once the calendar is week-aligned. Run
`compare` and report what it actually found either way.

**Checkpoint.** Show the preview output and any `compare` findings, then:

```
Confirmed shape:
  {first_year}-{last_year}, {pattern}, anchor={anchor}
  53-week years: {list, or "none"}
  {compare findings, if any were run}

Proceed to generate? (Y / N):
```

---

## Step 4 — Generate

```bash
ts calendar generate --start-month "{start_month}" --start-day "{start_day}" \
  --pattern "{pattern}" --anchor "{anchor}" \
  --first-year {first_year} --last-year {last_year} \
  --leap-week-period "{leap_week_period}" \
  --year-prefix "{year_prefix}" --quarter-prefix "{quarter_prefix}" \
  --year-basis "{year_basis}" --monthly-basis "{monthly_basis}" \
  --quarterly-basis "{quarterly_basis}" --fiscal-year-number "{fiscal_year_number}" \
  --month-names "{month_names}" --day-names "{day_names}" \
  --columns {columns} --out "{out_dir}/{table_name}.csv"
```

For an RLS set, run this once **per variant** — using that variant's own
`--start-month` / `--pattern` / `--anchor` / year range, but with every one
of the following held **identical** across every variant: `--year-prefix`,
`--quarter-prefix`, `--month-names`, `--day-names`, `--year-basis`,
`--monthly-basis`, `--quarterly-basis`, `--fiscal-year-number`, and
`--leap-week-period`. The design treats this whole label layer as
set-level, not per-variant — see Step 2: drift here is exactly what breaks
ThoughtSpot's search suggestions. Write each CSV into the **same**
`{out_dir}` and add that variant's discriminator:

```bash
ts calendar generate --start-month "{variant_start_month}" --start-day "{variant_start_day}" \
  --pattern "{variant_pattern}" --anchor "{variant_anchor}" \
  --first-year {variant_first_year} --last-year {variant_last_year} \
  --leap-week-period "{leap_week_period}" \
  --year-prefix "{year_prefix}" --quarter-prefix "{quarter_prefix}" \
  --year-basis "{year_basis}" --monthly-basis "{monthly_basis}" \
  --quarterly-basis "{quarterly_basis}" --fiscal-year-number "{fiscal_year_number}" \
  --month-names "{month_names}" --day-names "{day_names}" \
  --columns {columns} --out "{out_dir}/{variant_table_name}.csv" \
  --discriminator-column "{discriminator_column}" \
  --discriminator-value "{variant_discriminator_value}"
```

Every flag on the second line onward is copied **unchanged** from the
set's shared label spec; only `--start-month`, `--start-day`, `--pattern`,
`--anchor`, `--first-year`, `--last-year`, `--out`, and the two
`--discriminator-*` flags vary by variant.

Omit any flag the user didn't specify a non-default value for — every flag
above has a documented default except `--start-month`, `--start-day`,
`--first-year`, `--last-year` and `--out`, which are required.

---

## Step 5 — Validate

```bash
ts calendar validate --csv "{out_dir}/{table_name}.csv"
```

For an RLS set, repeat `--csv` once per variant in a single call — this is
what checks cross-variant label consistency, not just each file on its own:

```bash
ts calendar validate --csv "{out_dir}/{variant_a}.csv" --csv "{out_dir}/{variant_b}.csv"
```

If it fails on label drift between variants and the drift is a deliberate,
known exception (not an oversight), re-run with `--allow-label-drift` to
downgrade it to a warning. Otherwise fix the vocabulary — see
[references/calendar-table-contract.md](references/calendar-table-contract.md).

Stop and report the finding if `validate` exits non-zero for any other
reason; do not proceed to load a table that fails its own contract.

---

## Step 6 — Load to Snowflake

`ts load snowflake --source` takes a **directory**, not a single file, and
loads every `*.csv` in it as its own table (named from the file's stem,
upper-cased with non-alphanumerics turned to underscores) — which is
exactly what Step 4 already produced, one CSV per variant in `{out_dir}`:

```bash
ts load snowflake --source "{out_dir}" --profile "{sf_profile_name}" \
  --database "{database}" --schema "{schema}" --if-exists replace
```

For a **single calendar**, this is the whole step — one CSV, one table.

For an **RLS set**, this loads every variant as its own table in one call.
Then create the union with a literal discriminator per source table:

```bash
ts snowflake exec --sf-profile "{sf_profile_name}" -q "
CREATE OR REPLACE VIEW \"{database}\".\"{schema}\".\"{union_table}\" AS (
  SELECT *, '{discriminator_value_a}' AS \"{discriminator_column}\" FROM \"{database}\".\"{schema}\".\"{variant_a_table}\"
  UNION ALL
  SELECT *, '{discriminator_value_b}' AS \"{discriminator_column}\" FROM \"{database}\".\"{schema}\".\"{variant_b_table}\"
)"
```

Add one more `UNION ALL` branch per additional variant. This is the same
composition the corpus's own `rlscalendar` view uses.

---

## Step 7 — Register

Default path — register the table (or view) just loaded:

```bash
ts calendar register --name "{calendar_name}" --connection "{connection}" \
  --database "{database}" --schema "{schema}" --table "{table_or_union_table}" \
  --profile "{profile_name}"
```

**Native fast path** — only when the confirmed anchor rule is `fixed52`
**and** the pattern is `4-4-5`, `4-5-4`, or `5-4-4` — never `13x4` — and
only for a single (non-RLS) calendar. This skips Steps 4–6 entirely and
asks ThoughtSpot to generate the calendar itself:

```bash
ts calendar register --name "{calendar_name}" --connection "{connection}" \
  --database "{database}" --schema "{schema}" --table "{table}" \
  --native --start-month "{start_month}" --start-day "{start_day}" \
  --pattern "{pattern}" --anchor fixed52 \
  --first-year {first_year} --last-year {last_year} \
  --profile "{profile_name}"
```

`--native` is **refused for two separate reasons**, and the CLI will not
let either one silently ship a wrong calendar:

- **Any anchor rule other than `fixed52`** — the API emits fixed 364-day
  years with no leap week, so `nearest` or `first` would drift silently.
- **Pattern `13x4`** — the API has no 13-period calendar type to ask for.
  This refusal is **independent of anchor rule**: a `13x4` spec with
  `anchor fixed52` is still refused, because the pattern itself has no
  native equivalent, not because of how it re-anchors.

See open item 5 in [references/open-items.md](references/open-items.md)
before relying on the native path for anything beyond a quick check: the
exact date range it registers has not yet been confirmed live against a
locally generated `fixed52` calendar for the same years.

---

## Step 8 — Verify

```bash
ts calendar search --connection "{connection}" --profile "{profile_name}"
```

Confirm `{calendar_name}` appears with the expected date range. For an RLS
set, also spot-check in ThoughtSpot that the union table's row count matches
the sum of its source tables (each date should appear once per variant, not
once overall).

---

## Step 9 — Relabel an Existing Calendar (Alternate Path)

Take this path **instead of** Steps 1–8 when a calendar already exists in
Snowflake and only its month labels are wrong — the ThoughtSpot-defect case
from the top of this file: `monthly` carries the *fiscal* year, so a
January period inside a December-start fiscal year reads `"January 2024"`
for dates that are actually in January 2025. This does not regenerate the
calendar or touch its ThoughtSpot registration; it produces a new,
correctly-labelled table alongside the existing one.

`{skill_dir}` below is the absolute path of the directory containing this
SKILL.md (e.g. `~/.claude/skills/ts-object-calendar-builder` in Claude
Code, `~/.snowflake/cortex/skills/...` in Cortex Code CLI) — substitute the
real path when running.

Ask which table needs fixing, then confirm before running anything —
**checkpoint**, since this creates a new table:

```
Relabel {source_db}.{source_schema}.{source_table} -> {target_table}?
The original table is left untouched. (Y / N):
```

Run the fix:

```bash
ts snowflake exec -f "{skill_dir}/references/relabel-calendar.sql" \
  --sf-profile "{sf_profile_name}" \
  --var source_db="{source_db}" --var source_schema="{source_schema}" \
  --var source_table="{source_table}" --var target_table="{target_table}"
```

The four `--var` flags fill the placeholders in
[references/relabel-calendar.sql](references/relabel-calendar.sql):
`source_db` / `source_schema` / `source_table` name the existing table;
`target_table` names the new one, created in the same database and schema.
Every column is carried through unchanged except `year`, which the SQL
recomputes from the Gregorian year of `date` instead of copying the source
table's fiscal-year label.

Then:

- **If `{source_table}` was never registered with ThoughtSpot**, register
  `{target_table}` following Step 7.
- **If `{source_table}` is already registered**, this skill has no command
  to repoint an existing calendar object's table reference (calendar
  update/delete is out of scope — `ts calendar search` only verifies what
  is registered, it doesn't change it). Ask the user whether to register
  `{target_table}` as a new calendar object, or to repoint the existing one
  by hand in the ThoughtSpot admin UI.

---

## Error Handling

| Symptom | Action |
|---|---|
| ThoughtSpot rejects the table with a schema-mismatch error on `register` | Run `ts calendar validate --csv {path}` first — it checks the same column contract locally with a clearer message. See [references/calendar-table-contract.md](references/calendar-table-contract.md); a common cause is an unquoted Snowflake identifier that got upper-cased |
| `register --native` refused for the requested anchor | Expected — the native API cannot express `nearest` or `first` without silently drifting. Use the default (`FROM_EXISTING_TABLE`) path: generate, validate, load, then register without `--native` |
| `register --native` refused for pattern `13x4`: `--native cannot express pattern '13x4' — the API has no 13x4 calendar type. Generate a table and register it instead.` | Expected, and independent of anchor rule — even `anchor fixed52` is refused for `13x4`, because the API has no 13-period calendar type at all. Use the default (`FROM_EXISTING_TABLE`) path: generate, validate, load, then register without `--native` |
| `--native` registration times out or returns a 504 | Known issue on at least one cluster (`se-thoughtspot`) — see open item 2 in [references/open-items.md](references/open-items.md). All verified native-API behaviour in this skill comes from a different cluster. The default path (generate/validate/load/register) does not touch this endpoint and is unaffected |
| `ts calendar validate` fails on cross-variant label drift | Either align the label vocabulary across variants (same `--month-names`, `--day-names`, prefixes) so search suggestions resolve to one variant, or, if the drift is a deliberate known exception, re-run `validate` with `--allow-label-drift` to downgrade it to a warning |
| `ts load snowflake` reports the table already exists | Re-run with `--if-exists replace` (or `skip` to leave it alone) — the default (`error`) refuses to overwrite silently |
| `ts snowflake exec` aborts on an unfilled `{placeholder}` | A `--var` is missing for a token in the SQL — check every `{name}` in the query or file has a matching `--var name=value` |
| Auth fails (401) on any command | Token expired — refer the user to `/ts-profile-thoughtspot` (or `/ts-profile-snowflake` for the load step) to refresh credentials |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-09-16 | Initial release |
