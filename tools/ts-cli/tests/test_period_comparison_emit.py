# tools/ts-cli/tests/test_period_comparison_emit.py
import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from ts_cli.period_comparison.emit import (
    MAX_CONDITIONS_PER_GROUP,
    Labels,
    ModelRef,
    answer_tml,
    bucket_formula_expr,
    cohort_config,
    default_labels,
    dump_tml,
    measure_formulas,
    reusable_set_tml,
    validate_labels,
)
from ts_cli.period_comparison.windows import PlanError, PlanSpec, build_plan

T = date(2026, 11, 18)
FIXTURES = (Path(__file__).resolve().parents[3] / "agents/cli/"
            "ts-recipe-answer-period-comparison/references/probe-fixtures")
GUID = "00000000-0000-0000-0000-000000000000"
SET_GUID = "00000000-0000-0000-0000-000000000001"
LBL = default_labels("Black Friday", "prior-weeks", 6)
MODEL = ModelRef("M", GUID)
MEASURES = ["Average Black Friday Sales", "Average Comparison Sales", "Variance to Baseline"]


@pytest.fixture(scope="module")
def plan_bf_2024_2025():
    return build_plan(PlanSpec("black-friday", years=(2024, 2025)), T)


def _answer(plan, bucket, **kw):
    args = dict(bucket=bucket, answer_name="BF", bucket_name="Bucket", model=MODEL,
                date_column="order date", measure_column="Amount",
                event_title="Black Friday")
    args.update(kw)
    return answer_tml(plan, LBL, **args)


# --- labels -------------------------------------------------------------------

def test_default_labels():
    assert LBL == Labels("Black Friday Days", "6 Prior Weeks", "Not Black Friday")
    assert default_labels("Easter", "custom", 6).comparison == "Comparison Periods"
    assert default_labels("Easter", "prior-weeks", 1).comparison == "1 Prior Week"


@pytest.mark.parametrize("bad", ["Mother's Day", "", 'a"b', "[x]"])
def test_bad_labels_rejected(bad):
    with pytest.raises(PlanError):
        validate_labels(Labels(bad, "C", "O"))


@pytest.mark.parametrize("labels", [
    Labels("Days", "Days", "Other"),
    Labels("Days", "Weeks", "days"),  # ThoughtSpot compares strings case-insensitively
    Labels(" Days", "Weeks", "Other"),
    Labels("Da\nys", "Weeks", "Other"),
])
def test_clashing_or_padded_labels_rejected(labels):
    with pytest.raises(PlanError):
        validate_labels(labels)


def test_brace_in_label_is_kept_verbatim(plan_bf_2024_2025):
    labels = Labels("{answer_name} Days", "Prior {x}", "Other")
    a = answer_tml(plan_bf_2024_2025, labels, bucket="formula", answer_name="BF",
                   bucket_name="Bucket", model=MODEL, date_column="order date",
                   measure_column="Amount", event_title="Black Friday")
    exprs = " ".join(f["expr"] for f in a["answer"]["formulas"])
    assert "'{answer_name} Days'" in exprs and "'Prior {x}'" in exprs


# --- reusable Set -------------------------------------------------------------

def test_set_has_one_condition_per_window(plan_bf_2024_2025):
    cfg = cohort_config(plan_bf_2024_2025, LBL, "order date")
    ev, cmp_ = cfg["groups"]
    assert len(ev["conditions"]) == 2 and len(cmp_["conditions"]) == 12
    c = ev["conditions"][0]["date_filter_values"][0]
    assert c["date_range"] == {"start_date": "11/29/2024", "end_date": "12/02/2024"}
    assert all(x["date_filter_values"][0]["date_period"] == "DAY"
               for g in cfg["groups"] for x in g["conditions"])
    assert cfg["null_output_value"] == LBL.other


def test_set_condition_matches_verified_shape(plan_bf_2024_2025):
    """Open item #3 / probe fixture reusable-set.cohort.yaml."""
    cfg = cohort_config(plan_bf_2024_2025, LBL, "order date")
    assert [k for k in cfg] == ["cohort_type", "cohort_grouping_type", "anchor_column_id",
                                "groups", "null_output_value", "combine_non_group_values"]
    assert cfg["cohort_type"] == "SIMPLE" and cfg["cohort_grouping_type"] == "GROUP_BASED"
    assert cfg["anchor_column_id"] == "order date" and cfg["combine_non_group_values"] is True
    ev, cmp_ = cfg["groups"]
    assert (ev["name"], cmp_["name"]) == (LBL.event, LBL.comparison)
    assert ev["combine_type"] == cmp_["combine_type"] == "ANY"
    assert cmp_["conditions"][0] == {
        "operator": "BW",
        "column_name": "order date",
        "filter_value_type": "DATE_FILTER",
        "date_filter_values": [{
            "type": "EXACT_DATE_RANGE",
            "oper": "between",
            "date_range": {"start_date": "11/22/2024", "end_date": "11/25/2024"},
            "date_period": "DAY",
            "for_each_period": "NUM_DATE_PERIODS",
        }],
    }


def test_set_matches_probe_fixture():
    """Same plan as the imported probe fixture reusable-set.cohort.yaml."""
    plan = build_plan(PlanSpec("black-friday", years=(2018, 2019)), T)
    want = yaml.safe_load((FIXTURES / "reusable-set.cohort.yaml").read_text())["cohort"]
    model = ModelRef("{model_name}", "{model_guid}")
    got = reusable_set_tml(plan, LBL, "Order Date", want["name"], model, None)["cohort"]
    assert got == want


def test_reusable_set_binding(plan_bf_2024_2025):
    doc = reusable_set_tml(plan_bf_2024_2025, LBL, "order date", "BF Set", MODEL, None)
    assert doc["cohort"]["worksheet"] == {"id": "M", "name": "M", "fqn": GUID}
    assert doc["cohort"]["name"] == "BF Set"
    assert "guid" not in doc and "obj_id" not in dump_tml(doc)
    assert doc["cohort"]["config"] == cohort_config(plan_bf_2024_2025, LBL, "order date")


def test_reusable_set_guid_at_root(plan_bf_2024_2025):
    doc = reusable_set_tml(plan_bf_2024_2025, LBL, "order date", "BF Set", MODEL, SET_GUID)
    assert list(doc) == ["guid", "cohort"] and doc["guid"] == SET_GUID


# --- formula bucket -----------------------------------------------------------

def test_formula_wraps_date_and_uses_iso(plan_bf_2024_2025):
    e = bucket_formula_expr(plan_bf_2024_2025, LBL, "order date")
    assert "date ( [order date] ) >= to_date ( '2024-11-29' , '%Y-%m-%d' )" in e
    assert "\n" not in e and e.endswith(f"else '{LBL.other}'")


def test_formula_shape_matches_probe_fixture():
    """Same plan as probe fixture answer-formula-not-in-search.answer.tml."""
    plan = build_plan(PlanSpec("black-friday", years=(2018, 2019)), T)
    fixture = FIXTURES / "answer-formula-not-in-search.answer.tml"
    want = yaml.safe_load(fixture.read_text())["answer"]["formulas"][0]["expr"]
    assert bucket_formula_expr(plan, LBL, "Order Date") == want


def test_formula_groups_event_before_comparison(plan_bf_2024_2025):
    e = bucket_formula_expr(plan_bf_2024_2025, LBL, "order date")
    assert e.startswith("if ( ( date ( [order date] ) >= to_date ( '2024-11-29'")
    assert e.count(" or ") == 1 + 11
    assert f") then '{LBL.event}' else if ( (" in e
    assert f") then '{LBL.comparison}' else '{LBL.other}'" in e


# --- measures -----------------------------------------------------------------

def test_measures_are_row_level():
    m = measure_formulas("[Bucket]", LBL, "Amount", "order date", "Black Friday")
    txt = " ".join(f["expr"] for f in m)
    assert "group_aggregate" not in txt and "safe_divide ( sum_if" in txt
    assert "unique_count_if ( [Bucket] = 'Black Friday Days' , date ( [order date] ) )" in txt
    assert m[2]["expr"] == "[formula_Average Black Friday Sales] - [formula_Average Comparison Sales]"


def test_measure_ids_and_names():
    m = measure_formulas("[Bucket]", LBL, "Amount", "order date", "Black Friday")
    assert [f["id"] for f in m] == [f"formula_{n}" for n in MEASURES]
    assert [f["name"] for f in m] == MEASURES
    assert m[1]["expr"] == (
        "safe_divide ( sum_if ( [Bucket] = '6 Prior Weeks' , [Amount] ) , "
        "unique_count_if ( [Bucket] = '6 Prior Weeks' , date ( [order date] ) ) )")


# --- Answer -------------------------------------------------------------------

def test_answer_has_no_identifiers_unless_given(plan_bf_2024_2025):
    a = _answer(plan_bf_2024_2025, "formula")
    assert "guid" not in a and "owner" not in dump_tml(a)
    assert ("[order date] between [order date].01/01/2024 and [order date].12/31/2025"
            in a["answer"]["search_query"])


def test_answer_guid_at_root(plan_bf_2024_2025):
    a = _answer(plan_bf_2024_2025, "formula", answer_guid=SET_GUID)
    assert list(a) == ["guid", "answer"] and a["guid"] == SET_GUID


def test_answer_binds_model(plan_bf_2024_2025):
    a = _answer(plan_bf_2024_2025, "reusable-set")["answer"]
    assert a["name"] == "BF"
    assert a["tables"] == [{"id": "M", "name": "M", "fqn": GUID}]


def _bucket_absent(answer, bucket_ref, bucket_name):
    """Open item #7, layout (b): the bucket is in no search, column, table or chart."""
    assert bucket_ref not in answer["search_query"]
    assert bucket_name not in [c["name"] for c in answer["answer_columns"]]
    assert bucket_name not in answer["table"]["ordered_column_ids"]
    assert bucket_name not in [c["column_id"] for c in answer["table"]["table_columns"]]
    assert bucket_name not in [c["column_id"] for c in answer["chart"]["chart_columns"]]


def test_reusable_set_answer_layout(plan_bf_2024_2025):
    a = _answer(plan_bf_2024_2025, "reusable-set", bucket_name="BF Set")["answer"]
    assert "cohorts" not in a  # open item #6: the Set is named only
    assert [f["id"] for f in a["formulas"]] == [f"formula_{n}" for n in MEASURES]
    assert "sum_if ( [BF Set] = 'Black Friday Days' , [Amount] )" in a["formulas"][0]["expr"]
    _bucket_absent(a, "[BF Set]", "BF Set")
    fixture = yaml.safe_load(
        (FIXTURES / "answer-reusable-set-not-in-search.answer.tml").read_text())["answer"]
    probe = _answer(build_plan(PlanSpec("black-friday", years=(2018, 2019)), T),
                    "reusable-set", bucket_name="ZZ_probe_period_comparison_set",
                    date_column="Order Date",
                    model=ModelRef("{model_name}", "{model_guid}"))["answer"]
    for key in ("tables", "formulas", "search_query", "answer_columns"):
        assert probe[key] == fixture[key], key


def test_formula_answer_layout(plan_bf_2024_2025):
    a = _answer(plan_bf_2024_2025, "formula", bucket_name="Period Bucket")["answer"]
    assert "cohorts" not in a
    ids = [f["id"] for f in a["formulas"]]
    assert ids == ["formula_Period Bucket"] + [f"formula_{n}" for n in MEASURES]
    assert a["formulas"][0]["name"] == "Period Bucket"
    assert a["formulas"][0]["expr"] == bucket_formula_expr(plan_bf_2024_2025, LBL, "order date")
    assert ("sum_if ( [formula_Period Bucket] = 'Black Friday Days' , [Amount] )"
            in a["formulas"][1]["expr"])
    _bucket_absent(a, "[formula_Period Bucket]", "Period Bucket")


def test_answer_search_and_columns(plan_bf_2024_2025):
    a = _answer(plan_bf_2024_2025, "formula")["answer"]
    assert a["search_query"] == (
        "[order date].yearly [formula_Average Black Friday Sales] "
        "[formula_Average Comparison Sales] [formula_Variance to Baseline] "
        "[order date] between [order date].01/01/2024 and [order date].12/31/2025")
    assert [c["name"] for c in a["answer_columns"]] == MEASURES + ["Year(order date)"]
    assert a["table"]["ordered_column_ids"] == ["Year(order date)"] + MEASURES


def test_answer_chart_from_template(plan_bf_2024_2025):
    a = _answer(plan_bf_2024_2025, "formula")["answer"]
    chart = a["chart"]
    assert a["display_mode"] == "CHART_MODE" and chart["type"] == "ADVANCED_COLUMN"
    dims = {d["key"]: d for d in chart["custom_chart_config"][0]["dimensions"]}
    assert dims["x-axis"]["axes"] == [{"type": "FLAT", "column": "Year(order date)"}]
    assert dims["y-axis"]["axes"] == [{"type": "MERGED", "columns": MEASURES}]
    assert dims["slice-with-color"]["axes"] == [{"type": "FLAT", "column": "Measure names"}]
    props = json.loads(chart["custom_visual_props"])
    bars = {k: v["bar-color"] for k, v in props["columnVisualProps"].items() if "bar-color" in v}
    assert bars == dict(zip(MEASURES, ["#F04152", "#8C62F5", "#2E75F0"]))
    merged = props["axisVisualProps"]["__".join(MEASURES)]
    assert merged["axis-name"]["name"] == "Average Daily Sales"
    assert "Year(order date)" in props["axisVisualProps"]


def test_answer_output_is_synthetic(plan_bf_2024_2025):
    """No identifier but the placeholders passed in; nothing left unfilled."""
    text = dump_tml(_answer(plan_bf_2024_2025, "reusable-set"))
    for word in ("obj_id", "owner", "guid", "Dunder", "Weekend"):
        assert word not in text
    assert not re.search(r"\{[a-z_]+\}", text)
    uuids = set(re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text))
    assert uuids == {GUID}


def test_formula_names_must_not_collide(plan_bf_2024_2025):
    with pytest.raises(PlanError):
        _answer(plan_bf_2024_2025, "formula", bucket_name="Variance to Baseline")
    with pytest.raises(PlanError):
        _answer(plan_bf_2024_2025, "formula", event_title="Comparison")


@pytest.mark.parametrize("kw", [{"date_column": "order [date]"},
                                {"measure_column": "Amount]"},
                                {"bucket_name": "Mother's Day Bucket"},
                                {"event_title": "Mother's Day"},
                                {"answer_name": " "}])
def test_unsafe_names_rejected(plan_bf_2024_2025, kw):
    with pytest.raises(PlanError):
        _answer(plan_bf_2024_2025, "formula", **kw)


def test_model_column_may_hold_a_quote(plan_bf_2024_2025):
    a = _answer(plan_bf_2024_2025, "formula", measure_column="Owner's Amount")["answer"]
    assert "[Owner's Amount]" in a["formulas"][1]["expr"]


def test_unknown_bucket_form_rejected(plan_bf_2024_2025):
    with pytest.raises(PlanError):
        _answer(plan_bf_2024_2025, "answer-level-set")


def test_unresolved_clash_refused():
    plan = build_plan(PlanSpec("boxing-day", years=(2025,)), T)
    assert plan.needs_clash_decision
    with pytest.raises(PlanError, match="clash"):
        cohort_config(plan, LBL, "order date")


# --- the condition cap --------------------------------------------------------

def test_group_cap():
    over = build_plan(PlanSpec("black-friday", years=tuple(range(1970, 2020)),
                               prior_weeks=7), T)
    assert sum(len(y.comparisons) for y in over.years) == 350
    calls = [
        lambda: cohort_config(over, LBL, "order date"),
        lambda: bucket_formula_expr(over, LBL, "order date"),
        lambda: _answer(over, "formula"),
        lambda: _answer(over, "reusable-set"),
        lambda: reusable_set_tml(over, LBL, "order date", "S", MODEL, None),
    ]
    for call in calls:
        with pytest.raises(PlanError) as exc:
            call()
        assert LBL.comparison in str(exc.value) and "300" in str(exc.value)

    exact = build_plan(PlanSpec("black-friday", years=tuple(range(1970, 2020))), T)
    assert MAX_CONDITIONS_PER_GROUP == 300
    assert sum(len(y.comparisons) for y in exact.years) == 300
    assert len(cohort_config(exact, LBL, "order date")["groups"][1]["conditions"]) == 300
    bucket_formula_expr(exact, LBL, "order date")
    _answer(exact, "formula")


# --- YAML ---------------------------------------------------------------------

def test_dump_keeps_order_and_long_lines(plan_bf_2024_2025):
    a = _answer(plan_bf_2024_2025, "formula")
    text = dump_tml(a)
    assert text.startswith("answer:\n  name: BF\n  tables:")
    expr = a["answer"]["formulas"][0]["expr"]
    assert len(expr) > 1000
    assert yaml.safe_load(text) == a
    assert sum(1 for line in text.splitlines() if "to_date" in line) == 1


def test_template_ships_as_package_data():
    """The template is read at run time, so setuptools must ship it."""
    pkg_root = Path(__file__).resolve().parents[1] / "ts_cli"
    text = (pkg_root.parent / "pyproject.toml").read_text()
    section = text.split("[tool.setuptools.package-data]", 1)[1].split("\n[", 1)[0]
    line = next(ln for ln in section.splitlines() if ln.strip().startswith('"ts_cli"'))
    globs = [g.strip().strip('"') for g in line.split("=", 1)[1].strip().strip("[]").split(",")]
    covered = {p for g in globs if g for p in pkg_root.glob(g)}
    assert pkg_root / "period_comparison/templates/answer.yaml" in covered


# --- the year filter spans the plan's years, which must be consecutive ---

def test_year_filter_spans_kept_years_only():
    plan = build_plan(PlanSpec("black-friday", years=(2023, 2024, 2025)), date(2025, 11, 30))
    assert plan.dropped_years == (2025,)
    q = _answer(plan, "formula")["answer"]["search_query"]
    assert ".01/01/2023 and" in q and ".12/31/2024" in q


def test_non_consecutive_years_refused():
    # The filter runs first..last, so a missing middle year would be a row of zeros.
    plan = build_plan(PlanSpec("black-friday", years=(2022, 2024)), T)
    for bucket in ("formula", "reusable-set"):
        with pytest.raises(PlanError, match="2023"):
            _answer(plan, bucket)


# --- a backslash is dropped from a single-quoted literal (formula_text.py) ---

@pytest.mark.parametrize("bad", ["A\\B", "Days\\"])
def test_backslash_in_label_rejected(bad):
    with pytest.raises(PlanError, match="backslash"):
        validate_labels(Labels(bad, "C", "O"))


@pytest.mark.parametrize("kw", [{"bucket_name": "BF\\Period"}, {"event_title": "BF\\X"}])
def test_backslash_in_name_rejected(plan_bf_2024_2025, kw):
    with pytest.raises(PlanError, match="backslash"):
        _answer(plan_bf_2024_2025, "reusable-set", **kw)


def test_backslash_in_set_name_rejected(plan_bf_2024_2025):
    with pytest.raises(PlanError, match="backslash"):
        reusable_set_tml(plan_bf_2024_2025, LBL, "order date", "A\\B", MODEL, None)
