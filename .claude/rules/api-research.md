# API Research Rules

How to answer questions about ThoughtSpot REST API behaviour, endpoint shapes,
and product concepts. Applies when authoring or editing any skill, ts-cli
command, or shared schema.

---

## The core rule: consult the SpotterCode MCP before live testing

The repo wires the SpotterCode MCP server (see `.mcp.json`), which exposes the
canonical ThoughtSpot REST API spec and developer docs. Most "what does this
endpoint do?" questions are answerable from the spec without burning a staging
instance — and the spec is current, while inline prose in SKILL.md drifts.

**Precedence for any API question:**

1. `mcp__SpotterCode__get-rest-api-reference` — endpoint shape, request/response
   schema, error codes, auth requirements. Use `apiName: "..."` for an exact
   endpoint (e.g. `apiName: "deleteMetadata"`); `query: "..."` for semantic search.
2. `mcp__SpotterCode__get-developer-docs-reference` — broader coverage: product
   concepts, feature behaviour, examples, deployment, auth flows. Use as a
   fallback when (1) returns nothing, or for "how does X work" rather than
   "what is the request body for endpoint Y".
3. **Live instance** — only when the MCP doesn't answer the question, or the
   answer needs version-specific verification on a particular build.

Direct API probing against staging is still legitimate (see "When live testing
is the right answer" below) but should be the second step, not the first.

---

## When to use the MCP

Always, before any of these:

- Adding a new entry to `references/open-items.md`
- Adding a new command to `tools/ts-cli/`
- Describing an endpoint's request/response shape inline in a SKILL.md
- Documenting an error code, status enum, or response field
- Migrating a v1 endpoint to v2 (see `ts-cli.md` "v1 API migration trigger")
- Answering a user question about what an endpoint does

The fastest path is `apiName:` lookup when you already know the endpoint
operation ID (e.g. `searchMetadata`, `exportMetadataTML`, `importMetadataTML`,
`fetchPermissionsOnMetadata`, `deleteMetadata`). If you don't know the name,
run a `query:` search first, find the operation ID in the result, then re-query
by `apiName:` for the full spec.

---

## When live testing is the right answer

The MCP gives you the spec; the live instance gives you build-specific reality.
Test live when **any** of these are true:

- The MCP confirms an endpoint exists but a specific build returns 500 or a
  different shape (this is a build/version issue, not a spec issue —
  ts-dependency-manager open items #15, #18 are examples)
- The behaviour you need to verify is operational (timing, concurrency, cache
  invalidation, rollback ordering — open item #16)
- Permission, RLS, or sharing behaviour where the spec is silent on edge cases
- The skill needs to confirm a TML round-trip preserves a specific field

In these cases, the open-items.md entry should record: (a) what the MCP says,
(b) what the live test showed, (c) the divergence. Do not file an open-item
without first checking the MCP — most "is this endpoint documented?" questions
are answerable in 30 seconds.

---

## Documenting MCP findings

When MCP research resolves a question, record it in the same place a live-test
finding would go. The format is the same:

```markdown
## #N — Topic — VERIFIED via MCP YYYY-MM-DD

Verified against `get-rest-api-reference(apiName: "deleteMetadata")` on
{date}. Spec confirms:
- Request body: `{"metadata": [{"identifier": guid, "type": <type>}]}`
- 204 No Content on success
- `type` is required (matches the empirical finding in this open-item)
```

This keeps `open-items.md` honest about *how* an item was resolved — spec read,
live test, or both — and makes it easy to spot items that should be re-checked
on a newer build.

---

## What NOT to use the MCP for

- **Credential or auth secret values** — the MCP returns spec, never live tokens.
  Auth flow patterns belong in `ts-profile-thoughtspot/SKILL.md`.
- **TML file format details** — `agents/shared/schemas/thoughtspot-*-tml.md`
  is the authoritative source. These were derived from real import failures
  and capture invariants the spec doesn't surface (see CLAUDE.md "Critical TML
  invariants"). MCP queries about TML shape may contradict the schemas — trust
  the schemas, not the MCP, when they disagree.
- **Snowflake-side behaviour** — out of scope. Use Snowflake docs directly.
- **In-skill runtime decisions** — skills should call `ts` CLI, not the MCP,
  during execution. The MCP is a research/authoring tool; the CLI is the
  runtime tool. Mixing them adds complexity without benefit.

---

## Hooking this into existing rules

| Rule file | Relevant section | What it does |
|---|---|---|
| `agents/claude/CLAUDE.md` — "open-items.md pattern" | Add MCP-first step before filing an open-item |
| `.claude/rules/ts-cli.md` — "v1 API migration trigger" | Replace "REST Playground" with `get-rest-api-reference` |
| `.claude/rules/ts-cli.md` — "When a skill needs an API call ts-cli doesn't have yet" | Add: query MCP for the spec before writing the open-items.md test script |

If you find yourself writing "I should test this against staging to find out
what shape the response is", stop — query the MCP first.
