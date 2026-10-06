# ts-object-formula-translate — design

**Date:** 2026-10-06
**Status:** approved; v1 implemented (2026-10-06 — see §12 for deviations)
**Branch:** `feat/formula-translate-spec`
**Depends on:** `fix/round-increment` (BL-331) merged first. The translators this skill
routes to emit wrong `round` output until then.
**Inputs:** the function maps on `feat/bi-function-maps` (`docs/function-maps/`: Excel,
Sigma, Omni) and the converter mapping docs under `agents/shared/mappings/`.

---

## 1. Intent

A user pastes one formula written for another tool and gets back the ThoughtSpot
formula. The answer says how faithful the translation is and, when the user asks,
proves that ThoughtSpot compiles it.

### Requirements (from the user)

1. Paste a formula and get a ThoughtSpot formula back.
2. Guess the input syntax where possible, and confirm the guess.
3. Columns can be supplied, or the output can use example (placeholder) columns.

### Success

For any supported source language, one answer that gives:
- the ThoughtSpot formula
- its classification (`direct` / `direct (downgrade)` / `passthrough` / `unmappable`)
- the specific traps that applied
- its verification status
- a TML snippet ready to paste

No output may look more certain than its evidence. A translation that rests on an
unprobed composition says so on the same line.

### Non-goals (v1)

- Translating whole workbooks or models. That is the `ts-convert-from-*` skills' job.
- Writing the formula into a user's Model. The skill hands over TML and never edits an
  existing object.
- ThoughtSpot → other tools. The reverse direction is a natural v2. The to-Snowflake and
  to-Databricks paths already exist inside the `ts-convert-to-*` skills.
- CoCo Snowsight. That runtime has no `ts` CLI, so the skill gets an
  `EXPECTED_DIVERGENCES` entry with that justification.

---

## 2. Name and family

**`ts-object-formula-translate`**, in the `ts-object-{type}-{verb}` family. The object is
a formula and the verb is translate. The name already matches `check_skill_naming.py`'s
`ts-object-*` pattern, so the naming rule needs no change.

Why not `ts-convert-from-formula`: the `conversion-consistency-auditor` scans
`agents/cli/ts-convert-*` and audits each one against the Model invariants and coverage
matrices. Most of those (joins, `db_column_name`, `guid` placement) mean nothing for a
single formula. The auditor would report defects that are really category errors. The
same reasoning made `ts-link-*` its own family.

---

## 3. Architecture

Two layers, following the repo rule that skills call `ts` rather than re-translate in
prose (`.claude/rules/ts-cli.md`), and that mechanical steps become code (angle 11).

```
SKILL.md  ── detect dialect ── confirm ── resolve columns ── call CLI ── explain ── (validate)
                                                   │
                         ts formula translate --from <dialect> [--columns …] [--model …]
                                                   │
             ┌──────────────── adapter layer (one per dialect) ────────────────┐
             tableau   powerbi   qlik   sisense   snowflake   databricks   (excel/sigma/omni: v2)
             translate_single  translate_dax  translate  translate_jaql  sv_sql  mv_sql
```

### 3.1 New CLI command: `ts formula translate`

```
ts formula translate EXPR --from {tableau|dax|qlik|sisense|snowflake|databricks}
                          [--columns JSON] [--model GUID --profile NAME]
                          [--validate {none|compile|execute}]
```

Output is JSON on stdout (repo convention), with diagnostics on stderr:

```json
{
  "dialect": "tableau",
  "input": "ROUND(SUM([Sales]) / COUNTD([Customer]), 2)",
  "formula": "round ( sum ( [ORDERS::Sales] ) / unique count ( [ORDERS::Customer] ) , 0.01 )",
  "status": "TRANSLATED",
  "role": "MEASURE",
  "references": [
    {"source": "[Sales]",    "target": "[ORDERS::Sales]",    "placeholder": false},
    {"source": "[Customer]", "target": "[ORDERS::Customer]", "placeholder": false}
  ],
  "notes": ["round(): 2 decimal places → increment 0.01 (BL-331)"],
  "verification": {"level": "compile", "result": "OK", "sql": "…"},
  "tml": "formulas:\n- id: formula_…"
}
```

`status` is one of:
- `TRANSLATED`
- `APPROXIMATED` (a documented downgrade)
- `NEEDS_REVIEW` (the formula is untranslated and the original is kept)

### 3.2 Adapter layer

The existing translators were written for pipelines and do not agree on a contract:

| Dialect | Entry point | Returns today |
|---|---|---|
| Tableau | `tableau_translate.translate_single(raw, role, scoped_columns, …)` | `(expr, errors[], notes{})` |
| DAX | `powerbi.functions.translate_dax(dax, home_table, home_cols, …)` | `(expr or None, status, note)` |
| Qlik | `qlik.functions.translate(expr)` | `(expr, review_required, reason)` |
| Sisense | `sisense.functions.translate_jaql(expr, context)` | `(expr, status, …)` |
| Snowflake SQL | `sv_sql.translate_sql_expr(sql, resolver)` | `str`; raises on untranslatable |
| Databricks SQL | `databricks.mv_sql.translate_sql_expr(sql, resolver, agg_hook)` | `str`; raises |

Each adapter does three things:
- maps the result to the §3.1 shape;
- passes a **recording resolver** or column map, so every reference is captured in
  `references[]`;
- turns a raised error into `NEEDS_REVIEW` with the message as a note.

**The adapters wrap the translators; they do not fork them.** A fix to a translator reaches
both the converter skill and this skill. That is the BL-217 principle: import, never
re-implement.

**Role inference** (`ATTRIBUTE` / `MEASURE`) reuses `ts agentql classify-columns` logic
where it applies, and otherwise the aggregate detector in `formula_common.py`. The
BL-331 review found that detector misses `[formula_X]` references, so the adapter treats
references to MEASURE formulas as aggregated.

### 3.3 Excel, Sigma, Omni (no translator yet)

**v1:** the skill translates these from the function maps, as an agentic step. The map row
for every function used is cited in the answer, so the classification and verification
status come from the map, not from the model. `--validate compile` (§5) is **strongly
offered** for these, because nothing deterministic stands behind them.

**v2:** codify. Excel first, because most of its row-level grammar is shared with DAX, and
`powerbi/functions.py` already parses function-call syntax with Excel names. Sigma second.
Omni's model layer is SQL, so it routes to the Snowflake adapter; only Omni table calcs
need new code. This follows the Tableau `translate-formulas` pattern
(`.claude/rules/repo-audit.md`, angle 11).

---

## 4. Dialect detection

The skill guesses, then **always confirms in one line** ("Reading this as Tableau — say if
it's something else."). Detection is a scored heuristic. It never routes silently, because
two of the candidate languages are close to identical.

| Signal | Points to |
|---|---|
| `{FIXED`, `{INCLUDE`, `{EXCLUDE`, `ATTR(`, `COUNTD(`, `ZN(`, `'day'` single-quoted date parts | Tableau |
| `CALCULATE(`, `'Table'[Column]`, `VAR … RETURN`, `SELECTEDVALUE(`, `DIVIDE(` | DAX |
| `{<Field={…}>}` set analysis, `$(var)`, `Aggr(`, `Only(` | Qlik |
| `[key]` placeholders with a JAQL `context` object | Sisense |
| Leading `=`, A1/range refs (`B2`, `A:A`, `Sheet1!C3`), `SUMIFS`, `XLOOKUP` | Excel (or Google Sheets, or an Omni table calc) |
| `DateDiff("day", …)` CamelCase with double-quoted units, `[Table/Column]` | Sigma |
| `${view.field}`, `${TABLE}` | LookML **or** Omni (ask) |
| Bare SQL: `CASE WHEN`, `DATEADD(`, `IFF(`, `::`, `QUALIFY` | Snowflake SQL |
| `date_add(`, backtick identifiers, `MEASURE(` | Databricks SQL |

**Must ask** (no guess): Excel vs Sheets vs Omni table calc, when the user hasn't said
which; LookML vs Omni; and any formula scoring two dialects within a margin. The question
lists only the tied candidates.

Excel, Sheets and Omni table calcs share one map, with Omni's differences noted per row.
So the cost of asking is one line, and the cost of guessing wrong is an Omni `OFFSET` read
as an Excel cell reference.

---

## 5. Columns: three levels of context

| Level | User supplies | References resolve to | Validation available |
|---|---|---|---|
| **0: none** | the formula only | placeholders `[TABLE::Column]` derived from the source name (`[Sales]` → `[TABLE::Sales]`), each listed in `references[]` with `placeholder: true` | none |
| **1: names** | a column map (`Sales=ORDERS.SALES_AMT`, or a pasted list) | the mapped `[TABLE::Col]` | none |
| **2: Model** | profile + Model GUID or name | real columns: the skill exports the Model TML, matches source names to Model columns (exact, then case- and space-insensitive, then a **confirmed** fuzzy match; never a silent fuzzy match) | `compile`, `execute` |

At level 2, an unresolved reference is a question, never a guess. Each column's role and
data type come from the Model, and they drive role inference and date-function choice. For
example, `date_cols` feeds DAX's DATE-subtraction rule.

### 5.1 Validation (`--validate`)

There are two tiers, both opt-in, and both need level 2.

- **`compile`.** Build a **scratch copy** of the user's Model:
  - export its TML;
  - drop the guid;
  - rename it `ZZ_FORMULA_PROBE_<timestamp>_DELETE_ME`;
  - append the formula and its `columns[]` entry.

  Then import with `--create-new` and run `ts agentql generate-sql` over the formula,
  plus one grouping column for a measure. The result is OK with the compiled SQL, or the
  parser's error verbatim. The user's Model is never modified.
- **`execute`.** Do everything in `compile`, then run `ts agentql fetch-data … LIMIT 5`
  and show the rows.

**Cleanup is not optional.**
- The scratch Model is deleted in a `finally`, then confirmed gone with
  `ts metadata search`.
- If the delete fails, the command exits non-zero and prints the GUID.
- The skill repeats the GUID to the user, with the delete command to run.

This is the method used to settle `round` on 2026-10-06. That session hit two traps the
command must encode:

1. An aggregate formula must be selected as `AGG("name")`.
2. Selecting a plain `SUM(col)` alongside several formula measures made AgentQL put the
   formulas into GROUP BY. The query then failed with `[ca_3] is not a valid group by
   expression`, which is unrelated to the formula under test.

So probe **one formula per query**, with one grouping column and nothing else.

**Cheaper alternative to check first** (open item OI-1): `ts tml import --policy
VALIDATE_ONLY` may reject a malformed formula with no object created. If it does,
`compile` uses it, and the scratch-Model path is kept only for `execute`. Unknown today
whether VALIDATE_ONLY parses formula expressions or only the TML structure.

---

## 6. Output to the user

In order:

1. **The formula**, in a code block.
2. **Classification + one-line why**, e.g. "`direct (downgrade)`: matches Sigma only when
   the Answer's columns are exactly the parent groupings plus the sort column".
3. **Traps applied**, only the ones that fired, e.g.:
   - "round: 2 decimal places → increment 0.01"
   - "diff_days takes (end, start)"
   - "COUNT(*) has no ThoughtSpot form — counted the primary key"
4. **References table** (source → ThoughtSpot, with placeholders flagged).
5. **Verification status:**
   - for a translator-backed dialect, the translator plus the tests that cover the
     construct;
   - for a map-backed one, the map row's status;
   - for either, the `compile`/`execute` result when run.
6. **TML snippet**: `formulas[]` + `columns[]` entries, id `formula_<display name>` with
   spaces kept (the repo convention, per `thoughtspot-formula-patterns.md`), and
   `aggregation` only on the `columns[]` entry.
7. For `passthrough`: the warehouse-dialect warning (Snowflake is assumed; name it) and
   the `sql_*_op` variant's role consequence (Ossie map E7).
8. For `NEEDS_REVIEW` / `unmappable`: the reason and the nearest workaround from the map,
   such as a Model join for a lookup, a warehouse view, or a UDF recipe. Never a
   plausible-looking substitute; the Qlik translator's rule.

---

## 7. Skill flow (SKILL.md outline)

0. Branch/profile preamble per repo convention; no profile is needed for levels 0 and 1.
1. Take the formula. If several are pasted, handle them in one batch and number the
   answers.
2. Detect → confirm (§4).
3. Ask for the context level (§5): "Columns: use placeholders, give me names, or point me
   at a Model?" Default to placeholders.
4. Translator-backed: run `ts formula translate`. Map-backed: translate from the map rows,
   and cite them.
5. Present (§6).
6. Offer validation if level 2 and not yet run. For map-backed dialects, recommend it.
7. Loop: "Another formula?" Detection is sticky for the session unless the input changes
   shape.

---

## 8. Testing

- **Unit (`tools/ts-cli/tests/test_formula_translate.py`)**:
  - each adapter's normalisation;
  - the recording resolver;
  - placeholder generation;
  - `NEEDS_REVIEW` mapping of raised errors;
  - dialect detection over a labelled corpus. Seed the corpus from each converter's
    existing tests, plus the worked shapes of the four function maps. Include the
    must-ask ties, and assert that the detector returns a tie rather than a pick.
- **Golden cases**: a regression row for every trap the function maps name (round
  increment, `unique count`, `diff_days` order, `COUNT(*)`, window partition rule).
- **Validation**: unit-test that scratch-Model TML is built from an exported Model
  fixture with the guid removed and the name prefixed. Test cleanup on a simulated import
  failure, a query failure and a delete failure.
- **Smoke**: `tools/smoke-tests/smoke_ts_object_formula_translate.py`. One formula per
  translator-backed dialect at level 0, and one `compile` run at level 2 against
  se-thoughtspot that asserts the scratch Model is gone afterwards.

---

## 9. Open items (to `references/open-items.md`)

| # | Question | Why it matters |
|---|---|---|
| OI-1 | Does `--policy VALIDATE_ONLY` reject a malformed formula expression? | If yes, `compile` creates no objects at all |
| OI-2 | Does `day_number_of_week` follow the instance's week-start setting? | Every WEEKDAY / WEEKNUM / NETWORKDAYS composition (Excel map G11) |
| OI-3 | Does `diff_months` count boundaries crossed or complete months? | DATEDIF and Sigma `DateDiff` (Excel G12, Sigma V3) |
| OI-4 | Is `contains` case-sensitive? | Sigma `Contains`, Omni `contains` |
| OI-5 | Can `sql_double_op` wrap an aggregate? | Whether non-literal `ROUND(SUM(x), d)` can pass through or must be refused (assumed refused in BL-331) |

OI-2 to OI-4 are three one-formula probes using §5.1's own method. Running them before
v1 ships moves a large share of map-backed date and text rows from "unprobed" to
"verified".

---

## 10. Change impact (per root CLAUDE.md)

| Area | Update |
|---|---|
| New skill | `agents/cli/ts-object-formula-translate/SKILL.md` (Changelog from 1.0.0), README skills table, `agents/cli/SETUP.md` symlink step, smoke test, CHANGELOG.md |
| CoCo | `EXPECTED_DIVERGENCES` entry: "no ts CLI in Snowsight; formula translation needs the CLI translators" |
| ts-cli | `commands/formula.py`, registered in `cli.py`; `tools/ts-cli/README.md`; version bump in `__init__.py` + `pyproject.toml` |
| Shared | none new. The function maps stay in `docs/function-maps/` until a translator is codified, then move to `agents/shared/mappings/<tool>/` with a currency anchor, as the other converters' mappings do |

## 11. Phasing

| Phase | Scope |
|---|---|
| **v1** | `ts formula translate` over the six existing translators; levels 0–2; `compile`/`execute` validation; Excel/Sigma/Omni map-backed in the skill |
| **v1.1** | Run OI-1 to OI-4 and update the maps' verification status |
| **v2** | Codified Excel translator, then Sigma; reverse direction (ThoughtSpot → SQL) via the existing to-Snowflake/to-Databricks emitters |

## 12. Implementation notes (v1, 2026-10-06)

Code: `tools/ts-cli/ts_cli/formula_translate/` (pure: `context`, `refs`, `adapters`, `traps`,
`engine`, `detect`, `validate`), command `ts_cli/commands/formula.py`, tests
`tools/ts-cli/tests/test_formula_translate.py`, skill
`agents/cli/ts-object-formula-translate/`. Deviations from §1–§10, each with its reason:

| # | Deviation | Why |
|---|---|---|
| 1 | **`compile` uses `VALIDATE_ONLY` and creates nothing; `execute` alone builds the scratch Model** (and runs the VALIDATE_ONLY check first) | OI-1 verified live: VALIDATE_ONLY parses formulas (truncated expression, unknown function, unknown column, wrong arity all rejected, error_code 14516). §5.1 made this conditional on OI-1. Consequence: `compile` returns no SQL — `verification.sql` comes only from `execute` |
| 2 | **New dialect `--from thoughtspot`** (identity: resolves references, translates nothing) | §3.3 asks for `--validate compile` on map-backed answers, but every other `--from` would re-translate a hand-composed ThoughtSpot formula. This is the path for Excel / Sigma / Omni validation |
| 3 | Extra options: `--name`, `--key-column`, `--group-by`, `--context` (Sisense JAQL context), `--role` (Tableau); `--model` accepts an exact name as well as a GUID | Needed by the formula's TML id, the `COUNT(*)` rule, §5.1's one grouping column, Sisense's `context` input, and §5's "GUID or name" |
| 4 | Output adds `classification`, `traps[]` (separate from `notes[]`), `unresolved[]`, `context_level`, `agentql_wrapper`, `original_kept` / `partial`; `verification` carries `translator` and `tests` | §6 needs each of these as a separate field; `traps` vs `notes` keeps "what changed meaning" apart from translator chatter |
| 5 | Role inference uses `spotql_ops.classify_expr` (the `classify-columns` logic) plus references to aggregate Model formulas; `formula_common.expr_is_aggregated` is not used for role | §3.2 names both; `classify_expr` is the one that also yields the semi-additive `SUM` wrapper AgentQL needs |
| 6 | Two dialect-independent repairs: `COUNT(*)` / `count(1)` → `count ( <key> )` (placeholder `[TABLE::<primary key>]`, unresolved at level ≥1 until `--key-column`), and a guard that turns a translator's leftover SQL keyword (`DISTINCT`, `OVER`, …) into `NEEDS_REVIEW` | §6 item 3's `COUNT(*)` trap; the guard caught a real translator gap — `qlik.translate` converts `Count(DISTINCT x)` only as the whole expression, and emitted `count(DISTINCT Customer)` inside a larger one |
| 7 | Level 0 keeps a source table qualifier (`Sales[Amount]` → `[Sales::Amount]`, still `placeholder: true`); bare names use `TABLE` | The user wrote that table name; discarding it loses information |
| 8 | Level 2 data types come from the Model's Table TMLs (`export_associated`), best effort | The Model TML carries no data types; DAX date subtraction and Tableau date arithmetic need them |
| 9 | Exit codes: 0 ran, 1 scratch Model not confirmed deleted (GUIDs on stderr), 2 bad input / preconditions (placeholders or unresolved references block validation) | §5.1 requires non-zero on a failed delete; the rest makes scripting deterministic |
| 10 | Detection returns `ask[]` (only the tied candidates) and treats Google Sheets and Omni table calc as Excel's twins; weak generic signals (`[Field]`, bare identifier arguments) are scored so that `SUM([Sales])` is a five-way tie, not a pick | §4 "the question lists only the tied candidates" and §8 "assert that the detector returns a tie" |
| 11 | Trap lines beyond §6's examples: Monday week start (OI-2, BL-334), case-insensitive comparison for Tableau / Snowflake / Databricks sources (OI-4, BL-333), `diff_months` boundaries (OI-3), Tableau `DATEDIFF('week')` → `diff_days / 7` | Probe findings and one translator approximation found while testing; a trap that means the output computes something else (the `/ 7`) downgrades `TRANSLATED` to `APPROXIMATED` so the classification never reads cleaner than the traps |
| 12 | The function maps carry no per-row verification field, so the skill derives a row's status from its text: *verified live (date)* / *verified via <row>* / *unprobed* / *documentation only* | §6 item 5 "the map row's status" |
| 13 | Not implemented: the window-partition golden case of §8 | No translator-backed dialect emits a partitioned window from one formula; the trap belongs to the map-backed Sigma/Omni rows, which the skill handles from the map |

**Skill test.** SKILL.md was exercised by a fresh subagent on a three-formula batch (an Excel
`EXACT`/`ROUND` formula, a five-way tie, a Tableau week difference) and revised from its
findings: the map-row status rule now ranks "passthrough / composition with no live date for
that cell" first (it had let `EXACT` read as *verified live* from the probe of `=`), operators
and Excel cell references are covered by the framing rules, a display name is asked for, role
guidance for row-level amounts was added, and the `/ 7` downgrade above. A follow-up probe
settled the one risk it raised: a literal passed as a `sql_bool_op` argument keeps its case.

**OI-5 finding with wider reach:** `sql_number_aggregate_op` is rejected by the formula parser on
se-thoughtspot; `sql_double_aggregate_op` is accepted. `thoughtspot-formula-patterns.md`, the
Snowflake mapping, the Ossie map and all three function maps name the former. The skill
substitutes the latter; the shared references need their own correction.
