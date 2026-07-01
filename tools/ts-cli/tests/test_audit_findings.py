from ts_cli.audit.findings import Finding, build_summary


def test_finding_to_dict_includes_all_fields():
    f = Finding(
        check_id="D1", angle="data_modeling", severity="HIGH",
        object_type="model", object_name="Sales", object_guid="abc-123",
        detail="16 tables exceed threshold", metric=16,
        threshold={"green": 10, "yellow": 15},
    )
    d = f.to_dict()
    assert d["check_id"] == "D1"
    assert d["angle"] == "data_modeling"
    assert d["severity"] == "HIGH"
    assert d["object_type"] == "model"
    assert d["object_name"] == "Sales"
    assert d["object_guid"] == "abc-123"
    assert d["detail"] == "16 tables exceed threshold"
    assert d["metric"] == 16
    assert d["threshold"] == {"green": 10, "yellow": 15}


def test_finding_to_dict_none_metric():
    f = Finding(
        check_id="A3", angle="ai", severity="HIGH",
        object_type="model", object_name="Sales", object_guid="abc-123",
        detail="AI context missing", metric=None, threshold=None,
    )
    d = f.to_dict()
    assert d["metric"] is None
    assert d["threshold"] is None


def test_build_summary_counts_by_severity():
    findings = [
        Finding("D1", "data_modeling", "HIGH", "model", "A", "g1", "x", 1, None),
        Finding("D2", "data_modeling", "MEDIUM", "model", "A", "g1", "x", 1, None),
        Finding("A1", "ai", "HIGH", "model", "A", "g1", "x", 1, None),
    ]
    s = build_summary(findings, checks_run=10, models_count=2, tables_count=5)
    assert s["by_severity"]["HIGH"] == 2
    assert s["by_severity"]["MEDIUM"] == 1
    assert s["by_severity"]["LOW"] == 0
    assert s["by_angle"]["data_modeling"] == 2
    assert s["by_angle"]["ai"] == 1
    assert s["objects_scanned"]["models"] == 2
    assert s["objects_scanned"]["tables"] == 5
    assert s["checks_run"] == 10


def test_build_summary_empty_findings():
    s = build_summary([], checks_run=5, models_count=1, tables_count=3)
    assert all(v == 0 for v in s["by_severity"].values())
    assert all(v == 0 for v in s["by_angle"].values())
    assert s["checks_run"] == 5
