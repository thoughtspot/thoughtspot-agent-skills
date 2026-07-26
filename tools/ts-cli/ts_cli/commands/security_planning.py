"""ts security column-rules resolve / apply / build / import.

Attaches to the `column-rules` app defined in `security.py`; split out under the
file-size gate, the way `share_planning.py` splits from `share.py`.

This is the manifest layer: TS_COLUMN_SECURITY_RULES, --init-table, and
--source uniform|file|db, mirroring `ts alias` and `ts share` so the three pipelines
read the same way.

The plan JSON is the pivot between the two routes. `apply` executes it over the API,
`build` renders it to TML and `import` pushes that, so neither route needs a --route
flag and neither can silently disagree with the other about what a plan meant.

One plan-time refusal, re-checked by BOTH executors -- `build` and `apply` -- because a
plan file is something a human can edit in between:

- A PUBLISHED table is CSR_BLOCKED by default -- a conservative CLI choice, not a
  platform restriction. Live-verified 2026-07-27: an owning-Org CSR update against a
  genuinely published table returned HTTP 204 and took effect. What is still unverified
  is whether a TENANT Org can see or use a rule set applied that way, so this stays
  refused unless overridden. A table whose publication state could not be read is
  blocked the same way, since only a successful read can support the claim that it is
  unpublished. `apply --allow-published` is the one override; `build` has none.

Alongside it sits a default, not a refusal: pruning only ever happens when asked for. A
manifest instructs about the columns it names; the columns it omits are left alone unless
--prune says otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

from ts_cli.commands.security import (
    _client_for_org,
    _fail,
    _fetch_rules,
    _post_update,
    _profile_option,
    _published_orgs,
    _read_json_envelope,
    assert_org_context,
    column_rules_app,
)
from ts_cli.csr_plan import (
    CSR_TABLE_DDL,
    build_csr_steps,
    build_update_payload,
    explain_csr_error,
    parse_rule_flags,
    parse_rule_rows,
)


def expand_uniform_rules(tables: List[str], orgs: List[str],
                         rules: Dict[str, List[str]]) -> List[Dict[str, str]]:
    """Cross the named tables with every Org and rule.

    The common case: the multi-tenancy pattern secures the same columns for the same
    group names in every tenant Org, so per-Org variation is the exception. `file` and
    `db` express that variation when it exists, without making every tenant enumerate
    identical rows.

    Nothing is defaulted. Column security decides who sees tenant data, so the tables,
    the Orgs and the rules are always the operator's explicit input.

    Pure -- no I/O.
    """
    if not tables:
        raise ValueError("--table is required (repeatable) for --source uniform")
    if not orgs:
        raise ValueError("--org is required (repeatable) for --source uniform")
    if not rules:
        raise ValueError("--rule is required for --source uniform: which columns are "
                         "restricted, and to whom, is never inferred")

    return [
        {"org_name": org, "table_name": table, "column_name": column,
         "group_name": group}
        for org in dict.fromkeys(orgs)
        for table in dict.fromkeys(tables)
        for column in sorted(rules)
        # An empty group list is meaningful: one row with a blank group_name says
        # "secured, nobody". build_csr_steps drops the blank rather than sending it.
        for group in (rules[column] or [""])
    ]


def _resolve_table(client: Any, name: str) -> Dict[str, Any]:
    """Resolve a table name or GUID to {guid, name}, refusing an ambiguous name.

    Delegates to `ts share`'s resolver rather than repeating it: it already refuses an
    ambiguous name instead of picking the first hit, which matters as much here as it
    does for sharing. Securing the wrong table's columns is the same class of mistake
    as granting the wrong table.
    """
    from ts_cli.commands.security import _resolve_object

    resolved = _resolve_object(client, name)
    return {"guid": resolved["guid"], "name": resolved["name"]}


def _get_sf_cursor(sf_profile: Optional[str]):
    """Delegates to the shared helper in commands/load.py, imported lazily as elsewhere."""
    from ts_cli.commands.load import get_sf_cursor
    return get_sf_cursor(sf_profile)


def _load_manifest_rows(source: str, csv_path: Optional[str], table: Optional[str],
                        sf_profile: Optional[str]) -> List[Dict[str, Any]]:
    """Read the rule manifest for --source file or --source db.

    Both produce the same rows, so the parser does not care which was used.
    """
    if source == "file":
        if not csv_path:
            raise typer.BadParameter("--csv is required for --source file")
        import csv as csv_module
        with Path(csv_path).open() as handle:
            return list(csv_module.DictReader(handle))
    # `table` is never empty on the only real call path: `resolve_cmd` always passes
    # `table_name or "TS_COLUMN_SECURITY_RULES"`, so only a missing --sf-profile can
    # actually trigger a usage error here. `table` is still checked, in case a future
    # caller invokes this helper directly without that default.
    if not table:
        raise typer.BadParameter("--table-name is required for --source db")
    if not sf_profile:
        raise typer.BadParameter("--sf-profile is required for --source db")
    cursor = _get_sf_cursor(sf_profile)
    cursor.execute(f"SELECT * FROM {table}")  # noqa: S608 - operator-supplied table name
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _resolve_tables_for_rows(profile: Optional[str], rows: List[Dict[str, str]],
                             prune: bool) -> List[Dict[str, Any]]:
    """Resolve every (org, table) named in the manifest, per Org.

    Reads three things the pure engine cannot know: the table's GUID, whether it is
    published (or whether that could be read at all), and -- only when pruning -- which
    of its columns are secured today.

    The publication read costs one additional `metadata/search` call per table, not
    zero: `_resolve_table` delegates to `ts share`'s `_resolve_object`, whose
    `_descriptor` discards `orgIds` when it builds {guid, name, type, subtype} -- even
    though the metadata_header carrying them was already fetched during resolution.
    Folding the publication check into that same call would mean either changing that
    shared helper (also used by `ts share`, which has no need of `orgIds`) or
    duplicating its ambiguity-refusal logic here; the extra round-trip was accepted
    instead of doing either.
    """
    wanted: Dict[str, List[str]] = {}
    for row in rows:
        names = wanted.setdefault(row["org_name"], [])
        if row["table_name"] not in names:
            names.append(row["table_name"])

    tables: List[Dict[str, Any]] = []
    for org_name in sorted(wanted):
        client = _client_for_org(profile, org_name or None)
        if org_name:
            # Without this, resolution could read the Primary Org and return GUIDs for
            # the wrong tenant's tables entirely.
            assert_org_context(client, org_name, profile)
        for table_name in wanted[org_name]:
            resolved = _resolve_table(client, table_name)
            secured: List[str] = []
            if prune:
                secured = _secured_columns(client, resolved["guid"])
            published = _published_orgs(client, resolved["guid"])
            tables.append({
                "org_name": org_name,
                "table_name": table_name,
                "table_guid": resolved["guid"],
                # None from `_published_orgs` is "could not read", not "not published":
                # `build_csr_steps` blocks an unknown rather than planning against it.
                "published": bool(published),
                "publication_known": published is not None,
                "secured_columns": secured,
            })
    return tables


def _secured_columns(client: Any, table_guid: str) -> List[str]:
    """The columns secured on ONE table today, for --prune's stale-column list.

    `_fetch_rules` flattens every top-level entry in the response, so the rows are
    filtered back to the table that was asked about. Without the filter, an entry for any
    other table would contribute its column names to this table's ``unsecure`` list --
    the protection-removing direction, and the one direction this feature must never take
    by accident.

    An entry that names no table at all is kept: exactly one table was requested, so an
    unattributable row can only be that one, and dropping it would silently stop pruning.
    """
    return [row["column_name"] for row in _fetch_rules(client, [table_guid])
            if str(row.get("table_guid") or "") in ("", table_guid)]


def _report_plan_notices(steps: List[Dict[str, Any]]) -> int:
    """Print the blocked and stale-column notices to stderr; return the blocked count.

    Split out of `resolve_cmd` (below the module-health complexity cap), mirroring how
    `share_planning.py` extracts `_grant_summary` and friends out of its own `resolve`.
    Both notices are advisory at plan time: a `blocked` step is refused later by whichever
    executor runs, `build` or `apply`; an `unsecure` step only matters if `--prune` was
    passed.
    """
    blocked = [s for s in steps if s["blocked"]]
    for step in blocked:
        print(f"  {step['blocked']}", file=sys.stderr)
    for step in steps:
        if step["unsecure"]:
            print(f"  {step['org_name']}/{step['table_name']}: --prune would unsecure "
                  f"{', '.join(step['unsecure'])}", file=sys.stderr)
    return len(blocked)


def _plan_summary(steps: List[Dict[str, Any]], blocked_count: int) -> Dict[str, int]:
    """Counts an operator can sanity-check the plan against before applying it."""
    return {
        "orgs": len({s["org_name"] for s in steps}),
        "tables": len({(s["org_name"], s["table_name"]) for s in steps}),
        "columns": sum(len(s["rules"]) for s in steps),
        "steps": len(steps),
        "blocked": blocked_count,
        "unsecure": sum(len(s["unsecure"]) for s in steps),
    }


@column_rules_app.command("resolve")
def resolve_cmd(
    source: Optional[str] = typer.Option(None, "--source",
        help="Where the rules come from: uniform, file or db"),
    org: List[str] = typer.Option([], "--org",
        help="Target Org (repeatable). Required for --source uniform."),
    table: List[str] = typer.Option([], "--table",
        help="Target table (repeatable). Required for --source uniform."),
    rule: List[str] = typer.Option([], "--rule",
        help='"COL=GROUP[,GROUP...]" (repeatable). Required for --source uniform.'),
    csv_path: Optional[str] = typer.Option(None, "--csv",
        help="Manifest CSV for --source file"),
    table_name: Optional[str] = typer.Option(None, "--table-name",
        help="Manifest table for --source db (default TS_COLUMN_SECURITY_RULES)"),
    sf_profile: Optional[str] = typer.Option(None, "--sf-profile",
        help="Snowflake profile for --source db"),
    operation: str = typer.Option("REPLACE", "--operation",
        help="Group operation for every rule: REPLACE, ADD or REMOVE"),
    prune: bool = typer.Option(False, "--prune",
        help="Also unsecure columns that are secured today but absent from the "
             "manifest. Reads current state to work out which."),
    init_table: bool = typer.Option(False, "--init-table",
        help="Print the manifest DDL and exit"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Turn a rule manifest into a reviewable plan.

    The planning stage of both routes. `apply` executes the plan over the API;
    `build` plus `import` executes it over TML.

    Only the columns the manifest names are touched. --prune opts into unsecuring the
    columns it omits, and is the one case where this command reads current state. The
    default is deliberate: an incomplete manifest under prune-by-default would silently
    unsecure columns and expose data, whereas leaving stale protection in place is
    visible and recoverable.

    A published table is marked CSR_BLOCKED here rather than failing mid-apply. This is
    a conservative default, not a platform restriction: live-verified 2026-07-27, CSR
    from the owning Org succeeds on a published table, but whether a tenant Org can see
    or use the result is unverified. Use `--allow-published` to override, or `ts share`
    column grants instead.

    Output (JSON to stdout):
      {"rows": [...], "tables": [...], "steps": [...],
       "summary": {"orgs", "tables", "columns", "steps", "blocked", "unsecure"}}

    Examples:

    \b
      ts security column-rules resolve --init-table
      ts security column-rules resolve --source uniform --org ORG1 --org ORG2 \\
        --table T2_PUBLISH --rule "COST=Finance" --rule "SALARY=" -p prod
      ts security column-rules resolve --source file --csv rules.csv -p prod
      ts security column-rules resolve --source db --sf-profile sf \\
        --table-name TS_COLUMN_SECURITY_RULES --prune -p prod
    """
    if init_table:
        print(CSR_TABLE_DDL)
        return

    if source not in ("uniform", "file", "db"):
        raise typer.BadParameter("--source must be one of: uniform, file, db "
                                 "(or pass --init-table)")

    try:
        if source == "uniform":
            raw = expand_uniform_rules(list(table), list(org),
                                       parse_rule_flags(list(rule)))
        else:
            raw = _load_manifest_rows(
                source, csv_path, table_name or "TS_COLUMN_SECURITY_RULES", sf_profile)
        rows = parse_rule_rows(raw)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if not rows:
        raise typer.BadParameter(
            "The manifest produced no rules. An empty plan would apply nothing while "
            "reporting success.")

    tables = _resolve_tables_for_rows(profile, rows, prune)
    try:
        steps = build_csr_steps(rows, tables, operation=operation.upper(), prune=prune)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    blocked_count = _report_plan_notices(steps)
    summary = _plan_summary(steps, blocked_count)
    print(json.dumps({"rows": rows, "tables": tables, "steps": steps,
                      "summary": summary}))


# ---------------------------------------------------------------------------
# ts security column-rules apply -- the API-route executor
# ---------------------------------------------------------------------------

def _steps_from_plan(input_file: Optional[str]) -> List[Dict[str, Any]]:
    """The steps out of a plan envelope, refusing an empty one."""
    envelope = _read_json_envelope(input_file)
    steps = envelope.get("steps") or []
    if not steps:
        raise typer.BadParameter(
            "The plan has no steps. Applying it would report success having changed "
            "nothing. Re-run `ts security column-rules resolve`.")
    return steps


def _refuse_blocked(steps: List[Dict[str, Any]], allow_published: bool) -> None:
    """Refuse blocked steps before anything is written.

    Re-checked here rather than trusted from `resolve`, because the plan is a file a
    human can edit in between, and because `apply` is the last point at which refusing
    still costs nothing.

    The refusal is conservative, not a platform restriction: live-verified 2026-07-27,
    an owning-Org CSR update against a genuinely published table succeeds (HTTP 204).
    So these steps CAN succeed with --allow-published; what is unverified is whether a
    tenant Org can see or use the result once applied that way.
    """
    blocked = [s for s in steps if s.get("blocked")]
    if not blocked or allow_published:
        if blocked:
            print(f"Warning: --allow-published set; applying {len(blocked)} step(s) the "
                  f"plan marked CSR_BLOCKED. The platform accepts CSR from the owning "
                  f"Org (live-verified); whether a tenant Org can see or use the result "
                  f"is unverified.", file=sys.stderr)
        return

    lines = ["Refusing to apply: the plan contains steps this CLI blocks by default.", ""]
    lines += [f"  {s['blocked']}" for s in blocked]
    lines += ["",
              "This is a conservative default, not a platform restriction: an "
              "owning-Org CSR update does succeed on a published table (live-verified "
              "2026-07-27), but whether a tenant Org can see or use the result is "
              "unverified, so applying it could silently produce protection the "
              "tenant never receives. Either unpublish the table, secure its columns "
              "with `ts share` column grants instead, or pass --allow-published to "
              "send it anyway. Where publication state could not be READ, re-run "
              "`resolve` once it can be."]
    print("\n".join(lines), file=sys.stderr)
    raise typer.Exit(1)


def _refuse_missing_org(steps: List[Dict[str, Any]]) -> None:
    """Refuse any step with no org_name, in BOTH executors, before anything is written.

    `parse_rule_rows` already refuses a blank `org_name` at plan time, so no plan
    `resolve` produces can reach here missing one -- this guards the same plan-is-a-file
    threat model as `_refuse_blocked`: a human can strip a field between `resolve` and an
    executor. Refusing it costs nothing, since no legitimate plan is ever affected.

    In `apply`, skipping the Org-context assertion for a blank `org_name` would write to
    whatever Org the profile falls back to, silently, and report success having written
    one tenant's column security into another tenant's Org.

    `build` needs it too, and this is a change from Task 9's apply-only ruling: `org_name`
    was a warning label there, but it is now the output directory that keeps two Orgs'
    documents for one table apart. A blank one collapses them into the same path.
    """
    missing = [s for s in steps if not (s.get("org_name") or "").strip()]
    if not missing:
        return
    names = ", ".join(str(s.get("table_name") or "?") for s in missing)
    raise typer.BadParameter(
        f"{len(missing)} plan step(s) have no org_name ({names}). A plan step must "
        "name its Org: applying one against the profile's default Org could write one "
        "tenant's column security into another tenant's Org.")


@column_rules_app.command("apply")
def apply_cmd(
    input_file: Optional[str] = typer.Option(None, "--input",
        help="Plan JSON from `resolve`. Omit to read stdin."),
    dry_run: bool = typer.Option(False, "--dry-run",
        help="Print the payloads without sending them"),
    allow_published: bool = typer.Option(False, "--allow-published",
        help="Send steps the plan marked CSR_BLOCKED. The platform accepts CSR from "
             "the owning Org (live-verified); whether a tenant Org can see or use it "
             "is unverified, which is why this stays opt-in rather than routine."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Apply a plan over the API: one `rules/update` call per (Org, table).

    `update` takes one table per call, so its documented "all or none" rollback covers
    each call and not the run. A failure part-way leaves earlier tables applied, and the
    command stops rather than continuing, so the plan and reality diverge at a known
    point. Re-running a REPLACE plan is safe: it converges.

    Blocked steps are refused before anything is written. Verify with
    `get` before and after and diff the two.

    Output (JSON to stdout): {"payloads": [...]} under --dry-run; a per-step progress
    log on stderr otherwise.

    Examples:

    \b
      ts security column-rules resolve --source file --csv rules.csv -p prod \\
        > plan.json
      ts security column-rules apply --input plan.json --dry-run -p prod
      ts security column-rules apply --input plan.json -p prod
    """
    steps = _steps_from_plan(input_file)
    _refuse_blocked(steps, allow_published)
    _refuse_missing_org(steps)

    payloads: List[Dict[str, Any]] = []
    for step in steps:
        # Every field is read with .get: a hand-edited plan missing one is a usage error
        # naming the step, never a KeyError traceback. An absent `table_identifier` is
        # NOT quietly substituted with `table_name` -- one is a resolved GUID and the
        # other an ambiguous name, and `build_update_payload` refuses the empty string.
        try:
            payloads.append(build_update_payload(
                step.get("table_identifier") or "", step.get("rules") or {},
                operation=step.get("operation") or "REPLACE",
                unsecure=step.get("unsecure") or None))
        except ValueError as exc:
            raise typer.BadParameter(
                f"{step.get('org_name')}/{step.get('table_name')}: {exc}") from exc

    if dry_run:
        print(json.dumps({"payloads": payloads}))
        return

    for step, payload in zip(steps, payloads):
        org_name = step["org_name"]
        client = _client_for_org(profile, org_name)
        assert_org_context(client, org_name, profile)
        _post_update(client, payload,
                     f"[{org_name}] {step.get('table_name')}: "
                     f"{step.get('operation')} "
                     f"{', '.join(sorted(step.get('rules') or {}))}")

    print(json.dumps({"payloads": payloads}))


# ---------------------------------------------------------------------------
# ts security column-rules build / import -- the TML-route executor
# ---------------------------------------------------------------------------

def _build_documents(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Render each step into a `column_security_rules` document.

    Same standard as `apply`: a hand-edited plan missing `table_name`, or carrying an
    empty one, is a usage error naming the step rather than a KeyError or a bare
    ValueError traceback. The two executors read a malformed plan the same way.
    """
    from ts_cli.csr_plan import build_csr_tml
    from ts_cli.tml_common import dump_tml_yaml

    documents: List[Dict[str, Any]] = []
    for step in steps:
        if step.get("unsecure"):
            print(f"Warning: {step.get('org_name')}/{step.get('table_name')} has "
                  f"{len(step['unsecure'])} column(s) to unsecure, which the TML route "
                  f"cannot express (no is_unsecured equivalent). Use `apply` for those.",
                  file=sys.stderr)
        try:
            document = build_csr_tml(step.get("table_name") or "",
                                     step.get("rules") or {})
        except ValueError as exc:
            raise typer.BadParameter(
                f"{step.get('org_name')}/{step.get('table_name')}: {exc}") from exc
        documents.append({"table_name": step.get("table_name") or "",
                          "org_name": step.get("org_name") or "",
                          "yaml": dump_tml_yaml(document)})
    return documents


def _document_paths(directory: Path,
                    documents: List[Dict[str, Any]]) -> List[Path]:
    """One output path per document, namespaced by Org, refusing any collision.

    Steps are per (Org, table) but the platform's own filename is derived from the table
    alone, so two Orgs' documents for one table resolve to the SAME file: the second
    write wins and the first Org's rules are lost silently, while `written` reports the
    path twice. Importing that file into the first Org then gives it the other tenant's
    column security. Under `--source uniform` the two documents happen to be identical,
    but `--source file` and `--source db` exist to express per-Org variation.

    The Org name becomes a subdirectory rather than a filename prefix, so the filename
    stays byte-identical to what the platform exports and `import` can consume either.

    A collision is refused rather than overwritten: `written` must never list one path
    twice. An Org name carrying a path separator is refused for the same reason -- it
    would write outside --out, and a plan is a file a human can edit.
    """
    from ts_cli.csr_plan import csr_tml_filename

    paths: List[Path] = []
    for document in documents:
        org_name = str(document.get("org_name") or "")
        if "/" in org_name or "\\" in org_name or org_name in (".", ".."):
            raise typer.BadParameter(
                f"Plan step org_name '{org_name}' is not usable as a directory name: "
                f"`build --out` writes each Org's documents into their own subdirectory, "
                f"and a path separator would write outside --out.")
        path = directory / org_name / csr_tml_filename(document["table_name"])
        if path in paths:
            raise typer.BadParameter(
                f"Two plan steps would both write {path}. One (Org, table) is one "
                f"document, so this plan has a duplicate step: writing it would keep "
                f"only the last one's rules while reporting both as written. "
                f"De-duplicate the plan and re-run.")
        paths.append(path)
    return paths


@column_rules_app.command("build")
def build_cmd(
    input_file: Optional[str] = typer.Option(None, "--input",
        help="Plan JSON from `resolve`. Omit to read stdin."),
    out: Optional[str] = typer.Option(None, "--out",
        help="Directory to write the .tml files into. Omit to print them only."),
) -> None:
    """Render a plan into `column_security_rules` TML documents.

    The TML route's middle stage, mirroring `ts alias build`. Emit-only: no profile, no
    connection, nothing sent. The point is that the document is reviewable before it is
    imported, which is why this is a separate command rather than a flag on `apply`.

    Each document carries its mandatory `table:` reference. `guid:` is omitted, so an
    import creates rather than updates in place; add the guid to the document by hand
    for an in-place update.

    --out writes one file per (Org, table), into a subdirectory per Org:
    `<out>/<org_name>/<TABLE>_CSR.column_security_rules.tml`. A plan step is per (Org,
    table) but the platform's filename is derived from the table alone, so without the
    Org subdirectory two Orgs' documents for one table would land on the same path and
    the first Org's rules would be lost. The filename itself is exactly what the platform
    exports.

    Note the prune asymmetry: `is_unsecured` has no TML equivalent, so a plan carrying
    `unsecure` entries cannot express them here. Those steps are reported and the
    columns are simply absent from the document. Use `apply` when pruning matters.

    Output (JSON to stdout):
      {"documents": [{"table_name", "org_name", "yaml"}], "written": [paths]}

    Examples:

    \b
      ts security column-rules build --input plan.json
      ts security column-rules build --input plan.json --out ./plan/csr
      # -> ./plan/csr/ORG1/T2_PUBLISH_CSR.column_security_rules.tml
    """
    steps = _steps_from_plan(input_file)
    _refuse_blocked(steps, False)
    # org_name is load-bearing here, not a label: it is the output subdirectory.
    _refuse_missing_org(steps)

    documents = _build_documents(steps)

    written: List[str] = []
    if out:
        directory = Path(out)
        paths = _document_paths(directory, documents)
        for document, path in zip(documents, paths):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(document["yaml"])
            written.append(str(path))
            print(f"wrote {path}", file=sys.stderr)

    print(json.dumps({"documents": documents, "written": written}))


def _report_import_failures(failures: List[Dict[str, Any]], table_name: str) -> None:
    """Print each failed item's translated message to stderr and exit non-zero.

    `metadata/tml/import` returns HTTP 200 even when every item failed -- the
    per-item outcome is buried in the body (live-observed 2026-07-27: importing a CSR
    document into an Org missing the referenced table). `resp.ok` alone cannot see
    this, so `import_cmd` calls `tml_import_failures` first and routes here when it
    finds any: printing the raw body and exiting 0 would silently import nothing while
    reporting success, the exact failure mode this whole feature guards against.

    Each failure is run through `explain_csr_error` first; only when nothing matches
    does the platform's own `error_message` stand alone.
    """
    print(f"Could not import {table_name}'s column security rules: the HTTP call "
          f"succeeded, but the platform's own per-item status says the import did "
          f"not.", file=sys.stderr)
    for failure in failures:
        raw = failure.get("error_message") or ""
        explanation = explain_csr_error(raw) or raw or (
            f"error_code {failure.get('error_code')}")
        print(f"  [{failure.get('request_index')}] {explanation}", file=sys.stderr)
    raise typer.Exit(1)


@column_rules_app.command("import")
def import_cmd(
    file: Optional[str] = typer.Option(None, "--file",
        help="A .column_security_rules.tml file. Omit to read the YAML from stdin."),
    org: Optional[str] = typer.Option(None, "--org", help="Import into this Org"),
    dry_run: bool = typer.Option(False, "--dry-run",
        help="Validate the document and print what would be sent"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Import a `column_security_rules` TML document.

    The TML route's write stage, mirroring `ts alias import`. `create_new` is False, so
    a document carrying a `guid:` updates in place.

    The `table:` reference is checked locally first. Without it the platform fails with
    code 14502 and `Referenced table with name  not found`, whose doubled space is the
    empty name interpolated -- a message that points nowhere useful.

    A per-Org name that IS present but does not resolve -- the normal outcome of
    importing into an Org lacking a same-named table -- is not caught locally, and the
    platform answers with HTTP 200: the failure is buried in the response body, not the
    status code (live-observed 2026-07-27). This command reads that body and exits
    non-zero when it finds a failed item, translating the message via
    `explain_csr_error` where it can.

    Output (JSON to stdout): the import response, or the request body under --dry-run.

    Examples:

    \b
      ts security column-rules import --file T2_CSR.column_security_rules.tml -p prod

    \b
      # `build`'s stdout is the plan-level JSON envelope, not a bare TML document, so
      # a build | import pipe would hand `import` the wrong shape. Write to disk and
      # read the file back instead -- from the Org subdirectory `build` wrote it into,
      # which is what keeps two Orgs' documents for one table apart:
      ts security column-rules build --input plan.json --out ./csr
      ts security column-rules import \\
        --file ./csr/ORG1/T2_PUBLISH_CSR.column_security_rules.tml --org ORG1 -p prod
    """
    import yaml

    if file:
        text = Path(file).read_text()
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        raise typer.BadParameter("Provide --file <path> or pipe the TML in")

    try:
        document = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise typer.BadParameter(f"Could not parse the TML: {exc}") from exc

    body = (document.get("column_security_rules") or {}) if isinstance(
        document, dict) else {}
    if not (body.get("table") or {}).get("name"):
        raise typer.BadParameter(
            "This document has no `table:` reference. It is mandatory: without it the "
            "import fails with code 14502 and `Referenced table with name  not found`. "
            "Add table.name and re-run.")

    payload = {"metadata_tmls": [text], "import_policy": "ALL_OR_NONE",
               "create_new": False}
    if dry_run:
        print(json.dumps(payload))
        return

    client = _client_for_org(profile, org)
    if org:
        assert_org_context(client, org, profile)
    resp = client.post("/api/rest/2.0/metadata/tml/import", json=payload,
                       raise_for_status=False)
    if not resp.ok:
        _fail(resp, f"Could not import {body['table']['name']}'s column security rules")

    # `tml_import_failures` lives in tml_common.py, not here, because the same gap is
    # very likely present in `ts alias import` and `ts tml import` -- both only check
    # `resp.ok` too. This PR fixes it for CSR only, to keep the blast radius small;
    # wiring the other two callers to the same helper is a follow-up, not done here.
    from ts_cli.tml_common import tml_import_failures

    result = resp.json()
    failures = tml_import_failures(result)
    if failures:
        _report_import_failures(failures, body["table"]["name"])

    print(json.dumps(result))
