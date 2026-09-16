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


def test_same_basename_variants_are_distinct_not_merged(tmp_path):
    """Two variants in different directories must not collapse into one.

    Keying variants on Path(path).stem made a/cal.csv and b/cal.csv one entry,
    so the cross-variant check saw len < 2 and returned no findings: a false
    pass on the only check multi---csv mode exists for.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = _gen(tmp_path / "a", "cal.csv")
    b = _gen(tmp_path / "b", "cal.csv",
             month_names="FEB,MAR,APR,MAY,JUN,JUL,AUG,SEP,OCT,NOV,DEC,JAN")
    res = runner.invoke(app, ["validate", "--csv", str(a), "--csv", str(b)])
    assert res.exit_code != 0, res.output
    findings = json.loads(res.stdout)["findings"]
    assert any(f["code"] == "label-drift" for f in findings), findings


def test_the_same_csv_twice_is_rejected_not_silently_deduplicated(tmp_path):
    path = _gen(tmp_path, "dup.csv")
    res = runner.invoke(app, ["validate", "--csv", str(path), "--csv", str(path)])
    assert res.exit_code != 0
    assert "same file twice" in res.output


def test_a_28_column_csv_is_a_contract_error_not_a_ten_column_calendar(tmp_path):
    """Contract inference by header WIDTH let a malformed file pass clean.

    A 30-column calendar minus `monthly` and `quarterly` is 28 wide, so
    `len(header) >= 30` was false and it was read against the 10-column
    contract — whose ten columns were all present — and validated clean.
    """
    path = _gen(tmp_path, "twenty_eight.csv")
    _drop_column(path, "monthly")
    _drop_column(path, "quarterly")
    assert len(path.read_text().splitlines()[0].split(",")) == 28

    res = runner.invoke(app, ["validate", "--csv", str(path)])
    assert res.exit_code != 0, res.output
    findings = json.loads(res.stdout)["findings"]
    assert any(f["code"] == "column-contract" and "monthly" in f["message"]
               and "quarterly" in f["message"] for f in findings), findings


def test_a_trailing_discriminator_column_is_still_accepted(tmp_path):
    """The one tolerated deviation from an exact contract match."""
    path = _gen(tmp_path, "rls.csv",
                discriminator_column="TSGROUP", discriminator_value="TENANT_A")
    assert path.read_text().splitlines()[0].split(",")[-1] == "TSGROUP"
    res = runner.invoke(app, ["validate", "--csv", str(path)])
    assert res.exit_code == 0, res.output
    assert json.loads(res.stdout)["findings"] == []


def test_extra_columns_beyond_one_discriminator_are_rejected(tmp_path):
    path = _gen(tmp_path, "two_extra.csv")
    lines = path.read_text().splitlines()
    path.write_text("\n".join(f"{ln},x,y" if i else f"{ln},X1,X2"
                               for i, ln in enumerate(lines)) + "\n")
    res = runner.invoke(app, ["validate", "--csv", str(path)])
    assert res.exit_code != 0, res.output
    assert any(f["code"] == "column-contract"
               for f in json.loads(res.stdout)["findings"])


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


import pytest
from ts_cli.commands.calendars import build_register_payload


def test_register_payload_defaults_to_from_existing_table():
    payload = build_register_payload(
        name="RetailCal", connection="conn1", database="CUSTOM_CALENDAR",
        schema="PUBLIC", table="retail_cal", native=False, spec=None)
    assert payload["creation_method"] == "FROM_EXISTING_TABLE"
    assert payload["table_reference"] == {
        "connection_identifier": "conn1", "database_name": "CUSTOM_CALENDAR",
        "schema_name": "PUBLIC", "table_name": "retail_cal"}
    # All five generation-only keys are set atomically in build_register_payload —
    # assert every one absent, not just calendar_type, so a future change that
    # splits them apart still gets caught here.
    assert "calendar_type" not in payload
    assert "month_offset" not in payload
    assert "start_day_of_week" not in payload
    assert "start_date" not in payload
    assert "end_date" not in payload


def test_native_payload_carries_generation_parameters():
    from ts_cli.custom_calendar.spec import CalendarSpec
    spec = CalendarSpec(start_month=2, start_day_of_week=1, pattern="4-5-4",
                        anchor_rule="fixed52", first_year=2027, last_year=2027)
    payload = build_register_payload(
        name="N", connection="c", database="D", schema="S", table="T",
        native=True, spec=spec)
    assert payload["creation_method"] == "FROM_INPUT_PARAMS"
    assert payload["calendar_type"] == "FOUR_FIVE_FOUR"
    assert payload["month_offset"] == "February"
    assert payload["start_day_of_week"] == "Monday"
    # start_date/end_date convention verified live against `generate-csv` on
    # 2026-09-16 (see open item #5): the old "nominal start of first_year
    # through nominal start of last_year + 1" form for end_date produced a
    # partial trailing fiscal period — the API's own row count ran 5 days past
    # our generator's for a 3-year fixed52 range (1097 vs. 1092 rows), and the
    # 5 extra days formed a stub 13th month rather than a clean cutoff. The
    # confirmed rule: end_date is the last day the calendar actually covers —
    # the day before the next fiscal year's anchor
    # (`resolve_anchor(spec, last_year + 1) - 1 day`), which equals
    # `build_rows(...)[-1]["date"]`. start_date is separately confirmed correct
    # as-is: for fixed52 it equals `resolve_anchor(spec, first_year)` (the API
    # snaps forward to the next start_day_of_week, the same rule `anchor_first`
    # encodes), and matched the live first row (2027-02-01) exactly.
    assert payload["start_date"] == "02/01/2027"
    assert payload["end_date"] == "01/30/2028"


def test_native_payload_date_range_spans_multiple_fiscal_years():
    # Same convention-pinning intent as the single-year case above, but across a
    # multi-year range so an off-by-one-year regression (e.g. using last_year
    # instead of last_year + 1) is caught, not just an off-by-one-month one.
    # This is also the range the live 2026-09-16 verification used, where the
    # old formula's overshoot grew to 5 days (see open item #5).
    from ts_cli.custom_calendar.spec import CalendarSpec
    spec = CalendarSpec(start_month=2, start_day_of_week=1, pattern="4-5-4",
                        anchor_rule="fixed52", first_year=2027, last_year=2029)
    payload = build_register_payload(
        name="N", connection="c", database="D", schema="S", table="T",
        native=True, spec=spec)
    assert payload["start_date"] == "02/01/2027"
    assert payload["end_date"] == "01/27/2030"


def test_native_refuses_non_fixed52_anchor_rules():
    from ts_cli.custom_calendar.spec import CalendarSpec
    for rule in ("nearest", "first"):
        spec = CalendarSpec(start_month=2, start_day_of_week=1, pattern="4-5-4",
                            anchor_rule=rule, first_year=2027, last_year=2027)
        with pytest.raises(ValueError, match="fixed52"):
            build_register_payload(name="N", connection="c", database="D",
                                   schema="S", table="T", native=True, spec=spec)


def test_native_refuses_13x4_which_the_api_cannot_express():
    from ts_cli.custom_calendar.spec import CalendarSpec
    spec = CalendarSpec(start_month=1, start_day_of_week=1, pattern="13x4",
                        anchor_rule="fixed52", first_year=2027, last_year=2027)
    with pytest.raises(ValueError, match="13x4"):
        build_register_payload(name="N", connection="c", database="D",
                               schema="S", table="T", native=True, spec=spec)
