# Severity rubric (roadmap PR 4.2)

**Status:** design, 2026-11-01. Roadmap row 4.2 (`2026-10-23-audit-v2-roadmap.md`, wave
4): "each rule declares its evidence class; a heuristic alone cannot exceed MEDIUM; the
catalog gate warns when a rule fires on most Models of the SE snapshot." The product owner
skipped the design questions (2026-11-01); the calls below are the author's and are listed
at the end for checking.

## Why

A finding's severity tells a reader how sure the audit is and how much it matters. Today
nothing ties the first to the evidence: S2 calls a column PII from its name alone and grades
it HIGH, so 45 HIGH findings on the 148-Model SE demo sample rest on a regex; S5 grades a
column named like a credential CRITICAL. A reader cannot tell a guess from a fact, and a
wrong guess at HIGH costs the report its credibility. Separately, a rule that fires on most
Models is either telling the reader something about the whole estate (fine, but worth
saying once) or mis-calibrated; nothing notices either way. Under the Spotter assessment A3
is HIGH on 89% of the sample's Models and A6 on 79%.

## Goals

1. Every active rule declares an **evidence class** in the catalog.
2. The catalog gate **refuses** a rule whose evidence class is `heuristic` and whose
   highest reachable severity, under any profile, is above MEDIUM.
3. The audit can **report the fire rate** of every rule over a snapshot, and **warns** for a
   rule at MEDIUM or above that fires on more than half the Models, unless the rule records
   that this was reviewed.
4. The generated catalog doc and each finding say which class of evidence it rests on.

## Non-goals

- Re-grading rules on any ground other than the cap (that is the job of each rule's own
  review). The fire-rate warning surfaces candidates; it changes no severity.
- New rules (4.3, 4.4).
- Putting the SE snapshot, or anything derived from it per Model, in the repo.

## Anti-goals

- A fire-rate check that needs the snapshot in CI, or that commits per-Model results.
- A class so vague every rule picks the strongest one; the definitions below are tests a
  reviewer can apply.
- A warning that can be silenced without a reason and a date.

## Evidence classes

| Class | The finding rests on | Examples |
|---|---|---|
| `fact` | Something the TML or metadata states, read exactly (normalising whitespace and case is still exact) | A4 (no Model description), D8 (two Table objects on one physical table), S10 (`is_bypass_rls`), H8 (the same Answer formula, normalised, in two or more Answers) |
| `measure` | A count, share or ratio the TML states, graded against a pass mark the catalog chooses | A1, A2, A6 (coverage), D1, P7, P8 (size), P13 (rule count), P4 (table count with `join_progressive` off), D7 (shared share of two table sets) |
| `heuristic` | An inference: a name pattern, a role guess, a similarity | S1, S2, S4, S5 (personal data and credentials from names), H1, H2, H10 (name and wording patterns), D12 |

A rule that combines classes takes the **weakest** one it needs to fire: S2 needs a column
to be PII, which only a name pattern says, so it is `heuristic` even though "indexed" and
"no RLS" are facts.

Each of the 43 active rules gets a class in its catalog entry (`evidence:`); the builder
classifies them by the table's tests and lists the result in the PR. The author's starting
point: heuristic = S1, S2, S4, S5, H1, H2, H10, D12; measure = A1, A2, A6, D1, D9, P2, P7,
P8, P11, P13, P16, P17, P4, D7; fact = everything else (D11 and D7's shared-fact test
included: a table's role is read from declared joins and measures, PR 4.1 — a role
*default*, where no cardinality is declared, is not a name guess). So the cap moves only
S2, S4 and S5; D7 and H8 keep their HIGH.

## The cap

A `heuristic` rule's highest reachable severity, under every profile, is at most MEDIUM:
every severity `catalog_code.emitted_severities()` reports for the rule (bands, severity
maps, fixed severities, profile overrides and a code rule's registered severities). The
catalog gate enforces it, with the rule, profile and offending severity in its message.
Run-time override layers (`engine/run.py` `layers`) are not user-facing today; if they
become so, the cap must be enforced there too (noted in the code).

Effect: S2 HIGH → MEDIUM (its INFO stays), S4 HIGH → MEDIUM, S5 CRITICAL and HIGH (`token`)
→ MEDIUM. On the
sample this moves S2's 45 HIGH findings to MEDIUM (both assessments); S4 and S5 do not fire
there. Their messages and remediation keep saying what to check; the description says the
grade reflects a name match. Re-pin S2/S4/S5 with `repin_findings.py` after the sample
comparison shows nothing else moved.

## Fire rates

A new `ts audit fire-rates --snapshot-in <dir> [--assessment general|spotter]` (or a flag on
`ts audit run`; builder's choice) prints, per rule, the number and share of objects with at
least one finding, by severity. Counts only, never names.

The denominator is the rule's own object type: Models for a rule whose findings carry a
Model's guid (D7 counts the pair's first Model, as it reports), Tables for table, RLS-rule
and metadata findings, Answers for Answer findings, Sets for Set findings — each against
that type's count in the snapshot. A rule whose findings name no object (H8, `guid: none`;
D12, an empty guid) is listed with its finding count and never warns.

A rule **warns** when, under an assessment, it fires at MEDIUM or above on more than 50% of
its objects, unless its catalog entry carries a review for that assessment:
`fire_rate_reviewed: {spotter: {date: YYYY-MM-DD, rate: 0.89, note: "..."}}` (keyed by
profile id, so a Spotter review does not hide a General warning) saying why that is
expected (for A3: most Models genuinely have no coaching). A review warns again when it
is older than 180 days, or when the rate is more than 10 points above the reviewed `rate`.

Where it runs: the snapshot lives outside the repo, so this is **opt-in**:
`scripts/pr-ready.sh` runs it when `TS_AUDIT_SNAPSHOT` names a snapshot directory, and
`rule-authoring.md` makes it a step when adding or regrading a rule. CI does not run it.
On the sample today, under Spotter: A3 (89%), A6 (79%) and A1 (62%) would warn; A2 (50%,
exactly at the line) and A4 (41%) would not; under General, A3 (89%) would. This PR adds
reviews for those four (A3 under both assessments) with the measured rates.

## Report

The generated catalog doc gains an Evidence column. Each finding's JSON carries
`evidence` (from its rule), and the report's finding rows show "name match" for a heuristic
one, so a reader can tell a guess from a fact.

## Tests

- Gate: a heuristic rule reaching HIGH through a band, a severity map, a fixed severity and
  a profile override each fails; at MEDIUM it passes; a rule with no `evidence` fails; an
  unknown class fails.
- Fire rates: a synthetic snapshot where one rule fires on 3 of 4 Models warns, on 2 of 4
  does not; a fresh review for that assessment silences it, a review for the other
  assessment does not, a stale one does not, a rate 11 points above the reviewed one does
  not; a Table-scoped rule is counted against Tables; a rule with no object never warns;
  output has no names.
- The new finding field is listed in `audit_pinned.UNCOMPARED_AS_PINNED`, so re-pinning
  does not copy it into pins.
- S2/S4/S5 fixtures fire at MEDIUM; the sample replay differs from main only in S2's
  severity.

## Left to the builder

- The command's shape (new subcommand or flag), the JSON field name in findings, the exact
  report wording.
- Classifying the rules by the table's tests (the author's list above is a starting point).

## Calls made without the product owner (check these)

- Three classes, and "weakest class needed to fire" decides a mixed rule.
- **S5 (credential-named column) drops from CRITICAL (and HIGH for `token`) to MEDIUM**
  under the cap, like S2/S4.
- D7 and H8 are not heuristic (D7 a measure, H8 a fact), so they keep HIGH.
- A fire rate counts each rule against its own object type; rules naming no object never
  warn.
- Reviews are per assessment and lapse after 180 days or a 10-point rise.
- The fire-rate line is more than 50% of Models at MEDIUM or above, per assessment, and a
  review lapses after 180 days.
- The fire-rate check is opt-in (snapshot outside the repo), not a CI gate.
- Findings show their evidence class in the report.
