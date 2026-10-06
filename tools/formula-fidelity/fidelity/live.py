"""Live I/O: the Snowflake oracle and the ThoughtSpot scratch Table/Model/AgentQL run.

Everything here talks to a real system, so it is kept thin: the strings it sends come
from ``builders`` and the decisions about results from ``compare`` — both unit-tested.

ThoughtSpot calls reuse ``ts_cli`` rather than re-implementing it (``.claude/rules/
ts-cli.md``): the profile/token handling of ``ThoughtSpotClient``, and the import, delete,
search and AgentQL plumbing of ``ts_cli.formula_translate.validate.Validator`` — the same
scratch-object lifecycle ``ts formula translate --validate execute`` uses. Credentials only
ever come from the named profiles; nothing here reads, prints or stores a secret.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Callable, Optional

from fidelity import builders
from fidelity.compare import canon, canon_ts, error


def log(msg: str) -> None:
    print(f"  {msg}", file=sys.stderr, flush=True)


# =====================================================================================
# Snowflake
# =====================================================================================

class Warehouse:
    """One Snowflake session for the whole run (python-method profiles)."""

    def __init__(self, sf_profile: str):
        from ts_cli.commands.load import _connect_python, load_snowflake_profile

        profile = load_snowflake_profile(sf_profile)
        if profile.get("method", "python") != "python":
            raise SystemExit(f"Snowflake profile {sf_profile!r} uses method "
                             f"{profile.get('method')!r}; the harness needs a python-method "
                             "profile (one session carries the run's session parameters)")
        self.conn = _connect_python(profile, profile.get("default_warehouse"),
                                    profile.get("default_role"))

    def execute(self, sql: str) -> list[tuple]:
        cur = self.conn.cursor()
        try:
            cur.execute(sql)
            return cur.fetchall() if cur.description else []
        finally:
            cur.close()

    def keyed(self, sql: str) -> dict[str, dict]:
        return {str(k): canon(v) for k, v in self.execute(sql)}

    def table_exists(self, database: str, schema: str, table: str) -> bool:
        rows = self.execute(f"SHOW TABLES LIKE '{table}' IN SCHEMA {database}.{schema}")
        return any(str(r[1]).upper() == table.upper() for r in rows)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


def run_oracle(wh: Warehouse, case: dict, fixture: dict, fq_table: str) -> dict:
    """Expected values per key. A query error falls back to one query per key, so one bad
    row (a zero divisor) yields an ``error`` value for that key instead of losing the case."""
    sql = builders.oracle_sql(case, fixture, fq_table)
    try:
        return {"sql": sql, "values": wh.keyed(sql), "error": None}
    except Exception as exc:
        whole = str(exc)
    values: dict[str, dict] = {}
    for k in builders.key_values(case, fixture):
        try:
            got = wh.keyed(builders.oracle_sql(case, fixture, fq_table, only_key=k))
            values.update(got)
        except Exception as exc:
            values[str(k)] = error(_sf_error(exc))
    return {"sql": sql, "values": values, "error": _sf_error(whole), "per_key": True}


def _sf_error(exc: Any) -> str:
    s = str(exc)
    # "100051 (22012): 01b...: Division by zero" -> keep the message, drop the query id.
    return s.split(": ", 2)[-1].strip() if s.count(": ") >= 2 else s.strip()


# =====================================================================================
# ThoughtSpot
# =====================================================================================

_SEARCH = "/api/rest/2.0/metadata/search"


def ts_validator(profile: str):
    from ts_cli.client import ThoughtSpotClient, resolve_profile
    from ts_cli.formula_translate.validate import Validator

    return Validator(ThoughtSpotClient(resolve_profile(profile)), log=log)


def find_orphans(validator) -> list[dict]:
    """Scratch objects from earlier runs (``ZZ_FIDELITY_%_DELETE_ME``). Reported, never
    deleted: this run did not create them."""
    resp = validator.client.post(_SEARCH, json={
        "metadata": [{"type": "LOGICAL_TABLE", "name_pattern": builders.ORPHAN_PATTERN}],
        "record_size": -1, "record_offset": 0})
    try:
        rows = resp.json() or []
    except ValueError:
        rows = []
    out = []
    for r in rows if isinstance(rows, list) else []:
        name = r.get("metadata_name") or ""
        if name.startswith(builders.PREFIX) and name.endswith(builders.SUFFIX):
            hdr = r.get("metadata_header") or {}
            out.append({"name": name, "guid": r.get("metadata_id"),
                        "created_ms": hdr.get("created")})
    return out


def import_object(validator, doc: dict, name: str) -> tuple[Optional[str], Optional[str]]:
    guid, err = validator._import(doc, "ALL_OR_NONE", True)
    if err:
        return None, err
    if not guid:
        found = validator.find_by_name(name)
        guid = found[0] if found else None
    return guid, (None if guid else "import reported OK but no GUID was found")


def bisect_failures(items: list[Any], validate: Callable[[list[Any]], Optional[str]],
                    whole_error: Optional[str] = None) -> dict[Any, str]:
    """Isolate the items whose presence makes ``validate`` fail.

    ``validate(subset)`` returns None when the subset is accepted, else an error string.
    Returns ``{item: error}`` for every item that fails on its own. One bad formula cannot
    take down the batch; ``validate`` is VALIDATE_ONLY, so bisecting creates nothing.
    """
    err = whole_error if whole_error is not None else validate(items)
    if err is None:
        return {}
    if len(items) == 1:
        return {items[0]: err}
    mid = len(items) // 2
    out = bisect_failures(items[:mid], validate)
    out.update(bisect_failures(items[mid:], validate))
    if not out:  # each half passes alone, the whole does not: blame the pair, loudly
        out = {i: f"fails only in combination: {err}" for i in items}
    return out


def fetch_case(validator, model_name: str, model_guid: str, fname: str, key_col: str,
               role: str, wrapper: Optional[str], keys: list[Any]) -> dict:
    """ThoughtSpot values per key, plus the compiled SQL. On a query error, fall back to
    one query per key (mirrors the oracle), so a single erroring row is attributable."""
    stmt = builders.agentql_statement(model_name, fname, key_col, role, wrapper)
    gen = validator.agentql("generate", stmt, model_guid)
    out: dict[str, Any] = {"agentql": stmt, "sql": gen.get("executable_sql") or None,
                           "values": {}, "error": None}
    res = validator.agentql("fetch", stmt, model_guid)
    err = _agentql_error(res)
    if not err:
        out["values"] = _keyed(res)
        out["value_type"] = (res.get("columns") or [{}, {}])[-1].get("type")
        return out
    out["error"] = err
    for k in keys:
        one = validator.agentql("fetch", builders.agentql_statement(
            model_name, fname, key_col, role, wrapper, only_key=k), model_guid)
        e = _agentql_error(one)
        if e:
            out["values"][str(k)] = error(e)
        else:
            out["values"].update(_keyed(one))
    if all(v["t"] == "error" for v in out["values"].values()):
        out["values"] = {}
    out["per_key"] = True
    return out


def _agentql_error(res: dict) -> Optional[str]:
    errs = res.get("errors") or []
    if errs:
        return "; ".join(f"[{e.get('code')}] {e.get('message')}" for e in errs)
    if res.get("status") not in ("SUCCESS", None):
        return f"status {res.get('status')}"
    return None


def _keyed(res: dict) -> dict[str, dict]:
    cols = res.get("columns") or []
    vtype = cols[1]["type"] if len(cols) > 1 else ""
    return {str(r[0]): canon_ts(r[1], vtype) for r in res.get("rows") or [] if len(r) >= 2}


def teardown_ts(validator, created: list[tuple[str, Optional[str]]]) -> dict:
    """Delete (model first, then table) and confirm absence by GUID *and* by name — the
    name search also catches an object an import created without reporting its GUID."""
    remaining: list[str] = []
    outcomes: dict[str, str] = {}
    for name, guid in created:
        guids = list(dict.fromkeys(([guid] if guid else []) + validator.find_by_name(name)))
        for g in guids:
            try:
                outcomes[g] = validator.delete(g)
            except Exception as exc:
                outcomes[g] = f"error: {exc}"
        left = [g for g in guids if validator.exists(g)] + \
            [g for g in validator.find_by_name(name) if g not in guids]
        for g in left:
            log(f"CLEANUP FAILED — still present: {name} {g}. Delete it with: "
                f"ts metadata delete {g}")
        remaining.extend(left)
    return {"ts_confirmed_absent": not remaining, "remaining": remaining,
            "delete_outcomes": outcomes}


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False, default=str)
