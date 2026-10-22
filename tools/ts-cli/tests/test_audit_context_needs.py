"""Rule-declared data fetching (audit rule catalog, task 11).

`build_context` fetches the optional data — AI instructions, Answer TML, Set discovery —
when a selected rule `requires` it (`engine.run.needs_for`), not when a category letter
is selected. Model TML, Table TML, metadata and dependents are fetched as before.
"""
import copy
from unittest.mock import MagicMock, patch

import pytest
import yaml

from ts_cli.audit.catalog_model import build_catalog, load_catalog, load_raw
from ts_cli.audit.context import build_context
from ts_cli.audit.engine.run import needs_for

_NO_SETS = {"sets": {}, "incomplete": [], "notes": []}
_AI = "/ai/instructions/get"
_EXPORT = "/metadata/tml/export"


def _response(body):
    r = MagicMock()
    r.ok, r.status_code = True, 200
    r.json.return_value = body
    return r


class RecordingClient:
    """Model `m1` exports; its dependents lookup returns one Answer `a1`; every call is
    recorded as (url, json)."""

    def __init__(self):
        self.calls = []
        self.model = {"guid": "m1", "model": {"name": "Sales", "model_tables": [
            {"name": "ORDERS", "id": "ORDERS"}], "columns": [], "formulas": []}}
        self.answer = {"guid": "a1", "answer": {"name": "Revenue", "tables": []}}

    def post(self, url, json=None, **_kw):
        self.calls.append((url, json))
        if url.endswith(_EXPORT):
            ids = [m["identifier"] for m in json["metadata"]]
            docs = [self.answer] if ids == ["a1"] else [self.model]
            return _response([{"edoc": yaml.safe_dump(d)} for d in docs])
        if url.endswith(_AI):
            return _response({"nl_instructions_info": []})
        if url.endswith("/metadata/search") and (json or {}).get("include_dependent_objects"):
            return _response([{"metadata_id": "m1", "dependent_objects": {"dependents": {
                "m1": {"QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Revenue"}]}}}}])
        return _response([])

    def urls(self):
        return [u for u, _ in self.calls]

    def answer_exports(self):
        return [j for u, j in self.calls
                if u.endswith(_EXPORT) and [m["identifier"] for m in j["metadata"]] == ["a1"]]


def _build(needs):
    client = RecordingClient()
    with patch("ts_cli.audit.context.discover_sets", return_value=copy.deepcopy(_NO_SETS)) as disc:
        ctx = build_context(client, ["m1"], needs)
    return client, ctx, disc


def _catalog_with(edit):
    """The shipped catalog with `edit(rules_by_id)` applied to its raw YAML."""
    raw = copy.deepcopy(load_raw())
    by_id = {r["id"]: r for f, rules in raw.items() if f.startswith("rules/") for r in rules}
    edit(by_id)
    return build_catalog(raw)


# ── the fake client reaches each fetch ──────────────────────────────────────

def test_all_needs_fetch_everything():
    """Guards the fixture: with every need, the Answer export, AI lookup and Set
    discovery all happen — so their absence below is the needs, not the fake."""
    client, ctx, disc = _build(needs_for(load_catalog(), ["A", "D", "H", "P", "S"], "general"))
    assert any(u.endswith(_AI) for u in client.urls())
    assert len(client.answer_exports()) == 1 and [a["guid"] for a in ctx.answers] == ["a1"]
    disc.assert_called_once()


# ── the data follows the rules' `requires` ─────────────────────────────────

def test_needs_drive_fetch():
    client, ctx, disc = _build(needs_for(load_catalog(), ["D"], "general"))
    assert not any(u.endswith(_AI) for u in client.urls())
    assert client.answer_exports() == [] and ctx.answers == []
    disc.assert_not_called()
    # Model TML, metadata and dependents keep their unconditional fetches.
    assert [m["guid"] for m in ctx.models] == ["m1"]
    assert [d["guid"] for d in ctx.dependents["m1"]] == ["a1"]


def test_rule_moved_category_still_gets_its_data():
    def move_h7_to_d(rules):
        rules["H7"]["categories"] = ["D"]
    needs = needs_for(_catalog_with(move_h7_to_d), ["D"], "general")
    assert "answers" in needs
    client, ctx, _ = _build(needs)
    assert len(client.answer_exports()) == 1
    assert [a["guid"] for a in ctx.answers] == ["a1"]


def test_h_selection_still_discovers_sets():
    needs = needs_for(load_catalog(), ["H"], "general")
    assert "sets" in needs
    _, _, disc = _build(needs)
    disc.assert_called_once()


def test_a_selection_fetches_ai_instructions_and_no_answers():
    client, ctx, disc = _build(needs_for(load_catalog(), ["A"], "general"))
    assert [j for u, j in client.calls if u.endswith(_AI)] == [{"data_source_identifier": "m1"}]
    assert client.answer_exports() == [] and ctx.answers == []
    disc.assert_not_called()


@pytest.mark.parametrize("bad", [["H"], {"answer"}])
def test_build_context_rejects_what_is_not_a_requires_value(bad):
    """A caller still passing category letters would silently fetch nothing optional."""
    with pytest.raises(ValueError, match="unknown needs"):
        build_context(RecordingClient(), ["m1"], bad)


# ── needs_for: only rules that will run contribute ─────────────────────────

def test_needs_for_is_the_union_of_the_selected_rules_requires():
    cat = load_catalog()
    assert needs_for(cat, ["A"], "general") == {"model_tml", "ai_instructions"}
    assert needs_for(cat, ["H"], "general") == {"model_tml", "dependents", "sets", "answers"}
    assert needs_for(cat, ["P"], "general") == {"model_tml", "metadata", "table_tml"}
    assert needs_for(cat, [], "general") == set()


@pytest.mark.parametrize("profile", ["spotter", "general"])
def test_shipped_catalog_fetches_what_the_category_letters_did(profile):
    """No behaviour change today: for every one of the 31 category selections, the
    optional fetches are exactly the old `"A" in angles` / `"H" in angles` ones."""
    from itertools import combinations
    cat = load_catalog()
    for n in range(1, 6):
        for sel in combinations("ADHPS", n):
            needs = needs_for(cat, list(sel), profile)
            got = ("ai_instructions" in needs, "answers" in needs, "sets" in needs)
            assert got == ("A" in sel, "H" in sel, "H" in sel), sel


# The rules that read Set data: H5 (requires sets) and H4 (uses sets — @dependent_count
# reads ctx.dependents, which Set discovery writes into). Turning both off is what drops
# `sets` from an H selection.
_SET_READERS = ("H4", "H5")


def test_sets_are_needed_while_either_set_reader_runs():
    for rid in _SET_READERS:
        def retire_one(rules, rid=rid):
            rules[rid]["status"] = "retired"
        assert "sets" in needs_for(_catalog_with(retire_one), ["H"], "general"), rid


def test_catalog_retired_rule_contributes_nothing():
    def retire_set_readers(rules):
        for rid in _SET_READERS:
            rules[rid]["status"] = "retired"
    assert "sets" not in needs_for(_catalog_with(retire_set_readers), ["H"], "general")


def test_retired_rule_revived_by_a_layer_still_contributes_nothing():
    """Mirrors run_rules, which never runs a catalog-retired rule."""
    def retire_set_readers(rules):
        for rid in _SET_READERS:
            rules[rid]["status"] = "retired"
    cat = _catalog_with(retire_set_readers)
    revive = [{rid: {"status": "active"} for rid in _SET_READERS}]
    assert "sets" not in needs_for(cat, ["H"], "general", layers=revive)


def test_rule_disabled_under_the_profile_contributes_nothing_under_it():
    def answers_off_for_spotter(rules):
        for rid in ("H7", "H8", "H9"):
            rules[rid].setdefault("profiles", {})["spotter"] = {"status": "retired"}
    cat = _catalog_with(answers_off_for_spotter)
    assert "answers" not in needs_for(cat, ["H"], "spotter")
    assert "answers" in needs_for(cat, ["H"], "general")


def test_rule_disabled_by_a_layer_contributes_nothing():
    off = [{rid: {"status": "retired"} for rid in ("H7", "H8", "H9")}]
    assert "answers" not in needs_for(load_catalog(), ["H"], "general", layers=off)


def test_needs_for_rejects_unknown_category_and_profile():
    cat = load_catalog()
    with pytest.raises(ValueError, match="unknown categories"):
        needs_for(cat, ["X"], "general")
    with pytest.raises(ValueError, match="unknown profile"):
        needs_for(cat, ["A"], "nope")


def _a3_retired_under_spotter(rules):
    rules["A3"].setdefault("profiles", {})["spotter"] = {"status": "retired"}


def test_a5_gets_ai_instructions_when_a3_is_retired_by_a_profile():
    """A5 declares `uses: [ai_instructions]`, so its data no longer rides on A3's
    `requires`: with A3 off, an A-only selection still fetches the instructions."""
    cat = _catalog_with(_a3_retired_under_spotter)
    assert "ai_instructions" in needs_for(cat, ["A"], "spotter")
    client, _, _ = _build(needs_for(cat, ["A"], "spotter"))
    assert any(u.endswith(_AI) for u in client.urls())


def test_a5_gets_ai_instructions_when_a3_is_retired_by_a_layer():
    off = [{"A3": {"status": "retired"}}]
    assert "ai_instructions" in needs_for(load_catalog(), ["A"], "general", layers=off)


def test_with_a3_and_a5_off_nothing_needs_ai_instructions():
    off = [{"A3": {"status": "retired"}, "A5": {"status": "retired"}}]
    assert "ai_instructions" not in needs_for(load_catalog(), ["A"], "general", layers=off)


def test_a_layer_cannot_add_uses():
    """`uses` is not overridable: a layer setting it is ignored, as for `requires`."""
    layer = [{"D1": {"uses": ["answers"], "requires": ["answers"]}}]
    assert "answers" not in needs_for(load_catalog(), ["D"], "general", layers=layer)


# ── fetch order: Answers before Sets ────────────────────────────────────────

def test_set_consumers_do_not_widen_the_answer_export():
    """Set discovery writes each Set's consumers into `dependents`, which the Answer
    export walks; run after it, an Answer that uses only a Set would be exported and
    judged by H7-H9. Answers come only from the Models' and Tables' own dependents."""
    sets = {"sets": {"m1": [{"guid": "s1", "name": "B"}]}, "incomplete": [], "notes": []}
    consumers = {"dependents": [{"guid": "a9", "name": "Uses B", "type": "ANSWER"}],
                 "liveboards": {}, "unreadable": [], "other_types": [], "error": None}
    client = RecordingClient()
    with patch("ts_cli.audit.context.discover_sets", return_value=sets), \
            patch("ts_cli.audit.context.fetch_consumers", return_value=consumers):
        ctx = build_context(client, ["m1"], {"answers", "sets"})
    exported = [m["identifier"] for u, j in client.calls if u.endswith(_EXPORT)
                for m in j["metadata"]]
    assert "a9" not in exported and "a1" in exported
    assert ctx.dependents["s1"][0]["guid"] == "a9"  # the Set consumer was recorded


# ── profile handling at the two production call sites ──────────────────────

@pytest.fixture
def h5_off_for_spotter(monkeypatch):
    """The catalog every `data_needs` call loads: both Set readers (H4, H5) retired
    under spotter only."""
    import ts_cli.audit.catalog_model as cm

    def h5_off(rules):
        for rid in _SET_READERS:
            rules[rid].setdefault("profiles", {})["spotter"] = {"status": "retired"}
    cat = _catalog_with(h5_off)
    monkeypatch.setattr(cm, "load_catalog", lambda root=None: cat)


@pytest.fixture
def answers_off_for_spotter(monkeypatch):
    """The catalog every `data_needs` call loads: the Answer readers (H7, H8, H9)
    retired under spotter only."""
    import ts_cli.audit.catalog_model as cm

    def off(rules):
        for rid in ("H7", "H8", "H9"):
            rules[rid].setdefault("profiles", {})["spotter"] = {"status": "retired"}
    cat = _catalog_with(off)
    monkeypatch.setattr(cm, "load_catalog", lambda root=None: cat)


# Task 12a: this observed Set discovery (H4/H5 off under spotter). Since the cut-over
# `ts audit run` always fetches the report's own data (audit.REPORT_NEEDS, which
# includes sets), so Set discovery no longer depends on the profile; the same property
# — run_audit fetches for ITS profile only — is held through the Answer export, which
# only rules read.
@pytest.mark.parametrize("assessment,exports", [("spotter", False), ("general", True)])
def test_run_audit_fetches_for_its_own_profile_only(answers_off_for_spotter, assessment,
                                                    exports):
    from ts_cli.audit import run_audit
    client = RecordingClient()
    with patch("ts_cli.audit.context.discover_sets", return_value=copy.deepcopy(_NO_SETS)):
        run_audit(client, ["m1"], ["H"], assessment)
    assert bool(client.answer_exports()) is exports


def test_snapshot_capture_fetches_for_every_profile(h5_off_for_spotter, tmp_path):
    """A snapshot may be replayed under the other --assessment, so a spotter capture
    still holds the Sets general's H4/H5 read."""
    from ts_cli.commands.audit import _capture
    with patch("ts_cli.audit.context.discover_sets", return_value=copy.deepcopy(_NO_SETS)) as disc:
        _capture(RecordingClient(), ["m1"], ["H"], "spotter", tmp_path / "snap")
    disc.assert_called_once()


# ── run_audit selects by the catalog ────────────────────────────────────────

# Task 12a: was `..._makes_no_ai_or_answer_calls` (no AI call, no Set discovery). The
# report now declares its own needs (audit.REPORT_NEEDS: AI instructions for the
# Model questions/ERD, Sets for the consumers panel), fetched whatever the rules need,
# so a D-only run makes those two calls; it still exports no Answers, which only rules
# read.
def test_run_audit_d_only_makes_no_answer_calls_but_fetches_the_reports_data():
    from ts_cli.audit import run_audit
    client = RecordingClient()
    with patch("ts_cli.audit.context.discover_sets", return_value=copy.deepcopy(_NO_SETS)) as disc:
        run_audit(client, ["m1"], ["D"])
    assert client.answer_exports() == []
    assert any(u.endswith(_AI) for u in client.urls())
    disc.assert_called_once()


def test_run_audit_ignores_an_unknown_angle_as_before():
    from ts_cli.audit import run_audit
    client = RecordingClient()
    with patch("ts_cli.audit.context.discover_sets", return_value=copy.deepcopy(_NO_SETS)):
        out = run_audit(client, ["m1"], ["A", "X"])
    assert out["corpus"]["angles_run"] == ["A", "X"]
    assert any(u.endswith(_AI) for u in client.urls())
