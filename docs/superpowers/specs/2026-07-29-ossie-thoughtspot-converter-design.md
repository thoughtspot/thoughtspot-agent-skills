# Design: ThoughtSpot ↔ Apache Ossie converter + upstream learnings review

**Date:** 2026-07-29
**Status:** Phases 1–2 complete (PR #411); upstream posting of mapping docs parked pending ThoughtSpot legal approval; Phase 3 plan pending upstream feedback on #285.
**Owner:** Damian Waldron

## Background

Apache Ossie (incubating; formerly Open Semantic Interchange / OSI) is an ASF
project standardising semantic-model exchange across analytics/AI/BI platforms
(hub-and-spoke: each vendor ships an import + export converter against the
Ossie core spec). ThoughtSpot is involved in the initiative but has no code
contribution upstream yet — a scan of the last 100 commits on `apache/ossie`
shows Snowflake, dbt Labs, Honeydew, RelationalAI and WisdomAI authors, no
`@thoughtspot.com`.

Upstream repo facts (verified 2026-07-29):

- `converters/<vendor>/` packages, mostly Python (`pyproject.toml` + `uv.lock`,
  `src/ossie_<vendor>/`, `tests/` with fixtures), one CI workflow each
  (`.github/workflows/converter-<vendor>-ci.yml`).
- **Databricks converter is the gold-standard pattern**: `_common.py`,
  `metric_view_to_ossie.py` / `ossie_to_metric_view.py`, `cli.py`, fixtureA/B +
  TPC-DS fixture pairs, roundtrip tests, property-based roundtrip tests.
- **Snowflake converter is one-directional today** (Ossie → Snowflake YAML only).
- Shared assets: `core-spec/spec.md` + `ossie-schema.json` +
  `core-spec/expression_language.md`, `python/src/ossie/models.py`,
  `validation/validate.py`, `examples/tpcds_semantic_model.yaml`.
- `custom_extensions[].vendor_name` is a **free-form string** — using
  `THOUGHTSPOT` requires **no spec change**; we only add a row to the
  "well-known examples" table in `spec.md`.
- Contribution process is ASF: the dev mailing list is the decision channel.
  **No CLA is required to contribute** (`CONTRIBUTING.md`, corrected upstream in
  PR #339, 2026-08-29): an ICLA is needed only once a contributor is *elected as a
  committer*, before their Apache account is created, and a CCLA is likewise not
  required for contributions. The same commit dropped the `Signed-off-by`
  convention, asking only that commits be attributed to the correct author. An
  earlier version of this spec stated the pre-#339 text, which required an ICLA
  before a first non-trivial contribution could merge.

## Scope

Three deliverables:

1. **Workstream A (upstream):** a bidirectional `converters/thoughtspot/`
   Python package in `apache/ossie` — ThoughtSpot Model TML → Ossie and
   Ossie → Model TML — contributed via a single staged PR from a fork.
2. **Workstream B (inward):** a learnings review of the upstream Databricks +
   Snowflake converters against this repo's `ts-convert-to/from-snowflake-sv`
   and `ts-convert-to/from-databricks-mv` skills. Deliverable: a written report
   plus two-bucket routing (dated `BL-NNN` backlog entries, or trivial
   immediate fix PRs).
3. **Cross-cutting: expression/function mapping document.** Every function and
   operator surface in `core-spec/expression_language.md` classified as:
   - **direct** — a native ThoughtSpot formula function equivalent exists;
   - **passthrough** — requires ThoughtSpot `sql_*` passthrough functions
     (with an explicit caveat that passthrough bodies are warehouse-dialect-
     specific and bypass ThoughtSpot query planning);
   - **unmappable** — no representation; the converter must raise a converter
     issue (never silent loss).
   Canonical copy lives in the upstream converter package; a derivative copy
   lives in `agents/shared/mappings/ts-osi/` in this repo.

### Non-goals

- No `ts-convert-osi` skill or ts-cli wiring in this repo — separate later
  project once the upstream converter merges and stabilises.
- No live-instance API calls inside the converter — file-to-file only, like
  every other Ossie converter.
- No Liveboard/Answer/dashboard conversion — Ossie's scope is the semantic
  model.
- Worksheets out of scope — Models only.

## Decisions made

| Decision | Choice | Rationale |
|---|---|---|
| Converter direction scope | Bidirectional in one PR | Matches upstream databricks/omni quality bar (roundtrip tests need both) |
| Repo scope | Upstream PR only; no skill wiring here yet | Keep one repo changing at a time |
| Learnings deliverable | Report + BL-NNN routing | Repo's standard two-bucket rule |
| Sequencing | Spec-first, staged | Mapping docs reviewed on the dev list before code → less review churn |
| Function-map home | Both repos (canonical upstream, derivative here) | Upstream reviewers need it; our tooling references it offline |
| Prior art | None — start from scratch | Derive from this repo's TML schemas + Ossie core-spec |

## Phases

### Phase 0 — ASF prerequisites (user actions, parallel with Phase 1)

1. **Subscribe + intro:** empty email to `dev-subscribe@ossie.apache.org`,
   reply to the confirmation, then send an intro to `dev@ossie.apache.org`
   announcing the planned converter (draft below).
2. **No CLA step.** Removed 2026-08-31 — neither an ICLA nor a CCLA is required to
   open or merge a contribution (see Background). An ICLA becomes relevant only on
   election as a committer. ThoughtSpot's own internal OSS-contribution approval is a
   separate matter and was **granted 2026-08-31**.
3. **Raise intent:** GitHub issue on `apache/ossie` (draft below) + two-line
   dev-list message linking it. Better filed once Phase 2 drafts exist so
   there's substance to react to; the only hard rule is announce before the PR
   lands.

#### Draft intro email (dev@ossie.apache.org)

> **Subject:** Intro — Damian Waldron (ThoughtSpot), planning a ThoughtSpot
> converter contribution
>
> Hi all, I'm Damian Waldron, [role] at ThoughtSpot. ThoughtSpot has been
> involved in OSI since [context], and I'm planning to contribute a
> bidirectional ThoughtSpot converter (ThoughtSpot Model TML ↔ Ossie),
> following the pattern of the Databricks converter. I'll open a GitHub issue
> shortly with the proposed construct and expression mappings for feedback
> before I start on code. Looking forward to working with the community.

#### Draft GitHub issue (apache/ossie)

> **Title:** Proposal: ThoughtSpot converter (bidirectional, TML ↔ Ossie)
>
> **Body:**
>
> ThoughtSpot would like to contribute a converter between ThoughtSpot's
> semantic model format (Model TML + Table TML, YAML) and the Ossie semantic
> model, following the established converter pattern.
>
> **Scope**
> - Bidirectional: `tml_to_ossie` (import) and `ossie_to_tml` (export)
> - File-to-file, Python, mirroring the `converters/databricks` package shape
>   (fixtures incl. a TPC-DS pair, roundtrip + property-based tests, per-
>   converter CI workflow)
> - `custom_extensions` with `vendor_name: THOUGHTSPOT` for lossless roundtrip
>   of ThoughtSpot-only concepts; one row added to the well-known vendor
>   examples table in `core-spec/spec.md`
> - Construct-mapping and expression/function-mapping documents will be posted
>   on this issue for community review **before** the code PR
>
> **Proposed mapping sketch (high level)**
> | Ossie | ThoughtSpot |
> |---|---|
> | `datasets` | Model `model_tables` + Table TML (physical `source`) |
> | `fields` | table columns / ATTRIBUTE formulas |
> | `metrics` | MEASURE columns / formulas |
> | `relationships` | Model `joins` |
> | `ai_context` | synonyms, Spotter instructions |
> | `custom_extensions[THOUGHTSPOT]` | join types, aggregation defaults, formats, other TS-only metadata |
>
> Happy to adjust scope/shape based on feedback — the mapping docs will follow
> as comments on this issue.

### Phase 1 — Deep review of DBX + Snowflake converters (Workstream B + template for A)

Read upstream: `converters/databricks/` (full pattern incl.
`test_roundtrip_properties.py`), `converters/snowflake/` (one-directional —
itself a data point), `core-spec/spec.md`, `ossie-schema.json`,
`expression_language.md`, `python/src/ossie/models.py`,
`validation/validate.py`, and the `converter_issues.py` pattern in dbt/wisdom
(structured "what was lost" reporting; orionbelt's
`test_osi_metric_no_silent_loss` is the strongest expression of it).

Compare against this repo's four converter skills + `agents/shared/mappings/`
on these dimensions:

- expression-translation architecture (table-driven vs ad hoc)
- lossless roundtrip via `custom_extensions` vs our one-way fidelity approach
- silent-loss prevention (converter issues) vs our coverage-matrix approach
- fixture strategy (shared TPC-DS model across vendors) and property-based
  testing (we have neither)
- CLI/packaging conventions

**Deliverable:** `docs/reviews/2026-MM-DD-ossie-converter-learnings.md` in this
repo; every actionable finding routed per the two-bucket rule (validator or
dated `BL-NNN` in `docs/backlog.md`; trivial fixes as immediate small PRs).

**Open questions to resolve in this phase:**

- Does `ossie-schema.json` constrain `custom_extensions` shape beyond
  `vendor_name` + `data` (JSON-string) — and is `data`-as-JSON-string awkward
  for our nested TS metadata?
- Does the Go CLI plugin contract (`cli/internal/plugin/`) impose requirements
  on a converter's `cli.py` beyond what databricks does?
- Is the shared `python/` `ossie` models package intended as a converter
  dependency (converters differ today: gooddata has its own `models.py`)?

### Phase 2 — Mapping documents (the spec for the converter)

1. **Construct mapping** — Model TML + Table TML ↔ Ossie semantic model:
   `model_tables`/tables → `datasets`; columns → `fields`; MEASURE
   columns/formulas → `metrics`; `joins` → `relationships`;
   synonyms/instructions → `ai_context`; and the
   `custom_extensions[THOUGHTSPOT]` payload design for lossless roundtrip
   (join types, aggregation defaults, formats, Spotter instructions, other
   TS-only concepts discovered during drafting). The TS side is grounded in
   `agents/shared/schemas/thoughtspot-model-tml.md` and
   `thoughtspot-table-tml.md` (the repo's authoritative TML invariants).
2. **Function mapping** — the document described in Scope item 3: one row per
   `expression_language.md` function/operator → direct / passthrough /
   unmappable, with dialect caveats on every passthrough row.
3. Post both to the GitHub issue + dev list for early feedback before code.

### Phase 3 — Build the converter (fork of apache/ossie)

Mirror the databricks package shape:

```
converters/thoughtspot/
  README.md                      # incl. both mapping tables; ASF license headers everywhere
  pyproject.toml + uv.lock
  src/ossie_thoughtspot/
    __init__.py  cli.py  _common.py
    tml_to_ossie.py  ossie_to_tml.py
    expressions.py               # function-mapping table as code
    converter_issues.py          # no-silent-loss reporting
  tests/
    fixtures/                    # fixtureA/B TML+ossie pairs; tpcds_* pair matching examples/tpcds_semantic_model.yaml
    test_tml_to_ossie.py  test_ossie_to_tml.py
    test_roundtrip.py  test_roundtrip_properties.py
.github/workflows/converter-thoughtspot-ci.yml
converters/README.md             # add THOUGHTSPOT vendor row
core-spec/spec.md                # add THOUGHTSPOT to well-known vendor examples table
```

Build rules:

- Generated TML obeys this repo's critical TML invariants (`db_column_name`
  always present; `guid:` at document root; `formula_id` ↔ `formulas[].id`
  pairing; formula cross-refs by id; `aggregation:` only in `columns[]`;
  CHAR + object-form `list_choice` for list parameters).
- Ossie output validated with `validation/validate.py` against
  `ossie-schema.json`.
- TPC-DS fixture pair gives cross-vendor comparability — the same model every
  other converter round-trips.
- TML fixtures verified once against a live ThoughtSpot instance
  (`ts tml import` on a scratch instance) so the TS side is real, then frozen —
  upstream CI stays offline.

### Phase 4 — PR + upstream review

One PR from the fork: converter package + CI workflow + the two doc touches.
Follow the upstream PR template; respond to review on GitHub and the dev list.
No CLA gates the merge. A converter PR passes by lazy consensus — one binding **+1**
from a committer and no unresolved **-1**. Note this does *not* cover **A1**: adding
`THOUGHTSPOT` to the `Dialect` enum is a *specification* change, which needs a dev@
announcement, a minimum 7-day discussion window and a `[VOTE]` carrying three binding
**+1**s. File it as its own PR, early — PR #143 (`BIGQUERY`, 3 files) took 41 days.

### Phase 5 — Back-port into this repo

PR here adding `agents/shared/mappings/ts-osi/` (function-mapping derivative +
construct mapping), stage-sync per the change-impact map (`agents/shared/`
change ⇒ `./scripts/stage-sync.sh` after merge), plus the Phase 1 report and
backlog entries if not already merged.

## Testing & error handling

- Roundtrip tests both directions (TML→Ossie→TML and Ossie→TML→Ossie) using
  semantic equality, plus hypothesis property-based roundtrip tests
  (databricks pattern).
- Every dropped construct surfaces as a converter issue — never silent. This
  is the strongest single pattern upstream enforces and it aligns with this
  repo's coverage-matrix discipline.
- Unit tests for the pure mapping functions; no live connection required in
  upstream CI.

## Success criteria

1. Upstream PR merged with bidirectional converter + CI green.
2. Function-mapping doc reviewed upstream and mirrored in
   `agents/shared/mappings/ts-osi/`.
3. Learnings report merged here with every finding routed (validator, BL-NNN,
   or fix PR) — nothing left as "we noticed this".
