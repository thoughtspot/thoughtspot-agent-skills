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
