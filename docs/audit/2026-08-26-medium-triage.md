# 2026-08-26 full audit — medium (🟠) triage

**Purpose.** The two-bucket rule requires every finding to exit to a permanent check or a
dated backlog item. After the same-day wave closed all 9 🔴 and 10 of 25 🟡, **41 of the
46 🟠 were still unrouted** — which is the actual problem, larger than any individual
finding in the list. This triages all 41 so none is left as "we noticed this".

**Correction worth recording.** The legend is 🟠 = *medium*, 🟡 = *low*. Early routing in
this session referred to the 🟡 batch as "mediums"; PRs #461–#463 closed **low**-severity
findings. The medium tier was essentially untouched until this triage.

## Bucket A — fix now (small, self-contained, verifiable here)

Ordered by consequence, not by id.

> **One row never closed.** Fourteen of the fifteen bucket-A rows are ✅ — thirteen across
> PRs #465–#472, and **13.3** already closed by PR #447 before this triage actioned it.
> **13.14 / 13.15** is the fifteenth, and it is not closed: verified 2026-08-27,
> `mv_emit_joins.py` is untouched since PR #426 and neither mapping file has been edited in
> the cardinality section. It is now **BL-223** rather than an unmarked row here.

| # | Why it's in A | Shape |
|---|---|---|
| **1.1** | ✅ **CLOSED (PR #465).** **Do first.** Three runtime-output files are *still tracked* under `tools/ts-cli/plan/`, carrying real instance identifiers (source/target GUIDs, an org column layout) from a staging run. Verified tracked today. | delete + `.gitignore` + a third `check_repo_hygiene` query so the next staging run can't re-commit it |
| **17.4** | ✅ **CLOSED (PR #466).** **Silent false success on the destructive-recovery path.** All three typed probes failing leaves `out` empty, every guid reads "already gone", `failures == []`, and the ledger records *"Rollback complete. The source Org was never touched."* Nothing was deleted. | distinguish an absent row from a failed request; 5xx/429 must surface as rollback failure |
| **17.3** | ✅ **CLOSED (PR #467).** Qlik `_viz` emits no axis encoding for four chart types in `_CHART_NEEDS_AXIS`, so its boards **ship blank**; it is also the one converter with no pre-import lint. Sisense has the same step-order gap. | fix `_viz`; add the lint gate at the right step in both skills |
| **17.2** | ✅ **CLOSED (PR #467).** Qlik omits `quote='"'`, emitting `sql_string_op('UPPER({0})', …)` where every sibling emits double quotes per the schema. Only the single-quoted form is unverified against the parser — and BL-171 existed to stop emitting forms ThoughtSpot rejects. | one-arg fix + correct the mapping rows + cross-emitter comparison as the guard |
| **14.5** | ✅ **CLOSED (PR #468).** `record_size: 10` + exact-name post-filter: for a common substring ("Sales") the exact match need not be in the ten rows. Three silent modes, worst being `tables.py:94` → **creates a duplicate table** instead of updating. | `record_size: -1`, matching the codebase's own precedent |
| **13.22 / 13.25 / 13.26** | ✅ **CLOSED (PR #469)** (with 13.27/13.28). One Tableau cluster, one mapping file + `validate.py`. Census gaps that pass through untranslated *against the file's own fail-loud contract*: spatial is 13 vs the documented 15 (`PARSE_WKT` likeliest in real workbooks); ten `MODEL_*`/`SCRIPT_*` in no list at all; `RANK_PERCENTILE` is a **missed native equivalent**. | tables + `_UNMAPPED_FUNCTIONS` + generic `MODEL_`/`SCRIPT_`/`RANK_` regexes (the recurrence-proof form) |
| **4.3** | ✅ **CLOSED (PR #470).** Two allowlists store a backlog id, not a size, so an exempt file grows unbounded while the gate says PASS — `commands/tableau.py` went 1063 → **1675** lines (+58%) green throughout. | convert both to ratchets, mirroring `check_module_health`'s baseline pattern |
| **18.4** | ✅ **CLOSED (PR #470).** `CLAUDE.md:40` obliges routing to be recorded; **nothing reads harness config** in pre-commit or CI, which is exactly how the stale `haiku` pin survived. | `check_harness_routing.py` — frontmatter vs the routing table |
| **13.19** | ✅ **CLOSED (PR #470).** The flagship "Verified v1.1 Example" sets `window[].order: order_month` and never defines it — the artifact readers copy cannot be created as printed. | fix + a check that every `window[].order` resolves, in docs *and* emitter output |
| **13.3** | ✅ **ALREADY CLOSED — verified, nothing to do.** PR #447 added `agents/shared/worked-examples` to `ANCHORED_DIRS` and all **17 of 17** files now carry anchors. The finding's premise ("11 of 17 are never nudged", and that this was the structural cause of 13.2) was true when written and had been resolved by the time it was actioned. | none — confirm only |
| **13.7 / 13.8 / 13.16 / 13.17 / 13.2 / 14.3 / 18.5 / 18.2** | ✅ **CLOSED (PR #471)** (18.2 in #470). Pure doc corrections with a verified source, several self-contradictory today (13.8 contradicts a sibling file *and* itself two rows down; 14.3 reverses COUNT_DISTINCT in four places while the code is right; 18.5 still routes work to Haiku four bullets below the corollary forbidding it; 18.2's `.json.example` doesn't parse, so the documented `cp` breaks a contributor's settings). | doc edits; 18.2 also gets a one-line "every `.claude/*.json` parses" gate |
| **13.14 / 13.15** | ⚠️ **NOT CLOSED — FILED (BL-223) 2026-08-27.** The only bucket-A row that exited neither as a fix nor a deflection; `mv_emit_joins.py` is untouched since PR #426 and both mapping files still say "equivalent"/"never both". BL-223 also records that 13.14's central claim is **contested** by three repo sites and BL-174's live probe, so it is a dispute to settle rather than a fix to apply. `rely`/`cardinality` are neither equivalent nor exclusive — the vendor *recommends both* where the constraint holds, so every one-to-many join drops a recommended optimization. 13.15's one-to-many restrictions are import-time failures, therefore catchable. | doc + emitter change + a deterministic pre-emit check |
| ✅ **11.1 / 5.2** | **CLOSED (PR #472).** Skill wiring, not missing capability. `--connection` ships (casefolded, tested) and four skills hand-filter with prose that is *wrong* (`equals` vs casefold). The coach calls an `execute()` that is **defined nowhere**, inviting the exact `snowflake.connector.connect(` a validator already bans in SKILL.md. | name the real commands; delete the pseudo-call |
| ✅ **14.6 / 6.5 (rest) / 6.4 (rest)** | **CLOSED (14.6 in #470; 6.4/6.5 in #472).** Tails of already-closed work. BL-074's preamble missed the four *most interactive* skills. #449 fixed the interpreter list but left the warning text naming the old three. #449 fixed the `~/.zshenv` guard; `timeout=` is still absent (0 hits) so a hung request blocks the runner indefinitely. | small edits + a threshold validator for 14.6 |
| ✅ **5.3** | **CLOSED (PR #472).** The "endpoint not verified" verdict **predates `ts share`** — the pre-flight is buildable today from `ts auth whoami` + `ts share status`, no new CLI work. | wire Step 6; close open-item #2 |

## Bucket B — dated backlog items (real work, needs its own PR)

| # | Why not now | Proposed |
|---|---|---|
| **13.23** | ✅ **FILED (BL-219).** Behavioural parser change plus tests: `_extract_noodle_joins` drops any non-`=` relationship entirely, `_extract_joins` never captures the operator, and **no test exercises it**. Needs an operator-mapping design, not a patch. | new BL |
| **11.2** | ✅ **FILED (BL-220).** 15 skills open `~/.claude/thoughtspot-profiles.json` by hand, and `agents/cli/` also serves Cortex Code CLI where that path is wrong. Green-baseline validator + 15 edits. | new BL |
| **11.3** | ✅ **FILED (BL-122 note).** The missing shared reference must be *written*, then adopted in 7 converters; four have no scope prompt at all, so a second migration **silently creates duplicates**. | extend BL-122 |
| **11.4** | ✅ **FILED (BL-158 note).** Five independent cascade implementations; extracting one shared helper touches three converter commands. Transitive closure is the part an LLM gets wrong. | ~~extend BL-161 or new BL~~ → BL-158, which already owns it |
| **11.5** | ✅ **FILED (BL-034 note).** Build `ts tml export-corpus --cache-dir` — the last straggler from the 2026-06-29 sweep (everything else shipped). | BL-034 |
| **11.6** | ✅ **FILED (BL-221).** Extend `check_patterns` Check 8 to `references/**.md` (six internal imports live through the carve-out today), and re-examine a live allowlist entry whose removal condition is unmet. | new BL |
| **5.4** | ✅ **FILED (BL-086 note).** Two large deterministic blocks (~138 lines) belong in BL-086's substrate list: `ts model probe-columns`, `ts model detect-hierarchies`. | fold into BL-086 |
| **6.6** | ✅ **FILED (BL-222).** Adapter-layer tests for seven never-invoked `ts snowflake` subcommands; `exec` is entirely uncovered in CI. | new BL |
| **13.18** | ✅ **FILED (BL-102 note).** Parameterised `range`/`offset` (18.2) is the native equivalent of "last N days" — fold into the deferred parameter-emission work. | ~~fold into BL-031/13.2 work~~ → BL-102, which already owns the 18.2 live-verify |

## Bucket C — blocked on something I don't have

| # | Blocker |
|---|---|
| **13.24** | Needs a live 2026.x workbook built on a Tableau Semantics semantic model. The cheap interim (detect-and-warn on an unrecognised published-datasource class, so a run doesn't silently yield an empty join set) **is** doable and moves to bucket A if wanted. |
| **7.1** | ✅ **CLOSED 2026-08-27 — the *fix* needed no settings access, though the diagnosis did.** `validate` is now an *aggregate* job (`needs: [suite, pytest-matrix]`) that fails unless both succeeded, so the existing single required context covers the matrix. Aggregating beat adding the four legs to the required-checks list: it keeps interpreter versions out of a settings page where the next support-range bump would silently reopen the hole. The durability of that still rests on the off-repo setting never changing, which the repo cannot see — so `check_ci_gate_coverage.py` holds the end it can: a job named `validate` exists, every PR job is in its `needs:`, `always()` survives, and no gated job sets `continue-on-error`. The original blocker read: repo-admin change: branch protection requires only `validate`, so a red `pytest-matrix` on 3.10/3.14 **cannot block a merge**. Confirmed today: required contexts are `["validate"]`. Either add the four matrix legs or fold the matrix into `validate`. Needs someone with settings access. |
| **18.1** | ✅ **CLOSED 2026-08-27.** Allow-list widened in the **committed** `.claude/settings.json` (it is shared repo state, so every contributor hit the same wall): `WebSearch`, six domain-scoped `WebFetch` rules (Snowflake / Databricks / Tableau docs plus the Claude Code and Anthropic docs angle 18 reads), and the two **read-only** SpotterCode tools. `execute-thoughtspot-code` deliberately excluded. `check_audit_workflow_permissions.py` keeps it from rotting — adding a platform to `PLATFORMS` now fails the gate until its docs domain is approved, instead of blocking that one finder mid-sweep. Original blocker: The audit workflow's own premise is broken — every finder is told to use WebSearch/WebFetch/SpotterCode, none of which is in `permissions.allow`, so a 7- or 14-agent sweep blocks on interactive prompts. The fix is a **shared** allow-list widening (web domains + MCP tools), which is a policy call rather than a mechanical edit. |

## Recommended order

Items 1–5 are ✅ **done** — see the bucket-A table above for the PR that closed each.

1. **1.1** — tracked instance identifiers; smallest fix, highest embarrassment.
2. **17.4, 17.3, 17.2, 14.5** — the four behavioural bugs. 17.4 first: a destructive path that reports success having done nothing is the worst failure shape in the list.
3. **The Tableau census cluster** (13.22/13.25/13.26) — one file, one module, three findings.
4. **The validator promotions** (4.3, 18.4, 13.19, 18.2's gate, 14.6's) — each stops a class recurring.
5. **The doc corrections** — cheapest, and several are self-contradictions that mislead a reader today.
6. ✅ **DONE.** **File bucket B as dated BL items** before starting any of it, so nothing
   depends on this document surviving — BL-219/220/221/222 filed, BL-223 filed for the
   bucket-A row above that was never closed, plus dated notes folded into BL-034 / BL-086 /
   BL-102 / BL-122 / BL-158 (2026-08-27).
