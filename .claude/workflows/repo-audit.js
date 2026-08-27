export const meta = {
  name: 'repo-audit',
  description: 'Run a repo audit sweep (external product-currency/perf/deps, or full) and synthesise a prioritised report',
  whenToUse: 'When check_audit_freshness nudges that a sweep is due. args: {scope: "external" | "full"}. See .claude/rules/repo-audit.md.',
  phases: [
    { title: 'Survey', detail: 'one agent per angle (and per platform for product-currency)' },
    { title: 'Synthesize', detail: 'dedup, prioritise, route each finding to a bucket' },
  ],
}

// ── config (repo-specific — mirrors the angle/platform tables in repo-audit.md) ──

// args may arrive as an object ({scope:"full"}) or a JSON-ish string depending on the
// caller — accept both (verified 2026-07-03: an object arg reached the script as a string
// and silently fell back to 'external').
const scope = (typeof args === 'string' ? args.includes('full') : args && args.scope === 'full') ? 'full' : 'external'

// Angle 13 — one specialist lens per platform. Each reads the real mapping/schema
// files + their currency anchor, researches the product's CURRENT state, and reports
// assumptions that are now obsolete / newly-possible / wrong.
const PLATFORMS = [
  {
    key: 'thoughtspot', label: 'ThoughtSpot',
    research: 'Use the SpotterCode MCP for current API/feature state: load it via ToolSearch "select:mcp__SpotterCode__get-rest-api-reference,mcp__SpotterCode__get-developer-docs-reference" then query it.',
    areas: ['agents/shared/schemas/ (thoughtspot-*.md, thoughtspot-chart-types.md)', 'the ThoughtSpot side of agents/shared/mappings/*/'],
  },
  {
    key: 'snowflake', label: 'Snowflake',
    research: 'Use WebSearch / WebFetch (load via ToolSearch) against current Snowflake docs (semantic views, Cortex Analyst, SQL functions).',
    areas: ['agents/shared/mappings/ts-snowflake/', 'agents/shared/schemas/snowflake-schema.md'],
  },
  {
    key: 'databricks', label: 'Databricks',
    research: 'Use WebSearch / WebFetch against current Databricks docs (metric views, Genie, SQL functions).',
    areas: ['agents/shared/mappings/ts-databricks/', 'agents/shared/schemas/databricks-metric-view.md'],
  },
  {
    key: 'tableau', label: 'Tableau',
    research: 'Use WebSearch / WebFetch against current Tableau docs (calc functions, table calcs, LOD, set/parameter behaviour).',
    areas: ['agents/shared/mappings/tableau/'],
  },
]

// Angles that are MANUAL in the rubric and re-examined only on a full sweep (the rest
// are continuous validators — no point re-running them here).
// `effort` tiers the finder's reasoning cost (.claude/rules/model-routing.md): 'low' for
// mechanical grep/diff-shaped angles; omit for angles that need real judgment.
const INTERNAL_ANGLES = [
  { key: 'dead-files', n: 1, effort: 'low', prompt: 'Find legacy/dead files: untracked build artifacts, orphaned directories, files referenced nowhere, stale docs. Use git + grep.' },
  { key: 'tools-quality', n: 4, prompt: 'Review tools/ (ts-cli, validate, smoke-tests) for code health: dead code, missing error handling, duplicated logic, brittle parsing.' },
  { key: 'ts-cli-gaps', n: 5, prompt: 'Find operations skills need but the ts CLI lacks, and any inline `requests` calls in agents/cli/ SKILL.md files (anti-pattern per .claude/rules/ts-cli.md).' },
  { key: 'testing-value', n: 6, prompt: 'Assess whether tests assert real behaviour vs presence-only; whether smoke tests exercise meaningful paths. Name weak/missing coverage by file.' },
  { key: 'pr-validation', n: 7, effort: 'low', prompt: 'Compare scripts/pre-commit.sh against .github/workflows/validate.yml: any gate that runs in one but not the other, or is bypassable. Read both.' },
  { key: 'codification', n: 11, prompt: 'Find repeated skill logic across agents/cli/*/SKILL.md that should become a ts CLI command, a shared reference, or a validator.' },
]

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    angle: { type: 'string' },
    area: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          title: { type: 'string' },
          detail: { type: 'string' },
          file: { type: 'string' },
          suggested_bucket: { type: 'string', enum: ['validator', 'backlog', 'mapping-update', 'none'] },
        },
        required: ['severity', 'title', 'detail', 'suggested_bucket'],
      },
    },
  },
  required: ['angle', 'findings'],
}

const REPORT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    summary: { type: 'string' },
    counts: {
      type: 'object',
      additionalProperties: false,
      properties: { high: { type: 'integer' }, medium: { type: 'integer' }, low: { type: 'integer' } },
      required: ['high', 'medium', 'low'],
    },
    report_md: { type: 'string', description: 'Full markdown report ready to save under docs/audit/' },
  },
  required: ['summary', 'counts', 'report_md'],
}

// ── prompts ─────────────────────────────────────────────────────────────────

const GROUNDING =
  'Ground every finding in a real file you have READ — include the path in `file`. ' +
  'Do NOT invent product changes; if you cannot verify a change, omit it or mark severity "low". ' +
  'If the current mappings are still accurate, return an EMPTY findings array — that is a valid, good result. ' +
  'suggested_bucket: "validator" if a check could prevent recurrence, "mapping-update" if a shared mapping/schema needs editing, ' +
  '"backlog" if it needs real work (a dated BL-NNN), "none" for FYI.'

function platformPrompt(p) {
  return [
    `You are a ${p.label} product specialist auditing this repo's cross-platform assumptions (audit angle 13 — product currency).`,
    `Read the relevant files first: ${p.areas.join('; ')}.`,
    'Read each file\'s currency anchor (`<!-- currency: ... — YYYY-MM ... -->`); that is when the mapping was last validated.',
    `Then check what has changed in ${p.label} SINCE that date. ${p.research}`,
    `Report assumptions that are now: (a) obsolete (a construct deprecated/removed), (b) newly-possible (something we mark "untranslatable" that now has a native equivalent), or (c) simply wrong against the current product.`,
    'The Muze charting library and the v1-endpoint removal are the canonical examples of what this catches.',
    GROUNDING,
    `Set angle="13 product-currency" and area="${p.label}".`,
  ].join('\n')
}

const PERF_PROMPT = [
  'Audit performance (angle 14) across three sub-areas. Read real files.',
  '(a) Skill runtime: redundant API round-trips, un-batched user prompts, missing single-pass parsing, the obj_id read-back pattern — scan agents/cli/*/SKILL.md.',
  '(b) Generated-artifact efficiency: do the conversion mappings emit performant ThoughtSpot constructs (group_aggregate vs sql_*_aggregate_op pass-through, join cardinality, COUNT_DISTINCT handling)? Check agents/shared/mappings/.',
  '(c) ts-cli: pagination, token-cache reuse, connection-introspection cost — check tools/ts-cli/ts_cli/.',
  GROUNDING,
  'Set angle="14 performance".',
].join('\n')

// Angle 18 — the framework audits itself: the Claude harness config checked against
// the current Claude Code + model lineup. Same pattern as angle 13, pointed inward.
const HARNESS_PROMPT = [
  'Audit harness / framework currency (angle 18). The quality framework goes stale the same way product mappings do.',
  'Read the real files first: .claude/settings.json; .claude/agents/*.md (frontmatter); .claude/workflows/*.js; .claude/rules/model-routing.md and any other .claude/rules/*.md with a currency anchor; the harness-related parts of CLAUDE.md.',
  'Then check them against the CURRENT state of Claude Code and the Claude model lineup. Use WebSearch / WebFetch (load via ToolSearch) against the official Claude Code docs and Anthropic model documentation.',
  'Report: (a) stale model pins or tier assignments that no longer match the lineup (the canonical example: a pinned claude-opus-4-6 sat in settings.json after the Claude 5 family shipped); (b) new harness capabilities (settings, hooks, agent/workflow options) the repo should adopt; (c) rules files whose anchors are stale or whose claims no longer match how the harness behaves; (d) documented flows that contradict observed behaviour.',
  GROUNDING,
  'Set angle="18 harness-currency".',
].join('\n')

const DEPS_PROMPT = [
  'Audit dependency / supply-chain currency (angle 16). Read tools/ts-cli/pyproject.toml and any requirements files.',
  'Report: unpinned or over-broad version ranges, dependencies with known CVEs, EOL Python versions, anything materially out of date.',
  'Prefer suggested_bucket "validator" (e.g. a future pip-audit gate) or "backlog".',
  GROUNDING,
  'Set angle="16 dependency-currency".',
].join('\n')

function internalPrompt(a) {
  return [
    `Audit internal angle ${a.n} (${a.key}). ${a.prompt}`,
    'This is the deep full-sweep re-examination of an angle that is otherwise manual (the automated angles are covered by validators — do not re-do their work).',
    GROUNDING,
    `Set angle="${a.n} ${a.key}".`,
  ].join('\n')
}

// Angle 17 — the max /code-review backstop over the delta since the last full audit.
// Full scope only, delta-scoped, confidence-filtered. Per-PR /code-review is the primary
// net; this catches what slipped through. See repo-audit.md "Angle 17".
const CODE_REVIEW_PROMPT = [
  'You are performing a deep, `max`-effort code review — audit angle 17 (change correctness).',
  'This is the full-sweep BACKSTOP for behavioural bugs that slipped past per-PR review; it is NOT a code-health pass (that is angle 4).',
  '',
  'SCOPE — review only the delta since the last full audit:',
  '  1. Find the most recent full-audit report: `ls docs/audit/*-full.md | tail -1`.',
  '  2. Get the commit it was written at: `git log -1 --format=%H -- <that file>`.',
  '  3. Review the diff `<sha>..HEAD` (`git diff <sha>..HEAD` + `git log <sha>..HEAD`).',
  '  If no full-audit report exists, review the last 40 commits (`git diff HEAD~40..HEAD`).',
  '',
  'METHOD — across the changed code, hunt for:',
  '  - real correctness bugs (wrong logic, unhandled edge cases, off-by-one, error-swallowing);',
  '  - violations of the root CLAUDE.md and .claude/rules/*.md (read the ones relevant to the changed files);',
  '  - regressions visible from git history / prior PR context on the same lines.',
  'Adversarially verify each candidate before reporting it. Report ONLY findings you are highly confident are real.',
  'IGNORE (these are false positives for this angle): nitpicks and style; anything a linter/typechecker/CI would catch; pre-existing issues; issues on lines the delta did not modify; general quality/coverage gaps (those are angles 4/6).',
  '',
  GROUNDING,
  'For each finding, prefer suggested_bucket "backlog" (a dated BL-NNN or fix PR) for a one-off bug, or "validator" if a check_*.py could prevent the whole CLASS from recurring.',
  'Set angle="17 change-correctness". A clean review (empty findings array) is a valid, good result.',
].join('\n')

// ── run ─────────────────────────────────────────────────────────────────────

phase('Survey')
const platformCount = PLATFORMS.length
const internalCount = scope === 'full' ? INTERNAL_ANGLES.length : 0
log(`repo-audit: scope=${scope} — ${platformCount} platform specialists + performance + dependency + harness${scope === 'full' ? ` + ${internalCount} internal angles + max /code-review over the delta` : ''}`)

const finders = []

// Angle 13 — per platform
for (const p of PLATFORMS) {
  finders.push(() => agent(platformPrompt(p), { label: `currency:${p.key}`, phase: 'Survey', schema: FINDINGS_SCHEMA }))
}
const CONVERSION_PROMPT = `Audit conversion consistency across EVERY converter (angle 9).

Follow your agent instructions: discover the converter set and the invariant set at run
time — do not work from any list in this prompt, which would go stale the same way the
agent's own list did.

Report findings in two classes:
1. SEMANTIC — a converter that violates, contradicts or fails to state an invariant
   declared in agents/shared/schemas/ts-model-conversion-invariants.md.
2. IMPLEMENTATION DRIFT — a converter that re-implements a shared correctness helper
   instead of importing it, skips one its shape requires, emits a construct a sibling
   emits differently, or hand-instructs in prose what a sibling codified.

For each finding give file:line, the invariant id (or helper name) and the concrete
wrong output it produces. A finding a validator could mechanically catch should be
reported as a validator candidate, not as prose.`

// Angle 14, 16 — always part of the external sweep
finders.push(() => agent(PERF_PROMPT, { label: 'performance', phase: 'Survey', schema: FINDINGS_SCHEMA }))
// Dependency currency is mechanical (read pyproject, check advisories) — low effort suffices.
finders.push(() => agent(DEPS_PROMPT, { label: 'dependencies', phase: 'Survey', schema: FINDINGS_SCHEMA, effort: 'low' }))
// Angle 18 — always part of the external sweep
finders.push(() => agent(HARNESS_PROMPT, { label: 'harness-currency', phase: 'Survey', schema: FINDINGS_SCHEMA }))
// Internal angles — full scope only
if (scope === 'full') {
  for (const a of INTERNAL_ANGLES) {
    finders.push(() => agent(internalPrompt(a), { label: `internal:${a.key}`, phase: 'Survey', schema: FINDINGS_SCHEMA, ...(a.effort ? { effort: a.effort } : {}) }))
  }
  // Angle 9 — conversion consistency. Runs the dedicated auditor agent rather than a
  // generic finder: its judgment half (semantic invariants + cross-converter
  // implementation drift) is not covered by any validator, so before 2026-08-26 it ran
  // NOWHERE — not per-PR, not in the sweep — and the rubric's enforcement column for
  // this angle was fiction. The agent discovers its own scope, so a new converter is
  // audited from its first commit with no edit here.
  finders.push(() => agent(CONVERSION_PROMPT, { label: 'conversion-consistency', phase: 'Survey', schema: FINDINGS_SCHEMA, agentType: 'conversion-consistency-auditor' }))
  // Angle 17 — max /code-review backstop over the delta (full scope only).
  finders.push(() => agent(CODE_REVIEW_PROMPT, { label: 'code-review:delta', phase: 'Survey', schema: FINDINGS_SCHEMA, effort: 'max' }))
}

// Barrier: synthesis genuinely needs ALL findings together (dedup + prioritise).
const surveyed = (await parallel(finders)).filter(Boolean)
const allFindings = surveyed.flatMap((r) => (r.findings || []).map((f) => ({ ...f, angle: r.angle, area: r.area || '' })))

log(`survey complete: ${allFindings.length} raw finding(s) from ${surveyed.length} agent(s)`)

phase('Synthesize')
const synthPrompt = [
  `Synthesise a repo-audit report (scope=${scope}). Here are the raw findings as JSON:`,
  '```json',
  JSON.stringify(allFindings, null, 2),
  '```',
  'Deduplicate overlapping findings, prioritise by severity then blast-radius, and group by angle.',
  'Write the full report as the literal markdown TEXT value of the `report_md` output field — the',
  'actual report body (Verdict, a findings→outcome table with a suggested bucket per row, and a',
  'Follow-ups section), matching the structure of docs/audit/2026-06-17-full.md. Never output a',
  'placeholder, token, or variable name in place of that text — write the real content.',
  'Leave the date out of any filename references — the operator stamps it when saving.',
  'Set `counts` to the deduped totals by severity. Keep `summary` to 2-3 sentences.',
  'If there are zero findings, say so plainly — a clean sweep is a valid outcome.',
].join('\n')

const report = await agent(synthPrompt, { label: 'synthesis', phase: 'Synthesize', schema: REPORT_SCHEMA })

return {
  scope,
  raw_findings: allFindings,
  summary: report.summary,
  counts: report.counts,
  report_md: report.report_md,
  // The operator saves report_md to docs/audit/<YYYY-MM-DD>-<scope>.md and routes each
  // finding to a validator-PR or a dated BL-NNN (workflows cannot write files).
}
