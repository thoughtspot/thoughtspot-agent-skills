"""`ts formula` — translate one formula from another tool into ThoughtSpot syntax.

  translate — run the existing converter translator for the source dialect over ONE
              formula, record every column reference, list the traps that applied, and
              emit a ready-to-paste TML snippet. Optional proof that ThoughtSpot accepts it
              (--validate compile | execute) against a scratch copy of a Model.
  detect    — score which language a formula is written in; flags ties that must be asked.

The logic is in ts_cli/formula_translate/ (pure, unit-tested); this module is I/O only.
Skill: agents/cli/ts-object-formula-translate/SKILL.md.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(help="Translate one formula from another tool into ThoughtSpot syntax.",
                  no_args_is_help=True)

_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _read_expr(expr: Optional[str]) -> str:
    if expr is None or expr == "-":
        if sys.stdin.isatty():
            raise typer.BadParameter("pass the formula as an argument or on stdin")
        expr = sys.stdin.read()
    expr = expr.strip()
    if not expr:
        raise typer.BadParameter("empty formula")
    return expr


def _read_json_arg(value: Optional[str]) -> Optional[str]:
    if value and value.startswith("@"):
        return Path(value[1:]).expanduser().read_text()
    return value


def _client(profile: Optional[str]):
    from ts_cli.client import ThoughtSpotClient, resolve_profile

    return ThoughtSpotClient(resolve_profile(profile))


def _resolve_model_guid(client, model: str) -> str:
    if _GUID.match(model.strip()):
        return model.strip()
    resp = client.post("/api/rest/2.0/metadata/search", json={
        "metadata": [{"type": "LOGICAL_TABLE", "subtypes": ["WORKSHEET"], "name_pattern": model}],
        "record_size": -1, "record_offset": 0})
    rows = resp.json() or []
    hits = [r for r in rows if r.get("metadata_name") == model]
    if len(hits) != 1:
        raise SystemExit(f"--model {model!r}: expected one Model with that exact name, "
                         f"found {len(hits)}; pass its GUID")
    return hits[0]["metadata_id"]


@app.command("translate")
def translate_cmd(
    expr: Optional[str] = typer.Argument(None, help="The source formula (or '-' / omit to read stdin)"),
    source: str = typer.Option(..., "--from", "-f",
                               help="Source dialect: tableau | dax | qlik | sisense | snowflake | databricks | "
                                    "thoughtspot (already TS syntax: resolve refs + validate only)"),
    columns: Optional[str] = typer.Option(
        None, "--columns", "-c",
        help="Level 1 column map, JSON (or @file): {\"Sales\": \"ORDERS.SALES_AMT\"}, "
             "[\"ORDERS.SALES_AMT\"], or [{source, table, column, data_type, column_type, key}]"),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Level 2: a Model GUID or exact name; its columns resolve references"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                                          help="Profile (needed only with --model)"),
    validate: str = typer.Option("none", "--validate",
                                 help="none | compile (VALIDATE_ONLY, creates nothing) | "
                                      "execute (scratch Model + AgentQL, deleted after)"),
    name: str = typer.Option("Translated_Formula", "--name", "-n",
                             help="Display name for the formula (TML id is formula_<name>). "
                                  "Prefer underscores to spaces: the editor form can then "
                                  "reference it bare"),
    key_column: Optional[str] = typer.Option(
        None, "--key-column", help="Column to count rows by when the source has COUNT(*)"),
    group_by: Optional[str] = typer.Option(
        None, "--group-by", help="execute: the ATTRIBUTE a measure is probed by "
                                 "(default: the Model's first physical attribute)"),
    jaql_context: Optional[str] = typer.Option(
        None, "--context", help="sisense: the JAQL context object, JSON or @file"),
    role: Optional[str] = typer.Option(
        None, "--role", help="tableau: measure | attribute (default: inferred from aggregates)"),
    first_week_day: Optional[int] = typer.Option(
        None, "--first-week-day", min=0, max=6,
        help="qlik: the app's FirstWeekDay (0 = Monday … 6 = Sunday; US apps are usually 6). "
             "Without it a one-argument Weekday() is NEEDS_REVIEW"),
) -> None:
    """Translate ONE formula into ThoughtSpot formula syntax.

    Output: JSON to stdout — {dialect, input, formula (TML form, bracketed refs),
    formula_editor (formula-editor form, bare names), status, classification, role,
    references[], unresolved[], traps[], notes[], verification, tml}. status is
    TRANSLATED | APPROXIMATED | NEEDS_REVIEW (formula null, original kept).

    Context levels: none (placeholders [TABLE::Col]), --columns (names), --model (real
    columns; enables --validate). The user's Model is never modified.

    Exit codes: 0 = ran (read status / verification.result), 1 = the scratch Model could
    not be confirmed deleted (its GUID is printed), 2 = bad input or validation
    preconditions not met.

    Examples:

    \b
      ts formula translate "ROUND(SUM([Sales]) / COUNTD([Customer]), 2)" --from tableau
      echo "DIVIDE(SUM(Sales[Amount]), DISTINCTCOUNT(Sales[Customer]))" | ts formula translate --from dax
      ts formula translate "SUM(amount)" --from snowflake --columns '{"amount": "ORDERS.AMOUNT"}'
      ts formula translate "ROUND(AVG(salary), 0)" --from snowflake -m <model-guid> -p prod --validate execute
    """
    from ts_cli.formula_translate.adapters import normalise_dialect
    from ts_cli.formula_translate.engine import translate

    if validate not in ("none", "compile", "execute"):
        raise typer.BadParameter("--validate must be none, compile or execute")
    try:
        dialect = normalise_dialect(source)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    text = _read_expr(expr)
    if validate != "none" and not model:
        _err("--validate needs --model (context level 2)")
        raise typer.Exit(2)

    ctx, validator, model_doc = _build_context(columns, model, profile, key_column)
    result = translate(text, dialect, ctx, name=name,
                       sisense_context=_json_option(jaql_context, "--context"),
                       tableau_role=role, first_week_day=first_week_day)
    exit_code = 0
    if validate != "none":
        exit_code = _validate(result, validate, validator, model_doc, name, group_by)
    print(json.dumps(result, indent=2))
    if exit_code:
        raise typer.Exit(exit_code)


def _json_option(value: Optional[str], flag: str):
    if not value:
        return None
    try:
        return json.loads(_read_json_arg(value) or "{}")
    except ValueError as exc:
        _err(f"{flag} is not valid JSON: {exc}")
        raise typer.Exit(2)


def _build_context(columns: Optional[str], model: Optional[str], profile: Optional[str],
                   key_column: Optional[str]):
    """(ColumnContext, Validator or None, model TML or None) for the three levels."""
    from ts_cli.formula_translate.context import (
        ColumnContext, parse_columns_json, specs_from_model_tml,
    )
    from ts_cli.formula_translate.validate import ValidationError, Validator

    specs = []
    if columns:
        try:
            specs.extend(parse_columns_json(_read_json_arg(columns) or ""))
        except ValueError as exc:
            _err(str(exc))
            raise typer.Exit(2)
    level = 1 if specs else 0
    validator = model_doc = None
    if model:
        client = _client(profile)
        validator = Validator(client, log=_err)
        guid = _resolve_model_guid(client, model)
        try:
            model_doc, table_docs = validator.export_model(guid)
        except ValidationError as exc:
            _err(str(exc))
            raise typer.Exit(2)
        specs.extend(specs_from_model_tml(model_doc, table_docs))
        level = 2
        _err(f"model: {model_doc['model'].get('name')} ({guid}), {len(specs)} column(s)")
    ctx = ColumnContext(specs, level=level,
                        model_name=model_doc["model"].get("name") if model_doc else None)
    if key_column:
        spec = ctx.find(key_column)
        if spec is None:
            _err(f"--key-column {key_column!r} matches no column in the context")
            raise typer.Exit(2)
        spec.key = True
    return ctx, validator, model_doc


def _validation_blockers(result: dict) -> list[str]:
    blockers = []
    if result["formula"] is None:
        blockers.append(f"status is {result['status']} — nothing to validate")
    if result["unresolved"]:
        blockers.append(f"unresolved references: {result['unresolved']}")
    if any(r["placeholder"] for r in result["references"]):
        blockers.append("placeholder references remain")
    return blockers


def _validate(result: dict, level: str, validator, model_doc: dict, name: str,
              group_by: Optional[str]) -> int:
    """Run validation into ``result['verification']``; return the exit code."""
    from ts_cli.formula_translate.validate import ValidationError

    blockers = _validation_blockers(result)
    if blockers:
        result["verification"].update(level=level, result="NOT_RUN", error="; ".join(blockers))
        _err("validation not run: " + "; ".join(blockers))
        return 2
    try:
        ver = validator.run(level, model_doc, name, result["formula"], result["role"],
                            result.get("agentql_wrapper"), group_by=group_by)
    except ValidationError as exc:
        result["verification"].update(level=level, result="NOT_RUN", error=str(exc))
        _err(f"validation not run: {exc}")
        return 2
    except Exception as exc:  # e.g. the VALIDATE_ONLY call failing before any object exists
        result["verification"].update(level=level, result="ERROR",
                                      error=f"{type(exc).__name__}: {exc}")
        _err(f"validation error: {exc}")
        return 2
    result["verification"].update(ver)
    scratch = ver.get("scratch")
    if scratch and not scratch.get("confirmed_absent"):
        return 1  # Validator._cleanup has already logged every remaining GUID
    return 1 if ver.get("result") == "ERROR" else 0


@app.command("detect")
def detect_cmd(
    expr: Optional[str] = typer.Argument(None, help="The source formula (or '-' / omit to read stdin)"),
) -> None:
    """Score which language a formula is written in.

    Output: JSON {best, guess, ambiguous, ask[], candidates[{dialect, score, signals,
    backing}]}. When ambiguous is true, ask the user to choose among ask[] — never route
    on guess alone. Excel / Google Sheets / Omni table calc, and LookML / Omni, are always
    asked.

    \b
      ts formula detect "{FIXED [Region] : SUM([Sales])}"
    """
    from ts_cli.formula_translate.detect import detect

    print(json.dumps(detect(_read_expr(expr)), indent=2))
