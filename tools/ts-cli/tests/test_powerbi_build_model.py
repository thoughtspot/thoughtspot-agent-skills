"""Unit tests for ts_cli.powerbi.build_model — model assembly.

Pure functions, no live cluster. A tiny synthetic inventory exercises: join cardinality
read from the file, [formula_<name>] id-references, NEEDS-REVIEW measures not emitted,
the dangling-reference cascade, the connection-name-only invariant, and Spotter enablement.
"""
from ts_cli.powerbi.build_model import assemble


def _inv():
    return {
        "source_folder": "/tmp/Sales.pbip",
        "tables": [
            {"name": "Fact",
             "columns": [
                 {"name": "Amount", "dataType": "double", "summarizeBy": "sum"},
                 {"name": "DimId", "dataType": "int64"},
             ],
             "measures": [
                 {"name": "Total", "expression": "SUM(Fact[Amount])"},
                 {"name": "Double Total", "expression": "[Total] * 2"},
                 {"name": "PtInTime", "expression": "CALCULATE([Total], SAMEPERIODLASTYEAR('Dim'[d]))"},
                 {"name": "Iter", "expression": "SUMX(Fact, Fact[Amount])"},
                 {"name": "Derived", "expression": "[Iter] + 1"},
             ]},
            {"name": "Dim",
             "columns": [
                 {"name": "DimId", "dataType": "int64"},
                 {"name": "Name", "dataType": "string"},
             ],
             "measures": []},
        ],
        "relationships": [
            {"name": "Fact->Dim", "fromTable": "Fact", "fromColumn": "DimId",
             "toTable": "Dim", "toColumn": "DimId",
             "fromCardinality": "many", "toCardinality": "one"},
        ],
        "pages": [], "warnings": [],
    }


def _build():
    files, mapping = assemble(_inv(), {}, "MyConn", "db1", "sch1", "LEFT_OUTER", False)
    model = next(tml for fn, tml in files if fn.endswith(".model.tml"))["model"]
    tables = [tml for fn, tml in files if fn.endswith(".table.tml")]
    return files, mapping, model, tables


def test_files_emitted():
    files, _, _, tables = _build()
    assert len(tables) == 2                      # Fact + Dim
    assert any(fn.endswith(".model.tml") for fn, _ in files)


def test_join_cardinality_from_file():
    _, _, model, _ = _build()
    joins = [j for t in model["model_tables"] for j in t.get("joins", [])]
    assert len(joins) == 1
    assert joins[0]["cardinality"] == "MANY_TO_ONE"   # from fromCardinality=many/toCardinality=one
    assert joins[0]["type"] == "LEFT_OUTER"
    assert joins[0]["on"] == "[Fact::DimId] = [Dim::DimId]"


def test_formula_id_references():
    _, _, model, _ = _build()
    fmap = {f["name"]: f["expr"] for f in model["formulas"]}
    assert fmap["Total"] == "sum([Fact::Amount])"
    assert fmap["Double Total"] == "[formula_Total] * 2"   # sibling ref -> id-ref, not inlined


def test_needs_review_not_emitted():
    _, mapping, model, _ = _build()
    emitted = {f["name"] for f in model["formulas"]}
    rows = {m["name"]: m for m in mapping["measures"]}
    assert "PtInTime" not in emitted                      # SAMEPERIODLASTYEAR -> flagged
    assert rows["PtInTime"]["status"] == "NEEDS REVIEW"
    assert rows["PtInTime"]["ts_formula"] == ""


def test_cascade_flags_dependents_of_unmigrated():
    _, mapping, model, _ = _build()
    emitted = {f["name"] for f in model["formulas"]}
    rows = {m["name"]: m for m in mapping["measures"]}
    assert "Iter" not in emitted                          # SUMX -> NEEDS REVIEW
    assert "Derived" not in emitted                       # references [formula_Iter] -> cascaded out
    assert rows["Derived"]["status"] == "NEEDS REVIEW"
    assert "depends on un-migrated" in rows["Derived"]["note"]


def test_connection_name_only_no_fqn():
    _, _, _, tables = _build()
    conn = tables[0]["table"]["connection"]
    assert conn == {"name": "MyConn"}                     # repo invariant: name only, never fqn
    assert "fqn" not in conn


def test_spotter_enabled_by_default():
    _, _, model, _ = _build()
    assert model["properties"]["spotter_config"]["is_spotter_enabled"] is True
