# Skill personas: why each skill exists and who it is for

The [skills catalogue](../README.md#skills) answers *what* each skill does. This page
answers the three questions a catalogue cannot: **why it was built**, **who tends to
need it**, and **when to reach for it**.

Written for customer-facing technical field roles (SE, CSM, CSA, PS, SRE, PM) picking a
starting point, and for anyone deciding whether a skill fits a live customer situation.
Role labels are a hint, not a restriction. The job to be done is the reliable signal;
titles vary by region and account team.

> **Scope note.** This page is about fit and intent, not mechanics. For the operational
> detail (prerequisites, steps, flags, coverage limits) open the skill's `SKILL.md` and
> its `references/coverage-matrix.md` where one exists. Where a skill has known limits
> that matter in front of a customer, they are called out here as **Watch for**.

---

## Setup

Credentials, infrastructure, data loading, and tenancy configuration.

### `ts-profile-thoughtspot`

- **Business problem.** Every other skill needs authenticated access to a cluster, and
  hand-managing tokens across several clusters is where most first-run failures come from.
- **Who asks.** Everyone, once. This is the first skill anyone runs.
- **Use when** setting up a new cluster, rotating credentials, or diagnosing why another
  skill cannot authenticate.
- **Watch for** Org-scoped auth. Authenticating against an Org by name can silently fall
  back to the default Org, so confirm which Org a session actually landed in before
  trusting what you see.

### `ts-profile-snowflake`

- **Business problem.** The Snowflake conversion and recipe skills need warehouse access
  that is safe to store and easy to re-test.
- **Who asks.** SE and PS working a Snowflake account. Claude Code only, because Cortex
  Code manages its own connections.
- **Use when** you are about to run anything that touches Snowflake and want the
  credential step done once rather than per session.

### `ts-profile-databricks`

- **Business problem.** Same as above for Databricks, where auth has more variants
  (Service Principal OAuth M2M, PAT, existing CLI profile) and picking wrong wastes a
  demo slot.
- **Who asks.** SE and PS on Databricks accounts.
- **Use when** configuring a workspace for Metric View conversion, or testing whether an
  existing profile still works.

### `ts-profile-tableau`

- **Business problem.** Tableau migrations stall on access to the source. A stored,
  tested profile turns "can you send me the workbook?" into a direct pull.
- **Who asks.** SE and PS running a Tableau displacement.
- **Use when** you have Tableau Server or Cloud access and want to fetch workbooks
  directly rather than working from emailed files.

### `ts-load-source-data`

- **Business problem.** Demos and POCs stall waiting for real data. This provisions
  warehouse tables from a CSV, a Tableau download, or a schema-only manifest, generating
  synthetic rows when there is no real data to use.
- **Who asks.** SE building a POC, PS standing up a test environment.
- **Use when** you have structure but no data, or data but no tables. Snowflake and
  Databricks are supported.

### `ts-setup-sv`

- **Business problem.** The Snowsight runtime needs stored procedures installed before the
  semantic view skills work, and a stale procedure fails in a confusing way.
- **Who asks.** Anyone running skills inside Snowflake Workspaces.
- **Use when** prompted by another skill, or once after `ts-profile-thoughtspot`.

### `ts-setup-tenancy`

- **Business problem.** Multi-tenancy behaviour is hard to reason about in the abstract
  and harder to reproduce in a bug report. This builds a real multi-Org environment on
  demand, in one of four scenarios covering the pre-migration state, the target state, and
  the transition between them.
- **Who asks.** PS and SRE designing a tenancy model, PM reproducing a defect, SE
  rehearsing before touching a customer cluster.
- **Use when** you need somewhere safe to try publishing, aliasing, column security or Org
  migration, or when a bug needs several Orgs to show itself.

### `ts-migrate-orgs`

- **Business problem.** Tenants that grew their own copies of the same Table and Model are
  expensive to maintain and drift apart. This moves their content onto a governed
  published Model and retires the old Org, with the untouched source Org as the rollback.
- **Who asks.** PS and SRE consolidating an embedded or multi-tenant deployment.
- **Use when** repointing a tenant's Answers and Liveboards at published objects, or
  sizing how many tenants a Sets dependency blocks.
- **Watch for** the resumable pipeline. Backup, lift, rename, repoint and cleanup are
  separate stages by design; do not treat a partial run as a failed one.

---

## Conversion

Move semantic models between ThoughtSpot and external platforms.

The shared business problem: a customer's semantics already exist somewhere else.
Rebuilding them by hand is slow, error-prone, and the main reason migrations get
deprioritised. Every conversion skill is one-directional by design, so pick the skill by
which platform is the **source**.

### `ts-convert-from-tableau`

- **Business problem.** Tableau displacement is the most common competitive motion, and
  manual rebuilds of calculated fields are where the effort estimate balloons.
- **Who asks.** SE in a competitive cycle, PS delivering the migration.
- **Use when** you have a `.twb` or `.twbx` and want Table and Model TML, optionally with
  dashboards approximated as Liveboards.
- **Watch for** table calculations and row-offset logic, which do not all translate. Read
  the coverage matrix before you quote a percentage to a customer.

### `ts-convert-from-powerbi`

- **Business problem.** Power BI accounts carry heavy DAX investment, and "we would have
  to rewrite every measure" is a real objection.
- **Who asks.** SE in a competitive cycle, PS delivering the migration.
- **Use when** you have a `.pbip` project (TMDL semantic model plus PBIR report) and want
  Models, Answers and tabbed Liveboards.
- **Watch for** time intelligence, which is rebuilt using parameters rather than mapped
  one-to-one, and is worth walking through explicitly with the customer.

### `ts-convert-from-looker`

- **Business problem.** LookML is a genuine semantic layer, so a Looker migration is a
  semantic-layer-to-semantic-layer move rather than a dashboard port.
- **Who asks.** SE and PS on Looker displacements.
- **Use when** you have a LookML project and want Table and Model TML per explore,
  optionally with dashboards converted.

### `ts-convert-from-qlik`

- **Business problem.** Qlik apps hide their logic in master measures and Set Analysis,
  which is invisible until someone tries to rebuild it.
- **Who asks.** SE and PS on Qlik displacements.
- **Use when** you have an offline `.qvf` or exported Qlik Engine artifacts.
- **Watch for** Set Analysis and variables, which are flagged for review rather than
  silently translated.

### `ts-convert-from-sisense`

- **Business problem.** Sisense dashboards encode logic in JAQL, and there is no clean
  export path, so the work usually starts from a captured bundle.
- **Who asks.** SE and PS on Sisense displacements.
- **Use when** you already have a captured offline bundle JSON on disk. This is not a live
  Sisense fetch.

### `ts-convert-from-snowflake-sv`

- **Business problem.** A customer standardised on Snowflake's semantic layer should not
  have to choose between it and ThoughtSpot. This makes an existing Semantic View available
  to Spotter and search.
- **Who asks.** SE and PM on Snowflake-aligned accounts, and anyone handling "we already
  built our metrics in Snowflake".
- **Use when** Snowflake is the source and you want a ThoughtSpot Model, from one view or
  by merging several.

### `ts-convert-to-snowflake-sv`

- **Business problem.** The reverse direction, and the answer to "does ThoughtSpot lock our
  semantics in?" Model definitions become a Semantic View that Cortex Analyst can use.
- **Who asks.** SE answering an interoperability objection, PM on partner alignment.
- **Use when** ThoughtSpot is the source and you want `CREATE SEMANTIC VIEW` DDL, a `.sql`
  file, or an update to an existing view.

### `ts-convert-from-databricks-mv`

- **Business problem.** Same interoperability story as Snowflake, for Unity Catalog Metric
  Views.
- **Who asks.** SE and PM on Databricks-aligned accounts.
- **Use when** Databricks is the source and you want a ThoughtSpot Model, with dimensions
  becoming attributes and measures becoming measures or formulas.

### `ts-convert-to-databricks-mv`

- **Business problem.** Publishing ThoughtSpot semantics into Unity Catalog so Databricks
  AI/BI can use the same definitions.
- **Who asks.** SE answering an interoperability objection, PS on a joint architecture.
- **Use when** ThoughtSpot is the source and you want `CREATE VIEW WITH METRICS` DDL,
  either v0.1 single-source or v1.1 multi-source.

---

## Semantic Authoring

Build, optimise, and prepare Models for production.

### `ts-object-model-coach`

- **Business problem.** "Spotter gave a wrong or confusing answer" is usually a modelling
  problem, not a model-quality problem, and the fix is unglamorous: descriptions,
  synonyms, AI context, reference questions. This finds and drafts them, grounded in how
  users actually phrase things.
- **Who asks.** CSM and CSA on adoption and health conversations, SE before a demo.
- **Use when** natural language results are inconsistent, or before putting a Model in
  front of business users for the first time.
- **Watch for** the Coach Spotter Instructions field, which has a hard 3000-character
  limit, so the guidance has to be budgeted rather than exhaustive.

### `ts-object-model-erd`

- **Business problem.** Nobody can review a model they cannot see, and asking a customer's
  data team to log in to review joins adds a week.
- **Who asks.** SE in a design review, CSA onboarding an unfamiliar environment, PS
  producing a hand-over artefact.
- **Use when** you want a self-contained HTML diagram of tables, joins, columns, findings
  and row-level security that opens in any browser without a ThoughtSpot login.

### `ts-object-model-aggregates`

- **Business problem.** Slow Liveboards are an adoption killer, and choosing which
  aggregate to build is guesswork without knowing which query shapes actually repeat.
- **Who asks.** SRE and CSA on performance escalations, SE on a scale POC.
- **Use when** you want aggregate Models recommended from real usage, profiled for
  compression, and wired up for 26.6 aggregate-aware routing.
- **Watch for** open items still unverified on this skill. Check its `SKILL.md` status
  before relying on it in front of a customer.

### `ts-object-model-alias`

- **Business problem.** One governed Model often has to look different to different
  audiences, whether that is a language or a tenant's own vocabulary. Copying the Model per
  audience destroys the governance benefit.
- **Who asks.** PS on multi-tenant or international deployments.
- **Use when** you need column renaming by locale, by tenant, or a combined matrix of both.

### `ts-object-answer-promote`

- **Business problem.** Useful logic gets stranded in one person's saved Answer, so
  everyone else reinvents it or gets a different number.
- **Who asks.** CSA and CSM on adoption work, SE tidying a POC.
- **Use when** a formula or parameter in an Answer deserves to be available to everyone
  searching the Model.

---

## Platform and Governance

Publish, secure, audit, and maintain across Orgs.

### `ts-publish-orgs`

- **Business problem.** Serving many tenants by copying content into each Org means every
  fix has to be made many times. Publishing shares one governed definition instead.
- **Who asks.** PS and SRE on multi-tenant and embedded deployments.
- **Use when** pushing Tables, Models, Answers and Liveboards from the Primary Org to
  target Orgs, including the template variables and parameterisation publishing requires.

### `ts-security-columns`

- **Business problem.** Hiding a sensitive column sounds simple and is not: there are two
  mechanisms with different scopes and failure modes, and picking wrong leaves data
  reachable.
- **Who asks.** PS and SRE on a security review, SE answering a security questionnaire.
- **Use when** restricting columns for a group, tenant or audience, or deciding which
  mechanism applies to a published object.
- **Watch for** two things that surprise people. Column Security Rules are Org-scoped and
  do not travel with publication, and an object-level deny removes search but leaves
  column grants reachable by direct link, so revoke at the column level.

### `ts-audit`

- **Business problem.** Inheriting an unfamiliar environment, or being asked "is this
  healthy?", with no systematic way to answer.
- **Who asks.** CSA and PS on onboarding or take-over, SRE on escalations, CSM preparing a
  business review.
- **Use when** you want a read-only scan across AI Readiness, Data Modeling, Human
  Readiness, Performance and Security, with per-model scorecards and prioritised findings
  that route to the skill that fixes each one.

### `ts-dependency-manager`

- **Business problem.** "Can we drop this column?" is unanswerable at a glance, so nobody
  does it, and models accumulate dead weight until something breaks in production.
- **Who asks.** CSA and PS on cleanup and consolidation work.
- **Use when** auditing what depends on a column or object, or removing or repointing one
  across Models, Views, Answers and Liveboards, with a risk-rated report, TML backup and
  rollback.
- **Watch for** column aliases. Matching on base names alone misses a meaningful share of
  dependencies, so alias-aware matching is the point of the skill.

### `ts-variable-timezone`

- **Business problem.** Users in different timezones reading the same Liveboard and seeing
  different days is a credibility problem that looks like a data problem.
- **Who asks.** CSA and SRE on support escalations.
- **Use when** searching, setting or removing `ts_user_timezone` at Org or user level.
- **Watch for** release gating: Beta in 26.5, EA in 26.6.

---

## Query

Query and explore data through ThoughtSpot's semantic layer.

### `ts-object-model-agentql-query`

- **Business problem.** Two different needs, one skill. Getting data out of a Model
  programmatically, and seeing exactly what SQL ThoughtSpot generates for a given question
  when someone disputes a number.
- **Who asks.** SE proving out generated SQL, PM building accuracy or regression test sets,
  anyone debugging a suspect answer.
- **Use when** you want to turn a question into AgentQL, validate it to warehouse SQL,
  execute it, and read the rows. New to it? Start with the architecture reference.

---

## Recipes

Pre-built analytical capabilities for ThoughtSpot.

The shared business problem: a specific analytical need comes up in account after account,
and each SE solves it from scratch. A recipe is the solved version, deployable in minutes.

### `ts-recipe-formula-business-days-snowflake`

- **Business problem.** ThoughtSpot's built-in date differences count calendar days, but
  SLA, ticket age and fulfilment questions are almost always weekday-only.
- **Who asks.** SE and CSA on service, support and operations use cases.
- **Use when** someone needs business-day counts or weekday-only elapsed time. Deploys
  three Snowflake UDFs and shows the ThoughtSpot formula syntax to call them.

### `ts-recipe-formula-hms-display-snowflake`

- **Business problem.** Durations stored as integer seconds or minutes display as
  meaningless large numbers, which undermines trust in an otherwise correct dashboard.
- **Who asks.** SE and CSA on contact centre, service and operations use cases.
- **Use when** call duration, handle time or ticket age should read as `HH:MM:SS`,
  `DD:HH:MM:SS`, `HH:MM` or `DD:HH:MM`. Deploys four Snowflake UDFs plus the formula syntax.

---

## Keeping this page honest

This page is hand-maintained and is not currently validated against the skills it
describes, so it can drift. [BL-188](backlog.md) tracks moving `use-when` and `personas`
into `SKILL.md` frontmatter and generating this page from them, which is the durable fix.

Until then: if you add or materially change a skill, update the entry here in the same PR.
If you spot an entry that no longer matches the skill, correcting it is a genuinely useful
first contribution.
