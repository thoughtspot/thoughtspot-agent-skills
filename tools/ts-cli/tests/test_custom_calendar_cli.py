import json
from typer.testing import CliRunner
from ts_cli.commands.calendars import app

runner = CliRunner()


def test_preview_reports_year_spans_and_leap_periods():
    res = runner.invoke(app, [
        "preview", "--start-month", "February", "--start-day", "Monday",
        "--pattern", "4-5-4", "--anchor", "nearest",
        "--first-year", "2015", "--last-year", "2026",
    ])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["years"][0]["start"] == "2015-02-02"
    assert payload["years"][0]["weeks"] == 52
    leap = [y for y in payload["years"] if y["weeks"] == 53]
    assert [y["year"] for y in leap] == [2018, 2024]
    assert leap[0]["long_period"] == 12


def test_preview_emits_no_rows():
    res = runner.invoke(app, [
        "preview", "--start-month", "February", "--start-day", "Monday",
        "--pattern", "4-5-4", "--anchor", "nearest",
        "--first-year", "2017", "--last-year", "2017",
    ])
    assert "rows" not in json.loads(res.stdout)


def test_generate_writes_csv(tmp_path):
    out = tmp_path / "cal.csv"
    res = runner.invoke(app, [
        "generate", "--start-month", "February", "--start-day", "Monday",
        "--pattern", "4-5-4", "--anchor", "nearest",
        "--first-year", "2017", "--last-year", "2017",
        "--out", str(out),
    ])
    assert res.exit_code == 0, res.output
    lines = out.read_text().splitlines()
    assert lines[0].startswith("date,day_of_week,month,quarter,year,")
    assert len(lines) == 365            # header + 364 days


def test_generate_ten_column_mode(tmp_path):
    out = tmp_path / "cal10.csv"
    runner.invoke(app, [
        "generate", "--start-month", "February", "--start-day", "Monday",
        "--pattern", "4-5-4", "--anchor", "nearest",
        "--first-year", "2017", "--last-year", "2017",
        "--columns", "10", "--out", str(out),
    ])
    assert out.read_text().splitlines()[0].count(",") == 9


def test_generate_rejects_bad_pattern(tmp_path):
    res = runner.invoke(app, [
        "generate", "--start-month", "February", "--start-day", "Monday",
        "--pattern", "9-9-9", "--anchor", "nearest",
        "--first-year", "2017", "--last-year", "2017",
        "--out", str(tmp_path / "x.csv"),
    ])
    assert res.exit_code != 0
    assert "pattern" in res.output.lower()


def test_compare_cli_varies_year_basis():
    res = runner.invoke(app, [
        "compare", "--vary", "year-basis",
        "--start-month", "December", "--start-day", "Monday",
        "--pattern", "4-4-5", "--anchor", "first",
        "--first-year", "2024", "--last-year", "2024",
    ])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["differing_rows"] > 0


def test_compare_cli_varies_anchor():
    res = runner.invoke(app, [
        "compare", "--vary", "anchor",
        "--start-month", "February", "--start-day", "Monday",
        "--pattern", "4-5-4", "--anchor", "nearest",
        "--first-year", "2015", "--last-year", "2026",
    ])
    assert res.exit_code == 0, res.output
    assert json.loads(res.stdout)["first_divergence"] == 2017


def test_compare_cli_rejects_unknown_dimension():
    res = runner.invoke(app, [
        "compare", "--vary", "colour",
        "--start-month", "February", "--start-day", "Monday",
        "--pattern", "4-5-4", "--anchor", "nearest",
        "--first-year", "2017", "--last-year", "2017",
    ])
    assert res.exit_code != 0
