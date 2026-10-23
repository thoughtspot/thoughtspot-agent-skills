# RLS join cycles: catch them before query generation does

**Status:** design, awaiting approval · **Date:** 2026-10-23

## Why

A Model can import cleanly and then fail at query time with an unhelpful error
(`Guid Mismatch: guid … name … vs guid … name …`, BACH code 12325) when a table's
row-level-security rule joins back into the Model's own join graph. ThoughtSpot checks
the Model's joins for cycles at import (13123/13124), but it does not look at the joins
an RLS rule uses until a query runs. A real support case (internal ticket, root-caused
by the query-generation team; product-side validation is tracked separately) showed
the shape:

- The Model joins `bridge → users` (MANY_TO_ONE).
- The `users` table's RLS rule reaches `bridge` through the table-level join
  `users → bridge` (`rls_rules.joins`, `source: users`, `destination: bridge`).
- Together: `bridge → users → bridge`. Query generation sees `bridge` with two roots
  (the Model's root fact, and `bridge` itself via the RLS path) and throws the GUID
  mismatch. Filtering on the Liveboard broke for every user subject to the rule.

Neither `ts tml lint` nor `ts audit` catches this today: I17 builds its graph from
`model_tables[].joins` only, and no audit rule checks join cycles at all. Confirmed
against the case's own TML (kept outside the repo): the failing Model passes I17; the
combined graph below reports exactly the diagnosed cycle; the customer's workaround
Model checks clean.

## Goals

1. Detect, before import and in an audit of existing Models, a **directed cycle** in
   the graph formed by a Model's joins **plus** the RLS joins of the Tables it uses.
2. Say what to change, in words a modeller acts on: which RLS rule, which join, which
   Model join, and the two usual fixes (drop one of the two joins, or point the Model at
   a non-RLS copy of the table / move the rule).
3. One implementation, two callers: a shared graph builder used by a new lint rule and
   a new audit rule.

## Non-goals

- Changing ThoughtSpot's own import validation (that is the product ticket).
- Checking RLS rule *expressions* (`rules[].expr`) or which users a rule affects.
- Re-deriving query generation's root-selection logic. We flag the graph shapes that
  are known to fail; we do not simulate the query planner.
- Table-to-table cycles that involve no Model (a Table TML batch with no Model): out of
  scope; the failure only exists in a Model's query graph.

## Anti-goals

- **No false alarms on the common healthy shape.** An RLS path that runs the *same*
  way as the Model (the case's `users → organisations`, which the Model also joins
  `users → organisations`) is fine and must stay silent. A rule that cries wolf on
  every RLS table will be switched off.
- **No customer data in the repo.** Fixtures are synthetic recreations of the shape
  with made-up table names; the case files stay in the user's Downloads folder.

## The shape of RLS joins in Table TML (confirmed from a real export)

```yaml
table:
  name: users_rls
  joins_with:
  - name: users_rls_to_bridge          # an ordinary table-level join
    destination: {name: bridge}
    on: "[users_rls::user_key] = [bridge::user_key]"
    type: INNER                         # no cardinality on this join
  rls_rules:
    tables: [{name: bridge}, {name: users_rls}]
    joins:                              # the joins the rule's paths may use
    - name: users_rls_to_bridge         # = a joins_with name on this Table
      source: users_rls
      destination: bridge
      type: INNER
      is_one_to_one: false
    table_paths:
    - id: bridge_1
      table: bridge
      join_path:
      - join: [users_rls_to_bridge]     # ordered list of rls_rules.joins names
      column: [group_id]
    - id: users_rls_1
      table: users_rls
      column: [organisation_id]
    rules:
    - name: …
      expr: "[users_rls_1::organisation_id] in ts_var(org_ids) and [bridge_1::group_id] in ts_var(group_ids)"
```

`agents/shared/schemas/thoughtspot-table-tml.md` documents only `tables`,
`table_paths[].{id,table,column}` and `rules`. This work adds `rls_rules.joins[]` and
`table_paths[].join_path`, citing the live sighting.

## The check

**Graph.** Start from the Model's join graph exactly as I17 builds it (`JoinGraph`:
nodes are `model_tables` entries by alias/id/name; an edge per join, arrow
MANY → ONE by cardinality). Then, for each `model_tables` entry whose Table TML is
available and has `rls_rules` (the *secured table*):

- **Used joins only (decided).** A join counts when it appears in the `join_path` of
  a `table_paths` entry whose `id` is referenced (`[id::…]`) by at least one
  `rules[].expr`. An unreferenced path, or an `rls_rules.joins` entry no path uses,
  cannot put a table in a query, so it adds nothing.
- **Direction by walking the path (decided).** For each used path, walk its
  `join_path` items in order (each item a segment; all `join` names in an item are
  taken in order), starting at the secured table. Each join connects the current
  table to the other end named by its `source`/`destination` pair; the edge points
  **current → next**, i.e. away from the secured table — regardless of which end the
  TML lists as `source`. This makes the result independent of which table declared
  the table-level join (builder-check Q1). If a join does not touch the current
  table, the path is malformed: skip that path and say so in the finding detail
  (lint) / ignore it (audit). In the one real sample, path order and
  `source → destination` agree; the walk is the safer reading when they would not.
- RLS joins carry no cardinality, so the Model's MANY → ONE convention cannot apply;
  "away from the secured table" is the reading that reproduces the case's "two
  roots" diagnosis.

**Findings: directed cycles only (decided).** A finding is a cycle in the combined
graph that **contains at least one RLS edge** → HIGH. Model-only cycles are I17's,
and ThoughtSpot rejects them at import. Implementation (builder's call within this):
compute strongly connected components of the combined graph with the existing
`strongly_connected`; for each RLS edge `u → v` inside one component, report the
cycle `u → v → … → u`, completing it with the existing shortest-path helper from `v`
back to `u`. One finding per RLS edge that closes a cycle. Reuse the helpers; no new
cycle algorithm.

The related support case (two joins with opposite cardinalities between one pair
once RLS applied) is a two-node cycle in this graph, so it is covered.

**Not in scope: second routes (diamonds) through an RLS edge.** Nothing shows a
diamond failing at query time, and the common healthy star (fact → users,
fact → orgs, RLS users → orgs) is a diamond. Flagging it at HIGH would be exactly
the false alarm the anti-goals forbid. Filed as a backlog item to probe live before
any rule is written.

**Aliases (decided).** RLS joins name physical tables. When the Model has more than
one node for a physical table (aliased roles), the RLS edge is added from **every**
node of the source table to **every** node of the destination table: the rule
applies wherever the table is queried. With cycles-only findings this cannot invent
a loop that the Model's own arrows do not close. The healthy buyer/seller
role-playing shape (fact → users_buyer → orgs_buyer, fact → users_seller →
orgs_seller, RLS users → orgs) has no cycle and must stay silent; it is a required
fixture. A table the Model does not include contributes no node, and an RLS edge to
or from it is dropped.

## Where it surfaces

- **Lint: `I22`**, cross-file like I21 — runs only when the Model is linted together
  with the Table TMLs that carry the RLS rules (`ts tml lint` on a batch/directory,
  and the converters' pre-import lint). A Model linted alone has no ground truth for
  its Tables' RLS rules; it is silent, not a false pass, and the rule's docstring says
  so. Added to `tml_lint.py`'s `CANONICAL-RULE-SET` marker (the only list —
  `check_lint_invariant_list.py` enforces that), with an invariant entry in
  `agents/shared/schemas/ts-model-conversion-invariants.md`.
- **Audit: `S11`**, category S (Security), HIGH, scope `model`, one finding per
  closing RLS edge, message naming the RLS rule's table, the RLS join, and the Model join
  that closes the loop. Table TML is fetched unconditionally today, so the rule needs
  no new `requires`/`uses` entry; the read-declaration gate will confirm. A code rule
  (or a derived field + `each` aggregate) calling the shared helper — the builder's
  call per `rule-authoring.md` "When to write a code rule".
- **Shared helper:** a function in `tml_join_graph.py` that takes the Model's
  `model_tables` and a `{physical table name: table body}` map and returns the combined
  findings as data (each cycle: the nodes, the edges, which are RLS). Lint and
  audit format their own messages from it.

Message (user-facing; no engine identifiers):
> RLS on `users` joins out to `bridge` (`users_to_bridge`), and the Model joins `bridge`
> to `users` — a loop query generation cannot resolve (it fails with "Guid Mismatch").
> Drop one of the two joins, or point the Model at a copy of `users` without this RLS
> rule.

## Tests and evidence

- Synthetic fixtures (made-up names), each a Model + Table TMLs:
  1. the case's shape → cycle, I22 and S11 fire;
  2. the workaround (Model uses a non-RLS copy) → silent;
  3. RLS path in the same direction as the Model join (`users → orgs` both ways the
     same) → silent;
  4. RLS join declared but not used by any `join_path`, and a path no rule references
     → silent;
  5. opposite-cardinality pair (Model `a → b`, RLS on `b` walks `b → a`) → fires
     (two-node cycle);
  6. the case's shape with the table-level join declared on the *far* table
     (`source`/`destination` reversed in TML, path still starts at the secured table)
     → fires (proves the path walk, not the TML labels, sets direction);
  7. healthy star with a diamond (fact → users, fact → orgs, RLS users → orgs)
     → silent;
  8. aliased role-playing Model (buyer/seller roles of users and orgs, RLS
     users → orgs) → silent; plus an aliased variant of the case's shape → fires;
  9. malformed path (a join that does not touch the current table) → no crash; lint
     notes it, audit ignores it;
  10. Model linted without its Table TMLs → I22 silent.
- Catalog examples for S11 (`fires` / `silent`), generated catalog row, rule-id
  history gate passes.
- Run against the case's real files locally (never committed): I22 and S11 fire on the
  failing Model, silent on the workaround. Recorded in the PR as a sentence, no names.
- Run `ts audit` S on the 351-Model SE snapshot (`~/Dev/audit-runs/snapshots/se-30d`,
  via `--snapshot-in`): report the S11 count (new rule; the pinned legacy suite is
  unaffected because S11 is not a pinned rule). **If S11 fires on more than a handful
  of Models, stop and inspect them before shipping** — each hit must be a genuine RLS
  loop, or the rule is wrong; no downgrade-and-ship.
- Approving this design covers `rule-authoring.md` procedure 1 step 1 (the plain
  English restatement is the "The check" section). The generated catalog row (step 7)
  is shown in the PR description, not as a separate stop.

## Constraints

- Public repo: synthetic fixtures only; no customer, table or cluster names from the
  case anywhere in the repo, commits or PR.
- Repo rules: PR to main, ts-cli MINOR bump (new lint rule + audit rule), ts-audit
  MINOR bump, CHANGELOG, `ts-model-conversion-invariants.md`, Table TML schema doc,
  `rule-authoring.md` procedure followed for S11.
- Reuse `tml_join_graph.py` (`JoinGraph`, `strongly_connected`, the shortest-path helper); do not
  fork the cycle logic.

- Backlog: a dated item to probe whether a second route (diamond) through an RLS
  join fails at query time, before any rule flags it.

## Left to the builder

- Code rule vs derived field for S11.
- Exact message wording within the shape above.
- Whether I22 also runs inside the converters' existing pre-import lint calls
  automatically (it should wherever Table TMLs are already in the batch).
