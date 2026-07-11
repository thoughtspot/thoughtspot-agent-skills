from ts_cli.aggregate.history import extract_group_by, match_history

COLMAP = {"DIM_CATEGORY.CATEGORY": "Category", "DIM.STATE": "State"}


def test_extract_group_by_columns():
    sql = "SELECT category, SUM(amount) FROM f JOIN d GROUP BY dim_category.category"
    assert extract_group_by(sql) == ["DIM_CATEGORY.CATEGORY"]


def test_extract_group_by_multiple_columns_and_terminators():
    sql = ("SELECT a, b FROM f GROUP BY dim.state, dim_category.category "
           "ORDER BY 1 LIMIT 10")
    assert extract_group_by(sql) == ["DIM.STATE", "DIM_CATEGORY.CATEGORY"]


def test_extract_group_by_no_clause_returns_empty():
    assert extract_group_by("SELECT 1 FROM f") == []
    assert extract_group_by("") == []
    assert extract_group_by(None) == []


def test_match_history_weights_matching_signatures():
    sigs = [
        {"source_guid": "g1", "viz_name": None, "dimensions": ["Category"],
         "date_column": None, "parse_status": "full"},
        {"source_guid": "g2", "viz_name": "v", "dimensions": ["State"],
         "date_column": None, "parse_status": "full"},
    ]
    rows = [{"query_text": "SELECT 1 FROM f GROUP BY dim_category.category"},
            {"query_text": "SELECT 1 FROM f GROUP BY dim_category.category"}]
    weights = match_history(rows, sigs, COLMAP)
    assert weights["g1::"] == 3.0   # 1 base + 2 history hits
    assert weights["g2::v"] == 1.0  # base weight only


def test_match_history_date_column_included_in_signature_dims():
    sigs = [{"source_guid": "g1", "viz_name": None, "dimensions": ["Category"],
            "date_column": "State", "parse_status": "full"}]
    rows = [{"query_text": "SELECT 1 FROM f GROUP BY dim_category.category, dim.state"}]
    weights = match_history(rows, sigs, COLMAP)
    assert weights["g1::"] == 2.0  # base + 1 match (Category + State == dims|date)


def test_match_history_no_group_by_rows_do_not_add_weight():
    sigs = [{"source_guid": "g1", "viz_name": None, "dimensions": ["Category"],
            "date_column": None, "parse_status": "full"}]
    rows = [{"query_text": "SELECT 1 FROM f"}]
    weights = match_history(rows, sigs, COLMAP)
    assert weights["g1::"] == 1.0  # base weight only, no crash on empty display set
