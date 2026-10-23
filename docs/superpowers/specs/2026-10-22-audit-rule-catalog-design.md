# Audit rule catalog — design

**Status:** draft for approval · **Date:** 2026-10-22 · **Skill:** `ts-audit` (engine in
`tools/ts-cli/ts_cli/audit/`)

## Intent

`ts-audit`'s rules will change: some become obsolete, new ones are wanted, thresholds move.
Today every one of those is a code change. Each of the 51 live checks is a Python function
with its threshold, severity, wording and category baked in, and the human-readable catalog
(`agents/cli/ts-audit/references/check-catalog.md`), `CHECK_META`, the test fixtures and the
HTML report template are separate hand-kept copies that have drifted (16 disagreements
between catalog and code, found 2026-10-22).

This project turns the rules into **data**: a rule catalog the engine reads, so adding,
changing or retiring a rule — or a category — is a catalog edit plus a test, not an engine
change.

It serves two audiences, in order:

1. **This repo.** `ts-audit` runs on the framework, so the pattern is proven against a real
   cluster, not only on paper.
2. **Engineering.** They review the working code as a reference design and build the same
   pattern into the product. The working code is the handover; no separate
   language-neutral spec is required (user's decision).

**How rules get changed (user's decision):** the user describes a rule in conversation and
Claude writes it. So the catalog format must be easy for the user to *review*, and the
authoring path must be a documented procedure Claude follows, guarded by validation and
tests — not a format optimised for hand-editing by non-engineers.

**Ownership (user's decision):** initially product/engineering own the rules and ship them
per release (option 1). The design must leave room for per-cluster / per-Org admin overrides
of thresholds, severities and enablement (option 2) **without building them now**.

## Goals

- Adding, changing or retiring a rule is a catalog edit plus a test. No engine change for any
  rule that fits the rule types the engine supports.
- Categories (today's A/D/H/P/S angles) are data: label, order, description. A rule can
  belong to several categories. Adding a category needs no code.
- Each rule declares the data it needs; the engine fetches the union of what the selected
  rules need. (Today data fetching is keyed by category letter — `context.py:278,291` — so
  moving H8 out of H would silently starve it of Answers.)
- Assessment profiles (Spotter-ready / General, added in BL-399) become named override sets
  in the catalog, applied by the same mechanism a future admin override layer would use.
- One finding contract: every finding carries a uniform threshold payload with a
  **direction** (higher-is-better or lower-is-better) and bands, so the report renders every
  metric correctly. (Today there are 10 threshold payload shapes and the report treats every
  metric as a higher-is-better percentage against 80, so a complexity violation renders as a
  green bar.)
- The check catalog doc, `CHECK_META`, and the report's category labels and per-rule
  recommendations are **generated from** the catalog, with a `--check` gate so they cannot
  drift.
- A rule that cannot be expressed as data is a **named code rule** registered under the same
  catalog: one list of every rule, whatever implements it.

## Non-goals

- **Admin overrides (option 2) are not built.** The design specifies the layering and which
  keys are overridable so they can be added later without changing the catalog format.
- **No behaviour change in the conversion.** See Migration: the first version reproduces
  today's findings exactly. The 16 contradictions, the alias bugs and the other defects
  listed under "Follow-up" are fixed *afterwards*, each as a separate, reviewable rule edit.
- No new checks as part of this project.
- No UI for editing rules.
- No language-neutral spec document.

## Anti-goals (would make it a failure even if it works)

- A catalog that only an engineer can read. The user reviews every rule change; each rule
  must read close to how they would say it.
- A general-purpose expression language. The point is a small, safe set of rule types with
  parameters, which engineering can re-implement and admins could one day override. If a
  rule needs real logic, it is a named code rule, not a clever expression.
- Silent failure. A mistyped rule, an unknown field, or a rule whose examples no longer
  behave as stated must fail the commit, never quietly stop running.
- A conversion that "mostly" matches. Any difference in findings between old and new engines
  blocks deleting the old checks.

## Evidence the approach fits

A read of all 51 registered checks (2026-10-22) classified each by shape:

- **27 / 51 are pure data today**: a scope, a filter, a measure, and severity bands.
- **49 / 51 become data** with six aggregation modes and ~17 derived fields computed once in
  the engine.
- **2 / 51 clearly remain code**: H3 (hidden column not referenced, with a sole-join-carrier
  exemption) and S3 (PII without masking — a heuristic over RLS expressions). The review
  found four more likely code rules (A5, D10, D11, H10); see "Decisions settled during
  review" — the count is an estimate, not a target.
- Several checks are the same rule filed under two categories (D4 = P4; P14 = S9; the HIGH
  half of D2 = P6; D1's join-depth band ≈ P7). Multi-category rules remove the copies.

## The rule model

A rule is one catalog entry. Fields (names are the builder's call; the *concepts* are fixed):

| Concept | Meaning |
|---|---|
| id | Stable id, e.g. `A6`. Ids are never reused; a retired rule keeps its id. |
| title, description | Plain-English what and why, shown in the report and generated catalog. |
| status | `active` or `retired` (retired rules don't run but stay in the catalog so old reports still resolve). |
| categories | One or more category ids. |
| scope | What the rule iterates over (engine-provided scopes, below). |
| where | A filter over the scope's items, built from the operators below. |
| measure | What is measured per item or per group (a field, a derived field, a count). |
| aggregate | One of the aggregation modes below. |
| bands | Ordered severity bands over the measure, with a **direction**, e.g. lower-is-worse: `< 40 → HIGH, < 80 → MEDIUM`. Comparison operators are explicit per band (today coverage passes at `>=` and counts fire at `>`; both must be expressible). |
| severity rules | For presence/each rules: a fixed severity, or severity chosen from an item field (e.g. join type `OUTER → HIGH, LEFT_OUTER → INFO`; S2's `INFO if the table has RLS else HIGH`). |
| profiles | Per-profile overrides of `bands` / severity / enablement (e.g. A1 Spotter-ready 95, General 50). |
| message | A template for the finding's detail text, with placeholders for counts, metric, names. |
| remediation | The recommendation text and, where relevant, the follow-up skill. |
| display | Unit (%, count, depth) and whether higher is better — drives the report's metric bar. |
| requires | Data dependencies (Model TML, Table TML, AI instructions, dependents, Answers, Sets, metadata headers). |
| examples | At least one input that must fire (with expected severity) and one that must not. Run as tests. |
| implementation | `declarative` (default) or `code:<name>` for a registered code rule. |

### Engine-provided scopes

model · model.column · model.formula · model.filter · model.table (keyed by **alias**) ·
resolved join · table · table.rls_rule · rls column reference · answer · answer.table_ref ·
answer.formula · set · metadata header.

### Aggregation modes

| Mode | Meaning | Today's examples |
|---|---|---|
| each | one finding per matching item | D3 join type, P9 ID-like indexed column, S5 credential names |
| ratio | share of a parent's children matching a predicate, against bands | A1, A2, A6, D9, H1 |
| count | a count or metric against bands | D1 (several measures), P2, P8, P13, P16 |
| group | group items by a key, then flag duplicates (size > 1) or divergence (distinct values > 1) | D8, D12, H8 |
| pairwise | set similarity between two objects | D7 (Jaccard over table sets) |
| composite | weighted combination of other rules' metrics | A5 readiness score |

### Operators (inside `where` and severity rules)

exists / empty · equals / in · regex with an exclusion list · numeric comparison · length ·
contains · and / or / not · count over a sub-collection.

### Derived fields (code, written once)

~17 fields the engine computes so rules can refer to them by name, e.g. column
`is_indexed`, `data_type` (resolved from the Table TML via the alias), `has_synonyms`,
`is_pii(category)`, `table_has_rls`; model `has_ai_instructions`, `join_depth`,
`dependents_excluding_sets`; table `role` (fact/dimension), `is_joined`; join `key_types`,
`key_count`; formula `ref_depth`, `is_aggregated`, `normalised_expr`. Each derived field is a
small pure function with its own unit test. The exact list falls out of the conversion.

### Code rules

A rule that genuinely needs logic (H3, S3 today) is a Python function registered under a
name and referenced by `implementation: code:<name>`. It still has its catalog entry (id,
categories, bands where applicable, message, remediation, requires, examples), so it appears
in the generated catalog and report like any other rule. A code rule returns the same finding
contract.

## Categories and profiles

- **Categories** live in the catalog: id, label, display order, description. The report's
  tabs, heatmap columns and labels come from here; nothing in code or the template lists
  categories. The CLI's `--angles` selects categories by id; a rule runs if any of its
  categories is selected.
- **Profiles** (assessment profiles) live in the catalog as named override sets — exactly
  the shape a future admin override would take. The BL-399 table in `assessment.py` moves
  here. A5 is not profile-aware today; that stays true in the conversion and is a follow-up.

## Override layering (designed now, built later)

Effective rule = catalog default → profile → *(future)* cluster override → *(future)* Org
override, each layer may change only an allow-listed set of keys:

- **Overridable:** `status` (enable/disable), band thresholds, severities, `message` /
  `remediation` wording.
- **Not overridable:** `scope`, `where`, `measure`, `aggregate`, `implementation`,
  `requires` — what a rule *means* is product-owned.

Each finding records which layer supplied its threshold and severity (provenance), so a
report produced under overrides is explainable. In this project only the first two layers
exist; the merge function is written for N layers with tests using a synthetic third layer.

## Finding contract

Existing fields stay (`check_id`, `angle`, `severity`, object type/name/guid, `detail`,
`metric`, the legacy `threshold` dict). New fields: `categories`, and one uniform band
payload `{direction, unit, bands: [{op, value, severity}], profile, provenance}`. The
report's metric bar reads the new payload when present (so lower-is-better metrics render
correctly) and falls back to the legacy dict for old JSON. See "Decisions settled during
review".

## Generated artifacts

From the catalog, a generator (with `--check`, wired into pre-commit and CI like this repo's
other generators) writes:

- `agents/cli/ts-audit/references/check-catalog.md` — the human catalog, one row per rule,
  the severity column rendered from bands/profiles.
- `CHECK_META` (or its replacement) — consumed by the report.
- The report's category labels, order and per-rule recommendations (today hard-coded in
  `report_template.html`, lines ~778-783, 1039-1059, 1196). The template's two rule-specific
  views — the duplicates tab driven by D8 and the cleanup tab driven by H4/H5/H10 — become
  catalog flags (e.g. a rule declares it feeds the "cleanup" view) rather than ids in JS.

## Validation and the authoring procedure

- **Schema + validator**, run in pre-commit and CI: unknown keys, unknown scopes/modes/
  operators/derived fields/code-rule names, missing examples, reused or duplicate ids, a
  category id that does not exist, profile overrides touching non-overridable keys — all
  fail the commit.
- **Every rule's examples run as tests**: the "fires" example must produce exactly the
  stated severity; the "does not fire" example must produce nothing.
- **Authoring procedure** — a reference doc in the skill (e.g.
  `agents/cli/ts-audit/references/rule-authoring.md`) that Claude follows when the user
  describes a rule: restate the rule in plain English for confirmation; pick scope / mode /
  bands; write the entry and its examples; run validator + tests + the generator; show the
  user the generated catalog row and, where a live profile exists, the rule's findings on a
  real cluster before committing. Retiring a rule = `status: retired` plus a changelog line.
  The same doc covers adding a category, adding a derived field, and when to fall back to a
  code rule.

## Decisions settled during review (my calls — not the user's)

**Snapshot and replay; the equivalence gate compares rule logic over one shared context.**
Today `build_context` (`context.py:191+`) only fetches live, so a large corpus cannot be
replayed. The project adds a **snapshot**: `ts audit run --snapshot-out <dir>` writes the
fetched context (Model and Table TML, AI instructions, dependents, Answers, Sets, metadata
headers) to local JSON, and `--snapshot-in <dir>` runs from it with no cluster. Both engines
then run over the *same* snapshot, so any difference is the rules, not a cluster that changed
between two live runs. The rule-declared data fetching (`requires`) is tested separately:
a recording fake client asserts that a selection of rules fetches exactly the union of what
they declare — including the case that motivates it (a rule needing Answers runs without its
old category selected and still gets them). One live capture of the 351-Model corpus is
enough; it is never committed. The snapshot doubles as a useful feature (re-run or re-render
an audit offline).

**The audit JSON changes additively, and old runs still render.** Each finding keeps
`angle` (its first category) and gains `categories`; `summary.by_angle` stays, alongside a
new `summary.by_category`. The new uniform `threshold` payload is added as a new field
(e.g. `bands`), and the old per-check `threshold` dict is kept. So nothing that reads today's
JSON breaks, and `ts audit report` renders JSON produced before the cut-over. Removing the
legacy fields is a later, separate decision. Nothing outside this repo is known to read
`audit.json`; additive change makes that question moot.

**Bands are absolute and replaced whole.** A band list is always written out in full; a
profile (and a future override) replaces a rule's band list entirely, never a single number
inside it. So "General makes A6 a flat LOW" is just a different band list, there is no
"relative to the pass mark" syntax (the anti-goal), and an admin who changes A1's pass mark
supplies A1's full band list. The validator checks every *merged* band list: ordered, no
gaps or overlaps for its direction, valid severities. The overridable key is therefore
"bands" (the whole list), and provenance records which layer supplied the list.

**A multi-category finding counts once in totals, and once per category in category
views.** Severity totals and the finding count count it once. The heatmap, category tabs
and `summary.by_category` show it under every category it belongs to. The report states
that category columns can sum to more than the total.

**"Only H3 and S3 remain code" is an estimate, not a target.** The success criterion is the
equivalence gate plus the authoring procedure, not a count. Prefer declarative; but where a
check would need a bespoke mode, operator or cross-rule dependency used by nothing else, make
it a code rule. The likely candidates the review named: **A5** (its own denominators — an
empty model counts as one column — and its own name regex, so it does not reproduce as a
weighted mix of A1/A2), **D10** (bridge-vs-leaf), **D11** (needs table role and join
cardinality together), and **H10** (depends on H4's result). Each code rule still has a full
catalog entry and examples. Expected outcome: roughly 45 declarative, roughly 6 code.

## Migration: reproduce first, fix after (user's decision)

1. **Build the engine and catalog alongside the existing checks.** Convert all 51 checks,
   declarative where they fit and code rules otherwise (see the decision above). H6, a stub
   not in `ALL_CHECKS`, is recorded as retired.
2. **Equivalence gate.** Run old and new engines over the same snapshot and require identical
   findings — same rule ids, severities, objects, metrics, detail text and legacy threshold
   dicts:
   - the repo's existing audit tests and synthetic fixtures (committed);
   - a large **local, uncommitted** snapshot of the SE demo cluster (the 351 Models modified
     in the last 30 days, all categories, run under both profiles). This repo is public, so
     real snapshots are never committed; the comparison script is committed, the snapshot is
     not.
   Any difference blocks the cut-over. Only then are the old check functions deleted.
3. **Cut over**, regenerate the catalog doc, version bumps (ts-cli MINOR, ts-audit MINOR),
   CHANGELOG.
4. **Follow-up (separate PRs, each a deliberate rule edit with before/after findings):**
   - the 16 catalog-vs-code contradictions (D1, D2, D5, D6, D7, D9, D11, H1, H2, H10, S1, S2,
     S3, S5, A4 title, A5 not profile-aware) — for each, the user decides which side is right;
   - alias bugs: D10 (`checks_data.py:285`), D11 (`:312`), `rules.fact_tables`
     (`rules.py:187`, used by P5), H3 (`checks_human.py:108`) look tables up by name, not
     alias;
   - D11 ignores referencing joins (reads cardinality only from inline joins);
   - S3 claims to check CLS but column-security data is never loaded;
   - stale fixture titles (`test_fixtures.py:7-28`), unused constants, the `rules` shadowing
     in `checks_perf.py:241`, the duplicated `_NAME_ANTI`.
   These are listed now so nothing is lost; none are part of the conversion.

## Constraints

- Repo rules apply: worktree + PR, validators and tests green, the complexity cap
  (`check_module_health`, CAP 15) and file-size gate, version bumps at PR time, CHANGELOG,
  no customer data in the public repo (synthetic examples only).
- The catalog ships inside the `ts_cli` package (add it to `package-data` in
  `pyproject.toml`), loaded without network access.
- Runtime dependencies: PyYAML is already required; adding a JSON-schema validator to the
  runtime is the builder's call (it is currently a test-only dependency).
- Output of `ts audit run` / `ts audit report` keeps its command interface. The JSON gains
  fields; existing consumers (the report) are updated in the same change.

## Left to the builder

- Catalog file format details (YAML recommended — readable in review, and already used
  across the repo), file layout (one file vs one per category), exact key names.
- The concrete syntax of `where` / bands, provided it stays within the operator list.
- Module layout of the engine, derived-field registry and code-rule registry.
- The snapshot file layout.
- Whether the PR is split (engine + catalog behind a flag, then cut-over) or single, as long
  as the equivalence gate passes before the old checks are deleted.

## Calls I made (not from the user — check these)

- YAML as the recommended format; the authoring doc as the "describe it to Claude" path.
- Retire-don't-delete for rules; ids never reused.
- Allow-listed overridable keys (thresholds, severity, enablement, wording) and the
  layering order default → profile → cluster → Org.
- Multi-category rules replacing today's duplicated checks — **but only after** the
  conversion: during it, D4/P4 etc. stay as separate entries so findings match exactly.
- The equivalence corpus: committed synthetic fixtures plus a local, uncommitted SE-cluster
  snapshot.
- The five settled during review: snapshot/replay with a shared-context equivalence gate;
  additive JSON with old runs still rendering; absolute band lists replaced whole; a
  multi-category finding counted once in totals and per category in category views; the
  declarative count is an estimate, not a target.
