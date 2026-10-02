from ts_cli.sets.scope import select_models

MS = [{"guid": "g1", "name": "Dunder Mifflin"}, {"guid": "g2", "name": "DunderMifflin Sales"},
      {"guid": "g3", "name": "Retail"}]


def test_no_selectors_selects_all():
    assert select_models(MS, model=[], contains=[]) == (MS, [])


def test_guid_and_exact_name():
    got, miss = select_models(MS, model=["g3", "Dunder Mifflin"], contains=[])
    assert [m["guid"] for m in got] == ["g1", "g3"] and miss == []


def test_exact_name_is_case_insensitive():
    assert select_models(MS, model=["dunder mifflin"], contains=[])[0][0]["guid"] == "g1"


def test_contains_is_case_insensitive_substring():
    assert [m["guid"] for m in select_models(MS, model=[], contains=["DUNDER"])[0]] == ["g1", "g2"]


def test_overlapping_selectors_deduplicate():
    got, _ = select_models(MS, model=["g1"], contains=["dunder"])
    assert [m["guid"] for m in got] == ["g1", "g2"]


def test_unmatched_selectors_are_reported():
    assert select_models(MS, model=["nope"], contains=["zzz"])[1] == ["nope", "zzz"]


def test_missing_or_none_name_does_not_crash():
    ms = [{"guid": "g4", "name": None}, {"guid": "g5"}, {"guid": "g6", "name": "Retail"}]
    got, miss = select_models(ms, model=["g5", "retail"], contains=["ret", "zzz"])
    assert [m["guid"] for m in got] == ["g5", "g6"] and miss == ["zzz"]
