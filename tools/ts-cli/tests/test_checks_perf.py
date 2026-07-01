from ts_cli.audit.checks_perf import (
    check_p1, check_p2, check_p3, check_p4, check_p5, check_p6, check_p7,
    check_p8, check_p9, check_p11, check_p13, check_p14, check_p15,
    check_p16, check_p17, check_p18, ALL_CHECKS,
)
from ts_cli.audit.context import make_context


def _model(name="Sales", guid="m-1", columns=None, formulas=None,
           model_tables=None, properties=None, filters=None, constraints=None):
    return {
        "guid": guid,
        "model": {
            "name": name,
            "model_tables": model_tables or [{"name": "T1"}],
            "columns": columns or [],
            "formulas": formulas or [],
            "properties": properties or {},
            "filters": filters or [],
            "constraints": constraints or [],
        },
    }


def _col(name="Amount", column_type="MEASURE", aggregation=None,
         index_type=None, column_id=None, data_type="INT64"):
    c = {
        "name": name,
        "column_id": column_id or f"T1::{name}",
        "properties": {"column_type": column_type},
        "db_column_properties": {"data_type": data_type},
    }
    if aggregation:
        c["properties"]["aggregation"] = aggregation
    if index_type:
        c["properties"]["index_type"] = index_type
    return c


def _table_tml(name="ORDERS", guid="t-1", rls_rules=None):
    t = {"guid": guid, "table": {"name": name, "columns": []}}
    if rls_rules:
        t["table"]["rls_rules"] = rls_rules
    return t


def test_p1_flags_sql_view():
    ctx = make_context(metadata=[
        {"metadata_header": {"type": "SQL_VIEW", "name": "V1", "id": "v-1"}},
        {"metadata_header": {"type": "ONE_TO_ONE_LOGICAL", "name": "T1", "id": "t-1"}},
    ])
    findings = check_p1(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "P1"


def test_p1_passes_no_views():
    ctx = make_context(metadata=[
        {"metadata_header": {"type": "ONE_TO_ONE_LOGICAL", "name": "T1", "id": "t-1"}},
    ])
    assert check_p1(ctx) == []


def test_p4_flags_non_progressive():
    tables = [{"name": f"T{i}"} for i in range(6)]
    ctx = make_context(models=[_model(model_tables=tables,
                                       properties={"join_progressive": False})])
    findings = check_p4(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


def test_p8_flags_excess_columns():
    cols = [_col(f"C{i}") for i in range(80)]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_p8(ctx)
    assert any(f.check_id == "P8" for f in findings)


def test_p8_passes_under_threshold():
    cols = [_col(f"C{i}") for i in range(50)]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_p8(ctx) == []


def test_p13_flags_high_rls_count():
    rls = {"rules": [{"expr": f"[col{i}]"} for i in range(7)]}
    ctx = make_context(tables={"db.s.T1": _table_tml(rls_rules=rls)})
    findings = check_p13(ctx)
    assert any(f.check_id == "P13" and f.severity == "HIGH" for f in findings)


def test_p16_flags_deep_nesting():
    formulas = [{"name": "F1", "expr": "if(if(if(if(if(if([x]>0,1,0)>0,1,0)>0,1,0)>0,1,0)>0,1,0)>0,1,0)"}]
    ctx = make_context(models=[_model(formulas=formulas)])
    findings = check_p16(ctx)
    assert any(f.check_id == "P16" for f in findings)


def test_p18_flags_count_distinct():
    cols = [_col("Users", aggregation="COUNT_DISTINCT")]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_p18(ctx)
    assert any(f.check_id == "P18" for f in findings)


def test_all_checks_has_sixteen_entries():
    assert len(ALL_CHECKS) == 16
