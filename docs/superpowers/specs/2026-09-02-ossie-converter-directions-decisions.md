# Pre-decisions for Plan C+D (settle before writing tasks)

These are questions the mapping document deliberately left to "a Phase-3 converter
decision". The plan cannot be written without answering them, so each is answered here
with its reasoning, and each becomes a Global Constraint.

## PD1 — R4-P3: which TML shape does an Ossie metric become?

The document records two faithful emissions for `AGG(<scalar>)` and does not choose.

**Decision: pattern A (aggregate-in-expr) as the default, always.** Pattern B is more
idiomatic and more reusable, but it moves the aggregation into a *property*, so a
`TML -> Ossie` reader has to compose it back or the metric silently loses its aggregate.
The document says that outright. A silent loss on the return leg is the single failure
mode this whole converter is built to avoid, and pattern B buys idiomatic-ness we cannot
verify without a live query comparison (the document classes it as a query-time semantic
that VALIDATE_ONLY cannot probe).

Pattern A also has one object per metric and a grain fixed by the expr, which makes the
round-trip assertion straightforward. Choose reversibility over idiom.

Not hidden: the `shape` key already exists in the stash for exactly this, so a model that
*arrived* as pattern B round-trips back to pattern B. The decision above governs only
what we emit for a metric with no stash — i.e. a hand-authored or foreign Ossie document.

## PD2 — `--synthesize-time-columns`

The document leaves opt-in synthesis of a DATE column from an integer year to Phase 3,
noting X9 forbids inventing columns by default and that upstream has not been asked
whether a synthesised field should be marked converter-generated.

**Decision: do not implement the flag.** Emit the issue with its ready-to-paste formula,
as the document already specifies. Reasons: X9 is a rule, the upstream question is
genuinely open, and a flag that invents a column is exactly the kind of thing a first
contribution should not ship unilaterally. The issue already carries the remedy, so the
user is not stuck — they paste one formula.

## PD3 — BL-186 V1: the `calendar` property

Unresolved: ThoughtSpot's public TML doc gives `calendar: [ default | calendar_name ]`,
our SQL View reference records `CALENDAR_TYPE_GREGORIAN`, and the two are unreconciled.
The document says a converter "must not emit this property until they are".

**Decision: honour that.** `TML -> Ossie` stashes the observed value verbatim and raises
the issue naming the calendar. `Ossie -> TML` writes it back **only** from the stash, and
never synthesises one. This is the documented behaviour already; recorded so no task
author reads the ambiguity as licence to pick a spelling.

## PD4 — apache/ossie#287 (extended metadata) — branch or not?

#287 would move five stash keys to first-class fields. It is open.

**Decision: build against the schema as it is on main, and isolate the five keys behind
one module-level map** so that if #287 merges, the change is that map plus its tests, not
a sweep through the converter. Do not speculatively support both shapes: a branch on an
unmerged PR is untestable and doubles the surface. ID1's watch item (`label` vs
`display_label`) is the same call.

## PD5 — Which dialect does `TML -> Ossie` emit, and is a THOUGHTSPOT-only expression acceptable?

`THOUGHTSPOT` is registered in the `Dialect` enum and in `SKIP_SQL_VALIDATION`
(verified in the local checkout, both live after #351). So a THOUGHTSPOT-only expression
is schema-valid and skips the sqlglot parse.

**Decision: always emit the THOUGHTSPOT entry verbatim; emit the portable ANSI_SQL
sibling whenever the expression translated cleanly.** This makes round-trip fidelity
independent of translation quality — the verbatim entry is the source of truth on the
return leg — while still giving a non-ThoughtSpot consumer something executable in the
74% of cases the catalog covers directly. It is also exactly what rule 3 of the
document's Expression handling section already prescribes.

Consequence worth stating plainly: a round-trip test that passes because the verbatim
entry was preserved proves *preservation*, not *translation*. The two need separate
assertions, or the round-trip test becomes the same kind of self-consistent green as
BL-235's arity sweep.

## PD6 — the parser question (the one that blocked Plans C and D)

Researched against upstream rather than decided from taste. The evidence:

| Question | Answer |
|---|---|
| Does the reference converter (`databricks`) parse expressions? | **No.** `metric_view_to_ossie.py` / `ossie_to_metric_view.py` carry the string verbatim; the only transformation is a `re.sub(r"\bsource\.")` qualifier swap. |
| Does it emit `ANSI_SQL`? | **No** — it tags its own `DATABRICKS` dialect, and `pick_expression` reads `DATABRICKS` first with `ANSI_SQL` only as fallback. |
| Does ANY converter re-render an expression into another dialect? | **No.** Zero calls to `.sql(dialect=…)` or `transpile()` across the whole repo. |
| Who depends on `sqlglot`? | `dbt` and `nvidia` — but for *structural pattern-matching* and *lineage/normalised comparison*, never for translation. |
| What does the spec say? | "the default for Ossie should be to **pass unknown values through**", and choosing among dialects is the *consumer's* job — translation is not a producer obligation. |
| What is the round-trip bar? | **Exact string equality** (`_roundtrip_helpers.py`), achievable only because nothing reformats. |
| Cost of a new dependency | `.github/PULL_REQUEST_TEMPLATE.md`: "No third-party dependencies are added without PMC/IPMC approval". |

**Decision: option (C) as the default, with a thin (B) layer exactly where typed semantics
must be reconstructed. No new dependency; no SQL parser.**

Concretely:

- **`TML -> Ossie`.** Always emit the `THOUGHTSPOT` dialect entry carrying the formula
  **verbatim**. Emit an `ANSI_SQL` sibling only where it is free or near-free:
  a bare physical column reference (the common case — most fields are not computed),
  and single-construct formulas the catalog matches outright. Everything else is
  THOUGHTSPOT-only plus an issue recording non-portability. This is precisely what
  `databricks` does, plus a portable sibling it does not attempt.
- **`Ossie -> TML`.** Prefer the `THOUGHTSPOT` entry and use it verbatim (rewriting only
  references) — so a document we produced returns exactly. For a foreign document with no
  THOUGHTSPOT entry, translate the shapes the catalog can match structurally and raise an
  issue for the rest. Never guess.
- **A shallow ThoughtSpot-formula tokenizer is still required** — not a parser. It splits
  an outer call into `(name, [args])` and finds `[TABLE::Column]` references, which is
  exactly the input `translate_thoughtspot(name, args, …)` already expects and the input
  reference rewriting (ID3) needs. Roughly the same scope as `dbt`'s `_extract_agg_info`.

## PD7 — verbatim vs reconstructed, and why round-trip could silently pass

`thoughtspot_dialect_entry(name, args)` **reconstructs** the call textually — its own
docstring says the module "never has the original formula's exact whitespace". At the
sub-expression level that is unavoidable and fine.

**At the document level it is not.** Upstream's round-trip bar is exact string equality, so
`tml_to_ossie` must put the **original `expr` string, untouched**, into the THOUGHTSPOT
dialect entry — never a reconstruction. Using the reconstruction would normalise
`sum([A::b])` to `sum ( [A::b] )` and break exact equality on any formula not already in
ThoughtSpot's canonical spacing.

Related trap, and the reason this is written down: because the verbatim entry is what the
return leg reads, **a round-trip test can pass while translation is entirely broken.** It
proves preservation, not translation. The two need separate assertions — otherwise the
round-trip suite becomes the same self-consistent green as BL-235's arity sweep.
