from ts_cli.aggregate.signatures import column_kinds_from_model, extract_signatures

KINDS = {"Sales": "MEASURE", "Order Date": "DATE", "Customer": "ATTRIBUTE",
         "Category": "ATTRIBUTE", "State": "ATTRIBUTE"}


def _answer(search_query, cols):
    return {"answer": {"name": "A1", "search_query": search_query,
                       "answer_columns": [{"name": c} for c in cols],
                       "tables": [{"name": "M"}]}}


def test_simple_answer_signature():
    doc = _answer("[Sales] [Category]", ["Sales", "Category"])
    sigs = extract_signatures(doc, KINDS, "g1", "A1")
    assert len(sigs) == 1
    s = sigs[0]
    assert s["measures"] == ["Sales"]
    assert s["dimensions"] == ["Category"]
    assert s["date_column"] is None and s["date_bucket"] is None
    assert s["parse_status"] == "full"
    assert s["weight"] == 1.0


def test_date_bucket_token_parsed():
    doc = _answer("[Sales] [Order Date].monthly [State]",
                  ["Sales", "Order Date", "State"])
    s = extract_signatures(doc, KINDS, "g1", "A1")[0]
    assert s["date_column"] == "Order Date"
    assert s["date_bucket"] == "MONTHLY"
    assert s["dimensions"] == ["State"]


def test_filter_tokens_captured_as_filter_columns():
    doc = _answer("[Sales] [Category] [State] = 'california'",
                  ["Sales", "Category"])
    s = extract_signatures(doc, KINDS, "g1", "A1")[0]
    assert s["filter_columns"] == ["State"]
    assert "State" not in s["dimensions"]  # filtered, not grouped


def test_unknown_column_marks_partial():
    doc = _answer("[Sales] [Mystery Col]", ["Sales", "Mystery Col"])
    s = extract_signatures(doc, KINDS, "g1", "A1")[0]
    assert s["parse_status"] == "partial"


def test_liveboard_yields_one_signature_per_viz():
    doc = {"liveboard": {"name": "LB", "visualizations": [
        {"viz_guid": "v1", "answer": _answer("[Sales] [Category]", ["Sales", "Category"])["answer"]},
        {"viz_guid": "v2", "answer": _answer("[Sales] [State]", ["Sales", "State"])["answer"]},
    ]}}
    sigs = extract_signatures(doc, KINDS, "g2", "LB")
    assert len(sigs) == 2
    assert all(s["source_type"] == "LIVEBOARD_VIZ" for s in sigs)
    assert sigs[0]["viz_name"] == "A1"


def test_column_kinds_from_model():
    model_tml = {"model": {"columns": [
        {"name": "Sales", "properties": {"column_type": "MEASURE"}},
        {"name": "Order Date", "data_type": "DATE",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "State", "properties": {"column_type": "ATTRIBUTE"}},
    ], "formulas": [{"name": "Avg Sale", "expr": "average ( [Sales] )"}]}}
    kinds = column_kinds_from_model(model_tml)
    assert kinds == {"Sales": "MEASURE", "Order Date": "DATE",
                     "State": "ATTRIBUTE", "Avg Sale": "MEASURE"}
