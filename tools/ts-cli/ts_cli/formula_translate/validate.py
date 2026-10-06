"""``--validate compile|execute`` (spec §5.1) — prove ThoughtSpot accepts the formula.

The user's Model is NEVER modified. Both tiers work on a scratch copy of its TML: guid
dropped, renamed ``ZZ_FORMULA_PROBE_<timestamp>_DELETE_ME``, the formula and its
``columns[]`` entry appended.

- ``compile`` imports that copy with ``import_policy: VALIDATE_ONLY``. Open item OI-1,
  verified live on se-thoughtspot 2026-10-06: VALIDATE_ONLY parses formula expressions —
  a truncated expression, an unknown function, an unknown column and a wrong arity are each
  rejected with error_code 14516 — and creates no object. So ``compile`` creates nothing,
  but it also returns no SQL: ThoughtSpot only compiles SQL for a query, and a query needs
  a real Model.
- ``execute`` runs the VALIDATE_ONLY check first (a broken formula never creates an
  object), then imports the copy as a new Model, runs AgentQL ``generate-sql`` and
  ``fetch-data … LIMIT 5`` over it, and deletes it in ``finally``. Absence is then
  confirmed by search, both by GUID and by the scratch name — the name search also catches
  an object an import created without reporting its GUID.

Two traps from the 2026-10-06 ``round`` probe are encoded in ``agentql_statement``: an
aggregate formula is selected as ``AGG("name")`` (``SUM`` for a semi-additive
``last_value``/``first_value`` formula), and there is ONE formula per query plus one
grouping attribute and nothing else — a second measure made AgentQL push formulas into
GROUP BY (``[ca_3] is not a valid group by expression``).

All I/O goes through an injected client exposing ``post(path, json=..., raise_for_status=...)``
(``ts_cli.client.ThoughtSpotClient``), so every branch here is unit-testable with a fake.
"""
from __future__ import annotations

import copy
import json
import time
from typing import Any, Optional

from ts_cli.formula_translate.engine import formula_tml_entries

SCRATCH_PREFIX = "ZZ_FORMULA_PROBE_"
SCRATCH_SUFFIX = "_DELETE_ME"

_EXPORT = "/api/rest/2.0/metadata/tml/export"
_IMPORT = "/api/rest/2.0/metadata/tml/import"
_SEARCH = "/api/rest/2.0/metadata/search"
_DELETE = "/api/rest/2.0/metadata/delete"


class ValidationError(Exception):
    """A precondition failed (wrong object type, no grouping column, …)."""


def scratch_name(now: Optional[float] = None) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now if now is not None else time.time()))
    return f"{SCRATCH_PREFIX}{stamp}{SCRATCH_SUFFIX}"


def model_column_names(model_doc: dict) -> set[str]:
    m = model_doc.get("model", {})
    return {c.get("name") for c in m.get("columns") or []} | \
        {f.get("name") for f in m.get("formulas") or []}


def build_scratch_model(model_doc: dict, formula_name: str, expr: str, role: str,
                        name: str) -> dict:
    """A deep copy of ``model_doc`` ready to import as a NEW object."""
    if "model" not in model_doc:
        raise ValidationError("the object is not a Model (no `model:` key in its TML); "
                              "worksheets are not supported for validation")
    if formula_name in model_column_names(model_doc):
        raise ValidationError(f"the Model already has a column named {formula_name!r}; "
                              "pass --name with a different display name")
    doc = copy.deepcopy(model_doc)
    doc.pop("guid", None)
    doc.pop("obj_id", None)
    m = doc["model"]
    m.pop("obj_id", None)
    m["name"] = name
    m["description"] = ("Scratch copy made by `ts formula translate --validate`. "
                        "Safe to delete.")
    formula, column = formula_tml_entries(formula_name, expr, role)
    m.setdefault("formulas", []).append(formula)
    m.setdefault("columns", []).append(column)
    return doc


def pick_group_attribute(model_doc: dict, exclude: str) -> Optional[str]:
    """First physical ATTRIBUTE column — the one grouping column a measure is probed by."""
    for c in model_doc.get("model", {}).get("columns") or []:
        props = c.get("properties") or {}
        if c.get("column_id") and props.get("column_type") == "ATTRIBUTE" and c.get("name") != exclude:
            return c["name"]
    return None


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def agentql_statement(model_name: str, formula_name: str, role: str,
                      wrapper: Optional[str], group_by: Optional[str],
                      limit: Optional[int] = None) -> str:
    """One formula per query, plus one grouping attribute for a measure — nothing else."""
    f = f'"t1".{_q(formula_name)}'
    if role == "MEASURE":
        if not group_by:
            raise ValidationError("no ATTRIBUTE column to group by; pass --group-by")
        g = f'"t1".{_q(group_by)}'
        sql = (f'SELECT {g} AS "g", {wrapper or "AGG"}({f}) AS "v" '
               f'FROM {_q(model_name)} AS "t1" GROUP BY {g}')
    else:
        sql = f'SELECT {f} AS "v" FROM {_q(model_name)} AS "t1" GROUP BY {f}'
    return sql + (f" LIMIT {int(limit)}" if limit else "")


def _json(resp) -> Any:
    try:
        return resp.json() if getattr(resp, "text", "x") else {}
    except ValueError:
        return {}


class Validator:
    def __init__(self, client, log=None):
        self.client = client
        self.log = log or (lambda msg: None)

    # -- reads -------------------------------------------------------------------
    def export_model(self, guid: str) -> tuple[dict, list[dict]]:
        resp = self.client.post(_EXPORT, json={
            "metadata": [{"identifier": guid}], "export_associated": True,
            "export_fqn": True, "formattype": "JSON"})
        docs = []
        for item in _json(resp) or []:
            edoc = item.get("edoc") if isinstance(item, dict) else None
            if edoc:
                docs.append(json.loads(edoc))
        models = [d for d in docs if "model" in d]
        if not models:
            raise ValidationError(f"no Model TML exported for {guid} "
                                  "(is it a Model? worksheets are not supported)")
        model = next((d for d in models if d.get("guid") == guid), models[0])
        tables = [d for d in docs if "table" in d]
        return model, tables

    def find_by_name(self, name: str) -> list[str]:
        resp = self.client.post(_SEARCH, json={
            "metadata": [{"type": "LOGICAL_TABLE", "name_pattern": name}],
            "record_size": -1, "record_offset": 0})
        data = _json(resp)
        rows = data if isinstance(data, list) else (data or {}).get("metadata", [])
        return [r["metadata_id"] for r in rows if r.get("metadata_name") == name]

    def exists(self, guid: str) -> bool:
        resp = self.client.post(_SEARCH, json={
            "metadata": [{"type": "LOGICAL_TABLE", "identifier": guid}],
            "record_size": -1, "record_offset": 0})
        data = _json(resp)
        rows = data if isinstance(data, list) else (data or {}).get("metadata", [])
        return any(r.get("metadata_id") == guid for r in rows)

    # -- writes ------------------------------------------------------------------
    def _import(self, doc: dict, policy: str, create_new: bool) -> tuple[Optional[str], Optional[str]]:
        """Returns (guid or None, error or None)."""
        from ts_cli.tml_common import extract_imported_guid, tml_import_failures

        resp = self.client.post(_IMPORT, json={
            "metadata_tmls": [json.dumps(doc)], "import_policy": policy,
            "create_new": create_new}, raise_for_status=False)
        data = _json(resp)
        if not getattr(resp, "ok", True):
            return None, f"HTTP {getattr(resp, 'status_code', '?')}: {str(data)[:500]}"
        failures = tml_import_failures(data)
        if failures:
            f = failures[0]
            return None, f"{f.get('error_message') or f.get('status_code')} " \
                         f"(error_code {f.get('error_code')})"
        guid = extract_imported_guid(data if isinstance(data, list) else [data])
        return guid, None

    def validate_only(self, doc: dict) -> Optional[str]:
        _, err = self._import(doc, "VALIDATE_ONLY", True)
        return err

    def delete(self, guid: str) -> str:
        from ts_cli.commands.metadata import classify_delete_response

        resp = self.client.post(_DELETE, json={
            "metadata": [{"identifier": guid, "type": "LOGICAL_TABLE"}]},
            raise_for_status=False)
        return classify_delete_response(bool(getattr(resp, "ok", False)),
                                        getattr(resp, "status_code", 0),
                                        getattr(resp, "text", "") or "")

    def agentql(self, path_kind: str, statement: str, model_guid: str) -> dict:
        from ts_cli.commands.spotql import _FETCH_PATH, _GENERATE_PATH, normalise_response

        path = _GENERATE_PATH if path_kind == "generate" else _FETCH_PATH
        resp = self.client.post(path, json={"spotql_query": statement,
                                            "model_identifier": model_guid},
                                raise_for_status=False)
        return normalise_response(_json(resp))

    # -- orchestration -------------------------------------------------------------
    def run(self, level: str, model_doc: dict, formula_name: str, expr: str, role: str,
            wrapper: Optional[str], group_by: Optional[str] = None,
            name: Optional[str] = None) -> dict:
        name = name or scratch_name()
        doc = build_scratch_model(model_doc, formula_name, expr, role, name)
        if role == "MEASURE":
            group_by = group_by or pick_group_attribute(model_doc, formula_name)
        out: dict[str, Any] = {"level": level, "result": None, "method": None,
                               "error": None, "sql": None}

        self.log(f"validate: VALIDATE_ONLY import of scratch copy {name}")
        err = self.validate_only(doc)
        out["method"] = "VALIDATE_ONLY import (creates nothing)"
        if err or level == "compile":
            out["result"] = "FAILED" if err else "OK"
            out["error"] = err
            if not err:
                out["note"] = ("compile parses the formula against the Model; compiled SQL "
                               "is produced only by --validate execute")
            return out

        statement = agentql_statement(name, formula_name, role, wrapper, group_by)
        out.update(method="scratch Model + AgentQL", agentql=statement,
                   scratch={"name": name, "guid": None, "deleted": False,
                            "confirmed_absent": False})
        guid: Optional[str] = None
        try:
            guid = self._create_scratch(doc, name, out)
            if guid:
                self._query(statement, guid, out)
        except Exception as exc:  # reported as JSON by the caller, after cleanup ran
            out.update(result="ERROR", error=f"{type(exc).__name__}: {exc}")
        finally:
            self._cleanup(out, name, guid)
        return out

    def _create_scratch(self, doc: dict, name: str, out: dict) -> Optional[str]:
        self.log(f"validate: importing scratch Model {name}")
        guid, err = self._import(doc, "ALL_OR_NONE", True)
        if err:
            out.update(result="FAILED", error=f"scratch import: {err}")
            return None
        if not guid:
            found = self.find_by_name(name)
            guid = found[0] if found else None
        if not guid:
            out.update(result="FAILED", error="scratch import reported OK but no GUID was found")
            return None
        out["scratch"]["guid"] = guid
        return guid

    @staticmethod
    def _errors(resp: dict) -> Optional[str]:
        errs = resp.get("errors") or []
        return "; ".join(f"[{e.get('code')}] {e.get('message')}" for e in errs) or None

    def _query(self, statement: str, guid: str, out: dict) -> None:
        gen = self.agentql("generate", statement, guid)
        out["sql"] = gen.get("executable_sql") or None
        err = self._errors(gen)
        if err:
            out.update(result="FAILED", error=err)
            return
        fetched = self.agentql("fetch", statement + " LIMIT 5", guid)
        err = self._errors(fetched)
        if err:
            out.update(result="FAILED", error=err)
            return
        out.update(result="OK", columns=fetched.get("columns"), rows=fetched.get("rows"))

    def _cleanup(self, out: dict, name: str, guid: Optional[str]) -> None:
        """Delete every object carrying the scratch name, then confirm none is left.

        Records the outcome in ``out["scratch"]`` — ``confirmed_absent`` False plus
        ``remaining`` GUIDs on any failure — and LOGS every remaining GUID itself (stderr),
        so the "exit 1 prints the GUID" contract holds even if the caller never gets to
        print. Never lets a lookup failure pass as "deleted". A Ctrl-C during cleanup is
        recorded and logged, then re-raised.
        """
        scratch = out.setdefault("scratch", {"name": name, "guid": guid})
        guids: list[str] = [guid] if guid else []
        outcomes: dict = {}
        try:
            guids = list(dict.fromkeys(guids + self.find_by_name(name)))
            for g in guids:
                try:
                    outcomes[g] = self.delete(g)
                except Exception as exc:
                    outcomes[g] = f"error: {exc}"
            remaining = [g for g in guids if self.exists(g)] + \
                [g for g in self.find_by_name(name) if g not in guids]
        except KeyboardInterrupt:
            self._record_left(scratch, name, guids, outcomes, "interrupted during cleanup")
            raise
        except Exception as exc:  # cannot look or confirm — never read as "deleted"
            self._record_left(scratch, name, guids, outcomes, f"cleanup failed: {exc}")
            return
        scratch.update(deleted=not remaining, confirmed_absent=not remaining,
                       delete_outcomes=outcomes, guids=guids)
        if remaining:
            self._record_left(scratch, name, remaining, outcomes,
                              "scratch Model(s) still present after delete")

    def _record_left(self, scratch: dict, name: str, guids: list[str], outcomes: dict,
                     why: str) -> None:
        scratch.update(deleted=False, confirmed_absent=False, delete_outcomes=outcomes,
                       remaining=guids, cleanup_error=why)
        if guids:
            for g in guids:
                self.log(f"CLEANUP FAILED ({why}) — scratch Model still present: {g}. "
                         f"Delete it with: ts metadata delete {g}")
        else:
            self.log(f"CLEANUP NOT CONFIRMED ({why}) — search for {name!r} and delete it: "
                     f'ts metadata search --subtype WORKSHEET --name "{name}"')
