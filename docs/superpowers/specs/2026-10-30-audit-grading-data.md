# Grading into data (roadmap PR 2.4)

**Status:** built to the roadmap's PR 2.4 list (`2026-10-23-audit-v2-roadmap.md`, wave 2) ·
Closes BL-406 items 3, 7, 8 and 9; item 10 deferred (needs a ruling).

## What changes

| Rule | Was | Now |
|---|---|---|
| D1 | Its HIGH / MEDIUM lines (50 / 30) in `D1_MEASURES`, a code constant | The rule's catalog `bands`; the code rule registers `severity="bands"` and applies them to each measure (tables, joins, formulas) |
| H2 | Minimum and maximum length (20 / 400) and the number of issues listed (3) in module constants | `parameters: {min_chars: 20, max_chars: 400, issues_shown: 3}` in the catalog |
| H10 | LOW / MEDIUM fixed in code; quote length (60) a constant | `severity: {field: "@orphan_model", map: {true: MEDIUM}, default: LOW}` and `parameters: {quote_chars: 60}`. `@orphan_model` is a new derived field (no dependents but Sets, H4's test) |
| P6 | LOW / INFO fixed in code | Unchanged, **accepted**: one join yields up to two findings of different severities, which no single catalog severity source says |
| P2 | "Row-level" when no surfacing column declares an `aggregation`. The model schema says that key is a no-op on an aggregate expression and applies on a row-level one, so it was wrong both ways | `@is_row_level_formula`: the expression calls no aggregate function (`spotql_ops.AGGREGATE_FUNCS`, or a `sql_*_aggregate_op`, outside references and literals) and references no aggregate formula, followed through chains |
| H1, readiness score | The name anti-patterns kept twice (H1's `regex:` and `_NAME_ANTI` in `code_rules.py`) | One derived field, `@is_poor_name`, read by both |
| report | A null or numeric Model, table or column name or alias, or a numeric column description, ended `ts audit run` (`_build_ai_analysis`, the ERD's table lookup, the ERD finding placement, the readiness score) | A null name reads as empty, a numeric one as its text; a numeric description as present, as A1 and A4 read it. Tested end to end (`run_audit` then `render_report`, with a Table TML present so the ERD's lookup runs), since fixing one function at a time just moved the crash to the next — twice |

## The `parameters` key

A code rule's tuning numbers, in the catalog, so a reader can see and change them without
touching Python. `@code_rule(..., parameters={"min_chars", ...})` declares the names; the
function reads `rule.parameters`. The gate:

- requires exactly the declared names, each a finite, non-negative number (not a boolean);
- rejects `parameters` on a declarative rule, a retired one included;
- allows a profile override, which replaces the map whole (like `bands`);
- in `--base` mode, fails a rule whose parameter value changed while its description still
  quotes the old one (the band drift check, extended).

The generated catalog and the report's grading text show them after the grading
("LOW (tuned by min chars 20, max chars 400, issues shown 3)").

A code rule may also register a `band_shape`: the `(op, severity)` levels its wording
assumes. D1 words its findings ">{yellow} HIGH, >{green} MEDIUM", so every profile's
bands must be exactly `gt HIGH, gt MEDIUM`; the values are free.

## Choices

- **D1's three measures share one band set.** The roadmap says "D1's per-measure lines";
  the shipped lines were equal (30 / 50 for tables, joins and formulas), so one set
  reproduces them exactly. Tuning the measures apart would need per-measure bands, which
  no rule needs yet.
- **P6 stays in code.** Accepted by the product owner (2026-10-30): its two severities
  come from two independent tests of one join, which a single catalog severity source
  cannot express without a new mode. Revisit when a profile needs different P6
  severities, or a second rule has the same "one item, two kinds of finding" shape —
  then split P6 into two rules (a new id) or teach the engine per-finding grading.
- **Parameters, not bands, for H2 and H10.** Their numbers are not severity lines: H2's are
  the edges of an acceptable length, H10's is how much of a description to quote. Bands
  would have meant inventing severities for them.
- **P2 follows references.** `[formula_Rev] / [formula_Cnt]` divides two aggregates, so it
  is aggregate even though it calls no function. A formula without a `name` is judged on
  its own expression only.
- **P2's reference matching** is exact on the formula's name or id, as P17's reference
  graph is: `[rev]` for a formula named `Rev`, or a reference by the surfacing column's
  name, reads as row-level. Exported TML references by id, so this is rare.
- **P2's literal stripping.** A function name inside a `[...]` reference or a quoted literal
  does not count (`_NOT_CODE`, as P18). `sql_*_aggregate_op` is matched by name, since its
  SQL sits in a literal.
- **`@is_poor_name` on a non-string name** is False, as H1's `regex` operator read it. The
  readiness score coerced with `str()`, so a YAML-typed `name: 2024` used to count as poor
  there; it no longer does, though H1's description ("a leading digit") would say it is.
  No pinned or sampled Model has one.
- **`tml.node_key` removed.** `tml.join_target` uses `tml_join_graph.node_id`, the one
  definition, now that the audit engine may import the gate-safe shared modules. One
  difference: an entry with no alias, id or name reads as `"?"`, not `""`.

## Found in review, not fixed here

- D9 and P16 still count function names inside references and literals (P18 and now P2
  strip them). Pre-existing; both are pinned. Recorded on BL-406.
- Engine provenance records the source of bands and severity, not of `parameters`.
- A count parameter (`issues_shown`) accepts a fraction or 0, which `int()` truncates to
  an empty list. The gate's rule is "finite, non-negative", which suits lengths.
- D7 words HIGH "Identical table sets", true only while its HIGH line is 1.0; a profile
  could lower the line and keep the words. Latent (no profile overrides D7). On BL-406.
- A YAML date used as a name or description still ends the run, at the JSON output.
  Whether exports ever carry one unquoted is unknown. On BL-406.

## Effect on the SE demo sample (148 Models)

Only P2 moves: 6 → 8 LOW findings under both profiles (2 new; 6 with a different count, in
both directions). D1, H1, H2, H10 and the readiness score are identical, as intended: the
grading moves preserve behaviour.
