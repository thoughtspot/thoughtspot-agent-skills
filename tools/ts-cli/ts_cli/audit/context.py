from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

from ts_cli.commands.tml import parse_edoc, detect_tml_type


@dataclass
class AuditContext:
    models: list = field(default_factory=list)
    tables: dict = field(default_factory=dict)
    dependents: dict = field(default_factory=dict)
    metadata: list = field(default_factory=list)
    ai_instructions: dict = field(default_factory=dict)
    answers: list = field(default_factory=list)
    model_guids: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def guid_for(self, tml: dict) -> str:
        return tml.get("guid", "")

    def column_types(self, model: dict) -> dict:
        """``TABLE::COL`` -> warehouse data type, for every column of every table
        this model is built on.

        Model columns carry no data type. The schema's own currency anchor records
        it — "no data_type on formulas[]/columns[]" — so reading
        ``columns[].db_column_properties.data_type`` off the MODEL yields "" for
        every column, which is how the VARCHAR join-key checks shipped inert
        (audit 14.1). The type lives on the Table TML the ``column_id`` resolves
        to, keyed by the model_tables entry's ``alias`` (or ``name``).

        A table with no TML in ``self.tables`` contributes nothing: its columns'
        types are unknown, which a caller must not read as "not a string".
        """
        out: dict = {}
        for mt in (model.get("model", {}).get("model_tables") or []):
            table = self.tables.get(mt.get("fqn", ""))
            if not table:
                continue
            prefix = mt.get("alias") or mt.get("name") or ""
            for col in (table.get("table", {}).get("columns") or []):
                name = col.get("name", "")
                if not name:
                    continue
                dt = (col.get("db_column_properties") or {}).get("data_type", "")
                out[f"{prefix}::{name}"] = dt
        return out

    def tables_for_model(self, model: dict) -> list:
        result = []
        for mt in (model.get("model", {}).get("model_tables") or []):
            fqn = mt.get("fqn", "")
            if fqn and fqn in self.tables:
                result.append(self.tables[fqn])
        return result


#: TML writes join operands bracketed: `[ORDERS::CUST_ID] = [CUST::ID]`.
_BRACKETED = re.compile(r"\[([^\]]+)\]")


def nl_instructions(ai_data: dict) -> list:
    """Instruction strings from an ``ai/instructions/get`` response.

    The response is ``{"nl_instructions_info": [{"instructions": [...],
    "scope": "GLOBAL"}]}`` — there is no top-level ``instructions`` key.
    ``checks_ai`` read one anyway, so the API half of A3/A5 never fired and a
    Model coached through the UI reported HIGH "no coaching configured"
    (BL-292). Its unit fixtures passed a shape the API never returns, which is
    what kept it invisible.
    """
    out: list = []
    for info in (ai_data or {}).get("nl_instructions_info") or []:
        out.extend(info.get("instructions") or [])
    return out


def join_key_ids(on_str: str) -> list:
    """Column ids referenced by a join ``on`` clause.

    Splitting on ``=``/``,`` without stripping the brackets left
    ``"[ORDERS::CUST_ID]"``, which matches no ``column_id`` anywhere — the first
    of the two defects that made the VARCHAR join-key checks inert (audit 14.1).
    An unbracketed clause is tolerated so a hand-built fixture still parses.
    """
    text = on_str or ""
    bracketed = [m.strip() for m in _BRACKETED.findall(text) if m.strip()]
    if bracketed:
        return bracketed
    parts = text.replace("=", ",").replace(" and ", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def make_context(
    models=None,
    tables=None,
    dependents=None,
    metadata=None,
    ai_instructions=None,
    answers=None,
    model_guids=None,
    warnings=None,
) -> AuditContext:
    return AuditContext(
        models=models or [],
        tables=tables or {},
        dependents=dependents or {},
        metadata=metadata or [],
        ai_instructions=ai_instructions or {},
        answers=answers or [],
        model_guids=model_guids or [],
        warnings=warnings or [],
    )


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _table_key(parsed: dict) -> str:
    """The key a Table TML is stored under in ``AuditContext.tables``.

    Its GUID, because that is what ``model_tables[].fqn`` holds. This map used
    to be keyed by the warehouse path ``db.schema.db_table``, so every
    ``tables.get(mt["fqn"])`` compared a guid against a path and missed —
    ``column_types`` returned ``{}`` on every real run, and P6/D2 could not
    report a VARCHAR join key whatever their logic did. Falls back to the
    warehouse path for a doc that carries no guid.
    """
    t = parsed.get("table", {})
    warehouse_path = "{}.{}.{}".format(
        t.get("db") or "", t.get("schema") or "", t.get("db_table") or "")
    return parsed.get("guid") or warehouse_path


def build_context(
    client: Any,
    model_guids: list,
    angles: list,
) -> AuditContext:
    models = []
    tables = {}
    dependents = {}
    ai_instructions = {}
    answers = []

    _log(f"Exporting TML for {len(model_guids)} model(s)...")
    warnings = []
    model_batch = 50
    for i in range(0, max(len(model_guids), 1), model_batch):
        batch = model_guids[i:i + model_batch]
        if not batch:
            break
        resp = client.post("/api/rest/2.0/metadata/tml/export", json={
            "metadata": [{"identifier": g} for g in batch],
            "export_fqn": True,
            "export_associated": True,
            "formattype": "YAML",
        }, timeout=300, raise_for_status=False)
        if not resp.ok:
            msg = f"Model export batch {i // model_batch + 1} returned {resp.status_code}, skipping {len(batch)} model(s)"
            _log(f"Warning: {msg}")
            warnings.append(msg)
            continue
        for item in resp.json():
            edoc = item.get("edoc", "")
            parsed = parse_edoc(edoc, "YAML")
            if not parsed:
                continue
            tml_type = detect_tml_type(parsed)
            if tml_type == "model":
                models.append(parsed)
            elif tml_type == "table":
                # Key by GUID, because that is what `model_tables[].fqn` holds.
                # This map was keyed by the warehouse path "db.schema.db_table",
                # so every `tables.get(mt["fqn"])` lookup compared a guid against
                # a path and missed — `column_types` returned {} on every real
                # run, and with it P6/D2 could never report a VARCHAR join key.
                # `erd.py` carries a name-matching fallback written to work
                # around exactly this rather than fix it. Falls back to the
                # warehouse path when a doc carries no guid.
                tables[_table_key(parsed)] = parsed

    model_guids_from_tml = [m.get("guid") for m in models if m.get("guid")]
    table_guids_from_tml = [t.get("guid") for t in tables.values() if t.get("guid")]
    scoped_guids = list(set(model_guids + model_guids_from_tml + table_guids_from_tml))
    _log(f"Searching metadata for {len(scoped_guids)} scoped object(s)...")
    metadata_results = []
    batch_size = 50
    for i in range(0, len(scoped_guids), batch_size):
        batch = scoped_guids[i:i + batch_size]
        resp = client.post("/api/rest/2.0/metadata/search", json={
            "metadata": [{"identifier": g, "type": "LOGICAL_TABLE"} for g in batch],
            "include_headers": True,
            "include_hidden_objects": True,
            "record_size": -1,
            "record_offset": 0,
        }, timeout=300)
        data = resp.json()
        page = data if isinstance(data, list) else data.get("metadata", [])
        metadata_results.extend(page)

    _log("Fetching dependents...")
    from ts_cli.commands.metadata import (
        _build_dependents_payload, _normalize_dependents_response,
    )
    all_guids = list(set(model_guids + model_guids_from_tml + table_guids_from_tml))

    if all_guids:
        dep_batch = 15
        for i in range(0, len(all_guids), dep_batch):
            batch = all_guids[i:i + dep_batch]
            resp = client.post(
                "/api/rest/2.0/metadata/search",
                json=_build_dependents_payload(batch, "LOGICAL_TABLE"),
                timeout=300,
            )
            dep_rows = _normalize_dependents_response(resp.json())
            for row in dep_rows:
                src = row["source_guid"]
                dependents.setdefault(src, []).append(row)

    if "A" in angles:
        _log("Fetching AI instructions...")
        for guid in model_guids:
            try:
                resp = client.post("/api/rest/2.0/ai/instructions/get", json={
                    "data_source_identifier": guid,
                })
                ai_instructions[guid] = resp.json()
            except Exception:
                msg = f"AI instructions fetch failed for model {guid}"
                _log(f"Warning: {msg}")
                warnings.append(msg)

    if "H" in angles:
        answer_guids = set()
        for deps in dependents.values():
            for d in deps:
                if d.get("type") == "ANSWER" and d.get("guid"):
                    answer_guids.add(d["guid"])
        if answer_guids:
            _log(f"Exporting {len(answer_guids)} answer TML(s)...")
            guid_list = list(answer_guids)
            ans_batch = 50
            for i in range(0, len(guid_list), ans_batch):
                batch = guid_list[i:i + ans_batch]
                resp = client.post("/api/rest/2.0/metadata/tml/export", json={
                    "metadata": [{"identifier": g} for g in batch],
                    "export_fqn": True,
                    "formattype": "YAML",
                }, timeout=300, raise_for_status=False)
                if not resp.ok:
                    _log(f"Warning: answer export batch {i//ans_batch+1} returned {resp.status_code}, skipping {len(batch)} answer(s)")
                    continue
                for item in resp.json():
                    edoc = item.get("edoc", "")
                    parsed = parse_edoc(edoc, "YAML")
                    if parsed and detect_tml_type(parsed) == "answer":
                        answers.append(parsed)

    _log(f"Context ready: {len(models)} model(s), {len(tables)} table(s), "
         f"{len(answers)} answer(s)")

    return AuditContext(
        models=models,
        tables=tables,
        dependents=dependents,
        metadata=metadata_results,
        ai_instructions=ai_instructions,
        answers=answers,
        model_guids=model_guids,
        warnings=warnings,
    )
