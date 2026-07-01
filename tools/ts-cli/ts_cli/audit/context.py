from __future__ import annotations

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

    def guid_for(self, tml: dict) -> str:
        return tml.get("guid", "")

    def tables_for_model(self, model: dict) -> list:
        result = []
        for mt in (model.get("model", {}).get("model_tables") or []):
            fqn = mt.get("fqn", "")
            if fqn and fqn in self.tables:
                result.append(self.tables[fqn])
        return result


def make_context(
    models=None,
    tables=None,
    dependents=None,
    metadata=None,
    ai_instructions=None,
    answers=None,
    model_guids=None,
) -> AuditContext:
    return AuditContext(
        models=models or [],
        tables=tables or {},
        dependents=dependents or {},
        metadata=metadata or [],
        ai_instructions=ai_instructions or {},
        answers=answers or [],
        model_guids=model_guids or [],
    )


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


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
    resp = client.post("/api/rest/2.0/metadata/tml/export", json={
        "metadata": [{"identifier": g} for g in model_guids],
        "export_fqn": True,
        "export_associated": True,
        "formattype": "YAML",
    })
    for item in resp.json():
        edoc = item.get("edoc", "")
        parsed = parse_edoc(edoc, "YAML")
        tml_type = detect_tml_type(parsed)
        if tml_type == "model":
            models.append(parsed)
        elif tml_type == "table":
            fqn = (parsed.get("table", {}).get("db") or "") + "." + \
                  (parsed.get("table", {}).get("schema") or "") + "." + \
                  (parsed.get("table", {}).get("db_table") or "")
            tables[fqn] = parsed

    _log("Searching metadata inventory...")
    metadata_results = []
    offset = 0
    while True:
        resp = client.post("/api/rest/2.0/metadata/search", json={
            "metadata": [{"type": "LOGICAL_TABLE"}],
            "record_size": 200,
            "record_offset": offset,
            "include_headers": True,
            "include_hidden_objects": True,
        })
        data = resp.json()
        page = data if isinstance(data, list) else data.get("metadata", [])
        if not page:
            break
        metadata_results.extend(page)
        if len(page) < 200:
            break
        offset += 200

    _log("Fetching dependents...")
    all_guids = model_guids.copy()
    for t in tables.values():
        if t.get("guid"):
            all_guids.append(t["guid"])
    seen = set()
    unique_guids = []
    for g in all_guids:
        if g not in seen:
            seen.add(g)
            unique_guids.append(g)

    if unique_guids:
        resp = client.post("/api/rest/2.0/metadata/search", json={
            "metadata": [{"identifier": g, "type": "LOGICAL_TABLE"} for g in unique_guids],
            "include_dependent_objects": True,
            "dependent_object_version": "V2",
        })
        from ts_cli.commands.metadata import _normalize_dependents_response
        dep_rows = _normalize_dependents_response(resp.json())
        for row in dep_rows:
            src = row["source_guid"]
            dependents.setdefault(src, []).append(row)

    if "A" in angles:
        _log("Fetching AI instructions...")
        for guid in model_guids:
            try:
                resp = client.post("/api/rest/2.0/ai/instructions/get", json={
                    "metadata_identifier": guid,
                })
                ai_instructions[guid] = resp.json()
            except Exception:
                ai_instructions[guid] = {}

    if "H" in angles:
        answer_guids = set()
        for deps in dependents.values():
            for d in deps:
                if d.get("type") == "ANSWER" and d.get("guid"):
                    answer_guids.add(d["guid"])
        if answer_guids:
            _log(f"Exporting {len(answer_guids)} answer TML(s)...")
            guid_list = list(answer_guids)
            resp = client.post("/api/rest/2.0/metadata/tml/export", json={
                "metadata": [{"identifier": g} for g in guid_list],
                "export_fqn": True,
                "formattype": "YAML",
            })
            for item in resp.json():
                edoc = item.get("edoc", "")
                parsed = parse_edoc(edoc, "YAML")
                if detect_tml_type(parsed) == "answer":
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
    )
