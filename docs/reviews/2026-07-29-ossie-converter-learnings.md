# Ossie converter review — learnings for thoughtspot-agent-skills

**Date:** 2026-07-29 · **Sources:** apache/ossie @ c26b61c · **Companion spec:** docs/superpowers/specs/2026-07-29-ossie-thoughtspot-converter-design.md

## 1. Upstream architecture (spec, schema, shared tooling)

### Open-question answers

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | custom_extensions `data` shape | String-only. The JSON Schema constrains `CustomExtension.data` to `"type": "string"` with `additionalProperties: false` on the object — a nested object is rejected by schema validation, not just discouraged by convention. `spec.md`'s own schema block documents it the same way (`data: string  # JSON string containing vendor-specific data`), and the reference Python model (`OSICustomExtension`) types the field as a plain `str`. All three layers (schema, prose, Pydantic model) agree. **Implication for our converter:** the THOUGHTSPOT `custom_extensions` payload must be a *serialised JSON string*, never emitted as a nested YAML/JSON object; round-trip tests must `json.loads()` both sides and compare the parsed structures, not do a raw string comparison (whitespace/key-order in the serialised JSON is not guaranteed stable). | `core-spec/osi-schema.json:73-76` (`"data": {"type": "string", "description": "JSON string containing vendor-specific data"}`, inside the `CustomExtension` def at `osi-schema.json:66-80`); `core-spec/spec.md:427-429`; `python/src/ossie/models.py:88-94` (`class OSICustomExtension(BaseModel): ... data: str`) |
| 2 | Go CLI plugin contract for converters | The Go CLI's plugin contract is real but **not yet satisfied by any shipped converter, including databricks**. `plugin.go` defines the on-disk manifest shape (`plugin.yaml` with `ossie_plugin_spec`, `ossie_spec_version`, `name`, `platform`, `setup`, and `convert.to_ossie.invoke`/`convert.to_ossie.accepts`/`convert.from_ossie.invoke` command arrays); `discover.go` scans a plugins directory for subdirectories containing a `plugin.yaml` and validates required fields are present. `invoke.go` shows the runtime contract once a plugin is discovered: the CLI spawns `invoke[0]` with `invoke[1:]` as args, cwd'd to the plugin directory, writes a JSON `{"files": {...}}` envelope to the subprocess's **stdin**, and expects a JSON `{"files": {...}, "issues": [...]}` envelope back on **stdout**. Neither `ossie convert` (`cli/cmd/convert.go:45-48`) nor `ossie plugin install` (`cli/cmd/plugin/install.go:35-38`) is implemented yet (`fmt.Fprintln(cmd.OutOrStdout(), "not yet implemented")`), and no `plugin.yaml` file exists anywhere in the repo (confirmed by a repo-wide `find -iname plugin.yaml`, zero hits). The databricks converter's `cli.py` is a plain `argparse` program (`ossie-databricks export -i model.yaml -o view.yaml`) that reads/writes files by path via `-i`/`-o` flags — it does not speak the stdin/stdout JSON envelope the Go CLI expects, and it ships with no `plugin.yaml`. **Conclusion:** pip-installed converter CLIs (`ossie-databricks`, `ossie-snowflake`, etc.) are today invoked directly by users/scripts, entirely independently of the Go CLI's plugin-discovery mechanism — that mechanism is scaffolding (types + discovery + invoke plumbing) with no production wiring yet. A ThoughtSpot converter can follow the same pattern (ship a standalone pip CLI) without needing to implement the `plugin.yaml`/stdin-stdout contract, since no existing converter does either. | `cli/internal/plugin/plugin.go:1-91` (struct + `rawPlugin` YAML shape, `validate()` at `plugin.go:50-68`); `cli/internal/plugin/discover.go:15-50` (`Discover()`); `cli/internal/plugin/invoke.go:12-30` (`Request`/`Response` structs) and `invoke.go:44-83` (`Invoke()` stdin/stdout JSON protocol); `cli/cmd/convert.go:45-48`; `cli/cmd/plugin/install.go:35-38`; `converters/databricks/src/ossie_databricks/cli.py:36-74` (argparse `export`/`import` subcommands); repo-wide `find /Users/damianwaldron/Dev/ossie -iname "plugin.yaml"` → no results |
| 3 | Shared `ossie` models package usage | The brief's literal grep (`grep -rn "from ossie" converters/*/src --include="*.py" | grep -v "ossie_"`) returns **zero lines** — but this is a false negative, not a true "no converter imports it" result: `grep -rn` prints `<filepath>:<line>:<content>`, and every converter's own package directory is itself named `ossie_<vendor>` (e.g. `converters/dbt/src/ossie_dbt/msi_to_osi.py`), so the `grep -v "ossie_"` filter (matching the full `filepath:line:content` string) strips out every matching line regardless of what it imports, including genuine `from ossie import (...)` lines. Re-running the first grep alone and reading content, plus cross-checking each converter's `pyproject.toml`, gives the real answer: **2 of 9 converters depend on the shared `apache-ossie` Python package** — `dbt` (`from ossie import (...)` in `cli.py`, `osi_to_msi.py`, `msi_to_osi.py`) and `wisdom` (`from ossie import (...)` in `cli.py`, `osi_to_wisdom.py`, `wisdom_to_osi.py`), both declaring `apache-ossie>=0.2.0.dev0` in `pyproject.toml`. The remaining 7 converters define their own local models instead of depending on the shared package: `databricks`, `gooddata`, `honeydew`, `omni`, `orionbelt`, `snowflake` (all pure-Python, `pyproject.toml` dependencies limited to `PyYAML`/`jsonschema`/etc., no `apache-ossie` entry — e.g. `ossie_gooddata/models.py`, `ossie_snowflake/converter.py` define their own types) plus `polaris` and `salesforce`, which are Java/Maven converters (`pom.xml`, no Python package at all, out of scope for this Python-specific question). **Implication:** depending on the shared `ossie` package is optional, not a hard requirement of the converter ecosystem — a majority of shipped converters (7/9, or 5/7 of the Python ones) hand-roll their own model classes rather than pulling in `apache-ossie`. Our converter can reasonably choose either path; using the shared Pydantic models (`OSIDocument.to_osi_yaml()`/`to_osi_json()`) is the lower-effort, more spec-faithful option and is what the two most actively-maintained-looking converters (dbt, wisdom) already do. | `grep -rn "from ossie" converters/*/src --include="*.py" \| grep -v "ossie_"` → 0 results (false negative — filter matches full path, and every converter dir is named `ossie_<vendor>`); corrected content-only grep shows real imports at `converters/dbt/src/ossie_dbt/cli.py:32`, `converters/dbt/src/ossie_dbt/osi_to_msi.py:21`, `converters/dbt/src/ossie_dbt/msi_to_osi.py:24`, `converters/wisdom/src/ossie_wisdom/cli.py:32`, `converters/wisdom/src/ossie_wisdom/osi_to_wisdom.py:36`, `converters/wisdom/src/ossie_wisdom/wisdom_to_osi.py:28`; `pyproject.toml` dependency check: `converters/dbt/pyproject.toml` and `converters/wisdom/pyproject.toml` both list `apache-ossie>=0.2.0.dev0`; `converters/{databricks,gooddata,honeydew,omni,orionbelt,snowflake}/pyproject.toml` do not; `converters/{polaris,salesforce}/pom.xml` (Java, no Python package) |

### Validation pipeline

`validation/validate.py` is a standalone, dependency-declared (PEP 723 inline script metadata: `jsonschema`, `pyyaml`, `sqlglot`) validator run as `python validation/validate.py <yaml_file> [--schema <schema_file>]`. It performs four layered checks against a parsed Ossie YAML document, in order, and only proceeds to later checks if the document actually contains a `semantic_model` key:

1. **JSON Schema validation** (`validate_schema`, `validate.py:78-85`) — validates the raw parsed YAML dict against `core-spec/osi-schema.json` (Draft 2020-12) using `jsonschema.Draft202012Validator`. This is the authoritative structural gate: required fields, enum membership (`Dialect`, `DataType`), and `additionalProperties: false` on every `$defs` object (so unknown/extra keys anywhere in the document fail validation).
2. **Uniqueness checks** (`validate_unique_names`, `validate.py:99-128`) — dataset names unique within a model, field names unique within a dataset, metric names unique within a model, relationship names unique within a model.
3. **Reference checks** (`validate_references`, `validate.py:131-149`) — every relationship's `from`/`to` must name a dataset that actually exists in the same model.
4. **SQL syntax validation** (`validate_sql`, `validate.py:152-219`) — for every field/metric expression, for every dialect entry, parses the expression with `sqlglot` (dialect mapped via `DIALECT_MAP`: `SNOWFLAKE`→`snowflake`, `DATABRICKS`→`databricks`, `BIGQUERY`→`bigquery`, `ANSI_SQL`→sqlglot default/`None`; `MDX`/`TABLEAU`/`MAQL` are explicitly skipped as unparseable by sqlglot). Tries parsing the raw expression first, then falls back to wrapping it in `SELECT <expr>` (to tolerate bare column-reference expressions like `customer_id` that aren't valid standalone SQL). A failure to parse in either form is a hard error.

Exit behaviour: schema/unique-name/reference/SQL errors are all fatal (`sys.exit(1)`); a missing `sqlglot` install degrades SQL validation to a warning rather than a hard failure. **What `converters/README.md` itself confirms:** its "Writing a Converter" step 1 (`converters/README.md:231`) directs an export converter to run `validate.py` against the *source* Ossie model before conversion begins. Step 9 (`converters/README.md:250`) is about the opposite end of the pipeline and a different validator: "Verify the generated **vendor** model is valid according to **the vendor's own schema or tooling**" — this is validating vendor-format output (e.g. a Databricks Metric View or Snowflake semantic model YAML) against that vendor's own tooling, not running `validate.py` on an Ossie document. Neither step mentions running `validate.py` on an import converter's Ossie *output*. **Our own inference / recommended practice (not README-confirmed):** since `validate.py` is the only tool that checks Ossie-document validity, and the four checks above (schema, uniqueness, references, SQL) are exactly the invariants an import converter's emitted Ossie document must satisfy to be usable downstream, we recommend also running `validate.py` on an import converter's output as a self-check — the README just doesn't say to do this explicitly.

## 2. Databricks converter (the pattern to follow)

### 2.1 Architecture

Four modules under `src/ossie_databricks/` (plus `__init__.py`, a thin re-export shim: `__init__.py:24-32`):

- **`_common.py`** — shared, cross-cutting concerns only, per its own module docstring ("Both directions are pure offline YAML transforms. The only cross-cutting concerns live here", `_common.py:18-23`): version constants `OSSIE_VERSION`/`MV_VERSION` (`_common.py:37,41`); the `VENDOR = "DATABRICKS"` id, used only for the `custom_extensions` stash key (matched/written in `read_stash`, `write_stash`, and `foreign_vendor_extensions`: `_common.py:182,206,209,217`) — a separate constant, `DIALECT_DATABRICKS = "DATABRICKS"` (`_common.py:47`), drives dialect selection instead, consumed by `pick_expression` (`_common.py:231`) and written by both emitters (`metric_view_to_ossie.py:314,359`); a YAML-1.2-boolean `Loader`/`Dumper` pair so a bare `on:` join key or an `on`/`off` synonym string isn't misread/miswritten as a YAML-1.1 boolean (`_common.py:113-166`); the `ConversionError` exception (`_common.py:75-76`); input-validation helpers `require`/`require_str` (`_common.py:79-103`); the stash read/write/foreign-vendor-detection protocol (`_common.py:176-218`); `pick_expression`'s dialect-preference logic (`_common.py:221-235`); and `validate_source` (`_common.py:258-280`).
- **`ossie_to_metric_view.py`** — the export direction (Ossie → Metric View), entry point `convert_ossie_to_metric_view` (`ossie_to_metric_view.py:62-87`).
- **`metric_view_to_ossie.py`** — the import direction (Metric View → Ossie), entry point `convert_metric_view_to_ossie` (`metric_view_to_ossie.py:75-91`).
- **`cli.py`** — a plain `argparse` program (no shared `ossie` CLI framework), exposing exactly the two directions as subcommands: `export` (`cli.py:42-47`) and `import` (`cli.py:49-52`), each taking `-i`/`-o` file paths (default stdout) and calling straight into the corresponding module function (`cli.py:56-74`). This is the same file-based, non-plugin CLI shape Task 1 found for this converter (`cli.py:36-74`, cited in section 1, open-question #2).

### 2.2 Expression handling

`pick_expression` (`_common.py:221-235`) is **table-driven passthrough, not parsing**: given a field/metric's `expression.dialects[]` list, it builds a `{dialect: expression}` dict and returns `DATABRICKS` if present, else `ANSI_SQL`, else `None` — the SQL string itself is never parsed or rewritten by a grammar; it is a preference lookup over dialect labels. Three narrow, regex-based string transforms sit around that passthrough:

1. **Fact-column dequalification (export, measures only).** `_convert_metric` strips a leading `<fact>.` qualifier from a measure expression via a word-boundary regex, because Databricks measure idiom references fact columns bare (`SUM(amount)`, not `SUM(orders.amount)`): `ossie_to_metric_view.py:559`.
2. **Fact-column requalification (import, measures only).** The reverse rewrite, `re.sub(r"\bsource\.", ...)`, inserted with a lambda (not a raw backreference string) so a `--name` containing regex metacharacters can't corrupt the substitution: `metric_view_to_ossie.py:356` (regression-tested at `test_metric_view_to_ossie.py:200-206`).
3. **Join-path alias qualification (both directions).** On export, a bare-identifier field on a joined dataset is prefixed with its full join-alias path (`customer.c_name`; `customer.nation.n_name` at depth 2): `ossie_to_metric_view.py:509-517`. On import, `_resolve_column` strips known alias prefixes back off, filing the field under the deepest matching alias: `metric_view_to_ossie.py:326-346`.

Only a **bare identifier** (`is_simple_identifier`, `_common.py:169-173`) is safe to alias-prefix/de-prefix this way. A complex expression on a joined (non-fact) dataset is emitted as-is with a warning on a single-level join, but **dropped** (not guessed at) when the dataset is fanned out (reached via more than one join path, i.e. a diamond) because it can't be unambiguously attributed to one instance: `ossie_to_metric_view.py:509-517`, exercised by `test_fanout_complex_expr_dropped_not_emitted_ambiguously` (`test_ossie_to_metric_view.py:565-590`). There is no SQL AST, no `sqlglot` use, and no cross-dialect translation anywhere in this converter — that is a deliberate contrast with the spec-level `validation/validate.py`'s use of `sqlglot` noted in section 1.

### 2.3 Lossless roundtrip via custom_extensions

**What gets stashed.** Three fixed key-sets, one per placement level: model-level `filter`/`parameters`/`materialization` (`_MODEL_STASH_KEYS`, `metric_view_to_ossie.py:53`); join-level `rely`/`cardinality` (`_JOIN_STASH_KEYS`, `metric_view_to_ossie.py:54`); column-level (field or measure) `format`/`window` (`_COLUMN_STASH_KEYS`, `metric_view_to_ossie.py:55`) — i.e. exactly the Metric View fields the module docstring calls out as having "no native Apache Ossie field" (`metric_view_to_ossie.py:20-22`). One additional *derived* key, `STASH_SOURCE_KEY = "source_dataset"` (`_common.py:63-67`), records which dataset was the Metric View's `source`/grain when a `one_to_many` join is present in the tree (written only in that case: `metric_view_to_ossie.py:192-195`) — without it, the exporter's default FK-sink heuristic would re-root at the wrong (many-side) dataset on re-export.

**Payload shape.** `write_stash` (`_common.py:193-209`) builds `{"_v": STASH_VERSION, **data}` (`STASH_VERSION = 1`, `_common.py:54`) and `json.dumps`s it into a single `custom_extensions` list entry: `{"vendor_name": "DATABRICKS", "data": <json-string>}` — merging into an existing `DATABRICKS` entry rather than appending a second one. `read_stash` (`_common.py:176-190`) reverses this with `json.loads`, popping the `_v` marker before returning, and raises a `ConversionError` (not a raw `json.JSONDecodeError`) if the stashed `data` string is malformed (`_common.py:184-187`, regression-tested at `test_ossie_to_metric_view.py:655-670`). This is a direct, concrete instance of Task 1's schema finding — `data` is emitted and consumed strictly as a JSON *string*, never a nested YAML/JSON object — and the fixture makes the literal shape visible: `fixtureB_ossie.yaml:39-41` shows `data: '{"_v": 1, "format": {"type": "number", ...}}'` as a quoted scalar, not a mapping.

**Restoration on the reverse trip.** `ossie_to_metric_view.py` calls `read_stash` at each level — model (`ossie_to_metric_view.py:108`), relationship (`ossie_to_metric_view.py:397`) — and re-attaches a stashed key verbatim if present; if absent, several keys (`rely.at_most_one_match`, `cardinality`) are instead *derived* from the relationship's declared key/orientation shape (`ossie_to_metric_view.py:415-428`). This stash-if-present-else-derive logic is what `test_mv_to_ossie_to_mv_is_lossless`, `test_tpcds_mv_round_trips`, and `test_one_to_many_round_trips_mv_ossie_mv` assert byte-for-byte on the parsed dict (`test_roundtrip.py:47-79`).

### 2.4 Silent-loss prevention

The two directions have **different** postures, matching the README's own claim (`README.md:33-39` — "dropped with a warning" on export, "preserved" on import, "raises a `ConversionError`" for anything that breaks a hard requirement):

- **Export (Ossie → MV): warn-and-drop**, never silent. `_warn_dropped_model` (`ossie_to_metric_view.py:632-653`) warns on foreign-vendor `custom_extensions`, model-level `ai_context`, dataset-level `ai_context`, dataset-level `description`, and relationship `ai_context` — all dropped with no MV field to hold them. `_warn_dropped_field` (`ossie_to_metric_view.py:655-660`) warns on `dimension.is_time` (no MV counterpart) and foreign-vendor extensions on a field.
- **Import (MV → Ossie): stash-or-error**, not warn-and-drop, because the whole point of this direction is losslessness. A condition-less/cross join (`metric_view_to_ossie.py:210-214`), a non-equi or otherwise-undecomposable `on` (`metric_view_to_ossie.py:216-223`), a reserved/duplicate join name (`metric_view_to_ossie.py:126-135`), or an unsupported MV `version` (`metric_view_to_ossie.py:84-88`) all raise `ConversionError` rather than being dropped — these have no equi-join / no-Ossie-relationship representation at all, so silently proceeding would emit an invalid Ossie document. The one drop-with-warning case on import is a wildcard column (`expr: source.*`, no `name` key: `_is_wildcard`, `metric_view_to_ossie.py:67-72`), warned at `metric_view_to_ossie.py:161-164` — it genuinely has no field identity, so there's nothing to stash.

**No `converter_issues`-style structured report.** Diagnostics are plain `warnings.warn()` calls via a local `_warn(scope, msg)` helper in each module (`metric_view_to_ossie.py:58-59`, `ossie_to_metric_view.py:53-54`) — there is no accumulating list of findings returned alongside the converted output. The CLI does not intercept these; Python's default warnings machinery prints them to stderr on its own. Hard failures are `ConversionError` (`_common.py:75-76`), caught once in `cli.py:65-67` and printed as `Error: {e}` to stderr with exit code 1.

### 2.5 Test strategy

Four layers, all in `converters/databricks/tests/`:

1. **Fixture-based golden tests.** Each direction is asserted against a hand-authored expected output: `test_fixtureA_export_matches_expected` (`test_ossie_to_metric_view.py:29-31`), `test_fixtureB_import_matches_expected` (`test_metric_view_to_ossie.py:27-29`), plus a TPC-DS-derived pair (`tpcds_ossie.yaml`/`tpcds_metric_view.yaml`, 89/67 lines) exercising a multi-join star with `rely`/`filter`/`format` together (`test_tpcds_export_matches_expected`, `test_ossie_to_metric_view.py:34-39`). Comparisons that touch `custom_extensions` go through `canon()` (`_util.py:40-57`), which `json.loads`s every `custom_extensions[].data` string before comparing dicts — directly operationalizing Task 1's "compare parsed JSON, not raw strings" implication.
2. **Round-trip tests on the same fixtures**, with two different equality bars (`test_roundtrip.py:25-79`): `test_ossie_to_mv_to_ossie` is *documented-lossy* — it normalizes away known drops (model name, `primary_key`/`unique_keys`, per-dataset description) via `strip_dropped` (`_util.py:60-76`) before comparing. `test_mv_to_ossie_to_mv_is_lossless` and `test_tpcds_mv_round_trips` assert **no normalization at all** (`parse(mv_out) == parse(mv_in)`), i.e. "lossless" is defined as parsed-structural equality with zero exceptions.
3. **Property-based tests** (`test_roundtrip_properties.py`) using **Hypothesis** (`pytest.importorskip("hypothesis")`, `test_roundtrip_properties.py:39`; `from hypothesis import ... given, settings`, `test_roundtrip_properties.py:41-42`), 300 examples per property (`_SETTINGS`, `test_roundtrip_properties.py:57-60`). Generation is deliberately restricted to the *round-trippable subset* of shapes (`build_metric_view`/`build_ossie`, `_roundtrip_helpers.py:156-252`), and the invariants asserted are structural equality of: source/comment/filter/materialization, every dimension's/measure's `(expr, comment, display_name, synonyms, format)` (MV direction) or `(source, fields)`/relationship-set/metric-set/description (Ossie direction) tuple, and every join's `(source, condition, cardinality, rely)` plus the join-tree nesting edges (`assert_mv_roundtrip`, `_roundtrip_helpers.py:306-324`; `assert_ossie_roundtrip`, `_roundtrip_helpers.py:344-356`).
4. **Seeded-RNG duplicate of the same properties**, so the same generation/assertion logic runs even where `hypothesis` is not installed: `test_property_mv_to_ossie_to_mv_seeded` / `test_property_ossie_to_mv_to_ossie_seeded` (`test_roundtrip.py:86-95`) drive the identical `_roundtrip_helpers` builders through a hand-rolled `RandomRnd` implementing the same `Rnd` interface (`chance`/`count`/`pick`/`text`/`colname`) as the Hypothesis driver (`_roundtrip_helpers.py:58-88`), 250 seeds per direction.

Verified locally: `python3 -m pytest tests/` from `converters/databricks/` → **75 passed, 1 skipped** (the Hypothesis test class is skipped because `hypothesis` is not installed in this environment — confirming the dual-driver design at #3/#4 actually degrades gracefully rather than silently not-running).

### 2.6 CI & packaging

**Packaging** (`pyproject.toml`): distribution name `apache-ossie-databricks` (`pyproject.toml:23`), `hatchling` build backend (`pyproject.toml:18-20`), `requires-python = ">=3.11"` (`pyproject.toml:26`), a single runtime dependency `PyYAML>=6.0` (`pyproject.toml:31-33`) — no `apache-ossie` dependency, confirming Task 1's finding that databricks does not depend on the shared package. Dev extras are `pytest>=8.0` and `hypothesis>=6.0` (`pyproject.toml:39-42`). Console-script entry point `ossie-databricks = "ossie_databricks.cli:main"` (`pyproject.toml:44-45`). Layout is `src/`-style (`packages = ["src/ossie_databricks"]`, `pyproject.toml:47-48`), with pytest config inlined (`testpaths = ["tests"]`, `pythonpath = ["src"]`, `pyproject.toml:50-52`) and reinforced by `conftest.py` inserting `../src` onto `sys.path` directly (`conftest.py:22-23`).

**CI: no workflow file exists for this converter in this checkout.** The brief's target, `.github/workflows/converter-databricks-ci.yml`, is **absent** — verified two ways: `ls /Users/damianwaldron/Dev/ossie/.github/workflows/` lists exactly 9 files (`cli-ci.yml`, `converter-dbt-ci.yml`, `converter-gooddata-ci.yml`, `converter-honeydew-ci.yml`, `converter-omni-ci.yml`, `converter-orionbelt-ci.yml`, `converter-polaris-ci.yml`, `converter-salesforce-ci.yml`, `converter-snowflake-ci.yml`) with no `converter-databricks-ci.yml` among them, and `grep -rl databricks /Users/damianwaldron/Dev/ossie/.github/` returns zero matches. The sibling workflows share one shape (e.g. `converter-snowflake-ci.yml:20-63`, `converter-dbt-ci.yml:20-63`): path-scoped `push`/`pull_request` triggers on `converters/<name>/**`, a Python matrix (`3.11`–`3.14`), `uv` installed via curl, `uv sync` (line 58 in both), then `uv run pytest` (line 63 in both). Databricks also has no `uv.lock` (present for snowflake at `converters/snowflake/uv.lock`; absent from `converters/databricks/` — confirmed via directory listing). **Net effect: this converter's 76 tests (75 passed + 1 Hypothesis-skip, this section's #2.5) currently run only when a contributor invokes them manually**, per the README's own `## Development` section (`pip install -e ".[dev]"` then `python3 -m pytest tests/`, `README.md:109-114`) — there is no CI gate wired up for it, unlike every other Python converter in the repo.

## 3. Snowflake converter

**Headline structural fact: this converter is one-directional — Ossie → Snowflake only.** The module exposes exactly one conversion entry point, `convert_osi_to_snowflake` (`converter.py:80-135`), and there is no `snowflake_to_osi`/import-direction counterpart anywhere in `converters/snowflake/` — confirmed by grepping the whole directory for `to_osi`/`from_osi`/`import_`/`export_` function definitions (zero hits besides `main`, `converter.py:518`). This is a structural break from the pattern Task 2 documented for databricks, whose three-module split (`_common.py`/`ossie_to_metric_view.py`/`metric_view_to_ossie.py`) exists specifically because both directions are implemented and need shared plumbing between them. It also breaks from what the ecosystem's own `converters/README.md` prescribes: its "Writing a Converter" guide's step 7 is "**Apply custom extensions**: Extract `custom_extensions` entries matching the target `vendor_name` and apply vendor-specific settings to the output" (`converters/README.md:246`), and its "Round-Trip Fidelity" section states "A well-implemented converter pair (**import + export**) should preserve as much information as possible during round-tripping" (`converters/README.md:263-265`) — language that presupposes every converter ships both directions. The snowflake converter ships only one, so there is no round-trip story to test at all: nothing comes back to Ossie, so there is nothing to assert losslessness against, and (per 3.5 below) no round-trip test exists in its suite.

**The converter's own README does not acknowledge this gap.** `converters/snowflake/README.md` describes the tool only in the forward direction ("Converts Ossie YAML semantic models to Snowflake Cortex Analyst semantic model YAML", `README.md:22`), and its "Limitations" section (`README.md:64-69`) calls out exactly two narrow losses — `ai_context` on relationships has no Snowflake counterpart, and metric `datatype` isn't emitted because Snowflake infers result types from expressions — with no mention that a reverse direction doesn't exist, no mention that `custom_extensions` is dropped wholesale (3.3 below), and no pointer to any external tool that could close the loop. The one place a bidirectional intent leaks through is the package metadata itself: `pyproject.toml:30` describes the distribution as a "**Snowflake Cortex Analyst <> Apache Ossie converter**" — the `<>` reads as bidirectional — but the shipped code is one arrow only.

### 3.1 Architecture

One module, not a package split. `src/ossie_snowflake/` holds `__init__.py` (16 lines, license header only — no re-export shim, no `__all__`, nothing) and a single 546-line `converter.py` that contains the whole pipeline: YAML parsing/validation (`convert_osi_to_snowflake`, `converter.py:80-135`), model/dataset/relationship/field conversion (`_convert_model` `:138-182`, `_convert_dataset` `:185-259`, `_convert_relationship` `:333-373`, `_convert_named_expr` `:292-330`), a small set of pure string helpers (`_normalize_identifier`/`_split_identifiers`/`_parse_source`, `:417-472`; `_extract_synonyms`, `:475-485`), warning plumbing (`_warn_dropped_fields`, `:488-515`), and the CLI entry point (`main`, `:518-546`) — all in one file. There is no separate `cli.py`: the console-script target points directly at `ossie_snowflake.converter:main` (`pyproject.toml:44-45`). The CLI itself has no subcommands (`-i`/`-o` only, `converter.py:522-527`) — unlike databricks's `export`/`import` argparse subcommands (Task 2, `cli.py:42-52`), there is nothing to disambiguate since only one direction exists.

`OsiConversionError` (`converter.py:51-52`) is the sole custom exception type, mirroring databricks's `ConversionError` in name and role (hard-failure signal, caught once in `main`, `converter.py:533-537`, printed as `Error: {e}` and `sys.exit(1)`) but — as 3.4 details — used for a narrower class of failure here.

### 3.2 Expression handling

`_extract_expression` (`converter.py:376-414`) is table-driven passthrough in the same sense as databricks's `pick_expression`, but narrower: it loops over a field/metric's `expression.dialects[]`, keeps whichever entry is tagged `SNOWFLAKE` and whichever is tagged `ANSI_SQL` (`:397-402`), then prefers `SNOWFLAKE` if present, else `ANSI_SQL`, else warns and returns `None` — dropping the field/metric entirely (`:404-414`, exercised by `test_fields_with_unsupported_dialect_skipped`, `test_osi_to_snowflake_yaml_converter.py:674-709`). Only two dialect labels are ever consulted; there is no third-tier fallback and — unlike databricks's `DIALECT_DATABRICKS` constant driving a vendor-specific preference — no shared dialect constant at all: both tags are hardcoded string literals inline at their respective comparison sites, `"SNOWFLAKE"` at `:399` and `"ANSI_SQL"` at `:401`.

The expression string itself is never parsed or rewritten. There are no regex transforms comparable to databricks's fact-column de/requalification or join-alias qualification (Task 2 §2.2) anywhere in this file — a cross-dataset or join-scoped expression is passed through completely unchanged. The only string manipulation in the module operates on the dataset **`source`** field (a `db.schema.table` identifier), not on any SQL expression: `_split_identifiers` (`:424-439`) splits on unquoted dots (quote-aware, so a quoted identifier containing a literal `.` isn't misread as a level boundary), `_normalize_identifier` (`:417-422`) uppercases unquoted segments while preserving quoted ones verbatim, and `_parse_source` (`:441-472`) either detects a `SELECT`/`WITH`-prefixed string as a subquery and emits `{"definition": <source, unchanged>}` (`:454-459`) or requires exactly three dot-separated parts and raises `OsiConversionError` otherwise (`:461-471`). `_convert_relationship` (`:333-373`) carries `from`/`to`/`from_columns`/`to_columns` straight across as `left_table`/`right_table`/`relationship_columns` pairs (`:351-368`) and never touches an expression string — so there is no join-path handling in the expression layer at all, in contrast to databricks's alias-prefixing/fanout-drop logic.

### 3.3 Lossless roundtrip via custom_extensions

**This dimension does not exist here — absence is the finding.** Because the converter has no reverse direction, there is no stash/restore protocol of any kind: no `write_stash`/`read_stash` pair, no `_v` version marker, no vendor-keyed payload. `custom_extensions` appears in `converter.py` exactly twice, both inside `_warn_dropped_fields` (`:488-515`): once in the docstring ("Checks for universally-dropped fields (custom_extensions, label, version)", `:491`) and once in the actual check, `if source.get("custom_extensions"): dropped.append("custom_extensions")` (`:502-503`). It is treated identically to `version` (`:505-506`) and `label` (`:508-509`) — three flat keys checked for presence and reported as dropped, never read for content. This same call fires at every level the model has — model (`:180`), dataset (`:257`), field/metric (`:328`), relationship (`:371`) — so the drop is universal, not scoped to one construct type. Regression coverage matches: `TestWarnDroppedFields.test_custom_extensions_warned` (`test_osi_to_snowflake_yaml_converter.py:741-748`) and `TestDroppedFieldsEndToEnd.test_custom_extensions_dropped_with_warning` (`:808-817`) both assert only that a warning fires and the key is absent from output — never that any content survives.

This directly contradicts the ecosystem-level guidance in `converters/README.md`: step 7 of "Writing a Converter" says a converter should "**Extract** `custom_extensions` entries matching the target `vendor_name` and **apply** vendor-specific settings to the output" (`converters/README.md:246`), and the edge-case table says unknown-vendor `custom_extensions` should be "**Ignore (do not discard) — preserve for round-tripping**" (`converters/README.md:260`). The snowflake converter does the opposite of both: it never extracts a `SNOWFLAKE`-vendor `custom_extensions` entry to apply, and it discards (with only a warning) rather than preserving. Given there is no import direction to round-trip back through, preserving would have nowhere to flow anyway — but the point stands that the shipped behavior is a full inversion of the documented recommendation, not a partial gap.

### 3.4 Silent-loss prevention

One posture for the whole file: **warn-and-drop**, never stash, and no `ConversionError` is ever raised over information loss — only over structural malformation of the input document. All 14 `raise OsiConversionError(...)` sites (`converter.py:101,105,112,124,142,190,302,338,343,348,358,384,390,470`) fire on: a non-mapping YAML root, an unsupported spec `version`, a missing/empty/non-dict `semantic_model`, a missing required `name` (model/dataset/field-or-metric/relationship — four separate sites), a relationship missing `from`/`to`, a `from_columns`/`to_columns` length mismatch, a missing-or-malformed `expression` block or empty `dialects` list, and a `source` string that is neither a 3-part identifier nor a recognized subquery. Every one of these is "the document itself is incomplete or malformed" — none is "this construct exists and is well-formed but has no lossless Snowflake representation," which is the class that drove databricks's *import-direction* `ConversionError`s (condition-less join, non-equi join, reserved/duplicate join name, unsupported MV version — Task 2 §2.4). Because there is no import direction here, that second class of hard failure has no direction to occur in at all.

The soft side is a single warning helper, `_warn_dropped_fields` (`converter.py:488-515`), called at all four object levels and always reporting the same three universal keys (`custom_extensions`, `version`, `label`) plus caller-supplied `extra_dropped` entries for the `ai_context` sub-cases each call site computes locally (e.g. `_convert_model:179-180` for a dict-shaped `ai_context` with no usable synonym content, `_convert_relationship:370-371` for any relationship `ai_context` at all — relationships get no description-append treatment, so any `ai_context` there is dropped in full). Additional standalone warnings cover an unrecognized/`Opaque` `datatype` (`:64-77`), more than one `semantic_model` entry in the document (`:116-120`, only the first is converted), and a field/metric with no `SNOWFLAKE`/`ANSI_SQL` dialect (`:409-414`). As with databricks, there is no `converter_issues`-style structured/accumulating report — diagnostics are plain `warnings.warn()` calls, uncaught by the CLI, surfaced by Python's default warnings machinery on stderr. Unlike databricks, there is no export/import posture split to describe (databricks §2.4's contrast is the whole point of that section) — this converter has exactly one posture because it has exactly one direction.

### 3.5 Test strategy

One file, one layer, no fixtures. `tests/test_osi_to_snowflake_yaml_converter.py` (974 lines) holds 12 `TestX` classes covering every private helper individually — `TestNormalizeIdentifier`, `TestParseSource`, `TestExtractSynonyms`, `TestConvertDatatype`, `TestClassifyField`, `TestExtractExpression`, `TestConvertNamedExpr`, `TestConvertRelationship`, `TestConvertDataset`, `TestConvertOsiToSnowflake`, `TestWarnDroppedFields`, `TestDroppedFieldsEndToEnd` — plus one whole-pipeline class (`TestConvertOsiToSnowflake`, `:555-733`) that builds small models inline via two local helpers, `_wrap_osi`/`_minimal_model` (`:45-76`) and `_typed_field` (`:79-89`), and asserts specific output fields (e.g. `test_snowflake_dialect_preferred`, `:649-672`; `test_subquery_source`, `:711-733`). `TestConvertDatatype.test_maps_portable_datatype` (`:200-215`) is parametrized over all 9 rows of the README's own Data Type Mapping table (`README.md:43-53`), and `TestClassifyField.test_datatype_and_explicit_time_role` (`:253-270`) is parametrized over 11 `(dimension, datatype) → role` combinations. Across the file's 84 `def test_` methods (some parametrized), pytest collects **107 test cases** (`uv run pytest -q --collect-only` → "107 tests collected"); running the suite locally (`uv sync && uv run pytest -q` from `converters/snowflake/`) gives **107 passed** in 0.36s.

The one YAML fixture living in `tests/`, `example_converted_tpcds_semantic_model.yaml` (370 lines, an already-converted Snowflake-format TPC-DS model), is **never referenced by any test** — `grep -rn "example_converted_tpcds" tests/` and a directory-wide `grep -rln example_converted_tpcds converters/snowflake/` both return only the file itself. It reads as a standalone illustrative sample checked in alongside the tests, not a golden-file fixture consumed by an assertion.

Three of databricks's four test layers are **absent outright, not just thinner**, and the brief's instruction to call out absence explicitly applies to all three:
- **No fixture-based golden-file tests.** Nothing here plays the role of databricks's `test_fixtureA_export_matches_expected`/`test_fixtureB_import_matches_expected`/TPC-DS pair (Task 2 §2.5#1) — comparing a full converted document against a hand-authored expected-output file. `TestConvertOsiToSnowflake` asserts individual fields on ad hoc inline models instead.
- **No round-trip tests.** `grep -rln "roundtrip\|round_trip\|round-trip" converters/snowflake/` returns zero matches. This isn't a gap in an otherwise-bidirectional converter — there is no reverse direction to round-trip through (per the lead paragraph above), so the category has nothing to test.
- **No property-based tests, and no seeded-RNG substitute either.** `grep -rln hypothesis converters/snowflake/` returns zero matches, and there is no analog to databricks's `RandomRnd`-driven seeded fallback (Task 2 §2.5#4) — where databricks degrades gracefully from Hypothesis to a hand-rolled seeded driver, snowflake has neither.

### 3.6 CI & packaging

**Packaging** (`pyproject.toml`): distribution name `apache-ossie-snowflake` (`:28`), `hatchling` build backend (`:18-20`), `requires-python = ">=3.11"` (`:32`), a single runtime dependency `PyYAML>=5.0` (`:40-42` — one major version looser than databricks's `PyYAML>=6.0`, Task 2 §2.6) and, consistent with Task 1's open-question #3, no `apache-ossie` dependency. The only dev dependency is `pytest>=8.0` (`:23-25`) — no `hypothesis` extra, since (per 3.5) there is nothing that would use it. The console-script entry point (`ossie-snowflake = "ossie_snowflake.converter:main"`, `:44-45`) points at the single module directly, since there is no separate `cli.py`. Layout is `src/`-style (`packages = ["src/ossie_snowflake"]`, `:51-52`) with `testpaths = ["tests"]` (`:55`) — but unlike databricks there is no `pythonpath = ["src"]` pytest-config entry and no `conftest.py` (confirmed: `ls tests/` lists only the test file and the standalone example YAML — no `conftest.py`, versus databricks's `conftest.py:22-23` inserting `../src` onto `sys.path`). This has a real, empirically-verified consequence: running `python3 -m pytest tests/` directly from `converters/snowflake/` (the naive invocation, without a prior install step) fails with `ModuleNotFoundError: No module named 'ossie_snowflake'`; only `uv sync && uv run pytest` — which builds and installs the package into a project-local `.venv` before running — succeeds. Databricks's `conftest.py` shim means its tests are runnable via a bare `python3 -m pytest tests/`, no install needed; snowflake's tests are not.

**CI: the workflow this Task's brief flagged as present does exist** — `.github/workflows/converter-snowflake-ci.yml` is **63 lines**, correcting Task 2's finding that only databricks lacks a CI file (Task 2 §2.6 already used this exact file, `converter-snowflake-ci.yml:20-63`, as the reference shape for what a sibling workflow looks like — that citation is reused here as the primary subject rather than a comparator). Its shape: path-scoped `push`/`pull_request` triggers on `converters/snowflake/**` and the workflow file itself (`:22-32`), a Python matrix `3.11`–`3.14` (`:38-39`), `uv` installed via `curl | sh` (`:50-53`), `uv sync` under `working-directory: converters/snowflake` (`:55-58`), then `uv run pytest` (`:60-63`). **Net effect, contrasted with databricks (Task 2 §2.6): this converter's 107 tests run automatically on every push/PR touching `converters/snowflake/**`**, whereas databricks's 76 tests (75 passed + 1 Hypothesis-skip) run only when a contributor manually invokes `pytest` per its README's `## Development` section — there is no CI gate for databricks at all. Packaging-wise the two converters are near-identical in shape (same `hatchling`/`src`-layout/console-script pattern); the CI-wiring and local-dev-loop-friendliness axes are where they diverge, and each diverges in the *opposite* direction from the other (snowflake has CI but a less frictionless local test run; databricks has a frictionless local test run but no CI).

## 4. Comparison vs our converter skills

**Scope.** The four skills compared are `agents/cli/ts-convert-{to,from}-snowflake-sv` and
`agents/cli/ts-convert-{to,from}-databricks-mv`, plus the `tools/ts-cli/` code they drive and
the shared references they cite (`agents/shared/mappings/ts-snowflake/*`,
`agents/shared/mappings/ts-databricks/*`, `agents/shared/schemas/ts-model-conversion-invariants.md`).
`agents/databricks/skills/` is a separate Genie-Code runtime holding thin-shell skills that
defer to the same shared mappings (per `.claude/rules/runtime-coverage.md`), not a fifth
converter — it is out of scope here.

**How to read the comparison — the structural difference.** Ossie's converters are single
deterministic Python processes: read a YAML file, write a YAML file. Ours are two layers —
an **agentic** `SKILL.md` that orchestrates (object discovery, table-registration decisions,
connection selection, review checkpoints, live import/execute, post-import verification) over a
**deterministic** `ts` CLI core that does all the actual parsing, translation and emission
(`ts snowflake parse-sv` / `translate-formulas` / `build-model` / `build-sv` / `diff` /
`lint-ddl`; `ts databricks parse-mv` / `translate-formulas` / `build-model` / `build-mv`).
Every row below therefore has to name *which layer* it compares: for transformation logic the
comparable unit is `tools/ts-cli/`, not the SKILL.md; for workflow, confirmation gates and
live verification, upstream has no counterpart at all.

That split is not incidental — it is the outcome of `.claude/rules/repo-audit.md` angle 11's
"agentic → deterministic" codification drive, applied deliberately to exactly these four
skills: `ts-convert-from-snowflake-sv` 1.17.0 ("Rewire onto deterministic CLI commands …
Removes 8 inline Python code blocks"), `ts-convert-from-databricks-mv` 1.8.0,
`ts-convert-to-snowflake-sv` 1.4.0, and `ts-convert-to-databricks-mv` 1.2.0 ("deterministic
tokenizer→AST→Databricks-SQL translator"). What remains agentic in our skills is, by design,
the part Ossie's file-in/file-out model has no place for.

| Dimension | Ossie DBX converter | Ossie SF converter | Our ts-convert-* skills | Gap/learning |
|---|---|---|---|---|
| Expression translation | Dialect **selection**, not translation: `pick_expression` returns the `DATABRICKS` entry, else `ANSI_SQL`, else `None` (`_common.py:221-235`), plus three regex string rewrites around it (fact de/re-qualification, join-alias path). No AST, no `sqlglot`, no cross-dialect rewriting (§2.2) | Narrower selection only: `SNOWFLAKE` else `ANSI_SQL` else warn-and-drop the field (`converter.py:376-414`). Zero expression rewrites of any kind; the only string manipulation targets the dataset `source` identifier (§3.2) | Real bidirectional translation into a **non-SQL** target language: tokenizer→AST→target emitters (`ts_cli/sv_sql.py` + `sv_translate.py`; `ts_cli/databricks/mv_emit_sql.py`, `mv_emit_expr.py`, `mv_emit_window.py`), driven by 1,106-line and sibling mapping references with a Decision Flowchart, and gated by invariant **I7** (a `MANDATORY` "consult the reference before declaring untranslatable" block, e.g. `ts-convert-to-snowflake-sv` Step 8) | Not a like-for-like axis — Ossie never leaves SQL, so it needs no translator; ThoughtSpot's formula language is not SQL, so the Phase-3 converter *must* have one and ours is the only existing implementation. The one idea to adopt: upstream's **`ANSI_SQL` fallback tier**, which our emitters don't currently produce |
| Lossless roundtrip | `write_stash`/`read_stash` protocol: `_v`-versioned JSON **string** under `vendor_name: "DATABRICKS"`, three fixed key-sets + derived `source_dataset`, stash-if-present-else-derive on the reverse trip, asserted as parsed-dict equality with zero normalization (§2.3) | Does not exist — one direction only. `custom_extensions` is presence-checked and reported as dropped, never read for content (§3.3) | **No stash mechanism at all** — `grep -rn "stash\|custom_extension"` over the four skill dirs plus `agents/shared/mappings/ts-{snowflake,databricks}/` returns zero hits. Round-trip fidelity is verified *manually against live instances* and recorded in changelogs (`ts-convert-to-snowflake-sv` 1.5.0 round-tripped `SUPPORT_CASE_SV`; `ts-convert-from-databricks-mv` 1.9.0 "Verified via TS→MV→TS round-trip on SUPPORT_CASE") — never asserted by a test | **The biggest adoptable idea.** 13 + 10 + 8 + 10 documented limitation rows across the four coverage matrices are documented-then-lost. We already write *and* read a vendor extension blob (`with extension (CA='…')`) — but the from-direction uses it for "Type confirmation; not mapped to TML" only (from-SF coverage matrix row 31), i.e. the plumbing exists and is unused for preservation |
| Silent-loss prevention | Split posture by direction: export warn-and-drop (`_warn_dropped_model`/`_warn_dropped_field`), import **stash-or-`ConversionError`**. Diagnostics are bare `warnings.warn()` — no accumulating report (§2.4) | One posture for the whole file: warn-and-drop. All 14 `OsiConversionError` sites fire on *malformed input*, never on information loss. Also no accumulating report (§3.4) | Structured, machine-readable issue reports at every stage, JSON on stdout: `unsupported[]` + exit 1 (`parse-sv`, `parse-mv` — "the JSON is still written"; from-DBX Step 5: "Never continue silently past a non-empty `unsupported[]`"); `{total, translated, skipped}` with per-entry `name`/`block`/`reason` and `annotations[]` (`sparse_data_risk`, `pending_verification`, `one_row_per_period`, `lod_filter_asymmetry`) from `translate-formulas`; `skipped_formulas`/`dropped_join_attrs`/`unmapped_properties` from `build-sv`; `skipped: [{role, name, reason}]` + `warnings[]` from `build-mv`; a hard `ts tml lint` I1/I2/I4/I5/I8 exit-1 gate before any import; and a mandatory Step 10 human checkpoint that shows the Unmapped Properties Report before anything is written | **Where we are clearly ahead** — and it is exactly the shape the Go CLI's plugin response envelope wants (`{"files": …, "issues": [...]}`, §1 open-question #2), which *no shipped Ossie converter produces*. Adopt from upstream: the sharper **import-direction raise-don't-drop** line (our to-direction never hard-errors on loss) |
| Fixture strategy (shared TPC-DS) | Hand-authored fixtureA/fixtureB golden pairs **plus a TPC-DS-derived pair** (`tpcds_ossie.yaml`/`tpcds_metric_view.yaml`), compared through `canon()`, which `json.loads`-es every `custom_extensions[].data` before comparing (§2.5 #1) | No golden-file tests at all; the one TPC-DS-shaped YAML in `tests/` (`example_converted_tpcds_semantic_model.yaml`) is referenced by no test (§3.5) | **Worked-examples-as-oracle**: 4 Snowflake + 3 Databricks end-to-end examples under `agents/shared/worked-examples/`, declared ground truth by `agents/shared/CLAUDE.md` because each was verified against a live instance. Bound to code two ways: `tools/ts-cli/tests/test_worked_examples.py` re-validates the documented outputs against `check_sv_yaml`/`check_tml`, and `test_databricks_to_golden.py` runs the real emitter end-to-end against a fixture transcribed from `ts-to-databricks.md`. **No shared cross-platform corpus** — and no TPC-DS anywhere in the repo | Adopt a **shared vendor-neutral corpus** — Ossie's TPC-DS pair makes cross-converter comparison possible; each of our fixtures is one-of-a-kind (Dunder Mifflin, BIRD_SUPERHEROS, e-commerce transactions), so no two converters are ever exercised on the same input. Carry over *to* upstream: live-instance verification as the bar for "ground truth", and fixtures that test the **emitter**, not only the document |
| Property-based testing | Hypothesis, 300 examples per property, generation deliberately restricted to the round-trippable subset, **plus a seeded-RNG duplicate driver** (250 seeds/direction) so the same properties still run where `hypothesis` is not installed (§2.5 #3/#4) | None, and no seeded substitute either (§3.5) | **None.** `hypothesis` appears nowhere in the repo (case-insensitive scan of `*.py`/`*.toml`/`*.yml`/`*.txt`/`*.cfg`), and it is not in `tools/ts-cli/pyproject.toml`'s `dev` extra (`pytest`, `PyYAML`, `radon`, `vulture`, `pip-audit`). All 3,808 cases collected from `tools/ts-cli/tests/` are example-based | Clear one-way gap. We already have the invariants **stated as properties** — I1–I12, N1, PT1 in `ts-model-conversion-invariants.md` — but only ever check them on the specific documents a run happens to produce. Copy the **dual-driver** pattern verbatim: `validate.yml`'s 3.10/3.11/3.13/3.14 matrix legs install only `pytest pyyaml`, so a Hypothesis-only test would silently not run there |
| Packaging/CLI conventions | `apache-ossie-databricks`, hatchling, `src/` layout, `>=3.11`, single runtime dep `PyYAML>=6.0`, console script `ossie-databricks` with `export`/`import` argparse subcommands and `-i`/`-o` paths; `conftest.py` puts `../src` on `sys.path` so a bare `pytest tests/` works. **No CI workflow, no `uv.lock`** (§2.6) | `apache-ossie-snowflake`, same hatchling/`src`/console-script shape but no subcommands and **no `conftest.py`** — bare `pytest tests/` fails with `ModuleNotFoundError`, only `uv sync && uv run pytest` works. **Has** a 63-line CI workflow, 3.11–3.14 matrix (§3.6) | One distribution for everything: `thoughtspot-cli` 0.124.2 (setuptools), one console script `ts` with noun-verb subcommand groups, `requires-python >=3.10,<3.15`, warehouse SDKs behind optional extras (`[snowflake]`, `[qlik]`) so the core install stays at 4 deps. Output conventions are codified as a rule, not convention (`.claude/rules/ts-cli.md`: JSON to stdout, diagnostics to stderr, auth via `--profile`, auto-pagination). CI is one `validate.yml`: validators + full pytest on 3.12, a 3.10/3.11/3.13/3.14 matrix, `pip-audit` on push/PR plus a weekly cron | For Phase 3, follow upstream's convention (own pip dist + thin `-i`/`-o` shell over a library core) — 7 of 9 converters skip the shared `apache-ossie` package and none satisfies `plugin.yaml`, so neither is required. Copy the two-line `conftest.py` shim (SF's absence is a verified papercut). Learning *for* us: DBX's 76 uncovered tests are the cautionary tale — wire CI in the same PR as the first test |

### Expression translation

This is the row where the two designs are least comparable, and saying so precisely matters
more than scoring it. Ossie's data model carries per-dialect expression variants
(`expression.dialects[]`), so a converter's job is to *pick* the right one and hand it through:
`pick_expression` (`_common.py:221-235`) is a preference lookup over dialect labels, and the
snowflake converter's `_extract_expression` (`converter.py:376-414`) is the same idea with one
fewer tier. Neither ever parses SQL. Our converters cannot work that way in either direction,
because ThoughtSpot's formula language is not SQL — `unique count(...)`, `group_aggregate(expr,
{dims}, query_filters())`, `moving_sum(m, N, -1, [date])` have no dialect-variant relationship
to `COUNT(DISTINCT …)`, `AGG(…) OVER (PARTITION BY …)` or `range: trailing N day`. So we carry a
genuine translator on both sides, and the interesting comparison is in the *discipline around*
it rather than its existence. Two things line up almost exactly: upstream's refusal to guess
when attribution is ambiguous (a complex expression on a fanned-out dataset is dropped, not
guessed — `test_fanout_complex_expr_dropped_not_emitted_ambiguously`) is the same policy as our
`UntranslatableError` → `skipped[]` path, e.g. `rank(...)` in `ts-convert-to-databricks-mv`'s
coverage matrix L11 ("Fails loud — lands in `skipped[]`, not silently dropped or mis-mapped").
And upstream's version-gated hard failure on an unsupported input version is the same instinct
as our MV-on-MV fail-loud check. The one concrete thing to **adopt**: the `ANSI_SQL` fallback
tier. Our to-direction emitters produce exactly one dialect's SQL; an Ossie-targeting converter
should emit a `THOUGHTSPOT` dialect entry *and* an `ANSI_SQL` entry wherever the expression is
portable, and our translators are uniquely well placed to do that because at translate time
they hold both the ThoughtSpot formula and its source SQL. What the Phase-3 converter must
**carry over** from us is the I7 gate itself: a `MANDATORY` instruction to consult the mapping
reference before classifying anything as untranslatable. Upstream has no equivalent because it
has nothing to consult; a ThoughtSpot converter without it will drop translatable window and
LOD constructs, which is precisely the failure I7 was written to stop.

### Lossless roundtrip

Upstream's `custom_extensions` stash is the single most valuable idea in this review for our
own skills, because we have the identical problem and no answer to it. The four coverage
matrices document 13 (`to-snowflake-sv`), 10 (`to-databricks-mv`), 8 (`from-snowflake-sv`) and
10 (`from-databricks-mv`) limitation rows, and every one of them resolves to "documented in the
Unmapped Report, then gone" — `format_pattern`, `geo_config`, `column_groups`,
`default_date_bucket`, `custom_order`, locale aliases, `ai_context` (partial, folded into a
comment) on the way out; `ACCESS_MODIFIER: PRIVATE`, table-level synonyms, `is_enum`, sample
values on the way in. A TS→SV→TS round trip therefore cannot recover any of them, and nothing
in the repo measures how much is lost. The sharpest detail is that **we already ship the
plumbing and don't use it for this**: `ts-convert-to-snowflake-sv` emits
`with extension (CA='{ca_json}')`, and `ts-convert-from-snowflake-sv` parses that same clause —
but its coverage matrix row 31 records the from-side handling as "Parsed only … Type
confirmation; not mapped to TML". A `_v`-versioned, `THOUGHTSPOT`-keyed JSON payload written on
export and read on import is a small change to two CLI commands that would make the pair
genuinely lossy-by-declaration rather than lossy-by-default. Two upstream details are
non-negotiable if we do it: per §1 open-question #1 the payload must be a **serialised JSON
string**, and per §2.5 golden comparisons must `json.loads` both sides before comparing (the
`canon()` helper) because serialised key order is not stable. Note also *what* the reverse trip
does with the stash — stash-if-present-**else-derive** (`ossie_to_metric_view.py:415-428`
derives `rely.at_most_one_match`/`cardinality` when absent) — which is what makes a stashed
document and a hand-written one both work; a stash-only design would break on any input the
converter didn't itself produce. Against that, what we do better is worth stating plainly:
our round-trip claims are verified **against live instances** and dated
(`ts-convert-to-snowflake-sv` 1.5.0 re-parses a round-tripped `SUPPORT_CASE_SV` to
"13 tables / 12 relationships / 51 dimensions with all role-plays intact";
`ts-convert-from-databricks-mv` 1.9.0 verifies a TS→MV→TS round trip on the same object),
whereas upstream's losslessness is asserted purely offline. Offline structural equality and
live semantic verification are complements, not substitutes — the Phase-3 converter should have
both, and neither codebase has both today.

### Silent-loss prevention

Here the direction of the lesson reverses. Upstream's diagnostics are `warnings.warn()` calls
that Python's default machinery prints to stderr, with no accumulating structure in either
converter (§2.4, §3.4) — a caller cannot programmatically enumerate what was dropped. Our
pipeline emits a structured issue report at every stage: `parse-sv`/`parse-mv` write
`unsupported[]` and exit 1 while still writing the JSON, `translate-formulas` returns
`{total, translated, skipped}` with `name`/`block`/`reason` per skipped entry plus typed
`annotations[]` (`sparse_data_risk`, `pending_verification`, `one_row_per_period`,
`lod_filter_asymmetry`), `build-sv` reports `skipped_formulas`/`dropped_join_attrs`/
`unmapped_properties`, and `build-mv` returns `skipped: [{role, name, reason}]` alongside
`warnings[]`. That is then consumed twice — by a hard `ts tml lint` gate (I1/I2/I4/I5/I8, exit 1
before any import) and by the Step 10 human checkpoint, which is the thing upstream structurally
cannot have. The strategically important observation for Phase 3 is that **this already matches
the plugin contract's response envelope**: §1 open-question #2 found `invoke.go` expects
`{"files": {...}, "issues": [...]}` on stdout, and no shipped converter produces `issues` at all
because they all use `warnings.warn()`. A ThoughtSpot converter built on our summary-JSON
convention would be the first converter that can satisfy that envelope without a rewrite —
worth doing even though the Go `convert`/`plugin install` commands are still stubs, because it
costs nothing now and forecloses nothing. What we should **adopt** is upstream's harder line on
the import direction: a condition-less join, a non-equi `on`, a reserved/duplicate join name or
an unsupported version all `raise ConversionError` rather than degrade, on the explicit grounds
that the direction's purpose is losslessness. Our from-direction does this in places (MV-on-MV
fail-loud, the joinless-SV decision prompt, `unsupported[]` + exit 1) but our **to-direction
never hard-errors over loss** — every unmapped construct is a warn-and-drop into the Unmapped
Report, and the only exit-1 gates there are structural (`ts snowflake lint-ddl` errors). There
is a defensible reason (the to-direction ends at a human checkpoint that shows the report), but
the asymmetry should be a decision on record rather than an accident.

### Fixture strategy (shared TPC-DS)

Upstream's fixture story is thin in absolute terms — two hand-authored pairs and one TPC-DS pair
for databricks, nothing usable for snowflake — but it has one property ours lacks entirely:
the TPC-DS fixture is a **shared, vendor-neutral schema** that any converter in the ecosystem
can be tested against, which is what makes "does converter X handle a multi-join star with
`rely`/`filter`/`format` together?" a comparable question across converters. Our fixtures are
richer and better grounded — `agents/shared/worked-examples/` holds 4 Snowflake and 3 Databricks
end-to-end conversions, and `agents/shared/CLAUDE.md` makes them normative ("If a rule in
`mappings/` or `schemas/` conflicts with what a worked example produces, investigate before
changing either") precisely because each was verified against a live instance, which is a
stronger bar than any offline golden. They are also genuinely wired to the code, in two distinct
ways worth keeping distinct: `test_worked_examples.py` re-validates the *documented* output
against `check_sv_yaml`/`check_tml` (it explicitly does not re-run the conversion, since Claude
is in the execution path), while `test_databricks_to_golden.py` runs the *real emitter*
end-to-end against a fixture transcribed from `ts-to-databricks.md`. But every one of them is
bespoke — Dunder Mifflin, BIRD_SUPERHEROS, DUNDER_MIFFLIN_SALES_INVENTORY, COMPANY_WORKFORCE,
an e-commerce transactions MV — so no two of our converters are ever exercised on the same input
schema, and there is no TPC-DS anywhere in the repo (the only two files mentioning it are this
review and its companion spec). The cheap adoption for Phase 3 is direct: take upstream's
`tpcds_ossie.yaml` verbatim as the from-Ossie input fixture and assert the emitted Model TML
against `ts tml lint` plus a golden, which simultaneously gives us our first shared-corpus
fixture and our first cross-ecosystem comparability. The discipline to **carry over** to
upstream is the live-verification bar and the emitter-level golden: `test_databricks_to_golden.py`
is instructive here because building it *found emitter bugs and oracle divergences* and its
docstring records them rather than weakening the assertions — the opposite of the snowflake
converter's checked-in-but-unreferenced TPC-DS YAML.

### Property-based testing

This is the cleanest one-way gap in the whole comparison: upstream databricks has Hypothesis at
300 examples per property with a seeded-RNG fallback driver, and we have nothing — `hypothesis`
appears nowhere in the repo and is absent from `tools/ts-cli/pyproject.toml`'s `dev` extra, so
all 3,808 collected `tools/ts-cli/tests` cases are example-based. The reason this matters more
for us than the raw absence suggests is that **we have already written the properties down**:
`ts-model-conversion-invariants.md` states I1–I12, N1 and PT1 as universally-quantified rules
over generated Model TML ("For every entry in `formulas[]`, there must be a corresponding entry
in `columns[]`…"), and `ts tml lint` already implements the checker. What is missing is the
generator. A Hypothesis strategy producing arbitrary in-subset `parsed.json` documents, asserting
`lint_tml(build_model(parsed, translated, tables)) == []`, would test the *builder* rather than
the handful of documents our fixtures happen to contain — a materially stronger claim than any
example test we have, and one that would have caught the class of bug the duplicate-`column_id`
work (I8, ts-cli v0.92.0, shipped in `from-snowflake-sv` 1.19.0 / `from-databricks-mv` 1.10.0)
had to find the hard way. Upstream's second design decision is the one to copy most literally:
restricting generation to the *round-trippable subset* rather than generating everything and
excepting failures, which is what keeps a property test from becoming a list of known-bad
shapes. And the dual-driver arrangement — Hypothesis when installed, a hand-rolled seeded `Rnd`
implementing the same interface when not — is directly load-bearing for us: `validate.yml`
installs `pytest pyyaml radon pip-audit` on its 3.12 job and only `pytest pyyaml` on the
3.10/3.11/3.13/3.14 matrix legs, so a Hypothesis-only test would be silently skipped on every
leg as configured today, and adding the dependency to the 3.12 job alone would still leave the
four matrix legs uncovered. That is the exact failure mode upstream's `pytest.importorskip` +
seeded duplicate was built to avoid. Nothing in this row flows the other way.

### Packaging/CLI conventions

Our packaging is the stronger of the three, and its conventions are enforced rather than
merely followed: one distribution (`thoughtspot-cli` 0.124.2), one console script (`ts`) with
noun-verb subcommand groups, warehouse SDKs behind `[snowflake]`/`[qlik]` extras so the core
install stays at four dependencies, and `.claude/rules/ts-cli.md` codifying the output contract
(structured JSON to stdout, diagnostics to stderr, auth only via `--profile`, connections by
display name, transparent pagination) as a rule with pre-commit validators behind parts of it
(`check_no_inline_requests.py`, `check_pagination_convention.py`, `check_skill_cli_usage.py`,
`check_skill_flag_usage.py`) — versus upstream,
where the two converters diverge in *opposite* directions on the same two axes (DBX has a
frictionless local test loop but no CI; SF has CI but a `conftest.py`-shaped papercut that makes
bare `pytest tests/` fail). Ours is also the only side with cross-version CI over the whole
surface. For Phase 3 the right move is nonetheless to follow upstream's convention rather than
ours: ship `apache-ossie-thoughtspot` as its own pip distribution with a thin `-i`/`-o` argparse
shell over a library core, since §1 established that 7 of 9 converters skip the shared
`apache-ossie` package and *none* implements the `plugin.yaml`/stdin-stdout contract, so neither
dependency nor plugin conformance is expected of a new converter. Keeping the transformation
logic in a library rather than in the CLI entry point is what preserves the option of adding the
plugin envelope later — and, per the silent-loss row, our summary-JSON convention already
produces the `issues[]` half of it. Two small things to copy outright: DBX's two-line
`conftest.py` `sys.path` shim (its absence in the snowflake converter is a verified failure, not
a style preference), and its `PyYAML>=6.0` floor over SF's looser `>=5.0`. The cautionary
lesson runs the other way: the databricks converter's 76 tests — the best test suite in the
upstream repo — run only when a contributor remembers to invoke them, because no CI workflow
was ever wired up. Whatever repo or directory the Phase-3 converter lands in, its CI job belongs
in the same PR as its first test.

## 5. Findings and routing
_(filled by Task 5)_
