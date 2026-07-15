from ts_cli.aggregate.scoring import greedy_select


def _sig(w=1.0):
    return {"weight": w, "parse_status": "full"}


def test_coverage_mode_picks_by_newly_covered_weight():
    sigs = [_sig(), _sig(), _sig()]
    cands = [
        {"id": "a", "covered": [0, 1], "agg_rows": None, "flags": []},
        {"id": "b", "covered": [2], "agg_rows": None, "flags": []},
        {"id": "c", "covered": [0], "agg_rows": None, "flags": []},  # subsumed by a
    ]
    result = greedy_select(cands, sigs)
    assert result["mode"] == "coverage"
    assert result["selected"] == ["a", "b"]  # c adds nothing in coverage mode


def test_cost_mode_selects_nested_aggregate_for_compression():
    # A covers both sigs at 1000 rows; B covers sig0 only at 10 rows.
    # Coverage-greedy would stop after A; cost-greedy also takes B.
    sigs = [_sig(), _sig()]
    cands = [
        {"id": "A", "covered": [0, 1], "agg_rows": 1000, "flags": []},
        {"id": "B", "covered": [0], "agg_rows": 10, "flags": []},
    ]
    result = greedy_select(cands, sigs, base_rows=1_000_000)
    assert result["mode"] == "cost"
    assert result["selected"] == ["A", "B"]
    # B's marginal benefit is vs A's rows, not vs base
    b_entry = [e for e in result["curve"] if e["id"] == "B"][0]
    assert b_entry["marginal_benefit"] == 1.0 * (1000 - 10)


def test_cost_mode_stops_when_no_positive_gain():
    sigs = [_sig()]
    cands = [
        {"id": "A", "covered": [0], "agg_rows": 100, "flags": []},
        {"id": "worse", "covered": [0], "agg_rows": 5000, "flags": []},
    ]
    result = greedy_select(cands, sigs, base_rows=1_000_000)
    assert result["selected"] == ["A"]


def test_curve_reports_cumulative_coverage_pct():
    sigs = [_sig(2.0), _sig(1.0), _sig(1.0)]
    cands = [{"id": "a", "covered": [0], "agg_rows": None, "flags": []},
             {"id": "b", "covered": [1, 2], "agg_rows": None, "flags": []}]
    result = greedy_select(cands, sigs)
    assert result["curve"][0]["cumulative_coverage_pct"] == 50.0
    assert result["curve"][1]["cumulative_coverage_pct"] == 100.0


def test_consolidation_analysis_reports_combined_vs_narrow():
    from ts_cli.aggregate.scoring import consolidation_analysis
    candidates = [
        {"id": "c_state", "dimensions": ["State"], "covered": [0], "agg_rows": 14},
        {"id": "c_cat", "dimensions": ["Category"], "covered": [1], "agg_rows": 8},
        {"id": "c_prod", "dimensions": ["Product"], "covered": [2], "agg_rows": 77},
        {"id": "c_combined", "dimensions": ["State", "Category", "Product"],
         "covered": [0, 1, 2], "agg_rows": 6776},
    ]
    out = consolidation_analysis(candidates)
    assert len(out) == 1
    a = out[0]
    assert a["combined"] == "c_combined" and a["combined_agg_rows"] == 6776
    assert {s["id"] for s in a["subsumes"]} == {"c_state", "c_cat", "c_prod"}
    assert a["narrow_total_rows"] == 14 + 8 + 77   # what N separate aggregates cost


def test_consolidation_analysis_skips_when_fewer_than_two_subsumed():
    from ts_cli.aggregate.scoring import consolidation_analysis
    # A combined grain that only subsumes one narrow grain isn't a meaningful
    # combine-vs-split trade-off.
    candidates = [
        {"id": "c_state", "dimensions": ["State"], "covered": [0], "agg_rows": 14},
        {"id": "c_two", "dimensions": ["State", "Region"], "covered": [0], "agg_rows": 50},
    ]
    assert consolidation_analysis(candidates) == []


def test_consolidation_analysis_rows_none_until_profiled():
    from ts_cli.aggregate.scoring import consolidation_analysis
    candidates = [
        {"id": "a", "dimensions": ["A"], "covered": [0]},
        {"id": "b", "dimensions": ["B"], "covered": [1]},
        {"id": "ab", "dimensions": ["A", "B"], "covered": [0, 1]},
    ]
    out = consolidation_analysis(candidates)
    assert out[0]["narrow_total_rows"] is None      # unprofiled -> no row total
    assert out[0]["combined_agg_rows"] is None


def test_consolidation_analysis_excludes_narrow_dim_not_in_combined():
    from ts_cli.aggregate.scoring import consolidation_analysis
    # cand_date covers only the grand-total sig (0) — a subset of the combined's
    # coverage — but its dim ("Balance Date") is NOT in the combined grain, so
    # it must NOT be reported as subsumed (the combined table doesn't serve
    # Balance-Date-grouped queries).
    candidates = [
        {"id": "c_state", "dimensions": ["State"], "covered": [0, 1], "agg_rows": 14},
        {"id": "c_cat", "dimensions": ["Category"], "covered": [0, 2], "agg_rows": 8},
        {"id": "c_date", "dimensions": ["Balance Date"], "covered": [0], "agg_rows": 300},
        {"id": "c_combined", "dimensions": ["State", "Category"],
         "covered": [0, 1, 2], "agg_rows": 100},
    ]
    out = consolidation_analysis(candidates)
    assert {s["id"] for s in out[0]["subsumes"]} == {"c_state", "c_cat"}
    assert "c_date" not in {s["id"] for s in out[0]["subsumes"]}
