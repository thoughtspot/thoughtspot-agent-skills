---
name: ts-coach-model
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
| 1 | **Column AI Context** | `model.columns[].properties.ai_context` (free text, per column) | Tells Spotter the business meaning of one column |
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
**ts-coach-model** — comprehensively prepare a Model for Spotter: review existing AI context/synonyms/description, mine dependent objects + (optionally) Snowflake history, then generate your chosen mix of column AI Context, Synonyms, Reference Questions, Business Terms, and a Data Model Instructions draft.

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

```python
# Enumerate readable Models. The CLI subtype filter pulls both Worksheets and
# Models — filter to Models via metadata_header.contentUpgradeId.
import subprocess, json
res = subprocess.check_output([
    "ts", "metadata", "search",
    "--subtype", "WORKSHEET",
    "--profile", profile_name,
])
all_models = [r for r in json.loads(res)
              if r["metadata_header"].get("contentUpgradeId") != "WORKSHEET_TO_MODEL_UPGRADE"
              and r["metadata_header"].get("worksheetVersion") != "V1"
              and r["metadata_id"] != model_guid]

# For each Model, export TML cached on (guid, modified_time_in_millis)
cache_dir = pathlib.Path.home() / ".cache" / "ts-coach-model" / "tml-corpus"
cache_dir.mkdir(parents=True, exist_ok=True)
corpus = []
for m in all_models:
    cache_key = f"{m['metadata_id']}-{m['metadata_header']['modified']}.json"
    cache_path = cache_dir / cache_key
    if not cache_path.exists():
        # Stale entries for this guid get cleared on miss
        for old in cache_dir.glob(f"{m['metadata_id']}-*.json"):
            old.unlink()
        subprocess.check_call([
            "ts", "tml", "export", m["metadata_id"],
            "--profile", profile_name, "--fqn", "--parse",
        ], stdout=open(cache_path, "w"))
    corpus.append(json.loads(cache_path.read_text()))
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

### 6.1 — Column AI Context

For each column lacking `ai_context` (or marked for refinement):

1. Aggregate evidence from prose mining: phrases that appear near this column reference
2. Build a 2–3 sentence description following the template in
   [ai-asset-review-rules.md](references/ai-asset-review-rules.md#ai-context-template):
   `{purpose} {grain/cardinality} {business significance from mined prose}`
3. Propose with confidence score; flag low-confidence cases for explicit review

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
3. On a subsequent run of `ts-coach-model`, the BT can target the new formula
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

### 6.5 — Data Model Instructions

Generate rule candidates from observed patterns in mined searches and Snowflake
history. Examples grounded in mined evidence:
- *"When users say 'last month' or 'past month', interpret as the last 30 days
  (Transaction Date is at the day grain)."*
- *"For revenue questions, use the Amount column unless explicitly asked about gross."*

Output as plain markdown — no TML construction (see open-items.md #4).

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

# Surface 1 — column ai_context
for col in m.get("columns", []):
    delta = ai_context_deltas.get(col["name"])
    if delta and delta["action"] in ("ADD","REFINE"):
        col.setdefault("properties", {})["ai_context"] = delta["proposed_value"]

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

Merge new entries with existing ones; never blow them away:

```python
def next_id(used_ids):
    n = 1
    while str(n) in used_ids: n += 1
    return str(n)

merged = list(existing_feedback_entries)
used_ids = {str(e.get("id","")) for e in merged}
for e in new_reference_questions + new_business_terms:
    e["id"] = next_id(used_ids); used_ids.add(e["id"])
    merged.append(e)

feedback_tml = {"guid": model_guid, "nls_feedback": {"feedback": merged}}
```

### 8d. Save instructions.md (surface 5 — manual paste)

```python
(run_dir / "instructions.md").write_text(generated_instructions)
```

### 8e. Final confirmation gate

```
Ready to apply coaching to "{model_name}":

  Column AI Context updates:    {N_ai_add} ADDs, {N_ai_refine} REFINEs
  Column Synonyms updates:      {N_syn_add} ADDs, {N_syn_keep} KEEPs
  Reference Questions to add:   {N_ref}      (existing: {N_existing_ref})
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
| 1.0.0 | 2026-04-26 | Initial release — full Spotter coaching prep across five surfaces (Column AI Context, Column Synonyms, Reference Questions, Business Terms, Data Model Instructions draft). Reviews existing assets critically with KEEP/ADD/REFINE/REWRITE deltas; treats existing GLOBAL feedback as primary input signal with USER feedback gated behind explicit opt-in; mines schema + dependent Liveboard/Answer prose + (optional) Snowflake query history; up-front scope menu; worked-example explainer using the user's data; synonym-strategy explainer when both column synonyms and BUSINESS_TERM are selected. |
