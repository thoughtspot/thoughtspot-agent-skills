---
name: ts-object-model-aggregates
description: Audit a ThoughtSpot Model's Liveboards and Answers to recommend, generate, and wire aggregate Models (26.6 aggregate-aware routing). Analyses which query shapes repeat, profiles compression against the warehouse, presents a marginal-gain curve, and creates warehouse DDL + aggregate Model TML + the aggregated_models association with confirmation gates.
---

# ThoughtSpot: Aggregate Model Advisor

ThoughtSpot 26.6 lets a primary Model declare associated **aggregate Models** via an
`aggregated_models` TML block — Search/Spotter/Liveboard queries transparently route
to a smaller, pre-aggregated table when its columns fully satisfy the query, cutting
scanned rows by orders of magnitude
([docs](https://docs.thoughtspot.com/cloud/26.6.0.cl/model-aggregate-aware)). Deciding
*which* aggregates to build is manual today — this skill automates the analysis:

1. Mines the Model's dependent Liveboards and Answers into normalized **query
   signatures** (what dimensions, date grain, filters, and measures each one uses).
2. Generalizes those signatures up a **grain lattice** and ranks candidate aggregate
   grains by weighted coverage.
3. Optionally profiles candidates against a live warehouse (or emits SQL for manual
   profiling) to replace coverage estimates with actual **compression ratios**.
4. Presents a **marginal-gain curve** — diminishing returns as more aggregates are
   added — and lets you pick the cut-off. Maintenance-cost judgment stays human.
5. Generates the warehouse DDL, the aggregate Table + Model TML, and the
   `aggregated_models` association patch for each approved candidate — **every**
   artifact is shown before it executes or imports, nothing happens silently.

All deterministic logic (signature parsing, measure decomposition, lattice
generalization, cost-based greedy selection, SQL/DDL generation, TML assembly) lives
in the `ts aggregate` command group (`tools/ts-cli/ts_cli/aggregate/`). This skill is
thin orchestration: authentication, object picking (with an Owner column), the
judgment calls no CLI can make (aggregate naming, ambiguous-measure review, RLS parity
sign-off, the cut-off point), and the confirmation gates between each artifact.

Dependent-walking reuses the same alias-aware v2 `metadata dependents` path
`ts-dependency-manager` uses. TML mining and object-picker conventions follow
`ts-object-model-coach`. Backup/rollback of the primary Model's TML reuses
`ts dependency backup`/`rollback`, exactly as `ts-dependency-manager` does.

**This skill is pre-merge.** Every item in
[references/open-items.md](references/open-items.md) is still OPEN — several of them
(non-additive routing, join-pruning fidelity, the `aggregated_models` TML shape
itself) are correctness-affecting, not just cosmetic. Treat every recommendation this
skill produces as provisional until Step 7's routing verification passes, and read the
open items before trusting a candidate the classifier or lattice flagged as ambiguous.

Ask one question at a time. Wait for each answer before proceeding.

---

## References

| File | Purpose |
|---|---|
| [references/open-items.md](references/open-items.md) | Eleven unverified behaviours (routing semantics, TML shape, precedence, casing, timezone/week-start drift, join-pruning fidelity) — read before trusting any recommendation, and before merging this skill to `main` |
| [references/measure-decomposition-rules.md](references/measure-decomposition-rules.md) | Human-readable mirror of the measure decomposition table; what to do when the classifier returns `UNKNOWN` |
| [../ts-profile-thoughtspot/SKILL.md](../ts-profile-thoughtspot/SKILL.md) | ThoughtSpot auth, profile config |
| [ts-profile-snowflake (Claude Code)](../../claude/ts-profile-snowflake/SKILL.md) | Claude Code: Snowflake profile for connected-mode profiling/history/DDL execution (Cortex Code CLI users use their native `cortex connections` instead) |
| [../ts-dependency-manager/SKILL.md](../ts-dependency-manager/SKILL.md) | The `ts dependency backup`/`rollback` pattern this skill reuses for the primary Model's TML in Step 6/7 |
| [../ts-object-model-spotql-query/SKILL.md](../ts-object-model-spotql-query/SKILL.md) | Used in Step 7 to compile a test query to warehouse SQL and confirm which table (primary vs. aggregate) it hits |
| [../../shared/schemas/thoughtspot-model-tml.md](../../shared/schemas/thoughtspot-model-tml.md) | Model TML structure — `model_tables`, `aggregated_models`, GUID/import rules |
| [../../shared/schemas/thoughtspot-table-tml.md](../../shared/schemas/thoughtspot-table-tml.md) | Table TML structure — column definitions for the registered aggregate table |
| [../../shared/schemas/thoughtspot-formula-patterns.md](../../shared/schemas/thoughtspot-formula-patterns.md) | RLS rule syntax (Table objects) and measure formula patterns |
| [tools/ts-cli/README.md](../../../tools/ts-cli/README.md) (`ts aggregate` section) | Full flag reference for `signatures`/`recommend`/`profile`/`history`/`generate` |

---

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- `ts` CLI installed: `pip install -e tools/ts-cli` (v0.46.0+ — the `ts aggregate` group)
- Python package: `pyyaml` (`pip install pyyaml`)
- Snowflake profile (optional — only for connected-mode profiling/history/DDL
  execution) — `/ts-profile-snowflake` (Claude Code) or an active `cortex connections`
  connection (Cortex Code CLI). v1 history mining is Snowflake-only; profiling/DDL
  support Snowflake, Databricks, and BigQuery dialects, but only Snowflake has a
  connected (vs. manual) execution path today.
- ThoughtSpot user must have **MODIFY** or **FULL** access on the target Model, plus
  the **Can manage data** privilege and edit access on the connection the aggregate
  table will register against (registration validates `table.schema` against the
  connection's own credentials — the connection must be able to see the schema the
  aggregate table lands in).

---

## Step 0 — Overview

On skill invocation, display this plan before doing any work:

---
**ts-object-model-aggregates** — audit a Model's usage, recommend aggregate grains
with quantified benefit, and generate the warehouse DDL + aggregate Model TML +
association patch, gated by your approval at every step.

  1.  Profile check ......................................... auto
  2.  Pick the primary Model (Owner column shown) ........... you choose
  3.  Extract query signatures from dependents .............. auto
  4.  Optional: mine Snowflake query history for weights .... you choose
  5.  Recommend → profile → re-recommend → pick the cut-off . you confirm
  6.  Generate per selected candidate (DDL/table/model/assoc) you confirm at every gate
  7.  Verify routing ......................................... auto, you confirm on failure
  8.  Summary report ......................................... auto

Confirmation required: Steps 2, 4, 5, 6 (connection, DDL execution, table
registration fallback, RLS/CLS parity, each TML import), 7 (only if a rollback
decision is needed)
Auto-executed: Steps 1, 3, 8

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.

---

## Step 1 — Profile Check

Read `~/.claude/thoughtspot-profiles.json`. If missing or empty, tell the user to run
`/ts-profile-thoughtspot` first and stop. If multiple profiles exist, ask which to
use; if exactly one, confirm it.

```bash
source ~/.zshenv && ts auth whoami --profile "{profile_name}"
```

If this fails, the token may be expired — see `/ts-profile-thoughtspot`'s refresh
procedure. Save `{profile_name}` for all subsequent steps.

---

## Step 2 — Pick the Primary Model

This skill targets **Models only** (mirrors
[ts-object-model-coach Step 1](../ts-object-model-coach/SKILL.md)). Accept `--guid`
directly, or search:

```bash
source ~/.zshenv && ts metadata search \
  --subtype WORKSHEET --name "%{search_term}%" --profile "{profile_name}"
```

Classify each result `[MODEL]` or `[WORKSHEET]` using
`metadata_header.contentUpgradeId` / `worksheetVersion` (same logic as
[ts-object-answer-promote Step 5](../ts-object-answer-promote/SKILL.md)). If the user
picks a Worksheet, tell them it must be upgraded to a Model first and stop — this
skill's `ts aggregate signatures` command reads `model.model_tables`/`aggregated_models`,
which don't exist on a plain Worksheet.

**Display format.** Show results as a markdown table with columns
`# | Name | Owner | GUID | Modified`. Owner is
`metadata_header.authorDisplayName` (fall back to `authorName`); Modified is
`metadata_header.modified` (epoch millis) rendered as an ISO date. On shared
instances, name collisions across authors are common — without the Owner column the
user often picks the wrong Model.

Save `{model_guid}` and `{model_name}`. Create the working directory:

```python
import time, pathlib
workdir = pathlib.Path.home() / "Dev" / "aggregate-runs" / f"{slug(model_name)}-{int(time.time())}"
workdir.mkdir(parents=True, exist_ok=True)
```

---

## Step 3 — Extract Query Signatures

```bash
source ~/.zshenv && ts aggregate signatures \
  --model {model_guid} --profile "{profile_name}" --out "{workdir}"
```

Writes `{workdir}/model.tml.yaml` and `{workdir}/signatures.jsonl`. Stdout JSON:
`{"model_guid", "signatures", "full", "partial", "dependents", "export_failures"}`.
Report to the user:

```
Extracted {full} full + {partial} partial signatures from {dependents} dependent
Answer(s)/Liveboard(s) ({export_failures} export failure(s), skipped — not fatal).
```

`partial` signatures had a `search_query` token the parser couldn't resolve against
the Model's columns — they're excluded from coverage scoring but counted so coverage
percentages stay honest. If `partial` is large relative to `full`, note
[open-items.md #8](references/open-items.md#8--real-tml-search_query-token-casing--open)
(possible token-casing mismatch) as a likely cause and flag it in the final report.

### Export each `model_tables` Table TML

`recommend` doesn't need this, but `profile` and `generate` both do (a
`--tables-dir` of `<NAME>.tml.yaml` files, one per `model_tables` entry, keyed by the
table's exact `name:` — case-sensitive). Do this now so it's out of the way:

```python
import json, subprocess, yaml, pathlib

model_tml = yaml.safe_load(open(f"{workdir}/model.tml.yaml").read())
tables_dir = pathlib.Path(workdir) / "tables"
tables_dir.mkdir(parents=True, exist_ok=True)

physical_tables = []  # (display_name, db_table, connection_type) — used in Steps 4/6
for entry in model_tml["model"]["model_tables"]:
    table_name, table_fqn = entry["name"], entry["fqn"]
    result = subprocess.run(
        ["bash", "-c",
         f"source ~/.zshenv && ts tml export {table_fqn} "
         f"--profile '{profile_name}' --fqn --parse"],
        capture_output=True, text=True,
    )
    body = json.loads(result.stdout)
    table_section = body[0]["tml"]["table"]
    (tables_dir / f"{table_name}.tml.yaml").write_text(
        yaml.dump({"table": table_section}, default_flow_style=False, allow_unicode=True)
    )
    physical_tables.append((
        table_name,
        table_section.get("db_table", table_name),
        table_section.get("connection", {}).get("type"),
    ))
```

If any export fails, note it and continue — a candidate that needs that table for its
`FROM`/join clauses will surface as `UnsupportedModelError` later (skipped, not
fatal) rather than blocking the whole run.

---

## Step 4 — Optional: Mine Snowflake Query History

Ask:

```
Mine the underlying Snowflake query history to weight signatures by actual usage
frequency (rather than treating every dependent as equally important)? (Y / N)
Requires a Snowflake profile with ACCOUNT_USAGE access. v1 history mining is
Snowflake-only — skip this if the Model's tables live on Databricks or BigQuery.
```

Check `physical_tables` from Step 3 for `connection_type == "SNOWFLAKE"`. If none of
the Model's tables are Snowflake-backed, tell the user history mining isn't available
for this Model's source and skip straight to Step 5.

If Y, prompt for the Snowflake profile name (`{sf_profile_name}`) and run:

```bash
source ~/.zshenv && ts aggregate history \
  --dir "{workdir}" --snowflake-profile "{sf_profile_name}" \
  --tables "{comma_separated_db_table_names}" --days 30
```

`--tables` is the comma-separated **physical** table names (the `db_table` values
collected in Step 3, not the Model's display names). Writes `{workdir}/weights.json`.
Stdout: `{"history_rows", "weighted_signatures"}`. Save `{sf_profile_name}` — Step 5
can reuse it for connected-mode profiling.

If N (or history mining doesn't apply), proceed to Step 5 without `weights.json` —
`recommend` treats every signature with weight 1.0 (coverage-only mode) and the final
report notes this explicitly rather than presenting an unweighted curve as if it
reflected real usage.

---

## Step 5 — Recommend, Profile, Re-recommend, Pick the Cut-off

### 5a. Pass 1 — coverage-mode recommend

```bash
source ~/.zshenv && ts aggregate recommend --dir "{workdir}" \
  $([ -f "{workdir}/weights.json" ] && echo --weights "{workdir}/weights.json")
```

Writes/updates `{workdir}/candidates.json`. Stdout:
`{"mode", "selected", "curve", "candidates", "excluded_unprofiled"}` — `mode` will be
`"coverage"` on this first pass (no profiling data yet).

### 5b. Profile — connected or manual mode

Ask:

```
Profile the top candidates against the warehouse to replace estimated coverage with
actual row counts and compression ratios?

  C  Connected — I have a Snowflake profile with query access
  M  Manual    — emit a SQL script for you to run yourself (any warehouse)
  S  Skip      — keep coverage-only ranking (no compression numbers)

Enter C / M / S:
```

**C — connected mode** (reuse `{sf_profile_name}` from Step 4 if set, else ask):

```bash
source ~/.zshenv && ts aggregate profile --dir "{workdir}" --tables-dir "{workdir}/tables" \
  --snowflake-profile "{sf_profile_name}" --top-k 10
```

**M — manual mode:**

```bash
source ~/.zshenv && ts aggregate profile --dir "{workdir}" --tables-dir "{workdir}/tables" \
  --emit-sql "{workdir}/profile.sql"
```

Tell the user: *"Run `{workdir}/profile.sql` against your warehouse (any dialect — the
script is dialect-specific SQL, not a `ts` command). Each numbered statement returns
one row count; save the results as
`{"base_rows": N, "candidates": {"cand_1": rows, ...}}` (the `__base__` statement's
result goes to `base_rows`), then tell me when it's ready."* When ready, ask for the
results file path and run:

```bash
source ~/.zshenv && ts aggregate profile --dir "{workdir}" --tables-dir "{workdir}/tables" \
  --results "{results_path}"
```

Both modes write `agg_rows`/`base_rows` back into `{workdir}/candidates.json`.
Candidates whose SELECT can't be built deterministically are reported as `skipped`
(not fatal) — note them in the final report as needing manual SQL authoring.

**S — skip:** proceed to 5c without profiling; the curve stays coverage-only.

### 5c. Re-run recommend for the cost-mode curve

```bash
source ~/.zshenv && ts aggregate recommend --dir "{workdir}" \
  $([ -f "{workdir}/weights.json" ] && echo --weights "{workdir}/weights.json")
```

No extra flags needed — `recommend` reads `base_rows`/`agg_rows` back out of
`candidates.json` automatically (`_merge_prior_agg_rows`) and switches to `"mode":
"cost"` once at least one candidate is profiled. If any candidate ids appear in
`excluded_unprofiled`, note them — they were left out of cost-mode ranking because
they weren't profiled (increase `--top-k` in 5b and re-profile if one of them looks
important).

### 5d. Present the curve and let the user pick the cut-off

Join each `curve` entry (`id`, `marginal_benefit`, `cumulative_coverage_pct`,
`compression`) with that candidate's own `dimensions`/`bucket`/`flags` from
`candidates.json`:

```
#   Grain                              Bucket    Rows saved   Compression   Cum. coverage   Flags
1   Region × Product Category          MONTHLY   4.2M          240×          58%
2   Store                              DAILY     1.1M           38×          79%
3   Customer × Category × State        —         0.3M           12×          85%            wide_grain
4   Region × Product Category × SKU    WEEKLY    0.2M            9×          87%            compression<10×

(mode: cost — profiled row counts; coverage % is weighted by history if you mined it in Step 4)
```

Soft flags to call out, not hard rules — the maintenance-cost judgment stays human:
`compression < 10×`, `wide_grain` (grain > 8 columns), a candidate covering only
stale/rarely-viewed dependents. Also surface the standing caveat from
[open-items.md #10](references/open-items.md#10--filter-precision-vs-bucket-known-design-limitation-verify-impact-open):
coverage % doesn't account for filter precision finer than the bucket — a candidate
may look like it covers a query that filters more precisely than its stored grain.

Ask the user to pick a cut-off (e.g. "1,2" or "1-3" or "all" or "none"). Save the
selected candidate ids as `{selected_candidates}`.

---

## Step 6 — Generate Per Selected Candidate

Repeat this entire step once per id in `{selected_candidates}`, one at a time. The
processing order across candidates doesn't matter for the final association
ordering — `patch_association` re-sorts the whole `aggregated_models` block by
projected row count on every run, regardless of which candidate was generated first.

### 6a. Connection prompt

Per the standing rule (never silently reuse or trial-and-error an existing
connection): ask which warehouse dialect the aggregate table should target (default:
whichever `connection_type` the primary's own tables use, from Step 3).

```
The aggregate table for {grain_summary} needs a ThoughtSpot connection that can reach
its target database/schema.

  E  Use an existing connection
  C  Create a new connection   (Snowflake, key-pair auth)

Enter E / C:
```

**E — use an existing connection:**

```bash
source ~/.zshenv && ts connections list --profile "{profile_name}" --type {dialect_upper}
```

Ask how to identify it — name it exactly, filter by a partial string, or list all —
same flow as
[ts-convert-from-snowflake-sv Step 6B](../ts-convert-from-snowflake-sv/SKILL.md).
Save the exact `name` value from the response as `{connection_name}`.

**C — create a new connection (Snowflake only in v1):**

```bash
source ~/.zshenv && ts connections create \
  --name "{connection_name}" --account "{account}" --user "{user}" \
  --role "{role}" --warehouse "{warehouse}" --database "{database}" \
  --private-key-path "{key_path}" --profile "{profile_name}"
```

Never ask the user to paste a private key, password, or secret into the conversation
— the key is passed by file path only. For Databricks/BigQuery or password/OAuth
auth, direct the user to create the connection in the ThoughtSpot UI and return on
the **E** path.

Ask for the target `{db}` and `{schema}` for the aggregate table.

### 6a.1 — Choose the materialization

**Always ask this** — both the **E** and **C** branches above, for every dialect
(this replaced a v1 prompt that only fired on the **E** branch and only mentioned a
warehouse, not the underlying materialization choice).

Live-tested on Snowflake: a materialized view whose definition **joins more than one
table** is rejected outright with error `002212` ("Invalid materialized view
definition. More than one table referenced in the view definition."), and this
skill's aggregate SELECTs join the star's fact + dimension tables. So Snowflake
never offers a materialized view — only a dynamic table (which supports joins) or a
plain table. Databricks and BigQuery materialized views join natively, so they keep
the materialized-view option.

**Snowflake:**

```
How would you like to materialize {grain_summary}?

  D  Dynamic table — auto-refreshing; needs a warehouse to run refreshes
  T  Plain table   — CREATE TABLE AS (no warehouse needed; refresh it yourself)

Note: a Snowflake materialized view isn't offered here — Snowflake rejects a
materialized view whose definition joins more than one table (error 002212), and
this aggregate's SELECT joins the star's tables. Forcing --materialization mview
on Snowflake will error at generate time.

Enter D (then the warehouse name) / T:
```

If **D**: ask for the warehouse name (if the **C** branch above already created a
connection with a warehouse, offer to reuse that name) and save it as `{warehouse}`
— it's **required**; `ts aggregate generate` hard-fails with `--warehouse is
required to create a Snowflake dynamic table` if it's empty. If the user has no
warehouse to give, steer them to **T** instead. Set `{materialization}` = `dynamic`.

If **T**: leave `{warehouse}` empty and set `{materialization}` = `ctas`.

**Databricks / BigQuery:**

```
How would you like to materialize {grain_summary}?

  M  Materialized view — auto-refreshing
  T  Plain table        — CREATE TABLE AS (manual refresh)

Enter M / T:
```

If **M**: set `{materialization}` = `mview` (`{warehouse}` stays empty — not
needed). If **T**: set `{materialization}` = `ctas`.

### 6b. Generate the artifacts

Use the `{materialization}` (`dynamic` | `ctas` | `mview`) and `{warehouse}` chosen
in 6a.1 — `dynamic` requires a non-empty `{warehouse}` (Snowflake only); `ctas` and
`mview` need none:

```bash
source ~/.zshenv && ts aggregate generate \
  --dir "{workdir}" --candidate {candidate_id} --model-guid {model_guid} \
  --tables-dir "{workdir}/tables" --db "{db}" --schema "{schema}" \
  --connection-name "{connection_name}" --profile "{profile_name}" \
  --dialect {dialect} --materialization {materialization} \
  $([ -n "{warehouse}" ] && echo --warehouse "{warehouse}") \
  --out-dir "{workdir}/{candidate_id}"
```

`--materialization dynamic` emits a Snowflake dynamic table (needs `--warehouse` —
chosen in 6a.1); `--materialization mview` emits a Databricks/BigQuery materialized
view; `--materialization ctas` emits a plain `CREATE TABLE AS` on any dialect and
needs no warehouse. `--materialization mview` on Snowflake is rejected by `ts
aggregate generate` itself (the 002212 guard in `sqlgen.build_ddl`) — 6a.1 never
offers that combination, so this only fires if the flags are overridden by hand.
Writes five files to `{workdir}/{candidate_id}/`: `ddl.sql`, `table_spec.json`,
`table.tml.yaml`, `agg_model.tml.yaml`, `primary_patched.tml.yaml`. Stdout:
`{"candidate", "aggregate_name", "files"}`.

### 6c. DDL gate

Show the full contents of `{workdir}/{candidate_id}/ddl.sql`. Ask:

```
Create this aggregate table now?

  Y  Yes — execute the DDL directly (requires warehouse write access)
  M  Manual — I'll run it myself; tell me when it's done
  N  Cancel this candidate

Enter Y / M / N:
```

**Y — connected execution.** For a `method: cli` Snowflake profile:

```bash
{snow_cmd} sql -c {cli_connection} -f "{workdir}/{candidate_id}/ddl.sql"
```

For a `method: python` profile, connect via the Python connector (same helper
`ts-load-source-data`/`ts-convert-to-snowflake-sv` use) and `cursor.execute()` the
file's contents. Cortex Code CLI users: execute the DDL directly via the `sql_execute`
tool against the active `cortex connections` connection.

**M — manual.** Tell the user the exact file path to run, then wait for confirmation
before continuing — this flow is idempotent, so resuming in a later session is fine.

**N — cancel.** Skip the rest of Step 6 for this candidate and move to the next one
(or Step 7 if this was the last).

### 6d. Register the table in ThoughtSpot

`table_spec.json` is a single spec object; `ts tables create` reads a JSON **array**
from stdin:

```bash
python3 -c "
import json
spec = json.load(open('{workdir}/{candidate_id}/table_spec.json'))
print(json.dumps([spec]))
" | ts tables create --profile "{profile_name}"
```

Output: `{{aggregate_table_name}: guid_or_null}`. Schema validation against the
connection here doubles as proof the DDL actually ran — `ts tables create` reuses the
existing JDBC-error retry handling (transient errors retried automatically). If the
GUID comes back `null` after retries (a persistent JDBC/schema error), fall back:
ask the user to add the table via the ThoughtSpot UI manually, then resume once it
exists — check with `ts metadata search --subtype ONE_TO_ONE_LOGICAL --name
"{aggregate_table_name}"`.

### 6e. RLS/CLS parity — HARD GATE

**A fast aggregate that leaks rows across tenants is worse than no aggregate.** Check
every base table this candidate draws from (the `{workdir}/tables/*.tml.yaml` files
exported in Step 3) for `table.rls_rules`:

```python
import yaml, pathlib

rls_found = []
for f in pathlib.Path(f"{workdir}/tables").glob("*.tml.yaml"):
    doc = yaml.safe_load(f.read_text())
    rules = doc.get("table", {}).get("rls_rules")
    if rules:
        rls_found.append((f.stem, rules))
```

If `rls_found` is non-empty, this is a **hard stop** — refuse to import
`agg_model.tml.yaml` until the user explicitly confirms parity:

```
⛔ RLS PARITY REQUIRED

  Base table(s) with Row-Level Security:
    {table_name}: rule "{rule_name}" — {rule_expr}

  The new aggregate table has NO row-level security applied. Any user who can query
  the aggregate (directly or via routing) would see ALL rows, bypassing the primary
  Model's access control.

  Before this aggregate Model is imported, you must either:
    a) Apply an equivalent RLS rule to the new aggregate table in the ThoughtSpot UI
       (Table → Row Security), replicating the rule(s) above, or
    b) Confirm the aggregate table's data is not sensitive / RLS doesn't apply here

  Have you applied equivalent RLS to the aggregate table, or confirmed it's not
  needed? (type CONFIRM to proceed, anything else cancels this candidate)
```

Column-Level Security (CLS) cannot be reliably auto-detected today — retrieval of
`column_security_rules` TML is itself an open item on `ts-dependency-manager`
(unverified). Ask explicitly instead of silently skipping the check:

```
Do any of the base tables for this aggregate have Column-Level Security (CLS)
restricting which users can see specific columns? (Y / N — if unsure, check
Table → Column Security in the ThoughtSpot UI before answering)
```

If Y, require the same kind of explicit confirmation that equivalent CLS has been (or
will be) applied to the aggregate table before continuing. Do not proceed past this
gate on an unconfirmed "I'm not sure."

### 6f. Import the aggregate Model

```bash
source ~/.zshenv && ts tml import --file "{workdir}/{candidate_id}/agg_model.tml.yaml" \
  --profile "{profile_name}" --policy ALL_OR_NONE --create-new
```

`--create-new` is required — `agg_model.tml.yaml` has no `guid:` (it's brand new).
Parse the returned JSON for the new Model's GUID:

```python
import json
resp = json.loads(result.stdout)
agg_model_guid = resp[0]["response"]["object"][0]["header"]["id_guid"]
```

If the import fails, check that the RLS/CLS gate above wasn't bypassed and that the
`connection_name` matches exactly (case-sensitive) an existing connection.

### 6g. Back up and patch the primary Model

**Non-negotiable — always run before touching the primary.** Reuses
`ts dependency backup` exactly as `ts-dependency-manager` does:

```python
import json, subprocess

plan = {"operation": "REMOVE", "source": {"guid": model_guid, "type": "MODEL", "name": model_name},
        "fix": [], "delete": [], "out_dir": str(workdir)}
result = subprocess.run(
    ["bash", "-c", f"source ~/.zshenv && ts dependency backup --profile '{profile_name}'"],
    input=json.dumps(plan), capture_output=True, text=True,
)
if result.returncode != 0:
    raise SystemExit(f"Backup failed — primary Model NOT patched. {result.stderr}")
manifest = json.loads(result.stdout)
backup_dir = __import__("os").path.dirname(manifest["objects"][0]["backup_file"])
```

The `"operation": "REMOVE"` label is a formality of the shared plan schema — nothing
is actually being removed; only the `source` (primary Model) entry is backed up. Tell
the user the backup location and that it's required for Step 7's rollback path if
routing verification fails. Then import the patched primary:

```bash
source ~/.zshenv && ts tml import --file "{workdir}/{candidate_id}/primary_patched.tml.yaml" \
  --profile "{profile_name}" --policy ALL_OR_NONE
```

No `--create-new` here — `primary_patched.tml.yaml` carries the existing `guid:` at
the document root (it's an update, not a new object). Confirm the response's
`status.status_code == "OK"`.

Save `{backup_dir}` — needed by Step 7 if routing verification fails for this or a
later candidate.

---

## Step 7 — Verify Routing

For each candidate imported in Step 6, spot-check that a query which should route
does, and one that shouldn't, doesn't. Use
[ts-object-model-spotql-query](../ts-object-model-spotql-query/SKILL.md), or directly:

```bash
source ~/.zshenv && ts spotql generate-sql \
  'SELECT "Region", SUM("Sales") AS s FROM "ORDERS" AS "t1" GROUP BY "Region"' \
  --model {model_guid} --profile "{profile_name}"
```

SpotQL requires double-quoted identifiers, a table alias, and quoted column
references (see the worked example in `tools/ts-cli/README.md`'s `ts spotql` section).
Build the SELECT to match the candidate's exact grain — swap the illustrative
`"Region"`/`"Sales"`/`"ORDERS"` above for this candidate's dimension columns, bucketed
date column, and the measures it covers, keeping every identifier quoted and the
`FROM "…" AS "t1"` alias in place. Inspect the returned `executable_sql` for the
**aggregate table's physical name** (`table_spec.json`'s `db_table`). If present,
routing worked. Then run a **detail-grain** query (one that needs a column outside
the aggregate's grain) and confirm `executable_sql` references the **primary's**
table(s) instead — the fallback path.

If the candidate covers a NONADDITIVE measure at all (per
[measure-decomposition-rules.md](references/measure-decomposition-rules.md)), also
run that `unique count(...)` query specifically and confirm it falls back to the
primary rather than silently returning a wrong number from the aggregate (see
[open-items.md #4](references/open-items.md#4--non-additive-measure-routing--open)).

**On failure** (aggregate doesn't get hit when it should, or gets hit when it
shouldn't, or a NONADDITIVE query routes to the aggregate):

```
Routing verification FAILED for {candidate_id}: {what was expected vs. observed}

Roll back the aggregated_models association on {model_name}? (Y / N)
```

If Y:

```bash
source ~/.zshenv && ts dependency rollback --backup-dir "{backup_dir}" \
  --only updates --profile "{profile_name}"
```

This restores the primary Model's TML from before the patch (in place, same GUID).
It does **not** delete the aggregate Table/Model objects already created — note their
GUIDs in the report so the user can clean them up manually if they no longer want
them.

---

## Step 8 — Summary Report

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 AGGREGATE ADVISOR — SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Primary Model: {model_name} ({model_guid})
Signatures analyzed: {full} full + {partial} partial from {dependents} dependent(s)
Weighting: {"Snowflake query history (N days)" | "coverage-only, no history mined"}

Aggregates created:
  {candidate_id}  {grain_summary}   {compression}×   routing: ✓ verified
    Table:  {aggregate_table_name}  ({table_guid})
    Model:  {agg_model_name}  ({agg_model_guid})
    Projected rows saved: {marginal_benefit}

Candidates considered but not selected: {N}
Candidates skipped (SQL not deterministically buildable): {list, if any}

Known limitations carried into this recommendation (see open-items.md):
  - Filter-precision-vs-bucket (#10): coverage % doesn't account for filters more
    precise than the stored bucket.
  - {any other open item actually exercised by this run — e.g. #9 if a WEEKLY
    candidate was generated, #11 if a nullable-FK join was pruned}

Backup location(s): {backup_dir per candidate, if any patches were applied}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Error Handling

| Symptom | Action |
|---|---|
| `ts auth whoami` returns 401 | Token expired — see `/ts-profile-thoughtspot` refresh procedure |
| `ts aggregate signatures` reports `dependents: 0` | Model genuinely has none, or the type-string filter is stale on this build — see [open-items.md #7](references/open-items.md#7--dependent-type-filter-values--open-narrow) |
| Most signatures come back `partial` | Likely token-casing mismatch in `search_query` — see [open-items.md #8](references/open-items.md#8--real-tml-search_query-token-casing--open) |
| `ts aggregate generate` fails with `UnsupportedModelError` | Candidate needs manual SQL authoring — use `ts aggregate profile --emit-sql`'s output for that candidate as a starting point, or exclude it from the selected set |
| `ts tables create` returns a `null` GUID after retries | Persistent JDBC/schema error — confirm the connection's role can see the target `{db}.{schema}`; fall back to creating the table via the ThoughtSpot UI and resume |
| `ts tml import --create-new` for `agg_model.tml.yaml` fails | Check the RLS/CLS gate wasn't bypassed; confirm `connection_name` matches an existing connection exactly (case-sensitive) |
| Primary Model import (`primary_patched.tml.yaml`) fails with a version conflict | The primary drifted since Step 3 — re-run `ts aggregate generate` for this candidate (it re-exports the primary fresh every time) and retry |
| Routing verification fails | Offer rollback via `ts dependency rollback --backup-dir {backup_dir} --only updates`; the aggregate Table/Model objects are NOT auto-deleted — note their GUIDs for manual cleanup |
| `pyyaml` not installed | `pip install pyyaml` |

---

## Cleanup

The working directory at `{workdir}` (and any `{backup_dir}` under it) is kept after
the skill completes — it contains every intermediate artifact (`signatures.jsonl`,
`candidates.json`, per-candidate DDL/TML, TML backups). Remind the user:

```
Working directory retained at: {workdir}
Remove once you're confident every generated aggregate is correct: rm -rf {workdir}
```

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-07-11 | Initial release. Audits a Model's dependent Liveboards/Answers into query signatures (`ts aggregate signatures`), generalizes them into ranked candidate grains with a cost-based marginal-gain curve (`ts aggregate recommend`, optionally reweighted by Snowflake query history via `ts aggregate history`), profiles candidates in connected or manual mode (`ts aggregate profile`), and generates the warehouse DDL + aggregate Table/Model TML + `aggregated_models` association patch per approved candidate (`ts aggregate generate`) — gated at every artifact by a confirmation step, an RLS/CLS parity hard gate, and a post-import routing verification with rollback via `ts dependency backup`/`rollback`. Ships with eleven OPEN items in `references/open-items.md` covering routing semantics, `aggregated_models` TML shape, multi-aggregate precedence, and join-pruning fidelity — all must be VERIFIED against a live 26.6+ instance before this skill is considered merge-ready (tracked as Task 11 on `wip/ts-object-model-aggregates`). |
