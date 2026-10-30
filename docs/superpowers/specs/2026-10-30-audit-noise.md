# Noise fixes (roadmap PR 2.3), with BL-112

**Status:** built to the roadmap's PR 2.3 list (`2026-10-23-audit-v2-roadmap.md`, wave 2),
with one decision taken by the product owner on 2026-10-30 (D3) · Closes BL-406 item 4 and
BL-112.

## What changes

| Rule | Was | Now |
|---|---|---|
| D3 | One INFO per LEFT/RIGHT outer join (30% of all findings on the SE demo sample) | Full outer join HIGH per join, as before; one INFO per Model listing its LEFT/RIGHT outer joins. Code rule `join_types`. **Product owner's choice** (2026-10-30), over dropping them or leaving them |
| H2 | "The " and "A " counted as boilerplate openings | Dropped: ordinary English. "This is a", "Column for", "Field for" stay |
| A1, A2 | Coverage over every column | Over visible columns only: search and Spotter never show a hidden one |
| D10, D11, H3 | A model table looked up by `name`, though its columns carry the alias (BL-305) | By alias, else name; a join's `with` resolved by alias, id or name (`tml.join_target`, the join graph's own rule). D10 reports a table by that key |
| H3 | A formula referenced by id (`[formula_X]`, how TML writes it) not seen | Seen |
| S1 (and so S2, S4) | No space between words ("Zip Code" missed); short tokens inside words ("Hotel" a phone, "Cousin" a national id) | `_SEP` allows `-`, `_` or a space; short tokens (tel, fax, mobile, sin, nin, ssn, dob, iban) are whole words, ending at a non-letter or a camelCase hump |
| S5 | "API Key" / "Secret Key" not matched (raised in PR 2.2's review) | Matched |
| P18 | A function name inside a `[...]` reference or a literal matched; one wording for both kinds (PR 2.2 review) | Only code is searched; the detail says "COUNT_DISTINCT aggregation" or "distinct-count formula" (`@distinct_count_kind`) |
| smoke (BL-112) | Re-implemented the audit, tested its own drifted PII copy | Runs `ts audit run` and `ts audit report` on one Model, checks rule ids against the catalog, tests the audit's own `PII_PATTERNS` |

## Choices

- **D10's reporting name.** The key (alias, else name) — an aliased table's alias is what
  tells its roles apart. A table with an alias whose columns are prefixed by its physical
  name reads as zero-column: the schema says the prefix is the alias when there is one, and
  D6 already keyed this way.
- **S1's word boundary** is letters-only, so `home_phone`, `TEL_NO`, `telNumber` and
  `Tel` match while `Hotel` and `Intelligence` do not. Longer, distinctive words (email,
  phone, birthday) stay substring matches so `CustomerEmail` still reads as email.
- **Not done:** A1/A2's denominators for the Spotter profile's 95% / 80% pass marks are
  unchanged; with hidden columns gone, the bars apply to what a user can see.

## Verification

- Pins moved for A1, A2, D3, D10, D11, H2, H3, P18, S1, S2, S5 (output in the PR); edge probes
  updated; the D10 alias strict xfail passes as a plain test.
- `tests/test_audit_noise.py` and the updated engine, human and data tests hold each change.
- The 148-Model SE demo sample replayed on main and on the branch (General): D3 490 → 84,
  D10 62 → 17 (all 46 MEDIUM were the alias bug), H2 79 → 22, S1 51 → 89 and S2 23 → 50
  (display names now read; the 43 new S1 matches were checked by matched word — zip code,
  first/last/full name, birth, tax, postal, card, account — and the 5 dropped ones contained
  no PII word), A2 +1 MEDIUM under Spotter-ready. Every other rule's findings are identical.
- The rewritten smoke test, run live on the SE demo cluster with the branch's code: the
  audit, report and PII steps pass; the auth step fails on `ts auth whoami` (404 on main
  too — BL-497).
