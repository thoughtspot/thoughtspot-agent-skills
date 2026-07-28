# Per-wave aliases (spec step 7) — live verification

**Cluster:** `nebula-damian-alias` · **Date:** 2026-07-28 · **ts-cli:** v0.123.0

The last unbuilt piece of Phase D. Until now step 7 was **prose telling an operator to run
`/ts-object-model-alias` and check four things by eye**, one of which is the only genuinely
catastrophic action in the routine.

---

## What was actually missing

`ts alias build --merge` already refused overlapping scopes (PR #391) and enforced the 20/25 MB
ceilings and the 5 MB async path. Two things were not covered:

1. **"Confirm the export returned the aliases of every already-cut-over tenant."** An
   instruction, not a check. Alias load is full-document with no delta until 26.10, so the
   merged document **replaces** what the Model carries — a partial export silently strips every
   Org it missed, and those users see `STRING_1` where they saw `Region`. Nothing surfaces it:
   each entry left in the document is individually valid and the import returns `OK`.
2. **Hand-transcribing the alias rows.** They are the exact inverse of the rename `apply` just
   performed, which is already recorded in the approved `column-mapping.csv`. Retyping is a
   step whose mistakes are silent — a misspelled `column` aliases nothing.

`ts migrate aliases` covers both and **emits the envelope `ts alias build --merge` already
consumes**, so the transform, the ceilings and the async path stay where they were.

---

## The state it was tested against

The master `T2_PUBLISH_MODEL` (`2a743be3`) already carried **ORG2's** aliases from the earlier
end-to-end run — so this was a genuine preservation test, not a synthetic one.

```
STRING_1  ORG2  TS_WILDCARD_ALL -> 'Segment'
DATE_1    ORG2  TS_WILDCARD_ALL -> 'Order Date'
```

---

## 1. The argument refusals

| Passed | Result |
|---|---|
| neither `--expect-org` nor `--first-wave` | **Refused** — "a check that defaults to off is not a check" |
| **both** | **Refused** |
| 2 × `--target-org`, 1 × `--plan-dir` | **Refused**, naming the counts |

Requiring one of the two is deliberate. Defaulting `--expect-org` to empty would make the
catastrophic check silently do nothing, which is the exact class of bug it exists to prevent.

## 2. The catastrophic check, against real data

Claiming ORG3 was cut over when it holds no aliases:

```
$ ts migrate aliases -m 2a743be3-... --target-org ORG1 -d ./plan \
      --expect-org ORG2 --expect-org ORG3 -p nebula-damian-alias
exit=1
Refused. This wave must not be imported:
  - ORG3: already cut over, but the alias export returned NO entries for it. Merging would
    drop that Org's aliases on import and its users would see the base column names.
    Re-export before retrying
```

ORG2 passed because it genuinely is present; ORG3 was named. Coverage is checked **by Org, not
by count** — a count is satisfiable by the wrong Orgs, and ten aliases for one tenant would
pass "ten or more" while nine tenants are being wiped.

## 3. The valid wave

```
$ ts migrate aliases -m 2a743be3-... --target-org ORG1 -d ./plan --expect-org ORG2 -p …
2 alias(es) for ORG1; 1 Org(s) already present and preserved. Pipe into `ts alias build --merge`.

  ORG1  STRING_1  -> 'Segment'      group=TS_WILDCARD_ALL
  ORG1  DATE_1    -> 'Order Date'   group=TS_WILDCARD_ALL
```

Derived from `column-mapping.csv`, and correct: `Segment` → `STRING_1` was the rename `apply`
applied, so the alias is its inverse.

## 4. Merge, import, and the round-trip that proves preservation

Piped through `ts alias build --merge` (821 bytes) and imported. Re-exporting afterwards:

```
STRING_1  ORG2  TS_WILDCARD_ALL -> 'Segment'
STRING_1  ORG1  TS_WILDCARD_ALL -> 'Segment'
DATE_1    ORG2  TS_WILDCARD_ALL -> 'Order Date'
DATE_1    ORG1  TS_WILDCARD_ALL -> 'Order Date'
```

**ORG2 survived and ORG1 was added.** All four wildcard-scoped, so no column carries two
pathways. Both waves' provenance descriptions are intact.

## 5. Idempotent

Re-running the same wave and re-merging produced a **byte-identical** document
(`documents identical: True`). That matters for a step that is serialised and may be retried
inside its window.

## 6. The gate now recognises both Orgs

```
2 alias(es) for ORG1; 2 Org(s) already present and preserved.
```

Which is the next wave's precondition, established by this one.

---

## What is NOT verified, and cannot be by API

**That an ORG1 user actually sees `Segment`.** Aliases render *only* in Search Data, Answers,
Liveboards and Spotter — **not** in the Data Management app (an open ThoughtSpot development
item) and **not** via `metadata/answer/data`, which returns base names. So there is no
programmatic oracle: a human must open Search Data as a real non-admin user in ORG1
(`guest4`, or `guest1`) and look.

Everything up to and including the stored document is verified. The last inch is a human
looking at a screen, and no amount of API checking substitutes for it.

## Cluster state

The master's alias document now carries **ORG1 and ORG2**. That is additive and is the correct
end state for the fixture. The pre-change document (ORG2 only) was captured before the import;
to revert, rebuild without `--target-org ORG1` and import **without** `--merge`, which replaces
rather than appends.
