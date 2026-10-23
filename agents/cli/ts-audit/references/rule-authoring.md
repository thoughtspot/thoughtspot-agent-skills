# Audit Rule Authoring

How to add, change or retire a `ts audit` rule. Follow it when a user describes a check
they want ("flag Models with more than 40 hidden columns", "make A1 stricter for General",
"stop reporting D3 INFO findings").

Every check `ts audit run` makes is a **rule**: an entry in a YAML catalog, run by a
small rule engine. There are no check functions to write. A few rules whose logic no
declarative form expresses are **code rules**, but even those keep a full catalog entry.

| What | Where |
|---|---|
| Categories (the report's tabs, `--angles`) | `tools/ts-cli/ts_cli/audit/catalog/categories.yaml` |
| Assessment profiles (`--assessment`) | `tools/ts-cli/ts_cli/audit/catalog/profiles.yaml` |
| Rules, one file per primary category | `tools/ts-cli/ts_cli/audit/catalog/rules/{ai,data,human,perf,security}.yaml` |
| Rule engine: scopes, modes, bands, messages | `tools/ts-cli/ts_cli/audit/engine/` |
| Derived fields (`@name`) | `engine/fields.py`, `engine/fields_data.py`, `engine/fields_human.py` |
| Code rules (`code:<name>`) | `engine/code_rules.py`, `engine/code_rules_human.py` |
| Example fixtures (synthetic) | `tools/ts-cli/tests/audit_rule_fixtures/<category>.py` |
| The human catalog (generated) | [check-catalog.md](check-catalog.md) |

Commands below run from the repo root. They assume the `ts` on your PATH runs this
checkout's code (`pip install -e tools/ts-cli`, or `uv tool install --force -e
tools/ts-cli`). Check with the interpreter `ts` itself runs, not your `python3` (the
entry point's first line names it, or — for a long path — a `/bin/sh` trampoline does):

```bash
python3 - "$(command -v ts)" <<'EOF'
import re, subprocess, sys
lines = open(sys.argv[1]).read().splitlines()
interp = lines[0][2:].strip()
if interp.endswith("/sh"):
    interp = re.search(r"'exec' '([^']+)'", lines[1]).group(1)
print(subprocess.run([interp, "-c", "import ts_cli; print(ts_cli.__file__)"],
                     capture_output=True, text=True).stdout.strip())
EOF
```

It must print a path inside this checkout's `tools/ts-cli/`.

`python` and `pytest` below mean the environment ts-cli is installed in (activate it):
the generator and the re-pin helper import `ts_cli`, which needs its dependencies, and a
bare system `python3` may be too old or lack them (`ModuleNotFoundError: typer`). Only
`tools/validate/*.py` are written to run under any `python3` with PyYAML.

---

## Rule syntax

The shipped A6 entry, annotated. Keys not shown are described after it.

```yaml
- id: A6                          # permanent: never renamed, removed or reused
  title: Measure AI context coverage below threshold
  description: >-                 # what it detects and why; shown in check-catalog.md
    Share of a Model's visible MEASURE columns with a non-blank properties.ai_context.
  status: active                  # active (the default) | retired
  categories: [A]                 # first one sets the finding's legacy `angle`
  requires: [model_tml]           # data the rule needs; an object lacking it is skipped
  # uses: [ai_instructions]       # data it reads WITHOUT skipping objects that lack it
  # implementation: code:<name>   # only for a code rule; omitted = declarative
  scope: model                    # the object a finding is about
  aggregate:
    mode: ratio                   # each | ratio | count | group | pairwise | composite
    over: model.column            # the child scope counted (ratio / count)
    where:                        # which children count
      all:
        - {field: properties.column_type, regex: '^(?i:measure)\Z'}
        - {not: {field: properties.is_hidden, truthy: true}}
    match: {field: properties.ai_context, nonblank: true, truthy: true}
    unnamed_label: "?"            # ratio only: how a child with no name is listed
  bands:                          # grades the measured value; first matching level wins
    direction: higher_is_better   # or lower_is_better
    unit: percent                 # percent | count | depth | ratio | score
    levels:                       # worst first
      - {op: lt, value: 80, severity: LOW}
  profiles:                       # per-profile overrides; overridable keys only
    spotter:
      bands:                      # a band list is replaced whole, never merged
        direction: higher_is_better
        unit: percent
        levels:
          - {op: lt, value: 40.0, severity: HIGH}
          - {op: lt, value: 80, severity: MEDIUM}
      legacy_threshold: {green: 80, assessment: "{profile_label}", yellow: 40.0}
  message: "{matched}/{total} measures have AI context ({pct:.0f}%) — missing: {unmatched_names}"
  legacy_threshold: {green: 80, assessment: "{profile_label}"}   # reproduction only
  remediation: Run /ts-object-model-coach to improve descriptions, synonyms, AI context
  examples:
    fires: {fixture: model_measures_no_ai_context, profile: spotter, severity: HIGH}
    silent: {fixture: model_measures_with_ai_context, profile: spotter}
  # views: [cleanup]              # report views it feeds: duplicates | cleanup
```

**Severity source.** A grading mode (`ratio`, `count`, `pairwise`, `composite`) needs
`bands`. `each` and `group` take a fixed `severity: HIGH`, or a mapping on a field:

```yaml
severity: {field: "@join_type", map: {OUTER: HIGH}, default: INFO}
```

The lookup is exact and type-sensitive (YAML `true` is a boolean key). When the map is
keyed on a derived field (`@name`), the field must declare its possible values
(`@register(..., values=...)`) and the gate checks the keys against them; a map on a
plain path (`field: name`) is not checked, so spell its keys with care. An `each` rule may instead
grade a `measure` (a field holding a number) with `bands`. A rule has one source, never
both: `severity` beside `bands` is rejected.

**Per-severity wording.** A rule whose findings read differently by severity keeps every
wording; `legacy_threshold` takes the same form:

```yaml
message:
  by_severity:
    HIGH: FULL OUTER join causes performance issues
    INFO: "{@join_type} join — may indicate data discrepancies"
legacy_threshold:
  by_severity:
    MEDIUM: {high_overlap: 0.5}     # a severity with no entry has no threshold (null)
```

Under each profile, the message in force must word every severity the rule can emit, and
no entry may name a severity nothing emits.

**Retired rule.** `status: retired`, and it never runs. It needs no examples, and may
carry no logic at all when no profile revives it (H6):

```yaml
- id: H6
  title: Duplicate sets
  description: Deferred — requires deep set comparison. Retired; the id stays allocated.
  status: retired
  categories: [H]
  scope: set
```

**Code rule.** `implementation: code:<name>` names a function registered with
`@code_rule`; the entry carries no `aggregate`. Its message placeholders, severity source
(`bands`, the entry's `severity`, or severities fixed in code) and data reads are
declared by the registration, and the gate holds the entry to them.

### Vocabulary

| | Values |
|---|---|
| `scope` | `model`, `model.column`, `model.formula`, `model.filter`, `model.table`, `join`, `table`, `table.rls_rule`, `rls_column_ref`, `answer`, `answer.table_ref`, `answer.formula`, `set`, `metadata` |
| `requires` | `model_tml`, `table_tml`, `metadata`, `dependents`, `ai_instructions`, `answers`, `sets` |
| `uses` | `dependents`, `ai_instructions`, `answers`, `sets` (conditional data only) |
| Band `op` | `lt`, `lte`, `gt`, `gte`, `eq` |
| Severities | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO` |

**Aggregate keys per mode** (any other key is rejected):

| Mode | Keys (required in bold) | Finds |
|---|---|---|
| `each` | `where`, `measure` | one finding per scope item passing `where` |
| `ratio` | **`over`**, **`match`**, `where`, `unnamed_label` | share of `over` children passing `where` that also `match` |
| `count` | **`over`**, `where` | how many `over` children pass `where` |
| `group` | **`key`**, **`kind`**, `where`, `value`, `member`, `name`, `guid` | `kind: duplicates`: a group of 2+ items sharing `key`; `kind: divergence`: 2+ distinct `value`s under one `key` |
| `pairwise` | **`set`**, `where` | every pair of items, by Jaccard similarity of their `set` collections |
| `composite` | **`components`**, **`weights`**, `where` | weighted sum of components per item |

`over` must be a child scope of the rule's scope.

**Operators** in `where` / `match`. An expression takes exactly one form:

- `{all: [...]}`, `{any: [...]}` or `{not: expr}`: a combinator, on its own.
- `{field: <path>, <op>: <operand>, ...}`: one or more operators, ANDed.
- `{count: <child scope>, where: expr, gt: n}`: how many children pass `where`, compared.

To combine a combinator with anything else, wrap both in `all`.

| Operator | Meaning |
|---|---|
| `eq` | scalar equality; a boolean never equals a number; an absent field equals null |
| `in` | equals one of a list of scalars |
| `contains` | substring of a string, member of a list |
| `regex` / `not_regex` | `re.search` on a string (inline flags, e.g. `(?i)`); a non-string never matches |
| `exists` / `nonblank` / `truthy` | take `true` or `false` |
| `gt` `gte` `lt` `lte` | numeric; false for a non-number |
| `len_gt` / `len_lt` | length of a string, list or mapping; absent = 0 |

**Field paths.** `properties.column_type` walks the item. A non-numeric step on a list
maps over it, and a numeric step indexes it. `parent.` (repeatable) reads the enclosing
item, and `@name` is a derived field. A missing key yields null, never an error.

**Message placeholders** per mode (Python `str.format`; any other name fails the gate):

| Mode | Placeholders |
|---|---|
| `each` | `name`, `value`, `{obj.<path>}` (a field of the object), `{@field}` |
| `ratio` | `name`, `value`, `matched`, `total`, `pct`, `unmatched_names`, `matched_names` |
| `count` | `name`, `value`, `count`, `total` |
| `group` | `name`, `value`, `key`, `size`, `members`, `values` |
| `pairwise` | `name`, `value`, `a`, `b`, `similarity`, `shared`, `union` |
| `composite` | `name`, `value`, `score`, plus one per component |

`{name}` is the finding's object name, which can differ from the item's own: an RLS rule
reports its Table, a model table its alias. Use `{obj.name}` for the item's own name.
Name lists format as `{names}` (first 5, then "(+N more)"), `{names:head3}`,
`{names:head3+}` or `{names:all}`.

`legacy_threshold` reproduces the per-check `threshold` dict audit JSON carried before the
catalog. Give it to a new rule only if a reader needs one; `bands` already carries the
grading.

---

## `requires` vs `uses` — what the audit fetches

The audit fetches, for the rules that will run, the union of their `requires` and `uses`,
whichever category selected each rule:

| Data | Fetched |
|---|---|
| `model_tml`, `table_tml`, `metadata`, `dependents` | every audit, whatever the rules declare |
| `ai_instructions`, `answers`, `sets` | only when a selected rule declares them |

- **`requires`** both fetches the data and gates: an object lacking it is **skipped**.
  A3 requires `ai_instructions`, so a Model whose lookup failed is not judged.
- **`uses`** fetches but never gates. The rule reads the data and still judges an object
  without it: A5 scores a Model whose lookup failed as uncoached.
- `uses` takes only conditional data (`dependents`, `ai_instructions`, `answers`, `sets`).
  Model and Table TML and metadata are always fetched, so there is nothing to declare.
  `dependents` is fetched every audit today but is still declared, because Set discovery
  writes into it.
- A reader of `dependents` must also declare `sets`: Set rows are only present when Sets
  were fetched.
- Neither key is overridable per profile.

**The read-declaration gate.** Each derived field (`@register(name, uses=...)`), code rule
(`@code_rule(..., uses=...)`) and scope (`SCOPE_USES`) declares the conditional data it
reads. The catalog gate fails a rule whose scope, `@fields` or code read data its
`requires ∪ uses` does not cover, so the rule cannot be starved silently when it changes
category, or when the rule that happened to fetch its data is retired. The registrations
are checked against the code by a static scan of the compiled function and everything it
reaches (`ts_cli/audit/catalog_reads.py`). A second, dynamic layer checks what each
rule's examples actually read when run (`test_audit_catalog_uses.py`).

**Its limits, documented in `catalog_reads.py`.** The static scan does not see:

- a name computed at run time (`getattr(ctx, name)` with a non-literal, `vars(ctx)`,
  `operator.attrgetter`, `eval`);
- a function reached only through a data structure, or a callable passed in or returned;
- context methods reached other than by their own name;
- in a module the gate can only compile, a module-level name bound by anything but
  `def` / `class` / `import`;
- a module imported by computed name (`importlib.import_module`, `__import__`), and
  anything reached through it;
- code outside `ts_cli.audit` reached through a module-level import (for example
  `ts_cli.sets` from `context.py`).

It also over-approximates: an attribute named like a context field on another object
counts as a read, which fails loudly and is fixed by declaring.

Write derived fields and code rules so the scan can follow them: literal attribute
access on `ctx`, plain function calls, and literal scope names passed to `iterate`. A
reach it cannot resolve (a function-local import it cannot find, a non-literal scope)
fails the gate rather than passing silently.

---

## Profiles — what may and may not change

A profile (`spotter` "Spotter-ready", `general` "General", the default) is an override
layer. A rule's `profiles.<id>` block may replace only these keys:

| Overridable | Not overridable (what the rule *means*) |
|---|---|
| `status`, `bands` (the whole list), `severity`, `message`, `remediation` | `scope`, `aggregate` (`where`, `match`, `measure`, ...), `implementation`, `requires`, `uses`, `categories`, `id` |

`legacy_threshold` is also accepted in a profile block, only to reproduce the old
per-profile threshold dict (A1, A2, A6). To inherit a key, omit it from the profile
block; a key set to null is rejected ("removes nothing — omit the key").
The validator checks every **merged** band list, after the profile is applied: ordered
worst first, with valid ops and severities. `status` per profile can switch a rule off
under one profile. The history gate and the pinned findings judge the **effective** status
under each profile.

---

## The gates

| Gate | Run | Fails on |
|---|---|---|
| Catalog validator | `python3 tools/validate/check_audit_catalog.py --root .` (pre-commit, CI) | unknown keys or vocabulary, wrong operand types, a mode without its required keys, a severity the mode cannot produce, a non-overridable override, bands out of order, an active rule without `fires` and `silent` examples, undeclared data reads, `by_severity` gaps, a stale generated doc, prose (title, description, remediation, message text) naming an engine identifier (`@field`, `code:<name>`, `engine/…`), a `legacy_threshold` number that is not one of the rule's band values under that profile |
| Rule-id history | the same script with `--base origin/main` (CI) or `--merge-base-with origin/main` (pre-commit) | an id removed since the base (retire it instead), an id retired under every profile at the base that is active under any profile now (a reused id), or a rule whose bands changed while its `description` still quotes a band value no profile grades by now. Pre-commit skips with a notice when git has no merge base |
| Generated docs | `python -m ts_cli.audit.generate --check` (from `tools/ts-cli/`; the validator runs it too) | `check-catalog.md`'s generated block, or a GENERATED block in `SKILL.md` (categories, profiles and what they change, the rule-id table), differs from the catalog |
| Examples as tests | `pytest tools/ts-cli/tests/test_audit_rule_examples.py` | `fires` produces no finding, or one at a severity other than stated; `silent` produces any finding |
| Pinned legacy findings | `pytest tools/ts-cli/tests/test_audit_pinned_findings.py` | any of the 51 pinned rules reports, on any committed input under either profile, anything but its pinned findings (exact types, multiset) |

**Pinned findings.** Before the old check functions were deleted, every one of the 51
rules they ran was run over every committed test input under both profiles. The answers
are pinned in `tools/ts-cli/tests/audit_rule_fixtures/legacy_findings.json.gz`. The pinned
set is frozen: the file's own `rules` list, mirrored by `PINNED_RULE_IDS` in
`tests/audit_pinned.py`, and a test fails if they differ. A rule added later is **not**
pinned; its examples are its regression net. A pinned rule changed on purpose moves its
pin with the re-pin helper:

```bash
PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --rule D3 --dry-run 2>/dev/null
PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --rule D3 2>/dev/null
PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --input <fixture name> 2>/dev/null
PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --drop-rule D3      # retired rules only
PYTHONPATH=tools/ts-cli python tools/ts-cli/tests/repin_findings.py --drop-input <name> # a removed/renamed input
```

It rewrites only the named entries, from the current catalog. A rule not active under a
profile pins to `[]` there. It prints a before/after for every entry it changes, and the
gzip shows in a PR only as "Binary files differ", so **paste that output into the PR
description**. The before/after is on stdout; stderr carries progress lines, hence
`2>/dev/null`. Redirect it to a file to paste from (`> repin-D3.txt`): piping it into
`head` can kill the helper before it writes the pin, once the output outgrows the pipe. `--drop-rule` is refused while the rule is active under any profile.
`--drop-input` takes out a committed input you removed or renamed (refused while the
builder is still committed); re-pin the new name with `--input`.

---

## Procedures

### 1. Add a rule

1. **Restate it in plain English and confirm.** Say what object it reports on, what makes
   it fire, the severity at each level and under each profile, and what the finding says.
   Ask: "Is this the rule you mean?" Do not write YAML until the user says yes.
2. **Choose the shape.**
   - Scope: the object a finding is about.
   - Mode: one finding per bad item (`each`), a share (`ratio`), a count (`count`),
     duplicates or divergence across items (`group`), similar pairs (`pairwise`), or a
     score (`composite`).
   - Grading: `bands` for a measured value, `severity` (fixed or mapped) for presence.
   - Profiles: does either profile grade it differently, or switch it off?
   - Categories: the first is its primary; list more if it belongs in several tabs.
   - Data: `requires` / `uses`.
   - Id: the next free number in its category, never one listed under "Retired rules"
     in [check-catalog.md](check-catalog.md).
3. **Write the entry** in `rules/<category>.yaml`, and two fixtures in
   `tools/ts-cli/tests/audit_rule_fixtures/<category>.py`. Each fixture is a public,
   no-argument function returning an `AuditContext`, with invented names and GUIDs only:
   never TML exported from a real cluster. Add one builder per shape the rule needs rather
   than reshaping an existing one, because other rules refer to fixtures by name. Point
   `examples.fires` (with `severity`, and `profile` if it differs from the default) and
   `examples.silent` at them.
4. **Validate:** `python3 tools/validate/check_audit_catalog.py --root .` until it passes.
   It will also say the generated doc is stale; step 6 fixes that.
5. **Run the examples:**
   `pytest tools/ts-cli/tests/test_audit_rule_examples.py -k <ID> -q`. Then add boundary
   tests if the rule has bands or a mapping: one input just inside and one just outside
   each level, under each profile it differs in.
6. **Generate:** `(cd tools/ts-cli && python -m ts_cli.audit.generate)`. The subshell
   keeps you at the repo root for the next step.
7. **Show the user the generated row:**
   `grep -n "^| <ID> |" agents/cli/ts-audit/references/check-catalog.md`. This is how the
   rule will read to every audit reader. Confirm it says what they asked for.
8. **Run it on real data**, where a ThoughtSpot profile is configured. Capture a snapshot
   once, **outside the repository**, then replay it offline as often as needed:

   ```bash
   ts audit run --models <guid> [--models <guid> ...] --profile <profile> \
     --snapshot-out ~/audit-snapshots/<name> -o /dev/null
   ts audit run --snapshot-in ~/audit-snapshots/<name> --angles <category> \
     [--assessment spotter|general] -o /tmp/after.json
   python3 - /tmp/after.json <ID> <<'EOF'
   import json, sys
   for f in json.load(open(sys.argv[1]))["findings"]:
       if f["check_id"] == sys.argv[2]:
           print(f["severity"], f["object_type"], f["object_name"], "—", f["detail"])
   EOF
   ```

   Show the user the rule's findings. A replay refuses a selection whose rules read data
   the snapshot did not capture (for example a new rule that `requires: [answers]` on a
   snapshot taken with `--angles A`); capture again with that category. Snapshots hold
   real exported TML: never commit one, and never paste findings that name customer
   objects into the repo or a PR. `--snapshot-out` refuses, before fetching, a directory
   inside any git work tree and a non-empty directory that holds no earlier snapshot.
9. **Full checks:** `pytest tools/ts-cli/tests/ -q` and
   `python3 tools/validate/check_audit_catalog.py --root . --base origin/main`. A new rule
   needs no list edited anywhere: counts, the registry tests and the report meta all read
   the catalog, and a new rule is not pinned. A failure outside the rule's own tests is a
   finding about the rule, not a list to update.
10. **Commit** the rule, fixtures, tests and the regenerated `check-catalog.md` and `SKILL.md` together. At PR
    time, bump the ts-cli MINOR version, the ts-audit skill MINOR version with a
    changelog row, and add a CHANGELOG.md entry (see `.claude/rules/versioning.md`).

### 2. Change a rule

Follow procedure 1 with these differences.

- **Step 1** restates the change: the rule as it is, as it will be, and what that does to
  findings. "D3 INFO findings disappear; HIGH unchanged."
- **Before editing**, replay the snapshot and keep the result (`-o /tmp/before.json`).
  After the edit, replay again and show the user the before/after counts per severity:

  ```bash
  python3 - /tmp/before.json /tmp/after.json <ID> <<'EOF'
  import collections, json, sys
  for path in sys.argv[1:3]:
      found = [f for f in json.load(open(path))["findings"] if f["check_id"] == sys.argv[3]]
      print(path, len(found), dict(collections.Counter(f["severity"] for f in found)))
  EOF
  ```

  For a per-finding diff, `ts_cli.audit.equivalence.compare_findings(old, new)` takes the
  two `findings` LISTS (`json.load(open(path))["findings"]`, not the whole documents) and
  returns `only_old`, `only_new` and `changed`.
- **If the rule is one of the 51 pinned rules**, `test_audit_pinned_findings.py` fails
  until the pin moves. Re-pin it (`repin_findings.py --rule <ID> 2>/dev/null`, `--dry-run`
  first), check that the printed before/after is exactly the change the user approved,
  and paste it into the PR.
- **A rule that shares a threshold or logic with another moves with it.**
  `test_shared_rule_pairs_stay_in_step` (`test_checks_registry.py`) deliberately holds
  the pairs the data/perf split created to one value (BL-304): D4/P4, S9/P14, S8/P15,
  and P8's column ceiling and P7's depth bands, which equal D1's constants in
  `engine/tml.py` (`MAX_MODEL_COLUMNS`, `JOIN_DEPTH_*`), together with their
  `legacy_threshold`s. Change both sides in the same edit. Changing P8's 75 means
  changing `MAX_MODEL_COLUMNS`, which changes D1's findings too, so re-pin both
  (`--rule P8`, then `--rule D1`).
- **The rule's own behaviour tests** assert what it did before, on purpose: list them with
  `grep -rln "\"<ID>\"" tools/ts-cli/tests --include='test_*.py'` and update each one
  that pins the old threshold, severity or wording (`test_checks_<category>*.py`, the
  rule's boundary tests). Every other test is independent of any one rule's grading; if a
  test outside that list fails, treat it as a finding, not something to edit.
- **Never change what an id means.** Narrowing a threshold or fixing a defect is a change.
  Checking something else entirely is a new rule plus a retirement.
- A profile-specific change goes in `profiles.<id>`; a change for both goes at the rule's
  top level. Remember a band list is replaced whole.
- **A threshold lives in up to three places; move all of them.** When a rule's `bands`
  change, under any profile, also change (a) its `legacy_threshold` — the old checks'
  payload, e.g. A1's `{green: 50, assessment: …, yellow: 25.0}` — under the same profile
  (add `profiles.<id>.legacy_threshold` when only one profile's bands move), keeping its
  keys, key order and number types as they are; and (b) any number its `description`
  quotes ("General 50%"). The catalog gate fails a `legacy_threshold` number that is not
  one of that profile's band values, and the history gate fails a description still
  quoting a band value that changed. Neither can see a number the description words some
  other way ("half"), so re-read the description. Making A1 stricter for General (50 →
  60) is: `profiles.general.bands` (HIGH < 30, MEDIUM < 60),
  `profiles.general.legacy_threshold: {green: 60, assessment: '{profile_label}', yellow:
  30.0}`, and "General 60%" in the description.
- A behaviour change is a PATCH (a fix) or MINOR (new grading) skill bump, and its
  changelog row says what findings change.

### 3. Retire a rule

1. Confirm with the user. Retiring removes the rule's findings from every future audit.
2. Set `status: retired` on the entry. **Never delete the entry, and never reuse the id.**
   The history gate fails either. To switch it off under one profile only, set
   `profiles.<id>.status: retired` instead; then its `fires` example must name the
   profile it still runs under (`profile: spotter` when you retire it under the default,
   `general`), or the example test fails.
3. Leave the logic in place, or remove `aggregate` / `implementation` if no profile revives
   it. For a code rule (`implementation: code:<name>`) removing `implementation` orphans
   its registered function: delete the `@code_rule` function and its unit tests in the
   same change (`test_every_registered_code_rule_is_used_by_a_shipped_rule` and
   `test_a_code_rule_left_behind_is_detected` fail on a registration no rule names), or
   keep the `implementation`. Rewrite `description` to say the rule is retired and why ("Retired 2026-11: …"). It
   is the "Why" column under "Retired rules", and a test requires the word "retired" in
   it, so a detection description left unchanged fails.
4. If it is pinned, `repin_findings.py --rule <ID>` re-pins it to `[]`. Keeping it pinned
   proves it stays silent. Only if it should leave the pinned set,
   `repin_findings.py --drop-rule <ID>`, and remove it from `PINNED_RULE_IDS` in the same
   change.
5. Regenerate (`(cd tools/ts-cli && python -m ts_cli.audit.generate)`): it moves to
   "Retired rules", with its `description` as the reason. There is no other list of
   retired rules to update: the tests read `status: retired` from the catalog.
6. **The rule's own behaviour tests** expect it to fire. List them with
   `grep -rln "\"<ID>\"" tools/ts-cli/tests --include='test_*.py'`, and delete or invert
   (assert silence) each one that asserts a finding. A retired rule reports nothing,
   so they fail.
7. Run the full suite, then add a changelog line to the ts-audit skill's `## Changelog`
   saying which rule was retired and why.

### 4. Add a category

Categories are data, but a new one reaches further than a rule:

1. Add an entry to `categories.yaml`: `id` (a new capital letter, never reused), a unique
   `angle_key` (the `angle` value its rules' findings carry), `label`, `order`,
   `description`.
2. Move or add the rules that belong in it (`categories: [X, ...]`). A rule may belong to
   several categories. Its first category sets its finding's `angle`. Keep each rule in
   the rules file of its primary category, or add `rules/<name>.yaml`.
3. Update the one test that deliberately pins the category list,
   `test_loads_categories_and_profiles` in `test_audit_catalog.py` (a regression net:
   ids, labels and order are what audit JSON readers key on). Every other test reads the
   categories from the catalog, or checks only that the five fixed ones are still there;
   if another fails, treat it as a finding. Then update the ts-audit
   skill everywhere it lists categories: the "Audit angles" table at the top, Step 0's
   "B. Available angles" list, the Step 2a menu including its "X  All angles (A, D, H, P,
   S)" line and the `--angles` examples, and the Step 5 catalog table.
4. Regenerate, and render a report (`ts audit report`) to check the new tab and heatmap
   column.
5. Known limit: the legacy `summary.by_angle` counts only the five original angle keys.
   A new category's findings are counted in `summary.by_category`, which the report reads.

Category ids `A`, `D`, `H`, `P`, `S` are fixed. Never rename one.

### 5. Add a derived field

Add a derived field when a rule needs a value a field path cannot express: a default the
schema implies, a join graph, a lookup into another document.

1. Write a **pure function** of `(item, ctx)` in `engine/fields*.py`:

   ```python
   @register("is_wide", uses=(),          # the conditional data it reads; () for none
             label="the Model is wide")   # how it reads in generated text
   def is_wide(item, ctx):
       return len((item.get("obj") or {}).get("columns") or []) > 75
   ```

   `uses` and `label` are required. `label` is how the field reads to an audit reader:
   generated text (the report, the ERD's "Fix." line, `check-catalog.md`) writes it in
   place of `@is_wide`, so it is a clause for a true/false field ("the Model is wide")
   and a noun phrase otherwise ("the join type"). Declare `values=(...)` when a severity
   `map:` will key on it.
   Import anything heavier than the standard library inside the function: the catalog
   gate imports these modules under a bare Python 3.9 with only PyYAML. Use `memo.cached`
   for per-run lookups over the whole context rather than recomputing them per item.
2. **Unit-test it** beside the existing field tests (`tests/test_audit_engine.py`), covering
   absent data (it must return null or a default, never raise), and each branch.
3. Use it as `field: "@is_wide"` (or `{@is_wide}` in an `each` message), then run the
   catalog gate. It checks the rule's `requires ∪ uses` covers what the field declares,
   and that the declaration covers what the code reads.

### 6. When to write a code rule

Prefer declarative. Write a code rule only when the rule needs a mode, an operator or a
cross-rule dependency that nothing else would use. Examples:

- one rule grading several measures against separate thresholds (D1);
- one item yielding several independent findings (D2);
- a finding that depends on another rule's result.

A one-off value is a derived field, not a code rule. Then:

1. Register the function: `@code_rule("<name>", placeholders={...}, severity=...,
   uses=..., label="graded per join, on its key types and key count")` in
   `engine/code_rules*.py`. `label` says how it grades, in words: generated text shows it
   where a fixed-severity code rule's grading goes, never `code:<name>`, signature `(rule, ctx, profile) -> list[Finding]`.
   It receives the **effective** rule, with profile overrides applied. Grade with
   `bands.classify(value, rule.bands)`, word with `rule.message`, and never read the
   profile block yourself. Every finding's `check_id` must be the rule's id.
2. The catalog entry is complete as for any rule: `implementation: code:<name>`, no
   `aggregate`, and the severity source the registration declares. Give the reason it is
   code in a YAML comment beside `implementation:`, not in `description`: the
   description is read by audit readers, and the gate fails one naming `code:<name>`.
3. Examples, generate, snapshot and pinning work as in procedure 1. Add unit tests for
   each branch of the function.
