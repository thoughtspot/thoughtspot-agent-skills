---
name: ts-setup-tenancy
description: Stand up a reproducible multi-tenancy test environment on a ThoughtSpot cluster — Orgs, per-Org groups and users, warehouse tables, and optionally a published Model with per-tenant aliases and column security. Use when you need an environment to try publishing, aliasing, column security or the Org migration against, or to reproduce a bug that needs several Orgs. Builds a chosen scenario (topology / per-org / published / mixed), verifies it, and can tear it down.
---

# ThoughtSpot: Set Up a Multi-Tenancy Test Environment

Trying the single-model multi-tenancy pattern needs a cluster with several Orgs, per-Org
groups, users in the right groups, warehouse tables, and — depending on what you are
testing — either tenant-owned objects or a published one. Building that by hand is slow,
and the part people get wrong is not the slow part.

This skill builds one of four **scenarios**, verifies it, and can remove it again.

**This is scaffolding, not a deployment tool.** The environments are opinionated,
complete and disposable. Onboarding a real client is a different job — see
[Production is different](#production-is-different).

Ask one question at a time for **dependent** decisions. Batch **independent** questions
into a single prompt to cut round-trips.

---

## References

| File | Purpose |
|---|---|
| [references/scenarios.md](references/scenarios.md) | What each scenario contains and which feature it lets you exercise |
| [tools/ts-cli/README.md](../../../tools/ts-cli/README.md) (`ts tenancy`) | Flag reference for the topology commands |
| [tools/fixtures/tenancy-reference.yaml](../../../tools/fixtures/tenancy-reference.yaml) | The captured reference topology |
| [docs/multi-tenancy-platform-plan.md](../../../docs/multi-tenancy-platform-plan.md) | Programme context — what the pattern is and why |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth and profiles |

Hands off to: [`/ts-publish-orgs`](../ts-publish-orgs/SKILL.md),
[`/ts-object-model-alias`](../ts-object-model-alias/SKILL.md),
[`/ts-security-columns`](../ts-security-columns/SKILL.md).

---

## Prerequisites

- `ts` CLI on PATH, version **0.111.0+**
- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- **Orgs enabled**, and you are signed in to the **Primary Org** with `ADMINISTRATION`
- A warehouse connection is needed for every scenario except `topology`. The skill can
  create one, or reuse one you name
- Optional, for `published`: Orgs Publishing is **Early Access** — confirm it is enabled
- Optional, for column security via CSR: **Beta, 10.12+, feature-flagged off by default**
- **A cluster you are willing to have objects created on.** Prefer a dedicated test
  instance. Everything is marker-stamped and removable, but this creates real Orgs

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-setup-tenancy** — stand up a reproducible multi-tenancy test environment.

Steps:
  1.  Authenticate ..................................... auto
  2.  Confirm the target cluster ....................... you confirm (checkpoint)
  3.  Choose the scenario .............................. you choose
  4.  Choose the topology (Orgs / groups / users) ...... you choose
  5.  Plan the build .................................... auto
  6.  Review the plan .................................. you confirm (checkpoint)
  7.  Build the topology ............................... auto
  8.  Load warehouse tables + connection ............... auto
  9.  Build the objects for the scenario ............... auto
 10.  Verify and report what to look at ................ auto

Confirmation required: Steps 2, 3, 4, and the checkpoint in Step 6
Auto-executed: Steps 1, 5, 7, 8, 9, 10

Scenarios:
  topology   — Orgs, groups, users only
  per-org    — each tenant Org owns its objects, nothing published   (PRE-migration)
  published  — one Primary Model published out, aliased, secured     (POST-migration)
  mixed      — some tenants each way                                 (mid-migration)

Everything created is marker-stamped and removable with `ts tenancy teardown`.

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Step 1 — Authenticate

```bash
ts auth whoami --profile "{profile_name}"
```

Confirm `current_org` is **Primary** and `privileges` includes `ADMINISTRATION`. Stop if
either is wrong: Orgs cannot be created from a tenant Org.

**Do not read `orgs` or `org_privileges` as the user's reach** — both are a *per-token*
view. A Primary-scoped token reports `orgs: [{id: 0, name: Primary}]` even for a user who
administers four Orgs.

---

## Step 2 — Confirm the Target Cluster

**Checkpoint.** This step exists because the skill creates real Orgs and users, and the
most expensive mistake available is pointing it at the wrong instance.

```
About to build a test environment on:

  Profile:  {profile_name}
  URL:      {cluster_url}
  Orgs:     {existing org names}

This CREATES Orgs, groups and users. Use a cluster you are willing to have
objects created on — ideally a dedicated test instance.

Is this the right cluster? (Y / N):
```

Do not proceed on anything other than an explicit yes.

---

## Step 3 — Choose the Scenario

Full detail, and which feature each one lets you exercise:
[references/scenarios.md](references/scenarios.md).

```
What do you want to be able to test?

  1  topology   Orgs, per-Org groups, users. Nothing else.
                -> group resolution, org-scoped auth

  2  per-org    Each tenant Org owns its own Tables + Model. Nothing published.
                -> `ts migrate` (this is its INPUT), CSR on an Org's own object

  3  published  One Model in Primary, published to every tenant, aliased, secured.
                -> publishing, aliasing, column security

  4  mixed      Some tenants own their objects, some read the published one.
                -> the transition itself — where the untested interactions are

Enter 1-4:
```

Two things worth saying when they choose:

**If they pick `published` and mention migration** — the migration routine consumes the
*pre*-migration state, so `per-org` or `mixed` is what they want. `published` is the
target, not the input.

**If they are chasing a bug that will not reproduce** — suggest `mixed`. A cluster is
half-migrated for the whole duration of a real migration, and most of the remaining risk
in the programme lives there rather than at either endpoint.

Save as `{scenario}`.

---

## Step 4 — Choose the Topology

```
Topology:

  1  Reference  — the captured environment the platform was verified against
                  (ORG1/2/3, Analyst + Consumer in Primary, Demo Retail Group per tenant,
                   guest1-4 and rlsgroup1-5user)
  2  Minimal    — Primary + one tenant Org, two groups, two users
  3  My own     — a spec file you already have

Enter 1-3:
```

**Reference** uses `tools/fixtures/tenancy-reference.yaml`. It is *captured* from a
working cluster rather than hand-written, so it reproduces the environment every
verification round in this programme was run against.

**Minimal** is faster and enough for the CSR/CLS decision, but cannot reproduce the RLS or
multi-tenant fan-out cases.

For any topology, name the discriminating pair explicitly, because a test that cannot tell
two users apart proves nothing:

```
Discriminating users for {scenario}:
  {user_a} is in {group_a} — should SEE the secured column
  {user_b} is in {group_b} — should NOT

In the tenant Orgs both users are in the same group, so they do NOT discriminate
there. Tenant-side checks are "is it visible at all", not "who sees it".
```

Save as `{spec_path}`.

---

## Step 5 — Plan the Build

```bash
ts tenancy apply --spec "{spec_path}" --dry-run --profile "{profile_name}"
```

For scenarios beyond `topology`, also determine:

- **Connection** — ask whether to create one or name an existing one. Never silently
  reuse a connection or trial-and-error an existing one; a dedicated connection for a
  test environment is almost always right
- **Warehouse tables** — `/ts-load-source-data` provisions them. A scenario needs one
  small fact-like table with a column worth securing (a price or amount) and a column
  worth aliasing
- **Which tenants get which shape**, for `mixed`

---

## Step 6 — Review the Plan

**Checkpoint** — the last point before anything is created:

```
Scenario:    {scenario}
Cluster:     {profile_name} ({cluster_url})
Topology:    {n} Org(s), {n} group(s), {n} user(s)
Warehouse:   {connection}, {n} table(s)
Objects:     {what will be created, per Org}
Published:   {which Orgs, or "none"}
Marker:      {marker}   (teardown keys off this)

Proceed? (Y / N):
```

---

## Step 7 — Build the Topology

```bash
ts tenancy apply --spec "{spec_path}" --profile "{profile_name}"
ts tenancy verify --spec "{spec_path}" --profile "{profile_name}"
```

**Passwords are never taken in conversation.** If the users need to sign in — which they
do for any data-plane check — tell the operator to export the variable in their own
terminal, then pass its name:

```bash
export TS_TENANCY_PASSWORD='...'        # in YOUR terminal, never here
ts tenancy apply --spec "{spec_path}" --password-env TS_TENANCY_PASSWORD \
  --profile "{profile_name}"
```

Only `LOCAL_USER` accounts take one; federated accounts authenticate against the IdP.

Stop if `verify` is not complete. Every later step assumes the principals exist.

---

## Step 8 — Warehouse Tables and Connection

Skip entirely for `topology`.

Create or confirm the connection, then load the tables — `/ts-load-source-data` owns this
and infers a schema, generating synthetic rows where a source is schema-only.

The table needs, at minimum, a column worth **securing** (a price or amount) and a column
worth **aliasing** (a business-named attribute). Without both, `published` cannot
demonstrate what it exists to demonstrate.

---

## Step 9 — Build the Objects

### `topology`
Nothing further.

### `per-org` — the pre-migration state

For **each tenant Org**, create Tables and a Model **owned by that Org**. Nothing is
published, and Primary holds no shared object.

This is deliberately the object-count explosion the pattern exists to remove: N tenants ×
M objects. Say so when reporting, because it is the thing migration is measured against.

### `published` — the post-migration target

In **Primary**: create the Tables and Model, then hand off to `/ts-publish-orgs`.
Publishing needs the Tables parameterized first — `ts publish push` fails closed
otherwise, so variables are part of this step rather than an afterthought.

Then per-tenant aliases (`/ts-object-model-alias`) and column security
(`/ts-security-columns`).

**Column security is per (Org, object), not per object.** The same published table wants
CSR for Primary's users and CLS for a tenant's, simultaneously — that is the whole point
of the scenario, so configure both rather than picking one.

### `mixed`

Both of the above, split across tenants. Record which tenant got which shape and report
it — a `mixed` environment is useless if nobody remembers its shape.

---

## Step 10 — Verify and Report

```bash
ts tenancy verify --spec "{spec_path}" --profile "{profile_name}"
ts publish status {guids} --profile "{profile_name}"          # published / mixed
ts security column-rules get {table} --org "{org}" --profile "{profile_name}"
ts share status {guid} --columns --org "{org}" --profile "{profile_name}"
```

Then report **what to go and look at**, which is the part that makes the environment
usable rather than merely present:

```
Environment ready — scenario: {scenario}

  Orgs:      {orgs}
  Sign in as: {user_a} / {user_b}
  Marker:    {marker}

To see column security working:
  - {user_a} in Primary  -> SHOULD see {column}
  - {user_b} in Primary  -> should NOT
  - either user in {tenant_org} -> {expected}

Switch the Org picker deliberately. On a multi-Org cluster "I see nothing" is the
expected result almost everywhere, so an observation without the Org named proves
nothing.

Teardown:
  ts tenancy teardown --spec {spec_path} --org {orgs} --dry-run -p {profile}
```

That Org-picker warning is not boilerplate. A verification round in this programme was
derailed by a "user sees nothing" result taken from the wrong Org, which read as a real
finding and was the opposite of the truth.

---

## Tearing Down

```bash
ts tenancy teardown --spec "{spec_path}" --org {org} --dry-run --profile "{profile_name}"
ts tenancy teardown --spec "{spec_path}" --org {org} --yes --profile "{profile_name}"
```

Three independent things must line up before anything is deleted: the object carries the
spec's **marker**, its **Org was named** with `--org`, and **`--yes`** was passed. A user
who also belongs to an unnamed Org is refused, because deleting them would strip them from
it. Primary is never deleted.

Refusals are printed, not silent — they are the rail working. Always `--dry-run` first.

**Teardown covers the topology.** Objects created in Step 8/9 (tables, models, published
state) are removed by their own tools: `ts publish rollback`, then delete the Models and
Tables. Report what remains rather than implying the cluster is clean.

---

## Production is different

Do not use a scenario to onboard a real client. The postures are opposite:

| | Test environment (here) | Production onboarding |
|---|---|---|
| Completeness | Opinionated and complete — the point is one command | **Partial** — create the Org, let users arrive via SSO/SCIM |
| Teardown | Expected | Catastrophic |
| Users | `LOCAL_USER` with a shared password | Federated; no password at all |
| Decisions | Made by the scenario | Every one the operator's |

`ts tenancy apply` is the piece both share, and it is production-safe on its own —
per-user `account_type`, `{TENANT}` templating, and the three-gate teardown. The guided
production flow is **BL-143**.

---

## Error Handling

| Symptom | Action |
|---|---|
| `ts tenancy apply` reports spec problems | Read them all — they are reported together because topology mistakes are systematic. The commonest is a user joining a group not declared for that Org |
| `Invalid group identifiers: {name}` | A group from another Org. Groups are per-Org; `ts groups search --org {org}` shows what actually exists there |
| `verify` incomplete after `apply` | Re-run `apply` — it is idempotent. If it stays incomplete, an Org could not be read; check privileges **in that Org**, not in Primary |
| `ts publish push` fails "not parameterized" | Publishing needs the Tables parameterized first. `/ts-publish-orgs` does this; do not use `--skip-validation` |
| `cohort column ... is defined on the Model` | A Set was added to a Model being published. Sets cannot live on a published Model — delete the cohort column |
| CSR returns `403` / `10023` disabled-form | The feature is flagged off. Beta, 10.12+. Use CLS, or ask ThoughtSpot to enable it |
| CSR returns `10038` `FORBIDDEN` in a tenant Org | Expected on a published object: a tenant cannot define CSR on one published into it. Use CLS for that Org |
| Users cannot sign in | They were created without a password. Re-run with `--password-env`, or set passwords in the ThoughtSpot UI |
| Teardown refuses everything | Working as designed — check the marker matches and that you named `--org` |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-07-27 | Initial release |
