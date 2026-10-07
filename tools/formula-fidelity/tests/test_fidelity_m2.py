"""M2 (Databricks SQL): the case files, the Databricks builders and the Databricks oracle,
all without a network. The oracle runs against a fake DB-API connection."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
from decimal import Decimal

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tools" / "ts-cli"))

import run as runmod  # noqa: E402
from fidelity import builders as B  # noqa: E402
from fidelity import cases as caselib  # noqa: E402
from fidelity import live, report  # noqa: E402

DBX = HERE / "cases" / "databricks"


# -- case files ------------------------------------------------------------------------

def test_m2_cases_load_and_are_databricks():
    cases = caselib.load_cases(DBX / "m2.jsonl")
    fx = caselib.fixtures_for(cases, DBX)
    assert len(cases) >= 60
    assert {c["dialect"] for c in cases} == {"databricks"}
    assert list(fx) == ["fixture-m2.json"]
    assert B.warehouse_of(fx["fixture-m2.json"]) == "databricks"
    for c in cases:
        assert c["provenance"]["licence"] == "LicenseRef-ThoughtSpot-EULA (repo LICENSE)"


def test_nonansi_fixture_differs_from_m2_only_in_session():
    a = json.loads((DBX / "fixture-m2.json").read_text())
    b = json.loads((DBX / "fixture-m2-nonansi.json").read_text())
    assert a["rows"] == b["rows"] and a["columns"] == b["columns"]
    assert a["session"]["ANSI_MODE"] is True and b["session"]["ANSI_MODE"] is False
    assert a["session"]["TIMEZONE"] == b["session"]["TIMEZONE"] == "UTC"
    caselib.load_cases(DBX / "m2-nonansi.jsonl")


def test_m2_fixture_keeps_the_m0_edge_rows():
    m0 = json.loads((HERE / "cases" / "snowflake" / "fixture-m0.json").read_text())
    m2 = json.loads((DBX / "fixture-m2.json").read_text())
    assert m2["rows"] == m0["rows"]
    assert [c["name"] for c in m2["columns"]] == [c["name"] for c in m0["columns"]]


def test_databricks_fixture_rejects_sf_type_and_missing_types():
    base = {"name": "X", "key": "K", "warehouse": "databricks", "rows": [{"K": 1}],
            "columns": [{"name": "K", "wh_type": "BIGINT", "ts_type": "INT64",
                         "column_type": "ATTRIBUTE"}]}
    caselib.check_fixture(json.loads(json.dumps(base)))
    bad = json.loads(json.dumps(base))
    bad["columns"][0]["sf_type"] = "NUMBER"
    with pytest.raises(caselib.CaseError, match="wh_type"):
        caselib.check_fixture(bad)
    bad = json.loads(json.dumps(base))
    del bad["columns"][0]["wh_type"]
    with pytest.raises(caselib.CaseError, match="needs name/wh_type"):
        caselib.check_fixture(bad)
    bad = json.loads(json.dumps(base))
    bad["warehouse"] = "bigquery"
    with pytest.raises(caselib.CaseError, match="warehouse"):
        caselib.check_fixture(bad)


# -- builders --------------------------------------------------------------------------

FX = {"name": "M2", "key": "ROW_ID", "warehouse": "databricks",
      "session": {"TIMEZONE": "UTC", "ANSI_MODE": True},
      "columns": [{"name": "ROW_ID", "wh_type": "BIGINT", "ts_type": "INT64",
                   "column_type": "ATTRIBUTE"},
                  {"name": "S1", "wh_type": "STRING", "ts_type": "VARCHAR",
                   "column_type": "ATTRIBUTE"},
                  {"name": "T1", "wh_type": "TIMESTAMP_NTZ", "ts_type": "DATE_TIME",
                   "column_type": "ATTRIBUTE"}],
      "rows": [{"ROW_ID": 1, "S1": "O'Reilly", "T1": "2026-01-31 10:59:00"}]}


def test_databricks_session_statements():
    assert B.session_sql(FX) == ["SET TIME ZONE 'UTC'", "SET ansi_mode = true"]
    off = dict(FX, session={"ANSI_MODE": False})
    assert B.session_sql(off) == ["SET ansi_mode = false"]
    assert B.session_readback_sql(FX) == [("TIMEZONE", "SET timezone"),
                                         ("ANSI_MODE", "SET ansi_mode")]


@pytest.mark.parametrize("session", [{"WEEK_START": 0}, {"TIMEZONE": "UTC'; DROP"},
                                     {"ANSI_MODE": 1}])
def test_databricks_session_rejects_unknown_or_unsafe(session):
    with pytest.raises(ValueError):
        B.session_sql(dict(FX, session=session))


def test_snowflake_session_unchanged():
    assert B.session_sql({"session": {"TIMEZONE": "UTC"}}) == ["ALTER SESSION SET TIMEZONE = 'UTC'"]


def test_databricks_literals_and_load_sql():
    assert B.sql_literal("O'R", "STRING", "databricks") == "'O\\'R'"
    assert B.sql_literal("O'R", "VARCHAR(8)") == "'O''R'"
    assert B.create_table_sql(FX, "C.S.T") == (
        "CREATE TABLE C.S.T (\n  `ROW_ID` BIGINT,\n  `S1` STRING,\n  `T1` TIMESTAMP_NTZ\n)")
    ins = B.insert_rows_sql(FX, "C.S.T")
    assert "(1, 'O\\'Reilly', '2026-01-31 10:59:00'::TIMESTAMP_NTZ)" in ins
    case = {"role": "row", "source_formula": "S1", "group_by": None}
    assert B.oracle_sql(case, FX, "C.S.T", only_key=1).endswith("WHERE ROW_ID = 1 ORDER BY ROW_ID")


def test_databricks_table_tml_is_lower_case():
    names = B.object_names("M2", "STAMP")
    t = B.table_tml(FX, names, "DBX_DAMIAN", "AGENT_SKILLS", "AUDIT_PROBE")["table"]
    assert (t["db"], t["schema"], t["db_table"]) == (
        "agent_skills", "audit_probe", "zz_fidelity_m2_stamp")
    assert t["name"] == "ZZ_FIDELITY_M2_STAMP_TABLE_DELETE_ME"
    sf = B.table_tml(dict(FX, warehouse="snowflake"), names, "C", "AGENT_SKILLS", "PUBLIC")
    assert sf["table"]["db"] == "AGENT_SKILLS"


# -- the Databricks oracle, over a fake connection ---------------------------------------

class _Cur:
    def __init__(self, conn):
        self.conn, self.description, self._rows = conn, None, []

    def execute(self, sql):
        self.conn.sent.append(sql)
        out = self.conn.answer(sql)
        if isinstance(out, Exception):
            raise out
        self.description = [("k",), ("v",)] if out is not None else None
        self._rows = out or []

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _Conn:
    def __init__(self, answer):
        self.answer, self.sent, self.closed = answer, [], False

    def cursor(self):
        return _Cur(self)

    def close(self):
        self.closed = True


def _wh(answer):
    wh = object.__new__(live.DatabricksWarehouse)
    wh.conn = _Conn(answer)
    return wh


def test_databricks_values_are_canonical():
    wh = _wh(lambda sql: [(1, Decimal("1230")), (2, 3.5), (3, dt.date(2026, 1, 31)),
                          (4, dt.datetime(2026, 1, 1)), (5, None), (6, "x")])
    assert wh.keyed("SELECT") == {
        "1": {"t": "num", "v": "1230"}, "2": {"t": "num", "v": "3.5"},
        "3": {"t": "date", "v": "2026-01-31"}, "4": {"t": "datetime", "v": "2026-01-01T00:00:00"},
        "5": {"t": "null"}, "6": {"t": "str", "v": "x"}}


def test_databricks_table_exists_and_orphans():
    rows = [("audit_probe", "zz_fidelity_m2_a", False), ("audit_probe", "other", False)]
    wh = _wh(lambda sql: rows)
    assert wh.table_exists("AGENT_SKILLS", "AUDIT_PROBE", "ZZ_FIDELITY_M2_A")
    assert not wh.table_exists("AGENT_SKILLS", "AUDIT_PROBE", "ZZ_FIDELITY_M2_B")
    assert "LIKE 'zz_fidelity_m2_a'" in wh.conn.sent[0]
    assert live.find_warehouse_orphans(wh, "AGENT_SKILLS", "AUDIT_PROBE") == [
        {"name": "zz_fidelity_m2_a", "created_on": None}]
    assert wh.conn.sent[-1] == "SHOW TABLES IN `AGENT_SKILLS`.`AUDIT_PROBE` LIKE 'zz_fidelity_*'"
    with pytest.raises(ValueError):
        wh.table_exists("AGENT_SKILLS", "AUDIT_PROBE", "X' OR '1")


def test_databricks_oracle_falls_back_per_key_with_its_error_text():
    def answer(sql):
        if "WHERE ROW_ID = 2" in sql or "WHERE" not in sql:
            return Exception("[DIVIDE_BY_ZERO] Division by zero. Use `try_divide` to "
                             "tolerate. SQLSTATE: 22012\n== SQL ==")
        return [(int(sql.split("WHERE ROW_ID = ")[1].split()[0]), 1.0)]

    fx = dict(FX, rows=[{"ROW_ID": 1}, {"ROW_ID": 2}])
    case = {"role": "row", "source_formula": "N1 / N2", "group_by": None}
    out = live.run_oracle(_wh(answer), case, fx, "C.S.T")
    assert out["per_key"] and out["error"] == "[DIVIDE_BY_ZERO] Division by zero."
    assert out["values"] == {"1": {"t": "num", "v": "1.0"},
                             "2": {"t": "error", "v": "[DIVIDE_BY_ZERO] Division by zero."}}


@pytest.mark.parametrize("raw,want", [
    ("[DIVIDE_BY_ZERO] Division by zero. Use `try_divide`.", "[DIVIDE_BY_ZERO] Division by zero."),
    ("Error during request: [CAST_INVALID_INPUT] The value 'x' cannot be cast. Correct it",
     "[CAST_INVALID_INPUT] The value 'x' cannot be cast."),
    ("plain failure\nsecond line", "plain failure"),
])
def test_dbx_error(raw, want):
    assert live.dbx_error(raw) == want


# -- run.py wiring and the report ---------------------------------------------------------

def test_live_run_needs_dbx_profile_for_a_databricks_fixture(capsys):
    rc = runmod.main(["--cases", str(DBX / "m2.jsonl"), "--profile", "p", "--sf-profile", "s"])
    assert rc == 2
    assert "--dbx-profile" in capsys.readouterr().err


def test_default_warehouse_factory_dispatches_on_the_fixture(monkeypatch):
    made = []
    monkeypatch.setattr(live, "DatabricksWarehouse",
                        lambda p, cli=None: made.append(("dbx", p, cli)) or "D")
    monkeypatch.setattr(live, "Warehouse", lambda p: made.append(("sf", p)) or "S")
    deps = runmod.Deps(validator=object)
    assert deps.warehouse("databricks", "Production") == "D"
    assert deps.warehouse("databricks", "Production", "named") == "D"
    assert deps.warehouse("snowflake", "SF") == "S"
    assert made == [("dbx", "Production", None), ("dbx", "Production", "named"), ("sf", "SF")]


# -- credentials: env var, then the OS credential store; never ~/.databrickscfg -----------

SP = {"name": "Production", "host": "https://dbc-x.cloud.databricks.com/", "auth_type": "oauth-m2m",
      "client_id": "cid", "secret_env": "DATABRICKS_SP_SECRET_PRODUCTION",
      "dbx_profile": "ts-production"}


def test_credentials_prefer_the_env_var():
    asked = []
    kw = live.dbx_credentials(SP, getenv=lambda k: "s3" if k == SP["secret_env"] else None,
                              get_password=lambda *a: asked.append(a))
    assert kw == {"host": "https://dbc-x.cloud.databricks.com", "auth_type": "oauth-m2m",
                  "client_id": "cid", "client_secret": "s3"}
    assert asked == []


def test_credentials_fall_back_to_the_keychain_under_the_skill_service_and_account():
    asked = []
    kw = live.dbx_credentials(SP, getenv=lambda k: None,
                              get_password=lambda svc, acct: asked.append((svc, acct)) or "kc")
    assert asked == [("databricks-production", "cid")] and kw["client_secret"] == "kc"
    pat = dict(SP, auth_type="pat", secret_env=None, token_env="DATABRICKS_TOKEN_PRODUCTION")
    asked.clear()
    kw = live.dbx_credentials(pat, getenv=lambda k: None,
                              get_password=lambda svc, acct: asked.append((svc, acct)) or "t")
    assert asked == [("databricks-production", "token")] and kw["token"] == "t"


def test_credentials_missing_secret_fails_without_echoing_anything(capsys):
    with pytest.raises(SystemExit) as exc:
        live.dbx_credentials(SP, getenv=lambda k: None, get_password=lambda *a: None)
    assert "no credential" in str(exc.value)
    assert capsys.readouterr() == ("", "")


def test_credentials_reject_cli_only_auth():
    with pytest.raises(SystemExit, match="--dbx-cli-profile"):
        live.dbx_credentials(dict(SP, auth_type="databricks-cli"), getenv=lambda k: None,
                             get_password=lambda *a: None)


def test_report_reads_databricks_sql_and_labels_the_source():
    sql = ("SELECT `ta_1`.`ROW_ID` AS `ca_1`, CASE WHEN `ta_1`.`N2` = 0 THEN 0 ELSE x END "
           "AS `ca_2` FROM t")
    assert report._value_sql(sql) == "CASE WHEN `ta_1`.`N2` = 0 THEN 0 ELSE x END"
    assert report._value_sql('SELECT "ta_1"."K" "ca_1", (a + b) "ca_2" FROM t') == "(a + b)"
    assert report.warehouse_label({"warehouse": "databricks"}) == "Databricks"
    assert report.warehouse_label({}) == "Snowflake"


# -- identifiers ------------------------------------------------------------------------

def test_databricks_names_are_validated_and_backtick_quoted():
    assert B.fq("AGENT_SKILLS", "AUDIT_PROBE", "ZZ_T", "databricks") == \
        "`AGENT_SKILLS`.`AUDIT_PROBE`.`ZZ_T`"
    assert B.fq("AGENT_SKILLS", "PUBLIC", "ZZ_T") == "AGENT_SKILLS.PUBLIC.ZZ_T"
    for bad in ("A`B", "a.b", "X; DROP"):
        with pytest.raises(ValueError):
            B.fq("AGENT_SKILLS", bad, "T", "databricks")


@pytest.mark.parametrize("col", [
    {"name": "N1; DROP TABLE x", "wh_type": "DOUBLE"},
    {"name": "N`1", "wh_type": "DOUBLE"},
    {"name": "N1", "wh_type": "DOUBLE) ; DROP TABLE x --"},
    {"name": "N1", "sf_type": "VARCHAR(8) NOT NULL"},
    {"name": "N1", "wh_type": "decimal(10,2)"},
])
def test_column_names_and_types_are_allowlisted(col):
    with pytest.raises(ValueError):
        B.check_column(col)
    fx = dict(FX, columns=[dict(col, ts_type="X", column_type="ATTRIBUTE")])
    with pytest.raises(ValueError):
        B.create_table_sql(fx, "C.S.T")


@pytest.mark.parametrize("t", ["NUMBER(38,0)", "VARCHAR(64)", "FLOAT", "TIMESTAMP_NTZ",
                               "BIGINT", "DECIMAL(10, 2)", "BOOLEAN", "STRING"])
def test_known_types_pass_the_allowlist(t):
    B.check_column({"name": "C_1", "wh_type": t})


def test_fixture_loader_rejects_a_bad_column_name():
    fx = {"name": "X", "key": "K", "warehouse": "databricks", "rows": [{"K": 1}],
          "columns": [{"name": "K", "wh_type": "BIGINT", "ts_type": "INT64",
                       "column_type": "ATTRIBUTE"},
                      {"name": "bad name", "wh_type": "STRING", "ts_type": "VARCHAR",
                       "column_type": "ATTRIBUTE"}]}
    with pytest.raises(caselib.CaseError, match="column name"):
        caselib.check_fixture(fx)


# -- BL-374: the BL-366 round-trip cases read back as safe_divide --------------------------

@pytest.mark.parametrize("path,case_id,divisor", [
    (HERE / "cases" / "snowflake" / "m0.jsonl", "sf-fix-025", "[T::N2]"),
    (HERE / "cases" / "snowflake" / "m0.jsonl", "sf-fix-026", "[T::N2] * 0"),
    (DBX / "m2.jsonl", "dbx-fix-032", "[T::N2]"),
    (DBX / "m2.jsonl", "dbx-fix-033", "[T::N2] * 0"),
])
def test_bl366_round_trip_cases_read_back_as_safe_divide(path, case_id, divisor):
    cases = caselib.load_cases(path)
    case = next(c for c in cases if c["id"] == case_id)
    fx = caselib.fixtures_for([case], path.parent)[case["fixture"]]
    tr = runmod.translate_case(case, fx, "T")
    assert tr["status"] == "TRANSLATED"
    assert tr["formula"] == f"safe_divide ( [T::N1] , {divisor} )"
