from ts_cli.aggregate.history import extract_group_by, match_history

COLMAP = {"DIM_CATEGORY.CATEGORY": "Category", "DIM.STATE": "State"}


def test_extract_group_by_columns():
    sql = "SELECT category, SUM(amount) FROM f JOIN d GROUP BY dim_category.category"
    assert extract_group_by(sql) == (["DIM_CATEGORY.CATEGORY"], False)


def test_extract_group_by_multiple_columns_and_terminators():
    sql = ("SELECT a, b FROM f GROUP BY dim.state, dim_category.category "
           "ORDER BY 1 LIMIT 10")
    assert extract_group_by(sql) == (["DIM.STATE", "DIM_CATEGORY.CATEGORY"], False)


def test_extract_group_by_no_clause_returns_empty():
    assert extract_group_by("SELECT 1 FROM f") == ([], False)
    assert extract_group_by("") == ([], False)
    assert extract_group_by(None) == ([], False)


def test_extract_group_by_flags_dropped_non_identifier_tokens():
    # date_trunc(...) is not a bare identifier — it must be dropped AND flagged,
    # so match_history knows the real query grouped by something (a date bucket)
    # it couldn't parse.
    sql = "SELECT 1 FROM f GROUP BY fact.category, date_trunc('MONTH', d)"
    cols, had_dropped = extract_group_by(sql)
    assert cols == ["FACT.CATEGORY"]
    assert had_dropped is True


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
    assert weights["g1::"] == 2.0  # base + 1 match (Category + State == dims|date, clean)


def test_match_history_no_group_by_rows_do_not_add_weight():
    sigs = [{"source_guid": "g1", "viz_name": None, "dimensions": ["Category"],
            "date_column": None, "parse_status": "full"}]
    rows = [{"query_text": "SELECT 1 FROM f"}]
    weights = match_history(rows, sigs, COLMAP)
    assert weights["g1::"] == 1.0  # base weight only, no crash on empty display set


def test_match_history_date_trunc_query_matches_dated_signature_only():
    # IMPORTANT bug fix: "GROUP BY fact.category, date_trunc('MONTH', d)" extracts
    # only [Category] (date_trunc dropped, had_dropped=True). It must credit the
    # date-grained signature (Category + a date bucket), NOT the coarser dateless
    # Category-only signature — otherwise date-bucketed queries (the common case)
    # systematically over-weight the wrong, coarser aggregate.
    dated = {"source_guid": "dated", "viz_name": None, "dimensions": ["Category"],
             "date_column": "State", "parse_status": "full"}
    dateless = {"source_guid": "dateless", "viz_name": None, "dimensions": ["Category"],
                "date_column": None, "parse_status": "full"}
    rows = [{"query_text": "SELECT 1 FROM f GROUP BY dim_category.category, "
                           "date_trunc('MONTH', order_dt)"}]
    weights = match_history(rows, [dated, dateless], COLMAP)
    assert weights["dated::"] == 2.0      # base + 1 (dims == extracted identifiers)
    assert weights["dateless::"] == 1.0   # base only — NOT credited to the coarser grain


def test_match_history_clean_group_by_still_exact_matches_dateless():
    # Regression guard: when NOTHING was dropped, a dateless signature still
    # matches a clean all-identifier GROUP BY by exact set-equality (unchanged).
    dateless = {"source_guid": "g1", "viz_name": None, "dimensions": ["Category"],
                "date_column": None, "parse_status": "full"}
    rows = [{"query_text": "SELECT 1 FROM f GROUP BY dim_category.category"}]
    weights = match_history(rows, [dateless], COLMAP)
    assert weights["g1::"] == 2.0
