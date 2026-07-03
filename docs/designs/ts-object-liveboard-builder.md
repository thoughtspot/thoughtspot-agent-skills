# Design Proposal: `ts-object-liveboard-builder`

_A standalone skill that builds the **best possible** ThoughtSpot Liveboard for a domain —
applying BI + domain expertise — rather than faithfully mirroring a source dashboard. Also
reviews the model and proposes new KPIs/measures to improve analytics._

Status: **proposal / for review** · Author: migration session 2026-06-16 · Backlog:
**BL-026** ([`docs/backlog.md`](../backlog.md)) · Companion:
[`agents/shared/schemas/thoughtspot-chart-types.md`](../../agents/shared/schemas/thoughtspot-chart-types.md)

---

## 1. Motivation

The Tableau migration skill (`ts-convert-from-tableau`) is deliberately **faithful** — it
reproduces what the author built. But a faithful migration inherits the source's
limitations: missing KPIs, sub-optimal chart choices, no executive summary, no
period-over-period, charts chosen by a Tableau author years ago. Separately, a user with a
good **ThoughtSpot Model but no dashboard** has nothing to migrate from at all.

What's missing is a skill that asks a different question: *given this data, what is the best
analytical product we could build?* — answered by an agent acting as a senior BI analyst +
domain specialist. This proposal covers that skill and the two sub-asks:

- **(item 2)** Build the best liveboard for the domain; optionally take a Tableau file as a
  *hint* (what the business already tracks), not a *constraint*.
- **(item 3)** Make it **independent** of Tableau migration — a skill a user calls directly
  on a Model — and have it **review the model** (columns, measures, KPIs) and **suggest new
  KPIs/measures** that would improve analytics.

---

## 2. Goals / non-goals

**Goals**
- From a ThoughtSpot **Model** alone, produce an opinionated, well-structured liveboard.
- Recommend **KPIs and visualizations** grounded in the model's real columns + a profiled
  understanding of the data and inferred business domain.
- Propose **new derived measures** the model lacks (ratios, rates, period-over-period,
  segments) and, with approval, create them on the model.
- Be **callable standalone** and also **reusable** by `ts-convert-from-tableau` (an
  "enhance, don't just mirror" option).
- Always produce a **reviewable plan first**; never silently invent data.

**Non-goals**
- Not a faithful migrator (that's `ts-convert-from-tableau`).
- Not Spotter/NL readiness — synonyms, AI context, reference questions belong to
  `ts-object-model-coach` (cross-link, don't duplicate).
- Does not create warehouse tables or load data.
- Not a generic "edit any liveboard" tool — it *builds* a board from a model.

---

## 3. Where it sits — boundary analysis (critical)

Three skills touch this space; clear division prevents overlap:

| Skill | Question it answers | Owns |
|---|---|---|
| `ts-convert-from-tableau` | "Reproduce my Tableau workbook in ThoughtSpot." | Faithful parse → table/model/liveboard |
| `ts-object-model-coach` | "Make my model answer natural-language questions well." | Synonyms, AI context, reference questions, business terms |
| **`ts-object-liveboard-builder`** (new) | "Build the best analytical liveboard for this data, and tell me what metrics I'm missing." | KPI/viz recommendation, board composition, new-measure proposal |

**Shared seam:** the *liveboard emission* mechanics (viz TML, chart blocks, resolved-name
patch loop, obj_id read-back, theming, tabs) are currently embedded in
`ts-convert-from-tableau` Steps 9–11. They should be extracted to a **shared reference** so
both the migrator and the builder emit liveboards the same way (see §8).

---

## 4. Naming & family

**`ts-object-liveboard-builder`** — family 1 `ts-object-{type}-{verb}` (type=`liveboard`,
verb=`builder`), exactly parallel to the planned `ts-object-model-builder` and the shipped
`ts-object-model-coach`. No new family needed.

The model-enrichment capability (propose/create new measures) is delivered as a **stage**
of this skill, designed so it could later split into `ts-object-model-enrich` if it grows.

---

## 5. Inputs

| Input | Required | Role |
|---|---|---|
| ThoughtSpot **Model** | yes | The data foundation. Selected via the model picker (G guid / N name / F filter / L list-all) — reuse the picker added to `ts-convert-from-tableau` Step 1.5a. |
| **Domain hint** (user, one line) | no | "retail banking customers", "B2B SaaS subscriptions". Disambiguates when column names are generic. |
| **Tableau file** (.twb/.twbx) | no | Mined for *signal*: which fields/measures the business already visualizes = importance prior. Never a constraint. |
| Existing **liveboards/answers/query history** | no | Like model-coach: mine real usage to weight what matters. With authorization. |
| **Data profile** (live queries) | no, with auth | Cardinality, ranges, null rates, date span — to validate KPI feasibility and pick chart types. Read-only. |

---

## 6. The recommendation engine (the core IP)

A 7-stage pipeline. Each stage is grounded in real artifacts; nothing is invented.

### 6.1 Model profiling
Export the model; enumerate columns with type, role (ATTRIBUTE/MEASURE), aggregation,
formulas, parameters, and the date column(s) + grain. With authorization, profile the data:
distinct counts (cardinality), min/max/ranges, null rates, date span. Output: a structured
model fingerprint.

### 6.2 Column-role classification
Classify each column into analytical roles: **entity key**, **categorical dimension**,
**date/time**, **geo**, **additive measure**, **ratio/already-derived**, **high-cardinality
label** (e.g. Name — exclude from charts). Cardinality decides chart eligibility (a PIE needs
≤~6 categories; a 200-value dimension → BAR top-N).

### 6.3 Domain detection
Infer the business domain from column semantics + the optional domain hint (e.g.
`Balance`, `Customer`, `Region`, `Job Classification` → retail banking). Output: a domain
label + confidence + the matched signals. Low confidence → ask the user one question.

### 6.4 Analytical framework (intents)
Map the model to a standard analytical agenda — the angles a senior analyst always covers:
**magnitude** (totals/KPIs), **trend** (over the date), **composition** (mix), **ranking**
(top/bottom entities), **distribution** (spread across bands), **comparison/segmentation**
(cohort vs cohort), **correlation** (measure vs measure), **concentration** (Pareto/80-20),
**geography** (if geo). Only intents the data supports are kept.

### 6.5 KPI library (domain → metrics)
A curated, extensible `kpi-library` keyed by domain. Each entry: a metric, the columns/
formula it needs, the chart intent, and *why it matters*. Example (retail banking):
total customers, total/avg balance, balance per customer, customers by region/segment,
balance concentration (top-decile share), age/tenure distribution, new customers over time,
high-value-customer penetration. **Every proposed KPI is checked against the model** — if a
required column/measure is missing, it moves to §6.6 (propose it) or is dropped with a note.

### 6.6 New-measure proposal (the "suggest KPIs to improve analytics" ask)
Where the analytical agenda needs a measure the model lacks, propose it as a **new model
formula** — e.g. `Avg Balance per Customer = sum(Balance)/count(Customer ID)`,
period-over-period growth, penetration rate, a segment flag. Present each with its
expression, rationale, and the chart it unlocks. On approval, create them on the model
(reuse the obj_id read-back rule; back up the model TML first; fully reversible). This stage
is **independently runnable** ("just review my model and suggest metrics").

### 6.7 Chart-intent → chart-type mapping
Each kept intent + the column roles + cardinality select a chart type from the **verified
24** (see the companion chart-types reference). E.g. composition with ≤6 parts → PIE, else
TREEMAP; correlation → SCATTER, +magnitude → BUBBLE; concentration → PARETO; flow → SANKEY;
geo → GEO_AREA (only if a column is geo-tagged, else fall back to BAR + flag).

**Muze charting library (`ADVANCED_*`, early access).** When the target cluster has it
enabled, the builder can emit Muze (`ADVANCED_*`) types whose `custom_chart_config` shelf
model (`x-axis` / `y-axis` / `slice-with-color` / `trellis-by`) maps **cleanly onto this
engine's output** — series and small-multiples become first-class shelves rather than
implicit extra columns. Default to Legacy types for portability; make Muze an opt-in target.
See the chart-types reference "Muze charting library" section for the verified encoding rules
(don't mix `custom_chart_config` with a Legacy type).

### 6.8 Board composition
Assemble an opinionated layout, not a tile dump: **Tab 1 Executive Summary** (KPI row +
the 2–3 most important charts), **Tab 2+ analytical themes** (Trends, Segmentation,
Distribution, Geography…), grouped sections with titles/descriptions, a coherent theme,
parameter chips where useful. Apply the "best practices" an analyst would: lead with the
answer, one idea per tile, label everything, percentages formatted, sensible sort/top-N.

---

## 7. Flow (steps)

```
0.  Overview + mode (Build / Enrich-only / Plan-only)
1.  Auth + pick the Model (G/N/F/L picker) + optional domain hint   [batch where independent]
2.  Profile the model (+ optional data profiling, with auth)
3.  (optional) Ingest Tableau file / existing usage as importance signal
4.  Classify columns, detect domain  → confirm domain with the user
5.  Build the recommendation: KPIs, new-measure proposals, viz set, board structure
6.  PRESENT THE PLAN for approval — a written board spec (KPIs, each viz + chart type +
    why, new measures, tabs, theme). User edits/approves.   ← key checkpoint
7.  (approved) Create approved new measures on the model (backup first; reversible)
8.  Generate liveboard TML (shared emission library), validate, export-patch resolved names,
    re-import — using the model's REAL obj_id (read-back rule)
9.  Import + report (links, KPIs added, measures created, decisions, what was considered
    but dropped and why)
```

Modes: **Build** (full), **Enrich-only** (stages 1–2, 5-measures, 7 — no liveboard),
**Plan-only** (1–6, write the spec, no writes).

---

## 8. Independence & reuse architecture

Extract the liveboard mechanics into shared references consumed by **both** skills:

- `agents/shared/schemas/thoughtspot-chart-types.md` — the verified enum + intent mapping
  (**done** — promoted to shared, cited by `ts-convert-from-tableau`, on the coco stage list).
- `agents/shared/mappings/analytics/kpi-library.md` — domain → KPI patterns (§6.5).
- `agents/shared/mappings/analytics/chart-selection.md` — intent + roles + cardinality →
  chart type (§6.7), the decision logic.
- `agents/shared/schemas/thoughtspot-liveboard-tml.md` — already exists; the emission spec.

`ts-convert-from-tableau` keeps faithful mode, and gains an optional **"enhance" hand-off**:
after the model is confirmed (Step 7.5) it can offer "build a recommended liveboard instead
of / in addition to the faithful one" → delegates to the builder's stages 5–9. The builder
runs fully standalone with no Tableau input.

---

## 9. Grounding & guardrails (critical)

The biggest risk is a confident-but-wrong "expert" board. Guardrails:

1. **Never reference a column that isn't in the model.** Every KPI/viz is validated against
   the model fingerprint before it enters the plan.
2. **Profile before asserting ranges/feasibility.** Don't claim "top-decile share" without
   confirming the measure is additive and the entity cardinality supports it. Data reads are
   read-only and need user authorization.
3. **Plan-first approval.** Nothing is created until the user approves the written spec.
   New measures are approved item-by-item.
4. **Reversible model changes.** Back up the model TML before adding formulas; report exactly
   what changed; support rollback (mirror `ts-dependency-manager` backup pattern).
5. **Cite the reasoning.** Each recommendation states *why* (domain rationale + which columns
   it uses). Domain detection shows its confidence and signals.
6. **Opinionated but bounded.** Target a focused board (exec summary + 2–4 themed tabs), not
   40 tiles. Flag what was considered and deliberately left off.
7. **Reuse the obj_id read-back + resolved-name patch loop** — the failure modes are already
   known from the Tableau skill; don't relearn them.

---

## 10. Risks & mitigations (multi-angle)

| Angle | Risk | Mitigation |
|---|---|---|
| Correctness | Hallucinated KPIs / wrong domain | Ground in columns + profile; confirm domain; plan-first approval |
| Statistical | Non-additive measure summed; ratio-of-averages | Classify measures; build ratios as `sum/sum` not `avg(ratio)`; flag |
| UX | Over-built, noisy board | Opinionated composition, exec-summary-first, bounded tile count |
| Chart misuse | Pie with 50 slices, geo without geo-tag | Cardinality gates; geo only if geo-tagged, else BAR + flag |
| Model safety | Unwanted/duplicate formulas | Per-item approval, backup, reversible, name-collision checks |
| Overlap | Duplicates model-coach | Strict boundary (§3); cross-link, don't re-implement |
| Maintainability | Logic forks from the Tableau skill | Shared emission + chart-selection references (§8) |
| Trust | "Black-box expert" | Every recommendation cites its rationale + source columns |
| Determinism | Different board each run | Deterministic profiling + a fixed analytical agenda; LLM judgment only in prioritization, shown in the plan |

---

## 11. Plan of action (phasing)

- **Phase 0 — foundations (this PR):** verified chart-types reference promoted to
  `agents/shared/schemas/thoughtspot-chart-types.md`, cited by `ts-convert-from-tableau`, on
  the coco stage list (done) + this design.
- **Phase 1 — shared library:** author `chart-selection.md` + `kpi-library.md` (seed with
  2–3 domains: banking, retail, generic). Refactor Tableau Step 10a to also cite
  `chart-selection.md`.
- **Phase 2 — builder skill, Plan-only mode:** model picker + profiling + classification +
  domain detection + recommendation → write a board spec. No writes. Smoke test on
  `P1-UK-Bank-Customers`. This is independently valuable (item 3's "review + suggest").
- **Phase 3 — Build mode:** liveboard emission via the shared library + export-patch loop +
  obj_id read-back + theming/tabs. Import + report.
- **Phase 4 — Enrich mode:** new-measure proposal + approved creation on the model (backup +
  reversible).
- **Phase 5 — Tableau hand-off:** optional "enhance instead of mirror" delegation from
  `ts-convert-from-tableau` Step 7.5.
- **Phase 6 — domain library growth + evals:** expand `kpi-library` domains; add skill evals
  (skill-creator) measuring grounding (no invented columns) and plan quality.

Each phase ships as its own PR with a smoke test; Phase 2 is the minimum useful release.

---

## 12. Open questions for the user

1. **Measure creation default** — should Enrich create new measures on the *existing* model
   (mutates it, reversible) or on a *copy*? Recommendation: existing + backup, opt-in copy.
2. **Domain library scope** — which domains to seed first beyond banking/retail/generic?
3. **Tableau hand-off** — should "enhance" replace the faithful board, or add a second
   "Recommended" liveboard alongside it? Recommendation: add alongside, user chooses.
4. **Plan delivery** — board spec as an in-chat table (fast) and/or a written `*.plan.md`
   artifact (reviewable)? Recommendation: both, like the migration report.
5. **Naming of the enrich split** — keep enrichment inside the builder, or commit now to a
   future `ts-object-model-enrich`?
