---
name: ts-recipe-answer-period-comparison
description: Build a ThoughtSpot Answer that compares average daily sales during a retail event with the weeks before it, one row per year, with the variance. Built-in events are Black Friday, Cyber Monday, Christmas, Boxing Day and Easter, and any custom event works from its dates. The dates are computed by the `ts recipe period-comparison` command, never typed by hand. Use when someone asks for a Black Friday comparison, event lift or promotion uplift by year, wants to "compare sales to prior weeks" or a "normal week", or asks how Easter or Christmas sales compare with normal weeks. Not for same-dates-last-year comparisons, Liveboards, or edits to a Model.
metadata:
  category: Recipes
  summary: "Event-period comparison Answer: average daily sales in a retail event vs prior weeks, per year, as a reusable Set or Answer formula"
---

# ThoughtSpot: Event-Period Comparison Answer

One Answer that says how much a retail event lifted daily sales over normal weeks, for every
year at once. The default compares the event window (e.g. Black Friday to Cyber Monday) with
the six windows of the same shape in the weeks before it:

| Year | Average <Event> Sales | Average Comparison Sales | Variance to Baseline |
|---|---|---|---|
| one row per year | sales ÷ days with data, event window | the same, comparison windows | event minus comparison |

**Why a recipe.** Built by hand, this Answer needs a Set with dozens of typed date ranges,
and those drift (a missing week, a missing year). An earlier hand-built version used a
measure computed at a fixed level, which repeated a grand total on every row and inflated the
numbers. The recipe generates every date in code and uses only row-level conditional
aggregates (`sum_if`, `unique_count_if`, inside `safe_divide`).

**What it creates.** One Answer, plus one reusable Set when the user picks that form. It
never edits the Model, never creates a Liveboard and never touches the warehouse.

Ask one question at a time for **dependent** decisions. Batch **independent** questions
into a single prompt to cut round-trips.

## References

| File | Purpose |
|---|---|
| [../../../tools/ts-cli/README.md](../../../tools/ts-cli/README.md#ts-recipe-period-comparison) | `ts recipe period-comparison`: every option, the output JSON and the exit codes |
| [references/open-items.md](references/open-items.md) | What was verified live, and what is still open |
| [../../shared/schemas/thoughtspot-sets-tml.md](../../shared/schemas/thoughtspot-sets-tml.md) | Set TML, including the date-range condition this recipe emits |
| [../../shared/schemas/thoughtspot-answer-tml.md](../../shared/schemas/thoughtspot-answer-tml.md) | Answer TML; how an Answer names a reusable Set |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | Auth |

## Prerequisites

- A ThoughtSpot profile ([ts-profile-thoughtspot](../ts-profile-thoughtspot/SKILL.md)).
- ts-cli 0.220.0 or later (`ts recipe period-comparison --help` must work).
- A Model with a date column and a sales column whose daily total is a sum.

---

## Step 0 — Overview

Display, then wait for Y:

    ts-recipe-answer-period-comparison — event sales vs prior weeks, one row per year.

      1. Profile ................................. you choose
      2. Model, date column, sales column ........ you confirm
      3. Event, window, years .................... you choose
      4. Comparison windows ...................... you choose
      5. Bucket form (formula or reusable Set) ... you choose
      6. Generate and check the dates ............ you confirm
      7. Back up (if updating) and import ........ auto
      8. Verify, plus one check in the UI ........ you check

    Ready? [Y / N]

## Step 1 — Profile

Read `~/.claude/thoughtspot-profiles.json`; if there are several profiles, ask which. Run
`ts auth whoami --profile "{profile}"`. On failure send the user to `/ts-profile-thoughtspot`.

## Step 2 — Model and columns

Find the Model. Models are subtype `WORKSHEET`:

```bash
ts metadata search --subtype WORKSHEET --name "%{text}%" --profile "{profile}"
```

Keep its GUID (`metadata_id`) and exact name (`metadata_header.name`). Then read the columns
and their types:

```bash
ts tml export {model_guid} --associated --parse --profile "{profile}"
```

From the Model document, read `model.columns[]` (`name`, `column_id`,
`properties.column_type`, `formula_id`) and `model.formulas[]` (`id`, `name`, `expr`). A
column's type is on its Table: match `column_id` (`TABLE::column`) to that Table's
`columns[].db_column_properties.data_type`.

**Propose** one date column (an ATTRIBUTE of type `DATE` or `DATE_TIME`) and one sales column
(a MEASURE). The user confirms both, by their Model column names. Then check:

- **A fixed-level sales column.** If the sales column is a formula whose `expr` uses
  `group_aggregate` or any `group_*` function (`group_sum`, `group_count`, …), warn and ask
  for another column. Such a measure is computed at a fixed level, repeats its total on every
  row, and inflates the result: the trap this recipe exists to avoid.
- **A non-additive sales column.** The measures sum the column per window (`sum_if`),
  whatever its default aggregation. If the column's aggregation is not `SUM` (an average, a
  distinct count), say so and confirm the user wants its daily sum.
- **A date column on another Table.** Each measure sums the sales column per row
  (`sum_if`), so the rows must not be repeated by a join. Find each column's Table from
  its `column_id`, then read the joins: `model.model_tables[].joins[]` (`with`,
  `cardinality`), or for a `referencing_join` the source Table's `joins_with[]` entry.
  The date column should be on the sales column's Table, or on a Table that the sales
  column's Table joins `MANY_TO_ONE` (or `ONE_TO_ONE`), directly or through such joins.
  Exported Table TML usually omits `joins_with[].cardinality`: it is never emitted on
  export (`agents/shared/schemas/thoughtspot-table-tml.md`). When neither the Model join
  nor the Table entry gives a cardinality, ask the user which side has one row per key.
  Never assume `MANY_TO_ONE`.
  If the date column is on neither, warn: `sum_if` would add each sales value once per
  joined row and inflate the result. Step 8's UI check (no `CROSS JOIN`, each measure a
  flat `sum` from the fact table) shows the SQL's shape, not how many rows a join
  repeats, so it would not catch an ordinary join that repeats rows.
- **A DATE_TIME date column.** Note it now: Step 5 then offers only the formula form.
- **A custom or fiscal calendar.** Look at the date column's `properties.calendar`, on the
  Model column or its Table column. If it names a calendar other than the literal
  `calendar`, warn: the Answer's rows group by `.yearly`, which follows that calendar, while
  the generator places windows by Gregorian years. A window near the fiscal year boundary can land in a different
  row than its event.

## Step 3 — Event, window and years

Batch these four questions: event, window, years and the last loaded date.

**Event.** A built-in event, or a custom one:

| `--event` | Anchor day | Default window (`--offset 0 --length 4`) |
|---|---|---|
| `black-friday` | The day after the 4th Thursday of November | Friday to Monday (Cyber Monday) |
| `cyber-monday` | Black Friday + 3 | Monday to Thursday |
| `christmas` | 25 December | 25–28 December |
| `boxing-day` | 26 December | 26–29 December |
| `easter` | Easter Sunday | Sunday to Wednesday. Good Friday to Easter Monday is `--offset -2 --length 4` |
| `custom` | The user's dates, per year | Needs `--event-name "<Name>"` and `--event-dates <file>` |

For a custom event, write the user's dates to a YAML file exactly as given, one entry per
year, **quoted**: a start date (`2025: '2025-05-11'`), expanded with `--offset` and
`--length`, or one range (`2025: [['2025-05-09', '2025-05-12']]`). Never work out or fill in
a date yourself. A year missing from the file is an error.

**Window.** "Fri–Mon" is offset 0, length 4; "just the Friday" is offset 0, length 1. Every
window must fall inside one calendar year: a window that crosses 1 January is an error, so
a long Christmas window needs an earlier start or a shorter length.

**Years.** `--years 2020-2025` (or one year), or `--last N` for the last N finished years.
Ask what years the Model's data covers, and the first day it is loaded from. A year with no
data at all gives no row. `--data-through` guards only the end of the data: a year whose
data starts after its comparison windows but before its event gets a comparison average of
0 and a variance equal to the event average. Leave out each year whose earliest
comparison window starts before that first loaded day.

**Last loaded date.** Establish the last day the data is loaded through, and pass it as
`--data-through YYYY-MM-DD`. A year with any window ending after it is dropped and
reported in `dropped_years`. Without it, the command assumes data up to the day before
the run date, so a recent window with no data yet would average 0 and make a large
negative variance. Ask the user. If the Model is on an external cloud data warehouse,
`ts agentql fetch-data` can return the date column's maximum (not yet tried by this
recipe; see [ts-object-model-agentql-query](../ts-object-model-agentql-query/SKILL.md)):

```bash
ts agentql fetch-data 'SELECT MAX("t1"."{date_column}") AS "Last Day" FROM "{model_name}" AS "t1"' \
  --model {model_guid} --profile "{profile}"
```

If it fails, or the Model is not on an external warehouse, ask the user.

## Step 4 — Comparison windows

| Mode | Options | What it does |
|---|---|---|
| Prior weeks (default) | `--prior-weeks N` (default 6) | N windows of the event's shape, each moved back by whole weeks, so weekdays match |
| Custom ranges | `--comparison custom --comparison-dates <file>` | The user's ranges per year: `2025: [['2025-10-03', '2025-10-06'], …]`, quoted. Overlapping ranges are an error |

A group holds no more than 300 windows, so years × prior weeks must stay at or under 300
(both forms rendered live at 300; open item #3). Labels default to `<Event> Days`,
`<N> Prior Weeks` (`1 Prior Week` for one) or `Comparison Periods`, and `Not <Event>`;
change them with `--labels event=…,comparison=…,other=…`.

## Step 5 — Bucket form

The bucket decides, for each row, whether its date is in the event, a comparison window or
neither. Offer two forms:

| `--bucket` | Where it lives | Choose it when |
|---|---|---|
| `formula` (default) | A formula private to this Answer | The comparison is for this Answer only. **The only form for a DATE_TIME date column** |
| `reusable-set` | A Set shared on the Model, imported first | Other Answers should reuse the same event and comparison days |

- **DATE_TIME date column: offer only `formula`, and say why.** The bucket formula and the
  measures wrap the date column in `date ( … )`, so they should count days. A reusable Set's
  conditions take the bare column, so a window's last day may lose its rows after midnight.
  Say also that the formula form is the better choice, not a proven one: neither form is
  verified on a real DATE_TIME column (open item #9, tracked as BL-603). The Answer's year
  filter names the bare column in both forms; Step 6 checks the one case where that
  matters.
- **Model formulas are not offered.** The recipe never edits the Model.
- **If the user asks for an answer-level Set**, explain it is not in v1: an Answer formula
  cannot name one (SCAL-353379), so the Answer could have no variance column. It is tracked
  as BL-601.

Names: `--name` sets the Answer name (default `<Event> Period Comparison`), and `--set-name`
the bucket's name in either form (default `<Event> Period`).

**Re-runs.** Before generating, look for objects with the same names:

```bash
ts metadata search --type ANSWER --name "{answer_name}" --profile "{profile}"
ts sets inventory --model {model_guid} --profile "{profile}"   # reusable-set only
```

In the Sets inventory, check `orgs[].models[].discovery` is `COMPLETE` (an `INCOMPLETE`
Model's empty `sets[]` means unknown, not none), then look for the name in `sets[].name`.

**An Answer of that name may be on another Model.** The Answer search covers the whole
Org, and the default name is the same for everyone analysing the same event. For each
Answer found, export it and check what it searches:

```bash
ts tml export {found_answer_guid} --fqn --parse --profile "{profile}"
```

Offer the in-place update only when its `answer.tables[].fqn` equals this Model's GUID, and
show its author (`metadata_header.authorDisplayName` in the search result, or `authorName`)
so the user knows whose Answer it is. Otherwise, create a new Answer under a distinct name
and never pass that GUID as `--answer-guid`.

If a matching object exists, ask: update it in place (pass `--answer-guid` / `--set-guid`
in Step 6, back it up and drop `--create-new` in Step 7), or pick new names.

**Updating a Set in place changes every Answer that uses it.** First list its consumers:
that Set's `dependents[]` in the same inventory (if `dependents_complete` is `false`, the
list may be short). Tell the user that the new windows apply to all of them. If a label
changes, the other Answers' measures still compare the bucket with the old label, so they
read 0. When other Answers use the Set, offer a new Set name instead.

## Step 6 — Generate

```bash
ts recipe period-comparison --model-name "{model_name}" --model-guid {model_guid} \
  --date-column "{date_column}" --measure-column "{measure_column}" \
  --event {event} --years {years} --data-through {last_loaded_date} --bucket {bucket} \
  --name "{answer_name}" --set-name "{set_name}" -o {out_dir}
```

Make `{out_dir}` a scratch directory outside the repo, e.g. one made with `mktemp -d`.
The generated `.answer.tml` and `.cohort.tml` files hold the Model's name and GUID, and
`*.answer.tml` is not gitignored.

Add `--offset`, `--length`, `--event-name`, `--event-dates`, `--prior-weeks`,
`--comparison`, `--comparison-dates`, `--labels`, `--answer-guid` or `--set-guid` as chosen.
The command is offline: it writes TML and imports nothing. Read its exit code first:

| Exit | Stdout | Meaning and what to do |
|---|---|---|
| 0 | The plan, with `files` | Files written. Show the windows table (below) |
| 2 | JSON with `needs_clash_decision: true` | A clash: explain it and ask (below). Nothing written |
| 2 | Empty (usage message on stderr) | The command line is wrong: a missing or misspelt option. Fix it and re-run |
| 1 | `{"error": "…"}` | The request cannot be built: a window crossing 1 January (or a custom date typed in another year), a year missing from a custom file, more than 300 windows in a group, a bad label. Show the message and change the input with the user |

**A clash** is a prior-week window that holds a built-in event's anchor day. That is
another event's day (Boxing Day 2025's 4th prior window is Black Friday to Cyber Monday),
or the analysed event's own day when `--offset` moves the event window off it
(`--event black-friday --offset 7` puts Black Friday itself in the 1st prior window).
Explain each one in plain words from `clashes[]`: which window, which event, and that
keeping it pushes the baseline up and shrinks the measured lift. Offer:

1. **Skip and extend (recommended):** drop each clashing window and take the next week
   further back, so there are still N windows. Re-run with `--on-clash skip`; the output
   names each substitute in `substitutions`.
2. **Keep:** use the windows as they are, accepting the higher baseline. Re-run with
   `--on-clash keep`.
3. **Custom:** switch to custom comparison ranges (Step 4) for full control.

**Show the windows table before importing**, from `years[]`: one row per year with the event
window, the comparison windows and any substitutions; then `step` (the days between
windows) and any `dropped_years`. For a fixed-date event (Christmas, Boxing Day), say that
the comparison weeks align to the event's weekday that year: Christmas on a Thursday gives
Thursday-to-Sunday comparison windows.

**DATE_TIME and 31 December.** On a DATE_TIME date column, check whether any window, event
or comparison, ends on 31 December of the last year in the windows table (Christmas or Boxing Day
with a longer `--length` or an `--offset` can, as can a custom window). The Answer's year
filter ends at `.12/31/<last>` on the bare column, so that day's rows after midnight may be
dropped (open item #9). If one does, tell the user and ask them to check that year's figures
after import, or offer to end the window a day earlier (`--length` one less, or an earlier
end date in the custom dates file).

**If you run `ts tml lint`** on the generated Answer, it flags the bare `fqn` in
`tables[]`. That is expected: this is the binding verified live (open item #3 and the
smoke test). Do not "fix" it to `obj_id`. BL-604 narrows the lint rule.

Wait for the user to confirm the dates.

## Step 7 — Back up, then import

**Back up before an in-place update.** If Step 6 passed `--answer-guid` or `--set-guid`,
export what is on the server now into the run directory, before any import:

```bash
ts tml export {answer_guid} --fqn --profile "{profile}" > "{out_dir}/before-answer.json"
ts tml export {set_guid} --fqn --profile "{profile}" > "{out_dir}/before-set.json"   # a Set update only
```

Without `--parse`, each item's `edoc` is the object's TML exactly as the server returned
it, root `guid` included. On current builds that is JSON TML (the export ignores a
requested format, BL-567), and ThoughtSpot imports it. Save each `edoc` exactly as
returned to its own file, `before-answer.tml` and `before-set.tml`, and check each is
non-empty. If an export fails, stop: do not import without the backup.

Check each backup imports before relying on it:

```bash
ts tml import --file "{out_dir}/before-set.tml" --policy VALIDATE_ONLY --profile "{profile}"   # a Set update only
ts tml import --file "{out_dir}/before-answer.tml" --policy VALIDATE_ONLY --profile "{profile}"
```

If validation fails, stop before the update. **Re-importing a backup file is the
rollback**, the Set before the Answer, with `--policy ALL_OR_NONE` and without
`--create-new`, so its `guid` updates the object in place:

```bash
ts tml import --file "{out_dir}/before-set.tml" --policy ALL_OR_NONE --profile "{profile}"
ts tml import --file "{out_dir}/before-answer.tml" --policy ALL_OR_NONE --profile "{profile}"
```

A Set update changes every Answer that uses the Set (Step 5), so the Set's backup restores
all of them. Tell the user where the backup is, as ts-object-model-coach does (its Step 8a).

Import the Set first (reusable-set only), then the Answer, which names it:

```bash
ts tml import --file "{out_dir}/{set_name}.cohort.tml" --policy ALL_OR_NONE --create-new --profile "{profile}"
ts tml import --file "{out_dir}/{answer_name}.answer.tml" --policy ALL_OR_NONE --create-new --profile "{profile}"
```

Take each GUID from the output (`response.header.id_guid`, or
`response.object[0].header.id_guid`). When updating in place (`--answer-guid` /
`--set-guid` in Step 6), drop `--create-new`. A `/`, `\` or control character in a name
becomes `_` in the file name; the `files` list in Step 6's output has the exact paths.

**After an import timeout, do not retry at once.** A large import finishes on the server
after the client gives up. In the probes (open item #3), a 525-window import timed out and
a search straight away found nothing, yet it had been created. A 300-window Answer also
timed out, and was on the server within 2 minutes. `ts tml import` says "not retried"
when this happens. Wait a few minutes, then search by name (the Step 5
commands; for a Set, check `discovery` is `COMPLETE`). Retry only if the object is still
missing; otherwise a retry creates a duplicate.

## Step 8 — Verify

Export the Answer and check it:

```bash
ts tml export {answer_guid} --fqn --parse --profile "{profile}"
```

| Check | Expected |
|---|---|
| `formulas[]`, matched by `id` | `formula_Average <Event> Sales`, `formula_Average Comparison Sales`, `formula_Variance to Baseline`; for the formula form also `formula_<set name>`. The server reorders formulas and adds `was_auto_generated: false`, so never compare by position |
| `search_query` and `answer_columns[]` | The bucket is absent **by design**: the measures name it themselves, so the rows group by year alone (open item #7). Not a defect |
| `cohorts` | Absent in the reusable-set form: the Answer names the Set by name only (open item #6) |
| `tables[].fqn` | The Model GUID |

**Ask the user to check the SQL in the UI.** No `ts` command returns a saved Answer's SQL
(BL-600). Open the Answer and its query SQL view, and check:

- no `CROSS JOIN`;
- each measure is a flat `sum` (of a `CASE WHEN`) straight from the fact table;
- one row per year, and the chart shows year on the x-axis with the three measures.

The recipe passed this check on a test Model (open items #4 and #7). Ask for it anyway:
it is the only way to see the rows and SQL on the user's own Model.

**Report to the user:** the Answer's name and GUID (and the Set's), the windows table, the
backup directory and its rollback command after an in-place update (Step 7), and:

- **Days with data.** Each average is sales ÷ the number of days *with data* in the window.
  Filtering the Answer (to one product, say) changes that count, since days on which the
  product did not sell drop out of it.
- **An average of 0 means no data in that window,** not zero sales. Check the year's data
  is loaded, or re-run with an earlier `--data-through`.
- **Year rows** follow the date column's calendar year (`.yearly`); see the calendar warning
  in Step 2.

---

## Run it without an agent

The commands are in one place, the
[run-by-hand walkthrough in the ts-cli README](../../../tools/ts-cli/README.md#ts-recipe-period-comparison)
(find the Model, read its columns, generate, handle a clash, import, search before
retrying), with every option, the output JSON and the exit codes. Follow it, then check
the round trip with `ts tml export <answer-guid> --fqn --parse` (Step 8).

The decisions the agent would otherwise make:

| Decision | Rule |
|---|---|
| Date column | A DATE or DATE_TIME attribute. On DATE_TIME use `--bucket formula`: a reusable Set's conditions take the bare column, so a window's last day may lose rows after midnight. The formula form is not verified on a real DATE_TIME column either (open item #9), and the year filter names the bare column in both forms: if a window ends on 31 December of the last year in the plan's `years[]`, check that year's figures or end the window a day earlier |
| Last loaded date | Pass `--data-through` with the last day the data is loaded through, so a window with no data yet is dropped rather than averaged as 0 |
| Sales column | A measure summed per day. Never a formula built on `group_aggregate` or a `group_*` function: it repeats a fixed-level total on every row |
| Joins | The date column on the sales column's Table, or on a Table it joins many-to-one. Otherwise each sales value is summed once per joined row |
| Calendar | If the date column has a custom or fiscal calendar, the year rows follow it, not the Gregorian years the windows are placed in |
| Clash | Prefer `--on-clash skip`: keeping a window that holds a built-in event's anchor day (another event's, or this event's own when `--offset` moves off it) raises the baseline and shrinks the lift |
| Import timeout | Do not retry at once. Wait a few minutes, search by name (`ts metadata search --type ANSWER --name …`; for a Set, `ts sets inventory --model <guid>` with `discovery` `COMPLETE`), and retry only if it is missing |
| Re-run | Same names exist already: pass `--answer-guid` / `--set-guid`, back up each object first (`ts tml export <guid> --fqn`, saving each item's `edoc` exactly as returned, JSON on current builds, as a `.tml` file, and checking it with `ts tml import --policy VALIDATE_ONLY`; re-importing that file with `ALL_OR_NONE`, Set first, is the rollback), and import without `--create-new`. A same-name Answer found by the search counts only if its `tables[].fqn` is this Model's GUID (Step 5). Updating a Set changes every Answer that uses it (its `dependents[]` in the inventory); a changed label makes their measures read 0 |
| SQL check | In the UI query view: no `CROSS JOIN`, measures as a flat `sum` from the fact table, one row per year |

---

## Error handling

| Symptom | Cause | Action |
|---|---|---|
| `No such command 'recipe'` | ts-cli older than 0.220.0 | Reinstall ts-cli from this repo |
| Exit 1, `runs outside calendar year` | A window crosses 1 January, or a custom file has a date typed in another year | Shorten the window or move its start; correct the date in the file |
| Exit 1, `the limit is 300 per group` | Too many years × prior weeks | Fewer years or fewer prior weeks |
| Import `ERROR` 14516, `Search did not find …` | A column or Set name in a formula does not exist on the Model | Check `--date-column`, `--measure-column` and, for reusable-set, that the Set imported first |
| Import says "not retried" | Client timeout; the server may still finish | Step 7: wait, search, then retry only if missing |
| Answer shows several rows per year | The bucket was added to the search | Re-import the generated file; the bucket stays out of the search |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-11-19 | Initial release |
