"""live_run / teardown_ts against fakes: cleanup and outputs survive SystemExit and Ctrl-C
at every step, and deletion only ever targets objects this run provably created."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tools" / "ts-cli"))

import run as runmod  # noqa: E402
from fidelity import cases as caselib  # noqa: E402
from fidelity import live  # noqa: E402

CASES = HERE / "cases" / "snowflake" / "m0.jsonl"
START_MS = 1_000_000


class Boom:
    """Raise ``exc`` the ``nth`` time step ``name`` is reached."""

    def __init__(self, name=None, exc=None, nth=1):
        self.name, self.exc, self.nth, self.seen = name, exc, nth, {}

    def step(self, name):
        self.seen[name] = self.seen.get(name, 0) + 1
        if name == self.name and self.seen[name] == self.nth:
            raise self.exc


class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class FakeTS:
    """Objects keyed by GUID: {guid: (name, created_ms)}."""

    def __init__(self, boom, preexisting=None):
        self.boom = boom
        self.objects = dict(preexisting or {})
        self.deleted: list[str] = []
        self.client = self
        self._n = 0
        self.now = START_MS + 10

    # client.post — only metadata search is used directly
    def post(self, path, json=None, **kw):
        self.boom.step("search")
        pat = json["metadata"][0].get("name_pattern", "")
        exact = None if "%" in pat else pat
        rows = [{"metadata_id": g, "metadata_name": n, "metadata_header": {"created": c}}
                for g, (n, c) in self.objects.items()
                if (exact is None and n.startswith("ZZ_FIDELITY_")) or n == exact]
        return _Resp(rows)

    def _import(self, doc, policy, create_new):
        kind = "model" if "model" in doc else "table"
        self.boom.step(f"import_{kind}")
        self._n += 1
        g = f"guid-{kind}-{self._n}"
        self.objects[g] = (doc[kind]["name"], self.now)
        return g, None

    def validate_only(self, doc):
        self.boom.step("validate_only")
        return None

    def find_by_name(self, name):
        return [g for g, (n, _) in self.objects.items() if n == name]

    def delete(self, guid):
        self.boom.step("delete")
        self.objects.pop(guid, None)
        self.deleted.append(guid)
        return "deleted"

    def exists(self, guid):
        self.boom.step("exists")
        return guid in self.objects

    def agentql(self, kind, stmt, guid):
        self.boom.step("agentql")
        return {"status": "SUCCESS", "errors": [], "executable_sql": "SELECT 1",
                "columns": [{"type": "INT64"}, {"type": "DOUBLE"}], "rows": [[1, 1.0]]}


class FakeWH:
    def __init__(self, boom):
        self.boom = boom
        self.tables: set[str] = set()
        self.closed = False

    def execute(self, sql):
        if sql.startswith("SHOW TABLES"):
            self.boom.step("wh_show")
            return [("2026-01-01", t.split(".")[-1]) for t in self.tables]
        if sql.startswith("CREATE TABLE"):
            self.boom.step("wh_create")
            self.tables.add(sql.split()[2])
        elif sql.startswith("DROP TABLE"):
            self.boom.step("wh_drop")
            self.tables.discard(sql.split()[-1])
        elif sql.startswith("INSERT"):
            self.boom.step("wh_insert")
        else:
            self.boom.step("wh_session")
        return []

    def keyed(self, sql):
        self.boom.step("oracle")
        return {"1": {"t": "num", "v": "1"}}

    def table_exists(self, database, schema, table):
        self.boom.step("wh_exists")
        return f"{database}.{schema}.{table}" in self.tables

    def close(self):
        self.closed = True


def _args(tmp_path):
    return argparse.Namespace(
        cases=CASES, profile="p", sf_profile="s", connection="C", database="AGENT_SKILLS",
        schema="PUBLIC", out=tmp_path / "run.json", report=tmp_path / "report.md",
        fill_expected=False)


def _go(tmp_path, boom, ts=None):
    cases = caselib.load_cases(CASES)
    fixtures = caselib.fixtures_for(cases, CASES.parent)
    ts = ts or FakeTS(boom)
    wh = FakeWH(boom)
    deps = runmod.Deps(validator=lambda p: (boom.step("validator"), ts)[1],
                       warehouse=lambda kind, s: (boom.step("warehouse"), wh)[1],
                       now_ms=lambda: START_MS)
    return cases, ts, wh, deps, fixtures


def test_clean_run_exits_zero_and_leaves_nothing(tmp_path):
    boom = Boom()
    cases, ts, wh, deps, fx = _go(tmp_path, boom)
    rc = runmod.live_run(_args(tmp_path), cases, fx, "T", deps)
    assert rc == runmod.EXIT_OK
    assert ts.objects == {} and wh.tables == set() and wh.closed
    meta = json.loads((tmp_path / "run.json").read_text())["run"]
    assert meta["cleanup"]["ts_confirmed_absent"] and meta["cleanup"]["warehouse_confirmed_absent"]
    assert (tmp_path / "report.md").exists()


BODY_STEPS = ["validator", "search", "warehouse", "wh_show", "wh_session", "wh_create",
              "wh_insert", "oracle", "import_table", "validate_only", "import_model", "agentql"]


@pytest.mark.parametrize("step", BODY_STEPS)
@pytest.mark.parametrize("exc", [SystemExit(1), KeyboardInterrupt()])
def test_interrupt_in_body_cleans_up_writes_and_reraises(tmp_path, step, exc):
    boom = Boom(step, exc)
    cases, ts, wh, deps, fx = _go(tmp_path, boom)
    with pytest.raises(type(exc)):
        runmod.live_run(_args(tmp_path), cases, fx, "T", deps)
    assert ts.objects == {}, f"ThoughtSpot objects left after {step}"
    assert wh.tables == set(), f"warehouse table left after {step}"
    run = json.loads((tmp_path / "run.json").read_text())
    assert run["run"]["aborted"].startswith(type(exc).__name__)
    assert "ABORTED" in (tmp_path / "report.md").read_text()


@pytest.mark.parametrize("step", ["import_table", "agentql", "validate_only", "wh_create"])
def test_ordinary_exception_aborts_with_exit_3(tmp_path, step):
    boom = Boom(step, RuntimeError("nope"))
    cases, ts, wh, deps, fx = _go(tmp_path, boom)
    assert runmod.live_run(_args(tmp_path), cases, fx, "T", deps) == runmod.EXIT_ABORTED
    assert ts.objects == {} and wh.tables == set()


TEARDOWN_STEPS = [("search", 3), ("delete", 1), ("exists", 1), ("delete", 2), ("wh_drop", 1),
                  ("wh_exists", 1)]


@pytest.mark.parametrize("step,nth", TEARDOWN_STEPS)
@pytest.mark.parametrize("exc", [SystemExit(1), KeyboardInterrupt()])
def test_interrupt_in_teardown_still_runs_the_other_blocks(tmp_path, step, nth, exc):
    boom = Boom(step, exc, nth)
    cases, ts, wh, deps, fx = _go(tmp_path, boom)
    with pytest.raises(type(exc)):
        runmod.live_run(_args(tmp_path), cases, fx, "T", deps)
    meta = json.loads((tmp_path / "run.json").read_text())["run"]
    cl = meta["cleanup"]
    if step.startswith("wh_"):
        assert ts.objects == {}                 # ThoughtSpot block ran first, unaffected
        assert not cl["warehouse_confirmed_absent"]
    else:
        assert wh.tables == set()               # warehouse block ran despite the TS failure
        assert cl["warehouse_confirmed_absent"]
        assert not cl["ts_confirmed_absent"]
        assert all(r.get("name") for r in cl["remaining"])   # recorded by name (and GUID)
    assert cl["errors"]


def test_leftover_exits_1(tmp_path):
    boom = Boom()
    cases, ts, wh, deps, fx = _go(tmp_path, boom)
    ts.delete = lambda g: "error: refused"      # delete silently does nothing
    assert runmod.live_run(_args(tmp_path), cases, fx, "T", deps) == runmod.EXIT_LEFTOVERS
    meta = json.loads((tmp_path / "run.json").read_text())["run"]
    assert {r["guid"] for r in meta["cleanup"]["remaining"]} == set(ts.objects)


def test_fill_expected_skipped_on_abort(tmp_path):
    copy = tmp_path / "m0.jsonl"
    copy.write_text(CASES.read_text())
    (tmp_path / "fixture-m0.json").write_text((CASES.parent / "fixture-m0.json").read_text())
    boom = Boom("agentql", RuntimeError("x"))
    cases, ts, wh, deps, fx = _go(tmp_path, boom)
    args = _args(tmp_path)
    args.cases, args.fill_expected = copy, True
    before = copy.read_text()
    assert runmod.live_run(args, cases, fx, "T", deps) == runmod.EXIT_ABORTED
    assert copy.read_text() == before


# -- ownership rules -------------------------------------------------------------------

def test_teardown_deletes_recorded_guid_and_reports_other_name_matches():
    ts = FakeTS(Boom(), {"mine": ("ZZ_M", START_MS + 5), "old": ("ZZ_M", START_MS - 5),
                         "new-twin": ("ZZ_M", START_MS + 7)})
    res = live.teardown_ts(ts, [("ZZ_M", "mine")], START_MS)
    assert ts.deleted == ["mine"]                       # name matches never deleted here
    assert {r["guid"] for r in res["not_owned"]} == {"old", "new-twin"}
    assert res["ts_confirmed_absent"]


def test_teardown_without_recorded_guid_deletes_only_objects_created_after_start():
    ts = FakeTS(Boom(), {"old": ("ZZ_M", START_MS - 1), "new": ("ZZ_M", START_MS),
                         "untimed": ("ZZ_M", None)})
    res = live.teardown_ts(ts, [("ZZ_M", None)], START_MS)
    assert ts.deleted == ["new"]
    assert {r["guid"] for r in res["not_owned"]} == {"old", "untimed"}


def test_teardown_records_interrupt_and_continues():
    boom = Boom("delete", KeyboardInterrupt(), 1)
    ts = FakeTS(boom, {"m": ("ZZ_M", START_MS), "t": ("ZZ_T", START_MS)})
    res = live.teardown_ts(ts, [("ZZ_M", "m"), ("ZZ_T", "t")], START_MS)
    assert isinstance(res["interrupted"], KeyboardInterrupt)
    assert ts.deleted == ["t"]                          # the second object still went
    assert res["remaining"] == [{"name": "ZZ_M", "guid": "m", "unconfirmed": True}]
