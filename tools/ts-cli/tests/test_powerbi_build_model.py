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


def test_many_to_many_relationship_is_skipped_and_flagged():
    """A Model join cannot be MANY_TO_MANY (error 14528, lint I20), and emitting one as
    MANY_TO_ONE would fan out silently, so the join is left out and flagged (BL-397)."""
    from ts_cli.tml_lint import lint_tml
    inv = _inv()
    inv["relationships"][0].update({"fromCardinality": "many", "toCardinality": "many"})
    files, mapping = assemble(inv, {}, "MyConn", "db1", "sch1", "LEFT_OUTER", False)
    model_doc = next(tml for fn, tml in files if fn.endswith(".model.tml"))
    assert not [j for t in model_doc["model"]["model_tables"] for j in t.get("joins", [])]
    row = mapping["relationships"][0]
    assert row["status"] == "NEEDS REVIEW" and "bridge table" in row["note"]
    assert not [f for f in lint_tml(model_doc) if f.startswith("I20")]


# --- summarizeBy distinctCount -> unique count formula (invariant I5, BL-447) ---

def _distinct_inv():
    inv = _inv()
    inv["tables"][0]["columns"].append(
        {"name": "CustomerKey", "dataType": "string", "summarizeBy": "distinctCount"})
    # A bridge table whose only column is a distinct-counted key.
    inv["tables"].append({"name": "Bridge", "columns": [
        {"name": "BridgeKey", "dataType": "string", "summarizeBy": "distinctCount"}],
        "measures": []})
    return inv


def _build_distinct():
    files, mapping = assemble(_distinct_inv(), {}, "MyConn", "db1", "sch1", "LEFT_OUTER", False)
    model = next(tml for fn, tml in files if fn.endswith(".model.tml"))["model"]
    tables = {tml["table"]["name"]: tml["table"] for fn, tml in files if fn.endswith(".table.tml")}
    return model, tables, mapping


def test_distinct_count_column_keeps_the_key_and_adds_a_count():
    # Re-review: the Model column `CustomerKey` had BECOME the count, so a visual that
    # grouped by CustomerKey got one total row, marked Migrated. The key stays an
    # attribute under its own name; the distinct count is a separate formula column.
    # (Before BL-447 the column was `column_id` + COUNT_DISTINCT, demoted on a text key.)
    model, _, _ = _build_distinct()
    by_name = {c["name"]: c for c in model["columns"]}
    assert by_name["CustomerKey"] == {"name": "CustomerKey", "column_id": "Fact::CustomerKey",
                                      "properties": {"column_type": "ATTRIBUTE"}}
    count = by_name["CustomerKey (Distinct Count)"]
    assert count["formula_id"] == "formula_CustomerKey (Distinct Count)"
    assert count["properties"] == {"column_type": "MEASURE", "aggregation": "SUM",
                                   "index_type": "DONT_INDEX"}
    f = next(f for f in model["formulas"] if f["id"] == count["formula_id"])
    assert f["expr"] == ("( unique count ( [Fact::CustomerKey] ) + max ( if ( isnull "
                         "( [Fact::CustomerKey] ) ) then 1 else 0 ) )")  # BL-540


def test_no_count_distinct_aggregation_anywhere_and_i5_clean():
    from ts_cli.tml_lint import lint_tml
    model, tables, _ = _build_distinct()
    every_col = model["columns"] + [c for t in tables.values() for c in t["columns"]]
    assert not [c for c in every_col if (c.get("properties") or {}).get("aggregation") == "COUNT_DISTINCT"]
    assert tables["Fact"]["columns"][-1]["properties"] == {"column_type": "ATTRIBUTE"}
    assert not [f for f in lint_tml({"model": model}) if f.startswith(("I5", "I1"))]


def test_a_one_column_table_keeps_its_key_too():
    model, _, mapping = _build_distinct()
    bridge = [c for c in model["columns"] if str(c.get("column_id", "")).startswith("Bridge::")]
    assert bridge == [{"name": "BridgeKey", "column_id": "Bridge::BridgeKey",
                       "properties": {"column_type": "ATTRIBUTE"}}]
    assert any(c["name"] == "BridgeKey (Distinct Count)" for c in model["columns"])
    assert not any("kept as attributes" in w for w in mapping["warnings"])


def test_distinct_count_column_is_reported_in_the_mapping():
    _, _, mapping = _build_distinct()
    row = next(r for r in mapping["measures"] if r["name"] == "CustomerKey (Distinct Count)")
    assert row["status"] == "Approximated"
    assert row["ts_formula"].startswith("( unique count ( [Fact::CustomerKey] ) + max ( if ( isnull")
    # names the case where it differs from Power BI (review, BL-540)
    assert "no matching" in row["note"] and "blank row" in row["note"]
