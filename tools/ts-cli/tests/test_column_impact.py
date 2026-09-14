"""Tests for ts_cli/column_impact.py pure functions."""
import pytest

from ts_cli.column_impact import (
    BUCKET_LABELS,
    SUBTYPE_LABELS,
    apply_subtype_labels,
    build_impact_summary,
    collect_affected_lb_ans_guids,
    find_broken_formulas,
    find_broken_rls,
    parse_dependents,
)


# ── parse_dependents ────────────────────────────────────────────────────────

def test_parse_dependents_empty():
    result, inacc = parse_dependents({})
    assert result == []
    assert inacc is False


def test_parse_dependents_flattens_buckets():
    raw = {
        "dependents": {
            "col_guid_1": {
                "QUESTION_ANSWER_BOOK": [
                    {"id": "ans-1", "name": "My Answer"},
                ],
                "PINBOARD_ANSWER_BOOK": [
                    {"id": "lb-1", "name": "My Liveboard"},
                ],
            }
        },
        "hasInaccessibleDependents": False,
    }
    deps, inacc = parse_dependents(raw)
    types = {d["type"] for d in deps}
    assert types == {"ANSWER", "LIVEBOARD"}
    assert len(deps) == 2
    assert inacc is False


def test_parse_dependents_inaccessible_flag():
    raw = {
        "dependents": {},
        "hasInaccessibleDependents": True,
    }
    _, inacc = parse_dependents(raw)
    assert inacc is True


# ── apply_subtype_labels ────────────────────────────────────────────────────

def test_apply_subtype_labels_worksheet():
    dep_list = [{"guid": "g1", "name": "WS1", "type": "LOGICAL_TABLE", "raw_type": "LOGICAL_TABLE"}]
    subtype_map = {"g1": "WORKSHEET"}
    result = apply_subtype_labels(dep_list, subtype_map)
    assert result[0]["type"] == "WORKSHEET"


def test_apply_subtype_labels_non_lt_unchanged():
    dep_list = [{"guid": "a1", "name": "Ans1", "type": "ANSWER", "raw_type": "QUESTION_ANSWER_BOOK"}]
    result = apply_subtype_labels(dep_list, {})
    assert result[0]["type"] == "ANSWER"


def test_apply_subtype_labels_does_not_mutate_input():
    original = [{"guid": "g1", "name": "T1", "type": "LOGICAL_TABLE", "raw_type": "LOGICAL_TABLE"}]
    apply_subtype_labels(original, {"g1": "ONE_TO_ONE_LOGICAL"})
    assert original[0]["type"] == "LOGICAL_TABLE"


# ── find_broken_formulas ────────────────────────────────────────────────────

def test_find_broken_formulas_match():
    formulas = [
        {"id": "f1", "name": "Revenue", "expr": "sum(revenue)"},
        {"id": "f2", "name": "Cost",    "expr": "sum(cost)"},
    ]
    result = find_broken_formulas(formulas, "revenue")
    assert len(result) == 1
    assert result[0]["id"] == "f1"


def test_find_broken_formulas_case_insensitive():
    formulas = [{"id": "f1", "name": "X", "expr": "if_null(REVENUE, 0)"}]
    assert find_broken_formulas(formulas, "revenue") == formulas


def test_find_broken_formulas_no_match():
    formulas = [{"id": "f1", "name": "X", "expr": "sum(cost)"}]
    assert find_broken_formulas(formulas, "revenue") == []


# ── find_broken_rls ─────────────────────────────────────────────────────────

def test_find_broken_rls_rule_match():
    rules = [
        {"name": "r1", "expr": "ts_username = [TABLE::FIRST_NAME]"},
        {"name": "r2", "expr": "ts_username = [TABLE::LAST_NAME]"},
    ]
    paths = []
    broken_rules, broken_paths = find_broken_rls(rules, paths, "FIRST_NAME")
    assert len(broken_rules) == 1
    assert broken_rules[0][1]["name"] == "r1"
    assert broken_paths == []


def test_find_broken_rls_path_match():
    rules = []
    paths = [
        {"id": "P1", "table": "MY_TABLE", "column": ["FIRST_NAME", "LAST_NAME"]},
        {"id": "P2", "table": "MY_TABLE", "column": ["LAST_NAME"]},
    ]
    _, broken_paths = find_broken_rls(rules, paths, "FIRST_NAME")
    assert len(broken_paths) == 1
    assert broken_paths[0]["id"] == "P1"


# ── collect_affected_lb_ans_guids ───────────────────────────────────────────

def test_collect_affected_lb_ans_guids():
    dep_lists = [
        [
            {"guid": "lb-1", "raw_type": "PINBOARD_ANSWER_BOOK"},
            {"guid": "ans-1", "raw_type": "QUESTION_ANSWER_BOOK"},
        ],
        [
            {"guid": "lb-2", "raw_type": "PINBOARD_ANSWER_BOOK"},
            {"guid": "lb-1", "raw_type": "PINBOARD_ANSWER_BOOK"},  # duplicate
        ],
    ]
    lb_guids, ans_guids = collect_affected_lb_ans_guids(dep_lists)
    assert lb_guids == {"lb-1", "lb-2"}
    assert ans_guids == {"ans-1"}


def test_collect_affected_empty():
    lb, ans = collect_affected_lb_ans_guids([])
    assert lb == set()
    assert ans == set()


# ── build_impact_summary ────────────────────────────────────────────────────

def _make_dep(guid: str, raw_type: str) -> dict:
    labels = {"PINBOARD_ANSWER_BOOK": "LIVEBOARD", "QUESTION_ANSWER_BOOK": "ANSWER"}
    return {"guid": guid, "name": f"obj-{guid}", "type": labels.get(raw_type, raw_type), "raw_type": raw_type}


def test_build_impact_summary_counts_unique_objects():
    pass1 = [_make_dep("lb-1", "PINBOARD_ANSWER_BOOK")]
    pass4 = [_make_dep("lb-1", "PINBOARD_ANSWER_BOOK"), _make_dep("ans-1", "QUESTION_ANSWER_BOOK")]

    summary = build_impact_summary(
        column_name="Revenue",
        physical_col="REVENUE",
        pass1_deps=pass1,
        formula_dep_results=[],
        pass4_deps=pass4,
        sv_downstream=[],
        broken_formulas=[],
        col_security_rules=[],
        broken_rls=[],
        broken_paths=[],
        broken_vars=[],
        broken_terms=[],
        affected_actions=[],
        broken_views=[],
        broken_cohorts=[],
        broken_schedules=[],
        broken_alerts=[],
        any_inaccessible=False,
    )

    # lb-1 appears in both passes — unique count is 2 (lb-1 + ans-1)
    assert summary["unique_affected_objects"] == 2
    assert summary["column_name"] == "Revenue"
    assert summary["physical_col"] == "REVENUE"
    assert summary["has_inaccessible_dependents"] is False
    assert "personalized_liveboard_views" in summary["not_checked"]


def test_build_impact_summary_formula_dep_counted():
    formula_deps = [_make_dep("ans-2", "QUESTION_ANSWER_BOOK")]
    summary = build_impact_summary(
        column_name="Rev",
        physical_col="REV",
        pass1_deps=[],
        formula_dep_results=[("FormulaX", "fg-1", formula_deps, False)],
        pass4_deps=[],
        sv_downstream=[],
        broken_formulas=[{"id": "fg-1", "name": "FormulaX", "expr": "sum(REV)"}],
        col_security_rules=[],
        broken_rls=[],
        broken_paths=[],
        broken_vars=[],
        broken_terms=[],
        affected_actions=[],
        broken_views=[],
        broken_cohorts=[],
        broken_schedules=[],
        broken_alerts=[],
        any_inaccessible=False,
    )
    assert summary["unique_affected_objects"] == 1
    assert len(summary["broken_formulas"]) == 1
    assert summary["objects"][0]["via"] == "via formula 'FormulaX'"


# ── _find_col_guid pagination ───────────────────────────────────────────────

class _FakeClient:
    """Records the record_offset of every metadata/search page requested."""

    def __init__(self, pages):
        self.pages = pages
        self.offsets = []

    def request(self, method, path, json=None, **kw):   # noqa: A002 - mirrors ThoughtSpotClient
        offset = (json or {}).get("record_offset", 0)
        self.offsets.append(offset)

        class _R:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        idx = offset // 50
        return _R(self.pages[idx] if idx < len(self.pages) else [])


def _col(owner):
    return {"metadata_id": f"guid-of-{owner}", "metadata_header": {"owner": owner}}


def test_find_col_guid_finds_a_match_on_a_later_page():
    """Regression: a single 50-record page silently returned None for a common
    column name, which `ts columns impact` reads as 'no dependents, safe to
    delete'. The owner filter is applied in memory, so the match can sit past
    the first page."""
    from ts_cli.commands.columns import _find_col_guid

    page1 = [_col(f"other-{i}") for i in range(50)]
    page2 = [_col("other-x"), _col("WANTED")]
    client = _FakeClient([page1, page2])

    assert _find_col_guid(client, "CUSTOMER_ID", "WANTED") == "guid-of-WANTED"
    assert client.offsets == [0, 50], "should have requested exactly two pages"


def test_find_col_guid_stops_on_a_short_page():
    """A page shorter than the page size is the last one — do not keep asking."""
    from ts_cli.commands.columns import _find_col_guid

    client = _FakeClient([[_col("someone-else")]])
    assert _find_col_guid(client, "AMOUNT", "NOBODY") is None
    assert client.offsets == [0]


def test_find_col_guid_returns_none_when_exhausted():
    from ts_cli.commands.columns import _find_col_guid

    client = _FakeClient([[_col(f"o{i}") for i in range(50)], []])
    assert _find_col_guid(client, "AMOUNT", "NOBODY") is None
    assert client.offsets == [0, 50]
