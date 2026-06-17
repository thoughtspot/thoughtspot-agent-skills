# Repo Audit — 2026-06-17 (full, inaugural)

**Scope:** full (all 12 internal angles). **Method:** 8 parallel subagents, one per angle
cluster, synthesised into a prioritised report. **Rubric:** `.claude/rules/repo-audit.md`
(this audit predates the rubric and is what motivated it).

## Verdict

Repo healthy. Problems clustered, not systemic. Severity bands:

- 🔴 **Databricks runtime wired into nothing** — the Genie runtime's SETUP shared-path was
  broken and it was invisible in the parity matrix.
- 🟠 **CI was a strict subset of pre-commit** — filesystem-state gates ran only locally and
  were bypassable with `--no-verify`, no server-side catch.
- 🟡 **Weak validators** — secrets placeholder matching too loose; coverage-matrix backlog
  exemptions dateless; no guard against v1 endpoints regressing.
- 🟢 **Doc / backlog clutter** — completed items mixed with active backlog.
- **Security:** strong. Only Low-severity items, all addressed.

## Findings → outcomes (the two-bucket routing)

| # | Angle | Finding | Outcome | Bucket |
|---|---|---|---|---|
| 1 | Legacy / dead files | `coco/`, `unity-catalog/` untracked artifacts | Flagged for manual delete | (manual) |
| 2 | README / SETUP | Databricks SETUP shared-path wrong (`.assistant/shared/` vs `.assistant/skills/shared/`) | Fixed | PR (2026-06-17) |
| 3 | open-items | `check_open_items` only matched `## Item N`, missed `## #N` (6/7 files) | Fixed + regression test | PR #98 area |
| 4–5 | Tools / ts-cli | No central HTTP-error handling; raw tracebacks on API failure | Fixed | **#99** |
| 6 | Testing value | Smoke-test coverage gaps | Reviewed, acceptable | — |
| 7 | PR validation | CI ⊊ pre-commit; gates bypassable | CI gates added to `validate.yml` | merged |
| 8 | Cross-runtime drift | Databricks runtime absent from `PARITY.md` | Added `databricks` column to `generate_parity.py` | PR (2026-06-17) |
| 9 | Conversion consistency | CHAR vs VARCHAR params; measure-classification gap (live Tableau migration) | Fixed | ts-convert-from-tableau v1.14.1 |
| 10 | Security | secrets markers substring-matched; no v1-endpoint guard | Tightened + new `check_no_v1_endpoints.py` | **#100** |
| 11 | Codification | I1/I2/I4/I5 invariants enforced only by hand | New `ts tml lint` | **#99** |
| 12 | Synthesis | — | This report + the rubric | — |

## Codification wins (manual → automated)

Three audit findings became permanent validators, so they can't recur:

- `check_no_v1_endpoints.py` (AST-based) — angle 10
- `check_secrets.py` placeholder anchoring — angle 10
- `check_coverage_matrix.py` dateless-backlog rejection — angle 9

Plus `ts tml lint` codifies the model invariants (angle 11).

## PRs & backlog

- **Shipped:** #90–#98 (connection prompt, migration scope + obj_id rule, chart-types
  schema + Muze spec, CHAR/measure fixes, Databricks SETUP/PARITY, CI gates, ts-cli docs,
  open-items + changelog fixes, backlog archive).
- **In review:** #99 (`ts tml lint` + HTTP errors), #100 (validator hardening).
- **Backlog:** BL-026 (liveboard-builder), BL-027 (explicit table binding), BL-028 (audit
  mode for viz layer), BL-029 (coverage matrices for 3 conversion skills, target 2026-08-31).

## Follow-ups for the next audit

- First **external sweep** (angles 13/14/16) has never run — currency anchors not yet
  populated. That is the immediate next external pass.
- Angle 15 (conversion fidelity) parked 2026-06-17 — revisit once 13/14/16 are embedded.
- Manual deletes still pending: `coco/`, `agents/shared/worked-examples/unity-catalog/`.
