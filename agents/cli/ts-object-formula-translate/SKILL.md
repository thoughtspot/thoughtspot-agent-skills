---
name: ts-object-formula-translate
description: Translate one formula written for another tool (Tableau, Power BI DAX, Qlik, Sisense, Snowflake SQL, Databricks SQL, Excel / Google Sheets, Sigma, Omni) into a ThoughtSpot formula, with its classification, the traps that applied, a TML snippet, and optional proof that ThoughtSpot compiles it against a Model. Use when someone pastes a calculated field, measure, expression or spreadsheet formula and asks for the ThoughtSpot equivalent, "how do I write this in ThoughtSpot", or whether a function exists in ThoughtSpot. Not for converting whole workbooks or models (the ts-convert-from-* skills), and never edits an existing Model.
---

# ThoughtSpot: Formula Translate

Paste one formula from another tool; get the ThoughtSpot formula back, with how faithful it
is and, on request, proof that ThoughtSpot accepts it. **Nothing existing is ever modified.**
Validation works on a scratch copy of a Model and deletes it afterwards.

**The one rule: no output may look more certain than its evidence.** A translation that
rests on an unprobed composition says so *on the same line*.

## References

| File | Purpose |
|---|---|
| [../../../docs/superpowers/specs/2026-10-06-ts-object-formula-translate-design.md](../../../docs/superpowers/specs/2026-10-06-ts-object-formula-translate-design.md) | Design (§1–§10) and implementation notes (§12) |
| [../../../tools/ts-cli/README.md](../../../tools/ts-cli/README.md) | `ts formula translate` / `ts formula detect` — every flag and output key |
| [../../shared/schemas/thoughtspot-formula-patterns.md](../../shared/schemas/thoughtspot-formula-patterns.md) | ThoughtSpot formula ground truth — read before writing any map-backed formula |
| [../../../docs/function-maps/ts-excel-function-mapping.md](../../../docs/function-maps/ts-excel-function-mapping.md) | Excel, Google Sheets and Omni table calcs (map-backed) |
| [../../../docs/function-maps/ts-sigma-function-mapping.md](../../../docs/function-maps/ts-sigma-function-mapping.md) | Sigma (map-backed) |
| [../../../docs/function-maps/ts-omni-function-mapping.md](../../../docs/function-maps/ts-omni-function-mapping.md) | Omni modelling layer, table calcs, filters (map-backed) |
| [references/open-items.md](references/open-items.md) | OI-1…OI-5 — the live probes the traps rest on |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | Auth (only for a Model / validation) |

## How it works

| Source | Backing | How this skill translates it |
|---|---|---|
| Tableau, DAX, Qlik, Sisense, Snowflake SQL, Databricks SQL | **translator** — the converter skills' own code | `ts formula translate --from <dialect>`. The CLI result is the answer; do not quietly rewrite it. If it returns `NEEDS_REVIEW` (a translator gap, a known defect, or an output guard), explain the reason and you **may** offer a hand-composed alternative from the maps or `thoughtspot-formula-patterns.md`, labelled *hand-composed, not translator output* and validated if possible. A wrong translation is fixed in the translator, which also fixes the converter |
| Excel, Google Sheets, Omni table calc, Sigma, Omni modelling layer | **map** — `docs/function-maps/` | You translate from the map rows (Step 4b), citing each row. No code stands behind it, so validation is **recommended** |
| LookML | none | Point to `/ts-convert-from-looker`; out of scope here |

The CLI wraps the existing translators (`translate_single`, `translate_dax`, Qlik
`translate`, `translate_jaql`, `sv_sql` and `mv_sql` `translate_sql_expr`) and adds what
they do not: one recording resolver for every column reference, the dialect-independent
trap lines, a `COUNT(*)` repair, role inference, a TML snippet, and validation.

## Step 0 — Overview

Display, then go straight to Step 1 (no Y/N gate — nothing is written anywhere):

    ts-object-formula-translate — one formula in, a ThoughtSpot formula out.

      1. Paste the formula (several? they're answered in order)
      2. I guess the language and confirm in one line
      3. Columns: placeholders, your names, or a Model
      4. Translate — and say exactly how sure that is
      5. Optional: prove ThoughtSpot compiles / runs it (needs a Model)

    Nothing in ThoughtSpot is changed.

## Step 1 — Take the formula

Several formulas pasted at once: handle them as one batch and number the answers
(**Formula 1**, **Formula 2**, …). The detection and context choices below apply to the batch
unless a formula's shape clearly differs.

## Step 2 — Detect, then confirm (never route silently)

    ts formula detect '<formula>'

| `detect` says | You say |
|---|---|
| `ambiguous: false`, `best: X` | **One line**, then continue: "Reading this as **X** — say if it's something else." |
| `ambiguous: true`, `ask: [A, B, …]` | **Ask**, listing only `ask[]`: "Is this A or B?" Do not guess. |
| `ambiguous: true`, `ask: []` | Nothing matched: "Which tool is this from?" |

Always ask (the CLI marks these ambiguous every time): **Excel vs Google Sheets vs Omni table
calc** — one grammar, and an Omni `OFFSET` read as an Excel cell reference is wrong; and
**LookML vs Omni** for `${view.field}`. If the user already said which tool, skip the
question and use their answer.

Detection is sticky for the session: reuse the confirmed dialect for the next formula unless
its shape changes.

## Step 3 — Columns: three levels

Ask once: "Columns: **use placeholders**, **give me names**, or **point me at a Model**?"
Default to placeholders.

| Level | Flag | References become | Validation |
|---|---|---|---|
| 0 | none | `[TABLE::<source name>]`, listed as placeholders | no |
| 1 | `--columns '<json>'` | the mapped `[TABLE::COL]` | no |
| 2 | `--model <guid or exact name> --profile <p>` | the Model's real columns (by display name or physical name; formulas by `[formula_id]`) | `compile`, `execute` |

Level 1: turn whatever the user pasted (`Sales=ORDERS.SALES_AMT`, a list) into the JSON
`{"Sales": "ORDERS.SALES_AMT"}`. Add `"data_type": "DATE"` for date columns when known (DAX
date subtraction and Tableau date arithmetic depend on it), and `"key": true` for a primary
key.

Level 2: authenticate first (`ts auth whoami --profile <p>`; on failure send the user to
`/ts-profile-thoughtspot`). The Model is only read.

**An unresolved reference is a question, never a guess.** If the result has `unresolved[]`,
ask for each one, offering its `candidates` ("`[Custmer]` — did you mean **Customer**?"), then
re-run with a `--columns` entry for the confirmed mapping. A `COUNT(*)` with no key shows as
`[TABLE::<primary key>]`: ask which column is the table's key and re-run with `--key-column`.

## Step 4a — Translator-backed dialects

    ts formula translate '<formula>' --from <tableau|dax|qlik|sisense|snowflake|databricks> \
      [--columns '<json>'] [--model <guid> --profile <p>] [--name "<display name>"]

Pass the formula on stdin (`echo … | ts formula translate --from …`) when it contains quotes
the shell would mangle. Sisense: if the user has the JAQL context object, pass it with
`--context`; without it each `[key]` reads as a column named `key` (the CLI notes this).

Read: `formula`, `status`, `classification`, `role`, `references`, `unresolved`, `traps`,
`notes`, `verification.translator`, `tml`. Present per Step 5.

**`NEEDS_REVIEW` is a result, not a failure to hide.** `notes[]` says which of three things
happened, and the answer says it in plain words:

| `notes[]` starts with | Meaning | What you may offer |
|---|---|---|
| `known defect …` | the translator gets this construct wrong today; the fix is tracked (BL / branch named) | a hand-composed form from the maps, labelled as such |
| `the output calls …` / `the SQL operator …` / `'+' next to …` / `'=='` / `a bare TOTAL …` | the output guard caught something ThoughtSpot cannot parse | the same |
| anything else | the translator could not translate it | the map row's workaround (Step 5 item 8) |

Show `partial` (what the translator emitted) only labelled *rejected output*, never as an
answer.

## Step 4b — Map-backed dialects (Excel, Sheets, Omni, Sigma)

There is no translator; **you** compose the formula from the map, and the map — not you —
supplies the classification and the verification status.

1. Open the map for the confirmed dialect (References). Read its *How to read the tables*
   rules (Excel E1–E18, Sigma and Omni their own) and its gaps / *Unverified* section.
2. For **every function** in the formula, find its row. Record: section, the row's
   **Class**, its ThoughtSpot cell, and anything its Notes say about arguments. Operators,
   literals and references have rows in Sigma and Omni (*Operators and constructs*,
   *Operators, literals and references*); in Excel they are covered by the framing rules
   instead (E5: a cell is that row's value of its column, so `C2*D2` is `[T::C] * [T::D]`) —
   cite the rule, status **documentation only**.
3. Compose the formula from those cells only. Spell functions as the map does; check any
   function you are unsure of against `thoughtspot-formula-patterns.md`. Never use a
   function that appears in neither.
4. The formula's class is the **weakest** class of the rows used
   (`unmappable` < `structural` < `passthrough` < `direct (downgrade)` < `direct`).
5. A function with **no row**, or a row that is `unmappable`/`structural`: do not
   substitute something plausible. Give the row's workaround (a Model join for a lookup, a
   warehouse view, a UDF recipe) — Step 5 item 8.
6. Spelling: string literals are **single-quoted** in ThoughtSpot (`"Open"` → `'Open'`);
   double quotes are only for `sql_*_op` templates. A cell or range reference names a
   **column**: `B2` / `B:B` → ask the user for column B's header (or use `[TABLE::B]` as the
   placeholder), never `[TABLE::B2]`.
7. Run the composed formula through `ts formula translate '<formula>' --from thoughtspot`
   (any level): it resolves the references, adds the CLI's traps and role, and returns the TML
   — it translates nothing.

**Verification status of a map row** — pick the **first** that applies, and write it beside
the row in the answer. A live date counts only when it is about **the row's own ThoughtSpot
cell** — not about the native function the row was moved away from (Excel `EXACT` cites the
2026-10-06 probe of `=`, but its `sql_bool_op` cell was never probed), and a row-level
statement beats the map's header ("no row has been import-probed" predates the probes):

| Evidence for the row's ThoughtSpot cell | Write |
|---|---|
| a passthrough template, a multi-function composition, or listed under *Unverified* — with no live date for that exact cell | **unprobed** |
| "live-probed" / "live-verified" with a date for that cell (e.g. `ROUND`, E12) | **verified live (date)** |
| the row cites a named row of another map that itself carries a live date | **verified via \<map, row\>** |
| anything else | **documentation only** |

**Settled 2026-10-06** — apply these to **every** answer, translator- or map-backed, whatever
an older row says (see open-items OI-2…OI-5):

- **Case-sensitive comparison has no native form** (OI-4, BL-333): ThoughtSpot `=`,
  `contains` and `strpos` lowercase both sides. Excel `EXACT`/`FIND`, Sigma
  `Contains`/`StartsWith`/`EndsWith`/`Find`/`Like`, Omni `EXACT`/`FIND` and the
  contains-family filters are **passthrough** rows (`sql_bool_op ( "{0} = {1}" , … )`,
  `sql_bool_op ( "CONTAINS({0}, {1})" , … )`). Native `contains` is right only for a
  case-insensitive source (Sigma `ILike`, Excel `SEARCH`). A string literal passed as a
  `sql_bool_op` argument keeps its case (`sql_bool_op ( "{0} = {1}" , [d] , 'Engineering' )`
  compiled to `d = 'Engineering'` — verified live 2026-10-06, OI-4), so either form works.
- **Week start** (OI-2, BL-334): ThoughtSpot's week comes from the **Model's calendar**,
  Gregorian with a Monday start by default; `day_number_of_week` is fixed 1 = Monday. Never
  emit the `start_of_*` calendar-name argument and never ask for a calendar name. Any
  formula that assumes Monday is day one — weekday numbering, week alignment, `WEEKNUM` /
  ISO-week compositions, `NETWORKDAYS`-style arithmetic, `start_of_week` — gets the trap
  line *"assumes a Monday week start; diverges if the Model's calendar starts on another
  day"*. A source with an explicit fiscal or custom week/year setting (Excel `WEEKNUM`
  return types, Sigma/Omni fiscal settings, a DAX/Tableau fiscal year start) gets the note
  *"the week/fiscal definition comes from the Model's calendar, not from the formula"*.
- **`diff_months` / `diff_years` count boundaries crossed** (OI-3): Jan 31 → Feb 1 = 1. Excel
  `DATEDIF` `"M"`/`"Y"` (complete periods) needs the map's day-of-month correction; plain
  `diff_months` is not equivalent.
- **Aggregate passthrough name** (OI-5): ThoughtSpot has **no `sql_number_aggregate_op`** —
  the parser rejects it. Where a map row says `sql_number_aggregate_op`, emit
  **`sql_double_aggregate_op`** (live-accepted) with the same template, and say so in the
  traps line. `sql_double_op` *can* wrap an aggregate, but ThoughtSpot coalesces a NULL
  aggregate to 0 inside it.

Then, for anything map-backed, **offer `--validate compile` strongly** (Step 6): it is the
only thing that turns "unprobed" into evidence. The composed formula goes through the CLI as
`--from thoughtspot`, which resolves its references and translates nothing.

## Step 5 — Present (this order, every time)

Before presenting, **ask for a display name** unless the user gave one ("Name for this
formula? (default: *Translated Formula*)"), and pass it as `--name`: it becomes the TML id
`formula_<name>`, and two answers pasted into one Model with the default name collide.

**Role.** `MEASURE` when the formula aggregates, else `ATTRIBUTE` — a row-level amount such
as `[T::Qty] * [T::Price]` is an ATTRIBUTE formula. If the user wants it summed in searches,
say so and offer the aggregated form (`sum ( [T::Qty] * [T::Price] )`, a MEASURE); never
silently change the role.

1. **The formula**, in a code block.
2. **Classification + one-line why** — e.g. ``direct (downgrade)`: matches Sigma only when the
   Answer's columns are exactly the parent groupings plus the sort column``.
3. **Traps applied** — only those that fired (`traps[]`, plus any of Step 4b's settled
   facts the formula touches).
4. **References table** — source → ThoughtSpot, placeholders flagged:

   | Source | ThoughtSpot | |
   |---|---|---|
   | `[Sales]` | `[TABLE::Sales]` | placeholder |

5. **Verification status** — translator-backed: "**deterministic translator output**
   (`<verification.translator>`) — not verified against ThoughtSpot". The translator's tests
   show the construct is handled, not that this output is right, so never call it
   "verified" or "covered". Map-backed: each row's status from Step 4b. Either: the
   `compile`/`execute` result when run — the only thing that makes it **verified**. **An
   unprobed composition says "unprobed" on its own line, never "verified".**
6. **TML snippet** — `tml` from the CLI, or for map-backed formulas the same shape:
   ```yaml
   formulas:
   - id: formula_<Display Name>
     name: <Display Name>
     expr: "<formula>"
   columns:
   - name: <Display Name>
     formula_id: formula_<Display Name>
     properties:
       column_type: MEASURE        # ATTRIBUTE when the formula does not aggregate
       aggregation: SUM            # columns[] only, never formulas[]; omit for ATTRIBUTE
   ```
   Spaces stay in the id. Paste both entries into the Model's `formulas:` and `columns:`.
7. **`passthrough`** — the warning: the SQL runs in the warehouse, **Snowflake syntax is
   assumed** (name it; other warehouses may differ), ThoughtSpot cannot plan around it, and
   the `sql_*_op` variant fixes the column's type and role (Ossie map E7).
8. **`NEEDS_REVIEW` / `unmappable`** — the reason (`notes[]`), the original kept
   (`original_kept`), and the map's nearest workaround. **Never a plausible-looking
   substitute.**

## Step 6 — Validate (level 2 only)

**Always offer `--validate compile` when a Model is available** and validation has not run —
for translator-backed answers too (it creates nothing); **recommend** it for map-backed
answers. Without a Model, say the answer is unvalidated and that pointing at a Model would
let you check it. It needs every reference resolved (no placeholders, no `unresolved[]`).

    ts formula translate '<formula>' --from <dialect> --model <guid> --profile <p> \
      --name "<display name>" --validate compile     # parse check; creates NOTHING
    … --validate execute                             # + compiled SQL and 5 rows

| Tier | What it does | Objects created |
|---|---|---|
| `compile` | Imports a scratch copy of the Model with `VALIDATE_ONLY` (OI-1): a malformed expression, unknown function or column, or wrong arity is rejected with the parser's message | none |
| `execute` | The same check, then imports `ZZ_FORMULA_PROBE_<timestamp>_DELETE_ME` as a new Model, runs AgentQL `generate-sql` and `fetch-data … LIMIT 5` (one formula, one grouping attribute), deletes it, confirms it is gone | one, deleted |

**Map-backed formulas:** validate the formula you composed with `--from thoughtspot` (it is
already ThoughtSpot syntax: the CLI only resolves its references against the Model, so write
them as `[Column Name]` or `[TABLE::Column]`). Until that has run, call the answer
**unvalidated**.

Read `verification.result` (`OK` / `FAILED` / `NOT_RUN`) and `verification.error` verbatim.
Show `verification.sql` and `verification.rows` for `execute`.

**Cleanup is not optional.** Exit code 1 means a scratch Model could not be confirmed deleted:
stderr names every remaining GUID. Repeat each GUID to the user with the command:

    ts metadata delete <guid> --profile <p>

## Step 7 — Loop

"Another formula?" Reuse the confirmed dialect and context unless the input changes shape.

## Known limitations

- **Map-backed dialects have no code behind them**: the composition is yours, from the map
  rows; only `--from thoughtspot --validate` puts evidence behind it. v2 codifies Excel, then
  Sigma (spec §3.3).
- **Translator gaps surface as `NEEDS_REVIEW`, by design.** Example: Qlik's translator only
  converts `Count(DISTINCT x)` as a whole expression; inside a larger one the CLI's guard
  catches the leftover `DISTINCT` and refuses rather than emit an invalid formula. The output
  guard also rejects any function outside the ThoughtSpot formula catalog, a SQL operator
  read as a column (`ILIKE`, `RLIKE`), `==`, a bare `TOTAL`, and `+` on strings.
- **Known translator defects are downgraded until their fixes land:** Databricks `DATEDIFF`
  argument order (fix/databricks-datediff-order) and the day-of-week numbering of Snowflake
  `DAYOFWEEK`, Databricks `dayofweek` and Tableau `DATEPART('weekday')` (BL-334) come back
  `NEEDS_REVIEW`; `ZEROIFNULL` (BL-226, unverified) and a dropped Tableau `ZN()` come back
  `APPROXIMATED` with a trap.
- **A string comparison translated from a case-sensitive dialect** (Tableau, Snowflake,
  Databricks) comes back `APPROXIMATED`: ThoughtSpot compares case-insensitively (OI-4,
  BL-333), so values differing only in case answer differently.
- **Tableau `DATEDIFF('week', …)`** comes back as `diff_days ( … ) / 7` — fractional 7-day
  spans, not week boundaries — so the CLI reports it `APPROXIMATED` / `direct (downgrade)`
  with a trap line.
- **Level 2 data types** come from the Model's Table TMLs, best effort; a column whose type
  could not be read is treated as non-date.
- `compile` returns no SQL — only `execute` compiles a query.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-10-06 | Initial release — one formula from Tableau, DAX, Qlik, Sisense, Snowflake or Databricks via `ts formula translate` (ts-cli 0.157.0), and Excel / Sheets / Omni / Sigma from the function maps; scored dialect detection with must-ask ties; three column-context levels; traps, references and TML snippet; `compile` (VALIDATE_ONLY, no objects) and `execute` (scratch Model, deleted) validation |
