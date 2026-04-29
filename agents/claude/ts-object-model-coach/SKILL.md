---
name: ts-object-model-coach
description: Comprehensively prepare a ThoughtSpot Model for Spotter — review existing AI context, synonyms, and description for quality; mine dependent Liveboards/Answers and (optionally) Snowflake history for real business language; then generate the user's chosen mix of column AI Context, column Synonyms, Reference Questions, Business Terms, and a Data Model Instructions draft.
---

# ThoughtSpot: Coach a Model (Comprehensive Spotter Preparation)

Spotter accuracy depends on five distinct coaching surfaces working together. Most teams
curate them ad-hoc, in isolation, and let them drift over time. This skill produces
all five from the same evidence base — Model schema, dependent Liveboards/Answers,
analyst prose, and (optionally) Snowflake query history — and reviews any existing
content critically rather than blindly adding more.

**The five Spotter coaching surfaces:**

| # | Surface | Where it lives | What it does |
|---|---|---|---|
| 1 | **Column AI Context** | `model.columns[].properties.ai_context` (structured YAML — closed enums + refs only; ≤ 400 chars) | Declares the constraints downstream LLMs need to write correct SQL: `additivity`, `time_basis`, `source`, `grain_keys`. See [ai-context-schema.md](references/ai-context-schema.md). Prose context lives in `column.description`. |
| 2 | **Column Synonyms** | `model.columns[].synonyms[]` (array, per column) | Schema-level alternative names — used by the parser |
| 3 | **Reference Questions** | `nls_feedback.feedback[type=REFERENCE_QUESTION]` | Per-question NL → tokenised search mappings |
| 4 | **Business Terms** | `nls_feedback.feedback[type=BUSINESS_TERM]` | Coaching-layer phrase → column/formula mappings |
| 5 | **Data Model Instructions** | Model-level free text — TML location TBD (see [open-items.md](references/open-items.md) #4) | Global rules ("when I say last month, use last 30 days") |

**Research-backed defaults:**
- Reference Question target: ~15 to start (Snowflake's *"10–20 covering common questions"*).
- Mix simple aggregations with complex joins/ratios — *"Simple queries may not have as
  much useful information"*
  ([Cortex optimization](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/analyst-optimization)).
- Existing AI assets are critiqued + improved, **never silently overwritten**.
- The user picks which surfaces to generate via a single up-front menu.

Ask one question at a time. Wait for each answer before proceeding.

---

## References

| File | Purpose |
|---|---|
| [references/open-items.md](references/open-items.md) | Unverified API behaviours; Data Model Instructions TML location |
| [references/question-taxonomy.md](references/question-taxonomy.md) | Deterministic candidate-question patterns (T1–T4) and ranking |
| [references/token-mapping-rules.md](references/token-mapping-rules.md) | NL → `search_tokens` translation; paraphrase variants; chart_type/display_mode inference |
| [references/prose-mining-rules.md](references/prose-mining-rules.md) | How to extract business phrases from Model description, Answer/Liveboard prose, tile names |
| [references/ai-asset-review-rules.md](references/ai-asset-review-rules.md) | Critique heuristics for existing ai_context / synonyms / description |
| [references/synonym-strategy-explainer.md](references/synonym-strategy-explainer.md) | Inline explainer for column synonyms vs BUSINESS_TERM coaching (shown to the user) |
| [references/review-explainers.md](references/review-explainers.md) | 3-section explainer blocks (purpose / signals checked / outcome rules) prepended to every Step 7 review file |
| [references/cross-model-consistency.md](references/cross-model-consistency.md) | Cross-Model column collision detection — purpose, signals, decision tree, output format (powers Step 4.5) |
| [references/feedback-tml-verified-patterns.md](references/feedback-tml-verified-patterns.md) | Verified `nls_feedback` syntax patterns (search_tokens shapes, chart_type/display_mode values, axis_config notation) mined from real coached Models — authoritative reference for Step 6 + Step 8c generation |
| [~/.claude/skills/ts-profile-thoughtspot/SKILL.md](~/.claude/skills/ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth, profile config |
| [~/.claude/skills/ts-profile-snowflake/SKILL.md](~/.claude/skills/ts-profile-snowflake/SKILL.md) | Snowflake auth (optional) |
| [~/.claude/shared/schemas/thoughtspot-feedback-tml.md](~/.claude/shared/schemas/thoughtspot-feedback-tml.md) | Coaching TML structure (output for surfaces 3 + 4) |
| [~/.claude/shared/schemas/thoughtspot-model-tml.md](~/.claude/shared/schemas/thoughtspot-model-tml.md) | Model TML structure — `ai_context`, `synonyms`, `description` field locations (output for surfaces 1 + 2) |
| [~/.claude/shared/schemas/thoughtspot-answer-tml.md](~/.claude/shared/schemas/thoughtspot-answer-tml.md) | Answer TML — `name`, `description`, `search_query` mining input |
| [~/.claude/shared/schemas/thoughtspot-liveboard-tml.md](~/.claude/shared/schemas/thoughtspot-liveboard-tml.md) | Liveboard TML — visualization names + tile descriptions for prose mining |
| [~/.claude/shared/schemas/thoughtspot-formula-patterns.md](~/.claude/shared/schemas/thoughtspot-formula-patterns.md) | Formula syntax for answer-level formula generation |
| [~/.claude/mappings/ts-snowflake/ts-snowflake-formula-translation.md](~/.claude/mappings/ts-snowflake/ts-snowflake-formula-translation.md) | SQL → TS formula translation (mandatory read for SQL-derived candidates) |

---

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- Snowflake profile configured (optional, only for query-history mining) — `/ts-profile-snowflake`
- `ts` CLI installed: `pip install -e tools/ts-cli`
- Python: `pip install pyyaml`
- ThoughtSpot user must have **MODIFY** or **FULL** access on the target Model

---

## Step 0 — Overview

On skill invocation, display:

---
**ts-object-model-coach** — comprehensively prepare a Model for Spotter: review existing AI context/synonyms/description, mine dependent objects + (optionally) Snowflake history, then generate your chosen mix of column AI Context, Synonyms, Reference Questions, Business Terms, and a Data Model Instructions draft.

Steps:
  1.  Authenticate and pick the Model ........................ you choose
  2.  Export Model TML; extract schema and existing AI assets . auto
  3.  Mine candidate sources (Liveboards/Answers, prose, Snowflake) . auto
  4.  Review existing AI assets — produce critique + deltas .. auto
  4.5 Cross-Model consistency scan — flag column-name collisions across other Models . auto
  5.  Show critique; pick which surfaces to generate ......... you confirm
  6.  Generate proposals per selected surface ................. auto
  7.  Per-surface review with explainer blocks (purpose / signals / outcome rules) . you confirm
  8.  Build merged TML, backup, final import gate ............. you confirm
  9.  Import + smoke test ..................................... auto

Confirmation required: Steps 1, 5, 7, 8
Auto-executed: Steps 2, 3, 4, 4.5, 6, 9

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Step 1 — Authenticate and Pick the Model

Read `~/.claude/thoughtspot-profiles.json`. Prompt for profile if multiple exist; confirm
the single profile if exactly one.

```bash
source ~/.zshenv && ts auth whoami --profile "{profile_name}"
```

Save `{base_url}` (strip trailing slash) and `{profile_name}`.

Pick the Model — accept `--guid` or prompt to search:

```bash
source ~/.zshenv && ts metadata search \
  --subtype WORKSHEET --name "%{search_term}%" --profile "{profile_name}"
```

Mark each result `[MODEL]` or `[WORKSHEET]` using `metadata_header.contentUpgradeId` /
`worksheetVersion` (same logic as
[ts-object-answer-promote Step 5](~/.claude/skills/ts-object-answer-promote/SKILL.md)).
This skill targets **Models only** — recommend `/ts-object-model-builder` to upgrade
legacy Worksheets and stop.

**Display format.** Show results as a markdown table with columns
`# | Name | Owner | GUID | Modified`. The Owner column is the
`metadata_header.authorDisplayName` (fall back to `authorName` if the display name is
absent). On shared instances, name collisions across authors are common; without the
Owner column the user often picks the wrong object.

Save `{model_guid}` and `{model_name}`.

**Optional Snowflake profile.** Ask:

```
Mine the underlying Snowflake query history for real-world question patterns? (Y / N)
(requires a Snowflake profile with ACCOUNT_USAGE access; defaults to N)
```

If Y, prompt for Snowflake profile name and save as `{sf_profile_name}`.

Create the run directory:

```python
import time, pathlib
run_dir = pathlib.Path.home() / "Dev" / "coaching-runs" / f"{slug(model_name)}-{int(time.time())}"
run_dir.mkdir(parents=True, exist_ok=True)
```

---

## Step 2 — Export Model TML; Extract Schema and Existing AI Assets

Export the Model bundle:

```bash
source ~/.zshenv && ts tml export {model_guid} \
  --profile "{profile_name}" --fqn --associated --parse > {run_dir}/model_bundle.json
```

Parse and extract two structured outputs:

### 2a. Schema (drives candidate generation in Steps 3 + 6)

```python
import json
data = json.loads(open(run_dir/"model_bundle.json").read())

model = next(i["tml"]["model"] for i in data if i["type"] == "model")
columns = model.get("columns", [])
formulas = model.get("formulas", [])

# Classify columns. The Model TML may not populate properties.data_type for every
# column — fall back to NAME PATTERN for date detection (e.g. "Transaction Date",
# "Order Date" → date dim even when data_type is None).
import re
DATE_NAME_RE = re.compile(r'\b(date|datetime|timestamp|time|day|month|quarter|year)\b', re.I)
measures   = [c for c in columns if c.get("properties",{}).get("column_type") == "MEASURE"]
attributes = [c for c in columns if c.get("properties",{}).get("column_type") == "ATTRIBUTE"]
date_dims  = [c for c in attributes if DATE_NAME_RE.search(c["name"]) or c.get("properties",{}).get("data_type") in ("DATE","DATE_TIME","TIMESTAMP")]
non_date_attrs = [c for c in attributes if c not in date_dims]
```

Joins live at the **physical-table level** (`table_tml.table.joins_with`), not on
`model.model_tables[].joins_with` (which is empty in most exports). Aggregate them:

```python
table_items = [i for i in data if i["type"] == "table"]
joins = []
for t in table_items:
    for j in t["tml"]["table"].get("joins_with", []):
        joins.append({
            "from_table": t["tml"]["table"]["name"],
            "to_table":   j.get("destination", {}).get("name"),
            "type":       j.get("type"),
        })
# A dim is a "join key" (D_join in scoring) when its table is a join target for ≥2 tables.
join_target_counts = {}
for j in joins:
    join_target_counts[j["to_table"]] = join_target_counts.get(j["to_table"], 0) + 1
```

### 2b. Existing AI assets (drives the critique in Step 4)

Pull two categories of existing assets:

1. **Model TML assets** (`model.description`, `columns[].properties.ai_context`,
   `columns[].properties.synonyms[]`) — read directly from the bundle parsed in 2a.
2. **Existing feedback entries** — NOT in the bundle. `ts tml export --associated`
   does not surface `nls_feedback` (verified, see
   [open-items.md](references/open-items.md) #2). Enumerate via the metadata
   dependents API:

```python
import urllib.request
req = urllib.request.Request(
    f"{base_url}/api/rest/2.0/metadata/search", method="POST",
    headers={"Authorization": f"Bearer {token}", "X-Requested-By": "ThoughtSpot",
             "Content-Type": "application/json"},
    data=json.dumps({
        "metadata": [{"identifier": model_guid, "type": "LOGICAL_TABLE"}],
        "include_dependent_objects": True,
        "dependent_object_version":  "V2",
    }).encode(),
)
body = json.loads(urllib.request.urlopen(req, timeout=60).read())
fb_entries = body[0]["dependent_objects"]["dependents"][model_guid].get("FEEDBACK", []) or []

# Each entry has: id, name (= feedback_phrase), description (= type:
# REFERENCE_QUESTION / BUSINESS_TERM), authorName, authorDisplayName, modified.
# The full feedback content (search_tokens, formula_info, access level, chart_type,
# display_mode) is NOT exposed by this endpoint and is currently NOT retrievable on
# Cloud — see [open-items.md](references/open-items.md) #2 "Feedback content
# retrieval" sub-section, cross-referenced with ts-dependency-manager #18.
```

**Header-only fallback.** Since search_tokens and access level are unavailable, the
skill cannot:
- Split existing feedback into GLOBAL vs USER (Step 5 USER opt-in collapses to a
  no-op; treat as if no USER entries exist for signal purposes)
- Use existing `feedback_phrase` strings as paraphrase variants in Step 6.3 (no
  matching `search_tokens` to anchor them to)
- Critique stale references in Step 4 §4b (no tokens to validate against the
  current schema)

What the skill CAN still do header-only:
- Deduplicate by exact `feedback_phrase` match in Step 6 (case-insensitive)
- Show counts and a phrase preview in the Step 5 critique summary
- Surface entries whose `name`/phrase references columns no longer in the Model as
  a soft warning ("phrase mentions a column not on the Model — review manually")

When feedback content retrieval is restored (open-item #2 follow-up), this section
should re-enable the GLOBAL/USER split, paraphrase variant generation, and full
stale-reference critique.

```python
existing = {
    "model_description": model.get("description", "").strip(),
    "spotter_enabled":   model.get("properties",{}).get("spotter_config",{}).get("is_spotter_enabled", False),
    "columns_with_ai_context": [(c["name"], c["properties"]["ai_context"])
                                 for c in columns if c.get("properties",{}).get("ai_context")],
    "columns_with_synonyms":   [(c["name"], c.get("properties",{}).get("synonyms", []),
                                 c.get("properties",{}).get("synonym_type", ""))
                                 for c in columns if c.get("properties",{}).get("synonyms")],
    "existing_feedback_headers": [
        {"id": e["id"], "phrase": e["name"], "type": e.get("description","UNKNOWN"),
         "author": e.get("authorName"), "modified": e.get("modified")}
        for e in fb_entries
    ],
    "feedback_content_retrievable": False,  # see open-items.md #2 follow-up
    # Reserved for when content retrieval is restored:
    "existing_feedback_global": [],
    "existing_feedback_user":   [],
}
```

Persist both to `{run_dir}/schema.json` and `{run_dir}/existing_assets.json`.

---

## Step 3 — Mine Candidate Sources

Three sub-steps — run all that apply.

### 3a. Dependent Liveboards/Answers via verified v2 API

The CLI `ts metadata search` does not yet expose `--include-dependent-objects`. Use the
verified API contract documented in this skill's
[open-items.md](references/open-items.md) #1 (independently verified for the
ts-dependency-manager skill on the `wip/ts-dependency-manager` branch) — fast (~2s),
VERIFIED on Cloud:

```python
import urllib.request, json, os
profs = json.load(open(os.path.expanduser("~/.claude/thoughtspot-profiles.json")))
profs = profs.get("profiles", profs) if isinstance(profs, dict) else profs
prof = next(p for p in profs if p["name"] == profile_name)
token = os.environ[prof["token_env"]]

req = urllib.request.Request(
    f"{base_url}/api/rest/2.0/metadata/search",
    method="POST",
    headers={"Authorization": f"Bearer {token}", "X-Requested-By": "ThoughtSpot",
             "Content-Type": "application/json"},
    data=json.dumps({
        "metadata": [{"identifier": model_guid, "type": "LOGICAL_TABLE"}],
        "include_dependent_objects": True,
        "dependent_object_version": "V2",
    }).encode(),
)
with urllib.request.urlopen(req, timeout=60) as r:
    body = json.loads(r.read())

deps_node  = body[0].get("dependent_objects",{}).get("dependents",{}).get(model_guid, {})
answers    = deps_node.get("QUESTION_ANSWER_BOOK", []) or []
liveboards = deps_node.get("PINBOARD_ANSWER_BOOK", []) or []
```

Then export each dependent's TML and harvest:
- `answer.search_query` (tokenised — feeds taxonomy ranking)
- `answer.name`, `answer.description`, `answer.dynamic_name`, `answer.dynamic_description`
- For Liveboards: `liveboard.name`, `liveboard.description`, each
  `liveboard.visualizations[].answer.name` and per-tile `description`
  (these are the **highest signal** — analysts label tiles in business language)

Save all mined prose to `{run_dir}/mined_prose.json` and the search_queries to
`{run_dir}/mined_searches.json`. The two have separate downstream consumers.

### 3b. Snowflake query history (optional)

If `{sf_profile_name}` is set AND the Model is Snowflake-backed (check
`table_items[].tml.table.connection.type == "SNOWFLAKE"`):

Use `QUERY_PARAMETERIZED_HASH` to group queries by structure (different literals collapse
to the same hash). Filter out internal ThoughtSpot tasks (SAGE_INDEXING, SAGE_SAMPLING,
A3*) by filtering on the comment block:

```sql
WITH ranked AS (
  SELECT QUERY_PARAMETERIZED_HASH,
         ANY_VALUE(QUERY_TEXT) AS sample_query,
         COUNT(*) AS run_count
  FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
  WHERE QUERY_TEXT ILIKE '%{db}.{schema}.DM_%'
    AND START_TIME >= DATEADD('day', -90, CURRENT_TIMESTAMP())
    AND EXECUTION_STATUS = 'SUCCESS' AND QUERY_TYPE = 'SELECT'
    AND USER_NAME NOT LIKE 'ETL_%'
    AND CONTAINS(UPPER(QUERY_TEXT), 'GROUP BY')
    AND NOT QUERY_TEXT ILIKE '%task: SAGE_%'
    AND NOT QUERY_TEXT ILIKE '%task: A3%'
  GROUP BY QUERY_PARAMETERIZED_HASH
)
SELECT * FROM ranked WHERE run_count >= 2 ORDER BY run_count DESC LIMIT 30;
```

> **Real-world finding:** demo / TS-fronted Snowflake accounts often have **zero**
> useful patterns — the workload is dominated by ThoughtSpot's own indexing. If the
> result is empty, log it and proceed with mined prose + schema only. Don't error.

### 3c. Prose mining

Per [prose-mining-rules.md](references/prose-mining-rules.md): extract noun phrases from
all mined prose (model description, Answer/Liveboard names + descriptions, tile names),
match them against Model column display names with stem overlap, and emit two outputs:

- **Synonym candidates per column** — phrases that look like alternative names
  (`"inventory levels"` ↔ `[Inventory Balance]`)
- **Question seeds** — full sentences that read like business questions
  (`"growth in sales amounts"` → seed a YoY question with that phrasing)

Save to `{run_dir}/mined_prose_extract.json`.

### 3d. Existing GLOBAL feedback as input signal

Already-curated `access: GLOBAL` Reference Questions and Business Terms on the Model
are the **highest-quality input** available — an analyst has explicitly promoted them
for shared use. They feed:

- **Paraphrase variant generation** (Step 6.3) — existing `feedback_phrase` strings are
  pre-validated NL phrasings; reuse them as variants for any new question with
  matching `search_tokens`.
- **Synonym proposal validation** (Step 6.2) — existing `BUSINESS_TERM` entries show
  which phrase→column mappings the team has already accepted; don't propose
  competitors.
- **Ranking** (per [question-taxonomy.md](references/question-taxonomy.md)) — patterns
  that share `search_tokens` shape with an existing GLOBAL entry get `+4` (signals an
  important measure×dim combination); identical `feedback_phrase` matches drop the
  candidate and mark the existing entry as `KEEP`.

`access: USER` entries are excluded from input signal by default — they're private
and may be unreviewed. The user opts them in via the Step 5 scope menu prompt
(see [ai-asset-review-rules.md §4a](references/ai-asset-review-rules.md)).

```python
# Already extracted in Step 2b — just compile the per-pattern lookup
import re
def tokens_of(s):
    return set(re.findall(r'\[([^\]]+)\]', s.lower()))

global_token_shapes = [tokens_of(e["search_tokens"]) for e in existing_feedback_global
                        if e.get("type") == "REFERENCE_QUESTION"]
global_phrase_to_col = {e["feedback_phrase"].lower(): tokens_of(e["search_tokens"])
                        for e in existing_feedback_global
                        if e.get("type") == "BUSINESS_TERM"}
```

Stash both into `{run_dir}/feedback_signal.json` for Step 4 (review) and Step 6
(generation).

---

## Step 4 — Review Existing AI Assets — Produce Critique + Deltas

For each existing asset, score it against mined evidence and produce a delta proposal.
Full heuristics in [ai-asset-review-rules.md](references/ai-asset-review-rules.md).
Summary:

| Asset | Critique signals | Delta types |
|---|---|---|
| `model.description` | Length < 100 chars; missing key entities/measures present in mined prose | `KEEP` / `EXPAND` / `REWRITE` |
| `column.ai_context` | Empty; shorter than 30 chars; doesn't mention column purpose; contradicts mined prose | `ADD` / `REFINE` / `KEEP` |
| `column.synonyms` | Empty; missing high-frequency phrases from mined prose; redundant with display name | `ADD_PHRASES` / `REMOVE_REDUNDANT` / `KEEP` |
| `nls_feedback` GLOBAL entries | Stale references; downvoted entries; matches new candidate | `KEEP` / `FLAG_FOR_HUMAN` |
| `nls_feedback` USER entries | Out of scope by default; surface count only | `KEEP_OUT_OF_SCOPE` (default) |
| `nls_feedback` (header-only mode) | Phrase mentions a column not on the Model | `FLAG_FOR_HUMAN` (soft warning only — token-level critique unavailable; see [open-items.md](references/open-items.md) #2 sub) |

Per [ai-asset-review-rules.md §4](references/ai-asset-review-rules.md):
- **GLOBAL feedback** is treated as authoritative — preserved, used as input signal
  for Step 6, never silently overwritten
- **USER feedback** is gated behind the Step 5 opt-in. Default: skip entirely; not
  used as signal, not modified
- Stale references (entries pointing to columns/formulas no longer on the Model) get
  `FLAG_FOR_HUMAN` so the user can decide whether to keep, edit, or remove via UI

Existing values are **never silently overwritten** — the user must explicitly accept
each `REFINE` or `REWRITE` in Step 7. Save the critique to `{run_dir}/existing_review.json`.

---

## Step 4.5 — Cross-Model Consistency Scan

Spotter doesn't disambiguate between same-named columns across Models the user
can reach. The same query may return different numbers depending on which Model
the user happens to hit — the central failure mode in enterprise text-to-SQL
(Axius, *"The 7-Table Fallacy"*, 2026). Full implementation rules in
[cross-model-consistency.md](references/cross-model-consistency.md). Summary:

For each column in this Model, search all Models the user can read in the org
and compare on:

1. `db_column_name` — different warehouse source ⇒ almost always different meaning
2. `column_type` — measure vs attribute mismatch
3. `aggregation` — sum vs avg = different semantics
4. Formula expression — for formula columns, does the math agree?
5. `ai_context` text — substring conflict heuristic

### Pre-scan gate

The scan is the only step that scales with tenant size, not target size. Show the
user the cost estimate and let them choose the scope before any work starts:

```
Step 4.5 — Cross-Model Consistency Scan

Found {N_models} readable Models on this profile.

First-run scan exports TML for each Model in parallel (4-way concurrent),
cached locally on (guid, modified_time). Subsequent runs only re-export
Models that have been modified since the last run.

  Estimated time:  ~{est_seconds // 60} minute(s) first run, seconds thereafter
  Cache location:  ~/.cache/ts-object-model-coach/tml-corpus/

Proceed?
  [Y]              run full scan (default)
  [filter <name>]  scope-by-name LIKE pattern (e.g., "filter Dunder")
  [N]              skip Step 4.5 entirely

Choose:
```

Time estimate: assume ~1.5s per uncached Model export at 4-way parallel
(`N / 4 * 1.5s`). A scan of 343 Models lands at ~2 min wall time first run.

If the user picks `filter <name>`, re-run the metadata search with
`--name "%<name>%"` and recompute the count. Skip option (`N`) writes an
empty `cross_model_consistency.md` and proceeds to Step 5 normally.

### Implementation

```python
import json, pathlib, subprocess, time
from concurrent.futures import ThreadPoolExecutor, as_completed

# 1. Enumerate readable Models (--all auto-paginates; default page size is 50).
res = subprocess.check_output([
    "ts", "metadata", "search",
    "--subtype", "WORKSHEET",
    "--all",
    "--profile", profile_name,
])
all_models = [r for r in json.loads(res)
              if r["metadata_header"].get("contentUpgradeId") != "WORKSHEET_TO_MODEL_UPGRADE"
              and r["metadata_header"].get("worksheetVersion") != "V1"
              and r["metadata_id"] != model_guid]

# 2. Resolve cache dirs and load FORBIDDEN cache (24h TTL).
cache_dir = pathlib.Path.home() / ".cache" / "ts-object-model-coach" / "tml-corpus"
cache_dir.mkdir(parents=True, exist_ok=True)
forbidden_cache_path = cache_dir.parent / "forbidden.json"
forbidden_cache = {}
if forbidden_cache_path.exists():
    raw = json.loads(forbidden_cache_path.read_text())
    cutoff_ms = (time.time() - 24 * 3600) * 1000
    forbidden_cache = {g: e for g, e in raw.items() if e.get("ts_ms", 0) > cutoff_ms}

# 3. Split into "hit cache", "skip — known-FORBIDDEN", and "needs export".
to_export, corpus = [], []
for m in all_models:
    if m["metadata_id"] in forbidden_cache:
        continue  # silently skip — user can clear ~/.cache/ts-object-model-coach/forbidden.json to retry
    cache_key = f"{m['metadata_id']}-{m['metadata_header']['modified']}.json"
    cache_path = cache_dir / cache_key
    if cache_path.exists():
        corpus.append(json.loads(cache_path.read_text()))
    else:
        # Evict stale entries for this guid before re-exporting
        for old in cache_dir.glob(f"{m['metadata_id']}-*.json"):
            old.unlink()
        to_export.append((m, cache_path))

# 4. Parallel export with progress reporting.
def _export_one(m, cache_path):
    try:
        out = subprocess.check_output(
            ["ts", "tml", "export", m["metadata_id"],
             "--profile", profile_name, "--fqn", "--parse"],
            stderr=subprocess.PIPE, timeout=60,
        )
        cache_path.write_bytes(out)
        return ("ok", m, json.loads(out))
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", "replace")
        if "FORBIDDEN" in err or "UNAUTHORIZED" in err:
            return ("forbidden", m, err[:200])
        return ("error", m, err[:200])
    except Exception as e:
        return ("error", m, str(e)[:200])

if to_export:
    print(f"  Exporting {len(to_export)} Model(s) — {len(corpus)} cached, "
          f"{len(forbidden_cache)} skipped (known FORBIDDEN).")
    completed = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_export_one, m, p): m for m, p in to_export}
        for future in as_completed(futures):
            completed += 1
            status, m, payload = future.result()
            if status == "ok":
                corpus.append(payload)
            elif status == "forbidden":
                forbidden_cache[m["metadata_id"]] = {
                    "ts_ms": int(time.time() * 1000),
                    "name": m["metadata_header"]["name"],
                    "error": payload,
                }
            # ("error", ...) — log and skip; will retry next run
            if completed % 25 == 0 or completed == len(to_export):
                print(f"  Exporting {completed}/{len(to_export)}...")

# 5. Persist FORBIDDEN cache for the next run.
forbidden_cache_path.write_text(json.dumps(forbidden_cache, indent=2))
```

Build the column-name → collisions index, run the divergence checks per
[cross-model-consistency.md](references/cross-model-consistency.md), and
write `{run_dir}/cross_model_consistency.md` with the explainer block from
[review-explainers.md](references/review-explainers.md) Block 6 prepended.

Until the heuristic is calibrated against a live tenant
([open-items.md](references/open-items.md) #15), default the proposed
RouteAction to `NEEDS_REVIEW` for every collision — let the user pick.

The scan output is referenced from the Step 5 critique summary; users can
defer review by picking `0` from the surface menu or skip it via the cross-Model
checkbox.

> **Performance notes.**
>
> - **`max_workers=4`** is chosen to be polite to the API while delivering ~4x
>   speedup. The endpoint tolerates higher concurrency, but 4 keeps the run
>   well under any sensible rate limit even on smaller TS instances.
> - **FORBIDDEN cache TTL is 24 h** to handle daily permission changes without
>   re-paying the discovery cost on every run. Clear
>   `~/.cache/ts-object-model-coach/forbidden.json` to force a re-check.
> - **Successful TML caches do not expire** — they're keyed on `modified_time`,
>   so a Model edit naturally invalidates its entry. Stale entries for the
>   same guid are evicted on miss.

---

## Step 5 — Show Critique; Pick Which Surfaces to Generate

Display the critique summary, ask about USER feedback inclusion, then show the
scope menu. Example output:

```
=== Existing AI assets on "Dunder Mifflin Sales & Inventory" ===

Model description:               Present (430 chars, AI-generated)
                                 Critique: KEEP — coverage is good
Column AI Context:               0 / 19 columns populated
Column Synonyms:                 0 / 19 columns populated
Existing feedback (GLOBAL):      0 entries        — used as input signal
Existing feedback (USER):        0 entries        — private to creator
Spotter enabled:                 ✅

Cross-Model consistency scan:
  Scanned 47 Models you can read.
  Of this Model's 19 columns, 5 have name collisions in other Models.
  Of those, 2 look genuinely divergent (different db_column_name or formula),
  3 are duplicates with identical definitions.
  → cross_model_consistency.md generated; review in Step 7.
```

If `existing_feedback_user` is non-empty, ask:

```
This Model has {N_user} access:USER feedback entries (private to their creators).
By default these are excluded from this run — not used as signal, not modified.

Include them as input signal? (y/N, default N)
   - Y: existing USER entries seed paraphrase variants and influence ranking
        (treated like GLOBAL for the duration of this run only)
   - N: ignore them entirely; they remain untouched on the Model

Choose:
```

Save the answer as `include_user_feedback: bool` in `{run_dir}/scope.json`.

Then show the surface menu:

```
What would you like to generate or improve? (tick all that apply)

  [ ] 1. Column AI Context           — propose a 2-3 sentence business description per column
  [ ] 2. Column Synonyms             — propose alternative names per column (parser-level)
  [ ] 3. Reference Questions         — full NL question → tokenised search mappings (target ~15)
  [ ] 4. Business Terms              — phrase → column mappings (coaching-layer alternative)
  [ ] 5. Data Model Instructions     — global rules draft (manual paste — TML location TBD)
  [ ] 6. Improve Model description   — only shown when Step 4 critique is REWRITE/EXPAND
  [ ] 7. Cross-Model consistency     — review same-named-column collisions in other Models
                                        (only shown when Step 4.5 found ≥ 1 collision)

Enter numbers (e.g. "1,3,5"), "all", or "0" to skip generation but still review #7:
```

If the user selects **any** of #2 (Column Synonyms), #3 (Reference Questions), or #4
(Business Terms) — i.e. any phrase-coaching surface — display the **plain-English
explainer** from
[synonym-strategy-explainer.md](references/synonym-strategy-explainer.md) verbatim,
with all variables substituted from the user's data.

The explainer is informational, not a strategy choice — the skill auto-selects the
right Method per phrase using the decision tree:

| Phrase target | Method assigned | Surface |
|---|---|---|
| Maps to a single existing Model column | A — Synonym | `model.columns[].synonyms[]` |
| Maps to a calculation (formula) | B — Business Term | `nls_feedback` BUSINESS_TERM |
| Whole-sentence conversational phrasing | C — Reference Question | `nls_feedback` REFERENCE_QUESTION |

The user does NOT pick a global strategy ("A only" / "B only" / "Both"). Instead,
during Step 7 review they can override per row — change `KEEP` to `MOVE_TO_A`,
`MOVE_TO_B`, or `MOVE_TO_C` to route a phrase to a different Method. This per-row
control is the right level of granularity; global strategy was wrong.

After displaying the explainer, ask:

```
Continue with Method A/B/C auto-selection (you can override per row in Step 7)?
(Y / N):
```

Save the surface selection set and the user's confirmation as `{run_dir}/scope.json`.

---

## Step 6 — Generate Proposals Per Selected Surface

Per surface (only those selected in Step 5):

### 6.1 — Column AI Context (structured) + Column Description (prose)

`ai_context` is **structured-only** — closed enums and refs, never prose. The full
spec is in [ai-context-schema.md](references/ai-context-schema.md); concrete worked
examples are in [ai-context-examples.md](references/ai-context-examples.md). Step 6.1
generates two surfaces in parallel:

| Surface | Form | What goes here |
|---|---|---|
| `properties.ai_context` | Structured YAML — closed enums + refs only | Constraints the LLM needs to write correct SQL. Allowed keys: `additivity`, `non_additive_dimension`, `time_basis`, `source`, `grain_keys`, `unit`, `null_semantics`, `role` |
| `column.description` | Prose, 1–2 sentences (≤ 200 chars) | Business meaning, gotchas, edge cases, grain-in-words — the human-readable context |

#### Bootstrapping measures

For each measure column, bootstrap the **mandatory tier** (`additivity`,
`time_basis`, `grain_keys`) deterministically:

1. **`additivity`** — first-pass guess from `aggregation`:
   - `SUM` ⇒ `additive` unless mined evidence flags "snapshot" / "balance" /
     "closing" / "filled" → `semi_additive` candidate
   - `MAX` / `MIN` over a date column ⇒ `semi_additive` candidate
   - `COUNT_DISTINCT` and ratios/divisions ⇒ `non_additive`
2. **For `additivity: semi_additive`** — populate `non_additive_dimension`
   (the time-grain column the snapshot is anchored on). `additive_dimensions`
   is **NOT** an axis any more (removed 2026-04-29 — redundant with
   `non_additive_dimension`).
3. **`time_basis`** — for formula columns, infer from `formulas[]`
   `query_groups({DATE_DIM.DATE})`-style references. **Never copy formula text
   into `ai_context`.** Prefer the conformed shared date dim when one exists in
   the Model join graph. May be legitimately absent for time-agnostic measures.
4. **`grain_keys`** — list of column refs that uniquely identify one fact row.
   Derive from the table's primary key + the time_basis column.
5. **`source`** — **conditional override only.** Omit when `column_id: TABLE::COL`
   resolves cleanly via the table's `fqn`. Required when the column_id doesn't
   match the physical path (renamed/aliased columns, view-backed columns).

For optional axes on measures:
- **`unit`** — closed enum: `currency` / `count` / `ratio` / `percentage` /
  `duration`. Inferred from column name patterns and the underlying type.
- **`null_semantics`** — closed enum: `zero` / `unknown` / `no_snapshot`. For
  snapshot/balance measures, default to `no_snapshot`.

#### Bootstrapping dimensions

Dimensions get **at most three axes** in `ai_context`: `source` (conditional),
`null_semantics` (when NULL has business meaning), and `role` (the primary
dimensional axis).

| Dimension shape | What to populate |
|---|---|
| Has an id/code/label/key sibling on the same table (e.g. `Product Category` + `Product Category ID`) | `role:` on each — closed enum: `label` / `id` / `code` / `key` |
| Stand-alone label where NULL has business meaning | `role: label` + `null_semantics: unknown` |
| Renamed/aliased — `column_id` doesn't resolve | `source:` override (+ optionally `role:`) |
| Sole, unambiguous, resolves cleanly, no NULL semantics | **Empty.** `column.description` carries any prose. |
| Surrogate key, never user-facing | **Empty.** |

The `role` axis prevents the Test 3 Q-010 failure mode (LLM picked
`category_id` when the user asked for "category"). Combined with the system-prompt
rule below, it also reinforces the prevention of phantom dimension tables
(`DM_CATEGORY` etc.) when paired with the description prose.

#### Bootstrapping `column.description` (prose)

In parallel, generate `column.description` (prose, ≤ 200 chars) from:
- `mined_prose_extract.ai_context_evidence_per_column` (Step 3c)
- Existing `column.description` if present (preserve as primary signal)
- Mined Liveboard / Answer prose near the column reference

`column.description` is where business meaning, gotchas, and grain-in-words
live. Do not duplicate this content into `ai_context`.

#### Generator system-prompt rule

Include this clause **verbatim** in any LLM prompt that consumes TML + `ai_context`
(Spotter coaching prompts, third-party agent prompts, downstream SQL agents):

> *"This TML mixes ThoughtSpot DSL with metadata. Distinguish them when emitting SQL:*
>
> 1. *The `formulas[]` block contains **ThoughtSpot formula DSL**, not SQL.
>    Functions like `last_value(...)`, `query_groups(...)`, `growth_rate(...)`,
>    `cumulative_sum(...)` and any other TS-specific formula functions are **not**
>    SQL functions. Re-implement the formula's intent in target SQL from scratch —
>    never copy or partially translate the DSL.*
> 2. *Square-bracket column refs (`[Amount]`, `[Stock Quantity]`) and curly-brace
>    dim refs (`{DM_DATE_DIM.DATE}`) are **TS logical references**, not SQL
>    identifiers. Resolve each to its physical path via `column_id: TABLE::COL`
>    plus the table's `fqn` (or via an explicit `source:` axis when present, which
>    overrides column_id).*
> 3. *Column and table **display names** (e.g. `Total Sales`, `Inventory Balance`,
>    `Product Category`) are **TS logical names**. They are never valid SQL
>    identifiers — resolve them to physical paths the same way as bracket refs.*
> 4. *The `ai_context` block declares constraints on the column's result
>    (additivity, time_basis, grain_keys, role). Respect them when writing SQL; do
>    not infer constraints that are not declared. All prose context for a column
>    lives in `column.description`, not `ai_context`."*

#### Output and review

Propose each surface with a confidence score; flag low-confidence cases for
explicit review in Step 7. Low-confidence drivers: mined evidence is sparse,
`additivity` guess conflicts with mined evidence, no shared date dim detected for
`time_basis`, or an id/label/code/key sibling pair lacks a clear `role` assignment.

### 6.2 — Column Synonyms

For each column, compile a candidate synonym list from:
- Mined prose phrases matching the column name (stem overlap ≥ 0.6)
- Common business shorthands inferred from the column's apparent role
- User-defined existing synonyms (preserved)

Reject phrases that are exact substrings/supersets of the display name (e.g. don't add
`"inventory"` as a synonym of `Inventory Balance`).

### 6.3 — Reference Questions

Apply the taxonomy in [question-taxonomy.md](references/question-taxonomy.md): generate
~40 candidates across T1–T4, score by signals (mined search match +5, mined SQL match
+3, prose mention +2, join key +2, tier T1/T2 +1, formula required +1, duplicate of
existing entry → drop).

For each kept question, also generate **2–3 paraphrase variants** per
[token-mapping-rules.md](references/token-mapping-rules.md) §5 — e.g. canonical
*"Inventory Balance this month"* + variants *"how much stock do we have right now"*,
*"current inventory"*. All variants share the same `search_tokens` and `formula_info`,
differ only in `feedback_phrase`.

### 6.4 — Business Terms

Phrase → **existing** Model column or formula mappings, drawn from prose mining where:
- The phrase targets an existing **Model formula** (column synonyms can't reach formulas)
- OR the phrase needs `chart_type` / `display_mode` hints that a column synonym can't carry

**BUSINESS_TERMs cannot create new formulas inline** (verified
[open-items.md #12](references/open-items.md)). If a phrase needs a calculation that
doesn't exist on the Model:
1. The skill emits a `MOVE_TO_NEW_FORMULA` proposal in `business_terms.md`, NOT a
   default-KEEP BT entry
2. The user is directed to add the formula via `/ts-object-answer-promote` (or
   manually) first
3. On a subsequent run of `ts-object-model-coach`, the BT can target the new formula
   directly

**Required fields on every BT entry:**

```yaml
- type: BUSINESS_TERM
  access: GLOBAL
  feedback_phrase: "stock"
  parent_question: "stock"
  search_tokens: "[Inventory Balance]"   # MUST reference existing column or formula
  rating: UPVOTE
  display_mode: UNDEFINED                 # REQUIRED
  chart_type: KPI                         # REQUIRED (KPI is universally safe; see open-items.md #11)
```

Do NOT include `formula_info` on BT entries — verified rejected by the API.

See [token-mapping-rules.md §4](references/token-mapping-rules.md) for the full Method B
specification.

### 6.5 — Data Model Instructions (structured)

`model_instructions` is **structured-only** — closed enums and refs, never prose.
The full spec is in
[model-instructions-schema.md](references/model-instructions-schema.md). Follows
the same declarative-only discipline as per-column `ai_context`, just at Model
scope.

**Boundary** — only **untriggered global rules** belong here. Phrase-triggered
behavior ("when users say X, do Y") goes to `nls_feedback` (Surfaces 3 and 4),
not here. See
[model-instructions-schema.md § Boundary](references/model-instructions-schema.md#boundary--what-does-not-belong-here).

#### Bootstrapping the 5 categories

| Category | Bootstrap source |
|---|---|
| `exclusion_rules` | Mined prose mentioning "exclude", "ignore", "filter out"; existing CASE WHEN patterns in mined Snowflake SQL; analyst input on business semantics |
| `aggregation_defaults` | Columns with `column_type: ATTRIBUTE` whose name suggests an entity (`Customer Name`, `Order ID`) — bootstrap `count_distinct`. Mined query history showing repeated aggregation patterns. |
| `time_defaults` | Mined query window heuristics (the modal time range across mined queries); fiscal year metadata if present in connection settings |
| `output_formatting` | One rule per `ai_context.unit` value present in the Model — bootstrap conservative defaults (currency: no decimals, percentage: one decimal) |
| `schema_assumptions` | **`denormalized_attributes`**: every dimension column whose `column_id` lives on a parent table (rather than a dedicated dim table) is added — this is the meta-level reinforcement of the per-column phantom-table prevention. **`shared_conformed_date_dim`**: detect from `joins_with` graph — if multiple facts join through one date dim, it's the conformed anchor. **`surrogate_keys_only`**: tables whose PK columns have `column_id` like `*_KEY` and no business meaning. **`chasm_attribution`**: detect from `joins_with` graph — for each pair of fact tables (tables with MEASURE columns), compute shared dims (dims both join to) and unique dims; if `shared ≥ 1` AND (`A-only ≥ 1` OR `B-only ≥ 1`) emit a proposal. Default RouteAction `KEEP`; flag pairs with only one shared dim as `NEEDS_REVIEW` (single-shared-dim chasms have higher false-positive risk — analyst should confirm intent). See [model-instructions-schema.md § How `chasm_attribution` enables (and clarifies) cross-fact queries](references/model-instructions-schema.md#how-chasm_attribution-enables-and-clarifies-cross-fact-queries). |

#### Output

Generate the structured form to `{run_dir}/model_instructions.yaml` AND emit
the prose `instructions.md` for **manual paste** until
[open-items.md #4](references/open-items.md) verifies the TML location for
Model-level instructions. Once the location is verified, Step 9 will write
directly via `tml/import` and the manual-paste step becomes obsolete.

#### Validation

Same deploy-time validation as `ai_context` (Step 8b), applied at Model scope:
closed-key check, ref resolution, enum check, ≤ 80 char `note:` and `reason:`
fields. Validation failures block import.

#### Worked example

For Dunder Mifflin, a fully populated `model_instructions` is ~30 lines and
covers the Model-scope failure clusters from Test 4 plus the `chasm_attribution`
rule for the Inventory ↔ Order Detail pair (which has shared Product + Date but
no shared Customer/Region) — see
[model-instructions-schema.md § Worked example](references/model-instructions-schema.md#worked-example--full-model_instructions-for-dunder-mifflin).

#### Chasm-attribution detection algorithm (sketch)

```python
# Run after Step 2 (TML export) — operates on the parsed model graph.
fact_tables = [t for t in model["tables"] if any(
    c.get("properties", {}).get("column_type") == "MEASURE" for c in t["columns"])]

dim_joins_by_table = {}  # table_name -> set of dim col_refs it joins to
for jw in model.get("joins_with", []):
    a, b = parse_join_endpoints(jw["on"])  # e.g. "DM_INVENTORY::BALANCE_DATE = DM_DATE_DIM::DATE"
    dim_joins_by_table.setdefault(a.table, set()).add(b)
    dim_joins_by_table.setdefault(b.table, set()).add(a)

proposals = []
for fact_a, fact_b in itertools.combinations(fact_tables, 2):
    shared = dim_joins_by_table[fact_a.name] & dim_joins_by_table[fact_b.name]
    a_only = dim_joins_by_table[fact_a.name] - dim_joins_by_table[fact_b.name]
    b_only = dim_joins_by_table[fact_b.name] - dim_joins_by_table[fact_a.name]
    if len(shared) >= 1 and (a_only or b_only):
        confidence = "high" if len(shared) >= 2 else "low"
        proposals.append({
            "assumption": "chasm_attribution",
            "facts": [fact_a.name, fact_b.name],
            "shared_dims": sorted(shared),
            "note": f"non-shared values repeat across the other fact's unique dims",
            "_route_action": "KEEP" if confidence == "high" else "NEEDS_REVIEW",
        })
```

Pairs with **0 shared dims** are NOT chasm attributions (they have no bridging
dim) — never emit a proposal. Pairs with **1 shared dim** are flagged
`NEEDS_REVIEW` because single-shared-dim attributions have higher false-positive
risk (the analyst should confirm the cross-fact attribution is intended).

### 6.6 — Improved Model Description

Generate a single proposed replacement description, mentioning all primary
measures + dimensions present in the Model and any business context surfaced from
mined prose.

### 6.7 — Cross-Model Consistency Report

Format the collisions detected in Step 4.5 into the review file
`{run_dir}/cross_model_consistency.md`. Per
[cross-model-consistency.md](references/cross-model-consistency.md):

- Prepend the explainer block (Block 6 in
  [review-explainers.md](references/review-explainers.md))
- One row per column with ≥ 1 collision (skip columns with zero collisions —
  the file's purpose is to surface divergence, not enumerate non-issues)
- Default RouteAction = `NEEDS_REVIEW` until the heuristic is calibrated
  ([open-items.md #15](references/open-items.md))
- Auto-generate the "Suggested rationale" column from the heuristic; the user
  edits it during review

If a column is marked `DOCUMENT_DIFFERENCE`, append a `# CONFLICTS_WITH:`
annotation to that column's `ai_context` block during Step 8 build (uses
the rationale text from the review file). Future runs detect this annotation
and skip re-flagging the same collision unless underlying definitions change.

---

## Step 7 — Per-Surface Review with Explainer Blocks

For each generated surface, write a markdown file the user can edit directly.

**Prepend a 3-section explainer block** to each review file — *what this is for*,
*what we checked*, *rules for the outcomes you can pick*. The canonical text per
surface lives in [review-explainers.md](references/review-explainers.md). Display
it verbatim with placeholder substitutions (`{N_columns}`, `{N_filled}`,
`{N_models_scanned}`, etc.) so the user can pick decisions without re-reading
SKILL.md.

The Method labels (A/B/C) live within the relevant surface's explainer rather
than as separate headers — e.g. `synonyms.md` is Method A, `mappings.md` is
Method C. The full Method reasoning (when to use each, decision tree) is in
[synonym-strategy-explainer.md](references/synonym-strategy-explainer.md) and
is shown once at Step 5 before the surface menu.

Per-surface format:

| Surface | File | Explainer block | Notes |
|---|---|---|---|
| AI Context | `ai_context.md` | Block 1 in [review-explainers.md](references/review-explainers.md) | Table: column, current value, proposed YAML, action, slots filled (X / 9) |
| Synonyms | `synonyms.md` | Block 2 | METHOD A. Table: column, current synonyms, proposed additions, action |
| Reference Questions, Stage 1 | `candidates.md` | Block 3 | METHOD C — confirm questions |
| Reference Questions, Stage 2 | `mappings.md` | Block 4 | METHOD C — confirm tokens, variants, formulas |
| Business Terms | `business_terms.md` | Block 5 | METHOD B. Table: phrase, target formula, justification |
| Cross-Model Consistency | `cross_model_consistency.md` | Block 6 | Always shown when Step 4.5 found ≥ 1 collision |
| Description | `description.md` | Block 7 | Before/after diff |
| Data Model Instructions | `instructions.md` | Block 8 | Free-form draft + manual-paste guidance |

Each row has a `RouteAction` column with surface-specific allowed values. The
*per-surface* allowed values, defaults, and what each one does are in the
explainer block at the top of the file (Block 1–8 in
[review-explainers.md](references/review-explainers.md)). The shared / common
shape:

| RouteAction | Available on | Meaning |
|---|---|---|
| `KEEP` | All surfaces (default) | Apply this row using the surface's Method |
| `DROP` | All surfaces | Don't apply this row |
| `EDIT` | All surfaces | The user has edited the proposed value; treat as the new authoritative value |
| `MOVE_TO_A` | Synonyms, Reference Questions, Business Terms | Re-route this phrase to be a column synonym |
| `MOVE_TO_B` | Synonyms, Reference Questions | Re-route to be a Business Term + formula |
| `MOVE_TO_C` | Synonyms, Business Terms | Re-route to be a Reference Question |
| `MOVE_TO_NEW_FORMULA` | Business Terms only | Target formula doesn't exist; user runs `/ts-object-answer-promote` first |
| `KEEP_AS_IS` / `ALIGN` / `RENAME` / `DOCUMENT_DIFFERENCE` / `INTENTIONAL_DIFFERENCE` / `NEEDS_REVIEW` | Cross-Model Consistency only | See Block 6 |
| `EXPAND` / `REWRITE` | Description only | See Block 7 |
| `DEFER` | AI Context only | Skip this column this run; flag again next run |

This per-row override is the user's full control surface — there's no global
strategy choice. A phrase the user disagrees with as a Synonym can be moved to
a Business Term or Reference Question without leaving the review file.

Wait for the user to type `done` (or per-file `done`), re-read each file, parse the
RouteAction column, apply the routing, and ask for final confirmation per surface:

```
ai_context.md                 — kept 12 ADDs, 2 REFINEs, 5 KEEPs. Proceed? (Y / N):
synonyms.md                    — kept 18 ADDs, 6 routed to Method C, 11 dropped. Proceed? (Y / N):
business_terms.md              — kept 4 ADDs, 1 routed to Method A, 0 dropped. Proceed? (Y / N):
mappings.md                    — kept 28 questions, 4 routed to Method A. Proceed? (Y / N):
cross_model_consistency.md     — 2 RENAMEs, 1 DOCUMENT_DIFFERENCE, 2 KEEP_AS_IS. Proceed? (Y / N):
instructions.md                — kept 7 rules. Save for manual paste? (Y / N):
```

---

## Step 8 — Build Merged TML, Backup, Final Import Gate

### 8a. Backup current state

```python
import yaml, copy
backup_path = run_dir / "before" / "model.tml"
backup_path.parent.mkdir(parents=True, exist_ok=True)
backup_path.write_text(yaml.dump(model_tml, sort_keys=False))
if existing_feedback_entries:
    (run_dir / "before" / "feedback.tml").write_text(
        yaml.dump({"guid": model_guid,
                   "nls_feedback": {"feedback": existing_feedback_entries}}, sort_keys=False)
    )
```

### 8b. Build the patched Model TML (surfaces 1, 2, 6)

Deep-copy the original Model TML and apply each accepted delta:

```python
patched = copy.deepcopy(model_tml)
m = patched["model"]

# Surface 1 — column ai_context (structured-only) + column.description (prose)
for col in m.get("columns", []):
    delta = ai_context_deltas.get(col["name"])
    if delta and delta["action"] in ("ADD","REFINE"):
        col.setdefault("properties", {})["ai_context"] = delta["proposed_value"]
    desc_delta = description_deltas.get(col["name"])
    if desc_delta and desc_delta["action"] in ("ADD","REFINE"):
        col["description"] = desc_delta["proposed_value"]

# Validate ai_context per ai-context-schema.md § Safeguards. Block import on failure.
ALLOWED_KEYS = {"additivity","non_additive_dimension","time_basis","source",
                "grain_keys","unit","null_semantics","role"}
ENUM_ADDITIVITY = {"additive","semi_additive","non_additive"}
ENUM_UNIT = {"currency","count","ratio","percentage","duration"}
ENUM_NULL = {"zero","unknown","no_snapshot"}
ENUM_ROLE = {"label","id","code","key"}
errors = []
for col in m.get("columns", []):
    raw = col.get("properties", {}).get("ai_context")
    if not raw:
        continue
    if len(raw) > 400:
        errors.append(f"{col['name']}: ai_context exceeds 400 chars ({len(raw)})")
    parsed = yaml.safe_load(raw) if isinstance(raw, str) else raw
    if not isinstance(parsed, dict):
        errors.append(f"{col['name']}: ai_context must be a structured map, not prose")
        continue
    unknown = set(parsed.keys()) - ALLOWED_KEYS
    if unknown:
        errors.append(f"{col['name']}: unknown keys {unknown}; allowed: {ALLOWED_KEYS}")
    if "additivity" in parsed and parsed["additivity"] not in ENUM_ADDITIVITY:
        errors.append(f"{col['name']}: additivity must be one of {ENUM_ADDITIVITY}")
    if parsed.get("additivity") == "semi_additive" and "non_additive_dimension" not in parsed:
        errors.append(f"{col['name']}: semi_additive requires non_additive_dimension")
    if "unit" in parsed and parsed["unit"] not in ENUM_UNIT:
        errors.append(f"{col['name']}: unit must be one of {ENUM_UNIT}")
    if "null_semantics" in parsed and parsed["null_semantics"] not in ENUM_NULL:
        errors.append(f"{col['name']}: null_semantics must be one of {ENUM_NULL}")
    if "role" in parsed and parsed["role"] not in ENUM_ROLE:
        errors.append(f"{col['name']}: role must be one of {ENUM_ROLE}")
    # Reject prose: any string value containing whitespace + alpha words that don't match a ref shape
    enum_keys = ("additivity","unit","null_semantics","role")
    for k, v in parsed.items():
        if k in enum_keys:
            continue  # enums already validated
        values = v if isinstance(v, list) else [v]
        for item in values:
            if isinstance(item, str) and " " in item and "." not in item:
                errors.append(f"{col['name']}.{k}: free-text value rejected — use enums/refs only")
    # source / time_basis / non_additive_dimension resolution checked against schema
    src = parsed.get("source")
    if src and not _resolve_physical_column(src):
        errors.append(f"{col['name']}.source: '{src}' does not resolve to a physical column")
    tb = parsed.get("time_basis")
    if tb and not _resolve_model_column(m, tb):
        errors.append(f"{col['name']}.time_basis: '{tb}' is not a Model column")
    nad = parsed.get("non_additive_dimension")
    if nad and not _resolve_model_column(m, nad):
        errors.append(f"{col['name']}.non_additive_dimension: '{nad}' is not a Model column")
if errors:
    raise SystemExit("ai_context validation failed:\n  " + "\n  ".join(errors))

# Surface 2 — column synonyms
for col in m.get("columns", []):
    delta = synonym_deltas.get(col["name"])
    if delta and delta["action"] in ("ADD_PHRASES",):
        existing = set(col.get("synonyms", []))
        new = list(existing.union(delta["proposed_additions"]))
        col["synonyms"] = sorted(new)
        col.setdefault("properties", {})["synonym_type"] = "USER_DEFINED"

# Surface 6 — model description
if description_delta and description_delta["action"] in ("EXPAND","REWRITE"):
    m["description"] = description_delta["proposed_value"]
```

Run the Model TML self-validation checklist from
[~/.claude/shared/schemas/thoughtspot-model-tml.md](~/.claude/shared/schemas/thoughtspot-model-tml.md)
before serialising.

### 8c. Build the merged feedback TML (surfaces 3, 4)

> **Verified API behaviour (2026-04-27):** the `nls_feedback` TML import
> wholesale REPLACES the Model's feedback collection with the payload. There
> is no append/merge mode at the API. Per
> [open-items.md #18](references/open-items.md) the skill simulates
> merge-with-preservation by fetching existing entries first, then including
> them in the import payload alongside the new ones.

#### Step 1 — Fetch existing feedback content (full, not headers)

Per [open-items.md #2 sub](references/open-items.md) (verified retrievable
2026-04-27), use `tml/export` with `type=FEEDBACK` against the Model GUID:

```python
import urllib.request, json, yaml
req = urllib.request.Request(
    f"{base_url}/api/rest/2.0/metadata/tml/export", method="POST",
    headers={"Authorization": f"Bearer {token}", "X-Requested-By": "ThoughtSpot",
             "Content-Type": "application/json"},
    data=json.dumps({
        "metadata": [{"identifier": model_guid, "type": "FEEDBACK"}],
        "edoc_format": "YAML",
    }).encode(),
)
body = json.loads(urllib.request.urlopen(req, timeout=30).read())
edoc = body[0].get("edoc") if body else ""
existing_payload = yaml.safe_load(edoc) if edoc else {"nls_feedback": {"feedback": []}}
existing_entries = existing_payload.get("nls_feedback", {}).get("feedback", []) or []
```

`existing_entries` now contains the full content (`search_tokens`,
`formula_info`, `chart_type`, `display_mode`, `parent_question`, `access`,
`rating`, `axis_config`, etc.) — ready to round-trip back into the import.

#### Step 2 — Build the merged payload

Re-id the new entries to avoid collision with existing IDs, then concatenate.
The API will "replace" the collection, but the collection now contains
everything we want to keep:

```python
def next_id(used_ids):
    n = 1
    while str(n) in used_ids: n += 1
    return str(n)

merged = list(existing_entries)
used_ids = {str(e.get("id","")) for e in merged}
for e in new_reference_questions + new_business_terms:
    e["id"] = next_id(used_ids); used_ids.add(e["id"])
    merged.append(e)

feedback_tml = {"guid": model_guid, "nls_feedback": {"feedback": merged}}
```

#### Step 3 — Generated entries must use verified-only syntax

Every emitted `search_tokens`, `chart_type`, `display_mode`, and `axis_config`
value must follow the verified-working forms in
[feedback-tml-verified-patterns.md](references/feedback-tml-verified-patterns.md).
Forms not yet verified (untested keywords / positions) must NOT be emitted —
either drop the question or route via `MOVE_TO_NEW_FORMULA` (per
[#17](references/open-items.md)) / `DEFER`.

### 8d. Save instructions.md (surface 5 — manual paste)

```python
(run_dir / "instructions.md").write_text(generated_instructions)
```

### 8e. Final confirmation gate

```
Ready to apply coaching to "{model_name}":

  Column AI Context updates:    {N_ai_add} ADDs, {N_ai_refine} REFINEs
                                 (structured-only — declarative validation +
                                  ≤ 400 chars per column; see ai-context-schema.md
                                  § Safeguards)
  Column Description updates:   {N_desc_add} ADDs, {N_desc_refine} REFINEs
                                 (prose surface; ai_context contains no prose)
  Column Synonyms updates:      {N_syn_add} ADDs, {N_syn_keep} KEEPs
  Reference Questions to add:   {N_ref}      (existing: {N_existing_ref})
                                 ⚠ {N_existing_ref} existing entries WILL BE
                                  REPLACED by the import — see open-items.md #18
                                 ⚠ Formula-bearing tiers (t2.cumulative,
                                  t3.avg_per, t3.ratio, t3.share_of_total, t4.*)
                                  DEFERRED until #17 verified
                                 ⚠ Keyword-bearing tiers (t1.top_n,
                                  t2.recent_period, t2.this_vs_last,
                                  t3.year_filter) DEFERRED until #16 verified
  Business Terms to add:        {N_bt}        (existing: {N_existing_bt})
  Model description:            {DESCRIPTION_ACTION}
  Data Model Instructions:      {N_instr} draft rule(s) — for manual paste

  Backup saved to:   {run_dir}/before/
  Patched files at:  {run_dir}/after/

Proceed with import? (Y / N):
```

If N, exit gracefully — leave the run dir in place so the user can re-run or hand-edit.

---

## Step 9 — Import + Smoke Test

### 9a. Import patched Model TML (if any of surfaces 1, 2, 6 are non-empty)

```bash
source ~/.zshenv && ts tml import \
  --profile "{profile_name}" --policy ALL_OR_NONE --no-create-new \
  < {run_dir}/after/model.tml
```

### 9b. Import feedback TML (if any of surfaces 3, 4 are non-empty)

```bash
source ~/.zshenv && ts tml import \
  --profile "{profile_name}" --policy ALL_OR_NONE --no-create-new \
  < {run_dir}/after/feedback.tml
```

> **Open item:** standalone `nls_feedback` import vs bundled-with-model — see
> [open-items.md](references/open-items.md) #2 for the verification test.

### 9c. Smoke-test

Verification is split between two endpoints — `--associated` does **NOT** surface
feedback entries even when they exist (verified [open-items.md #2](references/open-items.md)).

**For Model TML changes (surfaces 1, 2, 6) — use `--associated`:**

```bash
source ~/.zshenv && ts tml export {model_guid} \
  --profile "{profile_name}" --fqn --associated --parse
```

Parse the response and confirm column-by-column:
- All `properties.ai_context` updates round-tripped (NB: `ai_context` lives in
  `properties.ai_context`)
- All `properties.synonyms[]` additions round-tripped (NB: synonyms live in
  `properties.synonyms`, NOT at column-level — see open-items.md #3)
- `model.description` matches if updated

**For feedback entries (surfaces 3, 4) — use `metadata/search` with `include_dependent_objects`:**

```python
import urllib.request, json
req = urllib.request.Request(
    f"{base_url}/api/rest/2.0/metadata/search", method="POST",
    headers={"Authorization": f"Bearer {token}", "X-Requested-By": "ThoughtSpot",
             "Content-Type": "application/json"},
    data=json.dumps({
        "metadata": [{"identifier": model_guid, "type": "LOGICAL_TABLE"}],
        "include_dependent_objects": True,
        "dependent_object_version": "V2",
    }).encode(),
)
body = json.loads(urllib.request.urlopen(req).read())
feedback = body[0]["dependent_objects"]["dependents"][model_guid].get("FEEDBACK", [])

# Each entry: {id, name (= feedback_phrase), description (= type), author, created, ...}
expected_count = len(existing_feedback_entries) + ref_qs_added + bt_added
assert len(feedback) == expected_count, f"Expected {expected_count}, found {len(feedback)}"
```

**Important: feedback import response interpretation:**
- Successful imports return `{header, status: {status_code: OK}}` with empty
  `diff: {}` and no `object` field — different shape from Model TML imports
- Don't interpret empty diff as failure for feedback imports
- "Duplicates will be replaced" warnings are accurate (referencing prior-run entries)

Surface any silent drops to the user (known TML import failure modes per
`feedback_ts_tml_import_constraints` memory). Common causes:
- Formula expression syntax invalid (BUSINESS_TERM with bad formulas) — entries
  drop with EDOC_FEEDBACK_TML_INVALID error in the response
- Invalid `chart_type` (e.g. `TABLE` is rejected; see open-items.md #11 for the
  verified valid set)
- References to columns/formulas no longer in the Model

### 9d. Final report

```
Coaching import complete for "{model_name}":

  AI Context applied:           {N_ai} columns
  Synonyms applied:             {N_syn} columns ({N_syn_phrases} total phrases)
  Reference Questions added:    {N_ref}
  Business Terms added:         {N_bt}
  Model description updated:    {Y/N}

  Data Model Instructions saved to: {run_dir}/instructions.md
    → paste these rules into the Spotter UI under Settings → Coach Spotter → Instructions

  Run directory: {run_dir}
  Rollback:      ts tml import --profile {profile_name} < {run_dir}/before/model.tml
                 (and feedback.tml if applicable)

Spotter will use the applied coaching on the next index refresh.
```

---

## Error Handling

| Symptom | Action |
|---|---|
| `ts auth whoami` returns 401 | Token expired — `/ts-profile-thoughtspot` to refresh |
| Selected data source is a Worksheet | Recommend `/ts-object-model-builder` to upgrade first; stop |
| No dependent Liveboards/Answers found in Step 3a | Reduce reference question target; rely on schema + prose only |
| Snowflake mining returns empty / SAGE-only | Log and proceed; demo accounts often have no analyst SQL |
| Snowflake `ACCOUNT_USAGE` returns 0 rows for any DM_ table | Verify role has `IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE` |
| User edits malform a markdown table | Re-show with structural pointer; do not silently drop rows |
| Import returns 403 / UNAUTHORIZED | User lacks edit access on the Model — surface clearly, stop |
| Import: `column not found` | A token references a column that doesn't exist — rebuild without that token |
| Import: `formula expression invalid` | Re-open `mappings.md` for user fix |
| Smoke-test shows missing entries | Likely silent drop on bad reference; diff and flag to user |
| `pyyaml` not installed | `pip install pyyaml` |

---

## Cleanup

The run directory at `~/Dev/coaching-runs/{slug}-{ts}/` is preserved deliberately —
backups + patched files are needed for rollback. To remove old runs:

```bash
find ~/Dev/coaching-runs -maxdepth 1 -mtime +30 -type d -exec rm -rf {} \;
```

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 2.1.0 | 2026-04-29 | **`ai_context` overhaul.** Structured-only — closed enums and refs; free-form prose moves to `column.description`. Allowed keys: `additivity`, `non_additive_dimension`, `time_basis`, `source` (conditional override), `grain_keys`, `unit`, `null_semantics`, `role`. Removed: `formula` axis (caused TS DSL transliteration failures in `agent-expressibility-eval` Test 4), `additive_dimensions` (redundant with `non_additive_dimension`). Added: `role` axis for dimensions (closed enum `label`/`id`/`code`/`key`) — addresses the Test 3 Q-010 id-vs-label confusion. `source` is now a conditional override — omit when `column_id: TABLE::COL` resolves cleanly via the table's `fqn`. New `references/ai-context-schema.md` is the authoritative spec; `references/ai-context-examples.md` collects 8 worked examples per failure cluster. Step 6.1 generates both `ai_context` (structured) and `column.description` (prose) in parallel and embeds a four-clause system-prompt rule (TS DSL is not SQL; bracket/curly refs resolve via column_id; display names are not SQL identifiers — don't infer phantom tables like `DM_CATEGORY` from column names; `ai_context` is authoritative). Step 8b adds deploy-time validation: closed-key check, enum check (incl. `role`), ref resolution, ≤ 400 chars, no prose values. Mandatory measure tier (`additivity`, `time_basis`, `grain_keys`) is never dropped under budget pressure. **`model_instructions` introduced.** Step 6.5 now generates a structured 5-category schema (`exclusion_rules`, `aggregation_defaults`, `time_defaults`, `output_formatting`, `schema_assumptions`) — same declarative-only discipline as `ai_context`, applied at Model scope. `schema_assumptions.denormalized_attributes` provides Model-level reinforcement of phantom-table prevention (lists denormalized columns once per Model rather than per-column). `schema_assumptions.chasm_attribution` declares fact-table pairs that share some dims but not all — encodes ThoughtSpot's chasm-trap attribution capability so external SQL agents handle fulfillment and marketing-attribution queries correctly (each fact aggregated at its own grain, attributed via shared dims with intentional value repetition across non-shared dims). Step 6.5 includes auto-detection from the `joins_with` graph; pairs with one shared dim are flagged `NEEDS_REVIEW`, pairs with ≥ 2 shared dims default to `KEEP`. Boundary: only untriggered global rules belong here; phrase-triggered rules (term aliases, default-by-phrase) are deferred to `nls_feedback` until a feedback-bundling decision lands. New `references/model-instructions-schema.md` is the authoritative spec. Cursor mirror bumped to v1.1.0 to match. |
| 2.0.0 | 2026-04-28 | **BREAKING:** skill renamed `ts-coach-model` → `ts-object-model-coach` to align with the `ts-object-{type}-{verb}` family pattern (see `.claude/rules/skill-naming.md`). Slash command, directory, smoke-test filename, and cache directory (`~/.cache/ts-object-model-coach/`) all change. Anyone with scripts or aliases pointing at the old name must update. Also formalises the cross-Model consistency scan (Step 4.5), per-surface explainer-block pattern, parallel TML export with progress + cache + pre-scan gate, and verified-pattern library mined from real coached Models — all of which landed in PR #9. |
| 1.0.0 | 2026-04-26 | Initial release — full Spotter coaching prep across five surfaces (Column AI Context, Column Synonyms, Reference Questions, Business Terms, Data Model Instructions draft). Reviews existing assets critically with KEEP/ADD/REFINE/REWRITE deltas; treats existing GLOBAL feedback as primary input signal with USER feedback gated behind explicit opt-in; mines schema + dependent Liveboard/Answer prose + (optional) Snowflake query history; up-front scope menu; worked-example explainer using the user's data; synonym-strategy explainer when both column synonyms and BUSINESS_TERM are selected. |
