"""Every string a live run sends (SQL, TML, AgentQL) and the bisection, tested offline."""
from __future__ import annotations

import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tools" / "ts-cli"))

from fidelity import builders as B  # noqa: E402
from fidelity.cases import load_fixture  # noqa: E402
from fidelity.live import bisect_failures  # noqa: E402

FX = load_fixture(HERE / "cases" / "snowflake" / "fixture-m0.json")
NAMES = B.object_names("M0", "20261006T000000")


def test_object_names_are_run_stamped_scratch_names():
    assert NAMES == {"warehouse_table": "ZZ_FIDELITY_M0_20261006T000000",
                     "ts_table": "ZZ_FIDELITY_M0_20261006T000000_TABLE_DELETE_ME",
                     "ts_model": "ZZ_FIDELITY_M0_20261006T000000_DELETE_ME"}
    for n in ("ts_table", "ts_model"):
        assert NAMES[n].startswith(B.PREFIX) and NAMES[n].endswith(B.SUFFIX)
    assert B.formula_name("sf-date-010") == "f_sf_date_010"


@pytest.mark.parametrize("v,t,out", [
    (None, "FLOAT", "NULL"), ("O'Brien", "VARCHAR(8)", "'O''Brien'"),
    ("2026-02-28", "DATE", "'2026-02-28'::DATE"), (-0.5, "FLOAT", "-0.5"),
    (1000000, "NUMBER(38,0)", "1000000"), (True, "BOOLEAN", "TRUE"),
])
def test_sql_literal(v, t, out):
    assert B.sql_literal(v, t) == out


@pytest.mark.parametrize("v,t", [("2026-2-1", "DATE"), ("1; DROP", "FLOAT"), (True, "FLOAT")])
def test_sql_literal_refuses_bad_values(v, t):
    with pytest.raises(ValueError):
        B.sql_literal(v, t)


def test_create_and_insert_sql():
    ddl = B.create_table_sql(FX, "DB.S.T")
    assert ddl.startswith("CREATE TABLE DB.S.T (") and "OR REPLACE" not in ddl
    ins = B.insert_rows_sql(FX, "DB.S.T")
    assert ins.count("\n  (") == len(FX["rows"]) and "'bAnAnA '" in ins
    assert B.session_sql(FX)[0] == "ALTER SESSION SET WEEK_START = 0"
    assert "ALTER SESSION SET TIMEZONE = 'UTC'" in B.session_sql(FX)


def test_oracle_sql_row_and_aggregate():
    row = {"source_formula": "N1 / N2", "role": "row"}
    assert B.oracle_sql(row, FX, "T") == "SELECT ROW_ID AS K, (N1 / N2) AS V FROM T ORDER BY ROW_ID"
    assert B.oracle_sql(row, FX, "T", only_key=2).endswith("WHERE ROW_ID = 2 ORDER BY ROW_ID")
    agg = {"source_formula": "SUM(N1)", "role": "aggregate", "group_by": "GRP"}
    assert B.oracle_sql(agg, FX, "T", only_key="A") == \
        "SELECT GRP AS K, (SUM(N1)) AS V FROM T WHERE GRP = 'A' GROUP BY GRP ORDER BY GRP"
    assert B.key_values(agg, FX) == ["A", "B", "C"]
    assert B.key_values(row, FX) == list(range(1, 11))


def test_table_and_model_tml_follow_the_invariants():
    t = B.table_tml(FX, NAMES, "APJ_TAB", "AGENT_SKILLS", "PUBLIC")["table"]
    assert t["connection"] == {"name": "APJ_TAB"}          # name only, never fqn
    assert all(c["db_column_name"] == c["name"] for c in t["columns"])
    assert t["db_table"] == NAMES["warehouse_table"]
    doc = B.model_tml(FX, NAMES, [("f_a", "sum ( [T::N1] )", "MEASURE"),
                                  ("f_b", "[T::N1] + 1", "ATTRIBUTE")])
    assert "guid" not in doc
    m = doc["model"]
    assert m["model_tables"] == [{"name": NAMES["ts_table"]}]
    fcols = {c["name"]: c for c in m["columns"] if "formula_id" in c}
    assert {f["id"] for f in m["formulas"]} == {c["formula_id"] for c in fcols.values()}
    assert all("aggregation" not in f for f in m["formulas"])
    assert fcols["f_a"]["properties"]["column_type"] == "MEASURE"


def test_agentql_one_formula_one_key():
    row = B.agentql_statement("M", "f_x", "ROW_ID", "row", None)
    assert row == ('SELECT "t1"."ROW_ID" AS "k", "t1"."f_x" AS "v" FROM "M" AS "t1" '
                   'GROUP BY "t1"."ROW_ID", "t1"."f_x" LIMIT 1000')
    agg = B.agentql_statement("M", "f_y", "GRP", "aggregate", None, only_key="A")
    assert agg == ('SELECT "t1"."GRP" AS "k", AGG("t1"."f_y") AS "v" FROM "M" AS "t1" '
                   "WHERE \"t1\".\"GRP\" = 'A' GROUP BY \"t1\".\"GRP\" LIMIT 1000")
    assert 'SUM("t1"."f_y")' in B.agentql_statement("M", "f_y", "GRP", "aggregate", "SUM")
    assert 'WHERE "t1"."ROW_ID" = 3 ' in B.agentql_statement("M", "f", "ROW_ID", "row", None, only_key=3)


def test_bisect_isolates_each_bad_formula():
    bad = {"c", "f"}
    calls = []

    def validate(ids):
        calls.append(list(ids))
        hit = [i for i in ids if i in bad]
        return f"rejected {hit[0]}" if hit else None

    out = bisect_failures(list("abcdefgh"), validate)
    assert out == {"c": "rejected c", "f": "rejected f"}
    assert bisect_failures(list("ab"), lambda ids: None) == {}


def test_bisect_blames_a_combination_loudly():
    out = bisect_failures(["a", "b"], lambda ids: "clash" if len(ids) == 2 else None)
    assert set(out) == {"a", "b"} and all("combination" in v for v in out.values())
