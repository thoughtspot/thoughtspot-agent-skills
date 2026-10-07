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
| [../../../docs/function-maps/ts-excel-function-mapping.md](../../../docs/function-maps/ts-excel-function-mapping.md) | Excel and Omni table calcs (map-backed); Google Sheets' fallback for every name the Sheets map does not row |
| [../../../docs/function-maps/ts-sheets-function-mapping.md](../../../docs/function-maps/ts-sheets-function-mapping.md) | Google Sheets (map-backed) — a **delta** on the Excel map; read it first |
| [../../../docs/function-maps/ts-sigma-function-mapping.md](../../../docs/function-maps/ts-sigma-function-mapping.md) | Sigma (map-backed) |
| [../../../docs/function-maps/ts-omni-function-mapping.md](../../../docs/function-maps/ts-omni-function-mapping.md) | Omni modelling layer, table calcs, filters (map-backed) |
| [references/open-items.md](references/open-items.md) | OI-1…OI-5 — the live probes the traps rest on |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | Auth (only for a Model / validation) |

## How it works

| Source | Backing | How this skill translates it |
|---|---|---|
| Tableau, DAX, Qlik, Sisense, Snowflake SQL, Databricks SQL, **Excel, Google Sheets** | **translator** — the converter skills' own code; for Excel / Sheets `ts_cli/excel/`, whose rules are the maps' *Translator coverage* rows | `ts formula translate --from <dialect>`. The CLI result is the answer; do not quietly rewrite it. If it returns `NEEDS_REVIEW` (a translator gap, a known defect, or an output guard), explain the reason and you **may** offer a hand-composed alternative from the maps or `thoughtspot-formula-patterns.md`, labelled *hand-composed, not translator output* and validated if possible. A wrong translation is fixed in the translator, which also fixes the converter |
| Omni table calc, Sigma, Omni modelling layer — and an Excel / Sheets construct the translator returned `NEEDS_REVIEW` | **map** — `docs/function-maps/` | You translate from the map rows (Step 4b), citing each row. No code stands behind it, so validation is **recommended**. For Excel / Sheets this is only the fallback, labelled *hand-composed from the map — not translator output* |
| LookML | none | Point to `/ts-convert-from-looker`; out of scope here |

The CLI wraps the existing translators (`translate_single`, `translate_dax`, Qlik
`translate`, `translate_jaql`, `sv_sql` and `mv_sql` `translate_sql_expr`, and the Excel /
Sheets `translate_excel`) and adds what they do not: one recording resolver for every column reference, the dialect-independent
trap lines, a `COUNT(*)` repair, role inference, a TML snippet, and validation.

## Step 0 — Overview

Display, then go straight to Step 1 (no Y/N gate — nothing is written anywhere):

    ts-object-formula-translate — one formula in, a ThoughtSpot formula out.

      1. Paste the formula (several? they're answered in order)
      2. I guess the language and confirm in one line
      3. Columns: placeholders, your names, or a Model
      4. Translate — and ask what it depends on (a column's type; per row or KPI)
      5. Say exactly how sure that is
      6. Optional: prove ThoughtSpot compiles / runs it (needs a Model)

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

Always ask (the CLI marks these ambiguous): **Excel vs Google Sheets vs Omni table calc** —
one grammar, and an Omni `OFFSET` read as an Excel cell reference is wrong — unless a
**Sheets-only function** fired (`QUERY`, `ARRAYFORMULA`, `IMPORTRANGE`, `REGEXMATCH`,
`COUNTUNIQUE`, the operator functions `ADD`/`EQ`/`GT`…; the Sheets map's Sheets-only rows):
that settles Google Sheets. `TO_DATE`, `SPLIT`, `FLATTEN`, `POW`, `JOIN`, `MINUS`, `ISDATE`
and `DIVIDE` are also Snowflake/Databricks/Tableau/Qlik/DAX spellings, so they count for
Sheets only beside a leading `=` or a cell reference. And always ask **LookML vs Omni** for
`${view.field}`. If the user already said which tool, skip the question and use their answer.

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
`{"Sales": "ORDERS.SALES_AMT"}` — or pass the shorthand as-is: `--columns 'A=ORDERS.ORDER_DATE,
B=ORDERS.AMOUNT'` (the natural form for spreadsheet column letters; an unmapped A1 cell comes
back as a `[TABLE::B]` placeholder with a *NEEDS_REVIEW: A1 reference* note — ask for column
B's header). For Excel / Sheets add `"data_type"` whenever it is known: it decides whether `&`
wraps an operand in `to_string` (ThoughtSpot rejects a number in `concat` **and** Text in
`to_string`) and whether `-` / `+` on a column is date arithmetic. Add `"data_type": "DATE"` for date columns when known (DAX
date subtraction and Tableau date arithmetic depend on it), and `"key": true` for a primary
key.

Level 2: authenticate first (`ts auth whoami --profile <p>`; on failure send the user to
`/ts-profile-thoughtspot`). The Model is only read.

**An unresolved reference is a question, never a guess.** If the result has `unresolved[]`,
ask for each one, offering its `candidates` ("`[Custmer]` — did you mean **Customer**?"), then
re-run with a `--columns` entry for the confirmed mapping. A `COUNT(*)` with no key shows as
`[TABLE::<primary key>]`: ask which column is the table's key and re-run with `--key-column`.

## Step 4a — Translator-backed dialects

    ts formula translate '<formula>' --from <tableau|dax|qlik|sisense|snowflake|databricks|excel|google_sheets> \
      [--columns '<json>'] [--model <guid> --profile <p>] [--name "<display name>"] [--role measure|attribute]

**Excel / Google Sheets: `--role`.** Pass it when the user already said it ("as a KPI", "per
row", "a measure"); otherwise run without it and let Step 4c ask, only when it matters. It
changes the formula, not just the label: a sheet formula over `[@Col]` is a per-row value, and
with `--role measure` the CLI rebuilds it at the right grain — additive expressions as the sum
of each column (`sum ( a ) - sum ( b )`), a ratio as a **ratio of totals** (`safe_divide (
sum ( num ) , sum ( den ) )`, never the sum of per-row ratios), a numeric `IF(…,1,0)` flag
left row-level (its column aggregation totals it). A text result stays an ATTRIBUTE with a
`group_aggregate` trap. Without `--role` the row-level translation's own role is inferred; for
a non-ratio that is safe (a per-row amount summed in a search gives the same total). Present
the CLI's result — do not re-compose it from the map.

Pass the formula on stdin (`echo … | ts formula translate --from …`) when it contains quotes
the shell would mangle. **Qlik `Weekday(d)` with one argument** depends on the app's
`FirstWeekDay`, which lives in the load script a pasted formula does not have: ask *"What is
the app's FirstWeekDay? (6 = Sunday, usual for US apps; 0 = Monday otherwise)"* and pass it
as `--first-week-day`. Without it the CLI returns `NEEDS_REVIEW`. Sisense: if the user has the JAQL context object, pass it with
`--context`; without it each `[key]` reads as a column named `key` (the CLI notes this).

Read: `formula`, `status`, `classification`, `role`, `references`, `unresolved`, `traps`,
`notes`, `verification.translator`, `tml`, and the two question fields `needs_types`,
`role_ambiguous` / `role_options`. Ask per Step 4c, then present per Step 5.

**`NEEDS_REVIEW` is a result, not a failure to hide.** `notes[]` says which of three things
happened, and the answer says it in plain words:

| `notes[]` starts with | Meaning | What you may offer |
|---|---|---|
| `known defect …` | the translator gets this construct wrong today; the fix is tracked (BL / branch named) | a hand-composed form from the maps, labelled as such |
| `the output calls …` / `the SQL operator …` / `'+' next to …` / `'=='` / `a bare TOTAL …` | the output guard caught something ThoughtSpot cannot parse | the same |
| anything else | the translator could not translate it | the map row's workaround (Step 5 item 8) |

Show `partial` (what the translator emitted) only labelled *rejected output*, never as an
answer.

## Step 4b — Map-backed dialects (Omni, Sigma) and the Excel / Sheets fallback

For Omni and Sigma there is no translator; **you** compose the formula from the map, and the map
— not you — supplies the classification and the verification status. **Excel and Google Sheets
come here only when `ts formula translate --from excel|google_sheets` returned `NEEDS_REVIEW`**
(its `notes[]` cite the map row): compose that construct from the cited row, label the answer
*hand-composed from the map — not translator output*, and validate it.

1. Open the map for the confirmed dialect (References; `detect`'s candidate names it as
   `map`). Read its *How to read the tables* rules (Excel E1–E18, Sheets E1–E9, Sigma and
   Omni their own) and its gaps / *Unverified* section.
   **Google Sheets reads two maps, in order** (the Sheets map's E1; `detect` names the
   second as `fallback_map`): a name **rowed in the Sheets map** takes that row — it either
   has no Excel namesake or behaves differently from it (`REGEXEXTRACT` capture groups,
   default `SPLIT`, Unicode `CODE`, one-argument `IFERROR`, `QUERY`); a name marked **‡** in
   its reconciliation list is an Excel compatibility alias and takes its **successor's**
   Excel row (`STDEV` → `STDEV.S`); **any other name takes its Excel map row** unchanged. For
   each row, cite the map it came from (*Sheets map, Text, `SPLIT`* / *Excel map via Sheets E1,
   Lookup, `VLOOKUP`*). Sheets traps that apply whatever a row says:
   - **`QUERY` is structural** — its `select` / `where` / `group by` / `order by` become the
     Model and Answer's columns, filters, attributes and sort, not a formula (map E9 and its
     clause table). Its string matching is **case-sensitive** where ThoughtSpot's `=` is
     not (E4), so a QUERY string filter needs the passthrough the clause table gives.
   - **`ARRAYFORMULA` is a no-op only when the inner expression is element-wise**
     (arithmetic, `IF`, per-cell text and date functions — drop it and translate the inside).
     Around `COUNTIF`/`SUMIF` over the same range it is a fixed-grain `group_aggregate`, and
     around `AND`/`OR` it collapses to one value (E6).
   - **One-argument `IFERROR` means NULL, not 0**: `IFERROR(A2 / B2)` is plain
     `[a] / [b]` (NULL on a zero divisor), never `safe_divide` (which returns 0).
     **There is no `nullif`** in ThoughtSpot — it is rejected at import (probe record §7,
     BL-339); the CLI's output guard refuses it.
   - **`NETWORKDAYS` / `NETWORKDAYS.INTL` holiday arrays hold serials or `DATE()`
     values, never text dates**: convert each by its form (a serial via E3, `DATE(y, m, d)`
     folded to one `to_date` literal), then apply the Excel row's holiday term.
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
an older row says (see open-items OI-2…OI-5, and probe record §7):

- **`nullif` and `isnotnull` do not exist** (VALIDATE_ONLY rejects them; BL-339). Never write
  them: `safe_divide ( a , b )` is 0 on a zero divisor, plain `a / b` is NULL on a zero
  divisor, `if ( b = 0 ) then null else a / b` is an explicit NULL (`null` is accepted in
  either branch), and "is not null" is `not ( isnull ( x ) )`. The CLI's output guard refuses
  both names.
- **`concat` takes N arguments, all Text**: wrap numbers (and dates) in `to_string`, and only
  them — `to_string` rejects a Text argument.
- **Zero only when the source asks for zero** (user decision 2026-10-07, BL-357). A SQL
  `x / NULLIF(y, 0)` is plain `x / y`, never `safe_divide`; `COALESCE(x / NULLIF(y, 0), 0)` (and
  `IFNULL`/`NVL`/`ZEROIFNULL`) is `ifnull ( safe_divide ( x , y ) , 0 )` — `safe_divide` alone is NULL
  on a NULL operand; any other default is `ifnull ( x / y , d )`; Snowflake `DIV0` keeps NULL for a
  NULL dividend. The "`safe_divide` for ratios" convention still holds for Excel ratios and for a
  plain-division ratio whose source states no NULL intent. Mapping docs: the Snowflake "Division
  and zero" section, the Databricks "safe_divide Pattern".
- **Databricks sources run non-ANSI in ThoughtSpot** (BL-358): an overflow wraps, an
  out-of-range cast clamps and a bad cast or zero divisor is NULL, where an ANSI source raises.
  The CLI adds a note to any Databricks `CAST`, and downgrades arithmetic with a 10-digit or
  longer integer literal to APPROXIMATED (an overflow there is a wrong number). Say so in the
  answer.

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
- **Aggregate passthrough name** (OI-5, BL-335): ThoughtSpot has **no
  `sql_number_aggregate_op`** (nor `sql_number_op`) — the parser rejects them. Use
  `sql_double_aggregate_op` (or the int/string/date/date_time/bool family); the shared maps
  were corrected in BL-335, so an older copy naming `sql_number_aggregate_op` is wrong.
  `sql_double_op` *can* wrap an aggregate, but ThoughtSpot coalesces a NULL aggregate to 0
  inside it.

Then, for anything map-backed, **offer `--validate compile` strongly** (Step 6): it is the
only thing that turns "unprobed" into evidence. The composed formula goes through the CLI as
`--from thoughtspot`, which resolves its references and translates nothing.

## Step 4c — Ask what the translation depends on

After detection and translation, **before presenting**, the CLI may report two things it could
not decide. Each changes the formula, so ask; never pick silently.

**Skip** the type question when a Model was given (`--model`: the types come from the Model),
and the role question when the user already stated the role. Both fields are empty / `false`
for dialects where they do not apply — today only Excel and Google Sheets set them.

**1. Per row, or a KPI that rolls up?** — when `role_ambiguous` is `true` (a ratio, including
inside `IFERROR` or `safe_divide`, and no `--role`). Show both `role_options[]` with their
formula-editor form and the one-line meaning:

    Formula 1 has a ratio — per row, or as a KPI that rolls up?
      a) Per row     safe_divide ( TOTAL_REVENUE - TOTAL_COGS , TOTAL_REVENUE )
                     the Excel cell, row by row; summed in a search it adds per-row ratios
      b) KPI         safe_divide ( sum ( TOTAL_REVENUE ) - sum ( TOTAL_COGS ) , sum ( TOTAL_REVENUE ) )
                     a ratio of totals — right for any grouping (region, month, total)

Take the meanings from `role_options[].meaning` (shortened is fine); the formulas verbatim.
Using the per-row form as a measure makes ThoughtSpot sum or average per-row ratios — say so
if the user picks (a) but describes a KPI.

**2. Column types** — when `needs_types[]` is non-empty. Ask **once per formula**, listing
every column, with its `reason` and the `suggested_type` as a default to confirm:

    A few columns change the formula depending on their type:
      - CONTRACT_TERM_MONTHS (text join) — a number? (likely yes, from the name)
      - REGION (blank test) — no guess from the name: number, text or date?
    Reply "yes to all suggestions", or correct any.

`confidence: high` reads "likely yes, from the name", `medium` "probably", `low` (no
suggestion) asks the type outright. Accept **"yes to all suggestions"**; a column with no
suggestion still needs an answer.

**Then re-run** with `--role <answer>` and `--columns` carrying each confirmed `data_type`
(`suggested_data_type`, or the user's correction: `INT64` / `DOUBLE` for numbers, `VARCHAR`,
`DATE`, `DATE_TIME`), keeping any mapping from Step 3:

    ts formula translate '<formula>' --from excel --role measure \
      --columns '{"CONTRACT_TERM_MONTHS": {"table": "TABLE", "column": "CONTRACT_TERM_MONTHS", "data_type": "INT64"}}'

The re-run's `needs_types` is empty and `role_ambiguous` false; present that result.

**Batch mode** (several formulas): translate them all first, then group the questions —
**types once per column across the whole batch** (one list, each column named once, with the
formulas it appears in), and **the role per formula** with a *"same for all ratios"* option
("a / b for each, or one answer for all"). Re-run each formula with its answers.

## Step 5 — Present (this order, every time)

Before presenting, **ask for a display name** unless the user gave one ("Name for this
formula? (default: *Translated_Formula*)"), and pass it as `--name`: it becomes the TML id
`formula_<name>`, and two answers pasted into one Model with the default name collide.
**Any name you coin** — the default, a helper formula a map composition needs — uses `_`
for spaces (`Total_Days`, `Start_Weekday`), so the editor form can reference it bare and
both forms share one name. A user-supplied name keeps its spaces.

**Two forms of every formula.** The CLI returns both: `formula_editor` (paste into the
ThoughtSpot **formula editor** — references by name, no brackets: `Total_Days - floor (
Total_Days / 7 )`) and `formula` / `tml` (paste into a Model's **TML** `formulas[]` —
bracketed references, which TML requires: `[formula_Total_Days] * 2` and `[TABLE::col]` are
accepted, bare `Total_Days` and display-name `[Total_Days]` are rejected; verified
VALIDATE_ONLY on se-thoughtspot 2026-10-06). A name with spaces cannot be referenced bare, so
it stays in brackets in the editor form; say that renaming it with underscores in the Model
would allow bare references. The bare-reference editor syntax is the user's ThoughtSpot
domain guidance — the editor is not reachable through the API — so `--validate` checks only
the TML form; say so if asked. For a map-backed answer, write both forms yourself by the
same rules (or get them from `--from thoughtspot`).

**Role.** `MEASURE` when the formula aggregates, else `ATTRIBUTE` — a row-level amount such
as `[T::Qty] * [T::Price]` is an ATTRIBUTE formula. If the user wants it summed in searches,
say so and offer the aggregated form (`sum ( [T::Qty] * [T::Price] )`, a MEASURE); never
silently change the role.

1. **Formula-editor form** (`formula_editor`), in a code block, headed *"Paste into the
   formula editor"* — plus the rename note from `formula_editor_notes[]` if any name stayed
   bracketed.
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
6. **TML form** — headed *"For TML (`formulas[]` of the Model) — brackets required"*: `tml`
   from the CLI, or for map-backed formulas the same shape:
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
   A user-supplied name keeps its spaces in the id; a coined one has underscores. Paste both
   entries into the Model's `formulas:` and `columns:`. A helper formula is referenced by id
   here (`[formula_Total_Days]`) and by bare name in the editor form (`Total_Days`).
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

## Step 6b — ThoughtSpot → Excel (on request)

If the user wants a ThoughtSpot formula written as an Excel formula ("how would I do this in
Excel?"), run the reverse direction — it is deterministic code, not a map composition:

    ts formula translate '<ThoughtSpot formula>' --from thoughtspot --to excel [--table <Excel Table name>]

Show `formula` (starts with `=`; row-level references are `[@Col]`, references inside an
aggregate `Table1[Col]`), then `traps[]` (always the blank-vs-NULL caveat: Excel treats a blank
as 0) and `notes[]`. `NEEDS_REVIEW` (windows, `rank`, `sql_*_op`, a `query_groups ( )` grain)
is a result: give the reason. Ask for the Excel Table's name if `Table1` is not it.

## Step 7 — Loop

"Another formula?" Reuse the confirmed dialect and context unless the input changes shape.

## Known limitations

- **Map-backed dialects have no code behind them**: the composition is yours, from the map
  rows; only `--from thoughtspot --validate` puts evidence behind it. Excel and Google Sheets
  are translator-backed since 1.2.0; Sigma is next (spec §3.3).
- **Excel / Sheets cover the maps' *Translator coverage* rows** (114 Excel functions since
  1.8.0, 22 Sheets delta rows, the criteria table); any other function is `NEEDS_REVIEW` citing its row. The
  60-formula acceptance workbook (`tools/ts-cli/tests/fixtures/excel_regression/`) translates
  VALIDATE_ONLY-clean; two of its reviewed answers differ by rule — the translator keeps the
  source's own test (`= 0`) and never introduces a column the formula does not reference.
- **Translator gaps surface as `NEEDS_REVIEW`, by design.** Example: Qlik's translator only
  converts `Count(DISTINCT x)` as a whole expression; inside a larger one the CLI's guard
  catches the leftover `DISTINCT` and refuses rather than emit an invalid formula. The output
  guard also rejects any function outside the ThoughtSpot formula catalog, a SQL operator
  read as a column (`ILIKE`, `RLIKE`), `==`, a bare `TOTAL`, and `+` on strings.
- **Known translator defects are downgraded until their fixes land:** `ZEROIFNULL` (BL-226,
  unverified) and a dropped Tableau `ZN()` come back `APPROXIMATED` with a trap. (The BL-334
  weekday numbering and BL-336 `DATEDIFF` order defects were fixed in the translators by
  #565 and #564; their entries are gone.)
- **A string comparison translated from a case-sensitive dialect** (Tableau, Snowflake,
  Databricks) comes back `APPROXIMATED`: ThoughtSpot compares case-insensitively (OI-4,
  BL-333), so values differing only in case answer differently.
- **Tableau `DATEDIFF('week', …)`** comes back as `diff_days ( … ) / 7` — fractional 7-day
  spans, not week boundaries — so the CLI reports it `APPROXIMATED` / `direct (downgrade)`
  with a trap line.
- **Excel / Sheets: a translation ThoughtSpot would reject on type is never TRANSLATED**
  (ts-cli 0.161.0, fidelity M1). A type checker over the emitted formula
  (`ts_cli/excel/typecheck.py`) knows each function's argument types — ThoughtSpot's
  *Numeric* slots take an **integer** (a DOUBLE is rejected by `substr`, `left`, `right`,
  `add_days`, `add_months`, `mod` and `to_double`), `to_string` has no one-argument form for a
  date, `if` branches share one type. A provable error comes back `NEEDS_REVIEW` with a
  `type check: …` note; a column of unknown type in an integer or conversion slot is asked in
  `needs_types` (reason `typed argument`) — so pass `data_type` in `--columns`. Excel's own
  coercions are written out: a text date → `to_date ( '…' , '%Y-%m-%d' )` (ambiguous
  day/month order is `NEEDS_REVIEW`), a serial number → its date, a number or boolean in a text
  function → its text (`'TRUE'` / `'FALSE'`, not `to_string`'s `true`), a date there → its
  serial number, numeric text in arithmetic → `to_double` (APPROXIMATED — non-numeric text **fails the whole query**, so `IFERROR(VALUE())` / `ISNUMBER(VALUE())` use `TRY_TO_DOUBLE`), a DOUBLE count →
  `floor`, mixed `IF` / `IFERROR` branches → one type (APPROXIMATED). The table is the Excel
  map's *Implicit type coercion* section.
- **Excel trigonometry is the identity form** (1.8.0): ThoughtSpot `sin` … `atan` take and
  return **radians**, as Excel does (live 2026-10-07, BL-364), so `SIN(x)` is `sin ( x )`. A
  map-backed answer from another dialect's map that multiplies by `180 / 3.14159…` is wrong
  for every non-zero input — the Tableau, Ossie, Omni and Sigma maps (and the Tableau
  translator) still do, until BL-364 lands; drop the conversion when composing from them.
- **Excel `TEXT` translates a subset of format codes** (1.8.0): plain numbers (`0`, `0.00`,
  `#,##0.00`, zero-padded), percentages, and date / time codes (`yyyy yy mmmm mmm mm dd ddd
  dddd hh ss` with `- / : . ,` and space). Everything else — `$`, fractions, scientific,
  conditional sections, single `m` / `d`, `AM/PM` — is `NEEDS_REVIEW`; a ThoughtSpot column
  number format is often the better home. A number-format `TEXT` over a column is
  APPROXIMATED: a negative value that rounds to zero prints `-0.00`.
- **The Excel `B` byte functions** (`LEFTB`, `FINDB`, …) come back APPROXIMATED as their plain
  function: Excel counts a double-byte character as 2 only with a DBCS default language.
- **Known divergence, not a defect: constant decimal arithmetic** (Excel only, BL-351). The
  warehouse computes literals as exact decimals, Excel as binary doubles, so an all-literal
  sum like `=0.1+0.2` can differ from Excel's in the 13th significant digit or beyond. The
  translation carries a trap saying so and stays TRANSLATED; over a DOUBLE column both
  compute in double.
- **Level 2 data types** come from the Model's Table TMLs, best effort; a column whose type
  could not be read is treated as non-date.
- `compile` returns no SQL — only `execute` compiles a query.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.8.0 | 2026-10-07 | Excel coverage pass (ts-cli v0.164.0, fidelity M1): 43 more Excel functions are translator-backed, chosen by how many corpus cases they blocked — `CHAR` / `UNICHAR` / `CODE` / `UNICODE`, `SIN` … `ATAN` (radians, the identity form; the map's degrees rule was wrong, BL-364), `ATAN2`, the hyperbolic family, `DEGREES`, `RADIANS`, `PI`, `FLOOR.MATH`, `CEILING.PRECISE`, `FLOOR.PRECISE`, `ISO.CEILING`, `TRUNC`, `EVEN`, `ODD`, `QUOTIENT`, `LOG`, `FACT`, `REPLACE`, the `B` byte variants, `FIND` / `SEARCH` with `start_num`, `TEXT` (a format-code subset), `DATE`, `ISTEXT` / `ISNONTEXT` / `ISLOGICAL`. NEEDS_REVIEW over the 2,463 eligible M1 cases fell from 70% to 33%. Fixes 1.5.0's DOUBLE precision snap, which made `ROUNDUP` / `CEILING` jump a step on exact values (3.0 → 3.1): now a 1e-9 nudge |
| 1.7.0 | 2026-10-07 | The Snowflake and Databricks translators it wraps (ts-cli v0.163.0, formula fidelity M2, BL-357..362): NULLIF divisions are plain `/` and zero-default ratios `ifnull ( safe_divide ( … ) , 0 )` (zero only when the source asks for zero); `DIV0` / `DIV0NULL` NULL-guarded; Databricks `BIGINT` casts 64-bit, `DECIMAL` / Snowflake `NUMBER(p,s)` / `TO_NUMBER` rounding to scale; `DIV`, `FLOOR`/`CEIL` with a scale, `%`, `\|\|`, `LIKE`/`ILIKE`/`RLIKE`, n-ary `COALESCE`, `NVL2`, `try_divide` and more translate; `ZEROIFNULL` is `ifnull`. New BL-358 traps for Databricks casts (note) and overflow-prone literals (APPROXIMATED). Takes 1.7.0 because the concurrent Excel coverage branch claims 1.6.0 |
| 1.5.0 | 2026-10-07 | Excel / Google Sheets (ts-cli v0.161.0, formula fidelity M1, BL-346..355): a type checker over the emitted formula turns every provable type error into `NEEDS_REVIEW` (a `type check:` note) instead of an import failure reported TRANSLATED, and asks a column's type (`needs_types`, reason `typed argument`) when an integer or conversion slot depends on it. Excel's implicit coercion is written out (text dates → `to_date`, serial numbers, numbers / booleans / dates into text, numeric text into arithmetic, DOUBLE counts → `floor`, one type across `IF` / `IFERROR` branches). Fixed silent wrong answers: `CEILING.MATH` sign and mode, a zero `CEILING` significance (0, not NULL), `ROUNDUP` / `ROUNDDOWN` beyond 6 digits, a boolean joined into text (`TRUE`), a text function over a date (its serial). Constant decimal arithmetic is a documented divergence (BL-351). A DOUBLE is snapped before `ceil` / `floor`; `VALUE` of non-numeric text fails the query, so `IFERROR(VALUE())` / `ISNUMBER(VALUE())` use `TRY_TO_DOUBLE`; cross-type comparison folds, DOUBLE-to-text and slashed day/month dates are APPROXIMATED with a trap |
| 1.4.0 | 2026-10-06 | The Snowflake and Databricks translators it wraps fix `SUBSTR` (zero-based start), `DATEDIFF(year)` and the other units, `MONTHS_BETWEEN` (pass-through) and `TO_CHAR(x, fmt)` (pass-through) — BL-340..343, BL-345, ts-cli v0.160.0. New: Snowflake `DATEDIFF(week)` / `DATEDIFF(hour)` and every Databricks 3-argument `DATEDIFF` come back as exact `sql_int_op` pass-throughs; Databricks `DATEDIFF(DAY, …)` is native `diff_days` when `--columns` types both arguments DATE. A `diff_weeks` in any translation carries a Monday-week-start trap |
| 1.3.0 | 2026-10-06 | New Step 4c: before presenting, ask *per row or a KPI that rolls up?* when `role_ambiguous` (showing both `role_options`), and the column types listed in `needs_types` with their name-based suggestions ("yes to all suggestions" accepted); re-run with `--role` and typed `--columns`; skipped with a Model or a stated role; grouped per column / per formula in a batch (ts-cli 0.159.0). Excel / Sheets no longer ask the role up front for every formula |
| 1.2.0 | 2026-10-06 | Excel and Google Sheets are translator-backed (`ts formula translate --from excel` or `--from google_sheets`, ts-cli 0.158.0): ask the intended role and pass `--role` (MEASURE builds additive sums and ratios of totals); the map is only the labelled fallback for `NEEDS_REVIEW`; new Step 6b, ThoughtSpot → Excel via `--to excel`; `nullif` / `isnotnull` do not exist and `concat` needs Text arguments (BL-339) |
| 1.1.0 | 2026-10-06 | Google Sheets reads the Sheets delta map first, then the Excel map for names it does not row (‡ aliases → their successor); `ts formula detect` (ts-cli 0.157.1) settles Sheets on a Sheets-only function and reports `fallback_map`; Sheets traps for `QUERY`, `ARRAYFORMULA`, one-argument `IFERROR` and holiday arrays (BL-338) |
| 1.0.0 | 2026-10-06 | Initial release — one formula from Tableau, DAX, Qlik, Sisense, Snowflake or Databricks via `ts formula translate` (ts-cli 0.157.0), and Excel / Sheets / Omni / Sigma from the function maps; scored dialect detection with must-ask ties; three column-context levels; traps, references and TML snippet; `compile` (VALIDATE_ONLY, no objects) and `execute` (scratch Model, deleted) validation |
