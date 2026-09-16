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


def _gen(tmp_path, name, **extra):
    out = tmp_path / name
    args = ["generate", "--start-month", "February", "--start-day", "Monday",
            "--pattern", "4-5-4", "--anchor", "nearest",
            "--first-year", "2017", "--last-year", "2017", "--out", str(out)]
    for k, v in extra.items():
        args += [f"--{k.replace('_', '-')}", v]
    res = runner.invoke(app, args)
    assert res.exit_code == 0, res.output
    return out


def test_validate_passes_a_clean_calendar(tmp_path):
    path = _gen(tmp_path, "clean.csv")
    res = runner.invoke(app, ["validate", "--csv", str(path)])
    assert res.exit_code == 0, res.output
    assert json.loads(res.stdout)["findings"] == []


def test_validate_fails_on_a_date_gap(tmp_path):
    path = _gen(tmp_path, "gap.csv")
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:5] + lines[6:]) + "\n")
    res = runner.invoke(app, ["validate", "--csv", str(path)])
    assert res.exit_code != 0
    assert "date-gap" in res.stdout


def test_validate_flags_cross_variant_label_drift(tmp_path):
    a = _gen(tmp_path, "a.csv")
    b = _gen(tmp_path, "b.csv",
             month_names="FEB,MAR,APR,MAY,JUN,JUL,AUG,SEP,OCT,NOV,DEC,JAN")
    res = runner.invoke(app, ["validate", "--csv", str(a), "--csv", str(b)])
    assert res.exit_code != 0
    assert "label-drift" in res.stdout


def test_allow_label_drift_downgrades_and_exits_zero(tmp_path):
    a = _gen(tmp_path, "a2.csv")
    b = _gen(tmp_path, "b2.csv",
             month_names="FEB,MAR,APR,MAY,JUN,JUL,AUG,SEP,OCT,NOV,DEC,JAN")
    res = runner.invoke(app, ["validate", "--csv", str(a), "--csv", str(b),
                              "--allow-label-drift"])
    assert res.exit_code == 0, res.output
    assert any(f["severity"] == "warning" for f in json.loads(res.stdout)["findings"])


def _drop_column(path, column_name):
    lines = path.read_text().splitlines()
    header = lines[0].split(",")
    idx = header.index(column_name)
    mangled = [",".join(line.split(",")[:idx] + line.split(",")[idx + 1:]) for line in lines]
    path.write_text("\n".join(mangled) + "\n")


def test_validate_reports_missing_contract_column_without_crashing(tmp_path):
    path = _gen(tmp_path, "missing_col.csv")
    _drop_column(path, "quarter")
    res = runner.invoke(app, ["validate", "--csv", str(path)])
    assert res.exit_code != 0
    payload = json.loads(res.stdout)  # must parse as JSON — no traceback on stdout
    findings = payload["findings"]
    assert any(f["code"] == "column-contract" and "quarter" in f["message"]
              for f in findings)


def test_validate_continues_after_one_bad_csv_in_a_set(tmp_path):
    bad = _gen(tmp_path, "bad.csv")
    good = _gen(tmp_path, "good.csv")
    _drop_column(bad, "quarter")
    good_lines = good.read_text().splitlines()
    good.write_text("\n".join(good_lines[:5] + good_lines[6:]) + "\n")  # induce a date gap

    res = runner.invoke(app, ["validate", "--csv", str(bad), "--csv", str(good)])
    assert res.exit_code != 0
    payload = json.loads(res.stdout)
    assert any(f["code"] == "column-contract" and f["source"] == str(bad)
              for f in payload["findings"])
    assert any(f["code"] == "date-gap" and f["source"] == str(good)
              for f in payload["findings"])
