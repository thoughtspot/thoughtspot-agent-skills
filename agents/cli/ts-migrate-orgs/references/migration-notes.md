# Migration notes — the findings behind the step order

Every rule in `SKILL.md` costs something to learn. This records what, so nobody
"simplifies" the order back to a version that was already tried.

All findings are live-verified on `nebula-damian-alias` unless marked otherwise. Full
accounts under `docs/superpowers/verification/`.

---

## Topology: one permanent Org per tenant, not a shared staging Org

A temporary staging Org was designed and rejected. It looks appealing — teardown becomes
"delete the Org" — but the appeal is an illusion:

- The clean Org **is already disposable**, because no users move into it until the final
  step. The staging Org adds a disposable Org to a design that already has one.
- Deleting an Org only works if the content is elsewhere first, so staging forces a
  **second lift of the largest object set** (hundreds of Answers and Liveboards) to avoid
  deleting the smallest (tens of Tables and Models).
- Org deletion is **unconditional**. Surgical cleanup refuses when a Model still has
  dependents, which is the missed-repoint check. Staging trades that check away.

## The Table dedupe key includes the connection

Tables dedupe on **(connection + db + schema + db_table)**, not logical name. Proven in
both directions: a same-connection, same-binding import collides
(`Cannot create a new table ... Existing Table GUID: …`); a different-connection, same-binding
import succeeds, even into an Org that already holds a *published* Table on that binding.

This matters most for the case that looked fatal: an RLS-segmented fleet where every
tenant references **one** physical table. Each tenant reaches it through its own
connection, so no collision.

Whether a *published* Table participates in the dedupe is **moot by construction** — a
tenant Org can never hold Primary's connection, so the colliding case is unreachable.

## Connection names are per-Org

Verified by rename, because `connection/create` validates warehouse connectivity even with
`validate: false` and so cannot be probed with a placeholder credential.

Two Orgs may hold the same connection name simultaneously. That is what lets the clean Org
carry the source's name and the lifted TML resolve unchanged.

**Publishing does not grant a usable connection.** A fresh Org with a published Table still
lists zero connections and still refuses a Table import.

## Connection deletion does not cascade

`deleteConnection`: *"If a connection has dependent objects, make sure you remove its
associations before the delete operation."* Spec-sourced, deliberately not live-tested —
the only connections on the test cluster carry real fixture Tables, and a cascade that
succeeded would destroy an Org to learn what the spec already states.

Hence Models → Tables → connection. The order is correct whichever way the platform
actually behaves.

## Reference resolution is fqn-then-name

Visible in a failure message:

```
Error: Tables do not exist. - SPIKE_T4
Warning: No table with fqn d3a688f2-… found for table_id SPIKE_T4
```

The importer tries the `fqn` (a source-Org GUID, dead in the target), fails, and falls
back to matching by **name**. Two consequences: intra-batch remapping works as the design
assumes, and **names must be unique in the target Org**.

## Renaming a column alias propagates to dependents

Editing only `columns[].name` and importing with `--no-create-new` is an **in-place column
update** (`diff: {columns_updated: 1}`), not a drop-and-add. A dependent Answer's stored
formula auto-updated with the Answer never being touched, and reverted symmetrically.
Dependents reference the column by `column_id`, not the name string.

This is the mechanism the whole architecture rests on — and the reason a wrong mapping is
dangerous rather than merely wrong.

## RLS carries; CSR does not

**RLS on a published object enforces for a real non-admin user in the tenant Org.**
Verified against a no-RLS control table, so "0 rows" could not be confused with "no
access".

**CSR does not travel with publication.** A rule defined in the owning Org is enforced
there, but a tenant Org the object is published to sees the restricted column in full — no
error, no warning.

The structural difference explains both: RLS lives **inside** the Table TML as part of the
object definition; a Column Security Rule is a **separate, Org-scoped security object**
attached to it. Publication makes the same GUID visible rather than copying, so what is
carried *in* the definition comes along and what hangs off it Org-scoped does not.

**Test as a real tenant user.** An admin bypasses RLS, and an owning-Org check passes even
when tenant-side behaviour is wrong — exactly how the CSR trap stayed hidden.

## BL-144 — a malformed RLS rule imports `OK` and wipes the existing one

| `expr` | Import | Rule afterwards |
|---|---|---|
| `[T_1::PROD_NM] = ts_username` | `OK` | present |
| `[T_1::PROD_NM] = ts_orgid` | `ERROR` — unknown keyword | unchanged |
| `ts_orgid = 0` | **`OK`** | **GONE** |

Row 2 is the control: the same unknown keyword errors loudly *with* a column reference and
passes silently *without* one. The rule is discarded before keyword validation.

Silent in the direction that removes security. `apply` therefore re-reads and asserts after
any write to a table that carried RLS — `OK` is never sufficient evidence.

## BL-145 — `ts_orgid` is not an RLS keyword

`Search did not find "ts_orgid" in your data or metadata`. The documented system variables
are `ts_username` and `ts_groups`; the Org-aware route is `ts_var(varName)` against an
**ABAC formula variable** with per-Org values.

ABAC is not enabled on the test cluster (the only variable class there is `TABLE_MAPPING`,
which is publishing parameterization, not ABAC) — but `ts_vars` **is** confirmed working in
the production environment, so this is a test-environment gap, not a platform limitation.

## Aliases: per wave, never per tenant

Aliases live on the Primary Org's Model with **no partial update** until delta load
(est. 26.10), so every append re-imports the whole document.

| | 500 Orgs | 1000 Orgs | 2000 Orgs |
|---|---|---|---|
| 30 cols | 3.0 MB | 6.0 MB | 12.0 MB |
| 50 cols | 5.0 MB | 10.0 MB | 20.0 MB ⚠ |
| 80 cols | 8.0 MB | 16.0 MB | **32.0 MB ✗** |

Single-locale, so roughly 3× the headroom the alias design's table implies. **Size is not
the near-term ceiling** — the O(N²) time cost is. Past 5 MB imports go async at 10–15 min;
per-tenant that is ~100 hours for the back half of a 1000-tenant fleet, versus ~5 hours in
waves of 50.

The catastrophic failure is a partial export feeding `build --merge`, which silently drops
already-migrated tenants' aliases.

## Open

- **Org-aware RLS on the test cluster** — needs ABAC enabled (BL-145). Parked: known to
  work in production.
- **A full-size batch binding content to newly-created Models** — the mechanism is proven,
  the scale is not. Re-measure on the first real tenant.
