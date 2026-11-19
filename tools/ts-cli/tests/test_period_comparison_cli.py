# tools/ts-cli/tests/test_period_comparison_cli.py
"""`ts recipe period-comparison`: options in, TML files and JSON out, no network."""
import json

import yaml

from ansi import plain
from runners import runner

from ts_cli.cli import app

# Synthetic identifiers only.
MODEL = ["--model-name", "Retail Sales", "--model-guid", "00000000-0000-0000-0000-0000000000aa"]
COLS = ["--date-column", "order date", "--measure-column", "Amount"]
TODAY = ["--today", "2026-11-18"]


def _run(tmp_path, *extra):
    args = ["recipe", "period-comparison", *MODEL, *COLS, *TODAY, "-o", str(tmp_path / "out"),
            *extra]
    return runner.invoke(app, args)


def _json(result):
    # stdout only: on Click 8.2+ `output` also carries the stderr diagnostics.
    return json.loads(result.stdout)


def _files(tmp_path):
    out = tmp_path / "out"
    return sorted(p.name for p in out.iterdir()) if out.exists() else []


def test_bf_formula_writes_one_file(tmp_path):
    r = _run(tmp_path, "--event", "black-friday", "--years", "2024-2025", "--name", "BF Lift")
    assert r.exit_code == 0, plain(r)
    out = _json(r)
    assert out["step"] == 7
    assert _files(tmp_path) == ["BF Lift.answer.tml"]
    assert out["files"] == [str(tmp_path / "out" / "BF Lift.answer.tml")]
    assert [y["year"] for y in out["years"]] == [2024, 2025]
    y2025 = out["years"][1]
    assert y2025["event"] == ["2025-11-28", "2025-12-01"]
    assert y2025["comparisons"][0] == ["2025-11-21", "2025-11-24"]
    assert len(y2025["comparisons"]) == 6
    assert out["dropped_years"] == [] and out["clashes"] == []
    assert out["needs_clash_decision"] is False
    doc = yaml.safe_load((tmp_path / "out" / "BF Lift.answer.tml").read_text())
    assert doc["answer"]["name"] == "BF Lift"
    assert "guid" not in doc
    names = [f["name"] for f in doc["answer"]["formulas"]]
    assert "Average Black Friday Sales" in names


def test_reusable_writes_set_and_answer(tmp_path):
    r = _run(tmp_path, "--event", "black-friday", "--years", "2024-2025", "--bucket",
             "reusable-set", "--name", "BF Lift", "--set-name", "BF Periods",
             "--set-guid", "00000000-0000-0000-0000-0000000000bb",
             "--answer-guid", "00000000-0000-0000-0000-0000000000cc")
    assert r.exit_code == 0, plain(r)
    assert _files(tmp_path) == ["BF Lift.answer.tml", "BF Periods.cohort.tml"]
    assert len(_json(r)["files"]) == 2
    cohort = yaml.safe_load((tmp_path / "out" / "BF Periods.cohort.tml").read_text())
    assert cohort["guid"] == "00000000-0000-0000-0000-0000000000bb"
    assert cohort["cohort"]["name"] == "BF Periods"
    assert cohort["cohort"]["worksheet"]["fqn"] == "00000000-0000-0000-0000-0000000000aa"
    answer = yaml.safe_load((tmp_path / "out" / "BF Lift.answer.tml").read_text())
    assert answer["guid"] == "00000000-0000-0000-0000-0000000000cc"
    assert any("[BF Periods]" in f["expr"] for f in answer["answer"]["formulas"])


def test_boxing_day_without_on_clash_exits_2_and_writes_nothing(tmp_path):
    r = _run(tmp_path, "--event", "boxing-day", "--years", "2025")
    assert r.exit_code == 2, plain(r)
    out = _json(r)
    assert out["needs_clash_decision"] is True
    assert out["files"] == []
    assert {c["event"] for c in out["clashes"]} >= {"black-friday", "cyber-monday"}
    assert all(c["year"] == 2025 and len(c["window"]) == 2 for c in out["clashes"])
    assert _files(tmp_path) == []


def test_boxing_day_skip_reports_substitutions(tmp_path):
    r = _run(tmp_path, "--event", "boxing-day", "--years", "2025", "--on-clash", "skip")
    assert r.exit_code == 0, plain(r)
    out = _json(r)
    subs = out["years"][0]["substitutions"]
    assert subs and all(set(s) == {"replaced", "with"} for s in subs)
    assert ["2025-11-28", "2025-12-01"] in [s["replaced"] for s in subs]
    assert out["needs_clash_decision"] is False
    assert len(out["files"]) == 1


def test_plan_error_exits_1_with_json_error(tmp_path):
    # A 10-day Christmas window runs into the next year: a hard error.
    r = _run(tmp_path, "--event", "christmas", "--length", "10", "--years", "2025")
    assert r.exit_code == 1, plain(r)
    out = _json(r)
    assert set(out) == {"error"} and "2025" in out["error"]
    assert _files(tmp_path) == []


def test_builder_error_after_plan_writes_nothing(tmp_path):
    # The plan is fine; the Set name holds a bracket, so building the Set fails.
    # The Answer must not be written either.
    r = _run(tmp_path, "--event", "black-friday", "--years", "2025", "--bucket",
             "reusable-set", "--set-name", "BF [Set]")
    assert r.exit_code == 1, plain(r)
    assert "bracket" in _json(r)["error"]
    assert _files(tmp_path) == []


def test_today_drops_unfinished_year(tmp_path):
    r = _run(tmp_path, "--event", "black-friday", "--years", "2025-2026")
    assert r.exit_code == 0, plain(r)
    out = _json(r)
    assert out["dropped_years"] == [2026]
    assert [y["year"] for y in out["years"]] == [2025]


def test_last_n(tmp_path):
    r = _run(tmp_path, "--event", "black-friday", "--last", "3")
    assert r.exit_code == 0, plain(r)
    assert [y["year"] for y in _json(r)["years"]] == [2023, 2024, 2025]


def test_years_and_last_together_is_error(tmp_path):
    r = _run(tmp_path, "--event", "black-friday", "--years", "2024-2025", "--last", "2")
    assert r.exit_code == 1, plain(r)
    assert "error" in _json(r)
    assert _files(tmp_path) == []


def test_bad_years_is_error(tmp_path):
    r = _run(tmp_path, "--event", "black-friday", "--years", "twenty")
    assert r.exit_code == 1, plain(r)
    assert "twenty" in _json(r)["error"]


def test_unknown_bucket_is_error(tmp_path):
    r = _run(tmp_path, "--event", "black-friday", "--years", "2025", "--bucket",
             "answer-set")
    assert r.exit_code == 1, plain(r)
    assert "answer-set" in _json(r)["error"]


def test_name_with_slash_is_safe_file_name(tmp_path):
    r = _run(tmp_path, "--event", "black-friday", "--years", "2025", "--bucket",
             "reusable-set", "--name", "Sales/Lift\\FY", "--set-name", "BF/Set")
    assert r.exit_code == 0, plain(r)
    assert _files(tmp_path) == ["BF_Set.cohort.tml", "Sales_Lift_FY.answer.tml"]
    answer = yaml.safe_load((tmp_path / "out" / "Sales_Lift_FY.answer.tml").read_text())
    assert answer["answer"]["name"] == "Sales/Lift\\FY"
    cohort = yaml.safe_load((tmp_path / "out" / "BF_Set.cohort.tml").read_text())
    assert cohort["cohort"]["name"] == "BF/Set"


def test_labels_partial_override(tmp_path):
    r = _run(tmp_path, "--event", "black-friday", "--years", "2025", "--bucket",
             "reusable-set", "--set-name", "BF Set",
             "--labels", "event=Black Friday Weekend,other=Everything Else")
    assert r.exit_code == 0, plain(r)
    cohort = yaml.safe_load((tmp_path / "out" / "BF Set.cohort.tml").read_text())
    config = cohort["cohort"]["config"]
    assert [g["name"] for g in config["groups"]] == ["Black Friday Weekend", "6 Prior Weeks"]
    assert config["null_output_value"] == "Everything Else"


def test_labels_unknown_key_is_error(tmp_path):
    r = _run(tmp_path, "--event", "black-friday", "--years", "2025", "--labels", "baseline=X")
    assert r.exit_code == 1, plain(r)
    assert "baseline" in _json(r)["error"]


def test_custom_event_from_file(tmp_path):
    dates = tmp_path / "events.yaml"
    dates.write_text("2024: '2024-05-12'\n2025: '2025-05-11'\n")
    r = _run(tmp_path, "--event", "custom", "--event-name", "Mothers Day",
             "--event-dates", str(dates), "--length", "1", "--years", "2024-2025",
             "--name", "MD Lift", "--on-clash", "skip")  # Easter 2024/2025 is a prior Sunday
    assert r.exit_code == 0, plain(r)
    out = _json(r)
    assert out["years"][1]["event"] == ["2025-05-11", "2025-05-11"]
    answer = yaml.safe_load((tmp_path / "out" / "MD Lift.answer.tml").read_text())
    assert "Average Mothers Day Sales" in [f["name"] for f in answer["answer"]["formulas"]]


def test_custom_event_needs_event_name(tmp_path):
    dates = tmp_path / "events.yaml"
    dates.write_text("2025: '2025-05-11'\n")
    r = _run(tmp_path, "--event", "custom", "--event-dates", str(dates), "--years", "2025")
    assert r.exit_code == 1, plain(r)
    assert "--event-name" in _json(r)["error"]


def test_event_dates_with_builtin_event_is_error(tmp_path):
    dates = tmp_path / "events.yaml"
    dates.write_text("2025: '2025-05-11'\n")
    r = _run(tmp_path, "--event", "black-friday", "--event-dates", str(dates),
             "--years", "2025")
    assert r.exit_code == 1, plain(r)
    assert "--event-dates" in _json(r)["error"]


def test_bad_today_is_error(tmp_path):
    args = ["recipe", "period-comparison", *MODEL, *COLS, "--today", "18/11/2026",
            "--event", "black-friday", "--years", "2025", "-o", str(tmp_path / "out")]
    r = runner.invoke(app, args)
    assert r.exit_code == 1, plain(r)
    assert "18/11/2026" in _json(r)["error"]


def test_today_option_is_hidden():
    r = runner.invoke(app, ["recipe", "period-comparison", "--help"])
    assert r.exit_code == 0
    text = plain(r)
    assert "--model-name" in text and "--today" not in text


# --- --data-through: the last day the data is loaded through ---

def _run_through(tmp_path, through, *extra):
    args = ["recipe", "period-comparison", *MODEL, *COLS, "--data-through", through,
            "-o", str(tmp_path / "out"), *extra]
    return runner.invoke(app, args)


def test_data_through_drops_year_whose_window_ends_after_it(tmp_path):
    # Black Friday 2025 runs 28 Nov to 1 Dec; data loaded through 30 Nov misses a day.
    r = _run_through(tmp_path, "2025-11-30", "--event", "black-friday", "--years", "2024-2025")
    assert r.exit_code == 0, plain(r)
    out = _json(r)
    assert [y["year"] for y in out["years"]] == [2024]
    assert out["dropped_years"] == [2025]


def test_data_through_keeps_window_ending_on_it(tmp_path):
    r = _run_through(tmp_path, "2025-12-01", "--event", "black-friday", "--years", "2024-2025")
    assert r.exit_code == 0, plain(r)
    out = _json(r)
    assert [y["year"] for y in out["years"]] == [2024, 2025]
    assert out["dropped_years"] == []


def test_data_through_with_last_n(tmp_path):
    r = _run_through(tmp_path, "2025-06-30", "--event", "black-friday", "--last", "2")
    assert r.exit_code == 0, plain(r)
    out = _json(r)
    assert [y["year"] for y in out["years"]] == [2023, 2024]
    assert out["dropped_years"] == [2025]


def test_data_through_and_today_together_is_error(tmp_path):
    r = _run(tmp_path, "--data-through", "2025-12-31", "--event", "black-friday",
             "--years", "2025")
    assert r.exit_code == 1, plain(r)
    assert "--data-through" in _json(r)["error"]
    assert _files(tmp_path) == []


def test_bad_data_through_is_error(tmp_path):
    r = _run_through(tmp_path, "31/12/2025", "--event", "black-friday", "--years", "2025")
    assert r.exit_code == 1, plain(r)
    err = _json(r)["error"]
    assert "--data-through" in err and "31/12/2025" in err


def test_data_through_option_is_documented():
    r = runner.invoke(app, ["recipe", "period-comparison", "--help"])
    assert r.exit_code == 0
    assert "--data-through" in plain(r)


def test_comparison_range_typed_in_a_future_year_is_an_error(tmp_path):
    dates = tmp_path / "cmp.yaml"
    dates.write_text(
        "2023: [['2023-11-01', '2023-11-04']]\n"
        "2024: [['2024-10-01', '2024-10-04'], ['2027-11-01', '2027-11-04']]\n"
        "2025: [['2025-11-01', '2025-11-04']]\n")
    r = _run_through(tmp_path, "2026-11-18", "--event", "black-friday", "--years", "2023-2025",
                     "--comparison", "custom", "--comparison-dates", str(dates))
    assert r.exit_code == 1, plain(r)
    assert "outside calendar year 2024" in _json(r)["error"]
    assert _files(tmp_path) == []


def test_help_keeps_the_range_text():
    # "[start, end]" was read as Rich markup and vanished from the help.
    r = runner.invoke(app, ["recipe", "period-comparison", "--help"], terminal_width=200)
    assert r.exit_code == 0
    text = " ".join(plain(r).replace("│", " ").split())
    assert "a start date (2025: '2025-05-11') or to one (start, end) date range" in text
    assert "each year to a list of (start, end) date ranges" in text
