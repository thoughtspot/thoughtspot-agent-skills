---
name: ts-object-set-manager
description: Inventory reusable Sets (cohorts) on ThoughtSpot Models — how many each Model has, what depends on each, which are delete candidates or could become answer-level, and where every grant on a Set came from. Use when cleaning up Sets, auditing who can see a Set, finding unused Sets, or deciding which Sets should stay reusable. v1 is report only — it changes nothing.
---

# ThoughtSpot: Set Manager

Report on every reusable Set across chosen Models, an Org, or the cluster. **v1 is
read-only.** Deleting, converting to answer-level and revoking grants are v2 (BL-327).

## References

| File | Purpose |
|---|---|
| [../../shared/schemas/thoughtspot-sets-tml.md](../../shared/schemas/thoughtspot-sets-tml.md) | Set TML — reusable vs answer-level |
| [../../../docs/superpowers/specs/2026-10-01-ts-object-set-manager-design.md](../../../docs/superpowers/specs/2026-10-01-ts-object-set-manager-design.md) | Design: findings F1–F12, classes (§4), provenance (§5), live checks (Appendix A) |
| [references/open-items.md](references/open-items.md) | Open items and live verification |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | Auth |
| [../../../tools/ts-cli/README.md](../../../tools/ts-cli/README.md) | `ts sets` — every flag, output key and note kind |

## Step 0 — Overview

Display, then wait for Y:

    ts-object-set-manager — inventory reusable Sets. Read-only: changes nothing.

      1. Authenticate ............................ auto
      2. Choose scope (Models / Org / Cluster) ... you choose
      3. Dry-run: what's in scope ................ you confirm
      4. Inventory ............................... auto
      5. Report (HTML + Markdown) ................ auto
      6. Walk through results .................... you review

    Ready? [Y / N]

## Step 1 — Authenticate

Read `~/.claude/thoughtspot-profiles.json`; if several profiles, ask which. Run
`ts auth whoami --profile "{profile}"`. On failure send the user to `/ts-profile-thoughtspot`.

## Step 2 — Scope

Ask once, accepting any combination:

    Which Models?
      M  By GUID or exact name (comma-separated)
      C  Name contains (e.g. DUNDER)
      O  Every Model in an Org
      X  Whole cluster (every Org)

Map to flags: M → `--model` (repeat per value), C → `--model-contains`, O → `--org`,
X → `--all-orgs`. `--all-orgs` scans every ACTIVE Org and **ignores `--org`** — if the user
picks both, say so and drop the Org. Connection scope is not available yet (BL-328) — say
so if asked.

## Step 3 — Dry run

    ts sets inventory {flags} --dry-run --profile "{profile}"

Show the Models matched per Org (stdout `orgs[].models`) and the estimate from stderr.
**Always** list the matches for a contains-selector, and **always** confirm for Org or
Cluster scope. Read out any `notes[]` (`org_skipped` — an Org that is not ACTIVE and will not
be scanned). On exit 1 with "No Model matched", show the selectors and return to Step 2.

## Step 4 — Inventory

    ts sets inventory {flags} --profile "{profile}" \
      -o ~/Dev/audit-runs/{profile}-sets-{YYYY-MM-DD}/sets-inventory.json > /dev/null

Progress goes to stderr. Per Model this is one call to an internal cohort listing, then
per Set a dependents lookup, a TML export of each Liveboard dependent, and one grants read.

## Step 5 — Report

    ts sets report ~/Dev/audit-runs/{profile}-sets-{YYYY-MM-DD}/sets-inventory.json \
      -o ~/Dev/audit-runs/{profile}-sets-{YYYY-MM-DD}/

Open `report.html`. `report.md` carries the same content.

## Step 6 — Walk through

Lead with `summary` from the inventory JSON (`models`, `models_incomplete`, `sets`,
`by_class`, `unexplained_grants`, `unknown_grants`), then:

| Class | Meaning | What to do today |
|---|---|---|
| `KEEP_FILTER` | Used as a Liveboard filter | Keep reusable |
| `REVIEW_MANUAL` | Could not classify — `reason` given (failed or hidden dependents, unreadable Liveboard, a dependent of another type such as another Set) | Inspect by hand |
| `KEEP_SHARED` | 2+ objects or 2+ visualizations | Keep reusable |
| `CANDIDATE_ANSWER` / `CANDIDATE_VIZ` | One user (`target` names it) | v2 will offer to move it in |
| `REVIEW_DELETE` | No recorded dependents | Check ad-hoc use; delete via the UI or `/ts-dependency-manager` |

A Set referenced only inside a visualization's formula counts as used.

**Liveboard-filter detection is verified live for both Liveboard shapes**: a Liveboard that
uses the Set as a filter and in a visualization (open item #4), and a Liveboard that uses the
Set *only* as a filter (open item #8). In both, ThoughtSpot lists the Liveboard as a dependent
of the Set, and the Set reads `KEEP_FILTER`. No hand-check for filter-only Liveboards is needed.

When a Set's `dependents_complete` is `false`, its dependents list may be short: the report
shows the count as "unknown" or "≥N". Say that the count is a floor, not a total.

| Provenance | Meaning |
|---|---|
| `DIRECT` | Edit grant — deliberate |
| `REQUIRED` | Owner of content that uses the Set — revoking breaks it |
| `EXPLAINED` | Holds a grant on content that uses the Set (copied at share time) |
| `UNEXPLAINED` | No content explains it — likely left over; review |
| `UNKNOWN` | Could not determine — not offered for review. Grants were unreadable, or the Set's consumers are uncertain (a failed dependents lookup, hidden dependents, a dependent with no author, a dependent of another type) |

Only `UNEXPLAINED` grants go on the review list. For grant changes today, point to `ts share`.

Always read out the **Scan notes** — the top-level `notes[]` (`org_skipped`) and each Org's
`notes[]`. An `org_skipped` note with `reason: "malformed"` (an Org row with no `orgId` or
`status`) makes the totals a floor; `reason: "inactive"` is a scope choice:

| Note kind | Say |
|---|---|
| `discovery_failed`, `unrecognised_row` | That Model is `INCOMPLETE`: its Set count is **unknown, not zero** |
| `dependents_failed` | That Set's dependents could not be read in full |
| `export_unreadable` | A Liveboard using the Set could not be inspected |
| `unrecognised_dependent` | A dependent of a type not inspected (e.g. another Set) |
| `grants_unreadable` | That Set's provenance is `UNKNOWN` |

Say plainly that nothing was changed.

## Known limitations

- **Discovery uses a private, undocumented endpoint** — the per-Model cohort listing
  `GET /callosum/v1/metadata/detail/{model}?type=LOGICAL_TABLE&fetchcohortcolumnsonly=true`
  (Confluence SAGE/4309319694). No public route lists a Model's Sets: Model dependents omit
  them, and a cluster-wide `LOGICAL_COLUMN` search did not finish in 2h45m (spec Appendix A).
  If a build moves the endpoint, every Model reads `INCOMPLETE` with a `discovery_failed` note.
- **`--all-orgs` ignores `--org`.** Cluster scope always means every ACTIVE Org.
- **No connection scope** (BL-328). Scope by Model, Org or cluster.
- Granting **edit** on a Set without access to its Model fails on save (BL-326, parked).
- `REVIEW_DELETE` cannot see unsaved ad-hoc searches.
- Group membership is not expanded: a user explained only via their group reads `UNEXPLAINED`.
- **`KEEP_FILTER` was verified live with an admin profile** (open items #4 and #8: filter +
  viz, and filter only). A non-admin caller was not run: for one, hidden dependents should make
  the Set `REVIEW_MANUAL` (#6), which is unit-tested but not observed live.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-10-02 | Initial release — report-only reusable Set inventory: scope by Model/Org/Cluster, classification, grant provenance |
