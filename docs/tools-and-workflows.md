# Tools & Workflows Reference

A complete catalog of every tool, skill, validator, and script in the
`thoughtspot-agent-skills` repo — what each does, when to use it, and how
the pieces fit together.

---

## 1. ThoughtSpot CLI (`ts`)

**Location:** `tools/ts-cli/`
**Install:** `pip install -e tools/ts-cli`

A lightweight Python CLI wrapping the ThoughtSpot REST API. Every Claude Code
and Cortex Code CLI skill uses this for all ThoughtSpot API calls — skills
never call `requests` directly.

### Command Reference

#### Authentication & Profiles

| Command | What it does |
|---|---|
| `ts profiles list` | List all configured ThoughtSpot profiles (credentials never shown) |
| `ts auth whoami` | Verify authentication, print current user details (JSON) |
| `ts auth token` | Print the current bearer token (for debugging / piping) |
| `ts auth logout` | Clear the cached token so the next command re-authenticates |

**Workflow:** Run `ts auth whoami --profile <name>` to confirm a profile works
before running any skill. If auth fails, use the `ts-profile-thoughtspot`
skill to reconfigure credentials.

---

#### Metadata Operations

| Command | What it does |
|---|---|
| `ts metadata search` | Search ThoughtSpot metadata objects by type, subtype, name, GUID, or tag. Auto-paginates with `--all`. |
| `ts metadata get <guid>` | Get details of a single metadata object by GUID |
| `ts metadata dependents <guid>` | List all objects that depend on the given source GUID(s) — models, liveboards, answers, sets, feedback |
| `ts metadata report <source>...` | Full dependency audit: walks dependents, probes TML for RLS rules, alerts, joins, column aliases, Spotter AI surface area. Outputs JSON/text/markdown. |
| `ts metadata delete <guid>` | Delete one or more ThoughtSpot objects by GUID |

**Workflow — Dependency audit:**
1. `ts metadata search --subtype MODEL --name "%Sales%"` → find the model GUID
2. `ts metadata dependents <guid>` → see what depends on it
3. `ts metadata report <guid> --format md` → full audit with risk classification

---

#### TML Export / Import

| Command | What it does |
|---|---|
| `ts tml export <guid>` | Export TML for one or more objects. Supports `--fqn` (fully-qualified names), `--associated` (include referenced tables), `--parse` (structured JSON output), `--type FEEDBACK` (coaching feedback). |
| `ts tml import` | Import TML objects from stdin (JSON array of TML strings). Supports `--policy PARTIAL` (best-effort) or `ALL_OR_NONE` (atomic). |

**Workflow — Export, modify, re-import:**
1. `ts tml export <guid> --fqn --parse > model.json` → export as structured JSON
2. Edit the TML in `model.json`
3. `cat tmls.json | ts tml import --policy ALL_OR_NONE` → re-import

---

#### Connection Management

| Command | What it does |
|---|---|
| `ts connections list` | List all data connections (auto-paginated). Filter by `--type` (SNOWFLAKE, BIGQUERY, etc.) |
| `ts connections get <id>` | Fetch a connection's database → schema → table → column hierarchy. Scope with `--database`, `--schema`, `--table`. |
| `ts connections add-tables <id>` | Add or update tables in a connection without removing existing ones. Reads table descriptors from stdin. |

**Workflow — Add new tables to a connection:**
1. `ts connections list` → find the connection ID
2. `ts connections get <id> --database MY_DB --schema MY_SCHEMA` → see existing tables
3. `echo '[{...}]' | ts connections add-tables <id>` → add new tables

---

#### Table Creation

| Command | What it does |
|---|---|
| `ts tables create` | Create ThoughtSpot logical table objects from a JSON spec on stdin. Auto-retries transient JDBC errors. Returns `{table_name: guid}` map. |

**Workflow:** Used by conversion skills (e.g. `ts-convert-from-tableau`) to
create table objects in ThoughtSpot after generating TML.

---

#### Tableau → TML Commands (`ts twb`)

The `ts twb` namespace ("TWB parsing & TML generation") is the deterministic
toolchain behind the **`ts-convert-from-twb-to-tml`** skill (see §2). It turns a
Tableau workbook into import-ready ThoughtSpot TML in numbered stages (T1–T7).
Every command is a pure, offline transform except `validate`, which calls the
cluster with VALIDATE_ONLY (a dry run — nothing is persisted).

> A separate `ts tableau` namespace wraps the Tableau **Server/Cloud REST API**
> (`signin`, `datasources`, `datasource`, `download`) for fetching *published*
> workbooks/datasources. That is a source-acquisition helper, **not** the TML
> pipeline — the pipeline is `ts twb`.

| Tool | Command | What it does |
|---|---|---|
| **T1** | `ts twb parse <file>` | Parse a `.twb`/`.twbx` into structured JSON — datasources, physical tables, joins, physical columns, calculated fields (topo-sorted by dependency level), parameters, and custom SQL. **`--out FILE`** writes the full JSON to disk and prints only a compact structural summary to stdout (counts + per-datasource breakdown + dashboard names), so the orchestrator never ingests the ~55K-token blob. |
| **T2** | `ts twb translate-formula` | Translate + classify calculated fields. Single (`--formula`) or batch (`--input parsed.json`). Uses a **Lark AST translator** — parses each formula into a tree, then emits ThoughtSpot syntax — with **per-formula fallback to the regex translator** if the grammar can't parse it (so it never errors). Covers LOD → `group_aggregate`, `TOTAL`, function renames, nested calls, quoted keywords, operator precedence, `#date#` literals, and comments. All output is lowercased (function names/keywords only — column refs, string literals, and date-format patterns like `MM`/`HH` are preserved). **`--out FILE`** writes the full result to disk and prints a compact object: `summary` (tier counts + `regex_fallbacks`), `judgment[]` (only the formulas needing model reasoning), `reference[]` (every formula's final expression, topo-ordered — keeps cross-formula refs resolvable), and `parameters[]`. |
| **T3** | `ts twb generate-tml` | Generate Table, SQL View, and Model TMLs deterministically from `parsed.json` + `translated.json` — no LLM. Maps types (`integer → INT64`, etc.), sets `db_column_name` on every column and `connection.name` (never `fqn`), joins by name, emits formulas in topo order with matching formula-column entries, and includes only the parameters actually referenced. |
| **T3** | `ts twb qualify` | Qualify bare `[Column]` refs to `[Table::Column]` in translated formulas using a table map; leaves calc-field refs and already-qualified refs untouched, and lists any unresolved columns. |
| **T4** | `ts twb postprocess <dir> <twb>` | Deterministic TML fix-up on the generated files: name mapping, SQL registry, table/sql_view/model fixes, `obj_id` injection, dedup, and local cross-reference validation. |
| **T5** | `ts twb validate <dir>` | Two-phase validation — local invariant lint (no API; catches `FULL_OUTER`, `INT` vs `INT64`, `CASE WHEN` in formulas, `fqn:` in model_tables, missing `db_column_properties`) + VALIDATE_ONLY import (`--profile`). Classifies each per-object error as fixable / locked / warning and tracks attempt count with a hard cap. |
| **T7** | `ts twb verify <file> <dir>` | Fidelity audit — diff the source TWB against the generated TMLs (tables, joins, formulas, parameters) to catch silent drops a server-side validation can't. Exits non-zero on errors. |

**Recent additions to this toolchain (this workstream):**
- **`--out` compact-output mode on T1/T2** — full JSON to a file, only a small summary/judgment object to stdout. Cuts the parse+translate context load from ~80K to ~16K tokens per run.
- **AST formula engine** (`tableau_formula_ast.py`) — a Lark grammar + tree-walk translator wired in behind a per-formula regex fallback. It fixes nested-call, quoted-keyword, and precedence bugs the regex passes could mangle; `summary.regex_fallbacks` reports how many formulas fell back (0 is healthy).
- **Lowercase normalization** — every generated formula uses lowercase functions/keywords while preserving the case of references, strings, and date-format patterns.

**Workflow — deterministic Tableau → TML pipeline (`ts twb`):**
1. `ts twb parse "Workbook.twbx" --out parsed.json` → structured data (compact summary to stdout)
2. `ts twb translate-formula --input parsed.json --out translated.json` → AST translation + classification (compact judgment object to stdout)
3. `ts twb generate-tml --input parsed.json --translated translated.json --connection <c> --database <db> --schema <s> --out output/Workbook` → Table/SQL-View/Model TMLs
4. `ts twb postprocess "output/Workbook" "Workbook.twbx"` → deterministic fix-up
5. `ts twb validate "output/Workbook" --profile <name>` → local lint + VALIDATE_ONLY
6. `ts twb verify "Workbook.twbx" "output/Workbook" --save` → fidelity audit
7. Import validated TMLs via `ts tml import`

---

## 2. Skills (Agent Capabilities)

Skills are step-by-step instructions that Claude Code, Cortex Code CLI, Cursor,
or Snowsight follow to complete a task. They live under `agents/` and are
invoked via slash commands (e.g. `/ts-convert-from-tableau`).

### Conversion Skills

| Skill | Direction | What it does |
|---|---|---|
| `ts-convert-to-snowflake-sv` | TS → Snowflake | Convert a ThoughtSpot model to a Snowflake Semantic View (single, split by domain, or update existing) |
| `ts-convert-from-snowflake-sv` | Snowflake → TS | Convert a Snowflake Semantic View into a ThoughtSpot Model (single, merge multiple, or update existing) |
| `ts-convert-to-databricks-mv` | TS → Databricks | Convert a ThoughtSpot model to a Databricks Metric View |
| `ts-convert-from-databricks-mv` | Databricks → TS | Convert a Databricks Metric View into a ThoughtSpot Model |
| `ts-convert-from-tableau` | Tableau → TS | Convert a Tableau workbook (.twb/.twbx) into ThoughtSpot table + model TMLs, with optional dashboard-to-liveboard migration |
| `ts-convert-from-twb-to-tml` | Tableau → TS | Deterministic Tableau workbook → ThoughtSpot TML pipeline. Drives the `ts twb` toolchain (parse → translate → generate → postprocess → validate → verify) so the model/tables are tool-generated, not hand-written; optional dashboard-to-liveboard migration. |

**Typical conversion workflow:**
1. User invokes `/ts-convert-from-tableau` (or similar)
2. Skill authenticates via `ts auth whoami`
3. Skill reads the source (file, API export, or TML export)
4. Skill generates TML files following shared schema references
5. Skill validates output via `ts twb validate` or `ts tml import --policy VALIDATE_ONLY`
6. Skill imports to ThoughtSpot via `ts tml import`

---

#### `ts-convert-from-twb-to-tml` — Internal Technical Deep-Dive

How the `ts-convert-from-twb-to-tml` pipeline works under the hood, from skill invocation to final TML import. For the engineering team.

##### Architecture Overview

The pipeline is a **guided LLM system** — deterministic CLI tools handle all mechanical work (parsing, translation, generation, postprocessing), while the LLM (Claude) handles orchestration, user interaction, ambiguous formula decisions, and error correction.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           SKILL (SKILL.md)                                  │
│  Claude reads the skill instructions and orchestrates the full flow.        │
│  It calls CLI tools, interprets results, makes decisions, and talks to      │
│  the user. The skill is the "brain"; the tools are the "hands".             │
└──────────────────────────────────────────────────────────────────────────────┘
        │           │           │            │           │           │
        ▼           ▼           ▼            ▼           ▼           ▼
   ┌────────┐ ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌────────┐
   │T1 Parse│ │T2 Trans-│ │T3 Gen-  │ │T4 Post-  │ │T5 Vali- │ │T7 Veri-│
   │        │ │  late   │ │erate TML│ │ process  │ │  date   │ │   fy   │
   └────────┘ └─────────┘ └─────────┘ └──────────┘ └─────────┘ └────────┘
   Determin-  Determin-   Determin-   Determin-    Determin-   Determin-
   istic      istic       istic       istic        istic +     istic
                                                   API call
```

##### What Each Component Does: Tool vs. Claude

| Step | Who does it | What happens |
|---|---|---|
| Step 0: Show plan | Claude | Displays the step list, asks Audit/Migrate |
| Step 1: Auth | Claude + `ts` CLI | Claude reads profile JSON, runs `ts auth whoami` |
| Step 2: Locate file | Claude | Asks user for path, validates it exists |
| Step 2.5: Table map | Claude | Parses optional mapping file |
| **Step 3: Parse TWB** | **T1 (tool)** | `ts twb parse` — XML → JSON. Deterministic. Sub-second. |
| **Step 3.5: Translate formulas** | **T2 (tool)** | `ts twb translate-formula` — Lark AST + regex fallback. Deterministic. |
| Step 4: Select connection | Claude + `ts` CLI | Lists connections via `ts connections list`, user picks |
| Step 4.5: Confirm tables | Claude + `ts` CLI | Searches ThoughtSpot metadata if needed |
| **Step 5: Generate TMLs** | **T3 (tool)** + Claude | T3 generates TMLs deterministically from disk. Claude resolves `decisions-needed.json` for ambiguous formulas. |
| **Step 6: Post-process** | **T4 (tool)** | 5 phases of deterministic fixes. No LLM involvement. |
| **Step 6.5: Validate** | **T5 (tool)** + Claude | T5 runs local lint + VALIDATE_ONLY API. Claude fixes errors. Loops up to 10 times. |
| **Step 6.7: Coverage audit** | **T7 (tool)** | Compares TWB vs TML for structural and formula accuracy. |
| Step 7: Review + Import | Claude + `ts` CLI | Shows summary, user confirms, `ts tml import` with ALL_OR_NONE |
| Step 7.5: Test | Claude | Asks user to verify in ThoughtSpot |
| Step 12: Report | Claude | Generates migration report |

##### Detailed Pipeline Flow

**Stage 1: Model Migration (Deterministic + LLM)**

```
                                    ┌─────────────────────────┐
                                    │    Input: .twb file     │
                                    └────────────┬────────────┘
                                                 │
                              ┌───────────────────┴───────────────────┐
                              │  STEP 3 — T1: ts twb parse            │
                              │  ─────────────────────────────────    │
                              │  WHO: Deterministic CLI tool          │
                              │  IN:  .twb XML (5K-100K lines)       │
                              │  OUT: parsed.json (disk) +            │
                              │       compact summary (stdout)        │
                              │                                       │
                              │  WHAT IT DOES:                        │
                              │  • Walks <datasource> elements        │
                              │  • Extracts tables, columns, joins    │
                              │  • Extracts calculated fields          │
                              │  • Extracts parameters                │
                              │  • Topo-sorts formulas (Kahn's algo)  │
                              │  • Resolves [Calculation_*] refs      │
                              │  • Detects sqlproxy, extracts, etc.   │
                              │                                       │
                              │  CONTEXT RULE: parsed.json NEVER      │
                              │  enters Claude's context. Tools read  │
                              │  it from disk.                        │
                              └───────────────────┬───────────────────┘
                                                  │
                                          parsed.json (on disk)
                                                  │
                              ┌───────────────────┴───────────────────┐
                              │  STEP 3.5 — T2: translate-formula    │
                              │  ─────────────────────────────────    │
                              │  WHO: Deterministic CLI tool          │
                              │  IN:  parsed.json                     │
                              │  OUT: translated.json (disk) +        │
                              │       compact view (stdout)           │
                              │                                       │
                              │  HOW IT TRANSLATES:                   │
                              │  1. Try Lark AST parser (primary)     │
                              │     - Full Earley grammar             │
                              │     - Handles nested LOD, IIF, CASE   │
                              │     - 100% accuracy on test suite     │
                              │  2. If AST fails → regex fallback     │
                              │     - Chain of regex substitutions    │
                              │     - 89% accuracy                    │
                              │                                       │
                              │  CLASSIFICATION:                      │
                              │  • deterministic: true → done         │
                              │  • deterministic: false → Claude      │
                              │    handles in Step 5                  │
                              │  • tier: untranslatable → skipped     │
                              │                                       │
                              │  STDOUT RETURNS:                      │
                              │  • summary (tier counts)              │
                              │  • judgment[] (only non-deterministic)│
                              │  • reference[] (all translated)       │
                              │  • parameters[]                       │
                              └───────────────────┬───────────────────┘
                                                  │
                                     translated.json (on disk)
                                     + compact view in context
                                                  │
          ┌───────────────────────────────────────┴─┐
          │                                         │
          ▼                                         ▼
┌─────────────────────┐               ┌──────────────────────────┐
│ Claude: Connection  │               │ Claude: Table mapping    │
│ selection, table    │               │ (optional user-provided  │
│ confirmation        │               │  file from Step 2.5)     │
│ (Steps 4, 4.5)     │               └────────────┬─────────────┘
└─────────┬───────────┘                            │
          └───────────────────┬────────────────────┘
                              │
                              ▼
                ┌─────────────────────────────────────────┐
                │  STEP 5 — T3: ts twb generate-tml       │
                │  ──────────────────────────────────────  │
                │  WHO: Deterministic CLI tool             │
                │  IN:  parsed.json + translated.json      │
                │       + connection name + db/schema      │
                │       + optional decisions.json          │
                │  OUT: *.table.tml, *.sql_view.tml,       │
                │       *.model.tml files in output dir    │
                │       + decisions-needed.json (if any)   │
                │                                          │
                │  PHASE 1: Table TMLs                     │
                │    physical table → table.tml YAML       │
                │    sets db, schema, db_table, connection  │
                │    maps columns with types               │
                │                                          │
                │  PHASE 2: SQL View TMLs                  │
                │    custom SQL → sql_view.tml YAML        │
                │    rewrites table refs, strips params     │
                │                                          │
                │  PHASE 3: Model TML                      │
                │    builds model_tables, joins, formulas,  │
                │    columns, parameters                    │
                │    looks up translations from T2 output   │
                │    generates decisions-needed.json for    │
                │    formulas Claude must resolve           │
                │                                          │
                │  KEY: parsed.json and translated.json     │
                │  are read from DISK by this tool. They    │
                │  never enter Claude's context window.     │
                │  This is the V3 breakthrough.             │
                └─────────────────┬───────────────────────┘
                                  │
                           ┌──────┴──────┐
                           │             │
                           ▼             ▼
                   decisions-needed.json?
                       │           │
                      YES          NO
                       │           │
                       ▼           │
            ┌──────────────────┐   │
            │ Claude resolves  │   │
            │ ambiguous        │   │
            │ formulas:        │   │
            │ • LOD → group_   │   │
            │   aggregate()    │   │
            │ • Window funcs   │   │
            │ • Growth patterns│   │
            │                  │   │
            │ Writes:          │   │
            │ decisions.json   │   │
            │                  │   │
            │ Re-runs T3 with  │   │
            │ --decisions flag │   │
            └────────┬─────────┘   │
                     └──────┬──────┘
                            │
                     TML files on disk
                            │
                            ▼
                ┌─────────────────────────────────────────┐
                │  STEP 6 — T4: ts twb postprocess        │
                │  ──────────────────────────────────────  │
                │  WHO: Deterministic CLI tool             │
                │  IN:  TML directory + source .twb        │
                │  OUT: TML files modified IN PLACE        │
                │                                          │
                │  Phase 0: Pre-setup                      │
                │    • Build name_mapping.json              │
                │    • Build SQL query registry             │
                │                                          │
                │  Phase 1: SQL View fixes                 │
                │    • Align SQL view names to TWB source  │
                │    • Propagate renames to models          │
                │                                          │
                │  Phase 2: Table fixes                    │
                │    • Align table/column names to TWB     │
                │    • Normalize db identifiers to         │
                │      UPPER_SNAKE_CASE                    │
                │                                          │
                │  Phase 3: Model fixes (8 sub-steps)      │
                │    1. Fix join on-clauses                │
                │    2. Restore column display names       │
                │    3. Inject parameters                  │
                │    4. Translate remaining formula refs   │
                │    5. Fix model_tables references        │
                │    6. Fix formula column refs            │
                │    7. Strip invalid GUIDs/FQNs           │
                │    8. Inject obj_ids + deduplicate       │
                │                                          │
                │  Phase 4: Cross-model name mapping       │
                │    • Fix stale formula_id refs across    │
                │      all model TMLs                      │
                │                                          │
                │  Phase 5: Cross-reference check          │
                │    • Verify every reference resolves     │
                │    • Report broken refs                  │
                │                                          │
                │  NO LLM INVOLVEMENT. Purely mechanical.  │
                └─────────────────┬───────────────────────┘
                                  │
                                  ▼
                ┌─────────────────────────────────────────┐
                │  STEP 6.5 — T5: ts twb validate         │
                │  ──────────────────────────────────────  │
                │  WHO: Tool (local lint) + API call       │
                │       + Claude (error fixing)            │
                │  IN:  TML directory + ThoughtSpot profile│
                │  OUT: Validation report JSON             │
                │                                          │
                │  Phase 1: Local proofread (lint)         │
                │    • FULL_OUTER → OUTER                  │
                │    • INT → INT64                         │
                │    • CASE WHEN → if/then/else            │
                │    • fqn in model_tables (invalid)       │
                │    • window funcs in model formulas      │
                │                                          │
                │  Phase 2: Server validation              │
                │    POST /api/rest/2.0/metadata/tml/import│
                │    import_policy: VALIDATE_ONLY          │
                │    (dry run — no data persisted)          │
                │                                          │
                │  Error classification:                   │
                │    • fixable → Claude fixes + re-validate│
                │    • locked → permanently unfixable       │
                │    • warning → informational             │
                │                                          │
                │  LOOP: Up to 10 attempts.                │
                │  Claude reads errors, edits TML files,   │
                │  re-runs T5. Continues until clean or    │
                │  attempts exhausted.                     │
                │                                          │
                │  Lock registry: _lock_registry.json      │
                │  tracks unfixable objects + cascades.     │
                │  Generates MIGRATION_LIMITATIONS.md      │
                └─────────────────┬───────────────────────┘
                                  │
                                  ▼
                ┌─────────────────────────────────────────┐
                │  STEP 6.7 — T7: ts twb verify           │
                │  ──────────────────────────────────────  │
                │  WHO: Deterministic CLI tool             │
                │  IN:  source .twb + TML directory        │
                │  OUT: MIGRATION_ACCURACY_REPORT.md       │
                │                                          │
                │  Check 1: Structural completeness        │
                │    • datasources vs models               │
                │    • tables vs table TMLs                │
                │    • custom SQL vs sql_view TMLs         │
                │    • joins count match                   │
                │    • translatable formulas vs TML        │
                │                                          │
                │  Check 2: Formula equivalence            │
                │    • Normalize both sides                │
                │    • LCS similarity scoring              │
                │    • >=85% = MATCH                       │
                │    • 50-84% = PARTIAL                    │
                │    • <50% = LOW                          │
                │                                          │
                │  Check 3: TML validity                   │
                │    • Structural checks on every TML      │
                │    • Banned functions in model formulas   │
                │                                          │
                │  Check 4: Limitation coverage            │
                │    • Untranslatable formulas documented?  │
                └─────────────────┬───────────────────────┘
                                  │
                                  ▼
                ┌─────────────────────────────────────────┐
                │  STEP 7 — Import                        │
                │  ──────────────────────────────────────  │
                │  WHO: Claude + ts CLI                    │
                │                                          │
                │  Claude shows the user:                  │
                │  • Formula map (what was converted)      │
                │  • Omissions (what was skipped + why)    │
                │  • Accuracy report summary               │
                │                                          │
                │  User confirms → Claude runs:            │
                │  ts tml import --policy ALL_OR_NONE      │
                │    --create-new --profile {name}          │
                │                                          │
                │  Import order: tables → sql_views →      │
                │  models (dependency order)                │
                └─────────────────────────────────────────┘
```

##### Data Flow — What Goes Where

```
                        .twb file
                            │
                  ┌─────────┴─────────┐
                  │   T1: parse       │
                  └─────────┬─────────┘
                            │
                    parsed.json ──────────────────────┐
                            │                         │
                  ┌─────────┴─────────┐               │
                  │  T2: translate    │               │
                  └─────────┬─────────┘               │
                            │                         │
                  translated.json                     │
                            │                         │
                  ┌─────────┴─────────┐               │
                  │  T3: generate-tml │◄──────────────┘
                  │  (reads BOTH from │     (reads parsed.json
                  │   disk directly)  │      for tables/joins)
                  └─────────┬─────────┘
                            │
              ┌─────────────┼──────────────┐
              │             │              │
        *.table.tml   *.sql_view.tml  *.model.tml
              │             │              │
              └─────────────┼──────────────┘
                            │
                  ┌─────────┴─────────┐
                  │  T4: postprocess  │◄── also reads .twb
                  └─────────┬─────────┘    for name alignment
                            │
                   TML files (fixed in place)
                            │
                  ┌─────────┴─────────┐
                  │  T5: validate     │──► ThoughtSpot API
                  └─────────┬─────────┘    (VALIDATE_ONLY)
                            │
                  ┌─────────┴─────────┐
                  │  T7: verify       │◄── reads .twb + TMLs
                  └─────────┬─────────┘
                            │
                  MIGRATION_ACCURACY_REPORT.md
                            │
                  ┌─────────┴─────────┐
                  │  ts tml import    │──► ThoughtSpot
                  └───────────────────┘    (live objects)
```

**Critical design principle:** `parsed.json` and `translated.json` are NEVER read into Claude's context. They pass between tools on disk. This is the V3 breakthrough that reduced cost by 73% and time by 75%.

##### Where Claude Gets Involved (and Why)

| Situation | Why tool can't handle it |
|---|---|
| Ambiguous formula decisions | LOD expressions, window functions, growth patterns need context from worksheet shelves to determine the right `group_aggregate` formulation |
| Validation error fixes | Server errors are diverse and contextual — wrong column name, missing join, type mismatch. Claude reads the error, finds the right fix, edits the TML. |
| Connection/table selection | Requires understanding user intent — which of 5 connections to use, which tables to reuse vs. create |
| User communication | Summarizing what was converted, explaining omissions, asking for confirmations |

##### File Layout on Disk

```
/tmp/ts_tableau_mig/
├── output/
│   └── {workbook_name}/
│       ├── parsed.json              ← T1 output
│       ├── translated.json          ← T2 output
│       ├── decisions-needed.json    ← T3 output (if any)
│       ├── decisions.json           ← Claude's resolved decisions
│       ├── {table_name}.table.tml   ← T3 output (one per table)
│       ├── {sql_view}.sql_view.tml  ← T3 output (custom SQL)
│       ├── {model_name}.model.tml   ← T3 output (one per datasource)
│       ├── name_mapping.json        ← T4 internal
│       ├── _twb_sql_registry.json   ← T4 internal
│       ├── _validate_state.json     ← T5 attempt counter
│       ├── _lock_registry.json      ← T5 unfixable objects
│       ├── MIGRATION_LIMITATIONS.md ← T5 auto-generated
│       └── MIGRATION_ACCURACY_REPORT.md ← T7 output
└── audit/
    └── {workbook_name}_audit.md     ← Audit mode report
```

##### Tool Command Reference

| Tool | Command | Key flags |
|---|---|---|
| T1 | `ts twb parse <file> --out <path>` | `--text` for human-readable; `--indent N` |
| T2 | `ts twb translate-formula --input <parsed.json> --out <path>` | `--formula "..."` for single; `--table-map <file>` |
| T3 | `ts twb generate-tml --input <parsed.json> --translated <translated.json> --connection <name> --database <db> --schema <sch> --out <dir>` | `--decisions <file>`, `--table-map <file>`, `--connection-tables <file>` |
| T4 | `ts twb postprocess <directory> <workbook.twb>` | — |
| T5 | `ts twb validate <directory> --profile <name>` | `--proofread-only` (skip API), `--reset` |
| T7 | `ts twb verify <workbook.twb> <tml-directory>` | `--verbose`, `--save` |

##### Key Design Decisions

1. **One model per Tableau datasource** — never merge datasources across models. Each datasource is independent.

2. **Files never enter LLM context** — parsed.json, translated.json, and TML files are consumed from disk by tools. Claude only sees compact summaries and specific errors.

3. **Topo-sort formulas** — Kahn's algorithm ensures Level 0 (no deps) goes first in the model. This prevents forward-reference errors.

4. **AST-first, regex-fallback** — The Lark parser handles 100% of the test suite. Regex catches anything the grammar doesn't cover. Both are deterministic.

5. **Validation loop with hard cap** — Up to 10 attempts. Lock registry prevents infinite loops on unfixable objects. Cascade detection locks dependent objects too.

6. **Import order matters** — Tables first, then SQL views, then models. Models reference tables; importing in wrong order causes "not found" errors.

7. **VALIDATE_ONLY before real import** — Dry-run catches errors without side effects. Real import only happens after user confirmation at Step 7.

---

### ThoughtSpot Object Skills

| Skill | What it does |
|---|---|
| `ts-object-answer-promote` | Promote formulas and parameters from a saved Answer into a Model. Exports the answer TML, extracts formulas, merges them into the parent model, and re-imports. |
| `ts-object-model-coach` | Prepare a Model for Spotter — reviews AI Context, synonyms, mines dependent objects for usage patterns, and generates coaching feedback TML improvements. |

**Model Coach workflow:**
1. Export the model TML + feedback TML
2. Analyze AI Context completeness, synonym coverage
3. Mine dependent answers/liveboards for search patterns
4. Generate improvement recommendations as feedback TML
5. Import the updated feedback TML

---

### Dependency Management

| Skill | What it does |
|---|---|
| `ts-dependency-manager` | Audit dependencies, safely remove or repoint columns across Models, Views, Answers, and Liveboards. Walks the dependency graph before any destructive action. |

**Dependency removal workflow:**
1. `ts metadata report <source-guid>` → full dependency audit
2. Skill classifies impact (high/medium/low risk)
3. For each dependent object: export TML → remove/repoint references → re-import
4. Delete the source object only after all dependents are updated

---

### Profile / Credential Skills

| Skill | What it does | Runtimes |
|---|---|---|
| `ts-profile-thoughtspot` | Add, update, test, or delete ThoughtSpot profiles. Stores credentials in OS keychain (never in files). | All |
| `ts-profile-snowflake` | Add, update, test, or delete Snowflake profiles. | Claude Code, Cursor |
| `ts-profile-databricks` | Add, update, test, or delete Databricks profiles (OAuth M2M, PAT, or existing CLI profile). | Claude Code, Cursor |

**Profile setup workflow:**
1. User provides URL + username
2. Skill directs user to store credential in OS keychain (user runs the command in their terminal)
3. Skill creates profile JSON in `~/.claude/thoughtspot-profiles.json`
4. Skill runs `ts auth whoami --profile <name>` to verify

---

### Recipe Skills

| Skill | What it builds | Platform |
|---|---|---|
| `ts-recipe-formula-business-days-snowflake` | Three Snowflake UDFs for weekday-only date arithmetic + ThoughtSpot formula syntax | Snowflake |
| `ts-recipe-formula-hms-display-snowflake` | Four Snowflake UDFs to format seconds/minutes as `HH:MM:SS`, `DD:HH:MM:SS`, etc. | Snowflake |

**Recipe workflow:**
1. Authenticate to both Snowflake and ThoughtSpot
2. Deploy UDF(s) to Snowflake
3. Show the ThoughtSpot formula syntax that calls the UDF
4. Optionally add the formula to an existing model

---

### Other Skills

| Skill | What it does | Runtimes |
|---|---|---|
| `ts-variable-timezone` | Search, set, or remove timezone values for `ts_user_timezone` at org or user level | Claude Code, Cursor |
| `ts-setup-sv` | Install or upgrade stored procedures used by CoCo Snowsight skills | CoCo Snowsight only |

---

## 3. Validation Tools

**Location:** `tools/validate/`

Static validators that run in the pre-commit hook. No live ThoughtSpot or
Snowflake connection required.

| Validator | What it checks |
|---|---|
| `check_references.py` | Every file path referenced in SKILL.md files actually exists in the repo. Resolves `~/.claude/shared/` → `agents/shared/`, etc. |
| `check_patterns.py` | Grep-based anti-pattern detector: `fqn:` inside connection blocks, `aggregation:` inside formulas, `connection_fqn` in Python, `%%` in help strings. |
| `check_yaml.py` | All fenced YAML code blocks in .md files parse without error. |
| `check_version_sync.py` | `ts_cli/__init__.py __version__` matches `pyproject.toml version`. |
| `check_consistency.py` | Cross-file consistency: broken references, stage copy completeness, skills table accuracy, symlink instructions, anti-patterns. |
| `check_runtime_coverage.py` | Every Claude skill has a corresponding Cursor `.mdc` file. CoCo divergences must be listed in `EXPECTED_DIVERGENCES`. |
| `check_skill_naming.py` | Skill directories match one of the nine documented family patterns (`ts-object-*`, `ts-profile-*`, `ts-convert-*`, etc.). |
| `check_skill_versions.py` | Every shipped skill has a `## Changelog` section with valid semver entries. |
| `check_smoke_tests.py` | Every new/modified Claude skill has a smoke test in `tools/smoke-tests/`, or is on the allowlist with justification. |
| `check_open_items.py` | Validates `references/open-items.md` format and status tracking. |
| `check_secrets.py` | Scans for credential values or secrets accidentally committed. |
| `check_sv_yaml.py` | Validates Snowflake Semantic View YAML structure. |
| `check_tml.py` | Validates TML file structure against known invariants. |

**Workflow — Pre-commit validation:**
All validators run automatically via `scripts/pre-commit.sh` on every commit.
To run manually:
```bash
python3 tools/validate/check_references.py --root .
python3 tools/validate/check_patterns.py --root .
python3 tools/validate/check_yaml.py
python3 tools/validate/check_version_sync.py
# ... or all at once via the pre-commit hook
```

### Suggestion / Advisory Tools

| Tool | What it does |
|---|---|
| `suggest_repo_changelog.py` | Detects new skills, ts-cli version bumps, new shared files in staged changes, and prompts the author to add a CHANGELOG.md entry. |
| `suggest_skill_version.py` | Suggests the appropriate version bump (major/minor/patch) based on staged changes to a skill. |
| `suggest_dependency_types.py` | Suggests dependency type classifications for open items. |

---

## 4. Smoke Tests

**Location:** `tools/smoke-tests/`

End-to-end tests that exercise skills against a live ThoughtSpot/Snowflake
instance. Require real credentials configured via profile skills.

| Smoke Test | Skill Tested |
|---|---|
| `smoke_ts_to_snowflake.py` | `ts-convert-to-snowflake-sv` |
| `smoke_ts_from_snowflake.py` | `ts-convert-from-snowflake-sv` |
| `smoke_ts_to_databricks.py` | `ts-convert-to-databricks-mv` |
| `smoke_ts_from_databricks.py` | `ts-convert-from-databricks-mv` |
| `smoke_ts_dependency_manager.py` | `ts-dependency-manager` |
| `smoke_ts_object_model_coach.py` | `ts-object-model-coach` |
| `smoke_ts_variable_timezone.py` | `ts-variable-timezone` |
| `smoke_ts-metadata-report.py` | `ts metadata report` command |
| `smoke_ts_recipe_formula_business_days_snowflake.py` | `ts-recipe-formula-business-days-snowflake` |
| `smoke_ts_recipe_formula_hms_display_snowflake.py` | `ts-recipe-formula-hms-display-snowflake` |

**Workflow:**
```bash
# Run a single smoke test
python tools/smoke-tests/smoke_ts_to_snowflake.py

# Run all smoke tests
python tools/validate/run_smoke_tests.py
```

---

## 5. Deployment Scripts

**Location:** `scripts/`

| Script | What it does |
|---|---|
| `deploy.sh` | Push to GitHub + conditionally sync CoCo files to Snowflake stage. Must be on `main` branch with clean working tree. Supports `--all` for full upload. |
| `stage-sync.sh` | Sync CoCo skill files and shared references to the Snowflake stage. Only uploads changed files (tracked via `.snowflake-deploy-sha`). Supports `--all` for full upload. |
| `pre-commit.sh` | Pre-commit hook that runs the full validation suite. Install with `ln -s ../../scripts/pre-commit.sh .git/hooks/pre-commit`. |
| `pre-push.sh` | Pre-push hook for additional checks before pushing to remote. |

**Deployment workflow (after PR merges to main):**
1. `git checkout main && git pull`
2. For `agents/coco-snowsight/` or `agents/shared/` changes: `./scripts/stage-sync.sh`
3. For `tools/ts-cli/` changes: `pip install -e tools/ts-cli` in affected environments
4. Claude Code changes (via symlinks) take effect immediately — no action needed

---

## 6. Shared Reference Library

**Location:** `agents/shared/`

Reference files consumed by ALL runtimes. Skills read these at execution time —
they are the single source of truth for schemas, mappings, and worked examples.

### Schemas (`agents/shared/schemas/`)

| File | What it documents |
|---|---|
| `thoughtspot-table-tml.md` | ThoughtSpot table TML structure and invariants |
| `thoughtspot-model-tml.md` | ThoughtSpot model TML structure and invariants |
| `thoughtspot-view-tml.md` | ThoughtSpot view TML structure |
| `thoughtspot-sql-view-tml.md` | ThoughtSpot SQL view TML structure |
| `thoughtspot-answer-tml.md` | ThoughtSpot answer TML structure |
| `thoughtspot-liveboard-tml.md` | ThoughtSpot liveboard TML structure |
| `thoughtspot-alert-tml.md` | ThoughtSpot alert TML structure |
| `thoughtspot-feedback-tml.md` | ThoughtSpot feedback/coaching TML structure |
| `thoughtspot-sets-tml.md` | ThoughtSpot sets/cohorts TML structure |
| `thoughtspot-tml.md` | General TML rules and cross-type invariants |
| `thoughtspot-formula-patterns.md` | Common ThoughtSpot formula patterns |
| `thoughtspot-connection.md` | ThoughtSpot connection object structure |
| `snowflake-schema.md` | Snowflake Semantic View YAML schema reference |
| `databricks-metric-view.md` | Databricks Metric View YAML schema reference |

### Mappings (`agents/shared/mappings/`)

| Directory | What it maps |
|---|---|
| `ts-snowflake/` | Column types, join types, formula translations, and property mappings between ThoughtSpot and Snowflake |
| `ts-databricks/` | Column types, join types, and property mappings between ThoughtSpot and Databricks |
| `tableau/` | Tableau formula-to-ThoughtSpot translation rules, TML mapping patterns |

### Worked Examples (`agents/shared/worked-examples/`)

| Directory | Contents |
|---|---|
| `snowflake/` | End-to-end ThoughtSpot ↔ Snowflake Semantic View conversion examples |
| `databricks/` | End-to-end ThoughtSpot ↔ Databricks Metric View conversion examples |

---

## 7. Runtime Coverage Matrix

Which skills are available on which runtimes:

| Skill | Claude Code | Cortex Code CLI | Cursor | CoCo Snowsight |
|---|:-:|:-:|:-:|:-:|
| `ts-profile-thoughtspot` | yes | yes | yes | yes |
| `ts-profile-snowflake` | yes | — | yes | — |
| `ts-profile-databricks` | yes | yes | yes | — |
| `ts-convert-to-snowflake-sv` | yes | yes | yes | yes |
| `ts-convert-from-snowflake-sv` | yes | yes | yes | yes |
| `ts-convert-to-databricks-mv` | yes | yes | yes | — |
| `ts-convert-from-databricks-mv` | yes | yes | yes | — |
| `ts-convert-from-tableau` | yes | yes | yes | — |
| `ts-convert-from-twb-to-tml` | yes | yes | — | — |
| `ts-object-answer-promote` | yes | yes | yes | — |
| `ts-object-model-coach` | yes | yes | yes | — |
| `ts-dependency-manager` | yes | yes | yes | — |
| `ts-variable-timezone` | yes | yes | yes | — |
| `ts-recipe-formula-business-days-snowflake` | yes | yes | yes | yes |
| `ts-recipe-formula-hms-display-snowflake` | yes | yes | yes | yes |
| `ts-setup-sv` | — | — | — | yes |

---

## 8. End-to-End Workflow: From Clone to Production

```
1. Clone repo
   └── git clone ... ~/thoughtspot-agent-skills

2. Install ts CLI
   └── pip install -e tools/ts-cli

3. Symlink skills into your agent runtime
   └── ln -s agents/cli/<skill> ~/.claude/skills/<skill>   (or ~/.snowflake/cortex/skills/)

4. Configure credentials
   └── /ts-profile-thoughtspot  →  stores in OS keychain
   └── /ts-profile-snowflake    →  stores in OS keychain (if needed)

5. Run a skill
   └── /ts-convert-from-twb-to-tml "My Workbook.twbx"
       ├── ts twb parse           → structured JSON (compact summary)
       ├── ts twb translate-formula → AST translate + classify
       ├── ts twb generate-tml    → Table / SQL-View / Model TML
       ├── ts twb postprocess     → fix-up TMLs
       ├── ts twb validate        → local proofread + server VALIDATE_ONLY
       ├── ts twb verify          → fidelity audit
       └── ts tml import          → import to ThoughtSpot

6. Develop / extend
   └── Edit skill or CLI command
   └── Run validators: python3 tools/validate/check_*.py
   └── Run smoke tests: python tools/smoke-tests/smoke_<skill>.py
   └── Commit (pre-commit hook runs all validators)
   └── Open PR against main

7. Deploy
   └── After PR merges: ./scripts/stage-sync.sh (for CoCo changes)
   └── Claude Code changes take effect immediately via symlinks
```