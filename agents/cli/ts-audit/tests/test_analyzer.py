"""Unit tests for the ts-audit analysis engine."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from analyzer import (
    AuditConfig,
    Corpus,
    Finding,
    check_a1,
    check_a2,
    check_a3,
    check_a4,
    check_a5,
    check_d1,
    check_d3,
    check_d4,
    check_d5,
    check_d6,
    check_d9,
    check_d10,
    check_d7,
    check_d8,
    check_h1,
    check_h2,
    check_h3,
    check_h10_columns,
    check_p2,
    check_p3,
    check_p5,
    check_p8,
    check_p9,
    check_p10,
    check_p11,
    check_p13,
    check_p14,
    check_s1,
    check_s8,
    check_s4,
    check_s5,
    check_s6,
    check_s9,
    run_audit,
    summarise,
    _detect_pii,
    _detect_stale,
    _normalise_expr,
    _join_depth,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SPOTTER_CFG = AuditConfig(profile="spotter-ready")
GENERAL_CFG = AuditConfig(profile="general")


def _model(
    name="Test Model",
    guid="guid-1",
    columns=None,
    formulas=None,
    model_tables=None,
    properties=None,
    description="",
    filters=None,
    constraints=None,
    model_instructions=None,
):
    m = {"name": name, "columns": columns or [], "formulas": formulas or []}
    if model_tables is not None:
        m["model_tables"] = model_tables
    else:
        m["model_tables"] = []
    if properties:
        m["properties"] = properties
    if description:
        m["description"] = description
    if filters:
        m["filters"] = filters
    if constraints:
        m["constraints"] = constraints
    if model_instructions:
        m["model_instructions"] = model_instructions
    return {"guid": guid, "model": m}


def _col(name, desc="", synonyms=None, column_id="", column_type="ATTRIBUTE",
         is_hidden=False, index_type="DONT_INDEX", formula_id=None, aggregation=None,
         db_column_name=None):
    props = {"column_type": column_type, "index_type": index_type}
    if is_hidden:
        props["is_hidden"] = True
    if aggregation:
        props["aggregation"] = aggregation
    c = {"name": name, "properties": props}
    if desc:
        c["description"] = desc
    if synonyms:
        c["synonyms"] = synonyms
    if column_id:
        c["column_id"] = column_id
    if formula_id:
        c["formula_id"] = formula_id
    if db_column_name:
        c["db_column_name"] = db_column_name
    return c


def _formula(name, expr, fid=None):
    f = {"name": name, "expr": expr}
    if fid:
        f["id"] = fid
    return f


def _table_tml(name, columns=None, rls_rules=None, guid="tbl-guid-1"):
    tbl = {"name": name, "columns": columns or []}
    if rls_rules:
        tbl["rls_rules"] = rls_rules
    return {"guid": guid, "table": tbl}


def _tbl_col(name, data_type="INT64", db_column_name=None):
    return {
        "name": name,
        "db_column_name": db_column_name or name,
        "db_column_properties": {"data_type": data_type},
    }


def _mt(name, fqn=None, joins=None):
    d = {"name": name}
    if fqn:
        d["fqn"] = fqn
    if joins:
        d["joins"] = joins
    else:
        d["joins"] = []
    return d


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_detect_pii_email(self):
        assert _detect_pii("customer_email")[0] == "Email"

    def test_detect_pii_phone(self):
        assert _detect_pii("phone_number")[0] == "Phone"

    def test_detect_pii_ssn(self):
        assert _detect_pii("ssn")[0] == "National ID"

    def test_detect_pii_none(self):
        assert _detect_pii("revenue") is None

    def test_detect_pii_credential(self):
        cat, sev = _detect_pii("password")
        assert cat == "Credentials"
        assert sev == "CRITICAL"

    def test_detect_stale_zdel(self):
        cat, sev = _detect_stale("zDEL Some Column")
        assert cat == "Deletion candidate"

    def test_detect_stale_do_not_use(self):
        assert _detect_stale("[DO NOT USE] Credit Burn")[0] == "Explicit exclusion"

    def test_detect_stale_excluded(self):
        assert _detect_stale("test_results") is None
        assert _detect_stale("test_automation") is None

    def test_detect_stale_copy(self):
        assert _detect_stale("Copy of Sales Model")[0] == "Copy artifact"

    def test_normalise_expr(self):
        assert _normalise_expr("  SUM ( [Revenue] ) ; ") == "sum ( [revenue] )"

    def test_join_depth_linear(self):
        m = _model(model_tables=[
            _mt("A", joins=[{"with": "B", "on": "A.id = B.id", "type": "INNER"}]),
            _mt("B", joins=[{"with": "C", "on": "B.id = C.id", "type": "INNER"}]),
            _mt("C"),
        ])
        assert _join_depth(m) == 2

    def test_join_depth_star(self):
        m = _model(model_tables=[
            _mt("Fact", joins=[
                {"with": "Dim1", "on": "", "type": "INNER"},
                {"with": "Dim2", "on": "", "type": "INNER"},
                {"with": "Dim3", "on": "", "type": "INNER"},
            ]),
            _mt("Dim1"), _mt("Dim2"), _mt("Dim3"),
        ])
        assert _join_depth(m) == 1


# ---------------------------------------------------------------------------
# A checks
# ---------------------------------------------------------------------------

class TestAChecks:
    def test_a1_below_threshold(self):
        cols = [_col(f"c{i}", desc="Good" if i < 3 else "") for i in range(10)]
        m = _model(columns=cols)
        f = check_a1(m, SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].check_id == "A1"
        assert f[0].score == 0.3

    def test_a1_above_threshold(self):
        cols = [_col(f"c{i}", desc="Good description here") for i in range(10)]
        m = _model(columns=cols)
        assert check_a1(m, SPOTTER_CFG) == []

    def test_a2_no_synonyms(self):
        cols = [_col(f"c{i}") for i in range(10)]
        m = _model(columns=cols)
        f = check_a2(m, SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].score == 0.0

    def test_a3_no_instructions(self):
        m = _model()
        f = check_a3(m, SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].severity == "HIGH"

    def test_a3_has_instructions(self):
        m = _model(model_instructions={"data_model_instructions": "Use ACV for revenue"})
        assert check_a3(m, SPOTTER_CFG) == []

    def test_a4_no_description(self):
        m = _model()
        assert len(check_a4(m, SPOTTER_CFG)) == 1

    def test_a4_has_description(self):
        m = _model(description="Sales pipeline model")
        assert check_a4(m, SPOTTER_CFG) == []

    def test_a5_score(self):
        cols = [_col(f"c{i}", desc="Good desc", synonyms=["syn"]) for i in range(10)]
        m = _model(
            columns=cols,
            description="Good model",
            model_instructions={"data_model_instructions": "coaching"},
        )
        f = check_a5(m, SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].score > 0.9


# ---------------------------------------------------------------------------
# D checks
# ---------------------------------------------------------------------------

class TestDChecks:
    def test_d1_small_model(self):
        m = _model(
            model_tables=[_mt(f"T{i}") for i in range(5)],
            columns=[_col(f"c{i}") for i in range(20)],
        )
        assert check_d1(m, SPOTTER_CFG) == []

    def test_d1_complex_model(self):
        m = _model(
            model_tables=[_mt(f"T{i}") for i in range(20)],
            columns=[_col(f"c{i}") for i in range(80)],
            formulas=[_formula(f"f{i}", "expr") for i in range(60)],
        )
        f = check_d1(m, SPOTTER_CFG)
        checks = {ff.check_name for ff in f}
        assert "COMPLEXITY_TABLES" in checks
        assert "COMPLEXITY_COLUMNS" in checks
        assert "COMPLEXITY_FORMULAS" in checks

    def test_d3_full_outer(self):
        m = _model(model_tables=[
            _mt("A", joins=[{"with": "B", "on": "A.id = B.id", "type": "OUTER"}]),
            _mt("B"),
        ])
        f = check_d3(m, SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].severity == "HIGH"

    def test_d3_inner(self):
        m = _model(model_tables=[
            _mt("A", joins=[{"with": "B", "on": "A.id = B.id", "type": "INNER"}]),
            _mt("B"),
        ])
        assert check_d3(m, SPOTTER_CFG) == []

    def test_d4_not_progressive(self):
        m = _model(
            model_tables=[_mt(f"T{i}") for i in range(10)],
            properties={"join_progressive": False},
        )
        f = check_d4(m, SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].severity == "HIGH"

    def test_d4_progressive(self):
        m = _model(properties={"join_progressive": True})
        assert check_d4(m, SPOTTER_CFG) == []

    def test_d5_orphan_table(self):
        m = _model(model_tables=[
            _mt("Fact", joins=[{"with": "Dim", "on": "", "type": "INNER"}]),
            _mt("Dim"),
            _mt("Orphan"),
        ])
        f = check_d5(m, SPOTTER_CFG)
        assert len(f) == 1
        assert "Orphan" in f[0].title

    def test_d7_identical(self):
        m1 = _model(name="M1", guid="g1", model_tables=[_mt("T1", fqn="f1"), _mt("T2", fqn="f2")])
        m2 = _model(name="M2", guid="g2", model_tables=[_mt("T1", fqn="f1"), _mt("T2", fqn="f2")])
        f = check_d7([m1, m2], SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].severity == "HIGH"
        assert f[0].check_name == "IDENTICAL_MODELS"

    def test_d7_no_overlap(self):
        m1 = _model(name="M1", guid="g1", model_tables=[_mt("T1", fqn="f1")])
        m2 = _model(name="M2", guid="g2", model_tables=[_mt("T2", fqn="f2")])
        assert check_d7([m1, m2], SPOTTER_CFG) == []

    def test_d9_sql_passthrough(self):
        m = _model(formulas=[
            _formula("f1", "sum([revenue])"),
            _formula("f2", "sql_int_aggregate_op(sum(col), 'table', 'col')"),
            _formula("f3", "sql_string_aggregate_op(...)"),
        ])
        f = check_d9(m, SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].score == 2/3

    def test_d10_zero_column_bridge(self):
        m = _model(
            columns=[_col("c1", column_id="Fact::c1")],
            model_tables=[
                _mt("Fact", joins=[{"with": "Bridge", "on": "", "type": "INNER"}]),
                _mt("Bridge", joins=[{"with": "Dim", "on": "", "type": "INNER"}]),
                _mt("Dim"),
            ],
        )
        f = check_d10(m, SPOTTER_CFG)
        bridge_findings = [ff for ff in f if "Bridge" in ff.title]
        assert len(bridge_findings) == 1
        assert bridge_findings[0].severity == "INFO"

    def test_d10_zero_column_leaf(self):
        m = _model(
            columns=[_col("c1", column_id="Fact::c1")],
            model_tables=[
                _mt("Fact", joins=[{"with": "Dim", "on": "", "type": "INNER"}]),
                _mt("Dim"),
                _mt("Leaf"),
            ],
        )
        f = check_d10(m, SPOTTER_CFG)
        leaf_findings = [ff for ff in f if "Leaf" in ff.title]
        assert len(leaf_findings) == 1
        assert leaf_findings[0].severity == "MEDIUM"


# ---------------------------------------------------------------------------
# H checks
# ---------------------------------------------------------------------------

class TestHChecks:
    def test_h1_bad_names(self):
        cols = [_col("col1"), _col("col2"), _col("val"), _col("tmp_calc"),
                _col("Good Name"), _col("Revenue"), _col("CUSTOMER_ID")]
        m = _model(columns=cols)
        f = check_h1(m, SPOTTER_CFG)
        assert len(f) == 1

    def test_h2_short_description(self):
        m = _model(columns=[_col("c1", desc="Hi")])
        f = check_h2(m, SPOTTER_CFG)
        assert len(f) == 1

    def test_h3_hidden_unused(self):
        m = _model(
            columns=[
                _col("visible", column_id="T::visible"),
                _col("hidden_unused", column_id="T::hidden_unused", is_hidden=True),
            ],
            model_tables=[_mt("T")],
        )
        f = check_h3(m, SPOTTER_CFG)
        assert len(f) == 1
        assert "hidden_unused" in f[0].detail

    def test_h3_hidden_formula_ref(self):
        m = _model(
            columns=[
                _col("hidden_calc", column_id="T::hidden_calc", is_hidden=True),
            ],
            formulas=[_formula("total", "sum([hidden_calc])")],
            model_tables=[_mt("T")],
        )
        assert check_h3(m, SPOTTER_CFG) == []

    def test_h10_stale_columns(self):
        m = _model(columns=[
            _col("zDEL Old Column"),
            _col("[DO NOT USE] Bad"),
            _col("Good Column"),
        ])
        f = check_h10_columns(m, SPOTTER_CFG)
        assert len(f) == 1
        assert "2 stale-pattern columns" in f[0].title


# ---------------------------------------------------------------------------
# P checks
# ---------------------------------------------------------------------------

class TestPChecks:
    def test_p8_sprawl(self):
        m = _model(columns=[_col(f"c{i}") for i in range(80)])
        f = check_p8(m, SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].score == 80

    def test_p8_no_sprawl(self):
        m = _model(columns=[_col(f"c{i}") for i in range(50)])
        assert check_p8(m, SPOTTER_CFG) == []

    def test_p10_bypass(self):
        m = _model(properties={"is_bypass_rls": True})
        f = check_p10(m, SPOTTER_CFG)
        assert len(f) == 1

    def test_p10_no_bypass(self):
        m = _model(properties={"is_bypass_rls": False})
        assert check_p10(m, SPOTTER_CFG) == []

    def test_p11_spotter_many_indexed(self):
        cols = [_col(f"c{i}", index_type="PREFIX_AND_SUBSTRING") for i in range(35)]
        m = _model(columns=cols, properties={"spotter_config": {"is_spotter_enabled": True}})
        f = check_p11(m, SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].severity == "INFO"


# ---------------------------------------------------------------------------
# S checks
# ---------------------------------------------------------------------------

class TestSChecks:
    def test_s1_pii(self):
        m = _model(columns=[_col("customer_email"), _col("revenue")])
        f = check_s1(m, SPOTTER_CFG)
        assert len(f) == 1

    def test_s4_bypass_with_pii(self):
        m = _model(
            columns=[_col("customer_email"), _col("revenue")],
            properties={"is_bypass_rls": True},
        )
        f = check_s4(m, SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].severity == "HIGH"

    def test_s5_credential(self):
        m = _model(columns=[_col("password"), _col("api_key")])
        f = check_s5(m, SPOTTER_CFG)
        assert len(f) == 2
        assert all(ff.severity == "CRITICAL" for ff in f)

    def test_s8_rls_varchar_column(self):
        table = _table_tml("Orders", columns=[
            _tbl_col("region", data_type="VARCHAR"),
            _tbl_col("order_id", data_type="INT64"),
        ], rls_rules={
            "rules": [{"expr": "[path1::region] = ts_username"}],
        })
        m = _model(guid="g1")
        corpus = Corpus(models=[m], tables=[table],
                        table_tmls_by_model={"g1": [table]})
        f = check_s8(m, corpus, SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].check_name == "RLS_VARCHAR_FILTER"
        assert "region" in f[0].title

    def test_s8_rls_int_column_no_finding(self):
        table = _table_tml("Orders", columns=[
            _tbl_col("org_id", data_type="INT64"),
        ], rls_rules={
            "rules": [{"expr": "[path1::org_id] = ts_groups"}],
        })
        m = _model(guid="g1")
        corpus = Corpus(models=[m], tables=[table],
                        table_tmls_by_model={"g1": [table]})
        f = check_s8(m, corpus, SPOTTER_CFG)
        assert len(f) == 0

    def test_s8_no_rls_no_finding(self):
        table = _table_tml("Orders", columns=[_tbl_col("region", data_type="VARCHAR")])
        m = _model(guid="g1")
        corpus = Corpus(models=[m], tables=[table],
                        table_tmls_by_model={"g1": [table]})
        f = check_s8(m, corpus, SPOTTER_CFG)
        assert len(f) == 0

    def test_s9_function_in_rls(self):
        table = _table_tml("Orders", columns=[
            _tbl_col("region", data_type="VARCHAR"),
        ], rls_rules={
            "rules": [{"expr": "UPPER([path1::region]) = ts_username"}],
        })
        m = _model(guid="g1")
        corpus = Corpus(models=[m], tables=[table],
                        table_tmls_by_model={"g1": [table]})
        f = check_s9(m, corpus, SPOTTER_CFG)
        assert len(f) == 1
        assert f[0].check_name == "RLS_FUNCTION_IN_EXPR"
        assert "UPPER" in f[0].title
        assert f[0].severity == "HIGH"

    def test_s9_no_function_no_finding(self):
        table = _table_tml("Orders", columns=[
            _tbl_col("region", data_type="VARCHAR"),
        ], rls_rules={
            "rules": [{"expr": "[path1::region] = ts_username"}],
        })
        m = _model(guid="g1")
        corpus = Corpus(models=[m], tables=[table],
                        table_tmls_by_model={"g1": [table]})
        f = check_s9(m, corpus, SPOTTER_CFG)
        assert len(f) == 0

    def test_s9_multiple_functions(self):
        table = _table_tml("Orders", columns=[
            _tbl_col("region", data_type="VARCHAR"),
        ], rls_rules={
            "rules": [
                {"expr": "UPPER([path1::region]) = ts_username"},
                {"expr": "TRIM([path1::region]) = ts_groups"},
            ],
        })
        m = _model(guid="g1")
        corpus = Corpus(models=[m], tables=[table],
                        table_tmls_by_model={"g1": [table]})
        f = check_s9(m, corpus, SPOTTER_CFG)
        assert len(f) == 2

    def test_s6_divergence(self):
        m1 = _model(name="M1", columns=[
            _col("status", column_type="ATTRIBUTE", db_column_name="status"),
        ])
        m2 = _model(name="M2", columns=[
            _col("status", column_type="MEASURE", db_column_name="status"),
        ])
        f = check_s6([m1, m2], SPOTTER_CFG)
        assert len(f) == 1
        assert "status" in f[0].title


# ---------------------------------------------------------------------------
# P13
# ---------------------------------------------------------------------------

class TestP13:
    def test_p13_many_rls_rules(self):
        tbl = _table_tml("Sales", rls_rules={
            "rules": [
                {"expr": "[Sales::region] = ts_username"},
                {"expr": "[Sales::country] = ts_username"},
                {"expr": "[Sales::division] = ts_username"},
                {"expr": "[Sales::team] = ts_username"},
            ],
        })
        m = _model(model_tables=[_mt("Sales", fqn="tbl-guid-1")])
        corpus = Corpus(models=[m], table_tmls_by_model={"guid-1": [tbl]})
        findings = check_p13(m, corpus, SPOTTER_CFG)
        assert len(findings) == 1
        assert findings[0].check_id == "P13"
        assert findings[0].severity == "MEDIUM"
        assert "4" in findings[0].title

    def test_p13_high_severity(self):
        rules = [{"expr": f"[Sales::col{i}] = ts_username"} for i in range(7)]
        tbl = _table_tml("Sales", rls_rules={"rules": rules})
        m = _model(model_tables=[_mt("Sales", fqn="tbl-guid-1")])
        corpus = Corpus(models=[m], table_tmls_by_model={"guid-1": [tbl]})
        findings = check_p13(m, corpus, SPOTTER_CFG)
        assert len(findings) == 1
        assert findings[0].severity == "HIGH"

    def test_p13_few_rules_no_finding(self):
        tbl = _table_tml("Sales", rls_rules={
            "rules": [
                {"expr": "[Sales::region] = ts_username"},
                {"expr": "[Sales::country] = ts_username"},
            ],
        })
        m = _model(model_tables=[_mt("Sales", fqn="tbl-guid-1")])
        corpus = Corpus(models=[m], table_tmls_by_model={"guid-1": [tbl]})
        findings = check_p13(m, corpus, SPOTTER_CFG)
        assert len(findings) == 0

    def test_p13_no_rls_no_finding(self):
        tbl = _table_tml("Sales")
        m = _model(model_tables=[_mt("Sales", fqn="tbl-guid-1")])
        corpus = Corpus(models=[m], table_tmls_by_model={"guid-1": [tbl]})
        findings = check_p13(m, corpus, SPOTTER_CFG)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# P14
# ---------------------------------------------------------------------------

class TestP14:
    def test_p14_if_in_rls(self):
        tbl = _table_tml("Sales", rls_rules={
            "rules": [{"expr": "if(is_group_member('admin'), true, [Sales::region] = ts_username)"}],
        })
        m = _model(model_tables=[_mt("Sales", fqn="tbl-guid-1")])
        corpus = Corpus(models=[m], table_tmls_by_model={"guid-1": [tbl]})
        findings = check_p14(m, corpus, SPOTTER_CFG)
        assert len(findings) == 1
        assert findings[0].check_id == "P14"
        assert findings[0].severity == "MEDIUM"
        assert "IF" in findings[0].title.upper() or "if" in findings[0].title

    def test_p14_contains_in_rls(self):
        tbl = _table_tml("Sales", rls_rules={
            "rules": [{"expr": "contains([Sales::email], ts_username)"}],
        })
        m = _model(model_tables=[_mt("Sales", fqn="tbl-guid-1")])
        corpus = Corpus(models=[m], table_tmls_by_model={"guid-1": [tbl]})
        findings = check_p14(m, corpus, SPOTTER_CFG)
        assert len(findings) == 1

    def test_p14_simple_rls_no_finding(self):
        tbl = _table_tml("Sales", rls_rules={
            "rules": [{"expr": "[Sales::region] = ts_username"}],
        })
        m = _model(model_tables=[_mt("Sales", fqn="tbl-guid-1")])
        corpus = Corpus(models=[m], table_tmls_by_model={"guid-1": [tbl]})
        findings = check_p14(m, corpus, SPOTTER_CFG)
        assert len(findings) == 0

    def test_p14_no_rls_no_finding(self):
        tbl = _table_tml("Sales")
        m = _model(model_tables=[_mt("Sales", fqn="tbl-guid-1")])
        corpus = Corpus(models=[m], table_tmls_by_model={"guid-1": [tbl]})
        findings = check_p14(m, corpus, SPOTTER_CFG)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_run_audit_all_angles(self):
        m = _model(
            columns=[
                _col("Revenue", desc="Total revenue", synonyms=["income"],
                     column_id="Sales::Revenue", column_type="MEASURE"),
                _col("customer_email", column_id="Sales::customer_email"),
            ],
            model_tables=[_mt("Sales", fqn="db.schema.sales")],
            description="Sales model",
            properties={"is_bypass_rls": True},
        )
        corpus = Corpus(models=[m])
        config = AuditConfig(angles=["A", "D", "H", "P", "S"])
        findings = run_audit(corpus, config)
        assert isinstance(findings, list)
        angles_found = {f.angle for f in findings}
        assert "A" in angles_found
        assert "S" in angles_found

    def test_summarise(self):
        findings = [
            Finding("A", "A1", "DESC_COV", "HIGH", "test", "", "", model_name="M1"),
            Finding("D", "D1", "COMPLEX", "HIGH", "test", "", "", model_name="M1"),
            Finding("S", "S1", "PII", "INFO", "test", "", "", model_name="M1"),
        ]
        s = summarise(findings)
        assert s["total"] == 3
        assert s["by_severity"]["HIGH"] == 2
        assert s["model_heatmap"]["M1"]["A"] == "HIGH"

    def test_single_angle(self):
        m = _model(columns=[_col("c1")])
        corpus = Corpus(models=[m])
        config = AuditConfig(angles=["P"])
        findings = run_audit(corpus, config)
        angles = {f.angle for f in findings}
        assert "A" not in angles
        assert "D" not in angles
