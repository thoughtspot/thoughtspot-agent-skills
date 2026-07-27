# Scenarios — what each one builds, and which feature it lets you exercise

Reference for [`../SKILL.md`](../SKILL.md) Step 3.

A scenario is not a convenience setting. The multi-tenancy programme has a **before** state
and an **after** state, and several of its components can only be tested against one or the
other:

- `ts migrate` consumes the **before** state. You cannot test a migration without one.
- Publishing, aliasing and column security demonstrate the **after** state.
- The bugs nobody has hit yet live in the **middle**, where a cluster is half migrated.

---

## The four scenarios

| Scenario | Orgs / groups / users | Tables + Models | Published? | Aliases | Column security |
|---|---|---|---|---|---|
| `topology` | ✅ | — | — | — | — |
| `per-org` | ✅ | one set **per tenant Org**, Org-owned | no | — | — |
| `published` | ✅ | one set in **Primary** | yes, to every tenant Org | per-tenant | yes |
| `mixed` | ✅ | both shapes | some tenants only | on the published tenants | on the published tenants |

---

## `topology` — the base

Orgs, per-Org groups, users and memberships. Nothing else.

**Use it when** you are testing something that only needs principals to exist —
`ts share`'s group resolution, org-scoped auth, or the per-Org group behaviour itself.

**It is also the substrate** every other scenario builds on, so a failure here is worth
fixing before looking at anything else. `ts tenancy apply` does the whole of it.

---

## `per-org` — the PRE-migration state

Each tenant Org owns its own Tables and Model. Nothing is published; Primary has no
shared object. This is what a client looks like **today**, before adopting the pattern.

**Use it for:**

- `ts migrate audit` — this is its input. The column-usage map, the `GAP` / `GAP_BLOCKER`
  split and the readiness verdict are all computed against tenant-owned Models.
- CSR in a tenant Org on an object that Org **owns** — live-verified to work, and the
  distinction that matters, because CSR is refused on an object published *into* an Org
  (`10038 FORBIDDEN`). Only this scenario gives you the working case.
- Anything about object-count explosion: N tenants × M objects is the problem the pattern
  exists to solve, and it is only visible here.

**What it deliberately does NOT have:** a published object. If a test needs one, it needs
`published` or `mixed`.

---

## `published` — the POST-migration target

One set of Tables and one Model in Primary, parameterized and published to every tenant
Org, with per-tenant column aliases and column security applied.

**Use it for:**

- `ts-publish-orgs` end to end, including the variable/parameterization work publishing
  requires.
- `ts-object-model-alias` — per-tenant display names over one shared Model.
- `ts-security-columns` — and specifically the case the design turns on: the same
  published table needs **CSR for Primary's users and CLS for a tenant's**, at the same
  time. This scenario is the only one where both rows exist simultaneously.
- Verifying the Liveboard-filter difference: under CSR a filter on a secured column stays
  interactive, under CLS it locks.

**Publishing needs parameterization first.** `ts publish push` fails closed on an
unparameterized object, so the scenario creates the template variables as part of the
build rather than as an afterthought.

---

## `mixed` — the state nobody has tested

Some tenant Orgs still own their objects; others read a published one. A cluster is in
this state for the entire duration of a real migration, which is usually weeks.

**Use it for the interactions that only exist here:**

| What to look at | Why it is only visible in `mixed` |
|---|---|
| `CSR_BLOCKED` | A table is published to *some* Orgs. CSR is legitimate for Primary's users and refused for the tenants — on the same object, in the same run |
| Alias propagation | A per-tenant alias on the published Model, alongside a migrated tenant's own naming. Base-name matching misses roughly 30% of dependents; this is where that shows |
| Cohort columns | Sets cannot live on a published Model. A tenant mid-migration may still have them, and the first migrated Set makes the Model unpublishable for everyone |
| Partial-failure recovery | `ts security column-rules apply` is one call per (Org, table) with per-call rollback, so a mid-loop failure leaves earlier tenants applied. Only a heterogeneous cluster reproduces that honestly |

**This is the scenario to reach for when a bug does not reproduce** in `per-org` or
`published`. Most of the platform's remaining risk is in the transition, not the endpoints.

---

## Choosing

```
Testing ts migrate, or CSR on an Org's own object?      -> per-org
Testing publishing, aliasing, or column security?       -> published
Testing the transition, or chasing a bug that will
  not reproduce at either endpoint?                     -> mixed
Only need principals to exist?                          -> topology
```

When unsure, `published` is the most generally useful: it is the state the pattern is
aiming at, and every shipped skill in the programme has something to demonstrate on it.

---

## What none of them are

**These are test environments, not production deployments.** They are opinionated,
complete, and disposable — the point is that one command produces something you can
immediately poke at, and another command removes it.

Onboarding a real client is a different job with a different posture: partial by nature
(the Org is created, users arrive via SSO), never torn down, and every decision the
operator's rather than the scenario's. That is tracked as **BL-143**, and
`ts tenancy apply` is the piece both share. Do not reach for a scenario to onboard a real
tenant.
