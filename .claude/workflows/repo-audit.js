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

const scope = (args && args.scope) === 'full' ? 'full' : 'external'

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
const INTERNAL_ANGLES = [
  { key: 'dead-files', n: 1, prompt: 'Find legacy/dead files: untracked build artifacts, orphaned directories, files referenced nowhere, stale docs. Use git + grep.' },
  { key: 'tools-quality', n: 4, prompt: 'Review tools/ (ts-cli, validate, smoke-tests) for code health: dead code, missing error handling, duplicated logic, brittle parsing.' },
  { key: 'ts-cli-gaps', n: 5, prompt: 'Find operations skills need but the ts CLI lacks, and any inline `requests` calls in agents/cli/ SKILL.md files (anti-pattern per .claude/rules/ts-cli.md).' },
  { key: 'testing-value', n: 6, prompt: 'Assess whether tests assert real behaviour vs presence-only; whether smoke tests exercise meaningful paths. Name weak/missing coverage by file.' },
  { key: 'pr-validation', n: 7, prompt: 'Compare scripts/pre-commit.sh against .github/workflows/validate.yml: any gate that runs in one but not the other, or is bypassable. Read both.' },
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

// ── run ─────────────────────────────────────────────────────────────────────

phase('Survey')
const platformCount = PLATFORMS.length
const internalCount = scope === 'full' ? INTERNAL_ANGLES.length : 0
log(`repo-audit: scope=${scope} — ${platformCount} platform specialists + performance + dependency${scope === 'full' ? ` + ${internalCount} internal angles` : ''}`)

const finders = []

// Angle 13 — per platform
for (const p of PLATFORMS) {
  finders.push(() => agent(platformPrompt(p), { label: `currency:${p.key}`, phase: 'Survey', schema: FINDINGS_SCHEMA }))
}
// Angle 14, 16 — always part of the external sweep
finders.push(() => agent(PERF_PROMPT, { label: 'performance', phase: 'Survey', schema: FINDINGS_SCHEMA }))
finders.push(() => agent(DEPS_PROMPT, { label: 'dependencies', phase: 'Survey', schema: FINDINGS_SCHEMA }))
// Internal angles — full scope only
if (scope === 'full') {
  for (const a of INTERNAL_ANGLES) {
    finders.push(() => agent(internalPrompt(a), { label: `internal:${a.key}`, phase: 'Survey', schema: FINDINGS_SCHEMA }))
  }
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
  'Produce `report_md`: a markdown report matching the structure of docs/audit/2026-06-17-full.md',
  '(Verdict, a findings→outcome table with a suggested bucket per row, and a Follow-ups section).',
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
