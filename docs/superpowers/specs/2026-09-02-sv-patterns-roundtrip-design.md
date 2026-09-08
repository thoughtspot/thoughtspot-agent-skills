# Design: Snowflake Semantic View pattern round-trip fidelity

**Date:** 2026-09-02
**Status:** Approved, not yet implemented.
**Owner:** Damian Waldron

## Background

`Snowflake-Labs/coco-skills` ships a skill, `skills/semantic-view-patterns`, containing
25 Snowflake Semantic View modelling patterns. Each pattern is a self-contained,
runnable bundle:

```
snippets/<pattern>/
  README.md          schema.sql        seed_data.sql
  semantic_view.sql  semantic_view.yaml  queries.sql
```

Two properties make this corpus worth more to us than a normal set of examples.

**It ships its own data.** `schema.sql` + `seed_data.sql` mean nothing has to be
synthesised. `ts-load-source-data` is therefore *not* on this path — it cannot
execute DDL (`commands/load.py:691-703` accepts no `--file`/`--query`), and there is
no data for it to infer.

**It is organised by construct, not by subject area.** Each pattern isolates one SV
modelling construct — ASOF joins, semi-additive metrics, window metrics, derived
metrics, role-playing dimensions. That is very nearly the axis along which
`ts-convert-from-snowflake-sv/references/coverage-matrix.md` is written, so the corpus
reads as a probe of that matrix almost row for row.

### Why now

The from-direction coverage matrix already *predicts* specific losses and names the
backlog item for each: facts emitted as `ATTRIBUTE` with no `MEASURE` branch (BL-181,
matrix row 16), `NULLIF(y,0)` → `safe_divide` silently converting NULL to 0 (BL-180,
row 39), same-table metric-on-metric dangling and exiting 1 (BL-194, row 27), primary
keys and temporal roles lost with no stash (BL-166, rows 4 and 38). Row 28
(window-metrics-referencing-metrics) concedes the gap outright: *"**not exercised on a
live fixture** — the TPC-DS fixture contains no window-on-metric construct, so this
row's evidence is unit-level only."*

Those are predictions. Nothing in the repo tests them end to end.

`.claude/rules/repo-audit.md` angle 15 — *conversion fidelity: does converted output
produce semantically equivalent results, the same numbers, not just valid-importing
TML?* — is **PARKED**, and the recorded reason is that it "needs live data on both
sides to test properly." This corpus is live data on both sides.

### What exists today, and what does not

| Capability | State |
|---|---|
| `ts snowflake diff` | A **column-map** comparator, not an SV comparator. Both sides are hand-built `{COLUMN: {expr, description, synonyms}}` JSON. Its docstring is explicit that it does not translate (`commands/snowflake.py:88-92`). |
| Step 11c reconciliation | Prose instructions to the agent, not code (`ts-convert-from-snowflake-sv/SKILL.md:914-944`). Opens with "A successful import is not a correct conversion." |
| `check_converter_parity.py` | "Parity" means converters share `formula_common.py` helpers — not source/target semantic parity. |
| Smoke tests | Both docstrings say "live round-trip", but neither compares an original SV against a regenerated one. Mode C tests *idempotent update*. |
| `docs/reviews/2026-07-29-ossie-tpcds-fidelity.md` | A one-off manual cross-validation. Produced "only 10 of 47 constructs survive unchanged". A document, not a rerunnable tool. |
| SV fixture corpus | **None.** No `.sql` or `.yaml` SV file exists in the tree; unit tests use inline DDL string constants. |

So: **no command or script anywhere takes an original Semantic View and a regenerated
one and compares them.** That gap is what this work measures around, not what it fills.

## Scope

Sixteen patterns, round-tripped Snowflake → ThoughtSpot → Snowflake, compared
structurally and numerically. The output is a review document and routed findings.

**In scope (16):** `accumulating_snapshot`, `ai_metadata`, `asof_join`,
`derived_metrics`, `entity_facts`, `fact_as_relationship_key`, `multi_fact_table`,
`multi_path_metrics`, `range_join`, `role_playing_dimensions`, `semi_additive_metric`,
`shared_degenerate_dimension`, `tags`, `time_intelligence`, `variables`,
`window_metrics`.

**Excluded, with reasons:**

| Pattern(s) | Reason |
|---|---|
| `introspection`, `standard_sql` | No `semantic_view.sql` — meta/diagnostic, nothing to convert |
| `sv_diagnostics` | 11 *deliberately broken* SVs (fan traps, ambiguous paths, reversed relationships). A negative-test corpus, a different exercise |
| `caller_rights`, `row_access_policies` | Require ACCOUNTADMIN; session role is `SE_ROLE` |
| `materialization`, `inline_sv`, `scoped_dataset` | Private preview; `materialization` also needs ACCOUNTADMIN |
| `system_explain_semantic_query` | Explain-plan tooling rather than a modelling construct |

### Non-goals

- **No new repo tooling.** No validator, no `ts` subcommand, no committed harness.
  Scratch scripts live in the session scratchpad. (A rerunnable harness is a
  plausible successor once this pass shows what a comparator must actually catch —
  it is deliberately not this piece of work.)
- **No fixture corpus vendored into the repo.**

### A note on identifiers, since this repo is public

An earlier draft of this spec carried a rule against naming the Snowflake account, role,
warehouse, connection or schema. That rule was stricter than this repo's established practice and
is **withdrawn as over-strict**, measured rather than assumed: `se-thoughtspot` appears in 104
tracked files, `AGENT_SKILLS` in 24, `APJ_TAB` in 14, `ap-southeast-2` in 6, `SE_ROLE` in 5,
`SE_DEMO_WH` in 2, `THOUGHTSPOT_PARTNER` in 1. Redacting a method document that must be
reproducible would cost real clarity and add no protection.

The security model that does bind (`.claude/rules/security.md`) is about **credentials**: tokens,
passwords and keys live in the OS credential store and never in a file, a command's argument list,
or the conversation. That line is held here.

The published **report** is a different genre and stays narrower — `docs/reviews/` precedent names
only the cluster nickname, and a review has no reason to widen exposure it does not need.
- **No conversion-code fixes.** Findings are recorded and routed; fixing them is
  separate work on separate branches.

## Environment

Verified live on 2026-09-02:

| | Value |
|---|---|
| Snowflake account | `THOUGHTSPOT_PARTNER` (`thoughtspot_partner.ap-southeast-2`), version 10.31.101 |
| Snowflake profile | `ThoughtSpot Partner (AP)` — python connector, key pair |
| Role / warehouse | `SE_ROLE` / `SE_DEMO_WH` |
| Privilege | `SE_ROLE` holds **OWNERSHIP on DATABASE `AGENT_SKILLS`**; `CREATE SEMANTIC VIEW` is a live grant on the account (`SKILLS.PUBLIC`) |
| ThoughtSpot | profile `se-thoughtspot`, `https://se-thoughtspot-cloud.thoughtspot.cloud` |
| `ts` CLI | 0.135.0, installed via `uv tool install --force -e tools/ts-cli --with snowflake-connector-python` |

Note: `ts auth whoami` returns 404 (code 13003) against `/api/rest/2.0/auth/session/user`
on this build, while `ts connections list` succeeds. Auth is fine; the whoami endpoint
is not. Do not read that 404 as an auth failure.

## Target layout

A single schema, **`AGENT_SKILLS.SV_PATTERNS`**, holding all 16 patterns' tables and
semantic views.

**AMENDED 2026-09-08 — the original justification here was wrong, and the error caused real
data loss.** This section claimed "within the 16 there are zero collisions", measured with a
lowercase-only regex applied only to `schema.sql`. Re-measured case-insensitively across every
`.sql` file, the 16 study patterns claim 32 distinct table names of which **two collide**:

| Table | Claimed by |
|---|---|
| `DIM_DATE` | `accumulating_snapshot`, `derived_metrics`, `role_playing_dimensions` |
| `ORDERS` | `asof_join`, `entity_facts`, `range_join`, `role_playing_dimensions` |

Because every pattern deploys with `CREATE OR REPLACE TABLE`, a later pattern silently
overwrites an earlier one's data with an incompatible shape, and the earlier pattern's stage A
then returns wrong rows with no error. This happened live: `DIM_DATE` was clobbered mid-run and
`derived_metrics`' stage A had to be re-isolated.

**Corrected layout: one schema per pattern, `AGENT_SKILLS.SV_PATTERNS_<pattern>`, table names
unchanged.** Renaming tables instead is not viable — it would break every `dim_date.x` reference
in the SV DDL and force hand-editing of `build-sv` output, contaminating the very thing being
measured. The extra ThoughtSpot table registration is the cost of isolation and is worth paying.

**Method consequence for the report:** a pattern whose oracle check passes is proven
uncontaminated at stage A. A pattern with no oracle cannot self-verify, so any pattern that (a)
shares a colliding table name and (b) ships no oracle must be re-run under isolation before its
numbers are published.

The snippets hardcode `SNIPPETS.PUBLIC` and open with `CREATE DATABASE IF NOT EXISTS
SNIPPETS`. Rewrite those references to the target before executing; do not create a
`SNIPPETS` database. Regenerated views are suffixed `_RT` and land beside their
originals, so both are queryable in the same session.

Every object created is tracked in a manifest for teardown.

## Deploy

Per pattern, in order, via `ts snowflake exec -f <file> --sf-profile "ThoughtSpot Partner (AP)"`:

1. `schema.sql`  2. `seed_data.sql`  3. `semantic_view.sql`

`ts snowflake exec` is the repo's sanctioned arbitrary-SQL path
(`commands/snowflake.py:270-357`).

## The round trip

Per pattern:

| # | Step | Command |
|---|---|---|
| 1 | Fetch source of truth | `SELECT GET_DDL('SEMANTIC_VIEW', '<fqn>')` |
| 2 | Parse | `ts snowflake parse-sv sv_ddl.sql --output parsed.json` |
| 3 | Introspect columns | `ts snowflake introspect --parsed parsed.json --sf-profile … --connection-name …` |
| 4 | Register tables | `cat tables-spec.json \| ts tables create --profile se-thoughtspot` |
| 5 | Translate formulas | `ts snowflake translate-formulas --input parsed.json --output translated.json` |
| 6 | Build + import Model | `ts snowflake build-model --parsed --translated --tables --model-name --sv-fqn --profile` (two-pass) |
| 7 | Export Model TML | `ts tml export <guid> --profile --fqn --associated --parse` |
| 8 | Regenerate SV | `ts snowflake build-sv --model … --tables-dir … --sv-name <fqn>_RT --output <p>_rt.sql` |
| 9 | Lint | `ts snowflake lint-ddl <p>_rt.sql` |
| 10 | Deploy regenerated SV | `ts snowflake exec -f <p>_rt.sql --sf-profile …` |

Step 6's two-pass import is mandatory, not stylistic: matrix L7 records that formulas
referencing `[TABLE::COL]` fail on initial CREATE and succeed on UPDATE.

## Comparison method

This is the substance of the deliverable.

### Structural

Parse **both** DDLs with the same parser — `ts snowflake parse-sv` on the original, and
again on the regenerated `_RT` DDL — then diff the two JSON documents. This gets
construct-level survival without anyone hand-writing a DDL comparator, and reuses a
shipped command rather than adding one. `ts snowflake diff` covers the column-map layer
(expressions, descriptions, synonyms).

Output per pattern: constructs in → constructs out, each loss attributed to a
coverage-matrix row where one predicts it.

### Numeric — three stages

Each numbered query in `queries.sql` is a clean `(DIMENSIONS, METRICS, WHERE)` tuple.
That is what makes this tractable: one tuple, three engines.

| Stage | Engine | How the query is expressed |
|---|---|---|
| **A** | Original Snowflake SV | `queries.sql` as written |
| **B** | ThoughtSpot Model | same tuple as AgentQL, via `ts agentql fetch-data -m <guid>` |
| **C** | Regenerated `_RT` SV | `queries.sql` rewritten through a name map |

Stage C needs the rewrite because identifiers change across the round trip. The map
(original SV name → ThoughtSpot column → regenerated SV name) is assembled from the
`parse-sv` JSON, the exported Model TML, and the `build-sv` output. Building it is
mechanical; a name that cannot be mapped is itself a finding (the construct did not
survive).

**Why three stages and not two.** Two stages can only say *something* broke. Three give
two independent hops, so every discrepancy is attributable:

- **A ≠ B** → the from-converter (`parse-sv` / `translate-formulas` / `build-model`)
- **B ≠ C** → the to-converter (`build-sv`)
- **A ≠ C** → net round-trip loss, the number that goes in the headline

**The free oracle.** Many `queries.sql` carry expected values in comments — e.g.
`semi_additive_metric` query 1: `-- Expected: 2024-05-31 → $7,500.00 (1250 + 5300 + 950)`.
Where present, that independently validates Stage A, so we are not comparing two wrong
answers to each other and calling it agreement.

### Verdicts

Per query: `EXACT` / `NUMERIC_DIFF` / `SHAPE_DIFF` (row count or grouping differs) /
`UNAVAILABLE` (metric did not survive to that stage) / `ERROR`.

Numeric comparison normalises on column name and row ordering. Decimals compare equal
within a **relative tolerance of 1e-12** — tight enough that a real semantic divergence
(BL-180's NULL → 0, a double-counted fan trap) cannot hide inside it, loose enough to
absorb representation drift between two engines.

*Amended 2026-09-02, from 1e-9.* The original value was an estimate and an adversarial
review falsified it: at relative 1e-9 the threshold reaches one cent at $10M and one
dollar at $1B, so `123456789.01` vs `123456789.02` compared EXACT. For a study whose
headline numbers are revenue totals, that is exactly the divergence class worth catching.
Comparing Decimals natively rather than coercing to float landed in the same change, so
the tighter bound costs no legitimate precision. A comparison that needs a looser
tolerance to pass is a finding, not a tuning problem: record the actual delta rather
than widening the tolerance. `UNAVAILABLE` is a distinct verdict from
`ERROR` on purpose: a metric that vanished structurally and a metric that blew up at
query time are different findings with different fixes.

## Sequencing

**Pilot: three patterns, then a review gate.**

| Pattern | Why it is in the pilot |
|---|---|
| `derived_metrics` | Predicted hard failure. `store_pct_of_total AS store_sales.store_revenue / total_revenue` is a metric-on-derived-metric; matrix row 27 says the reference dangles, I13 fires, `build-model` exits 1 (BL-194) |
| `semi_additive_metric` | `NON ADDITIVE BY` → `last_value(...)` (rows 21/22), and facts-as-`ATTRIBUTE` (BL-181). Carries expected values in comments |
| `multi_fact_table` | Three fact tables on two shared dimensions — the fan-trap / `USING` class, and cross-fact derived metrics |

Stop after these three, show the comparison output, adjust the method, then run the
remaining 13. The point of the gate is to avoid running a flawed comparison sixteen times.

If `derived_metrics` fails at step 6 exactly as predicted, that is a *confirmation*, not
a blocker: record it, then inline the offending metric **in a local copy of the source
`semantic_view.sql`** and carry the rest of the pattern through so its other constructs
still get measured. That edit is to the test input, not to conversion code — the
no-fixes non-goal above still holds — and the report states plainly that the pattern
was measured in modified form.

## Deliverable

`docs/reviews/2026-09-02-sv-patterns-roundtrip-fidelity.md`, following the
`2026-07-29-ossie-tpcds-fidelity.md` precedent:

- Method and environment, including the tolerance and normalisation rules
- Per pattern: structural survival table + query verdict table
- Synthesis: every finding classified as **confirms** a predicted matrix row,
  **refutes** one, or is **new**
- Routing: each finding to a validator or a dated `BL-NNN`, per the two-bucket rule in
  `.claude/rules/repo-audit.md`

Coverage-matrix corrections land in the same PR — a matrix row proven wrong is edited,
not just noted. If the evidence supports it, the PR also proposes unparking audit
angle 15 with this corpus named as its fixture.

New backlog ids start at **BL-231** (`docs/backlog.md` ends at BL-229; BL-230 is claimed
on branch `docs/bl-230-ascii-identifiers`). Per the CLAUDE.md resolution rule, re-check
the highest id at PR time rather than trusting this number.

Work happens in the worktree `/Users/damianwaldron/Dev/ts/wt-sv-roundtrip` on branch
`feat/sv-patterns-roundtrip-fidelity`.

## Risks

**A ThoughtSpot connection must see `AGENT_SKILLS.SV_PATTERNS`.** This is the one risk
that can block everything, so it is verified before the 16 are deployed. `APJ_TAB` is
the candidate. Connection introspection cannot confirm it — `connection/search` returns
an empty database/table hierarchy on this cluster for every auth type, live-verified and
recorded in `.claude/rules/ts-cli.md`. Confirm instead via `ts metadata search` filtered
on `metadata_header.dataSourceName`, and fall back to `ts connections create`.

**A new schema may sit outside an existing connection's scope.** `ts tables create` takes
explicit database/schema/table, so this is expected to work, but it is unproven for a
schema created after the connection. Same mitigation as above.

**`SE_ROLE` ownership implies but does not prove `CREATE SEMANTIC VIEW` in
`AGENT_SKILLS`.** The explicit grant observed is on `SKILLS.PUBLIC`. First deploy is a
single pattern, treated as the privilege probe.

**Shared cluster.** se-thoughtspot already carries 1,302 connections. Namespace every
created object and tear down at the end; the manifest from the deploy step is the
teardown input.

**Stage B translation is the method's weakest joint.** Turning a `SEMANTIC_VIEW()` tuple
into AgentQL is mechanical for the common shapes but not for all of them (`WHERE` on a
non-selected dimension, ordering semantics). Where a faithful AgentQL expression cannot
be written, record the query as `UNAVAILABLE` at stage B with the reason, and still run
A vs C — a missing middle stage costs attribution for that query, not the round-trip
number.

## Success criteria

1. All 16 patterns deployed to `AGENT_SKILLS.SV_PATTERNS` and round-tripped, or excluded
   with a recorded reason.
2. Every pattern has a structural survival table and a query verdict table.
3. Every coverage-matrix row the corpus exercises is marked confirmed, refuted, or
   untested — including row 28, whose text currently concedes it has never run live.
4. Every finding is routed to a validator or a dated `BL-NNN`. Nothing is left as
   "we noticed this."
5. All created Snowflake and ThoughtSpot objects are torn down, verified by re-running
   the manifest.
