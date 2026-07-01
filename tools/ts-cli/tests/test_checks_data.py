from ts_cli.audit.checks_data import (
    check_d1, check_d2, check_d3, check_d4, check_d5, check_d6,
    check_d7, check_d8, check_d9, check_d10, check_d11, check_d12,
    ALL_CHECKS,
)
from ts_cli.audit.context import make_context


def _model(name="Sales", guid="m-1", model_tables=None, columns=None,
           formulas=None, properties=None):
    return {
        "guid": guid,
        "model": {
            "name": name,
            "model_tables": model_tables or [{"name": "T1", "id": "T1"}],
            "columns": columns or [],
            "formulas": formulas or [],
            "properties": properties or {},
        },
    }


def _join(name="j1", with_table="T2", type="INNER", on="col1 = col2", cardinality=None):
    j = {"name": name, "with": with_table, "type": type, "on": on}
    if cardinality:
        j["cardinality"] = cardinality
    return j


def _col(name="Amount", column_type="MEASURE", table="T1", data_type="INT64",
         aggregation=None, is_hidden=False, index_type=None, db_column_name=None):
    c = {
        "name": name,
        "column_id": f"{table}::{name}",
        "properties": {"column_type": column_type},
    }
    if aggregation:
        c["properties"]["aggregation"] = aggregation
    if is_hidden:
        c["properties"]["is_hidden"] = True
    if index_type:
        c["properties"]["index_type"] = index_type
    if db_column_name:
        c["db_column_name"] = db_column_name
    c["db_column_properties"] = {"data_type": data_type}
    return c


def test_d1_flags_excess_tables():
    tables = [{"name": f"T{i}", "id": f"T{i}"} for i in range(16)]
    ctx = make_context(models=[_model(model_tables=tables)])
    findings = check_d1(ctx)
    assert any(f.check_id == "D1" and f.severity == "HIGH" and "table" in f.detail.lower()
               for f in findings)


def test_d1_passes_small_model():
    tables = [{"name": f"T{i}", "id": f"T{i}"} for i in range(5)]
    cols = [_col(f"C{i}") for i in range(10)]
    ctx = make_context(models=[_model(model_tables=tables, columns=cols)])
    findings = check_d1(ctx)
    assert not any("table" in f.detail.lower() for f in findings)


def test_d4_flags_non_progressive():
    tables = [{"name": f"T{i}", "id": f"T{i}"} for i in range(6)]
    ctx = make_context(models=[_model(model_tables=tables,
                                       properties={"join_progressive": False})])
    findings = check_d4(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


def test_d4_passes_progressive():
    tables = [{"name": f"T{i}", "id": f"T{i}"} for i in range(6)]
    ctx = make_context(models=[_model(model_tables=tables,
                                       properties={"join_progressive": True})])
    assert check_d4(ctx) == []


def test_d4_passes_small_model():
    tables = [{"name": f"T{i}", "id": f"T{i}"} for i in range(3)]
    ctx = make_context(models=[_model(model_tables=tables,
                                       properties={"join_progressive": False})])
    assert check_d4(ctx) == []


def test_d5_flags_unjoined_table():
    tables = [
        {"name": "T1", "id": "T1", "joins": [_join(with_table="T2")]},
        {"name": "T2", "id": "T2"},
        {"name": "T3", "id": "T3"},
    ]
    ctx = make_context(models=[_model(model_tables=tables)])
    findings = check_d5(ctx)
    assert any(f.check_id == "D5" and "T3" in f.detail for f in findings)


def test_d5_passes_all_joined():
    tables = [
        {"name": "T1", "id": "T1", "joins": [_join(with_table="T2")]},
        {"name": "T2", "id": "T2"},
    ]
    ctx = make_context(models=[_model(model_tables=tables)])
    assert check_d5(ctx) == []


def test_d7_flags_identical_table_sets():
    m1 = _model(name="M1", guid="g1",
                model_tables=[{"name": "T1", "fqn": "db.s.T1"}, {"name": "T2", "fqn": "db.s.T2"}])
    m2 = _model(name="M2", guid="g2",
                model_tables=[{"name": "T1", "fqn": "db.s.T1"}, {"name": "T2", "fqn": "db.s.T2"}])
    ctx = make_context(models=[m1, m2])
    findings = check_d7(ctx)
    assert any(f.check_id == "D7" and f.severity == "HIGH" for f in findings)


def test_d7_passes_disjoint_models():
    m1 = _model(name="M1", guid="g1",
                model_tables=[{"name": "T1", "fqn": "db.s.T1"}])
    m2 = _model(name="M2", guid="g2",
                model_tables=[{"name": "T3", "fqn": "db.s.T3"}])
    ctx = make_context(models=[m1, m2])
    assert check_d7(ctx) == []


def test_d9_flags_high_sql_ratio():
    formulas = [
        {"name": f"F{i}", "expr": f"sql_int_aggregate_op(SUM(col{i}))"}
        for i in range(5)
    ] + [
        {"name": f"G{i}", "expr": f"sum([col{i}])"}
        for i in range(5)
    ]
    ctx = make_context(models=[_model(formulas=formulas)])
    findings = check_d9(ctx)
    assert any(f.check_id == "D9" for f in findings)


def test_all_checks_has_twelve_entries():
    assert len(ALL_CHECKS) == 12
