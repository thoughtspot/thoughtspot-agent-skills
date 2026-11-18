"""A Model whose Table TML could not be exported is not "Can use".

P19 falls back to a Table column's calendar, P21 reads a Table column's aggregation
flags, P25 a Table's database, schema and table names, and P28 a Table's RLS rules. A
Table whose export failed holds none of them, and each rule read that as nothing to
report, so the Model read "Can use". Each now counts as not assessed for that Model,
and its readiness is unknown unless something firm blocks it.

End to end through `build_context`, with the Table's export item failing inside an
HTTP 200 (`edoc: null`, status ERROR), as `metadata/tml/export` answers a Table the
user may not download.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import yaml

from ts_cli.audit import run_audit
from ts_cli.audit.context import build_context

MODEL = {"guid": "m1", "model": {
    "name": "Sales", "formulas": [],
    "model_tables": [{"name": "ORDERS", "fqn": "t1"}, {"name": "ITEMS", "fqn": "t2"}],
    "columns": [{"name": "Amount", "column_id": "ITEMS::AMOUNT",
                 "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
                {"name": "Day", "column_id": "ITEMS::DAY",
                 "properties": {"column_type": "ATTRIBUTE"}}]}}
LATE_RULES = ("P19", "P21", "P25", "P28")


def _table(guid, name):
    return {"guid": guid, "table": {"name": name, "db": "DB", "schema": "S",
                                    "db_table": name, "connection": {"name": "Warehouse A"},
                                    "columns": [{"name": "AMOUNT", "properties": {}},
                                                {"name": "DAY", "properties": {}}]}}


FAILED = {"edoc": None, "info": {"id": "t2", "name": "ITEMS",
                                 "status": {"status_code": "ERROR",
                                            "error_message": "No permission to download"}}}


def _response(body):
    r = MagicMock()
    r.status_code, r.ok = 200, True
    r.json.return_value = body
    return r


class Client:
    """Exports Model m1 with Table t1, and t2 too unless `t2_fails`; every source's
    header says Snowflake on Warehouse A, whose settings and calendars are searched.
    Warehouse A's connection header says `parameterizedConnection: parameterized`."""

    def __init__(self, t2_fails: bool, parameterized: bool = False):
        self.t2_fails, self.parameterized = t2_fails, parameterized

    def post(self, url, json=None, **_kw):
        if url.endswith("/metadata/search") \
                and [m.get("type") for m in json["metadata"]] == ["CONNECTION"]:
            return _response([] if json.get("record_offset") else [{"metadata_header": {
                "id": "conn-a", "parameterizedConnection": self.parameterized,
                "isParameterized": False}}])
        if url.endswith("/metadata/tml/export"):
            t2 = FAILED if self.t2_fails else {"edoc": yaml.safe_dump(_table("t2", "ITEMS"))}
            return _response([{"edoc": yaml.safe_dump(MODEL)},
                              {"edoc": yaml.safe_dump(_table("t1", "ORDERS"))}, t2])
        if url.endswith("/metadata/search") and (json or {}).get("include_headers"):
            return _response([{"metadata_header": {
                "id": m["identifier"], "type": "ONE_TO_ONE_LOGICAL",
                "dataSourceType": "RDBMS_SNOWFLAKE", "dataSourceName": "Warehouse A"}}
                for m in json["metadata"] if m["identifier"] != "m1"])
        if url.endswith("/connection/search"):
            return _response([] if json.get("record_offset") else [{
                "id": "conn-a", "name": "Warehouse A", "data_warehouse_type": "SNOWFLAKE",
                "details": {"configuration": _config()}}])
        return _response([])


def _config():
    return json.dumps({"accountName": "acme", "user": "svc", "password": "******"})


def _readiness(t2_fails, parameterized=False):
    ctx = build_context(Client(t2_fails, parameterized), ["m1"], {"calendars", "connections"})
    [model] = run_audit(None, ["m1"], ["P"], ctx=ctx)["corpus"]["models"]
    return ctx, model["data_cache"]


def test_a_table_that_failed_to_export_leaves_the_model_not_assessed():
    ctx, dc = _readiness(t2_fails=True)
    assert "t2" not in ctx.tables and any("No permission" in w for w in ctx.warnings)
    assert dc["readiness"] == "unknown"
    assert dc["reasons"] == []
    assert dc["not_assessed"] == list(LATE_RULES)


def test_control_the_same_model_with_every_table_exported_can_use_data_cache():
    ctx, dc = _readiness(t2_fails=False)
    assert "t2" in ctx.tables
    assert (dc["readiness"], dc["reasons"], dc["not_assessed"]) == ("ready", [], [])


def test_a_model_on_a_parameterized_connection_cannot_use_data_cache():
    """The connection search shows no `${var}` token for a parameterized connection
    (open-items #17); its metadata header says so, and P24 reads that."""
    ctx, dc = _readiness(t2_fails=False, parameterized=True)
    assert dc["readiness"] == "blocked"
    assert [(r["rule"], r["items"]) for r in dc["reasons"]] == [
        ("P24", ["Warehouse A: template variable"])]
