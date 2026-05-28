# `ts metadata report` — Design Spec

**Date:** 2026-05-28
**Author:** damian.waldron@thoughtspot.com (with Claude)
**Status:** Draft — awaiting user review

---

## 1. Problem

ThoughtSpot users frequently need to answer one question before making any change to a column, table, or model: **"What depends on this, and how risky is touching it?"**

Today the only path is `/ts-dependency-manager` Audit mode, which is interactive (multi-step skill conversation), couples audit to mutation flows (the same skill that audits also removes and repoints), and re-implements the dep walk inline in `SKILL.md`. There is no way to:

- Run the audit non-interactively from a shell, CI job, or another skill
- Get a stable JSON contract for the dep graph that other skills can consume
- Surface column-level sharing, column alias TML, and Spotter AI-surface signals (currently scattered, partially documented, or hand-rolled in the skill)
- Produce shareable markdown output for Jira / Slack / PRs

This work adds a new CLI command, `ts metadata report`, that owns the pure data-and-classification side of dependency inspection. The existing `ts-dependency-manager` skill consumes it for Audit mode and reuses it inside the Remove / Repoint workflow steps.

## 2. Goals and non-goals

**Goals**
- One-shot, non-interactive dependency audit from the shell
- Stable JSON contract for skill orchestration
- Coverage parity with — and several gains beyond — today's skill Audit mode
- Three output formats: JSON (default), text (terminal), markdown (sharing)
- Risk classification + recommended action per source
- Name-or-GUID input with auto-detection

**Non-goals**
- Replacing the skill's interactive Remove / Repoint workflow (those keep the scope picker, per-viz decisions, TML backup, ALL_OR_NONE import, and rollback)
- Cross-system audit (Snowflake/Databricks query history) — deferred to v2
- `report-diff` mode — deferred; JSON contract is stable enough to add later
- Rename mode — already excluded from the skill (see SKILL.md prior decision)

## 3. Architecture

### Module layout

```
tools/ts-cli/ts_cli/
├── commands/
│   └── metadata.py
│       └── @app.command("report")        # thin Typer wrapper, ~80 lines
├── report/                                # new package
│   ├── __init__.py                        # exports build_report()
│   ├── resolver.py                        # name/GUID → typed source descriptor
│   ├── walker.py                          # per-source-type dep walk
│   ├── tml_probes.py                      # TML pulls: RLS, alerts, aliases, AI-surface
│   ├── classifier.py                      # risk + recommended-action rules
│   ├── formatters.py                      # JSON / text-tree / markdown
│   └── schema.py                          # dataclasses for the JSON contract
└── tests/
    ├── test_report_resolver.py
    ├── test_report_walker.py
    ├── test_report_classifier.py
    └── test_report_formatters.py
```

Public entry points:

```python
def build_report(source_ref: str, *, profile: str, with_deep: bool = True) -> dict:
    """Single source: resolve → walk → probe → classify → return one report dict."""

def build_reports(source_refs: list[str], *, profile: str, with_deep: bool = True) -> dict:
    """Multi-source: returns {"schema_version": "1.0", "reports": [report, ...]}.
    Each report has the same single-source shape; failures carry "error" instead of "dependents"."""
```

The CLI command is a thin wrapper that picks single vs multi based on argument count, calls the appropriate entry point, and dispatches to the requested formatter. No new HTTP client; everything routes through the existing `ThoughtSpotClient`.

### Separation of concerns vs the skill

| Layer | Owned by | Why |
|---|---|---|
| Source resolution, dep walk, TML probes, classification | `ts metadata report` (CLI) | Pure function. No state. No interactivity. Unit-testable. |
| Mode picker (Audit / Remove / Repoint), scope picker (column / column set / whole object) | `ts-dependency-manager` skill | Interactive UX. |
| Per-viz decisions (REMOVE_CHART vs CONVERT_TO_TABLE) | `ts-dependency-manager` skill | Requires user judgment. |
| TML backup, ALL_OR_NONE import, post-import verify, rollback | `ts-dependency-manager` skill | Stateful workflow. |
| Risk classification rules | CLI (`report/classifier.py`) | Pure rules, consumed verbatim by skill. |

## 4. CLI surface

```
ts metadata report <SOURCE> [<SOURCE> ...]
                  [--profile <name>]
                  [--format json|text|md]            (default: json)
                  [--fast]                            (skip TML probes; v2 API only)
                  [--with-acls / --no-acls]          (default: with-acls)
                  [--out <path>]                     (write to file)
                  [--depth N]                         (default: 3)
                  [--dormant-days N]                 (threshold for dormant tag; default 180)
                  [--no-color]                        (text format only)
```

Dormancy is a signal the classifier uses to choose LOW vs MEDIUM — all dependents are always included regardless. `--dormant-days` tunes the threshold; it does not gate inclusion.

### Source resolution (auto-detect)

| Input | Interpreted as |
|---|---|
| 36-char UUID | GUID → metadata search resolves type |
| `DB.SCHEMA.TABLE` | three-part → LOGICAL_TABLE |
| `DB.SCHEMA.TABLE.COLUMN` | four-part → LOGICAL_COLUMN |
| `ModelName` | name → LOGICAL_TABLE subtype WORKSHEET; ambiguity = error with candidates |
| `ModelName.column` | two-part → column on a Model |

Ambiguity → exit code 2, structured JSON to stderr listing candidates with GUID + owner + modified date.

### Examples

```bash
# Three-part name
ts metadata report EDUCATION_BUSINESS.EDUCATION_BUSINESS.UNIVERSITY_FACULTY \
    --profile SpotterAccuracy --format text

# Column-scoped audit
ts metadata report DB_IMDB.DB_IMDB.MOVIE.num_votes \
    --profile SpotterAccuracy --format text

# Markdown for sharing
ts metadata report <guid> --profile SpotterAccuracy --format md --out audit.md

# Skill-side use (JSON contract)
ts metadata report <guid> --profile <name> --format json --fast

# Multi-source batch
ts metadata report <src1> <src2> <src3> --profile <name> --format md --out bulk.md
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Report written successfully |
| 1 | Auth / network failure |
| 2 | Source unresolvable (ambiguous or no match) |
| 3 | Multi-source: some succeeded, some failed |

## 5. Coverage matrix (v1)

| Dependency type | Source | Coverage |
|---|---|---|
| Models / Worksheets / Views | v2 dependents API | Auto |
| Answers / Liveboards | v2 dependents API | Auto |
| Sets / Cohorts | v2 dependents API (type=LOGICAL_COLUMN) | Auto |
| Spotter feedback | v2 dependents API (FEEDBACK bucket) | Auto |
| Joins | `metadata_detail.relationships` (free; no extra call) | Auto |
| RLS rules (on table) | Table TML `rls_rules` | Auto |
| Monitor alerts | Liveboard `--associated` (`monitor_alert` doc) | Auto |
| Inline aliases (table / model / view) | Standard TML export | Auto |
| Column-level sharing (ACLs) | `POST /api/rest/2.0/security/metadata/fetch-permissions` (type=LOGICAL_COLUMN) | Auto, informational |
| Column alias TML (Mechanism 2) | `export_options.export_with_column_aliases: true` (10.13.0.cl+ Beta) | Auto (verified on SpotterAccuracy 2026-05-28) |
| Spotter AI surface area (DMI / synonyms / refs) | Model TML inspection | Auto |
| **CSR (column_security_rules)** | `export_options.export_column_security_rules` (10.12.0.cl+ Beta) | **Deferred — cluster feature gate; tracked under open-item #9** |

### Cluster build pre-flight

When TML probes are enabled (default — not `--fast`), the CLI sniffs cluster build via a lightweight metadata call. If the cluster is below the version that supports a Beta flag, the corresponding probe degrades to `not_checked` in the report's coverage block with a reason — instead of erroring.

## 6. JSON contract (schema_version "1.0")

### Single source

```jsonc
{
  "schema_version": "1.0",
  "walked_at": "2026-05-28T14:23:01Z",
  "profile": "SpotterAccuracy",
  "source": {
    "input": "DB_IMDB.DB_IMDB.MOVIE.num_votes",
    "guid": "6645d2b5-...",
    "type": "LOGICAL_COLUMN",
    "name": "num_votes",
    "parent": { "guid": "4b891a59-...", "name": "DB_IMDB.DB_IMDB.MOVIE", "type": "LOGICAL_TABLE" }
  },
  "dependents": [
    {
      "guid": "...",
      "name": "...",
      "type": "LOGICAL_TABLE",
      "subtype": "WORKSHEET",
      "via": "v2_dependents",
      "hops": 1,
      "owner": { "id": "...", "display_name": "Administrator" },
      "modified_at": "2026-03-17T...",
      "risk": { "tag": "LOW", "reason": "Dormant Model; no consumers" }
    }
  ],
  "coverage": [
    { "type": "Models", "checked": true, "found": 1 },
    { "type": "Answers", "checked": true, "found": 0 },
    { "type": "RLS rules on table", "checked": true, "found": 0 },
    { "type": "Monitor alerts", "checked": true, "found": 0 },
    { "type": "Column ACLs", "checked": true, "found": 0, "informational": true },
    { "type": "Column alias TML", "checked": true, "found": 0 },
    { "type": "CSR (column_security_rules)", "checked": false, "reason": "feature not enabled on cluster" }
  ],
  "classification": {
    "per_dependent": [ /* same risk objects as inline */ ],
    "aggregate": { "tag": "LOW", "recommendation": "REVIEW_RECOMMENDED" }
  },
  "warnings": []
}
```

### Multi-source

```jsonc
{
  "schema_version": "1.0",
  "walked_at": "2026-05-28T14:23:01Z",
  "profile": "SpotterAccuracy",
  "reports": [
    { /* single-source shape */ },
    { /* single-source shape */ },
    { "source": { "input": "...", ... }, "error": "Source unresolvable", "candidates": [...] }
  ]
}
```

Schema versioned so future shape changes are explicit. Consumers MUST check `schema_version` prefix. Both shapes share the same major version; consumers detect single vs multi by presence of `source` (single) or `reports` (multi) at root.

## 7. Risk classification

Tags apply at the **dependent** level. The classifier inspects each dependent's TML (already exported during the walk) and computes the tag based on how that dependent references the source.

- When source is a **column**: rules below apply directly — "charts use it on axis" means *this column* is on the axis.
- When source is a **table or Model**: the rule fires if *any column on the source* is referenced in the corresponding way. The reason string identifies which column triggered the tag (e.g., `"chart uses 'num_votes' on Y axis"`).

| Tag | Condition |
|---|---|
| `SAFE` | Zero dependents; no RLS, no alerts, no Spotter feedback, no aliases |
| `LOW` | Dependents exist but only auto-Models / dormant dependents (modified > `--dormant-days`) / informational signals (aliases, ACLs); no charts use source column(s) on axis |
| `MEDIUM` | Active (non-dormant) Answers/Liveboards reference source; charts use source column(s) on color/size/shape; alerts filter on source column(s); Spotter feedback references source column(s) |
| `HIGH` | Charts use source column(s) on x or y axis; model-level filters reference source column(s); join conditions reference source column(s) |
| `STOP` | RLS rule on this table or joined table references source column(s); CSR rule references source column(s) (when cluster supports CSR) |

### Aggregate recommendation

| Max per-dependent tag | Recommendation |
|---|---|
| All SAFE | `SAFE_TO_DROP` |
| LOW | `REVIEW_RECOMMENDED` |
| MEDIUM | `PLAN_REQUIRED` (points to `/ts-dependency-manager` Remove mode) |
| HIGH | `PLAN_REQUIRED_WITH_PER_VIZ_DECISIONS` |
| Any STOP | `BLOCKED_RESOLVE_RLS_FIRST` |

The classifier is a pure function: `(walk_result) → (per_dep_risks, aggregate)`. Unit-testable without a live instance.

## 8. Formatters

Each formatter is a function on the `Report` dataclass.

**JSON** (default) — the schema in section 6, stable contract.

**Text** — tree first, coverage matrix second, aggregate recommendation third. ANSI color on TTY; `--no-color` flag. Wraps to terminal width.

**Markdown** — same content as text, but ASCII tree in a fenced code block and coverage as a markdown table. Designed for pasting into Jira/Slack/PRs.

New formatters (HTML, Confluence) can be added without touching existing three.

## 9. Integration with `ts-dependency-manager`

### Today

Audit mode = Steps 4 (walk) + 5 (render impact report) of the skill. Both implemented inline in SKILL.md as ~150 lines of Python.

### After this PR

Audit mode = `ts metadata report <source> --profile <name> --format json` + skill renders the markdown output for the user. Remove and Repoint flows use the same call for the walk; Steps 6–11 (per-viz decisions, backup, apply, rollback) are unchanged.

The skill gains for free: column ACLs, column alias TML, joins coverage, Spotter AI surface area, risk + recommended-action classification.

## 10. Companion updates to ship in the same PR

| File / artifact | Change |
|---|---|
| `agents/cli/ts-dependency-manager/SKILL.md` | Update `description:` frontmatter (remove "rename", add "audit"); Step 0 narrative; Step 2 mode picker (add CLI aside); Step 4 (replace inline walk with CLI call); Step 5 (replace inline render with CLI markdown); References table (add design doc + CLI README rows); Changelog entry |
| `agents/cli/ts-dependency-manager/references/dependency-types.md` | Status column updates: #7 (Monitor alert) and #8 (RLS rule) move from "Implementable (skill-side hand-roll)" to "Implementable (auto via `ts metadata report`)"; #11 (Inline alias) becomes "Implementable (full)" |
| `agents/cli/ts-dependency-manager/references/open-items.md` | #5 closes; #10 closes (alias TML retrieval verified via `export_with_column_aliases` Beta flag on SpotterAccuracy 2026-05-28); #19 closes (multi-source mode covers it); #21 partially closes (risk + recommendation free; "jump into matching flow" still deferred); #9 (CSR) stays open with note that API path exists, gated on cluster config; new entry #22 opens to track the smoke test for `ts metadata report` until verified |
| `agents/cursor/rules/ts-dependency-manager.mdc` | Condensed mirror of SKILL.md edits; untested-in-Cursor disclaimer retained |
| `tools/smoke-tests/smoke_ts-dependency-manager.py` | Update Audit assertions for new CLI-call shape; assert markdown render present |
| `tools/smoke-tests/smoke_ts-metadata-report.py` (new) | Live CLI smoke against a stable test fixture on SpotterAccuracy; asserts schema_version, source, classification.aggregate |
| `tools/ts-cli/__init__.py` + `pyproject.toml` | Version bump (MINOR — additive subcommand). Bump at PR time, not during wip |
| `tools/ts-cli/README.md` | New command entry |
| `CHANGELOG.md` | Repo-level entry: `feat: add ts metadata report command + audit-mode rewrite` |

### Skill name review

Kept `ts-dependency-manager` (matches the `ts-dependency-*` family rule, covers audit + remove + repoint, no semantic gain from rename, would force MAJOR bump).

## 11. Error handling

| Failure | Behavior |
|---|---|
| Profile not found / auth fails | Exit 1; error to stderr |
| Source unresolvable | Exit 2; JSON to stderr with candidates if ambiguous |
| Single sub-call fails (TML export, fetch-permissions) | Continue; mark that section `"error": "..."`; never abort whole report |
| Multi-source: one source fails | Continue with others; exit 3 at end; failed source carries `"error"` field |
| Beta flag rejected by older cluster | 400 detected; probe degrades to `not_checked` with reason |

## 12. Test plan

### Unit (no live instance)

```
tests/test_report_resolver.py     — UUID, 3-part, 4-part, ambiguous-name, no-match
tests/test_report_walker.py       — Table source 1-hop and 2-hop; Column source
tests/test_report_classifier.py   — SAFE/LOW/MEDIUM/HIGH/STOP fixtures; aggregate rule
tests/test_report_formatters.py   — JSON schema validity; text tree+matrix; md parses
```

### Smoke (live, staging)

`tools/smoke-tests/smoke_ts-metadata-report.py`:
- Calls `ts metadata report <stable-test-guid> --profile SpotterAccuracy --format json`
- Asserts: `schema_version == "1.0"`, `source.guid` matches, `classification.aggregate.tag` ∈ valid set
- Asserts: expected dependent count for the test fixture (drift detection)

`tools/smoke-tests/smoke_ts-dependency-manager.py` gains: assertion that Audit mode produces non-empty report and parses CLI JSON correctly.

## 13. Deferred to v2 (or later)

- Snowflake / Databricks warehouse query-history sweep (cross-system audit)
- `ts metadata report-diff before.json after.json` (orphan detection after change)
- `--column "fac*"` wildcard expansion
- CSR (column_security_rules) full coverage — gated on cluster feature enablement
- Recommendation engine "jump directly into matching skill flow" (open-item #21 final piece)

## 14. Open questions

- None at design time. All ambiguities were resolved during brainstorming.

## 15. Implementation notes

- Versioning: do NOT bump ts-cli or skill version on the feature branch. Bump at PR time per `.claude/rules/versioning.md`.
- Branch: this work must land on `feat/ts-metadata-report` (or similar `feat/*`), not on `wip/databricks` or `wip/model-builder`. The wip branches are scoped to unrelated work; merging this in would violate branch protocol.
- Pre-commit hooks (`check_skill_versions.py`, `check_runtime_coverage.py`, `check_consistency.py`, `check_smoke_tests.py`) must all pass before PR open. Plan includes running them locally.
- MCP-first rule applies for any further endpoint research during implementation: query `SpotterCode get-rest-api-reference` before live testing.
