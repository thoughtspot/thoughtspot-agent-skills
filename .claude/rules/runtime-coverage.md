# Runtime Coverage — one runtime

Skills in this repo are served by **one runtime, the CLI**. Its skill files are read by
two host tools, and both have a shell and the `ts` CLI:

| Directory | Read by | How it is installed |
|---|---|---|
| `agents/cli/` | Claude Code **and** Cortex Code CLI | symlinked into `~/.claude/skills/` and `~/.snowflake/cortex/skills/` (see `agents/cli/SETUP.md`) |
| `agents/claude/` | Claude Code only | an annex holding `ts-profile-snowflake`; Cortex Code manages Snowflake connections natively |

Both read the reference library in `agents/shared/`. `tools/validate/_dirs.py` lists the
two skill directories once, and every validator scans both.

Supporting Cortex Code CLI costs nothing extra: it is the same files through a second
symlink, not a second copy.

---

## Retired runtimes

| Runtime | Directory | What it was |
|---|---|---|
| CoCo Snowsight | `agents/coco-snowsight/` | Stored-procedure skills for Snowsight Workspaces (the Snowflake conversion pipeline, its ThoughtSpot auth, and `ts-setup-sv` to install the procedures), deployed to a Snowflake stage |
| Databricks Genie | `agents/databricks/` | Genie Code shells for the two Metric View converters, plus a vendored notebook build of the `ts_cli` translators, deployed as an Asset Bundle |

Both were retired on **2026-11-08**:

- **No usage signal** for either.
- **Sync and validator overhead on every change.** Each needed its own deployment step
  (stage sync; bundle deploy), and keeping them in step with the CLI skills took three
  validators — runtime coverage, mirror sync and the parity matrix — that every skill
  change had to satisfy. The CoCo stage had already stopped being synced, so the
  overhead bought nothing.
- **Native import covers part of what they offered, not all of it.** ThoughtSpot's own
  Snowflake Semantic View and Databricks Metric View import is Early Access, covers the
  SV/MV → ThoughtSpot direction only, and is not yet verified live here (audit 2026-11-08
  finding 13.3; BL-542). The reverse direction stays with the CLI converters
  `ts-convert-to-snowflake-sv` and `ts-convert-to-databricks-mv`.

The pre-retirement state is preserved at git tag **`runtimes-archive-2026-11-08`**
(commit `ad1dd15e`), including the validators that served them (`check_runtime_coverage.py`,
`check_mirror_sync.py`, `generate_parity.py`) and `scripts/stage-sync.sh` /
`scripts/deploy.sh`:

```bash
git checkout runtimes-archive-2026-11-08 -- agents/coco-snowsight agents/databricks
```

The CLI converters for both platforms (`ts-convert-{to,from}-snowflake-sv`,
`ts-convert-{to,from}-databricks-mv`), `ts-profile-databricks`, `ts-profile-snowflake` and
the shared mappings were **not** part of either runtime and are unaffected.

---

## Adding a runtime is a decision, not an edit

A second skill directory looks cheap and is not: the retired runtimes are the record of
what one costs. Before adding one:

1. **Name who it is for** and why the CLI, through Claude Code or Cortex Code CLI, cannot
   serve them.
2. **Decide how its copies stay in step** with `agents/cli/` — a generator, a mirror check,
   or a documented manual review — and who runs its deployment step. A copy with no
   owner drifts; the CoCo mirrors did.
3. **Add it to `tools/validate/_dirs.py`.** Every validator then scans it, including the
   ones that assume the `ts` CLI (direct `requests`, flag usage, smoke tests). A runtime
   without the `ts` CLI needs the split between "every runtime" and "runtimes with the
   CLI" restored in `_dirs.py` first (it existed as `CLI_RUNTIMES` until 2026-11-08).
4. **Keep one name per skill.** A skill carried by two runtimes uses the same directory
   name in both ([skill-naming.md](skill-naming.md), "Runtime coverage").

Record the decision in the root `CLAUDE.md` and here, in the same PR that adds the
directory.
