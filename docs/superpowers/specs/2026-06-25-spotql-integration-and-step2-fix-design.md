# Design — SpotQL skill: integration docs, Step 2 fix, capability summary, Model selection

**Skill:** `ts-object-model-spotql-query`
**Branch:** `feat/spotql-integration-and-step2-fix` (off `main` — no direct push; ships via PR)
**Date:** 2026-06-25
**Author:** damian.waldron

## Background

This design came out of an exploratory session against `champ-staging` querying the
"Dunder Mifflin Sales & Inventory" Model (`4da3a07f-fe29-4d20-8758-260eb1315071`). Three
things surfaced that the skill doesn't currently capture well:

1. **The raw SpotQL API format** — `generate-sql` / `fetch-data` request and response
   shapes, the columnar result encoding, and several non-obvious parsing gotchas. A
   developer wanting to call SpotQL from their own product/agent has to reverse-engineer
   this from the `ts` CLI source today.
2. **A real accuracy bug in Step 2** — the SKILL.md instructions for reading a Model's TML
   to classify columns do not match the actual Model TML structure, which breaks the
   `SUM`-vs-`AGG` decision that Step 3 depends on.
3. **Two UX gaps** — there is no canonical "what can you do?" capability answer, and Step 1
   doesn't gracefully accept the GUID/URL a user most often has to hand.

The four reference files (`spotql-rules.md`, `udf-reference.md`, `patterns.md`,
`limitations.md`) are well-researched, dated, ticket-linked, and live-verified. They are
**not** in scope for rework — this design leaves them as-is.

## Goals

- Let a developer integrate SpotQL into their own product/agent from a single reference doc.
- Make the skill emit paste-ready API request bodies during a normal developer-mode session.
- Fix Step 2 so column classification (attribute vs measure, raw vs aggregate-formula) is
  correct and deterministic.
- Give the skill a consistent capability summary and a forgiving Model-selection step.

## Non-goals

- No changes to `spotql-rules.md` / `udf-reference.md` / `patterns.md` / `limitations.md`.
- No new `ts` CLI command — the integration doc describes the raw HTTP API for non-CLI
  consumers; CLI users keep using `ts spotql`.
- No natural-language→SpotQL automation beyond what the skill already does.

## Key technical findings (the grounding for this design)

Verified live on `champ-staging`, 2026-06-25:

- **Endpoints are callosum, not public REST.** `POST /callosum/v1/v2/data/spotql/generate-sql`
  and `.../fetch-data` — under `/callosum/v1/v2/`, **not** the documented `/api/rest/2.0/`
  surface. The SpotterCode MCP (public API spec) does not index them. Document them
  empirically.
- **Request bodies differ slightly.** `fetch-data` takes `{spotql_query, model_identifier}`.
  The playground schema for `generate-sql` additionally shows `connection_type` — it is
  **optional**; the `ts` CLI omits it and the call succeeds against a standard CDW
  connection.
- **`generate-sql` success** = `{"executable_sql": "<warehouse SQL>"}` with **no `status`
  field**. Errors = HTTP 400 with `{"error": {"message": {"code", "debug": "[CODE] …"}}}`.
- **`fetch-data` success** = `{"query_result": {"results": [{"tables": {"column": [...]}}]}}`
  — **columnar**, with four gotchas (see Change 1).
- **Model TML structure** (from `ts tml export <guid>`): the edoc is a structured document
  (JSON syntax on this build; `yaml.safe_load` parses both). `column_type` lives at
  `columns[].properties.column_type` — **not** as a direct child of the column entry.
  Formula columns carry a `formula_id` that references a separate top-level `formulas[]`
  array; the formula's `expr` is where the aggregate logic lives.

## The five changes

### Change 1 — New `references/integration.md`

Reference material (not an agent flow) for calling SpotQL directly from your own code.
Sections:

1. **Authentication** — three options, each with request/response shape:
   - Trusted-auth secret key → `POST /api/rest/2.0/auth/token/full` with
     `{username, secret_key, validity_time_in_sec}` (recommended for a service/agent).
   - Username + password → same endpoint with `{username, password, validity_time_in_sec}`.
   - Existing bearer token (browser/long-lived) used directly.
   - Note token TTL from `expiration_time_in_millis`; cache and refresh before expiry.
   - All requests carry `Authorization: Bearer <token>`, `Content-Type: application/json`,
     `Accept: application/json`.
2. **Endpoints + request bodies** — both endpoints under `/callosum/v1/v2/data/spotql/`.
   `generate-sql` body shows the optional `connection_type` with the "omit for standard CDW"
   note; `fetch-data` body is `{spotql_query, model_identifier}`. **Callout:** these are
   callosum endpoints, not the documented public `/api/rest/2.0/` API.
3. **`generate-sql` response** — `{"executable_sql": …}`, no `status`; the HTTP-400 error
   envelope and how to pull the `[CODE]` out of `error.message.debug`.
4. **`fetch-data` response** — the full raw columnar shape, with the four gotchas called out:
   - Columnar, not row-major (all values for col 0, then col 1, …).
   - Column `name` is an unstable per-query GUID — use the **SELECT ordinal** as the
     identifier; the caller maps ordinals to its own column labels.
   - `INT64` arrives as a JSON **string** (`"int64Val": "1672107"`) — parse with `int()`.
   - Every cell carries **all** type fields (zeros/empties for the irrelevant ones) — use
     the column-level `type` to choose which field to read; respect `nullVal`.
5. **Minimal response parser** — ~20 lines (Python) transposing columnar → rows, handling
   the INT64 string and `nullVal`, keyed to SELECT order. Mirrors the logic in
   `tools/ts-cli/ts_cli/commands/spotql.py` (`extract_columns_and_rows` / `_cell_value`)
   so the two stay conceptually aligned.

Add a row to the SKILL.md reference table pointing at this file.

### Change 2 — SKILL.md Step 6 (Review): paste-ready request bodies

In developer/integration depth, after a successful `generate-sql`, emit a
**📋 Request bodies (paste into playground or your own code)** block pre-filled with the
session's actual SpotQL and Model GUID, for both endpoints. Zero extra API calls (both
values are already in memory). **Trigger = developer depth** — no separate
intent-detection; developer mode already implies the user wants the artifacts.

### Change 3 — SKILL.md Step 2: TML parsing fix + column classification

Rewrite Step 2 to match real Model TML:

- The edoc is structured data — JSON or YAML; `ts tml export … --parse` (or
  `yaml.safe_load`, which accepts both) yields a dict. Drop the bare "(YAML)" claim.
- `column_type` is at `columns[].properties.column_type` (ATTRIBUTE / MEASURE).
- A formula column carries `formula_id`; resolve it against the top-level `formulas[]`
  array to read the formula `expr`.
- **Classification technique** (makes Step 3 deterministic, not trial-and-error):
  - ATTRIBUTE → group by it.
  - MEASURE whose `formulas[].expr` contains an aggregate keyword
    (`sum`, `count`, `group_aggregate`, `last_value`, `first_value`, …) → **aggregate-formula
    column → `AGG()`**.
  - MEASURE with no aggregating formula → **raw measure → `SUM`/`AVG`/…**.
  - Cross-link `spotql-rules.md` § Aggregation (which already documents the `AGG` vs `SUM`
    rule and the "quick test" probe).

### Change 4 — SKILL.md capability summary ("what can you do?")

Add a short **"What this skill does"** block near the top (after the intro, before
References) naming the four capabilities — **answer** a Model question, **show the work**
(SpotQL / warehouse SQL / JSON / table), **help you integrate** (paste-ready bodies + the
integration doc), **explain the rules** (aggregation, UDFs, patterns, limitations) — and
the **external-CDW-only** requirement up front. This is the canonical answer the agent
gives to "what can you do?" and doubles as an at-a-glance scope statement.

### Change 5 — SKILL.md Step 1: always ask for the Model; accept GUID / URL / name

Rewrite Step 1 so the agent always asks which Model to use and accepts any of:

- **A GUID** — use directly for `--model`.
- **A ThoughtSpot URL** — extract the GUID from the path (e.g. `/#/data/tables/<guid>`,
  `/#/data/embrace/<guid>`); users frequently have the Model open in a browser.
- **A name or nothing** — fall back to
  `ts metadata search --subtype WORKSHEET --name "%<term>%"`, present matches with
  name + GUID + owner + modified date (per the object-selection convention), let the user
  pick.

The GUID/URL path skips search; search is the fallback only. Either way, confirm the
resolved Model **display name** (needed for the `FROM` clause) before proceeding.

## Supporting / repo-convention updates

- **Reference table** in SKILL.md gains the `integration.md` row (part of Change 1).
- **`## Changelog`** bump to **1.1.0** at PR time (new capability — MINOR), dated entry
  summarising the integration doc + Step 2 fix + capability/Model-selection improvements.
- **`open-items.md`** — add a verified note: `connection_type` is optional/empirical on
  `generate-sql`, and the SpotQL endpoints are callosum (`/callosum/v1/v2/…`), not the
  public REST API the MCP indexes.
- **Smoke test** — `tools/smoke-tests/smoke_ts_object_model_spotql_query.py` already exists;
  check whether a small assertion on the Step 2 TML-parsing/classification path is warranted
  (add only if it doesn't require a live connection per the smoke-test rules).

## Files touched

| File | Change |
|---|---|
| `agents/cli/ts-object-model-spotql-query/references/integration.md` | **New** (Change 1) |
| `agents/cli/ts-object-model-spotql-query/SKILL.md` | Changes 2, 3, 4, 5 + reference-table row + changelog bump |
| `agents/cli/ts-object-model-spotql-query/references/open-items.md` | `connection_type` + callosum-endpoint note |
| `tools/smoke-tests/smoke_ts_object_model_spotql_query.py` | Optional assertion on Step 2 path |

## Risks / open questions

- **`connection_type` semantics** are empirical (no public spec). The doc states what we
  verified (optional for standard CDW) and flags it as build/connection-specific rather
  than claiming completeness.
- **TML edoc format** (JSON vs YAML) may vary by build/object version. Step 2's fix uses a
  format-agnostic parse (`yaml.safe_load` accepts both; `--parse` handles it), so the guidance
  holds regardless.
- **No new CLI surface** — keeps the change documentation-and-instructions only, lowering
  regression risk; the smoke test already covers the `ts spotql` happy path.

## Validation

Before opening the PR:
- `python3 tools/validate/check_*.py --root .` (skill-version, references, consistency, etc.)
- `pytest tools/ts-cli/tests/test_spotql.py` (unchanged logic, confirm still green)
- Re-run the smoke test against `champ-staging` (or `se-thoughtspot` per the smoke profile).
- Spot-check the integration doc's parser against a real `fetch-data` response.
