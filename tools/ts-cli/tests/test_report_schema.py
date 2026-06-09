# tools/ts-cli/tests/test_report_schema.py
"""Tests for report.schema dataclasses — the JSON contract types."""
from __future__ import annotations

from ts_cli.report.schema import (
    SourceDescriptor,
    Owner,
    RiskTag,
    DependentEntry,
    CoverageEntry,
    Classification,
    Report,
    SCHEMA_VERSION,
)


def test_schema_version_string():
    assert SCHEMA_VERSION == "1.0"


def test_source_descriptor_to_dict():
    src = SourceDescriptor(
        input="DB.SCHEMA.TABLE",
        guid="abc-123",
        type="LOGICAL_TABLE",
        name="TABLE",
        parent=None,
    )
    assert src.to_dict() == {
        "input": "DB.SCHEMA.TABLE",
        "guid": "abc-123",
        "type": "LOGICAL_TABLE",
        "name": "TABLE",
        "parent": None,
    }


def test_dependent_entry_to_dict():
    dep = DependentEntry(
        guid="d-1",
        name="My Model",
        type="LOGICAL_TABLE",
        subtype="WORKSHEET",
        via="v2_dependents",
        hops=1,
        owner=Owner(id="u-1", display_name="Admin"),
        modified_at="2026-03-01T00:00:00Z",
        risk=RiskTag(tag="LOW", reason="Dormant Model"),
    )
    d = dep.to_dict()
    assert d["guid"] == "d-1"
    assert d["risk"]["tag"] == "LOW"
    assert d["owner"]["display_name"] == "Admin"


def test_report_to_dict_includes_schema_version():
    src = SourceDescriptor(input="x", guid="g", type="LOGICAL_TABLE", name="x", parent=None)
    rep = Report(
        source=src,
        walked_at="2026-05-28T00:00:00Z",
        profile="test",
        dependents=[],
        coverage=[CoverageEntry(type="Models", checked=True, found=0)],
        classification=Classification(per_dependent=[], aggregate=RiskTag(tag="SAFE", reason="No dependents")),
        warnings=[],
    )
    d = rep.to_dict()
    assert d["schema_version"] == "1.0"
    assert d["source"]["guid"] == "g"
    assert d["coverage"][0]["found"] == 0
