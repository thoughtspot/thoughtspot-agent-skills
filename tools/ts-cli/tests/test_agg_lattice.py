from ts_cli.aggregate.lattice import bucket_covers, covers, generate_candidates
from ts_cli.aggregate.measures import classify_measure

PLANS = {"Sales": classify_measure("Sales", aggregation="SUM"),
         "Customers": classify_measure("Customers", expr="unique count ( [Customer] )")}


def _sig(dims, measures=("Sales",), date_column=None, bucket=None, filters=()):
    return {"dimensions": list(dims), "measures": list(measures),
            "date_column": date_column, "date_bucket": bucket,
            "filter_columns": list(filters), "parse_status": "full", "weight": 1.0,
            "source_guid": "g", "source_name": "s", "source_type": "ANSWER",
            "viz_name": None}


def test_bucket_covers_finer_or_equal_serves_coarser():
    assert bucket_covers("DAILY", "MONTHLY") is True   # daily grain answers monthly query
    assert bucket_covers("MONTHLY", "DAILY") is False
    assert bucket_covers("MONTHLY", "MONTHLY") is True
    assert bucket_covers(None, "MONTHLY") is True      # raw date grain answers anything dated
    assert bucket_covers("MONTHLY", None) is False     # detail-date query needs raw dates


def test_covers_requires_dims_filters_and_measures():
    cand = {"dimensions": ["Category", "State"], "date_column": None, "bucket": None}
    assert covers(cand, _sig(["Category"]), PLANS) is True
    assert covers(cand, _sig(["Category"], filters=["State"]), PLANS) is True
    assert covers(cand, _sig(["Category"], filters=["Region"]), PLANS) is False
    assert covers(cand, _sig(["Customer"]), PLANS) is False


def test_nonadditive_measure_needs_grain_column():
    cand_without = {"dimensions": ["Category"], "date_column": None, "bucket": None}
    cand_with = {"dimensions": ["Category", "Customer"], "date_column": None, "bucket": None}
    sig = _sig(["Category"], measures=["Customers"])
    assert covers(cand_without, sig, PLANS) is False
    assert covers(cand_with, sig, PLANS) is True


def test_generate_candidates_unions_similar_dimsets():
    sigs = [_sig(["Category", "State"]), _sig(["Category", "State", "Customer"]),
            _sig(["Category"])]
    cands = generate_candidates(sigs, PLANS)
    dimsets = [tuple(c["dimensions"]) for c in cands]
    # the union set covers all three signatures
    assert ("Category", "Customer", "State") in dimsets
    union = [c for c in cands if tuple(c["dimensions"]) == ("Category", "Customer", "State")][0]
    assert sorted(union["covered"]) == [0, 1, 2]


def test_candidates_use_finest_required_bucket():
    sigs = [_sig(["State"], date_column="Order Date", bucket="MONTHLY"),
            _sig(["State"], date_column="Order Date", bucket="DAILY")]
    cands = generate_candidates(sigs, PLANS)
    best = [c for c in cands if len(c["covered"]) == 2]
    assert best and best[0]["bucket"] == "DAILY"


def test_detail_date_sig_forces_raw_date_bucket():
    # A detail-date sig (date_bucket=None) needs raw dates: the merged candidate
    # must land at bucket=None and cover BOTH sigs, not bucket=MONTHLY covering one.
    sigs = [_sig(["State"], date_column="Order Date", bucket="MONTHLY"),
            _sig(["State"], date_column="Order Date", bucket=None)]
    cands = generate_candidates(sigs, PLANS)
    best = [c for c in cands if len(c["covered"]) == 2]
    assert best and best[0]["bucket"] is None
    assert sorted(best[0]["covered"]) == [0, 1]


def test_wide_grain_flagged():
    dims = [f"D{i}" for i in range(9)]
    cands = generate_candidates([_sig(dims)], PLANS, max_width=8)
    wide = [c for c in cands if len(c["dimensions"]) == 9]
    assert wide and "wide_grain" in wide[0]["flags"]
