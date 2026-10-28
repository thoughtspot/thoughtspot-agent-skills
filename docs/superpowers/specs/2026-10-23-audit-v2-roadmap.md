# ts-audit v2 — roadmap

**Status:** accepted by the product owner (PR #668) · **Date:** 2026-10-23
**Inputs:** the expert rule review (2026-10-23, kept outside the repo — role labels only),
the BL-406 contradiction sheet, the product owner's rulings in conversation (recorded
below), production call-home size data (aggregates only), and the RLS support case
(kept outside the repo).

## Principles every item must keep

1. **Deterministic code decides; the LLM only orchestrates.** Anything mechanical (finding
   objects, filtering, exporting, grading, rendering) is `ts` CLI code, not skill prose the
   LLM executes. Faster, repeatable, cheaper in tokens.
2. **The rule files are the single source.** Every piece of documentation that describes a
   rule, category or profile is generated from the catalog and gated by
   `generate --check`. Nothing restates a rule by hand.
3. **The report is assembled from parts.** One file per view plus a registry; a fixed
   audit JSON renders every view in a test. A new view is a new file and a registry line.
4. **Every finding change is visible.** Each PR that changes findings carries the re-pin
   output and a before/after count on the SE demo snapshot and on the support-case Model.
5. **Public repo.** Synthetic fixtures; customer data, names and cluster hosts never in
   the repo, commits or PRs.

## Rulings already made (2026-10-23)

- Retire **S3** (unmasked personal data — never reads column security; back when it reads
  Column Security Rules), **P9** (ID columns indexed — search indexing is unrelated to
  query performance), **S8** (text column in an RLS rule — no security premise), **P5**
  (no date limit on fact tables — a design choice, wrong fact detection) and **D6**
  ("fact" table with >40% attributes — grain is keys and dates). **A5** (Spotter
  readiness score) stops being a finding and becomes a score in the report header and
  heatmap.
- Merge the duplicate pairs into one rule each: **D2→P6** (text join keys, LOW;
  multi-key joins INFO), **D4→P4** (all joins forced on every query; categories D and
  P), **S9→P14** (function in an RLS rule; performance, not security).
- **P2 kept, reworded:** a row-level formula is recomputed by the warehouse on every
  query; materialise heavy ones as a column in ETL. Modest severity.
- The 16 BL-406 contradictions follow the decision sheet's recommendations, except where a
  rule above is retired or merged (S3, D6, A5, D2 resolved by those).
- Formula `aggregation:` is ignored in query generation except for `group_aggregate` and
  `last_value`/`first_value` formulas with no aggregation inside — so additivity checks
  target physical columns and those formulas only.
- Date-part columns are usually unnecessary (date keywords cover them): a LOW hint, not an
  error. Many-side aliases and Spotter parameters are in rollout: LOW warnings, not errors.
- A large number of hidden **ordinary** columns is a smell (remove them, or use column
  security); hidden **formulas** used by other formulas are the legitimate case.

## The work, in PRs, in order

Each PR gets a short design note (or a section of this roadmap) and a plan before it is
built; each is reviewed and merged on its own. Wave order is chosen so earlier PRs make
later ones cheaper.

### Wave 1 — foundations (make everything after this cheaper and safer)

| PR | What | Why first |
|---|---|---|
| 1.1 | **Generated `SKILL.md` blocks.** The category table, the Step 0/2 angle lists, the profile description (pass marks, column lines) and the rules-file table become generated blocks under `generate --check`. | Every later PR changes rules; without this each one must hand-edit the skill and will drift. |
| 1.2 | **Report Model stats fix.** Join count and join depth read `model_tables[].joins` (they read a Model-level `joins` key Model TML does not have, so every Model shows 0 / 0 since #140). | A visible bug in every report today; tiny. |
| 1.3 | **`ts audit run` owns scope and fetch** (BL-407). Options for a connection list and "all Models"; the skill's Steps 3–4 (LLM-run search, hand filter, manual TML export) shrink to choosing the scope. | Principle 1; removes the LLM's most expensive, least reliable work. |

### Wave 2 — BL-406: make the existing rules right

| PR | What |
|---|---|
| 2.1 | **Retire, merge, reword** per the rulings above (S3, P9, S8, P5, D6 retired; A5 → report score; D2→P6, D4→P4, S9→P14 merged; P2 reworded). |
| 2.2 | **The 16 contradictions** per the sheet: A4 retitle; D7 identical HIGH / partial MEDIUM only with a shared fact; H10 MEDIUM when also orphan; H1/H2 per-Model counts kept; D11 wording and reach (MANY_TO_MANY, referencing joins); docs-only fixes where the code was right (D5, D9, S1, S2, S5). |
| 2.3 | **Noise fixes:** H2's "The "/"A " boilerplate pattern; D3's outer-join INFO volume; alias-vs-name lookups (D10, D11, H3); A1/A2 coverage over visible columns only; S1's pattern word boundaries and display names (with BL-112). |
| 2.4 | **Grading into data:** D1's per-measure lines, H2's and H10's limits and wording become catalog bands/messages (profile-overridable). Includes the A5-null-name crash and P2's expression-based "scalar" test, and the housekeeping (unused constants, duplicated name regex, stale fixture titles, `parent.` semantics on malformed TML). |

### Wave 3 — report structure, then the formula tree

| PR | What |
|---|---|
| 3.1 | **Split the report template** into one file per view plus a view registry; a render test over a fixed audit JSON for every view. No visible change. |
| 3.2 | **Formula dependency tree** view: per Model, how formulas build on each other (ratio → its inputs → theirs), expand/collapse, with hidden helper formulas marked. Built as the first view on the new structure. |

### Wave 4 — better judgement, then new rules

| PR | What |
|---|---|
| 4.1 | **Role inference from join direction** (fact / dimension / bridge / outrigger), shared by the audit, the ERD and the future remodel tool; replaces "more than 3 measures = fact". |
| 4.2 | **Severity rubric:** each rule declares its evidence class; a heuristic alone cannot exceed MEDIUM; the catalog gate warns when a rule fires on most Models of the SE snapshot. |
| 4.3 | **New rules, set 1** (TML alone, high value): undocumented visible measures (G4); hidden ordinary columns (new); one term naming two columns (G3); non-additive physical columns or LOD/last-value formulas summed (G1, as corrected); redundant or conflicting Table-level joins (G14); join key type mismatch (G11); technical columns visible (G15). |
| 4.4 | **New rules, set 2:** RLS robustness — outer-joined table under an RLS rule with no `is_null` clause, an RLS path through a one-to-many join, rules that build no suggestion index (G5); IDs, zip codes and coordinates typed MEASURE, and the date-part hint (G2, as reframed); many-side alias and Spotter-parameter warnings (G9, G10); flags as 0/1 measures (G17); slot-named columns with no aliases (G19). |

### Wave 5 — the proposed Model

| PR | What |
|---|---|
| 5.x | **`ts-object-model-remodel` skill** (own design first): from Model + Table TML and role inference, a remodel plan, lint-clean proposed Model TML, and current vs proposed ERDs through `ts-object-model-erd`. First target: the RLS repair shape (tenant rule on each table's own key; group scope on an RLS-only lookup). |

### Not scheduled (backlog items, filed in the PR that defers them)

- G6 fan-trap / mixed grain, G7 semi-additive snapshots, G16 role-play alias bloat, G20
  cross-Model conformance — after 4.1 (they need role inference).
- G8 SCD-2 current-row handling, G12 text dates / fact with no date, G13 keyword-named
  columns, G18 date-column guidance, G21 units and formats, G22 usage-aware orphans
  (needs usage data).
- S3's return once Column Security Rules are read.
- BL-410 (diamonds through RLS joins) — parked by the user.

## Done means

Each wave's PRs merged with green CI; the SE snapshot before/after recorded in each PR;
the support-case Model re-audited at the end of waves 2 and 4 (locally) showing its
findings reduced to the actionable set; generated docs and the report render test
passing; no hand-written restatement of a rule left in the skill.
